#!/usr/bin/env python3
"""Read-only CI candidate review. A verified development build is not a release."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

try:
    from scripts import build_distribution, release_channels, verify_artifacts
except ModuleNotFoundError:
    import build_distribution
    import release_channels
    import verify_artifacts


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid candidate inventory path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value:
        raise ValueError('Candidate inventory path escapes its output directory')
    return path


def verify_inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Candidate must be a real directory')
    if any(path.is_symlink() for path in root.rglob('*')):
        raise ValueError('Candidate contains symlinks')
    if {path.name for path in root.iterdir()} - {'result.json', 'build.log', 'output'}:
        raise ValueError('Unexpected candidate root files')
    raw = (root / 'result.json').read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Candidate report is too large')
    report = json.loads(raw)
    if (report.get('schema') != 1 or report.get('project') != 'domino'
            or report.get('repository') != 'KJaebye/domino' or report.get('ok') is not True
            or report.get('publication_allowed') is not False):
        raise ValueError('Expected a successful, unpublished Domino CI candidate')
    for key in ('source_sha', 'infra_sha'):
        if not re.fullmatch('[0-9a-f]{40}', report.get(key, '')):
            raise ValueError('Candidate has no pinned ' + key)
    if not re.fullmatch('sha256:[0-9a-f]{64}', report.get('image_id', '')):
        raise ValueError('Candidate has no pinned builder image')
    if not re.fullmatch(r'\d{8}T\d{6}Z-' + report['source_sha'][:12] + '-[0-9a-f]{6}', report.get('run_id', '')):
        raise ValueError('Candidate run identity differs from its source')
    expected = report.get('files')
    if not isinstance(expected, dict) or not expected:
        raise ValueError('Candidate output inventory is empty')
    for name, checksum in expected.items():
        safe_relative(name)
        if not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
            raise ValueError('Invalid candidate checksum')
    output = root / 'output'
    actual = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file()}
    if actual != expected:
        raise ValueError('Candidate output inventory or checksum differs')
    checks = json.loads((output / 'checks.json').read_text())
    if report.get('checks') != checks or checks.get('ok') is not True or checks.get('published') is not False:
        raise ValueError('Controller and container reports differ')
    if checks.get('mode') != report.get('mode') or checks.get('profile') != report.get('profile'):
        raise ValueError('Controller and container check scope differs')
    return report


def source_metadata(source):
    declarations = {}
    for node in ast.parse((source / 'src/domino_cli.py').read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('VERSION', 'BUILD_CHANNEL'):
                    declarations[target.id] = ast.literal_eval(node.value)
    return declarations['VERSION'], declarations.get('BUILD_CHANNEL', 'release')


def review(root, source, *, smoke=False):
    report = verify_inventory(root)
    source = source.resolve()
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != report['source_sha']:
        raise ValueError('Review source differs from the candidate source commit')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=all']):
        raise ValueError('Review source has tracked modifications')
    requested, channel = source_metadata(source)
    if requested != report['version'] or channel != report.get('build_channel'):
        raise ValueError('Candidate version or build channel differs from source')
    release = root / 'output/dist/release'
    manifest, _ = build_distribution.load_runtime(release)
    if manifest['version'] != requested or manifest.get('published') is not False:
        raise ValueError('Runtime manifest version or publication state differs')
    from_scripts = manifest.get('source_files', {})
    if not from_scripts or from_scripts.get('src/domino_cli.py') != digest(source / 'src/domino_cli.py'):
        raise ValueError('Candidate has no matching CLI source manifest')
    for name, checksum in from_scripts.items():
        safe_relative(name)
        path = source / name
        if not path.is_file() or digest(path) != checksum:
            raise ValueError('Artifact source manifest differs from pinned source: ' + name)
    if manifest.get('build_script_sha256') != digest(source / 'scripts/build_release.py'):
        raise ValueError('Candidate builder script differs from source')
    sdist = root / f'output/dist/pypi/domino_proxy-{requested}.tar.gz'
    if not sdist.is_file():
        raise ValueError('Candidate has no source distribution')
    distro = root / 'output/dist/distribution'
    distribution = json.loads((distro / 'distribution.json').read_text())
    if (distribution.get('version') != requested or distribution.get('apt_signed') is not False
            or distribution.get('release_manifest_sha256') != digest(release / 'release.json')):
        raise ValueError('Debian candidate is signed, mismatched or from another runtime')
    deb = distro / f'domino-proxy_{requested}-1_all.deb'
    if distribution.get('deb') != deb.name or not deb.is_file():
        raise ValueError('Debian candidate version differs')
    for name, checksum in distribution['files'].items():
        safe_relative(name)
        if digest(distro / name) != checksum:
            raise ValueError('Debian distribution inventory differs')
    names = {item['name'] for item in report['checks'].get('checks', []) if item.get('ok') is True}
    required = {'repository', 'install-test-package', 'full-regression', 'build-release',
                'verify-artifacts', 'verify-pip', 'build-sdist', 'verify-pypi-metadata', 'prepare-unsigned-apt'}
    blockers = []
    if report['profile'] != 'full' or not required.issubset(names) or any(item.get('ok') is not True for item in report['checks'].get('checks', [])):
        blockers.append('Full regression and all packaging checks are required')
    if report.get('mode') == 'release-candidate' and 'release-preflight' not in names:
        blockers.append('Stable channel preflight was not recorded by CI')
    if channel != 'release' or report.get('mode') != 'release-candidate':
        blockers.append('Development/ordinary CI builds cannot be published as stable releases')
    if smoke:
        previous = verify_artifacts.ROOT
        try:
            verify_artifacts.ROOT = source
            verify_artifacts.verify(release)
        finally:
            verify_artifacts.ROOT = previous
    return {'schema': 1, 'candidate_verified': True, 'publication_allowed': False,
            'eligible_for_release_preparation': not blockers, 'blockers': blockers,
            'version': requested, 'source_sha': sha, 'run_id': report['run_id'],
            'infra_sha': report['infra_sha'], 'image_id': report['image_id'],
            'profile': report['profile'], 'build_channel': channel,
            'report_sha256': digest(root / 'result.json'), 'deb_sha256': digest(deb),
            'source_distribution_sha256': digest(sdist), 'local_artifact_smoke': smoke,
            'not_tested': report['checks'].get('not_tested', [])}


def preflight():
    """Public-channel reads only; never rebuild an already distributed version."""
    root = Path(__file__).resolve().parents[1]
    requested, channel = source_metadata(root)
    release_channels.version(requested)
    if channel != 'release':
        raise ValueError('Stable candidates require BUILD_CHANNEL = release')
    if release_channels.api('repos/KJaebye/domino/releases/tags/v' + requested, missing=True) is not None:
        raise ValueError('This version already has a GitHub release/draft; reuse its original inputs')
    if release_channels.fetch('https://pypi.org/pypi/domino-proxy/' + requested + '/json', missing=True) is not None:
        raise ValueError('This version is already on PyPI; original files must not be rebuilt')
    apt = release_channels.fetch('https://raw.githubusercontent.com/KJaebye/domino-apt/main/channel.json', missing=True)
    if apt is not None and release_channels.version_tuple(json.loads(apt)['version']) >= release_channels.version_tuple(requested):
        raise ValueError('APT already distributes this or a newer version')
    formula = release_channels.fetch('https://raw.githubusercontent.com/KJaebye/homebrew-tap/main/Formula/domino.rb', missing=True)
    if formula is not None:
        values = re.findall(r'^  version "(' + release_channels.VERSION + r')"$', formula.decode(), re.M)
        if len(values) != 1 or release_channels.version_tuple(values[0]) >= release_channels.version_tuple(requested):
            raise ValueError('Homebrew formula is unrecognized or already distributes this/newer version')
    return {'version': requested, 'unpublished': True, 'publication_allowed': False}


def doctor(directory):
    """Inspect layout and Keychain item metadata; never retrieve secret values."""
    directory = directory.expanduser()
    config = directory / 'state.json'
    home = directory / 'gnupg'
    state = json.loads(config.read_text()) if config.is_file() else {}
    def item_visible(service, account):
        if sys.platform != 'darwin' or not shutil.which('security'):
            return None
        return subprocess.run(['security', 'find-generic-password', '-s', service, '-a', account],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
    pypi = item_visible('https://upload.pypi.org/legacy/', '__token__')
    apt = item_visible(state.get('keychain_service', 'domino-release/apt'),
                       state.get('keychain_username', 'signing-passphrase'))
    layout = (config.is_file() and directory.is_dir() and not directory.stat().st_mode & 0o077
              and home.is_dir() and not home.is_symlink() and not home.stat().st_mode & 0o077)
    identity = False
    expected = '8704BE99B201383E16246ED9099855D35D066EE8'
    if layout and state.get('apt_fingerprint') == expected and shutil.which('gpg'):
        listing = subprocess.run(['gpg', '--homedir', str(home), '--batch', '--with-colons',
                                  '--list-secret-keys', expected], capture_output=True, text=True, timeout=20)
        identity = listing.returncode == 0 and expected in listing.stdout
    app = Path.home() / '.local/share/domino-agent/state.json'
    blockers = []
    if pypi is not True:
        blockers.append('The project PyPI Keychain item is not visible; configure/unlock it locally')
    if not layout or not identity:
        blockers.append('Restore the existing restricted APT signing directory and pinned signing identity')
    if apt is not True:
        blockers.append('The APT signing-passphrase Keychain item is not visible')
    return {'schema': 1, 'production_secrets_read': False, 'published': False,
            'pypi_keychain_item_visible': pypi, 'apt_passphrase_item_visible': apt,
            'apt_credentials_layout_valid': bool(layout), 'existing_apt_signing_identity_present': identity,
            'github_app_metadata_present': app.is_file(),
            'publication_credentials_ready': not blockers, 'blockers': blockers,
            'source_submission_note': 'Use the authenticated local GitHub account for authorized branch pushes and PRs; preserve main review requirements'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['review', 'preflight', 'doctor'])
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--credentials-dir', type=Path, default=Path.home() / '.local/share/domino-release')
    args = parser.parse_args()
    if args.operation == 'preflight':
        result = preflight()
    elif args.operation == 'doctor':
        result = doctor(args.credentials_dir)
    else:
        if not args.candidate or not args.source:
            parser.error('review requires --candidate and --source')
        result = review(args.candidate, args.source, smoke=args.smoke)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as output:
            output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
