"""Offline upgrades in disposable user venvs; no real proxy or service changes."""
from contextlib import redirect_stderr, redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import domino_cli as cli
import domino_cli_sync as sync


INSTALLER = b'''import shutil, sys
from pathlib import Path
stage=Path(sys.argv[2]);home=Path.home();app=home/'.local/share/domino/cli'
if app.exists(): shutil.rmtree(app)
shutil.copytree(stage/'cli',app)
launcher=home/'.local/bin/domino';launcher.parent.mkdir(parents=True,exist_ok=True)
if not launcher.exists():
 launcher.write_text('#!/usr/bin/env python3\\n# Managed by Domino CLI\\nimport sys,runpy\\nsys.path.insert(0,'+repr(str(app))+')\\nrunpy.run_module("domino_cli",run_name="__main__")\\n')
 launcher.chmod(0o700)
'''
INSTALLER = (b"import json,sys\nfrom pathlib import Path\ndef subscription_arguments(parser): pass\n"
             b"if __name__ == '__main__' and sys.argv[1:2] == ['proxy']:\n"
             b" (Path.home()/'proxy-on').write_text('on')\n"
             b" print(json.dumps({'supported':True,'routing':'domino'}));raise SystemExit(0)\n"
             b"if __name__ == '__main__':\n" +
             b'\n'.join(b' ' + line for line in INSTALLER.splitlines()) + b'\n')


class CLISyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='domino-sync-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {'HOME': str(self.home), 'PIP_NO_INDEX': '1',
                                                  'PIP_DISABLE_PIP_VERSION_CHECK': '1'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.out = io.StringIO()
        self.redirect = redirect_stdout(self.out)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.stage = self.root / 'stage'
        (self.stage / 'cli').mkdir(parents=True)
        for name, content in self.files(cli.VERSION).items():
            (self.stage / 'cli' / name).write_bytes(content)
        (self.stage / 'install_domino.py').write_bytes(INSTALLER)
        (self.stage / 'manifest.json').write_text('{"schema":1}')
        self.sender_wheel = self.wheel(cli.VERSION, self.stage)
        self.launcher = self.home / '.local/bin/domino'
        self.runtime = self.home / '.local/share/domino/cli'

    def files(self, version):
        files = {name: Path(cli.__file__).with_name(name).read_bytes() for name in cli.CLI_MODULES}
        files['domino_cli.py'] = files['domino_cli.py'].replace(
            f"VERSION = '{cli.VERSION}'".encode(), f"VERSION = '{version}'".encode())
        files['install_domino.py'] = INSTALLER
        return files

    def wheel(self, version, root):
        return sync.make_wheel(self.files(version), root / f'domino_proxy-{version}-py3-none-any.whl',
                               version, sync.license_text())

    def seed_package(self, version):
        # Mirror the pipx location and exposed symlink from the reported failure.
        self.venv = self.home / '.local/share/pipx/venvs/domino-proxy'
        subprocess.run([sys.executable, '-m', 'venv', str(self.venv)], check=True,
                       capture_output=True, text=True, timeout=45)
        self.python = self.venv / 'bin/python'
        wheel = self.wheel(version, self.root)
        subprocess.run([str(self.python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)],
                       check=True, capture_output=True, text=True, timeout=30)
        if version == '0.17.8':
            (self.venv / 'bin/domino').write_text(
                f'#!{self.python}\nimport sys\nfrom domino_cli import main\nsys.exit(main())\n')
        self.launcher.parent.mkdir(parents=True, exist_ok=True)
        self.launcher.symlink_to(self.venv / 'bin/domino')
        self.keep = self.venv / 'keep-user-files'
        self.keep.write_text('keep')

    def seed_runtime(self, version):
        self.runtime.mkdir(parents=True)
        for name, content in self.files(version).items():
            (self.runtime / name).write_bytes(content)

    def actual_version(self):
        return subprocess.check_output([str(self.launcher), '--version'], text=True, timeout=15).strip()

    def test_old_pipx_entry_upgrades_offline_and_keeps_its_symlink(self):
        self.seed_package('0.17.8')
        self.seed_runtime('1.0.2')
        target = os.readlink(self.launcher)
        self.assertEqual(self.actual_version(), '0.17.8')
        sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), cli.VERSION)
        self.assertEqual(os.readlink(self.launcher), target)
        self.assertEqual(self.keep.read_text(), 'keep')
        self.assertIn('0.17.8 → ' + cli.VERSION, self.out.getvalue())
        self.assertIn('目标 CLI 已核验', self.out.getvalue())

    def test_newer_package_is_not_downgraded_and_supplies_newer_runtime(self):
        self.seed_package('9.0.0')
        self.seed_runtime('0.17.8')
        before = (self.venv / 'bin/domino').read_bytes()
        sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), '9.0.0')
        self.assertEqual(sync.source_version(self.runtime / 'domino_cli.py'), '9.0.0')
        self.assertEqual((self.venv / 'bin/domino').read_bytes(), before)
        self.assertEqual(json.loads((self.stage / 'manifest.json').read_text())['cli_version'], '9.0.0')

    def test_newer_runtime_upgrades_an_older_package_without_being_downgraded(self):
        self.seed_package('0.17.8')
        self.seed_runtime('9.0.0')
        sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), '9.0.0')
        self.assertEqual(sync.source_version(self.runtime / 'domino_cli.py'), '9.0.0')

    def test_equal_version_skips_package_reinstallation(self):
        self.seed_package(cli.VERSION)
        with patch.object(sync, 'checked_run', wraps=sync.checked_run) as run:
            sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertFalse(any('pip' in call.args[0] and 'install' in call.args[0] for call in run.call_args_list))
        self.assertEqual(self.actual_version(), cli.VERSION)

    def test_package_upgrade_failure_reports_partial_state_instead_of_success(self):
        self.seed_package('0.17.8')
        original = sync.checked_run
        def run(argv, **kwargs):
            if 'pip' in argv and 'install' in argv:
                raise sync.SyncError('目标 CLI 更新失败')
            return original(argv, **kwargs)
        with patch.object(sync, 'checked_run', side_effect=run), self.assertRaisesRegex(sync.SyncError, 'CLI 更新失败'):
            sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), '0.17.8')
        self.assertEqual(sync.source_version(self.runtime / 'domino_cli.py'), cli.VERSION)
        self.assertNotIn('目标 CLI 已核验', self.out.getvalue())

    def test_first_standalone_deploy_is_verified(self):
        sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), cli.VERSION)
        self.assertTrue((self.home / 'proxy-on').is_file())
        report = json.loads((self.stage / 'deployment-summary.json').read_text())
        self.assertTrue(report['system_proxy_enabled'])

    def test_streamed_program_preserves_request_stdin_and_removes_its_source(self):
        program = 'import json,sys;print(json.dumps({"value":json.load(sys.stdin)["value"],"path":__file__}))'
        command = lambda source, tty=False: ['sh', '-c', source]
        argv = sync.streamed_remote_argv(command, program, 'agent', [], False)
        self.assertTrue(all(len(value.encode()) < 128 * 1024 for value in argv))
        result = subprocess.run(argv, input='{"value":42}', capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response['value'], 42)
        self.assertFalse(Path(response['path']).exists())

    def test_system_proxy_state_is_verified_and_batch_flag_is_forwarded(self):
        for supported, routing in [(True, 'domino'), (False, 'unsupported')]:
            with self.subTest(supported=supported), patch.object(sync, 'checked_run', return_value=json.dumps(
                    {'supported': supported, 'routing': routing})) as run:
                result = sync.connect_system_proxy(sys.executable, self.stage, batch=True)
                self.assertEqual(result['system_proxy_enabled'], supported)
                self.assertIn('--non-interactive', run.call_args.args[0])

    def test_failed_or_unconfirmed_proxy_never_completes_deployment(self):
        for response in ['{}', '[]', 'invalid', '{"supported":true,"routing":"off"}']:
            with self.subTest(response=response), patch.object(sync, 'checked_run', return_value=response), \
                    self.assertRaisesRegex(sync.SyncError, '系统代理未接通'):
                sync.connect_system_proxy(sys.executable, self.stage)
        original = sync.checked_run
        def run(command, **kwargs):
            if 'proxy' in command:
                raise sync.SyncError('测试接通失败')
            return original(command, **kwargs)
        with patch.object(sync, 'checked_run', side_effect=run), self.assertRaisesRegex(sync.SyncError, '系统代理未接通'):
            sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertFalse((self.stage / 'deployment-summary.json').exists())

    def test_compact_output_hides_install_chatter_but_preserves_authentication_channel(self):
        (self.stage / 'install_domino.py').write_bytes(INSTALLER + '''
if __name__ == '__main__':
 print('INSTALLER-DETAIL')
 print('代理出网校验通过；出口地区：JP')
 print('fixture sudo password prompt',file=sys.stderr)
'''.encode())
        code = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                'import domino_cli_sync as sync;sync.deploy(Path(sys.argv[2]),sys.argv[3],'
                'home=Path(sys.argv[4]),verbose=False)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(Path(sync.__file__).parent),
                                 str(self.stage), cli.VERSION, str(self.home)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('INSTALLER-DETAIL', result.stdout)
        self.assertIn('fixture sudo password prompt', result.stderr)
        self.assertIn('服务与出网检查', result.stdout)
        self.assertNotIn(str(self.launcher), result.stdout)
        report = json.loads((self.stage / 'deployment-summary.json').read_text())
        self.assertEqual(report['exit_country'], 'JP')
        self.assertEqual(report['cli_version'], cli.VERSION)

    def test_compact_failure_replays_installer_diagnostics_without_reporting_success(self):
        (self.stage / 'install_domino.py').write_text('print("fixture failure detail")\nraise SystemExit(1)\n')
        error = io.StringIO()
        with redirect_stderr(error), self.assertRaises(sync.SyncError):
            sync.deploy(self.stage, cli.VERSION, home=self.home, verbose=False)
        self.assertIn('fixture failure detail', error.getvalue())
        self.assertFalse((self.stage / 'deployment-summary.json').exists())

    def test_verbose_keeps_installer_details(self):
        (self.stage / 'install_domino.py').write_bytes(INSTALLER + b'\nif __name__ == "__main__": print("INSTALLER-DETAIL")\n')
        code = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                'import domino_cli_sync as sync;sync.deploy(Path(sys.argv[2]),sys.argv[3],'
                'home=Path(sys.argv[4]),verbose=True)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(Path(sync.__file__).parent),
                                 str(self.stage), cli.VERSION, str(self.home)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('INSTALLER-DETAIL', result.stdout)
        self.assertIn('目标 CLI 已核验', result.stdout)

    def test_runtime_install_failure_does_not_upgrade_the_package(self):
        self.seed_package('0.17.8')
        (self.stage / 'install_domino.py').write_text('raise SystemExit(1)\n')
        with self.assertRaisesRegex(sync.SyncError, '目标运行环境部署失败'):
            sync.deploy(self.stage, cli.VERSION, home=self.home)
        self.assertEqual(self.actual_version(), '0.17.8')
        self.assertFalse(self.runtime.exists())
        self.assertNotIn('目标 CLI 已核验', self.out.getvalue())

    def test_unrelated_and_unknown_environment_launchers_are_rejected_before_install(self):
        self.launcher.parent.mkdir(parents=True)
        for content in ['#!/bin/sh\necho unrelated\n',
                        '#!/usr/bin/python3\nfrom domino_cli import main\nsys.exit(main())\n']:
            self.launcher.write_text(content)
            with self.subTest(content=content), self.assertRaises(sync.SyncError):
                sync.deploy(self.stage, cli.VERSION, home=self.home)
            self.assertFalse(self.runtime.exists())
            self.assertEqual(self.launcher.read_text(), content)

    def test_parallel_sync_is_rejected_before_preparing_or_installing(self):
        lock = self.home / '.local/share/domino-cli-sync.lock'
        lock.parent.mkdir(parents=True)
        with lock.open('w') as handle, patch.object(sync, '_deploy') as deploy:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(sync.SyncError, '另一个 CLI 同步'):
                sync.deploy(self.stage, cli.VERSION, home=self.home)
            deploy.assert_not_called()

    def test_runtime_wheel_reads_only_declared_modules(self):
        root = self.stage / 'cli'
        (root / 'private.py').write_text('do not include')
        self.assertEqual(set(sync.module_files(root)), set(cli.CLI_MODULES))
        content = (root / 'domino_cli.py').read_text().replace("'domino_cli_sync.py'", "'../private.py'")
        (root / 'domino_cli.py').write_text(content)
        with self.assertRaises(sync.SyncError):
            sync.module_files(root)

    def test_wheel_inputs_and_version_are_checked_and_license_is_included(self):
        with zipfile.ZipFile(self.sender_wheel) as archive:
            info = f'domino_proxy-{cli.VERSION}.dist-info'
            self.assertIn(f'Version: {cli.VERSION}', archive.read(info + '/METADATA').decode())
            self.assertIn(info + '/licenses/LICENSE', archive.namelist())
            self.assertEqual(set(cli.CLI_MODULES), {name for name in archive.namelist() if '/' not in name})
        with self.assertRaises(sync.SyncError):
            sync.make_wheel({'private/config.json': b'private'}, self.root / 'bad.whl', cli.VERSION, b'license')
        with self.assertRaises(sync.SyncError):
            sync.make_wheel(self.files('0.17.8'), self.root / 'bad.whl', cli.VERSION, b'license')
        self.assertGreater(sync.version_key('1.10.0'), sync.version_key('1.9.9'))


if __name__ == '__main__':
    unittest.main()
