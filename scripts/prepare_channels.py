#!/usr/bin/env python3
"""Prepare a Homebrew tap and signed apt site; never publish or create keys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

try:
    from scripts import build_distribution, build_release
except ModuleNotFoundError:
    import build_distribution
    import build_release

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_REPO = 'KJaebye/domino'
DEFAULT_TAP_REPO = 'KJaebye/homebrew-tap'
DEFAULT_APT_REPO = 'KJaebye/domino-apt'
DEFAULT_APT_URL = 'https://downloads.oetree.cc/domino/apt/'
DEFAULT_APT_SOURCES_URL = 'https://downloads.oetree.cc/domino/domino.sources'


def repository_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value) or '..' in value:
        raise ValueError('Use a GitHub owner/repository name')
    return value


def fingerprint(key):
    if not re.fullmatch(r'(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})', key):
        raise ValueError('Use a full existing GPG signing key fingerprint')
    public = subprocess.run(['gpg', '--batch', '--with-colons', '--fingerprint', key],
                            check=True, capture_output=True, text=True).stdout
    value = next((line.split(':')[9] for line in public.splitlines() if line.startswith('fpr:')), None)
    if not value or value.upper() != key.upper():
        raise ValueError('Signing key fingerprint does not match')
    return value.upper()


def sources_text(url, armored_key):
    # apt >= 2.4 (Ubuntu 22.04+) supports an embedded key scoped to this source.
    lines = ['Types: deb', 'URIs: ' + url, 'Suites: stable', 'Components: main',
             'Architectures: amd64 arm64', 'Signed-By:']
    lines.extend(' ' + (line if line else '.') for line in armored_key.strip().splitlines())
    return '\n'.join(lines) + '\n'


def prepare(release, output, *, release_repo=DEFAULT_RELEASE_REPO, tap_repo=DEFAULT_TAP_REPO,
            apt_repo=DEFAULT_APT_REPO, sign_key=None, previous_repo=None, apt_url=None, existing_deb=None):
    if output.exists() or output.is_symlink():
        raise FileExistsError('Channel output already exists; choose a new directory')
    release_repo, tap_repo, apt_repo = map(repository_name, (release_repo, tap_repo, apt_repo))
    if not tap_repo.split('/')[1].startswith('homebrew-'):
        raise ValueError('Tap repository name must start with homebrew-')
    manifest, _ = build_distribution.load_runtime(release)
    version = manifest['version']
    runtime = f'domino-runtime-{version}.tar.gz'
    entry = next(item for item in manifest['files'] if item['name'] == runtime)
    release_url = f'https://github.com/{release_repo}/releases/download/v{version}'
    owner, name = apt_repo.split('/')
    apt_url = apt_url or (DEFAULT_APT_URL if apt_repo == DEFAULT_APT_REPO
                          else f'https://{owner.lower()}.github.io/{name}/')
    parsed = urlsplit(apt_url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(char.isspace() for char in apt_url)):
        raise ValueError('APT URL must be a public HTTPS directory')
    apt_url = apt_url.rstrip('/') + '/'
    tap_name = tap_repo.replace('/homebrew-', '/', 1)
    signing_fingerprint = fingerprint(sign_key) if sign_key else None
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.domino-channels-', dir=output.parent) as directory:
        stage = Path(directory) / 'ready'
        stage.mkdir()
        distribution = stage / 'distribution'
        build_distribution.build(release, distribution, sign_key=sign_key, previous_repo=previous_repo,
                                 existing_deb=existing_deb)
        tap = stage / 'tap'
        (tap / 'Formula').mkdir(parents=True)
        (tap / 'Formula/domino.rb').write_text(build_release.formula_text(runtime, version, entry['sha256'], release_url))
        (tap / 'README.md').write_text(
            '# Domino Homebrew tap\n\n'
            f'```sh\nbrew install {tap_name}/domino\nbrew upgrade {tap_name}/domino\n```\n\n'
            'Installs the CLI without starting services or changing proxy settings. '
            'Use `domino catch` to configure and start a local proxy, '
            'or `domino USER@IP` to deploy remotely.\n')
        site = stage / 'apt-site'
        shutil.copytree(distribution / 'apt', site)
        (site / '.nojekyll').write_text('')
        install = 'This is an unsigned preview; do not configure it as an apt source.\n'
        if sign_key:
            armored = subprocess.run(['gpg', '--batch', '--armor', '--export', sign_key],
                                    check=True, capture_output=True, text=True).stdout
            if not armored.startswith('-----BEGIN PGP PUBLIC KEY BLOCK-----'):
                raise ValueError('Public key export is invalid')
            (site / 'domino.sources').write_text(sources_text(apt_url, armored))
            sources_url = DEFAULT_APT_SOURCES_URL if apt_url == DEFAULT_APT_URL else apt_url + 'domino.sources'
            install = (f'```sh\ncurl -fsSL {sources_url} '
                       '| sudo tee /etc/apt/sources.list.d/domino.sources >/dev/null\n'
                       'sudo apt update\nsudo apt install domino-proxy\n```\n\n'
                       f'Signing key fingerprint: `{signing_fingerprint}`\n')
        (site / 'README.md').write_text('# Domino apt repository\n\nUbuntu 22.04+ / amd64 and arm64.\n\n' + install +
            '\nPackages install the CLI only. Configuration and services remain user-managed.\n')
        report = {'schema': 1, 'version': version, 'published': False,
                  'release_repo': release_repo, 'tap_repo': tap_repo, 'apt_repo': apt_repo,
                  'runtime_url': release_url + '/' + runtime, 'apt_url': apt_url,
                  'brew_install': f'brew install {tap_name}/domino',
                  'apt_signed': bool(sign_key), 'signing_fingerprint': signing_fingerprint,
                  'files': {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted(stage.rglob('*')) if path.is_file()}}
        (stage / 'channels.json').write_text(json.dumps(report, indent=2) + '\n')
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release-repo', default=DEFAULT_RELEASE_REPO)
    parser.add_argument('--tap-repo', default=DEFAULT_TAP_REPO)
    parser.add_argument('--apt-repo', default=DEFAULT_APT_REPO)
    parser.add_argument('--apt-url', help='Override the apt HTTPS directory, default: downloads.oetree.cc/domino/apt/ for Domino')
    parser.add_argument('--sign-key')
    parser.add_argument('--previous-repo', type=Path)
    parser.add_argument('--existing-deb', type=Path)
    args = parser.parse_args()
    report = prepare(args.release, args.output, release_repo=args.release_repo, tap_repo=args.tap_repo,
                     apt_repo=args.apt_repo, sign_key=args.sign_key, previous_repo=args.previous_repo,
                     apt_url=args.apt_url, existing_deb=args.existing_deb)
    print(json.dumps({'output': str(args.output), **{key: value for key, value in report.items() if key != 'files'}}))


if __name__ == '__main__':
    main()
