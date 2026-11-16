#!/usr/bin/env python3
"""Prepare a portable Debian CLI package and an optional signed apt repository.

Consumes checksum-verified runtime artifacts. Does not install packages, publish,
start services, inspect user configuration, or generate signing keys.
"""
import argparse
from datetime import datetime, timezone
from email.utils import format_datetime, parseaddr
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'domino-proxy'
MAINTAINER = 'KJaebye <KJaebye@users.noreply.github.com>'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tar_bytes(files, epoch):
    stream = io.BytesIO()
    # dpkg requires parent directories to be present in data.tar, and tracks
    # these entries so package-owned directories can be removed on uninstall.
    directories = {parent.as_posix() for name in files for parent in Path(name).parents
                   if parent != Path('.')}
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories | files.keys()):
            directory = name in directories
            content, mode = (b'', 0o755) if directory else files[name]
            info = tarfile.TarInfo(name)
            if directory:
                info.type = tarfile.DIRTYPE
            info.size, info.mode, info.mtime = len(content), mode, epoch
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(stream.getvalue(), mtime=0)


def deb_bytes(control, files, epoch):
    result = bytearray(b'!<arch>\n')
    for name, content in [('debian-binary', b'2.0\n'),
                          ('control.tar.gz', tar_bytes(control, epoch)),
                          ('data.tar.gz', tar_bytes(files, epoch))]:
        header = f'{name + "/":<16}{epoch:<12}{0:<6}{0:<6}{"100644":<8}{len(content):<10}`\n'
        if len(header) != 60:
            raise ValueError('Invalid Debian archive header')
        result.extend(header.encode('ascii'))
        result.extend(content)
        if len(content) % 2:
            result.extend(b'\n')
    return bytes(result)


