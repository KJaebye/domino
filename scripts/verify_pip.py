#!/usr/bin/env python3
"""Install the built wheel into a disposable venv; no service initialization.

pip resolves declared dependencies using the configured public package index.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from package_home import seed, snapshot, unchanged

ROOT = Path(__file__).resolve().parents[1]


def verify(release, previous_release=None):
    release = release.resolve()
    previous_release = previous_release.resolve() if previous_release else None
    manifest = json.loads((release / 'release.json').read_text())
    version = manifest['version']
    wheel = release / next(item['name'] for item in manifest['files'] if item['name'].endswith('.whl'))
    with tempfile.TemporaryDirectory(prefix='domino-pip-') as directory:
        root = Path(directory)
        home = root / 'home'
        home.mkdir()
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('DOMINO_', '_DOMINO', 'PYTHONPATH'))}
        environment.update(HOME=str(home), PIP_CACHE_DIR=str(root / 'cache'),
                           CARGO_HOME=str(root / 'cargo'), RUSTUP_HOME=str(root / 'rustup'),
                           NO_COLOR='1', TERM='dumb')
        venv.EnvBuilder(with_pip=True).create(root / 'venv')
        binary = root / 'venv/bin'
        def run(command):
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr[-2000:])
            return result.stdout
        previous_version = None
        initial_wheel = wheel
        if previous_release:
            previous = json.loads((previous_release / 'release.json').read_text())
            previous_version = previous['version']
            from packaging.version import Version
            assert Version(previous_version) < Version(version), 'Upgrade baseline must be an older release'
            initial_wheel = previous_release / next(item['name'] for item in previous['files']
                                                    if item['name'].endswith('.whl'))
        run([str(binary / 'python'), '-m', 'pip', 'install', '--disable-pip-version-check', str(initial_wheel)])
        assert run([str(binary / 'domino'), '--version']).strip() == (previous_version or version)
        # pip/platform cache files belong to installation, not a subsequent CLI query.
        assert not any((home / path).exists() for path in ['.config/domino', '.local/share/domino',
                       'Library/LaunchAgents/local.domino.mihomo.plist']), 'Package install initialized Domino'
        seed(home)
        baseline = snapshot(home)
        if previous_release:
            run([str(binary / 'python'), '-m', 'pip', 'install', '--disable-pip-version-check',
                 '--upgrade', str(wheel)])
            unchanged(home, baseline, 'Package upgrade')
        run([str(binary / 'python'), '-m', 'pip', 'check'])
        def query(args):
            output = run(args)
            unchanged(home, baseline, 'Query ' + ' '.join(Path(value).name if i == 0 else value for i, value in enumerate(args)))
            return output
        assert query([str(binary / 'domino'), '--version']).strip() == version
        assert 'usage:' in query([str(binary / 'domino'), '--help'])
        assert 'usage:' in query([str(binary / 'domino-install'), '--help'])
        assert json.loads(query([str(binary / 'domino'), 'shell', 'status', '--json']))['policy_only']
        assert json.loads(query([str(binary / 'domino'), '--output', 'json', 'capabilities']))['data']['application_version'] == version
        run([str(binary / 'python'), '-I', '-c', 'import prompt_toolkit,yaml,domino_install; assert not domino_install.domino_cli.PACKAGE_MANAGED'])
        unchanged(home, baseline, 'CLI and dependency import')
        run([str(binary / 'python'), '-m', 'pip', 'uninstall', '-y', 'domino-proxy'])
        assert not (binary / 'domino').exists() and not (binary / 'domino-install').exists()
        unchanged(home, baseline, 'Package removal')
    return {'version': version, 'ok': True, 'wheel_install_dependencies_and_remove': True,
            'upgraded_from': previous_version,
            'isolated_venv': True, 'configuration_unchanged': True, 'native_install_changed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--previous-release', type=Path, help='Optional older release to exercise a real pip upgrade')
    args = parser.parse_args()
    report = verify(args.release, args.previous_release)
    (ROOT / 'dist/pip-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
