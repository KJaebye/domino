#!/usr/bin/env python3
"""Local multi-channel publishing, with optional read-only installation checks.

Credentials stay in macOS Keychain and a restricted directory outside the
repository. Never reads repository token files, initializes Domino, creates
repositories, uploads private keys, or generates production keys.
"""
import argparse
import ast
import base64
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from scripts import build_distribution as distribution, prepare_channels, verify_artifacts
except ModuleNotFoundError:
    import build_distribution as distribution
    import prepare_channels
    import verify_artifacts

VERSION = r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)'
PROJECT = 'domino-proxy'


def version(value):
    if not re.fullmatch(VERSION, value):
        raise ValueError('Version must use X.Y.Z, without a v prefix')
    return value


def version_tuple(value):
    return tuple(map(int, version(value).split('.')))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def outputs(**values):
    path = os.environ.get('GITHUB_OUTPUT')
    if path:
        with open(path, 'a') as stream:
            for key, value in values.items():
                value = str(value).lower() if isinstance(value, bool) else str(value)
                if '\n' in value or '\r' in value:
                    raise ValueError('Invalid workflow output')
                stream.write(f'{key}={value}\n')


def fetch(url, *, missing=False, authenticated=False, limit=32 * 1024 * 1024):
    headers = {'User-Agent': 'domino-release', 'Accept': 'application/vnd.github+json' if authenticated else '*/*'}
    github_token = os.environ.get('GH_TOKEN') or os.environ.get('GH_API_TOKEN')
    if authenticated and github_token:
        if not url.startswith('https://api.github.com/'):
            raise ValueError('Credentials are restricted to the GitHub API')
        headers['Authorization'] = 'Bearer ' + github_token
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                if prepare_channels.urlsplit(response.url).scheme != 'https':
                    raise RuntimeError('Public endpoint redirected outside HTTPS')
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('Public release file exceeds size limit')
                return data
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 3:
                raise RuntimeError(f'Public endpoint returned HTTP {error.code}') from None
        except URLError:
            if attempt == 3:
                raise RuntimeError('Public endpoint could not be reached') from None
        time.sleep(2 ** attempt)


def api(path, *, missing=False, data=None, method=None):
    if os.environ.get('RELEASE_LOCAL_API') == '1':
        args = ['gh', 'api', path]
        if data is not None:
            args += ['--method', method or 'POST', '--input', '-']
        result = subprocess.run(args, input=json.dumps(data).encode() if data is not None else None,
                                capture_output=True, timeout=60)
        if result.returncode:
            try:
                problem = json.loads(result.stdout)
            except ValueError:
                problem = {}
            if missing and problem.get('status') == '404':
                return None
            raise RuntimeError('GitHub API request failed: ' + path)
        return json.loads(result.stdout)
    if data is not None:
        raise ValueError('GitHub writes run locally through the existing gh login')
    data = fetch('https://api.github.com/' + path, authenticated=True, missing=missing)
    return json.loads(data) if data is not None else None


def resolve(work, repo, requested, tap_repo=None, apt_url=None, apt_repo=None):
    requested = version(requested)
    repo = prepare_channels.repository_name(repo)
    tap_repo = prepare_channels.repository_name(tap_repo or repo.split('/')[0] + '/homebrew-tap')
    if not tap_repo.split('/')[1].startswith('homebrew-'):
        raise ValueError('Tap repository name must start with homebrew-')
    owner, name = repo.split('/')
    apt_repo = prepare_channels.repository_name(apt_repo or owner + '/domino-apt')
    apt_url = apt_url or f'https://raw.githubusercontent.com/{apt_repo}/main/'
    # Use the same validation as channel generation without touching an output.
    parsed = prepare_channels.urlsplit(apt_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in apt_url)):
        raise ValueError('APT URL must be a public HTTPS directory')
    ref = api(f'repos/{repo}/git/ref/tags/v{requested}')['object']
    for _ in range(5):
        if ref['type'] == 'commit':
            break
        if ref['type'] != 'tag':
            raise ValueError('Release tag does not resolve to a commit')
        ref = api(f'repos/{repo}/git/tags/{ref["sha"]}')['object']
    if ref['type'] != 'commit' or not re.fullmatch('[a-f0-9]{40}', ref['sha']):
        raise ValueError('Release tag does not resolve to a commit')
    existing = api(f'repos/{repo}/releases/tags/v{requested}', missing=True)
    if existing and (existing['draft'] or existing['prerelease']):
        raise ValueError('Resume only published stable releases; inspect the draft first')
    plan = {'schema': 1, 'version': requested, 'repository': repo, 'source_sha': ref['sha'],
            'tap_repository': tap_repo, 'apt_repository': apt_repo, 'apt_url': apt_url.rstrip('/') + '/',
            'existing_release': existing is not None, 'assets': existing['assets'] if existing else []}
    work.mkdir(parents=True, exist_ok=False)
    write_json(work / 'plan.json', plan)
    outputs(version=requested, source_sha=ref['sha'], existing_release=existing is not None)
    return plan