def load_runtime(release):
    raw = (release / 'release.json').read_bytes()
    manifest = json.loads(raw)
    version = manifest['version']
    if not re.fullmatch(r'0\.\d+\.\d+', version):
        raise ValueError('Invalid runtime version')
    sums = {}
    for line in (release / 'SHA256SUMS').read_text().splitlines():
        checksum, name = line.split('  ')
        if Path(name).name != name or name in sums or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Invalid checksum manifest')
        sums[name] = checksum
    if sums.get('release.json') != digest(raw):
        raise ValueError('Release manifest checksum mismatch')
    for entry in manifest['files']:
        name = entry['name']
        if Path(name).name != name:
            raise ValueError('Invalid artifact name')
        data = (release / name).read_bytes()
        if len(data) != entry['bytes'] or digest(data) != entry['sha256'] or sums.get(name) != digest(data):
            raise ValueError('Artifact checksum mismatch: ' + name)
    name = f'domino-runtime-{version}.tar.gz'
    if name not in {entry['name'] for entry in manifest['files']}:
        raise ValueError('Runtime not in release manifest')
    files = {}
    total = 0
    with tarfile.open(release / name) as archive:
        for member in archive:
            path = Path(member.name)
            if (path.is_absolute() or '..' in path.parts or path.parts[0] != f'domino-{version}'
                    or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe runtime member')
            if not member.isfile():
                continue
            relative = path.relative_to(f'domino-{version}').as_posix()
            if relative in files or member.size > 32 * 1024 * 1024:
                raise ValueError('Duplicate or oversized runtime file')
            total += member.size
            if total > 100 * 1024 * 1024:
                raise ValueError('Runtime exceeds size limit')
            files[relative] = archive.extractfile(member).read()
    if 'cli/domino_install.py' not in files:
        raise ValueError('Runtime lacks package entry points')
    return manifest, files


def wrapper(entry):
    return ('#!/usr/bin/python3\nimport sys\n'
            'sys.dont_write_bytecode = True\n'
            'sys.path[:0] = ["/usr/lib/domino/cli", "/usr/lib/domino/cli/_vendor"]\n'
            f'from domino_install import {entry}\nraise SystemExit({entry}())\n').encode()


def payload(runtime):
    files = {}
    for name, content in runtime.items():
        if name.startswith('bin/'):
            continue
        if name == 'cli/completion.zsh':
            target = 'usr/share/zsh/vendor-completions/_domino'
        elif name == 'cli/completion.bash':
            target = 'usr/share/bash-completion/completions/domino'
        elif name.startswith('cli/'):
            if name.endswith(('.so', '.dylib', '.dll', '.pyc')):
                raise ValueError('Architecture-independent package contains binary code')
            target = 'usr/lib/domino/' + name
        else:
            target = f'usr/share/doc/{PACKAGE}/' + name
        files[target] = (content, 0o644)
    files['usr/bin/domino'] = (wrapper('package_cli'), 0o755)
    files['usr/bin/domino-install'] = (wrapper('package_install'), 0o755)
    notice = runtime.get('NOTICE', b'')
    license_text = runtime.get('LICENSE', b'Project license has not been selected; consult the copyright holder.\n')
    files[f'usr/share/doc/{PACKAGE}/copyright'] = (license_text + b'\n' + notice, 0o644)
    return files


def repository(output, deb, control, epoch):
    repo = output / 'apt'
    pool = repo / 'pool/main/d/domino-proxy' / deb.name
    pool.parent.mkdir(parents=True)
    shutil.copyfile(deb, pool)
    index = (control + f'Filename: {pool.relative_to(repo).as_posix()}\n'
             f'Size: {pool.stat().st_size}\nSHA256: {digest(pool.read_bytes())}\n\n').encode()
    suite = repo / 'dists/stable'
    for arch in ['amd64', 'arm64']:
        binary = suite / f'main/binary-{arch}'
        binary.mkdir(parents=True)
        (binary / 'Packages').write_bytes(index)
        (binary / 'Packages.gz').write_bytes(gzip.compress(index, mtime=0))
    paths = sorted(path for path in suite.rglob('*') if path.is_file())
    release = ('Origin: Domino\nLabel: Domino\nSuite: stable\nCodename: stable\n'
               f'Date: {format_datetime(datetime.fromtimestamp(epoch, timezone.utc), usegmt=True)}\n'
               'Architectures: amd64 arm64\nComponents: main\nDescription: Domino CLI packages\n')
    for algorithm in ['sha256', 'sha512']:
        release += algorithm.upper() + ':\n'
        for path in paths:
            checksum = hashlib.new(algorithm, path.read_bytes()).hexdigest()
            release += f' {checksum} {path.stat().st_size:16} {path.relative_to(suite).as_posix()}\n'
    (suite / 'Release').write_text(release)
    return repo


def sign_repository(repo, key):
    if not re.fullmatch(r'(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})', key):
        raise ValueError('Use a full existing GPG signing key fingerprint')
    release = repo / 'dists/stable/Release'
    common = ['gpg', '--batch', '--local-user', key]
    subprocess.run(common + ['--output', str(release.with_name('InRelease')), '--clearsign', str(release)], check=True)
    subprocess.run(common + ['--output', str(release.with_name('Release.gpg')), '--detach-sign', str(release)], check=True)
    public = subprocess.run(['gpg', '--batch', '--export', key], check=True, capture_output=True).stdout
    if not public:
        raise ValueError('Signing public key export is empty')
    (repo / 'domino-archive-keyring.gpg').write_bytes(public)


def build(release, output, maintainer=MAINTAINER, sign_key=None, epoch=None):
    if output.exists() or output.is_symlink():
        raise FileExistsError('Distribution output already exists; choose a new directory')
    if '\n' in maintainer or '\r' in maintainer or not parseaddr(maintainer)[1] or '@' not in parseaddr(maintainer)[1]:
        raise ValueError('Maintainer must contain a name and email on one line')
    manifest, runtime = load_runtime(release)
    version = manifest['version']
    epoch = int(datetime.fromisoformat(manifest['built_at']).timestamp()) if epoch is None else epoch
    if not 0 <= epoch < 10**11:
        raise ValueError('Invalid build epoch')
    files = payload(runtime)
    control = (f'Package: {PACKAGE}\nVersion: {version}-1\nSection: net\nPriority: optional\n'
               f'Architecture: all\nMaintainer: {maintainer}\n'
               f'Installed-Size: {(sum(len(data) for data, _ in files.values()) + 1023) // 1024}\n'
               'Depends: python3 (>= 3.9), curl, openssh-client\nRecommends: sudo, systemd\n'
               'Homepage: https://github.com/KJaebye/domino\n'
               'Description: Proxy configuration management and independent SSH deployment\n'
               ' Installs the Domino CLI with bundled Python dependencies.\n'
               ' Local proxy initialization is explicit: run domino-install as a normal user.\n')
    md5sums = ''.join(hashlib.md5(data).hexdigest() + '  ' + name + '\n' for name, (data, _) in sorted(files.items()))
    control_files = {'control': (control.encode(), 0o644), 'md5sums': (md5sums.encode(), 0o644)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.domino-distribution-', dir=output.parent) as directory:
        staged = Path(directory) / 'output'
        staged.mkdir()
        deb = staged / f'{PACKAGE}_{version}-1_all.deb'
        deb.write_bytes(deb_bytes(control_files, files, epoch))
        repo = repository(staged, deb, control, epoch)
        if sign_key:
            sign_repository(repo, sign_key)
        formula = next(item['name'] for item in manifest['files'] if item['name'].endswith(('.rb', '.rb.in')))
        shutil.copyfile(release / formula, staged / formula)
        report = {'version': version, 'distribution': PACKAGE, 'published': False,
                  'release_manifest_sha256': digest((release / 'release.json').read_bytes()),
                  'deb': deb.name, 'apt_signed': bool(sign_key), 'maintainer': maintainer,
                  'service_install_hooks': False, 'architecture': 'all',
                  'files': {p.relative_to(staged).as_posix(): digest(p.read_bytes())
                            for p in sorted(staged.rglob('*')) if p.is_file()}}
        (staged / 'distribution.json').write_text(json.dumps(report, indent=2) + '\n')
        # Publish only into an exclusively reserved output directory.
        output.mkdir()
        try:
            for path in staged.iterdir():
                path.rename(output / path.name)
        except BaseException:
            shutil.rmtree(output)
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--maintainer', default=MAINTAINER, help='Public Debian maintainer identity')
    parser.add_argument('--sign-key', help='Existing GPG key fingerprint; omit for an unsigned preview')
    args = parser.parse_args()
    version = json.loads((args.release / 'release.json').read_text())['version']
    output = args.output or ROOT / ('dist/distribution-' + version)
    report = build(args.release, output, args.maintainer, args.sign_key,
                   int(os.environ['SOURCE_DATE_EPOCH']) if 'SOURCE_DATE_EPOCH' in os.environ else None)
    print(json.dumps({'output': str(output), **report}))


if __name__ == '__main__':
    main()
