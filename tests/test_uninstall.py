from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import pwd
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import domino_cli as cli
import domino_completion as completion
import domino_macos as mac
import domino_uninstall as uninstall
import domino_tui as ui
import install_domino as ctx


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.app = self.home / '.local/share/domino'
        self.backups = self.home / '.local/share/domino-backups'
        self.service = self.root / 'system/domino.service'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.temp.cleanup)
        for key, value in [('HOME', self.home), ('APP', self.app), ('BACKUPS', self.backups), ('SERVICE', self.service)]:
            self.stack.enter_context(patch.object(ctx, key, value))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.calls = []
        self.run = self.stack.enter_context(patch.object(ctx, 'run', side_effect=lambda *a, **k: self.calls.append('auth')))
        self.proxy = self.stack.enter_context(patch.object(ctx, 'system_proxy', side_effect=lambda *a, **k: self.calls.append('proxy')))
        self.sudo = self.stack.enter_context(patch.object(ctx, 'sudo', side_effect=self.fake_sudo))
        self.stop = self.stack.enter_context(patch.object(mac, 'stop', side_effect=lambda *a: self.calls.append('stop')))
        self.stack.enter_context(patch.object(mac, 'launch', side_effect=AssertionError('Unexpected launchctl access')))

    def fake_sudo(self, *args):
        self.calls.append(args)
        if args[:2] == ('rm', '-f'):
            self.service.unlink()

    def seed(self, system='linux', package=False):
        self.stack.enter_context(patch.object(uninstall.sys, 'platform', system))
        for directory in (self.app / 'data', self.backups, self.home / '.config/domino',
                          self.home / ('Library/Caches/domino' if system == 'darwin' else '.cache/domino')):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'test-data').write_text('private fixture')
        (self.app / 'data/config.json').write_text('{}')
        (self.app / 'mihomo').write_text('fixture')
        self.user_text = '#!/bin/sh\nexport MY_SETTING=kept\n'
        for name in ('.bashrc', '.zshrc', '.vscode-server/server-env-setup'):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.user_text + ctx.BEGIN + '\nsource domino\n' + ctx.END + '\n')
            path.chmod(0o640)
        (self.home / '.zshrc').write_text((self.home / '.zshrc').read_text() +
            '# >>> Domino completion >>>\nsource completion\n# <<< Domino completion <<<\n')
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('from domino_install import package_cli\n' if package else ctx.CLI_MARKER + '\n')
        if system == 'darwin':
            service, logs = mac.paths(self.home)
            service.parent.mkdir(parents=True)
            service.write_bytes(plistlib.dumps({'Label': mac.LABEL, 'DominoManaged': 1,
                'ProgramArguments': [str(self.app / 'mihomo')]}))
            logs.mkdir(parents=True)
            (logs / 'mihomo.log').write_text('fixture')
        else:
            self.service.parent.mkdir()
            self.service.write_text(ctx.unit_text(pwd.getpwuid(os.getuid()).pw_name, 'fixture'))
        return launcher

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_linux_removes_owned_runtime_and_only_managed_shell_blocks(self):
        launcher = self.seed()
        unrelated = self.home / '.config/another-app/settings'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('keep')
        uninstall.uninstall(ctx, yes=True, non_interactive=True)
        self.assertEqual(self.calls[:3], ['auth', 'proxy', ('systemctl', 'disable', '--now', 'domino.service')])
        self.assertFalse(self.service.exists())
        self.assertFalse(self.app.exists())
        self.assertFalse(self.backups.exists())
        self.assertFalse((self.home / '.config/domino').exists())
        self.assertFalse((self.home / '.cache/domino').exists())
        self.assertFalse(launcher.exists())
        self.assertEqual(unrelated.read_text(), 'keep')
        for name in ('.bashrc', '.zshrc', '.vscode-server/server-env-setup'):
            path = self.home / name
            self.assertEqual(path.read_text(), self.user_text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertTrue((self.home / '.local/share/domino.lock').is_file())

    def test_macos_restores_proxy_before_bootout_and_cleans_agent_logs_cache(self):
        self.seed('darwin')
        uninstall.uninstall(ctx, yes=True)
        self.assertEqual(self.calls, ['proxy', 'stop'])
        self.run.assert_not_called()
        self.sudo.assert_not_called()
        for p in (*mac.paths(self.home), self.home / 'Library/Caches/domino', self.app):
            self.assertFalse(p.exists())

    def test_preview_is_read_only_without_password_process_or_lock(self):
        self.seed()
        before = self.snapshot()
        uninstall.uninstall(ctx, dry_run=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_crlf_shell_content_outside_markers_is_byte_preserved(self):
        self.seed()
        path = self.home / '.bashrc'
        user = b'export MY_SETTING=kept\r\n# trailing comment\r\n'
        path.write_bytes(user + (ctx.BEGIN+'\r\nsource domino\r\n'+ctx.END+'\r\n').encode())
        uninstall.uninstall(ctx, yes=True)
        self.assertEqual(path.read_bytes(), user)

    def test_cancel_or_missing_confirmation_does_not_change_any_files(self):
        self.seed()
        before = self.snapshot()
        with self.assertRaises(ctx.InstallError):
            uninstall.uninstall(ctx, non_interactive=True)
        with patch.object(uninstall.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='n'):
            with self.assertRaises(ctx.InstallError):
                uninstall.uninstall(ctx)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_foreign_service_and_other_users_service_are_preserved(self):
        self.seed()
        original = self.service.read_text()
        for text in ('[Service]\nExecStart=/bin/other\n', original.replace('User='+pwd.getpwuid(os.getuid()).pw_name, 'User=another-user'),
                     original.replace(str(self.app / 'mihomo'), '/opt/other/mihomo')):
            self.service.write_text(text)
            before = self.snapshot()
            with self.assertRaises(ctx.InstallError): uninstall.uninstall(ctx, yes=True)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.calls, [])

    def test_malformed_markers_abort_before_proxy_or_service_changes(self):
        self.seed()
        (self.home / '.bashrc').write_text(ctx.BEGIN+'\nkeep me\n')
        before = self.snapshot()
        with self.assertRaises(ctx.InstallError): uninstall.uninstall(ctx, yes=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_symlinked_paths_are_not_followed_or_removed(self):
        self.seed()
        external = self.root / 'external'
        external.mkdir()
        (external / 'important').write_text('keep')
        import shutil
        shutil.rmtree(self.backups)
        self.backups.symlink_to(external, target_is_directory=True)
        with self.assertRaises(ctx.InstallError): uninstall.uninstall(ctx, yes=True)
        self.assertEqual((external / 'important').read_text(), 'keep')
        self.assertTrue(self.app.exists())
        self.assertEqual(self.calls, [])

    def test_proxy_failure_preserves_service_configuration_and_shell_files(self):
        self.seed()
        before = self.snapshot()
        self.proxy.side_effect = ctx.InstallError('Cannot restore proxy')
        with self.assertRaises(ctx.InstallError): uninstall.uninstall(ctx, yes=True)
        self.assertTrue(self.service.exists())
        for name, data in before.items(): self.assertEqual((self.root / name).read_bytes(), data)
        self.sudo.assert_not_called()

    def test_stop_failure_preserves_files(self):
        self.seed()
        before = self.snapshot()
        self.sudo.side_effect = ctx.InstallError('Cannot stop service')
        with self.assertRaises(ctx.InstallError): uninstall.uninstall(ctx, yes=True)
        for name, data in before.items(): self.assertEqual((self.root / name).read_bytes(), data)

    def test_package_launcher_and_symlink_are_preserved(self):
        launcher = self.seed(package=True)
        before = launcher.read_bytes()
        uninstall.uninstall(ctx, yes=True)
        self.assertEqual(launcher.read_bytes(), before)
        launcher.unlink()
        target = self.root / 'pipx-domino'
        target.write_text('package entry')
        launcher.symlink_to(target)
        uninstall.uninstall(ctx, yes=True)
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(target.read_text(), 'package entry')

    def test_repeated_uninstall_succeeds_without_stale_runtime(self):
        self.seed()
        uninstall.uninstall(ctx, yes=True)
        self.calls.clear()
        uninstall.uninstall(ctx, yes=True)
        self.assertEqual(self.calls, [])


class UninstallRoutingTests(unittest.TestCase):
    def test_ui_uses_menu_before_destructive_foreground_confirmation(self):
        workspace = object.__new__(ui.Workspace)
        workspace.state = Mock()
        workspace.menu = Mock()
        workspace.queue = Mock()
        workspace.dispatch('/uninstall')
        workspace.menu.assert_called_once()
        workspace.queue.assert_not_called()
        workspace.dispatch('/uninstall --dry-run')
        self.assertEqual(workspace.queue.call_args.args, ('卸载预览', 'uninstall', '--dry-run'))
        workspace.dispatch('/uninstall --confirm')
        self.assertEqual(workspace.queue.call_args.args, ('卸载 Domino', 'uninstall'))
        self.assertTrue(workspace.queue.call_args.kwargs['foreground'])

    def remote_argv(self, ssh, *options):
        original = cli.remote_source
        def isolated(source):
            return original(source).replace("SERVICE = Path('/etc/systemd/system/domino.service')",
                "SERVICE = Path.home() / 'fixture-system/domino.service'")
        with patch.object(cli, 'remote_source', side_effect=isolated):
            return ssh.action_argv('uninstall', *options)

    def test_local_and_remote_flags_route_to_current_backend(self):
        for target in ([], ['alice@host']):
            with patch.object(cli, 'run') as run, patch.object(cli, 'SSH') as ssh:
                self.assertEqual(cli.main([*target, 'uninstall', '--yes', '--batch']), 0)
                if target:
                    call = ssh.return_value.__enter__.return_value.action.call_args
                    args = call.args
                    self.assertFalse(call.kwargs['tty'])
                    run.assert_not_called()
                else:
                    args = run.call_args.args[0][2:]
                    ssh.assert_not_called()
                self.assertEqual(args[0], 'uninstall')
                self.assertIn('--yes', args)
                self.assertIn('--non-interactive', args)
        self.assertIn('uninstall', completion.candidates(['un'])[1])

    def test_preview_does_not_enter_agent_protocol(self):
        for target in ([], ['alice@host']):
            with patch.object(cli, 'run') as run, patch.object(cli, 'SSH') as ssh:
                self.assertEqual(cli.main([*target, 'uninstall', '--dry-run', '--batch']), 0)
                if target:
                    args = ssh.return_value.__enter__.return_value.action.call_args.args
                else:
                    args = run.call_args.args[0][2:]
                self.assertEqual(args[0], 'uninstall')
                self.assertIn('--dry-run', args)
                self.assertNotIn('--yes', args)

    def test_remote_payload_preview_works_without_installed_cli(self):
        args = cli.build_parser().parse_args(['alice@host', 'uninstall', '--dry-run', '--batch'])
        ssh = cli.SSH(args)
        ssh.command_argv = lambda command, tty=False: ['sh', '-c', command]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith(('DOMINO_', '_DOMINO'))}
            env['HOME'] = str(home)
            result = subprocess.run(self.remote_argv(ssh, '--dry-run', '--non-interactive'),
                cwd=directory, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('预览', result.stdout)
            self.assertEqual(list(home.iterdir()), [])

    def test_remote_payload_removes_partial_fixture_and_preserves_user_rc(self):
        args = cli.build_parser().parse_args(['alice@host', 'uninstall', '--yes', '--batch'])
        ssh = cli.SSH(args)
        ssh.command_argv = lambda command, tty=False: ['sh', '-c', command]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            app = home / '.local/share/domino'
            app.mkdir(parents=True)
            (app / 'fixture').write_text('partial install')
            rc = home / '.bashrc'
            rc.write_text('export KEEP=1\n'+ctx.BEGIN+'\nmanaged\n'+ctx.END+'\n')
            env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH' and not k.startswith(('DOMINO_', '_DOMINO'))}
            env['HOME'] = str(home)
            result = subprocess.run(self.remote_argv(ssh, '--yes', '--non-interactive'),
                cwd=directory, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(app.exists())
            self.assertEqual(rc.read_text(), 'export KEEP=1\n')

