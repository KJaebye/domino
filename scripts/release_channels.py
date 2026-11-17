#!/usr/bin/env python3
"""Deterministic multi-channel release operations for the single release workflow.

Secrets come from the execution environment only. Never reads local credential
files, initializes Domino, creates repositories, or generates production keys.
"""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
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


def api(path, *, missing=False):
    data = fetch('https://api.github.com/' + path, authenticated=True, missing=missing)
    return json.loads(data) if data is not None else None


def resolve(work, repo, requested, tap_repo=None, apt_url=None):
    requested = version(requested)
    repo = prepare_channels.repository_name(repo)
    tap_repo = prepare_channels.repository_name(tap_repo or repo.split('/')[0] + '/homebrew-tap')
    if not tap_repo.split('/')[1].startswith('homebrew-'):
        raise ValueError('Tap repository name must start with homebrew-')
    owner, name = repo.split('/')
    apt_url = apt_url or f'https://{owner.lower()}.github.io/{name}/apt/'
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
            'tap_repository': tap_repo, 'apt_url': apt_url.rstrip('/') + '/',
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


def prepare(work, source):
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
    if plan['existing_release']:
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
        tap_repo=plan['tap_repository'], apt_repo=plan['repository'], apt_url=plan['apt_url'])
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


@contextmanager
def tap_credentials():
    private = os.environ.get('RELEASE_TAP_SSH_KEY')
    if not private:
        if not os.environ.get('GH_TOKEN'):
            raise ValueError('Configure a tap-only RELEASE_TAP_SSH_KEY or RELEASE_TAP_TOKEN secret')
        yield dict(os.environ), False
        return
    with tempfile.TemporaryDirectory(prefix='domino-tap-key-') as directory:
        root = Path(directory)
        key = root / 'key'
        with key.open('x') as stream:
            key.chmod(0o600)
            # Secret input can omit the final LF or contain CRLF. OpenSSH
            # rejects an otherwise valid private key without its final LF.
            stream.write(private.replace('\r\n', '\n').strip() + '\n')
        keys = api('meta')['ssh_keys']
        if not keys or any(not re.fullmatch(r'(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+', item) for item in keys):
            raise ValueError('GitHub SSH host keys are invalid')
        known_hosts = root / 'known_hosts'
        known_hosts.write_text(''.join('github.com ' + item + '\n' for item in keys))
        env = {name: value for name, value in os.environ.items() if name not in ('RELEASE_TAP_SSH_KEY', 'GH_TOKEN', 'GH_API_TOKEN')}
        env['GIT_TERMINAL_PROMPT'] = '0'
        env['GIT_SSH_COMMAND'] = ('ssh -F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes '
                                '-o UserKnownHostsFile=' + shlex.quote(str(known_hosts)) + ' -i ' + shlex.quote(str(key)))
        yield env, True