def plan_at(work):
    return json.loads((work / 'plan.json').read_text())


def checksums(path):
    result = {}
    for line in path.read_text().splitlines():
        digest, name = line.split('  ')
        if (not re.fullmatch('[a-f0-9]{64}', digest) or Path(name).name != name or name in result):
            raise ValueError('Invalid package checksum manifest')
        result[name] = digest
    return result


def pypi_files(work):
    plan = plan_at(work)
    release = work / 'release'
    expected = {f'domino_proxy-{plan["version"]}-py3-none-any.whl', f'domino_proxy-{plan["version"]}.tar.gz'}
    sums = checksums(release / 'PYPI-SHA256SUMS')
    if set(sums) != expected:
        raise ValueError('PyPI manifest must contain exactly this version wheel and sdist')
    for name, digest in sums.items():
        if hashlib.sha256((release / name).read_bytes()).hexdigest() != digest:
            raise ValueError('PyPI package checksum mismatch: ' + name)
    manifest, _ = distribution.load_runtime(release)
    if manifest['version'] != plan['version']:
        raise ValueError('Artifact version differs from release plan')
    return sums


def prepare(work, source, candidate=None, existing_deb=None):
    plan = plan_at(work)
    requested = plan['version']
    actual_sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual_sha != plan['source_sha']:
        raise ValueError('Source checkout differs from release tag')
    tree = ast.parse((source / 'src/domino_cli.py').read_text())
    declared = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets))
    if declared != requested:
        raise ValueError('Tag and CLI version differ')
    release = work / 'release'
    candidate_review = None
    if candidate is not None:
        try:
            from scripts import candidate_release
        except ModuleNotFoundError:
            import candidate_release
        candidate_review = candidate_release.review(candidate, source)
        if not candidate_review['eligible_for_release_preparation']:
            raise ValueError('; '.join(candidate_review['blockers']))
        original = candidate / 'output/dist/release'
        existing_deb = candidate / f'output/dist/distribution/domino-proxy_{requested}-1_all.deb'
        if plan['existing_release']:
            # Channel recovery always takes the official bytes as its source of
            # truth. The same reviewed candidate may corroborate them; it can
            # never replace them or introduce a different same-version build.
            recovered = prepare(work, source, existing_deb=existing_deb)
            for path in original.iterdir():
                published = release / path.name
                if not published.is_file() or hashlib.sha256(published.read_bytes()).hexdigest() != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise ValueError('Published original differs from the reviewed candidate: ' + path.name)
            sdist = f'domino_proxy-{requested}.tar.gz'
            if hashlib.sha256((release / sdist).read_bytes()).hexdigest() != candidate_review['source_distribution_sha256']:
                raise ValueError('Published source distribution differs from the reviewed candidate')
            deb = work / f'channels/distribution/domino-proxy_{requested}-1_all.deb'
            if hashlib.sha256(deb.read_bytes()).hexdigest() != candidate_review['deb_sha256']:
                raise ValueError('Recovered APT package differs from the original CI candidate')
            recovered['ci_candidate'] = candidate_review
            write_json(work / 'plan.json', recovered)
            return recovered
        allowed = {f'domino-runtime-{requested}.tar.gz', f'domino_proxy-{requested}-py3-none-any.whl',
                   'release.json', 'SHA256SUMS', 'domino.rb', 'domino.rb.in'}
        if {path.name for path in original.iterdir()} - allowed:
            raise ValueError('Unexpected files in candidate release directory')
        shutil.copytree(original, release)
        sdist = f'domino_proxy-{requested}.tar.gz'
        shutil.copyfile(candidate / 'output/dist/pypi' / sdist, release / sdist)
        names = [f'domino_proxy-{requested}-py3-none-any.whl', sdist]
        (release / 'PYPI-SHA256SUMS').write_text(''.join(
            hashlib.sha256((release / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in names))
    elif plan['existing_release']:
        release.mkdir()
        allowed = {f'domino-runtime-{requested}.tar.gz', f'domino_proxy-{requested}-py3-none-any.whl',
                   f'domino_proxy-{requested}.tar.gz', 'release.json', 'SHA256SUMS', 'PYPI-SHA256SUMS',
                   'domino.rb', 'domino.rb.in'}
        for asset in plan['assets']:
            if asset['name'] not in allowed:
                continue
            url = f'https://github.com/{plan["repository"]}/releases/download/v{requested}/' + asset['name']
            data = fetch(url)
            if asset.get('digest') != 'sha256:' + hashlib.sha256(data).hexdigest():
                raise ValueError('GitHub asset digest is missing or differs: ' + asset['name'])
            (release / asset['name']).write_bytes(data)
    else:
        subprocess.run([sys.executable, str(source / 'scripts/build_release.py'), '--output', str(release.resolve())], check=True)
        subprocess.run([sys.executable, '-m', 'build', '--sdist', '--outdir', str(release.resolve()), str(source)], check=True)
        names = [f'domino_proxy-{requested}-py3-none-any.whl', f'domino_proxy-{requested}.tar.gz']
        (release / 'PYPI-SHA256SUMS').write_text(''.join(
            hashlib.sha256((release / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in names))
    # Original source and all package bytes, including the sdist, remain fixed on retries.
    sums = pypi_files(work)
    original_root = verify_artifacts.ROOT
    try:
        verify_artifacts.ROOT = source.resolve()
        report = verify_artifacts.verify(release)
    finally:
        verify_artifacts.ROOT = original_root
    write_json(work / 'artifact-verification.json', report)
    subprocess.run([sys.executable, '-m', 'twine', 'check', *[str(release / name) for name in sorted(sums)]], check=True)
    channels = prepare_channels.prepare(release, work / 'channels', release_repo=plan['repository'],
        tap_repo=plan['tap_repository'], apt_repo=plan['repository'], apt_url=plan['apt_url'],
        existing_deb=existing_deb)
    if candidate_review is not None:
        deb = work / f'channels/distribution/domino-proxy_{requested}-1_all.deb'
        if hashlib.sha256(deb.read_bytes()).hexdigest() != candidate_review['deb_sha256']:
            raise ValueError('Local APT package differs from the original CI candidate bytes')
        plan['ci_candidate'] = candidate_review
    plan.update(pypi_files=sums, files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(release.iterdir()) if p.is_file()},
                deb=channels['version'] + '-1')
    write_json(work / 'plan.json', plan)
    return plan


def validate_inputs(work):
    plan = plan_at(work)
    for name, digest in plan['files'].items():
        if Path(name).name != name or hashlib.sha256((work / 'release' / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Prepared release inputs changed')
    pypi_files(work)
    report = json.loads((work / 'channels/channels.json').read_text())
    if report['version'] != plan['version']:
        raise ValueError('Channel materials have a different version')
    for name, digest in report['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or hashlib.sha256((work / 'channels' / path).read_bytes()).hexdigest() != digest:
            raise ValueError('Prepared channel materials changed')
    return plan


def publish_github(work):
    plan = validate_inputs(work)
    # A draft makes incomplete uploads visible without announcing them as a release.
    tag = 'v' + plan['version']
    common = ['--repo', plan['repository']]
    existing = api(f'repos/{plan["repository"]}/releases/tags/{tag}', missing=True)
    remote = {item['name']: item.get('digest') for item in existing['assets']} if existing else {}
    for name, digest in plan['files'].items():
        if name in remote and remote[name] != 'sha256:' + digest:
            raise ValueError('Existing GitHub release file conflicts: ' + name)
    missing = [name for name in plan['files'] if name not in remote]
    if existing and not existing['draft']:
        if missing:
            raise ValueError('Published GitHub release has missing original assets')
        return
    if not existing:
        subprocess.run(['gh', 'release', 'create', tag, *common, '--verify-tag', '--draft',
                        '--title', tag, '--generate-notes'], check=True)
    if missing:
        subprocess.run(['gh', 'release', 'upload', tag, *common,
                        *[str(work / 'release' / name) for name in missing]], check=True)
    uploaded = api(f'repos/{plan["repository"]}/releases/tags/{tag}')
    remote = {item['name']: item.get('digest') for item in uploaded['assets']}
    if any(remote.get(name) != 'sha256:' + digest for name, digest in plan['files'].items()):
        raise ValueError('Uploaded release checksums differ; draft retained for inspection')
    subprocess.run(['gh', 'release', 'edit', tag, *common, '--draft=false'], check=True)


def pypi_missing(work):
    plan = validate_inputs(work)
    data = fetch(f'https://pypi.org/pypi/{PROJECT}/{plan["version"]}/json', missing=True)
    remote = {item['filename']: item for item in json.loads(data)['urls']} if data is not None else {}
    missing = []
    for name, digest in plan['pypi_files'].items():
        if name not in remote:
            missing.append(name)
        elif remote[name]['digests']['sha256'] != digest or remote[name].get('yanked'):
            raise ValueError('Existing PyPI file conflicts or is yanked: ' + name)
    return missing


def stage_pypi(work):
    missing = pypi_missing(work)
    upload = work / 'pypi-upload'
    upload.mkdir(exist_ok=False)
    for name in missing:
        shutil.copyfile(work / 'release' / name, upload / name)
    outputs(needed=bool(missing))
    return missing


def verify_pypi(work, install=False):
    for attempt in range(6):
        if not pypi_missing(work):
            break
        if attempt == 5:
            raise ValueError('PyPI has not published all expected files')
        time.sleep(5)
    if install:
        requested = plan_at(work)['version']
        with tempfile.TemporaryDirectory(prefix='domino-pypi-') as directory:
            envdir = Path(directory) / 'venv'
            subprocess.run([sys.executable, '-m', 'venv', str(envdir)], check=True)
            python = envdir / 'bin/python'
            subprocess.run([str(python), '-m', 'pip', '--isolated', 'install', '--index-url',
                            'https://pypi.org/simple/', '--no-cache-dir', f'{PROJECT}=={requested}'], check=True)
            check_cli(envdir / 'bin/domino', requested)


def check_cli(executable, requested):
    with tempfile.TemporaryDirectory(prefix='domino-query-home-') as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DOMINO_', '_DOMINO'))}
        env['HOME'] = directory
        result = subprocess.check_output([str(executable), '--version'], env=env, text=True).strip()
        if result != requested or list(Path(directory).iterdir()):
            raise ValueError('Installed CLI version differs or query modified HOME')


def publish_brew(work):
    plan = validate_inputs(work)
    expected = (work / 'channels/tap/Formula/domino.rb').read_bytes()
    url = f'https://raw.githubusercontent.com/{plan["tap_repository"]}/main/Formula/domino.rb'
    current = fetch(url + '?release_check=' + str(time.time_ns()), missing=True)
    if current is not None:
        declared = re.findall(r'^  version "(' + VERSION + r')"$', current.decode(), re.M)
        if len(declared) != 1:
            raise ValueError('Existing Domino formula is not recognized')
        if version_tuple(declared[0]) > version_tuple(plan['version']):
            raise ValueError('Refusing to downgrade the Homebrew channel')
        if declared[0] == plan['version']:
            if current != expected:
                raise ValueError('Existing Homebrew version points to different content')
            return
    files = {'Formula/domino.rb': expected}
    if api(f'repos/{plan["tap_repository"]}/contents/README.md', missing=True) is None:
        files['README.md'] = (work / 'channels/tap/README.md').read_bytes()
    publish_git_files(plan['tap_repository'], files, 'domino ' + plan['version'])


def verify_brew(work, install=False):
    plan = validate_inputs(work)
    raw = fetch(f'https://raw.githubusercontent.com/{plan["tap_repository"]}/main/Formula/domino.rb'
                + '?release_check=' + str(time.time_ns()))
    if raw != (work / 'channels/tap/Formula/domino.rb').read_bytes():
        raise ValueError('Public Homebrew formula differs from the verified release')
    subprocess.run(['ruby', '-c'], input=raw, check=True, capture_output=True)
    if install:
        formula = plan['tap_repository'].replace('/homebrew-', '/', 1) + '/domino'
        subprocess.run(['brew', 'install', formula], check=True)
        subprocess.run(['brew', 'test', formula], check=True)
        prefix = subprocess.check_output(['brew', '--prefix', formula], text=True).strip()
        check_cli(Path(prefix) / 'bin/domino', plan['version'])


def apt_fetch(plan, name, missing=False):
    url = plan['apt_url'] + name
    if prepare_channels.urlsplit(url).hostname == 'raw.githubusercontent.com':
        url += '?release_check=' + str(time.time_ns())
    return fetch(url, missing=missing)


def apt_state(plan):
    raw = apt_fetch(plan, 'channel.json', missing=True)
    if raw is None:
        if apt_fetch(plan, 'dists/stable/InRelease', missing=True) is not None:
            raise ValueError('Existing APT source has no channel state; refusing to replace it')
        return None
    state = json.loads(raw)
    if state.get('schema') != 1 or state.get('repository') != plan['repository']:
        raise ValueError('APT source state is not recognized')
    if version_tuple(state['version']) > version_tuple(plan['version']):
        raise ValueError('Refusing to downgrade the APT channel')
    return state


def apt_fingerprint():
    key = os.environ.get('APT_GPG_FINGERPRINT', '')
    if not re.fullmatch(r'(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})', key):
        raise ValueError('Configure the full public APT_GPG_FINGERPRINT repository variable')
    return key.upper()


def prepare_apt(work):
    plan = validate_inputs(work)
    key = apt_fingerprint()
    old = apt_state(plan)
    if old and old['signing_fingerprint'] != key:
        raise ValueError('APT signing key changed; use an explicit key rotation procedure')
    if old and old['version'] == plan['version']:
        verify_apt(work)
        outputs(deploy=False)
        return False
    previous = work / 'previous-apt'
    if old:
        for name, digest in old['files'].items():
            if not name.startswith('pool/') and '/by-hash/' not in name:
                continue
            if not re.fullmatch(r'pool/main/d/domino-proxy/domino-proxy_' + VERSION + r'-\d+_all\.deb'
                               r'|dists/stable/main/binary-(?:amd64|arm64)/by-hash/(?:SHA256|SHA512)/[a-f0-9]+', name):
                raise ValueError('Invalid previous APT pool member')
            data = apt_fetch(plan, name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Previous APT package checksum differs')
            path = previous / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if not (previous / 'pool').is_dir():
            raise ValueError('Previous APT state has no package pool')
    private = os.environ.get('APT_GPG_PRIVATE_KEY')
    local = os.environ.get('RELEASE_LOCAL_SIGNING') == '1'
    if not local and not private:
        raise ValueError('Configure the local GPG key and Keychain passphrase')
    with nullcontext() if local else signing_home(private):
        report = prepare_channels.prepare(work / 'release', work / 'apt-signed', release_repo=plan['repository'],
            tap_repo=plan['tap_repository'], apt_repo=plan['repository'], apt_url=plan['apt_url'],
            sign_key=key, previous_repo=previous if old else None,
            existing_deb=work / f'channels/distribution/domino-proxy_{plan["version"]}-1_all.deb')
    if 'ci_candidate' in plan:
        deb = work / f'apt-signed/distribution/domino-proxy_{plan["version"]}-1_all.deb'
        if hashlib.sha256(deb.read_bytes()).hexdigest() != plan['ci_candidate']['deb_sha256']:
            raise ValueError('Signed APT staging changed the original CI package bytes')
    public = work / 'pages'
    public.mkdir()
    shutil.copytree(work / 'apt-signed/apt-site', public / 'apt')
    state = {'schema': 1, 'repository': plan['repository'], 'version': plan['version'],
             'source_sha': plan['source_sha'], 'signing_fingerprint': key,
             'files': {name.removeprefix('apt-site/'): digest for name, digest in report['files'].items()
                       if name.startswith('apt-site/')}}
    write_json(public / 'apt/channel.json', state)
    outputs(deploy=True)
    return True


@contextmanager
def signing_home(private):
    previous = os.environ.get('GNUPGHOME')
    with tempfile.TemporaryDirectory(prefix='domino-release-gpg-') as directory:
        os.chmod(directory, 0o700)
        os.environ['GNUPGHOME'] = directory
        try:
            subprocess.run(['gpg', '--batch', '--import'], input=private.encode(), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            yield
        finally:
            subprocess.run(['gpgconf', '--homedir', directory, '--kill', 'gpg-agent'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if previous is None:
                os.environ.pop('GNUPGHOME', None)
            else:
                os.environ['GNUPGHOME'] = previous


def verify_apt(work, install=False):
    plan = validate_inputs(work)
    state = apt_state(plan)
    key = apt_fingerprint()
    if not state or state['version'] != plan['version'] or state['signing_fingerprint'] != key:
        raise ValueError('APT version or signing key differs')
    expected_deb = work / f'channels/distribution/domino-proxy_{plan["version"]}-1_all.deb'
    package = f'pool/main/d/domino-proxy/{expected_deb.name}'
    if state['files'].get(package) != hashlib.sha256(expected_deb.read_bytes()).hexdigest():
        raise ValueError('APT published a different Debian package')
    with tempfile.TemporaryDirectory(prefix='domino-apt-check-') as directory:
        root = Path(directory)
        os.chmod(root, 0o755)  # apt's _apt user must be able to read the scoped source.
        gnupg = root / 'gnupg'
        gnupg.mkdir(mode=0o700)
        names = ['domino.sources', 'domino-archive-keyring.gpg', 'dists/stable/InRelease', package]
        for name in names:
            data = apt_fetch(plan, name)
            if hashlib.sha256(data).hexdigest() != state['files'].get(name):
                raise ValueError('APT public file checksum differs: ' + name)
            (root / Path(name).name).write_bytes(data)
        listing = subprocess.check_output(['gpg', '--homedir', str(gnupg), '--batch', '--with-colons',
                                          '--show-keys', str(root / 'domino-archive-keyring.gpg')],
                                         text=True, stderr=subprocess.PIPE)
        fingerprints = [line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:')]
        if len([line for line in listing.splitlines() if line.startswith('pub:')]) != 1 or not fingerprints or fingerprints[0] != key:
            raise ValueError('APT archive key does not match the pinned primary fingerprint')
        subprocess.run(['gpgv', '--keyring', str(root / 'domino-archive-keyring.gpg'),
                        str(root / 'InRelease')], check=True, capture_output=True)
        source = (root / 'domino.sources').read_text()
        prefix = prepare_channels.sources_text(plan['apt_url'], '')
        if not source.startswith(prefix):
            raise ValueError('APT source fields differ from the expected scoped source')
        lines = source[len(prefix):].splitlines()
        if not lines or any(not line.startswith(' ') for line in lines):
            raise ValueError('APT embedded key block is invalid')
        armored = '\n'.join('' if line == ' .' else line[1:] for line in lines) + '\n'
        binary = subprocess.run(['gpg', '--homedir', str(gnupg), '--batch', '--dearmor'],
                                input=armored.encode(), check=True, capture_output=True).stdout
        if binary != (root / 'domino-archive-keyring.gpg').read_bytes():
            raise ValueError('APT embedded key differs from the verified archive key')
        signed = (root / 'InRelease').read_text()
        for arch in ['amd64', 'arm64']:
            name = f'dists/stable/main/binary-{arch}/Packages'
            data = apt_fetch(plan, name)
            digest = hashlib.sha256(data).hexdigest()
            if digest != state['files'].get(name) or not re.search(
                    r'^ ' + digest + r'\s+' + str(len(data)) + r' ' + re.escape(name.removeprefix('dists/stable/')) + r'$', signed, re.M):
                raise ValueError('APT package index does not match signed metadata')
            index = data.decode()
            if (f'Filename: {package}\n' not in index or f'Version: {plan["version"]}-1\n' not in index
                    or f'SHA256: {state["files"][package]}\n' not in index):
                raise ValueError('APT package index differs from the expected release')
        if install:
            options = ['-o', 'Dir::Etc::sourcelist=' + str(root / 'domino.sources'),
                       '-o', 'Dir::Etc::sourceparts=-', '-o', 'APT::Get::List-Cleanup=0']
            subprocess.run(['sudo', 'apt-get', *options, 'update'], check=True)
            subprocess.run(['sudo', 'apt-get', *options, 'install', '-y', '--no-install-recommends',
                            PROJECT + '=' + plan['version'] + '-1'], check=True)
            check_cli('/usr/bin/domino', plan['version'])


def publish_apt_git(work):
    """Publish public signed files by git; does not need Pages or Actions."""
    plan = validate_inputs(work)
    repository = prepare_channels.repository_name(plan['apt_repository'])
    source = work / 'pages/apt'
    state = json.loads((source / 'channel.json').read_text())
    for name, digest in state['files'].items():
        relative = Path(name)
        allowed = (name in ['domino.sources', 'domino-archive-keyring.gpg', 'README.md', '.nojekyll']
                   or re.fullmatch(r'pool/main/d/domino-proxy/domino-proxy_' + VERSION + r'-\d+_all\.deb', name)
                   or re.fullmatch(r'dists/stable/(?:Release|InRelease|Release\.gpg|main/binary-(?:amd64|arm64)/'
                                   r'(?:Packages(?:\.gz)?|by-hash/(?:SHA256/[a-f0-9]{64}|SHA512/[a-f0-9]{128})))', name))
        if not allowed or relative.is_absolute() or '..' in relative.parts or (source / relative).is_symlink():
            raise ValueError('Only public APT repository files may be uploaded')
        data = (source / relative).read_bytes()
        if re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----', data):
            raise ValueError('Private key material cannot be published')
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Signed APT publication files changed')
    files = {name: (source / name).read_bytes() for name in [*state['files'], 'channel.json']}
    publish_git_files(repository, files, 'Publish signed Domino ' + plan['version'])


def publish_git_files(repository, files, message):
    """Commit public files atomically through the Git API, without git transport."""
    repository = prepare_channels.repository_name(repository)
    parent = api(f'repos/{repository}/git/ref/heads/main')['object']['sha']
    commit = api(f'repos/{repository}/git/commits/{parent}')
    tree = api(f'repos/{repository}/git/trees/{commit["tree"]["sha"]}?recursive=1')
    if tree.get('truncated'):
        raise ValueError('Repository tree is too large for a complete publication check')
    old = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
    changes, blobs = [], {}
    for name, data in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
            raise ValueError('Invalid public repository path')
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if old.get(name) == digest:
            continue
        if digest not in blobs:
            blob = api(f'repos/{repository}/git/blobs', data={'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
            if blob['sha'] != digest:
                raise ValueError('Uploaded Git blob checksum differs')
            blobs[digest] = digest
        changes.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': digest})
    if not changes:
        return parent
    new_tree = api(f'repos/{repository}/git/trees', data={'base_tree': commit['tree']['sha'], 'tree': changes})
    new_commit = api(f'repos/{repository}/git/commits', data={'message': message, 'tree': new_tree['sha'], 'parents': [parent]})
    api(f'repos/{repository}/git/refs/heads/main', method='PATCH', data={'sha': new_commit['sha'], 'force': False})
    return new_commit['sha']


def publish_pypi_local(work):
    missing = stage_pypi(work)
    if missing:
        token = keychain_password('https://upload.pypi.org/legacy/', '__token__')
        if not token:
            raise ValueError('Configure the project PyPI token in macOS Keychain')
        env = {name: value for name, value in os.environ.items() if not name.startswith('TWINE_')}
        env.update(TWINE_USERNAME='__token__', TWINE_PASSWORD=token)
        # Only the Twine subprocess receives the password; no .pypirc or
        # repository token file is read, and no secret appears in argv/artifacts.
        subprocess.run([sys.executable, '-m', 'twine', 'upload', '--non-interactive',
                        '--disable-progress-bar', '--username', '__token__', '--config-file', os.devnull,
                        '--repository-url', 'https://upload.pypi.org/legacy/',
                        *[str(work / 'pypi-upload' / name) for name in missing]], check=True, env=env)
    verify_pypi(work, install=True)


@contextmanager
def local_credentials(directory, channel):
    if channel != 'apt':
        raise ValueError('Only APT signing uses separate local GPG credentials')
    directory = directory.expanduser().resolve()
    if directory.is_relative_to(prepare_channels.ROOT) or directory.stat().st_mode & 0o077:
        raise ValueError('Credentials must be outside the repository in a 0700 directory')
    saved = dict(os.environ)
    try:
        if channel == 'apt':
            state = json.loads((directory / 'state.json').read_text())
            password = keychain_password(state['keychain_service'], state['keychain_username'])
            if password is None:
                raise ValueError('APT signing passphrase is missing from macOS Keychain')
            home = directory / 'gnupg'
            if home.is_symlink() or home.stat().st_mode & 0o077:
                raise ValueError('GPG HOME must be a regular 0700 directory')
            os.environ.update(GNUPGHOME=str(home), APT_GPG_FINGERPRINT=state['apt_fingerprint'],
                              APT_GPG_PASSPHRASE=password, RELEASE_LOCAL_SIGNING='1')
            os.environ.pop('APT_GPG_PRIVATE_KEY', None)
        yield
    finally:
        if channel == 'apt':
            subprocess.run(['gpgconf', '--homedir', str(directory / 'gnupg'), '--kill', 'gpg-agent'],
                           capture_output=True)
        os.environ.clear()
        os.environ.update(saved)


def keychain_password(service, username):
    # Select the native backend explicitly; never fall back to a plaintext file.
    from keyring.backends.macOS import Keyring
    return Keyring().get_password(service, username)


def publish_local(work, repo, requested, selected, credentials, dry_run=False, candidate=None):
    """One local workflow. Each channel has its own recoverable result."""
    selected_channels = ['pypi', 'brew', 'apt'] if selected == 'all' else [selected]
    previous_api = os.environ.get('RELEASE_LOCAL_API')
    os.environ['RELEASE_LOCAL_API'] = '1'
    results = {}
    try:
        resolve(work, repo, requested, os.environ.get('RELEASE_TAP_REPOSITORY') or None,
                os.environ.get('RELEASE_APT_URL') or None, os.environ.get('RELEASE_APT_REPOSITORY') or None)
        with tempfile.TemporaryDirectory(prefix='domino-tag-source-') as directory:
            source = Path(directory) / 'source'
            target = plan_at(work)['source_sha']
            available = subprocess.run(['git', '-C', str(prepare_channels.ROOT), 'cat-file', '-e', target],
                                       capture_output=True).returncode == 0
            if available:
                subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout',
                                str(prepare_channels.ROOT), str(source)], check=True)
                subprocess.run(['git', '-C', str(source), 'checkout', '--quiet', '--detach', target], check=True)
            else:
                subprocess.run(['git', '-c', 'http.version=HTTP/1.1', 'clone', '--quiet', '--depth', '1',
                                '--single-branch', '--branch', 'v' + requested,
                                f'https://github.com/{repo}.git', str(source)], check=True, timeout=180)
            prepare(work, source, candidate=candidate) if candidate is not None else prepare(work, source)
        results['prepare'] = 'success'
        if dry_run:
            return summary(work, results, selected, True)
        publish_github(work)
        results['github'] = 'success'
        for channel in selected_channels:
            try:
                if channel == 'pypi':
                    publish_pypi_local(work)
                elif channel == 'brew':
                    publish_brew(work)
                    verify_brew(work)
                else:
                    with local_credentials(credentials, 'apt'):
                        deploy = prepare_apt(work)
                    if deploy:
                        publish_apt_git(work)
                    state = json.loads((credentials.expanduser() / 'state.json').read_text())
                    previous_key = os.environ.get('APT_GPG_FINGERPRINT')
                    try:
                        os.environ['APT_GPG_FINGERPRINT'] = state['apt_fingerprint']
                        verify_apt(work)
                    finally:
                        if previous_key is None:
                            os.environ.pop('APT_GPG_FINGERPRINT', None)
                        else:
                            os.environ['APT_GPG_FINGERPRINT'] = previous_key
                results[channel] = 'success'
                print(channel + ': verified')
            except Exception as error:
                results[channel] = 'failure'
                # Exception text may contain secret-bearing commands from external
                # libraries. Per-command stderr and the exception type identify failure.
                detail = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
                print(channel + ': failed (' + detail + ')', file=sys.stderr)
        return summary(work, results, selected, False)
    except Exception:
        if 'prepare' not in results:
            results['prepare'] = 'failure'
        elif 'github' not in results:
            results['github'] = 'failure'
        if not (work / 'release-status.json').exists():
            try:
                summary(work, results, selected, dry_run)
            except ValueError:
                pass
        raise
    finally:
        if previous_api is None:
            os.environ.pop('RELEASE_LOCAL_API', None)
        else:
            os.environ['RELEASE_LOCAL_API'] = previous_api


def summary(work, results, selected, dry_run):
    plan = plan_at(work) if (work / 'plan.json').exists() else {
        'version': os.environ.get('RELEASE_VERSION', 'unknown'), 'source_sha': None}
    channels = ['pypi', 'brew', 'apt'] if selected == 'all' else [selected]
    states = {channel: ('checked' if dry_run and results.get('prepare') == 'success' else
                       'verified' if results.get(channel) == 'success' else
                       'failed' if results.get(channel) == 'failure' else 'blocked') for channel in channels}
    ok = all(state in ('checked', 'verified') for state in states.values())
    report = {'version': plan['version'], 'source_sha': plan['source_sha'], 'dry_run': dry_run,
              'complete': ok and not dry_run and selected == 'all',
              'request_complete': ok and not dry_run, 'channels': states, 'jobs': results}
    write_json(work / 'release-status.json', report)
    text = f'# Domino {plan["version"]}\n\n' + ('Dry run; nothing published.\n\n' if dry_run else '')
    text += '| Channel | Result |\n| --- | --- |\n' + ''.join(f'| {name} | {state} |\n' for name, state in states.items())
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a') as stream:
            stream.write(text)
    if not ok:
        raise ValueError('Release is incomplete; see per-channel jobs and release-status.json')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['publish', 'resolve', 'prepare', 'publish-github', 'stage-pypi',
                                            'verify-pypi', 'verify-brew', 'publish-brew', 'prepare-apt', 'verify-apt', 'summary'])
    parser.add_argument('--work', type=Path)
    parser.add_argument('--source', type=Path, default=Path('.release-source'))
    parser.add_argument('--version', default=os.environ.get('RELEASE_VERSION'))
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'KJaebye/domino'))
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--channels', choices=['all', 'pypi', 'brew', 'apt'], default='all')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--candidate', type=Path, help='Import an exact, fully checked stable CI candidate; never relabel a development build')
    parser.add_argument('--credentials-dir', type=Path, default=Path.home() / '.local/share/domino-release')
    args = parser.parse_args()
    operation = args.operation
    if operation == 'publish':
        requested = version(args.version or '')
        work = args.work or prepare_channels.ROOT / 'dist' / f'local-release-{requested}-{time.time_ns()}'
        work.parent.mkdir(parents=True, exist_ok=True)
        result = publish_local(work, args.repo, requested, args.channels, args.credentials_dir, args.dry_run,
                               candidate=args.candidate.resolve() if args.candidate else None)
        print(json.dumps({'work': str(work), **result}))
        return
    args.work = args.work or Path('release-work')
    if operation == 'resolve':
        resolve(args.work, args.repo, args.version or '', os.environ.get('RELEASE_TAP_REPOSITORY') or None,
                os.environ.get('RELEASE_APT_URL') or None, os.environ.get('RELEASE_APT_REPOSITORY') or None)
    elif operation == 'prepare':
        prepare(args.work, args.source.resolve(), candidate=args.candidate.resolve() if args.candidate else None)
    elif operation == 'summary':
        needs = json.loads(os.environ['RELEASE_JOB_RESULTS'])
        results = {name: job['result'] for name, job in needs.items()}
        summary(args.work, results, os.environ.get('RELEASE_CHANNELS', 'all'), os.environ.get('RELEASE_DRY_RUN') == 'true')
    else:
        function = {'publish-github': publish_github, 'stage-pypi': stage_pypi, 'verify-pypi': verify_pypi,
                    'verify-brew': verify_brew, 'publish-brew': publish_brew, 'prepare-apt': prepare_apt, 'verify-apt': verify_apt}[operation]
        function(args.work, install=args.install) if operation.startswith('verify-') else function(args.work)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, HTTPError, URLError, subprocess.CalledProcessError) as error:
        # Do not echo command argv, HTTP response bodies or secret-bearing environments.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print('Release failed: ' + message, file=sys.stderr)
        raise SystemExit(1)
