from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import install_domino as remote
import domino_cli as tool
import domino_shell as shell
import domino_subscriptions as subscriptions


class EnvironmentTests(unittest.TestCase):
    def test_managed_block_preserves_shebang_and_is_idempotent(self):
        original = '#!/bin/sh\nexport KEEP=1\n'
        value = remote.managed_block(original, 'export PROXY=1')
        self.assertTrue(value.startswith('#!/bin/sh\n'))
        self.assertIn('export KEEP=1', value)
        self.assertEqual(remote.managed_block(value, 'export PROXY=1'), value)
        self.assertEqual(value.count(remote.BEGIN), 1)

    def test_malformed_blocks_are_not_rewritten(self):
        for old in [remote.BEGIN, remote.END, remote.END + '\n' + remote.BEGIN]:
            with self.subTest(old=old), self.assertRaises(remote.InstallError):
                remote.managed_block(old, 'export A=1')

    def test_process_match_excludes_robotics_and_other_users(self):
        home = Path('/home/nvidia')
        yes = [['/usr/bin/node', '/home/nvidia/.vscode-server/cli/servers/X/server/out/server-main.js'],
               ['/home/nvidia/.vscode-server/code-hash', 'command-shell'],
               ['/home/nvidia/.vscode-server/extensions/openai.chatgpt-x/bin/codex', 'app-server']]
        no = [['/opt/ros/humble/bin/robot', '--config', '/home/nvidia/.vscode-server/settings.json'],
              ['/home/other/.vscode-server/code-hash', 'command-shell'],
              ['/home/nvidia/workspace/codex', 'app-server'],
              ['/usr/bin/robot', 'command-shell', '/home/nvidia/.vscode-server/settings.json']]
        for argv in yes:
            self.assertTrue(remote.vscode_target(argv, home), argv)
        for argv in no:
            self.assertFalse(remote.vscode_target(argv, home), argv)


