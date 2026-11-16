#!/usr/bin/env python3
"""Install the built wheel into a disposable venv; no service initialization.

pip resolves declared dependencies using the configured public package index.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def verify(release):
    manifest = json.loads((release / 'release.json').read_text())
    version = manifest['version']
    wheel = release / next(item['name'] for item in manifest['files'] if item['name'].endswith('.whl'))
    with tempfile.TemporaryDirectory(prefix='domino-pip-') as directory:
        root = Path(directory)
        home = root / 'home'
        home.mkdir()
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('DOMINO_', '_DOMINO', 'PYTHONPATH'))}
        environment.update(HOME=str(home), PIP_CACHE_DIR=str(root / 'cache'), NO_COLOR='1', TERM='dumb')
        venv.EnvBuilder(with_pip=True).create(root / 'venv')
        binary = root / 'venv/bin'
        def run(command):
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stderr[-2000:])
            return result.stdout
        run([str(binary / 'python'), '-m', 'pip', 'install', '--disable-pip-version-check', str(wheel)])
        run([str(binary / 'python'), '-m', 'pip', 'check'])
        assert run([str(binary / 'domino'), '--version']).strip() == version
        assert 'usage:' in run([str(binary / 'domino'), '--help'])
        assert 'usage:' in run([str(binary / 'domino-install'), '--help'])
        assert json.loads(run([str(binary / 'domino'), 'shell', 'status', '--json']))['policy_only']
        assert json.loads(run([str(binary / 'domino'), '--output', 'json', 'capabilities']))['data']['application_version'] == version
        run([str(binary / 'python'), '-I', '-c', 'import prompt_toolkit,yaml,domino_install; assert not domino_install.domino_cli.PACKAGE_MANAGED'])
        assert not list(home.iterdir()), 'CLI smoke changed HOME'
        run([str(binary / 'python'), '-m', 'pip', 'uninstall', '-y', 'domino-proxy'])
        assert not (binary / 'domino').exists() and not (binary / 'domino-install').exists()
        assert not list(home.iterdir()), 'Package removal changed HOME'
    return {'version': version, 'ok': True, 'wheel_install_dependencies_and_remove': True,
            'isolated_venv': True, 'configuration_unchanged': True, 'native_install_changed': False}


if __name__ == '__main__':
    report = verify(ROOT / 'dist/release')
    (ROOT / 'dist/pip-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