def publish_brew(work):
    plan = validate_inputs(work)
    with tap_credentials() as (env, ssh), tempfile.TemporaryDirectory(prefix='domino-tap-') as directory:
        tap = Path(directory) / 'tap'
        url = (f'git@github.com:{plan["tap_repository"]}.git' if ssh else
               f'https://github.com/{plan["tap_repository"]}.git')
        subprocess.run(['git', 'clone', '--single-branch', '--branch', 'main',
                        url, str(tap)], check=True, env=env)
        formula = tap / 'Formula/domino.rb'
        if formula.exists():
            text = formula.read_text()
            current = re.findall(r'^  version "(' + VERSION + r')"$', text, re.M)
            if len(current) != 1:
                raise ValueError('Existing Domino formula is not recognized')
            if version_tuple(current[0]) > version_tuple(plan['version']):
                raise ValueError('Refusing to downgrade the Homebrew channel')
            if current[0] == plan['version']:
                runtime = 'domino-runtime-' + plan['version'] + '.tar.gz'
                url = f'https://github.com/{plan["repository"]}/releases/download/v{plan["version"]}/{runtime}'
                if f'  sha256 "{plan["files"][runtime]}"\n' not in text or f'  url "{url}"\n' not in text:
                    raise ValueError('Existing Homebrew version points to different content')
                return
        formula.parent.mkdir(exist_ok=True)
        shutil.copyfile(work / 'channels/tap/Formula/domino.rb', formula)
        if not (tap / 'README.md').exists():
            shutil.copyfile(work / 'channels/tap/README.md', tap / 'README.md')
        subprocess.run(['git', '-C', str(tap), 'add', '--', 'Formula/domino.rb', 'README.md'], check=True, env=env)
        subprocess.run(['git', '-C', str(tap), '-c', 'user.name=github-actions[bot]',
                        '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                        'commit', '-m', 'domino ' + plan['version']], check=True, env=env)
        # gh reads GH_TOKEN through the credential protocol; no credential is stored in the URL.
        auth = [] if ssh else ['-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential']
        subprocess.run(['git', '-C', str(tap), *auth, 'push', 'origin', 'HEAD:main'], check=True, env=env)


def apt_state(plan):
    raw = fetch(plan['apt_url'] + 'channel.json', missing=True)
    if raw is None:
        if fetch(plan['apt_url'] + 'dists/stable/InRelease', missing=True) is not None:
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
        return
    previous = work / 'previous-apt'
    if old:
        for name, digest in old['files'].items():
            if not name.startswith('pool/'):
                continue
            if not re.fullmatch(r'pool/main/d/domino-proxy/domino-proxy_' + VERSION + r'-\d+_all\.deb', name):
                raise ValueError('Invalid previous APT pool member')
            data = fetch(plan['apt_url'] + name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Previous APT package checksum differs')
            path = previous / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if not (previous / 'pool').is_dir():
            raise ValueError('Previous APT state has no package pool')
    private = os.environ.get('APT_GPG_PRIVATE_KEY')
    if not private:
        raise ValueError('Configure the APT_GPG_PRIVATE_KEY environment secret')
    with signing_home(private):
        report = prepare_channels.prepare(work / 'release', work / 'apt-signed', release_repo=plan['repository'],
            tap_repo=plan['tap_repository'], apt_repo=plan['repository'], apt_url=plan['apt_url'],
            sign_key=key, previous_repo=previous if old else None)
    public = work / 'pages'
    public.mkdir()
    shutil.copytree(work / 'apt-signed/apt-site', public / 'apt')
    state = {'schema': 1, 'repository': plan['repository'], 'version': plan['version'],
             'source_sha': plan['source_sha'], 'signing_fingerprint': key,
             'files': {name.removeprefix('apt-site/'): digest for name, digest in report['files'].items()
                       if name.startswith('apt-site/')}}
    write_json(public / 'apt/channel.json', state)
    outputs(deploy=True)


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
            data = fetch(plan['apt_url'] + name)
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
            data = fetch(plan['apt_url'] + name)
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
    parser.add_argument('operation', choices=['resolve', 'prepare', 'publish-github', 'stage-pypi',
                                            'verify-pypi', 'publish-brew', 'prepare-apt', 'verify-apt', 'summary'])
    parser.add_argument('--work', type=Path, default=Path('release-work'))
    parser.add_argument('--source', type=Path, default=Path('.release-source'))
    parser.add_argument('--version', default=os.environ.get('RELEASE_VERSION'))
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY', 'KJaebye/domino'))
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    operation = args.operation
    if operation == 'resolve':
        resolve(args.work, args.repo, args.version or '', os.environ.get('RELEASE_TAP_REPOSITORY') or None,
                os.environ.get('RELEASE_APT_URL') or None)
    elif operation == 'prepare':
        prepare(args.work, args.source.resolve())
    elif operation == 'summary':
        needs = json.loads(os.environ['RELEASE_JOB_RESULTS'])
        results = {name: job['result'] for name, job in needs.items()}
        summary(args.work, results, os.environ.get('RELEASE_CHANNELS', 'all'), os.environ.get('RELEASE_DRY_RUN') == 'true')
    else:
        function = {'publish-github': publish_github, 'stage-pypi': stage_pypi, 'verify-pypi': verify_pypi,
                    'publish-brew': publish_brew, 'prepare-apt': prepare_apt, 'verify-apt': verify_apt}[operation]
        function(args.work, install=args.install) if operation.startswith('verify-') else function(args.work)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, HTTPError, URLError, subprocess.CalledProcessError) as error:
        # Do not echo command argv, HTTP response bodies or secret-bearing environments.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print('Release failed: ' + message, file=sys.stderr)
        raise SystemExit(1)