class FakeSocket:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def connect_ex(self, address):
        return 1


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.app = self.home / '.local/share/domino'
        self.backups = self.home / '.local/share/domino-backups'
        self.service = self.root / 'system/domino.service'
        self.service.parent.mkdir()
        self.state = {'active': False, 'enabled': False}
        self.legacy_app = self.home / '.local/share/robot-clash'
        self.legacy_backups = self.home / '.local/share/robot-clash-backups'
        self.legacy_service = self.service.with_name('robot-clash.service')
        self.legacy_state = {'active': False, 'enabled': False}
        self.stack = ExitStack()
        for name, value in [('HOME', self.home), ('APP', self.app), ('BACKUPS', self.backups), ('SERVICE', self.service),
                            ('LEGACY_APP', self.legacy_app), ('LEGACY_BACKUPS', self.legacy_backups),
                            ('LEGACY_SERVICE', self.legacy_service)]:
            self.stack.enter_context(patch.object(remote, name, value))
        self.stack.enter_context(patch.object(remote.os, 'getuid', return_value=1000))
        self.stack.enter_context(patch.object(remote.platform, 'machine', return_value='aarch64'))
        self.stack.enter_context(patch.object(remote.shutil, 'which', side_effect=lambda c: '/usr/bin/' + c))
        self.stack.enter_context(patch.object(remote.socket, 'socket', return_value=FakeSocket()))
        self.stack.enter_context(patch.object(remote, 'run', side_effect=self.fake_run))
        self.stack.enter_context(patch.object(remote, 'sudo', side_effect=self.fake_sudo))
        self.stack.enter_context(patch.object(remote, 'systemctl', side_effect=self.fake_systemctl))
        self.stack.enter_context(patch.object(remote, 'controller', return_value=b'{"version":"test"}'))
        self.stack.enter_context(patch.object(remote, 'probe', return_value={'healthy': True, 'exit_country': 'US'}))
        self.stack.enter_context(patch('pwd.getpwuid', return_value=SimpleNamespace(pw_shell='/bin/bash')))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.bundle = self.make_bundle()

    def tearDown(self):
        vars(remote).pop('_domino_registry_backup', None)
        self.stack.close()
        self.temp.cleanup()

    def fake_run(self, args, **kwargs):
        if args == ['id', '-un']:
            return SimpleNamespace(stdout='nvidia\n', returncode=0)
        if args == ['id', '-gn']:
            return SimpleNamespace(stdout='nvidia\n', returncode=0)
        return SimpleNamespace(stdout='', returncode=0)

    def fake_sudo(self, *args):
        if args[0] == 'install':
            shutil.copy2(args[-2], args[-1])
        elif args[0] == 'rm':
            Path(args[-1]).unlink(missing_ok=True)
        elif args[0] == 'systemctl':
            state = self.legacy_state if self.legacy_service.name in args else self.state
            action = args[1]
            if action == 'stop': state['active'] = False
            if action == 'start': state['active'] = True
            if action == 'disable':
                state['enabled'] = False
                if '--now' in args: state['active'] = False
            if action == 'enable':
                state['enabled'] = True
                if '--now' in args: state['active'] = True
        return SimpleNamespace(stdout='', returncode=0)

    def fake_systemctl(self, action, service=None):
        service = service or remote.SERVICE
        state = self.legacy_state if service == self.legacy_service else self.state
        return state[action[3:]]

    def make_bundle(self):
        bundle = self.root / 'bundle'
        data = bundle / 'data'
        data.mkdir(parents=True)
        (bundle / 'mihomo').write_bytes(b'TEST-BINARY')
        (data / 'config.json').write_text(json.dumps({'mixed-port': 7897,
            'external-controller': '127.0.0.1:19090', 'secret': 'TEST-CREDENTIAL'}))
        (bundle / 'selections.json').write_text('{}')
        (bundle / 'manifest.json').write_text(json.dumps({'schema': 1, 'arch': 'arm64',
            'version': 'v1.2.3', 'proxy_port': 7897, 'api_port': 19090,
            'test_url': remote.DEFAULT_TEST, 'shell_env': True}))
        return bundle

    def seed_existing(self):
        (self.app / 'data').mkdir(parents=True)
        (self.app / 'mihomo').write_bytes(b'OLD-WORKING-BINARY')
        (self.app / 'data/config.json').write_text(json.dumps({'mixed-port': 7897,
            'external-controller': '127.0.0.1:19090', 'secret': 'OLD-CREDENTIAL'}))
        self.service.write_text(remote.MARKER + '\nOLD-WORKING-UNIT\n')
        (self.home / '.bashrc').write_text('# original shell\n')
        (self.home / '.bashrc').chmod(0o640)
        self.state.update(active=True, enabled=False)

    def test_package_initializer_preserves_pipx_symlink_on_success_and_failed_upgrade(self):
        self.stack.__enter__()
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        target = self.root / 'package-launcher'
        target.write_text('package managed executable')
        launcher.symlink_to(target)
        manifest_path = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['package_managed_cli'] = True
        manifest_path.write_text(json.dumps(manifest))
        (self.bundle / 'cli').mkdir(exist_ok=True)
        (self.bundle / 'cli/domino_shell.py').write_text('# helper')
        remote.install(self.bundle)
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(target.read_text(), 'package managed executable')
        with patch.object(remote, 'probe', side_effect=remote.InstallError('test health failure')):
            with self.assertRaises(remote.InstallError):
                remote.install(self.bundle)
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(target.read_text(), 'package managed executable')

    def assert_package_redeploy(self, *, symlink=False, legacy=False):
        import domino_uninstall
        self.stack.__enter__()
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        entry = 'from domino_cli import main\nsys.exit(main())\n' if legacy else 'from domino_install import package_cli\nsys.exit(package_cli())\n'
        content = '#!/usr/bin/python3\nimport sys\n' + entry
        target = self.root / 'venv/bin/domino' if symlink else launcher
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        target.chmod(0o755)
        if symlink:
            launcher.symlink_to(target)
        (self.bundle / 'cli').mkdir()
        (self.bundle / 'cli/domino_cli.py').write_text('# fixture CLI')
        remote.install(self.bundle)
        with patch.object(domino_uninstall.sys, 'platform', 'linux'), \
                patch.object(remote, 'system_proxy'), \
                patch('pwd.getpwuid', return_value=SimpleNamespace(pw_shell='/bin/bash', pw_name='nvidia')):
            domino_uninstall.uninstall(remote, yes=True)
        self.assertFalse(self.app.exists())
        self.assertEqual(target.read_text(), content)
        remote.install(self.bundle)
        self.assertTrue(self.app.is_dir())
        self.assertEqual(launcher.is_symlink(), symlink)
        self.assertEqual(target.read_text(), content)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        with patch.object(remote, 'probe', side_effect=remote.InstallError('fixture health failure')):
            with self.assertRaises(remote.InstallError):
                remote.install(self.bundle)
        self.assertEqual(target.read_text(), content)
        self.assertEqual(launcher.is_symlink(), symlink)

    def test_deploy_uninstall_redeploy_preserves_current_pip_console_script(self):
        self.assert_package_redeploy()

    def test_deploy_result_reports_public_facts_without_terminal_integration(self):
        path = self.bundle / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.update(deployment_output='compact', shell_env=False)
        path.write_text(json.dumps(manifest))
        remote.install(self.bundle)
        report = json.loads((self.bundle / 'deployment-result.json').read_text())
        self.assertEqual(report['exit_country'], 'US')
        self.assertEqual(report['proxy_port'], 7897)
        self.assertIsNone(report['shell_enabled'])
        self.assertNotIn('TEST-CREDENTIAL', json.dumps(report))

    def test_deploy_uninstall_redeploy_preserves_pipx_console_symlink(self):
        self.assert_package_redeploy(symlink=True)

    def test_deploy_uninstall_redeploy_preserves_legacy_pip_console_script(self):
        self.assert_package_redeploy(legacy=True)

    def test_unknown_launchers_are_rejected_before_installation(self):
        self.stack.__enter__()
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        target = self.root / 'unrelated'
        target.write_text('#!/bin/sh\necho unrelated\n')
        for kind in ('file', 'symlink', 'broken-link'):
            if launcher.exists() or launcher.is_symlink(): launcher.unlink()
            if kind == 'file': launcher.write_text(target.read_text())
            else: launcher.symlink_to(target if kind == 'symlink' else self.root / 'missing')
            with self.subTest(kind=kind), self.assertRaisesRegex(remote.InstallError, '其他程序'):
                remote.install(self.bundle)
            self.assertFalse(self.app.exists())
            self.assertFalse(self.service.exists())
            self.assertEqual(target.read_text(), '#!/bin/sh\necho unrelated\n')

    def seed_registry(self):
        root = self.home / '.config/domino/subscriptions'
        revision = 'a' * 32
        cached = root / 'cache' / revision
        remote.write_private(cached / 'config.json', '{"rules":["MATCH,DIRECT"]}')
        remote.write_private(cached / 'providers/original.json', '{"original":true}')
        index = root / 'index.json'
        remote.write_private(index, json.dumps({'schema': 1, 'items': [
            {'id': 'b' * 32, 'name': 'existing online', 'kind': 'subscription',
             'url': 'https://example.invalid/private', 'revision': revision}]}), 0o640)
        remote.write_private(self.app / 'data/subscription.json', '{"id":"' + 'b' * 32 + '"}')
        remote.write_private(self.app / 'data/source/config.json', '{"old_source":true}')
        return index, cached

    def legacy_environment(self, number=17890):
        return f'''export PATH="$HOME/.local/bin:$PATH"
export http_proxy=http://127.0.0.1:{number}
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export all_proxy=socks5h://127.0.0.1:{number}
export ALL_PROXY="$all_proxy"
export no_proxy=localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
export NO_PROXY="$no_proxy"
'''

    def seed_shell_environment(self, text):
        remote.write_private(self.home / '.config/domino/proxy.env', text)
        body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
        for name in ['.bashrc', '.zshrc', '.vscode-server/server-env-setup']:
            remote.write_private(self.home / name, remote.managed_block('# user settings\n', body), 0o640)

    def test_existing_shell_policy_survives_repeated_upgrades_including_pending(self):
        self.seed_existing()
        policy = self.app / 'shell-policy.json'
        manifest_path = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for enabled in (False, True):
            for pending in (False, True):
                with self.subTest(enabled=enabled, pending=pending):
                    original = json.dumps({'version': 1, 'enabled': enabled})
                    remote.write_private(policy, original)
                    manifest['awaiting_subscription'] = pending
                    manifest_path.write_text(json.dumps(manifest))
                    for _ in range(2):
                        remote.install(self.bundle)
                        self.assertEqual(policy.read_text(), original)

    def test_complete_legacy_template_enables_linux_policy_except_when_pending(self):
        self.seed_existing()
        manifest_path = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for pending in (False, True):
            with self.subTest(pending=pending):
                (self.app / 'shell-policy.json').unlink(missing_ok=True)
                self.seed_shell_environment(self.legacy_environment())
                manifest['awaiting_subscription'] = pending
                manifest_path.write_text(json.dumps(manifest))
                for _ in range(2):
                    remote.install(self.bundle)
                    self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': not pending})
                    loader = (self.home / '.config/domino/proxy.env').read_text()
                    self.assertIn('# Legacy proxy port: 17890\n', loader)
                    self.assertIn('--legacy-port 17890', loader)
                self.assertFalse((self.app / 'shell-env.previous').exists())

    def test_generated_legacy_marker_does_not_enable_missing_policy(self):
        self.seed_existing()
        self.seed_shell_environment(shell.integration(self.app, sys.executable, legacy_port=17890))
        for _ in range(2):
            remote.install(self.bundle)
            self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': False})
            self.assertIn('# Legacy proxy port: 17890\n', (self.home / '.config/domino/proxy.env').read_text())
        self.assertFalse((self.app / 'shell-env.previous').exists())

    def test_custom_and_incomplete_legacy_environments_are_backed_up_not_enabled(self):
        self.seed_existing()
        for text in (self.legacy_environment() + '# custom\nexport MY_SETTING=preserved\n',
                     'export http_proxy=http://127.0.0.1:17890\n'):
            with self.subTest(text=text):
                (self.app / 'shell-policy.json').unlink(missing_ok=True)
                (self.app / 'shell-env.previous').unlink(missing_ok=True)
                self.seed_shell_environment(text)
                for _ in range(2):
                    remote.install(self.bundle)
                    self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': False})
                    self.assertEqual((self.app / 'shell-env.previous').read_text(), text)
                    loader = (self.home / '.config/domino/proxy.env').read_text()
                    self.assertIn('Managed by Domino shell integration', loader)
                    self.assertNotIn('# Legacy proxy port:', loader)

    def test_success_is_repeatable_without_duplicate_environment(self):
        remote.install(self.bundle)
        remote.install(self.bundle)
        self.assertTrue(self.state['active'])
        self.assertTrue(self.state['enabled'])
        self.assertEqual((self.home / '.bashrc').read_text().count(remote.BEGIN), 1)
        self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': False})
        self.assertEqual((self.app / 'data/config.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(list(self.backups.glob('*/snapshot.json'))), 2)

    def test_empty_install_starts_service_and_skips_proxy_health_and_environment_changes(self):
        path=self.bundle/'manifest.json'
        manifest=json.loads(path.read_text())
        manifest['awaiting_subscription']=True
        path.write_text(json.dumps(manifest))
        with patch.object(remote,'probe') as probe:
            remote.install(self.bundle)
        self.assertTrue(self.state['active'])
        self.assertTrue(self.state['enabled'])
        shell=(self.home/'.bashrc').read_text()
        self.assertIn('proxy.env',shell)
        self.assertNotIn('http_proxy',shell)
        probe.assert_not_called()

    def test_first_install_failure_removes_new_service_and_files(self):
        with patch.object(remote, 'probe', side_effect=remote.InstallError('synthetic failure')):
            with self.assertRaises(remote.InstallError):
                remote.install(self.bundle)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.service.exists())
        self.assertFalse(self.state['active'])
        self.assertFalse(self.state['enabled'])
        self.assertFalse((self.home / '.bashrc').exists())

    def test_update_failure_restores_binary_unit_active_and_enable_state(self):
        self.seed_existing()
        with patch.object(remote, 'probe', side_effect=remote.InstallError('synthetic failure')):
            with self.assertRaises(remote.InstallError):
                remote.install(self.bundle)
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')
        self.assertIn('OLD-WORKING-UNIT', self.service.read_text())
        self.assertEqual((self.home / '.bashrc').read_text(), '# original shell\n')
        self.assertEqual((self.home / '.bashrc').stat().st_mode & 0o777, 0o640)
        self.assertTrue(self.state['active'])
        self.assertFalse(self.state['enabled'])

    def test_cancellation_also_restores_predeployment_state(self):
        self.seed_existing()
        with patch.object(remote, 'probe', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                remote.install(self.bundle)
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')
        self.assertTrue(self.state['active'])
        self.assertFalse(self.state['enabled'])

    def test_partial_environment_failure_restores_every_environment_file(self):
        self.seed_existing()
        def failing_environment(port, **kwargs):
            remote.write_private(self.home / '.bashrc', 'PARTIAL NEW CONFIG')
            remote.write_private(self.home / '.config/domino/proxy.env', 'PARTIAL SECRET')
            raise OSError('disk full')
        with patch.object(remote, 'configure_environment', side_effect=failing_environment):
            with self.assertRaises(remote.InstallError) as caught:
                remote.install(self.bundle)
        self.assertEqual(caught.exception.effect,'rolled_back')
        self.assertEqual((self.home / '.bashrc').read_text(), '# original shell\n')
        self.assertFalse((self.home / '.config/domino/proxy.env').exists())
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')

    def test_registry_snapshot_is_captured_once_and_failure_is_not_published(self):
        snapshot_registry = subscriptions.snapshot_registry
        with patch.object(subscriptions, 'snapshot_registry', wraps=snapshot_registry) as capture:
            backup = remote.snapshot()
        capture.assert_called_once_with(remote, backup)
        self.assertFalse((backup / 'legacy/registry').exists())
        shutil.rmtree(backup)
        with patch.object(subscriptions, 'snapshot_registry', side_effect=OSError('snapshot failed')):
            with self.assertRaises(OSError):
                remote.snapshot()
        self.assertFalse(list(self.backups.glob('*/snapshot.json')))
        self.assertFalse(self.app.exists())
        self.assertFalse(self.service.exists())

    def test_invalid_registration_is_rejected_before_install_side_effects(self):
        (self.bundle / 'registration.json').write_text('{"version":1,"kind":"subscription","url":"http://unsafe.invalid"}')
        with patch.object(remote, 'snapshot') as snapshot, patch.object(remote, 'run') as run:
            with self.assertRaises((subscriptions.DomainError, ValueError)):
                remote.install(self.bundle)
        snapshot.assert_not_called()
        run.assert_not_called()
        self.assertFalse(self.app.exists())
        self.assertFalse(self.service.exists())

    def test_invalid_source_is_rejected_before_install_side_effects(self):
        source = self.bundle / 'data/source'
        source.mkdir()
        (source / 'config.json').write_text('{"proxies":[]}')
        (source / 'metadata.json').write_text('{"version":1}')
        with patch.object(remote, 'snapshot') as snapshot, patch.object(remote, 'run') as run:
            with self.assertRaises((subscriptions.DomainError, ValueError, RuntimeError)):
                remote.install(self.bundle)
        snapshot.assert_not_called()
        run.assert_not_called()
        self.assertFalse(self.app.exists())

    def test_valid_bundle_source_is_installed_and_registered_without_fetching(self):
        import domino_sources
        config_path = self.bundle / 'data/config.json'
        config = json.loads(config_path.read_text())
        config['proxies'] = [{'name': 'new-node', 'type': 'ss', 'server': 'example.invalid',
                              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private'}]
        config_path.write_text(json.dumps(config))
        source = self.bundle / 'data/source'
        with patch.object(tool, 'download_resource', side_effect=AssertionError('no network')):
            domino_sources.create_source(config, config_path, source)
            remote.install(self.bundle)
        self.assertEqual((self.app / 'data/source/config.json').read_bytes(), (source / 'config.json').read_bytes())
        self.assertEqual((self.app / 'data/source/metadata.json').read_bytes(), (source / 'metadata.json').read_bytes())
        index = json.loads((self.home / '.config/domino/subscriptions/index.json').read_text())
        marker = json.loads((self.app / 'data/subscription.json').read_text())
        self.assertEqual(index['items'][0]['id'], marker['id'])
        self.assertEqual(index['items'][0]['kind'], 'snapshot')

    def test_registration_failure_restores_registry_source_marker_and_runtime(self):
        config_path = self.bundle / 'data/config.json'
        config = json.loads(config_path.read_text())
        config['proxies'] = [{'name': 'new-node', 'type': 'ss', 'server': 'example.invalid',
                              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private'}]
        config_path.write_text(json.dumps(config))
        self.seed_existing()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        data = {str(path.relative_to(self.app / 'data')): path.read_bytes()
                for path in (self.app / 'data').rglob('*') if path.is_file()}
        register = subscriptions.register_installed
        def fail_after_registration(ctx, bundle):
            register(ctx, bundle)
            raise OSError('synthetic failure after publication')
        with patch.object(subscriptions, 'register_installed', side_effect=fail_after_registration):
            with self.assertRaises(remote.InstallError) as caught:
                remote.install(self.bundle)
        self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(index.stat().st_mode & 0o777, 0o640)
        self.assertEqual({path.name for path in cached.parent.iterdir()}, {cached.name})
        self.assertEqual({str(path.relative_to(self.app / 'data')): path.read_bytes()
                          for path in (self.app / 'data').rglob('*') if path.is_file()}, data)
        self.assertTrue(self.state['active'])

    def test_registry_index_or_marker_write_failure_restores_transaction(self):
        config_path = self.bundle / 'data/config.json'
        config = json.loads(config_path.read_text())
        config['proxies'] = [{'name': 'new-node', 'type': 'ss', 'server': 'example.invalid',
                              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private'}]
        config_path.write_text(json.dumps(config))
        self.seed_existing()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        write = remote.write_private
        for target in (index, self.app / 'data/subscription.json'):
            with self.subTest(target=target.name):
                failed = False
                def fail_once(path, *args, **kwargs):
                    nonlocal failed
                    if Path(path) == target and not failed:
                        failed = True
                        raise OSError('synthetic write failure')
                    return write(path, *args, **kwargs)
                with patch.object(remote, 'write_private', side_effect=fail_once):
                    with self.assertRaises(remote.InstallError) as caught:
                        remote.install(self.bundle)
                self.assertTrue(failed)
                self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
                self.assertEqual(index.read_bytes(), before)
                self.assertEqual((self.app / 'data/source/config.json').read_text(), '{"old_source":true}')
                self.assertEqual({path.name for path in cached.parent.iterdir()}, {cached.name})
                self.assertTrue(self.state['active'])

    def test_registration_failure_removes_new_registry_and_owned_revision(self):
        config_path = self.bundle / 'data/config.json'
        config = json.loads(config_path.read_text())
        config['proxies'] = [{'name': 'new-node', 'type': 'ss', 'server': 'example.invalid',
                              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private'}]
        config_path.write_text(json.dumps(config))
        register = subscriptions.register_installed
        def fail_after_registration(ctx, bundle):
            register(ctx, bundle)
            raise KeyboardInterrupt
        with patch.object(subscriptions, 'register_installed', side_effect=fail_after_registration):
            with self.assertRaises(KeyboardInterrupt) as caught:
                remote.install(self.bundle)
        self.assertEqual(caught.exception.domino_effect, 'rolled_back')
        self.assertFalse(hasattr(remote, '_domino_registry_backup'))
        root = self.home / '.config/domino/subscriptions'
        self.assertFalse((root / 'index.json').exists())
        self.assertFalse(list((root / 'cache').glob('*')))
        self.assertFalse(self.app.exists())

    def test_restore_attempts_registry_when_app_recovery_fails(self):
        self.seed_existing()
        index, _ = self.seed_registry()
        before = index.read_bytes()
        backup = remote.snapshot()
        remote.write_private(index, '{"schema":1,"items":[]}')
        with patch.object(remote, '_restore_installations', side_effect=OSError('app recovery failed')):
            with self.assertRaises(remote.InstallError) as caught:
                remote.restore(backup)
        self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
        self.assertEqual(index.read_bytes(), before)

    def test_restore_attempts_app_when_registry_recovery_fails(self):
        self.seed_existing()
        backup = remote.snapshot()
        (self.app / 'mihomo').write_bytes(b'PARTIAL')
        with patch.object(subscriptions, 'restore_registry', side_effect=OSError('registry recovery failed')):
            with self.assertRaises(remote.InstallError) as caught:
                remote.restore(backup)
        self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')
        self.assertTrue(self.state['active'])

    def test_rollback_restores_referenced_revisions_preserving_unrelated_cache(self):
        self.seed_existing()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        remote.install(self.bundle)
        remote.write_private(index, '{"schema":1,"items":[]}')
        shutil.rmtree(cached)
        unrelated = cached.parent / ('f' * 32)
        remote.write_private(unrelated / 'config.json', '{"unrelated":true}')
        remote.rollback()
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual((cached / 'providers/original.json').read_text(), '{"original":true}')
        self.assertEqual((self.app / 'data/source/config.json').read_text(), '{"old_source":true}')
        self.assertTrue((unrelated / 'config.json').is_file())

    def test_legacy_backup_without_registry_extension_preserves_current_index(self):
        self.seed_existing()
        backup = remote.snapshot()
        shutil.rmtree(backup / 'registry')
        index, _ = self.seed_registry()
        before = index.read_bytes()
        remote.restore(backup)
        self.assertEqual(index.read_bytes(), before)

    def test_registration_runs_only_after_health_and_environment_success(self):
        with patch.object(subscriptions, 'register_installed') as register:
            with patch.object(remote, 'probe', side_effect=remote.InstallError('health failed')):
                with self.assertRaises(remote.InstallError):
                    remote.install(self.bundle)
            register.assert_not_called()
            with patch.object(remote, 'configure_environment', side_effect=OSError('environment failed')):
                with self.assertRaises(remote.InstallError):
                    remote.install(self.bundle)
            register.assert_not_called()
            remote.install(self.bundle)
            register.assert_called_once_with(remote, self.bundle)
        self.assertFalse(hasattr(remote, '_domino_registry_backup'))

    def test_rollback_restores_predeployment_state_and_saves_current(self):
        self.seed_existing()
        remote.install(self.bundle)
        remote.rollback()
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')
        self.assertEqual((self.home / '.bashrc').read_text(), '# original shell\n')
        self.assertTrue(self.state['active'])
        self.assertFalse(self.state['enabled'])
        kinds = [json.loads(p.read_text())['kind'] for p in self.backups.glob('*/snapshot.json')]
        self.assertIn('rollback-safety', kinds)

    def test_failed_rollback_restores_the_pre_rollback_state(self):
        self.seed_existing()
        remote.install(self.bundle)
        original_restore = remote.restore
        calls = []
        def fail_once(backup):
            calls.append(backup)
            if len(calls) == 1:
                shutil.rmtree(self.app)
                raise remote.InstallError('synthetic rollback failure')
            return original_restore(backup)
        with patch.object(remote, 'restore', side_effect=fail_once):
            with self.assertRaises(remote.InstallError):
                remote.rollback()
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'TEST-BINARY')
        self.assertTrue(self.state['active'])
        self.assertTrue(self.state['enabled'])

    def test_status_does_not_print_node_or_controller_credentials(self):
        remote.install(self.bundle)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(remote.status(True), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result['healthy'])
        self.assertNotIn('TEST-CREDENTIAL', output.getvalue())

    def test_port_conflict_does_not_modify_target(self):
        sock = FakeSocket()
        sock.connect_ex = lambda _: 0
        with patch.object(remote.socket, 'socket', return_value=sock), self.assertRaises(remote.InstallError):
            remote.install(self.bundle)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.service.exists())

    def test_unowned_service_and_symlink_environment_refused_before_sudo(self):
        self.service.write_text('# unrelated service\n')
        with patch.object(remote, 'sudo') as sudo, self.assertRaises(remote.InstallError):
            remote.install(self.bundle)
        sudo.assert_not_called()
        self.service.unlink()
        (self.home / '.bashrc').symlink_to(self.root / 'unrelated')
        with self.assertRaises(remote.InstallError):
            remote.install(self.bundle)
        self.assertFalse(self.app.exists())

    def test_custom_proxy_port_is_used_and_exported(self):
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['proxy_port'] = 17890
        manifest['api_port'] = 19091
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        config = json.loads((self.bundle / 'data/config.json').read_text())
        config.update({'mixed-port': 17890, 'external-controller': '127.0.0.1:19091'})
        (self.bundle / 'data/config.json').write_text(json.dumps(config))
        with patch.object(remote, 'probe', return_value={'healthy': True, 'exit_country': None}) as probe:
            remote.install(self.bundle)
        probe.assert_called_once_with(17890, remote.DEFAULT_TEST)
        from domino_shell import proxy_port
        self.assertEqual(proxy_port(self.home / '.local/share/domino'),17890)
        self.assertIn('Managed by Domino shell integration', (self.home / '.config/domino/proxy.env').read_text())

    def test_default_install_sets_up_bash_without_creating_zshrc(self):
        remote.install(self.bundle)
        self.assertIn('proxy.env', (self.home / '.bashrc').read_text())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_first_install_without_shell_env_does_not_create_policy_or_environment(self):
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['shell_env'] = False
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        remote.install(self.bundle)
        self.assertFalse((self.app / 'shell-policy.json').exists())
        self.assertFalse((self.home / '.config/domino/proxy.env').exists())
        self.assertFalse((self.home / '.bashrc').exists())

    def test_no_shell_environment_option_preserves_policy_and_environment_exactly(self):
        self.seed_existing()
        self.seed_shell_environment(self.legacy_environment())
        names = ['.bashrc', '.zshrc', '.vscode-server/server-env-setup', '.config/domino/proxy.env']
        before = {name: ((self.home / name).read_bytes(), (self.home / name).stat().st_mode & 0o777)
                  for name in names}
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest.update(shell_env=False, awaiting_subscription=True)
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        policy = self.app / 'shell-policy.json'
        for enabled in (None, False, True):
            with self.subTest(enabled=enabled):
                policy.unlink(missing_ok=True)
                original = json.dumps({'version': 1, 'enabled': enabled}) if enabled is not None else None
                if original is not None:
                    remote.write_private(policy, original)
                for _ in range(2):
                    remote.install(self.bundle)
                    self.assertEqual(policy.read_text() if policy.exists() else None, original)
                    for name, expected in before.items():
                        path = self.home / name
                        self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), expected)

    def test_failed_shell_migration_restores_policy_environment_and_custom_backup(self):
        self.seed_existing()
        self.seed_shell_environment(self.legacy_environment() + '# custom\n')
        policy = self.app / 'shell-policy.json'
        previous = self.app / 'shell-env.previous'
        names = ['.bashrc', '.zshrc', '.vscode-server/server-env-setup', '.config/domino/proxy.env']
        before = {name: ((self.home / name).read_bytes(), (self.home / name).stat().st_mode & 0o777)
                  for name in names}
        configure = remote.configure_environment
        migrated = []
        def fail_after_update(port, **kwargs):
            configure(port, **kwargs)
            migrated.append(((self.home / '.config/domino/proxy.env').read_text(), previous.read_text()))
            raise remote.InstallError('synthetic environment migration failure')
        for enabled in (None, False, True):
            with self.subTest(enabled=enabled):
                policy.unlink(missing_ok=True)
                original = ('{ "enabled": ' + str(enabled).lower() + ', "version": 1 }\n') if enabled is not None else None
                if original is not None:
                    remote.write_private(policy, original, 0o640)
                remote.write_private(previous, 'previous custom backup\n')
                migrated.clear()
                with patch.object(remote, 'configure_environment', side_effect=fail_after_update):
                    with self.assertRaises(remote.InstallError) as caught:
                        remote.install(self.bundle)
                self.assertEqual(caught.exception.effect, 'rolled_back')
                self.assertEqual(len(migrated), 1)
                self.assertIn('Managed by Domino shell integration', migrated[0][0])
                self.assertEqual(migrated[0][1], self.legacy_environment() + '# custom\n')
                self.assertEqual(policy.read_text() if policy.exists() else None, original)
                if original is not None:
                    self.assertEqual(policy.stat().st_mode & 0o777, 0o640)
                self.assertEqual(previous.read_text(), 'previous custom backup\n')
                for name, expected in before.items():
                    path = self.home / name
                    self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), expected)

    def test_invalid_existing_policy_is_rejected_before_install_mutation(self):
        self.seed_existing()
        for text in ('{broken', '{"version":1,"enabled":1}', '{"version":1,"enabled":true,"extra":0}'):
            with self.subTest(text=text):
                remote.write_private(self.app / 'shell-policy.json', text)
                with patch.object(remote, 'sudo') as sudo, self.assertRaises(ValueError):
                    remote.install(self.bundle)
                sudo.assert_not_called()
                self.assertEqual((self.app / 'shell-policy.json').read_text(), text)
                self.assertEqual((self.app / 'mihomo').read_bytes(), b'OLD-WORKING-BINARY')

    def test_deployment_lock_prevents_parallel_modification(self):
        with remote.deployment_lock():
            with self.assertRaises(remote.InstallError):
                with remote.deployment_lock():
                    self.fail('second deployment acquired the lock')

    def test_backup_path_traversal_refused(self):
        for value in ['..', '../outside', '/tmp/arbitrary']:
            with self.assertRaises(remote.InstallError):
                remote.select_backup(value)

    def seed_legacy(self):
        (self.legacy_app / 'data').mkdir(parents=True)
        (self.legacy_app / 'mihomo').write_bytes(b'LEGACY-BINARY')
        (self.legacy_app / 'data/config.json').write_text(json.dumps({
            'mixed-port': 7897, 'external-controller': '127.0.0.1:19090', 'secret': 'OLD-SECRET'}))
        self.legacy_service.write_text(remote.LEGACY_MARKER + '\nLEGACY-UNIT\n')
        self.legacy_state.update(active=True, enabled=True)
        body = '[ ! -r "$HOME/.config/robot-clash/proxy.env" ] || . "$HOME/.config/robot-clash/proxy.env"'
        (self.home / '.bashrc').write_text(f'{remote.LEGACY_BEGIN}\n{body}\n{remote.LEGACY_END}\nexport KEEP=1\n')
        remote.write_private(self.home / remote.LEGACY_ENV_FILES[-1], 'export http_proxy=http://127.0.0.1:7897\n')

    def test_legacy_upgrade_replaces_service_and_environment(self):
        self.seed_legacy()
        # Occupied ports belonging to the managed old service are reusable.
        sock = FakeSocket()
        sock.connect_ex = lambda _: 0
        with patch.object(remote.socket, 'socket', return_value=sock):
            remote.install(self.bundle)
        self.assertFalse(self.legacy_service.exists())
        self.assertFalse(self.legacy_app.exists())
        self.assertFalse(self.legacy_state['active'])
        self.assertFalse(self.legacy_state['enabled'])
        self.assertTrue(self.state['active'])
        self.assertIn('domino/data/config.json', self.service.read_text())
        shell = (self.home / '.bashrc').read_text()
        self.assertNotIn('robot-clash', shell)
        self.assertIn('export KEEP=1', shell)
        self.assertEqual(shell.count(remote.BEGIN), 1)
        self.assertFalse((self.home / remote.LEGACY_ENV_FILES[-1]).exists())
        self.assertFalse(self.legacy_backups.exists())
        self.assertFalse(json.loads((self.app / 'shell-policy.json').read_text())['enabled'])
        self.assertEqual((self.app / 'shell-env.previous').read_text(), 'export http_proxy=http://127.0.0.1:7897\n')
        remote.install(self.bundle)
        self.assertEqual((self.home / '.bashrc').read_text(), shell)

    def test_robot_clash_complete_legacy_environment_migrates_policy_and_port(self):
        self.seed_legacy()
        remote.write_private(self.home / remote.LEGACY_ENV_FILES[-1], self.legacy_environment())
        for _ in range(2):
            remote.install(self.bundle)
            self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': True})
            self.assertIn('# Legacy proxy port: 17890\n', (self.home / '.config/domino/proxy.env').read_text())
            self.assertFalse((self.home / remote.LEGACY_ENV_FILES[-1]).exists())
            self.assertFalse((self.app / 'shell-env.previous').exists())
        self.assertNotIn('robot-clash', (self.home / '.bashrc').read_text())

    def test_failed_legacy_upgrade_restores_old_service_and_files(self):
        self.seed_legacy()
        original_shell = (self.home / '.bashrc').read_bytes()
        original_env = (self.home / remote.LEGACY_ENV_FILES[-1]).read_bytes()
        with patch.object(remote, 'probe', side_effect=remote.InstallError('failure')):
            with self.assertRaises(remote.InstallError):
                remote.install(self.bundle)
        self.assertFalse(self.service.exists())
        self.assertFalse(self.app.exists())
        self.assertTrue(self.legacy_state['active'])
        self.assertTrue(self.legacy_state['enabled'])
        self.assertEqual((self.legacy_app / 'mihomo').read_bytes(), b'LEGACY-BINARY')
        self.assertEqual((self.home / '.bashrc').read_bytes(), original_shell)
        self.assertEqual((self.home / remote.LEGACY_ENV_FILES[-1]).read_bytes(), original_env)
        self.assertFalse((self.home / '.config/domino/proxy.env').exists())
        self.assertFalse((self.app / 'shell-policy.json').exists())

    def test_upgrade_rollback_restores_old_name_and_removes_new_name(self):
        self.seed_legacy()
        remote.install(self.bundle)
        remote.rollback()
        self.assertFalse(self.service.exists())
        self.assertFalse(self.app.exists())
        self.assertFalse(self.state['active'])
        self.assertTrue(self.legacy_service.exists())
        self.assertTrue(self.legacy_state['active'])
        self.assertIn(remote.LEGACY_BEGIN, (self.home / '.bashrc').read_text())
        self.assertFalse((self.home / remote.ENV_FILES[-1]).exists())

    def test_legacy_query_reads_existing_service_without_migration(self):
        self.seed_legacy()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(remote.status(True), 0)
        self.assertEqual(json.loads(output.getvalue())['service'], 'robot-clash.service')
        with patch.object(remote, 'controller', side_effect=[b'{"proxies":{}}', b'{"mode":"rule"}']) as controller:
            self.assertEqual(remote.proxy_state(), (json.loads((self.legacy_app / 'data/config.json').read_text()) | {'mode': 'rule'}, {}))
        self.assertEqual(controller.call_args_list[0].args[0], self.legacy_app / 'data')
        self.assertFalse(self.app.exists())

    def test_historical_backup_can_be_restored_after_upgrade(self):
        self.seed_legacy()
        with remote.legacy_layout():
            historical = remote._snapshot()
        remote.install(self.bundle)
        self.assertEqual(remote.select_backup(historical.name), historical)
        remote.rollback(historical.name)
        self.assertFalse(self.service.exists())
        self.assertFalse(self.app.exists())
        self.assertTrue(self.legacy_state['active'])
        self.assertEqual((self.legacy_app / 'mihomo').read_bytes(), b'LEGACY-BINARY')

    def test_failure_during_historical_restore_recovers_new_deployment(self):
        self.seed_legacy()
        with remote.legacy_layout():
            historical = remote._snapshot()
        remote.install(self.bundle)
        original = remote._restore
        def fail_historical(backup):
            if backup == historical:
                raise OSError('synthetic failure')
            return original(backup)
        with patch.object(remote, '_restore', side_effect=fail_historical):
            with self.assertRaises(remote.InstallError) as caught:
                remote.rollback(historical.name)
        self.assertEqual(caught.exception.effect,'rolled_back')
        self.assertTrue(self.state['active'])
        self.assertFalse(self.legacy_state['active'])
        self.assertFalse(self.legacy_service.exists())
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'TEST-BINARY')

    def test_unowned_legacy_service_is_not_stopped_or_removed(self):
        self.legacy_service.write_text('# unrelated\n')
        with patch.object(remote, 'sudo') as sudo, self.assertRaises(remote.InstallError):
            remote.install(self.bundle)
        sudo.assert_not_called()
        self.assertEqual(self.legacy_service.read_text(), '# unrelated\n')

    def test_legacy_upgrade_without_shell_env_preserves_environment(self):
        self.seed_legacy()
        original_shell = (self.home / '.bashrc').read_bytes()
        original_env = (self.home / remote.LEGACY_ENV_FILES[-1]).read_bytes()
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['shell_env'] = False
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        remote.install(self.bundle)
        self.assertEqual((self.home / '.bashrc').read_bytes(), original_shell)
        self.assertEqual((self.home / remote.LEGACY_ENV_FILES[-1]).read_bytes(), original_env)
        self.assertFalse((self.app / 'shell-policy.json').exists())
        self.assertFalse((self.home / '.config/domino/proxy.env').exists())
        self.assertFalse(self.legacy_service.exists())

    def test_incomplete_migration_snapshot_is_not_available_for_rollback(self):
        original = remote._snapshot
        def fail_legacy(kind='deploy', backup=None):
            if backup is not None:
                raise OSError('synthetic disk full')
            return original(kind)
        with patch.object(remote, '_snapshot', side_effect=fail_legacy):
            with self.assertRaises(OSError):
                remote.snapshot()
        with self.assertRaises(remote.InstallError):
            remote.select_backup()

    def add_cli(self):
        cli = self.bundle / 'cli'
        cli.mkdir()
        source = Path(remote.__file__).parent
        for name in tool.CLI_MODULES:
            shutil.copy2(source / name, cli / name)

    def test_target_cli_runs_and_discovers_its_configuration_without_source_workspace(self):
        self.add_cli()
        config_path = self.bundle / 'data/config.json'
        config = json.loads(config_path.read_text())
        config['proxies'] = [{'name': 'Japan', 'type': 'socks5', 'server': 'node.example', 'port': 1080}]
        config_path.write_text(json.dumps(config))
        remote.install(self.bundle)
        launcher = self.home / '.local/bin/domino'
        self.assertEqual(launcher.stat().st_mode & 0o777, 0o700)
        environment = {**os.environ, 'HOME': str(self.home)}
        result = subprocess.run([sys.executable, str(launcher), '--version'], cwd=self.root,
                                env=environment, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), tool.VERSION)
        code = 'import domino_cli; a=domino_cli.build_parser().parse_args(["deploy","alice@next"]); p,c,_=domino_cli.source_config(a); assert p.parent.parent.name=="domino"; assert c["mixed-port"]==7897'
        subprocess.run([sys.executable, '-c', code], cwd=self.app / 'cli', env=environment,
                       capture_output=True, text=True, check=True)

    def test_rollback_restores_previous_cli_and_removes_first_install_launcher(self):
        self.add_cli()
        remote.install(self.bundle)
        launcher = self.home / '.local/bin/domino'
        original = launcher.read_bytes()
        remote.install(self.bundle)
        remote.rollback()
        self.assertEqual(launcher.read_bytes(), original)
        first_backup = min(self.backups.iterdir(), key=lambda p: json.loads((p / 'snapshot.json').read_text())['created_ns'])
        remote.rollback(first_backup.name)
        self.assertFalse(launcher.exists())
        self.assertFalse(self.app.exists())

    def test_unrelated_cli_launcher_is_not_overwritten(self):
        self.add_cli()
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('# unrelated program\n')
        with patch.object(remote, 'sudo') as sudo, self.assertRaises(remote.InstallError):
            remote.install(self.bundle)
        sudo.assert_not_called()
        self.assertEqual(launcher.read_text(), '# unrelated program\n')

    def test_wheel_installed_cli_is_preserved_during_deployment_and_rollback(self):
        self.add_cli()
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        original = '#!/usr/bin/python3\nimport sys\nfrom domino_cli import main\nsys.exit(main())\n'
        launcher.write_text(original)
        remote.install(self.bundle)
        self.assertEqual(launcher.read_text(), original)
        remote.rollback()
        self.assertEqual(launcher.read_text(), original)

    def test_service_management_uses_only_its_owned_service(self):
        remote.install(self.bundle)
        for action in ['stop', 'start', 'restart']:
            with patch.object(remote, 'sudo') as sudo, patch.object(remote,'system_proxy',return_value={'supported':False}) as proxy:
                remote.service_action(action, non_interactive=True)
            sudo.assert_called_once_with('systemctl', action, 'domino.service')
            proxy.assert_called_once_with('off' if action=='stop' else 'on',render=False)
        self.service.write_text('# someone else\n')
        with patch.object(remote, 'sudo') as sudo, self.assertRaises(remote.InstallError):
            remote.service_action('stop', non_interactive=True)
        sudo.assert_not_called()

    def test_logs_follow_does_not_restart_or_modify_the_service(self):
        remote.install(self.bundle)
        with patch.object(remote, 'run') as run, patch.object(remote, 'sudo') as sudo:
            remote.service_action('logs', non_interactive=True, lines=50, follow=True)
        sudo.assert_not_called()
        self.assertEqual(run.call_args.args[0], ['sudo', '-n', 'journalctl', '-u', 'domino.service', '-n', '50', '--no-pager', '-f'])


if __name__ == '__main__':
    unittest.main()
