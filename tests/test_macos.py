from contextlib import contextmanager, redirect_stdout, nullcontext
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import domino_macos as mac
import domino_macos_app as native
import install_domino as common
import domino_cli as tool
import domino_shell as shell
import domino_subscriptions as subscriptions


KINDS = ['web', 'secureweb', 'socksfirewall']


def proxies(port=7897, enabled=True, server='127.0.0.1'):
    return {kind: {'server': server, 'port': port, 'enabled': enabled, 'authenticated': False}
            for kind in KINDS}


class ProxyNetwork:
    def __init__(self, current):
        self.current = copy.deepcopy(current)
        self.writes = []
        self.before = None
        self.after = None

    def settings(self, service):
        return copy.deepcopy(self.current)

    def network(self, *args, write=False, batch=False):
        if not write:
            return 'Enabled: No\nAuto Proxy Discovery: Off\n'
        self.writes.append((args, batch))
        if self.before:
            self.before(args)
        command = args[0]
        for kind in KINDS:
            if command == '-set' + kind + 'proxy':
                self.current[kind].update(server=args[2], port=int(args[3]), enabled=True, authenticated=False)
            elif command == '-set' + kind + 'proxystate':
                self.current[kind]['enabled'] = args[2] == 'on'
        if self.after:
            self.after(args)
        return ''


class MacLaunchLifecycleTests(unittest.TestCase):
    def test_stop_waits_for_departing_job_before_start_bootstraps(self):
        gone = SimpleNamespace(returncode=5, stdout='')
        present = SimpleNamespace(returncode=0, stdout='state = running')
        with patch.object(mac, 'launch', side_effect=[present, present, gone, gone, present, present]) as launch, \
                patch.object(mac.time, 'sleep') as sleep:
            mac.stop(Path('/unused'))
            mac.start(Path('/unused'))
        self.assertEqual([call.args[0] for call in launch.call_args_list],
                         ['bootout', 'print', 'print', 'print', 'enable', 'bootstrap'])
        sleep.assert_called_once_with(.1)

    def test_stop_reports_timeout_instead_of_starting_a_departing_job(self):
        with patch.object(mac, 'launch', return_value=SimpleNamespace(returncode=0)), \
                patch.object(mac.time, 'monotonic', side_effect=[0, 31]), \
                self.assertRaisesRegex(RuntimeError, '退出超时'):
            mac.stop(Path('/unused'))


class MacTests(unittest.TestCase):
    def test_effective_system_proxy_summary_ignores_terminal_proxy_environment(self):
        output='HTTPEnable : 1\nHTTPProxy : 127.0.0.1\nHTTPPort : 7897\nHTTPSEnable : 1\nHTTPSProxy : 127.0.0.1\nHTTPSPort : 7897\n'
        with patch.object(mac.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=output)):
            self.assertEqual(mac.system_proxy_overview(17897),{'routing':'other','ports':[7897]})
            self.assertEqual(mac.system_proxy_overview(7897),{'routing':'domino','ports':[7897]})
        with patch.object(mac.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ProxyAutoConfigEnable : 1\n')):
            self.assertEqual(mac.system_proxy_overview(17897)['routing'],'pac')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.app = self.home / '.local/share/domino'
        self.ctx = SimpleNamespace(HOME=self.home, APP=self.app, BACKUPS=self.home / '.local/share/domino-backups',
                                   InstallError=common.InstallError, write_private=common.write_private,
                                   current_installation=lambda: (self.app, None),
                                   managed_block=common.managed_block, owned_cli=lambda _: True,
                                   is_package_cli=common.is_package_cli,
                                   install_cli=Mock(), prepare_custom_rules=Mock(), run=Mock(), controller=Mock(return_value=b'{"version":"test"}'),
                                   configure_cli_path=common.configure_cli_path,
                                   configure_shell_environment=common.configure_shell_environment,
                                   prepare_shell_policy=common.prepare_shell_policy,
                                   install_shell_policy=common.install_shell_policy,
                                   human_header=common.human_header, human_row=common.human_row,
                                   installation_summary=common.installation_summary, recovery_guidance=common.recovery_guidance,
                                   show=common.show,
                                   probe=Mock(return_value={'healthy': True, 'exit_country': 'JP'}))
        self.bundle = self.root / 'bundle'
        (self.bundle / 'data').mkdir(parents=True)
        (self.bundle / 'mihomo').write_bytes(b'FAKE-MAC-BINARY')
        (self.bundle / 'data/config.json').write_text(json.dumps({'mixed-port': 17897, 'external-controller': '127.0.0.1:19091'}))
        (self.bundle / 'selections.json').write_text('{}')
        self.manifest = {'schema': 1, 'platform': 'darwin', 'arch': 'arm64', 'proxy_port': 17897,
                         'api_port': 19091, 'shell_env': True, 'test_url': common.DEFAULT_TEST}
        self.write_manifest()
        self.active = False
        self.native_app = self.root / 'native' / native.APP_NAME
        (self.native_app / native.EXECUTABLE).parent.mkdir(parents=True)
        (self.native_app / native.EXECUTABLE).write_bytes(b'NATIVE-LAUNCHER')
        (self.native_app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': native.BUNDLE_ID, 'DominoManaged': 1}))
        self.native_prepare = patch.object(native, 'prepared', side_effect=lambda _: nullcontext(self.native_app))
        self.native_register = patch.object(native, 'register')
        self.native_prepare.start()
        self.register = self.native_register.start()
        self.addCleanup(self.native_prepare.stop)
        self.addCleanup(self.native_register.stop)

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest))

    def perform_install(self):
        def start(home): self.active = True
        def stop(home): self.active = False
        with patch.object(mac, 'state', side_effect=lambda _: (self.active, mac.paths(self.home)[0].exists())), \
                patch.object(mac, 'start', side_effect=start), patch.object(mac, 'stop', side_effect=stop), \
                patch.object(mac.platform, 'machine', return_value='arm64'), \
                patch.object(mac.socket, 'socket') as socket, redirect_stdout(io.StringIO()):
            socket.return_value.__enter__.return_value.connect_ex.return_value = 1
            mac.install(self.ctx, self.bundle)

    def test_standalone_install_preserves_detected_package_cli(self):
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        target = self.root / 'venv/bin/domino'
        target.parent.mkdir(parents=True)
        content = '#!/usr/bin/python3\nfrom domino_install import package_cli\nraise SystemExit(package_cli())\n'
        target.write_text(content)
        launcher.symlink_to(target)
        (self.bundle / 'cli').mkdir()
        (self.bundle / 'cli/domino_cli.py').write_text('# fixture CLI')
        self.ctx.install_cli = common.install_cli
        with patch.multiple(common, HOME=self.home, APP=self.app):
            self.perform_install()
            with patch.object(self.ctx, 'probe', side_effect=common.InstallError('fixture health failure')):
                with self.assertRaises(common.InstallError):
                    self.perform_install()
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(target.read_text(), content)

    def test_package_initializer_preserves_pipx_symlink_during_failed_upgrade(self):
        launcher = self.home / '.local/bin/domino'
        launcher.parent.mkdir(parents=True)
        target = self.root / 'pipx-launcher'
        target.write_text('package managed executable')
        launcher.symlink_to(target)
        self.ctx.owned_cli = common.owned_cli
        self.manifest['package_managed_cli'] = True
        self.write_manifest()
        self.perform_install()
        with patch.object(self.ctx, 'probe', side_effect=common.InstallError('test health failure')):
            with self.assertRaises(common.InstallError):
                self.perform_install()
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(target.read_text(), 'package managed executable')

    def test_install_uses_user_launchagent_and_restores_shell_after_failed_upgrade(self):
        self.perform_install()
        self.assertTrue(self.active)
        plist, _ = mac.paths(self.home)
        value = plistlib.loads(plist.read_bytes())
        self.assertEqual(value['Label'], 'local.domino.mihomo')
        self.assertTrue(value['KeepAlive'])
        self.assertEqual(value['ProgramArguments'], native.command(self.app))
        self.assertEqual(value['AssociatedBundleIdentifiers'], [native.BUNDLE_ID])
        shell = (self.home / '.zshrc').read_bytes()
        self.assertIn(b'.config/domino/proxy.env', shell)
        self.assertIn('Managed by Domino shell integration', (self.home / '.config/domino/proxy.env').read_text())
        self.assertFalse(json.loads((self.app / 'shell-policy.json').read_text())['enabled'])
        self.assertFalse((self.home / '.vscode-server').exists())
        self.ctx.probe.side_effect = common.InstallError('synthetic failure')
        with self.assertRaises(common.InstallError):
            self.perform_install()
        self.assertTrue(self.active)
        self.assertEqual((self.home / '.zshrc').read_bytes(), shell)
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'FAKE-MAC-BINARY')

    def test_launcher_preparation_failure_leaves_running_installation_untouched(self):
        self.perform_install()
        before = {str(p.relative_to(self.app)): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}
        plist = mac.paths(self.home)[0].read_bytes()
        with patch.object(native, 'prepared', side_effect=common.InstallError('compiler unavailable')), \
                patch.object(mac, 'snapshot') as snapshot:
            with self.assertRaises(common.InstallError):
                self.perform_install()
        snapshot.assert_not_called()
        self.assertTrue(self.active)
        self.assertEqual(mac.paths(self.home)[0].read_bytes(), plist)
        self.assertEqual({str(p.relative_to(self.app)): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}, before)

    def test_network_app_migration_preserves_core_data_and_proxy_and_rolls_back_failure(self):
        self.perform_install()
        plist, _ = mac.paths(self.home)
        value = plistlib.loads(plist.read_bytes())
        value['ProgramArguments'] = [str(self.app / 'mihomo'), '-d', str(self.app / 'data'), '-f', str(self.app / 'data/config.json')]
        value.pop('AssociatedBundleIdentifiers')
        plist.write_bytes(plistlib.dumps(value))
        shutil.rmtree(native.app_path(self.app))
        original = plist.read_bytes()
        core = (self.app / 'mihomo').read_bytes()
        config = (self.app / 'data/config.json').read_bytes()
        def register(ctx, runtime, **kwargs):
            if not kwargs.get('remove') and native.app_path(runtime).exists():
                raise common.InstallError('synthetic registration failure')
        with patch.object(mac, 'state', return_value=(True, True)), \
                patch.object(mac, 'stop'), patch.object(mac, 'start'), \
                patch.object(native, 'register', side_effect=register), \
                patch.object(mac, 'system_proxy', side_effect=AssertionError('No proxy changes')):
            with self.assertRaises(common.InstallError) as error:
                mac.setup_network_app(self.ctx)
        self.assertEqual(error.exception.effect, 'rolled_back')
        self.assertEqual(plist.read_bytes(), original)
        self.assertFalse(native.app_path(self.app).exists())
        with patch.object(mac, 'state', return_value=(True, True)), \
                patch.object(mac, 'stop'), patch.object(mac, 'start') as start, \
                patch.object(mac, 'system_proxy', side_effect=AssertionError('No proxy changes')), \
                redirect_stdout(io.StringIO()):
            mac.setup_network_app(self.ctx)
        start.assert_called_once_with(self.home)
        self.assertEqual(plistlib.loads(plist.read_bytes())['ProgramArguments'], native.command(self.app))
        self.assertEqual((self.app / 'mihomo').read_bytes(), core)
        self.assertEqual((self.app / 'data/config.json').read_bytes(), config)

    def seed_registry(self):
        root = self.home / '.config/domino/subscriptions'
        revision = 'a' * 32
        cached = root / 'cache' / revision
        common.write_private(cached / 'config.json', '{"rules":["MATCH,DIRECT"]}')
        common.write_private(cached / 'providers/original.json', '{"original":true}')
        index = root / 'index.json'
        common.write_private(index, json.dumps({'schema': 1, 'items': [
            {'id': 'b' * 32, 'name': 'existing online', 'kind': 'subscription',
             'url': 'https://example.invalid/private', 'revision': revision}]}), 0o640)
        common.write_private(self.app / 'data/subscription.json', '{"id":"' + 'b' * 32 + '"}')
        common.write_private(self.app / 'data/source/config.json', '{"old_source":true}')
        return index, cached

    def make_configured_bundle(self):
        path = self.bundle / 'data/config.json'
        config = json.loads(path.read_text())
        config['proxies'] = [{'name': 'new-node', 'type': 'ss', 'server': 'example.invalid',
                              'port': 443, 'cipher': 'aes-128-gcm', 'password': 'private'}]
        path.write_text(json.dumps(config))

    def test_registry_snapshot_failure_is_not_published_or_installed(self):
        with patch.object(subscriptions, 'snapshot_registry', side_effect=OSError('snapshot failed')) as capture:
            with self.assertRaises(OSError):
                self.perform_install()
        capture.assert_called_once()
        self.assertFalse(list(self.ctx.BACKUPS.glob('*/snapshot.json')))
        self.assertFalse(self.app.exists())
        self.assertFalse(mac.paths(self.home)[0].exists())

    def test_invalid_registration_is_rejected_before_install_side_effects(self):
        (self.bundle / 'registration.json').write_text('{"version":1,"kind":"subscription","url":"http://unsafe.invalid"}')
        with patch.object(mac, 'snapshot') as snapshot:
            with self.assertRaises((subscriptions.DomainError, ValueError)):
                self.perform_install()
        snapshot.assert_not_called()
        self.ctx.run.assert_not_called()
        self.assertFalse(self.app.exists())
        self.assertFalse(mac.paths(self.home)[0].exists())

    def test_invalid_source_is_rejected_before_install_side_effects(self):
        source = self.bundle / 'data/source'
        source.mkdir()
        (source / 'config.json').write_text('{"proxies":[]}')
        (source / 'metadata.json').write_text('{"version":1}')
        with patch.object(mac, 'snapshot') as snapshot:
            with self.assertRaises((subscriptions.DomainError, ValueError, RuntimeError)):
                self.perform_install()
        snapshot.assert_not_called()
        self.ctx.run.assert_not_called()
        self.assertFalse(self.app.exists())

    def test_valid_bundle_source_is_installed_and_registered_without_fetching(self):
        import domino_sources
        self.make_configured_bundle()
        config_path = self.bundle / 'data/config.json'
        source = self.bundle / 'data/source'
        with patch.object(tool, 'download_resource', side_effect=AssertionError('no network')):
            domino_sources.create_source(json.loads(config_path.read_text()), config_path, source)
            self.perform_install()
        self.assertEqual((self.app / 'data/source/config.json').read_bytes(), (source / 'config.json').read_bytes())
        self.assertEqual((self.app / 'data/source/metadata.json').read_bytes(), (source / 'metadata.json').read_bytes())
        index = json.loads((self.home / '.config/domino/subscriptions/index.json').read_text())
        marker = json.loads((self.app / 'data/subscription.json').read_text())
        self.assertEqual(index['items'][0]['id'], marker['id'])
        self.assertEqual(index['items'][0]['kind'], 'snapshot')

    def test_registration_failure_restores_registry_source_marker_and_runtime(self):
        self.perform_install()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        data = {str(path.relative_to(self.app / 'data')): path.read_bytes()
                for path in (self.app / 'data').rglob('*') if path.is_file()}
        self.make_configured_bundle()
        register = subscriptions.register_installed
        def fail_after_registration(ctx, bundle):
            register(ctx, bundle)
            raise OSError('synthetic failure after publication')
        with patch.object(subscriptions, 'register_installed', side_effect=fail_after_registration):
            with self.assertRaises(common.InstallError) as caught:
                self.perform_install()
        self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(index.stat().st_mode & 0o777, 0o640)
        self.assertEqual({path.name for path in cached.parent.iterdir()}, {cached.name})
        self.assertEqual({str(path.relative_to(self.app / 'data')): path.read_bytes()
                          for path in (self.app / 'data').rglob('*') if path.is_file()}, data)
        self.assertTrue(self.active)

    def test_registry_index_or_marker_write_failure_restores_transaction(self):
        self.perform_install()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        self.make_configured_bundle()
        write = self.ctx.write_private
        for target in (index, self.app / 'data/subscription.json'):
            with self.subTest(target=target.name):
                failed = False
                def fail_once(path, *args, **kwargs):
                    nonlocal failed
                    if Path(path) == target and not failed:
                        failed = True
                        raise OSError('synthetic write failure')
                    return write(path, *args, **kwargs)
                with patch.object(self.ctx, 'write_private', side_effect=fail_once):
                    with self.assertRaises(common.InstallError) as caught:
                        self.perform_install()
                self.assertTrue(failed)
                self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
                self.assertEqual(index.read_bytes(), before)
                self.assertEqual((self.app / 'data/source/config.json').read_text(), '{"old_source":true}')
                self.assertEqual({path.name for path in cached.parent.iterdir()}, {cached.name})
                self.assertTrue(self.active)

    def test_cancelled_registration_restores_absent_registry_and_first_install(self):
        self.make_configured_bundle()
        register = subscriptions.register_installed
        def fail_after_registration(ctx, bundle):
            register(ctx, bundle)
            raise KeyboardInterrupt
        with patch.object(subscriptions, 'register_installed', side_effect=fail_after_registration):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.perform_install()
        self.assertEqual(caught.exception.domino_effect, 'rolled_back')
        self.assertFalse(hasattr(self.ctx, '_domino_registry_backup'))
        root = self.home / '.config/domino/subscriptions'
        self.assertFalse((root / 'index.json').exists())
        self.assertFalse(list((root / 'cache').glob('*')))
        self.assertFalse(self.app.exists())
        self.assertFalse(mac.paths(self.home)[0].exists())
        self.assertFalse(self.active)

    def test_restore_attempts_registry_even_if_app_recovery_fails(self):
        self.perform_install()
        index, _ = self.seed_registry()
        before = index.read_bytes()
        with patch.object(mac, 'state', return_value=(True, True)):
            backup = mac.snapshot(self.ctx)
        common.write_private(index, '{"schema":1,"items":[]}')
        with patch.object(mac, '_restore_installation', side_effect=OSError('app recovery failed')):
            with self.assertRaises(common.InstallError) as caught:
                mac.restore(self.ctx, backup)
        self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
        self.assertEqual(index.read_bytes(), before)

    def test_restore_attempts_app_even_if_registry_recovery_fails(self):
        self.perform_install()
        with patch.object(mac, 'state', return_value=(True, True)):
            backup = mac.snapshot(self.ctx)
        (self.app / 'mihomo').write_bytes(b'PARTIAL')
        with patch.object(mac, 'stop'), patch.object(mac, 'start') as start, \
                patch.object(subscriptions, 'restore_registry', side_effect=OSError('registry recovery failed')):
            with self.assertRaises(common.InstallError) as caught:
                mac.restore(self.ctx, backup)
        self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
        self.assertEqual((self.app / 'mihomo').read_bytes(), b'FAKE-MAC-BINARY')
        start.assert_called_once_with(self.home)

    def test_manual_rollback_restores_referenced_revisions_and_source(self):
        self.perform_install()
        index, cached = self.seed_registry()
        before = index.read_bytes()
        with patch.object(mac, 'state', return_value=(True, True)):
            backup = mac.snapshot(self.ctx)
        common.write_private(index, '{"schema":1,"items":[]}')
        shutil.rmtree(cached)
        shutil.rmtree(self.app / 'data/source')
        unrelated = cached.parent / ('f' * 32)
        common.write_private(unrelated / 'config.json', '{"unrelated":true}')
        self.ctx.select_backup = lambda _: backup
        with patch.object(mac, 'state', return_value=(True, True)), patch.object(mac, 'stop'), \
                patch.object(mac, 'start'), redirect_stdout(io.StringIO()):
            mac.rollback(self.ctx)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual((cached / 'providers/original.json').read_text(), '{"original":true}')
        self.assertEqual((self.app / 'data/source/config.json').read_text(), '{"old_source":true}')
        self.assertTrue((unrelated / 'config.json').is_file())

    def test_legacy_backup_without_registry_extension_preserves_current_index(self):
        self.perform_install()
        with patch.object(mac, 'state', return_value=(True, True)):
            backup = mac.snapshot(self.ctx)
        shutil.rmtree(backup / 'registry')
        index, _ = self.seed_registry()
        before = index.read_bytes()
        with patch.object(mac, 'stop'), patch.object(mac, 'start'):
            mac.restore(self.ctx, backup)
        self.assertEqual(index.read_bytes(), before)

    def test_registration_runs_only_after_health_and_environment_success(self):
        with patch.object(subscriptions, 'register_installed') as register:
            self.ctx.probe.side_effect = common.InstallError('health failed')
            with self.assertRaises(common.InstallError):
                self.perform_install()
            register.assert_not_called()
            self.ctx.probe.side_effect = None
            with patch.object(mac, 'configure_environment', side_effect=OSError('environment failed')):
                with self.assertRaises(common.InstallError):
                    self.perform_install()
            register.assert_not_called()
            self.perform_install()
            register.assert_called_once_with(self.ctx, self.bundle)
        self.assertFalse(hasattr(self.ctx, '_domino_registry_backup'))

    def test_existing_shell_policy_survives_repeated_upgrades_including_pending(self):
        self.perform_install()
        policy = self.app / 'shell-policy.json'
        for enabled in (False, True):
            for pending in (False, True):
                with self.subTest(enabled=enabled, pending=pending):
                    original = json.dumps({'version': 1, 'enabled': enabled})
                    common.write_private(policy, original)
                    self.manifest['awaiting_subscription'] = pending
                    self.write_manifest()
                    for _ in range(2):
                        self.perform_install()
                        self.assertEqual(policy.read_text(), original)

    def test_generated_legacy_marker_does_not_enable_missing_policy(self):
        self.seed_legacy_environment(shell.integration(self.app, 'python3', legacy_port=17890))
        for _ in range(2):
            self.perform_install()
            self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': False})
            loader = (self.home / '.config/domino/proxy.env').read_text()
            self.assertIn('# Legacy proxy port: 17890\n', loader)
            self.assertIn('--legacy-port 17890', loader)
        self.assertFalse((self.app / 'shell-env.previous').exists())

    def test_invalid_existing_policy_is_rejected_before_install_mutation(self):
        self.perform_install()
        for text in ('{broken', '{"version":1,"enabled":1}', '{"version":1,"enabled":true,"extra":0}'):
            with self.subTest(text=text):
                common.write_private(self.app / 'shell-policy.json', text)
                with patch.object(mac, 'snapshot') as snapshot, self.assertRaises(ValueError):
                    self.perform_install()
                snapshot.assert_not_called()
                self.assertEqual((self.app / 'shell-policy.json').read_text(), text)
                self.assertEqual((self.app / 'mihomo').read_bytes(), b'FAKE-MAC-BINARY')

    def test_first_install_failure_removes_agent_configuration_and_environment(self):
        self.ctx.probe.side_effect = common.InstallError('synthetic failure')
        with self.assertRaises(common.InstallError):
            self.perform_install()
        self.assertFalse(self.active)
        self.assertFalse(self.app.exists())
        self.assertFalse(mac.paths(self.home)[0].exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_empty_install_starts_service_without_claiming_proxy_health_or_setting_shell_proxy(self):
        self.manifest['awaiting_subscription']=True
        self.write_manifest()
        self.perform_install()
        self.assertTrue(self.active)
        self.assertTrue(mac.paths(self.home)[0].exists())
        self.ctx.probe.assert_not_called()
        shell=(self.home/'.zshrc').read_text()
        self.assertIn('proxy.env',shell)
        self.assertNotIn('http_proxy',shell)
        self.assertFalse(json.loads((self.app / 'shell-policy.json').read_text())['enabled'])

    def legacy_environment(self, number=17897):
        return f'''export PATH="$HOME/.local/bin:$PATH"
export http_proxy=http://127.0.0.1:{number}
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$http_proxy"
export all_proxy=socks5h://127.0.0.1:{number}
export ALL_PROXY="$all_proxy"
export no_proxy=localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
export NO_PROXY="$no_proxy"
'''

    def seed_legacy_environment(self, text):
        common.write_private(self.home / '.config/domino/proxy.env', text)
        body = '[ ! -r "$HOME/.config/domino/proxy.env" ] || . "$HOME/.config/domino/proxy.env"'
        for name in ['.zshrc', '.bashrc']:
            common.write_private(self.home / name, common.managed_block('# user settings\n', body), 0o640)

    def test_upgrade_retires_legacy_proxy_exports_and_keeps_unrelated_shell_text(self):
        self.seed_legacy_environment(self.legacy_environment(17890))
        self.perform_install()
        self.assertIn('# Legacy proxy port: 17890', (self.home / '.config/domino/proxy.env').read_text())
        self.assertFalse(json.loads((self.app / 'shell-policy.json').read_text())['enabled'])
        for name in ['.zshrc', '.bashrc']:
            shell = (self.home / name).read_text()
            self.assertIn('# user settings', shell)
            self.assertIn('proxy.env', shell)
            self.assertNotIn('http_proxy', shell)
            self.assertEqual((self.home / name).stat().st_mode & 0o777, 0o640)
        before = (self.home / '.zshrc').read_text()
        self.perform_install()
        self.assertEqual((self.home / '.zshrc').read_text(), before)
        self.assertIn('# Legacy proxy port: 17890\n', (self.home / '.config/domino/proxy.env').read_text())
        self.assertFalse(json.loads((self.app / 'shell-policy.json').read_text())['enabled'])
        self.assertFalse((self.app / 'shell-env.previous').exists())

    def test_custom_proxy_file_is_preserved_but_no_longer_loaded_automatically(self):
        text = self.legacy_environment() + '# custom configuration\nexport MY_SETTING=preserved\n'
        self.seed_legacy_environment(text)
        for _ in range(2):
            self.perform_install()
            self.assertEqual((self.app / 'shell-env.previous').read_text(), text)
            self.assertFalse(shell.read_policy(self.app)['enabled'])
            loader = (self.home / '.config/domino/proxy.env').read_text()
            self.assertIn('Managed by Domino shell integration', loader)
            self.assertNotIn('# Legacy proxy port:', loader)

    def test_default_install_sets_up_zsh_without_creating_bashrc(self):
        self.perform_install()
        self.assertIn('proxy.env', (self.home / '.zshrc').read_text())
        self.assertFalse((self.home / '.bashrc').exists())

    def test_first_install_without_shell_env_does_not_create_policy_or_environment(self):
        self.manifest['shell_env'] = False
        self.write_manifest()
        self.perform_install()
        self.assertFalse((self.app / 'shell-policy.json').exists())
        self.assertFalse((self.home / '.config/domino/proxy.env').exists())
        self.assertFalse((self.home / '.zshrc').exists())

    def test_no_shell_env_preserves_policy_and_environment_exactly(self):
        self.perform_install()
        self.seed_legacy_environment(self.legacy_environment())
        names = ['.zshrc', '.bashrc', '.config/domino/proxy.env']
        before = {name: ((self.home / name).read_bytes(), (self.home / name).stat().st_mode & 0o777)
                  for name in names}
        self.manifest.update(shell_env=False, awaiting_subscription=True)
        self.write_manifest()
        policy = self.app / 'shell-policy.json'
        for enabled in (None, False, True):
            with self.subTest(enabled=enabled):
                policy.unlink(missing_ok=True)
                original = json.dumps({'version': 1, 'enabled': enabled}) if enabled is not None else None
                if original is not None:
                    common.write_private(policy, original)
                for _ in range(2):
                    self.perform_install()
                    self.assertEqual(policy.read_text() if policy.exists() else None, original)
                    for name, expected in before.items():
                        path = self.home / name
                        self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), expected)

    def test_failed_environment_migration_restores_policy_environment_and_custom_backup(self):
        self.perform_install()
        self.seed_legacy_environment(self.legacy_environment() + '# custom\n')
        names = ['.zshrc', '.bashrc', '.config/domino/proxy.env']
        before = {name: ((self.home / name).read_bytes(), (self.home / name).stat().st_mode & 0o777)
                  for name in names}
        policy = self.app / 'shell-policy.json'
        previous = self.app / 'shell-env.previous'
        migrated = []
        def fail_after_update(app, home, **kwargs):
            common.configure_shell_environment(app, home, **kwargs)
            migrated.append(((self.home / '.config/domino/proxy.env').read_text(), previous.read_text()))
            raise common.InstallError('synthetic environment migration failure')
        self.ctx.configure_shell_environment = fail_after_update
        for enabled in (None, False, True):
            with self.subTest(enabled=enabled):
                policy.unlink(missing_ok=True)
                original = ('{ "enabled": ' + str(enabled).lower() + ', "version": 1 }\n') if enabled is not None else None
                if original is not None:
                    common.write_private(policy, original, 0o640)
                common.write_private(previous, 'previous custom backup\n')
                migrated.clear()
                with self.assertRaises(common.InstallError) as caught:
                    self.perform_install()
                self.assertEqual(caught.exception.effect, 'rolled_back')
                self.assertEqual(len(migrated), 1)
                self.assertIn('Managed by Domino shell integration', migrated[0][0])
                self.assertEqual(migrated[0][1], self.legacy_environment() + '# custom\n')
                self.assertTrue(self.active)
                self.assertEqual(policy.read_text() if policy.exists() else None, original)
                if original is not None:
                    self.assertEqual(policy.stat().st_mode & 0o777, 0o640)
                self.assertEqual(previous.read_text(), 'previous custom backup\n')
                for name, expected in before.items():
                    path = self.home / name
                    self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), expected)

    def test_new_shells_do_not_inject_proxy_and_preserve_inherited_or_manual_values(self):
        self.seed_legacy_environment(self.legacy_environment())
        self.perform_install()
        (self.app / 'cli').mkdir(exist_ok=True)
        shutil.copy2(Path(mac.__file__).with_name('domino_shell.py'), self.app / 'cli/domino_shell.py')
        env = {k: v for k, v in os.environ.items() if k.lower() not in
               ['http_proxy', 'https_proxy', 'all_proxy', 'no_proxy']}
        env['HOME'] = str(self.home)
        env.pop('BASH_ENV', None)
        for shell, rc in [('zsh', '.zshrc'), ('bash', '.bashrc')]:
            executable = shutil.which(shell)
            if not executable:
                continue
            script = '. "$HOME/' + rc + '"; printf "%s|%s|%s" "${http_proxy-unset}" "${https_proxy-unset}" "${all_proxy-unset}"'
            for inherited in [None, 'http://127.0.0.1:7897', 'http://127.0.0.1:17897']:
                with self.subTest(shell=shell, inherited=inherited):
                    values = dict(env)
                    if inherited:
                        values.update(http_proxy=inherited, https_proxy=inherited)
                    result = subprocess.run([executable, '-f' if shell == 'zsh' else '--noprofile', '-c', script],
                                            env=values, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if inherited and ':17897' in inherited:
                        self.assertIn('baseline is unknown', result.stderr)
                    else:
                        self.assertEqual(result.stderr, '')
                    expected = f'{inherited}|{inherited}|unset' if inherited and ':17897' not in inherited else 'unset|unset|unset'
                    self.assertEqual(result.stdout, expected)
            result = subprocess.run([executable, '-f' if shell == 'zsh' else '--noprofile', '-c',
                                     'export https_proxy=http://manual:8080; ' + script],
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'unset|http://manual:8080|unset')

    def test_other_system_proxy_uses_clear_enabled_summary(self):
        current = {kind: {'enabled': True, 'server': '127.0.0.1', 'port': 7897,
                          'authenticated': False}
                   for kind in ('web', 'secureweb', 'socksfirewall')}
        output = io.StringIO()
        with patch.object(mac, 'network', return_value=''), redirect_stdout(output):
            mac.show_system_proxy(self.ctx, 'Wi-Fi', current, None)
        text = output.getvalue()
        self.assertIn('● 未指向 Domino', text)
        self.assertNotIn('系统代理指向其他代理或混合使用', text)

    def test_system_proxy_status_uses_solid_red_off_green_domino_and_yellow_pac(self):
        (self.app / 'data').mkdir(parents=True)
        (self.app / 'data/config.json').write_text('{"mixed-port":17897}')
        cases = [(False, 17897, False, '● 未指向 Domino', '31'),
                 (True, 7897, False, '● 未指向 Domino', '31'),
                 (True, 17897, False, '● 已指向 Domino', '32'),
                 (False, 17897, True, '● 使用 PAC / 自动代理配置', '33')]
        for enabled, port, automatic, summary, tone in cases:
            with self.subTest(enabled=enabled, port=port, automatic=automatic):
                current = {kind: {'enabled': enabled, 'server': '127.0.0.1', 'port': port,
                                  'authenticated': False}
                           for kind in ('web', 'secureweb', 'socksfirewall')}
                before = copy.deepcopy(current)
                with patch.object(mac, 'network', return_value='Enabled: Yes' if automatic else ''), \
                        patch.object(self.ctx, 'human_header') as header, redirect_stdout(io.StringIO()):
                    mac.show_system_proxy(self.ctx, 'Wi-Fi', current, None)
                header.assert_called_once_with('系统代理', summary, tone)
                self.assertEqual(current, before)

    def test_system_proxy_cannot_be_enabled_before_a_subscription_is_configured(self):
        (self.app/'data').mkdir(parents=True)
        (self.app/'data/config.json').write_text('{"mixed-port":17897,"proxies":[]}')
        (self.app/'manifest.json').write_text('{"awaiting_subscription":true}')
        self.ctx.current_installation=lambda:(self.app,None)
        with patch.object(mac,'network_service',return_value='Wi-Fi'), patch.object(mac,'proxy_settings',return_value={}), \
                patch.object(mac,'network') as network, self.assertRaisesRegex(common.InstallError,'配好订阅'):
            mac.system_proxy(self.ctx,'on')
        network.assert_not_called()

    def test_foreign_launchagent_is_not_overwritten(self):
        plist, _ = mac.paths(self.home)
        plist.parent.mkdir(parents=True)
        plist.write_bytes(plistlib.dumps({'Label': mac.LABEL}))
        with self.assertRaises(common.InstallError):
            self.perform_install()
        self.ctx.run.assert_not_called()

    def test_linux_bundle_is_rejected_before_modifying_the_machine(self):
        self.manifest['platform'] = 'linux'
        self.write_manifest()
        with self.assertRaises(common.InstallError):
            self.perform_install()
        self.assertFalse(self.app.exists())

    def test_macos_asset_is_selected_and_digest_is_required(self):
        name = 'mihomo-darwin-arm64-v1.2.3.gz'
        release = {'tag_name': 'v1.2.3', 'assets': [{'name': name, 'digest': 'sha256:' + 'a' * 64,
                   'browser_download_url': 'https://github.com/MetaCubeX/mihomo/releases/download/v1.2.3/' + name}]}
        self.assertEqual(tool.release_asset(release, 'arm64', 'darwin')[1]['name'], name)
        release['assets'][0]['digest'] = None
        with self.assertRaises(tool.ToolError):
            tool.release_asset(release, 'arm64', 'darwin')

    @contextmanager
    def proxy_network(self, current):
        (self.app / 'data').mkdir(parents=True, exist_ok=True)
        (self.app / 'data/config.json').write_text('{"mixed-port":17897}')
        self.ctx.current_installation = lambda: (self.app, None)
        adapter = ProxyNetwork(current)
        with patch.object(mac, 'network_service', side_effect=lambda requested=None: requested or 'Wi-Fi'), \
                patch.object(mac, 'proxy_settings', side_effect=adapter.settings), \
                patch.object(mac, 'network', side_effect=adapter.network), \
                patch.object(mac, 'state', return_value=(True, True)), redirect_stdout(io.StringIO()):
            yield adapter

    def proxy_record(self, original=None, port=17897):
        path = self.home / '.config/domino/system-proxy.json'
        common.write_private(path, json.dumps({'service': 'Wi-Fi', 'proxies': original or proxies(), 'domino_port': port}))
        return path

    def service_plist(self):
        path, _ = mac.paths(self.home)
        common.write_private(path, plistlib.dumps({'Label': mac.LABEL, 'DominoManaged': 1}))

    def test_system_proxy_restore_preserves_configuration_of_a_new_owner(self):
        record = self.home / '.config/domino/system-proxy.json'
        previous = {kind: {'server': '127.0.0.1', 'port': 7897, 'enabled': True, 'authenticated': False}
                    for kind in ['web', 'secureweb', 'socksfirewall']}
        common.write_private(record, json.dumps({'service': 'Wi-Fi', 'proxies': previous, 'domino_port': 17897}))
        (self.app / 'data').mkdir(parents=True)
        (self.app / 'data/config.json').write_text('{"mixed-port":17897}')
        self.ctx.current_installation = lambda: (self.app, None)
        current = {kind: dict(value, port=8888) for kind, value in previous.items()}
        with patch.object(mac, 'network_service', return_value='Wi-Fi'), patch.object(mac, 'proxy_settings', return_value=current), \
                patch.object(mac, 'network') as network:
            result = mac.system_proxy(self.ctx, 'off', render=False)
        network.assert_not_called()
        self.assertFalse(record.exists())
        self.assertEqual(result['proxies'], current)
        self.assertFalse(result['restore_available'])

    def test_system_proxy_switch_saves_and_restores_previous_clash_settings(self):
        (self.app / 'data').mkdir(parents=True)
        (self.app / 'data/config.json').write_text('{"mixed-port":17897}')
        self.ctx.current_installation = lambda: (self.app, None)
        old = {kind: {'server': '127.0.0.1', 'port': 7897, 'enabled': True, 'authenticated': False}
               for kind in ['web', 'secureweb', 'socksfirewall']}
        current = {kind: dict(value, port=17897) for kind, value in old.items()}
        record = self.home / '.config/domino/system-proxy.json'
        output=io.StringIO()
        with patch.object(mac, 'network_service', return_value='Wi-Fi'), patch.object(mac, 'state', return_value=(True, True)), \
                patch.object(mac, 'proxy_settings', side_effect=[old, current]), patch.object(mac, 'network', return_value=''), \
                redirect_stdout(output):
            mac.system_proxy(self.ctx, 'on',as_json=True)
        self.assertEqual(json.loads(output.getvalue())['proxies']['web']['port'],17897)
        self.assertEqual(json.loads(record.read_text())['proxies'], old)
        output=io.StringIO()
        adapter = ProxyNetwork(current)
        with patch.object(mac, 'network_service', return_value='Wi-Fi'), patch.object(mac, 'proxy_settings', side_effect=adapter.settings), \
                patch.object(mac, 'network', side_effect=adapter.network) as network, redirect_stdout(output):
            mac.system_proxy(self.ctx, 'off',as_json=True)
        restored=json.loads(output.getvalue())
        self.assertEqual(restored['proxies']['web']['port'],7897)
        self.assertTrue(restored['proxies']['web']['enabled'])
        self.assertFalse(restored['restore_available'])
        self.assertFalse(record.exists())
        network.assert_any_call('-setwebproxy', 'Wi-Fi', '127.0.0.1', '7897', write=True, batch=False)

    def test_stop_retires_stale_record_without_reenabling_disabled_proxies(self):
        self.service_plist()
        for port in (7897, 17897, 8888):
            with self.subTest(port=port):
                record = self.proxy_record()
                current = proxies(port, enabled=False)
                with self.proxy_network(current) as adapter, patch.object(mac, 'stop') as stop:
                    mac.service_action(self.ctx, 'stop', batch=True)
                    stop.assert_called_once_with(self.home)
                self.assertEqual(adapter.current, current)
                self.assertEqual(adapter.writes, [])
                self.assertFalse(record.exists())

    def test_partial_takeover_restores_only_owned_proxy(self):
        record = self.proxy_record()
        current = proxies(8888)
        current['web'] = proxies(17897, server='LOCALHOST')['web']
        current['socksfirewall'] = dict(current['socksfirewall'], enabled=False)
        with self.proxy_network(current) as adapter:
            result = mac.system_proxy(self.ctx, 'off', batch=True, render=False)
        self.assertEqual(result['proxies']['web'], proxies()['web'])
        for kind in ('secureweb', 'socksfirewall'):
            self.assertEqual(result['proxies'][kind], current[kind])
        self.assertTrue(adapter.writes)
        self.assertTrue(all(args[0] in ('-setwebproxy', '-setwebproxystate') and batch for args, batch in adapter.writes))
        self.assertFalse(record.exists())

    def test_no_record_stop_disables_only_enabled_domino_pointers(self):
        self.service_plist()
        current = proxies(7897)
        current['web'] = proxies(17897, server='::1')['web']
        current['socksfirewall'] = proxies(17897, enabled=False)['socksfirewall']
        with self.proxy_network(current) as adapter, patch.object(mac, 'stop') as stop:
            mac.service_action(self.ctx, 'stop')
            stop.assert_called_once()
        self.assertEqual(adapter.current['web'], dict(current['web'], enabled=False))
        self.assertEqual(adapter.current['secureweb'], current['secureweb'])
        self.assertEqual(adapter.current['socksfirewall'], current['socksfirewall'])
        self.assertEqual(adapter.writes, [(('-setwebproxystate', 'Wi-Fi', 'off'), False)])

    def test_repeated_on_refreshes_only_lost_ownership_baselines(self):
        original = proxies()
        record = self.proxy_record(original)
        current = proxies(17897)
        current['secureweb'] = proxies(8888)['secureweb']
        current['socksfirewall'] = proxies(7897, enabled=False)['socksfirewall']
        with self.proxy_network(current) as adapter:
            mac.system_proxy(self.ctx, 'on', render=False)
            baseline = json.loads(record.read_text())['proxies']
            self.assertEqual(baseline['web'], original['web'])
            self.assertEqual(baseline['secureweb'], current['secureweb'])
            self.assertEqual(baseline['socksfirewall'], current['socksfirewall'])
            mac.system_proxy(self.ctx, 'off', render=False)
        self.assertEqual(adapter.current, baseline)
        self.assertFalse(record.exists())

    def test_failed_repeated_on_rolls_back_entry_state_and_prior_record(self):
        record = self.proxy_record()
        saved = json.loads(record.read_text())
        current = proxies(8888, enabled=False)
        current['web'] = proxies(17897)['web']
        with self.proxy_network(current) as adapter:
            def fail_once(args):
                if args[0] == '-setsecurewebproxystate' and args[2] == 'on':
                    adapter.before = None
                    raise common.InstallError('synthetic apply failure')
            adapter.before = fail_once
            with self.assertRaises(common.InstallError) as caught:
                mac.system_proxy(self.ctx, 'on', render=False)
            self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
        self.assertEqual(adapter.current, current)
        self.assertEqual(json.loads(record.read_text()), saved)

    def test_incomplete_restore_is_retry_safe_and_blocks_stop(self):
        self.service_plist()
        original = proxies(7897, enabled=False)
        record = self.proxy_record(original)
        with self.proxy_network(proxies(17897)) as adapter, patch.object(mac, 'stop') as stop:
            def fail(args):
                if args[0] == '-setwebproxystate':
                    raise common.InstallError('synthetic state failure')
            adapter.before = fail
            with self.assertRaises(common.InstallError):
                mac.service_action(self.ctx, 'stop')
            stop.assert_not_called()
            self.assertEqual(adapter.current['web'], dict(original['web'], enabled=True))
            self.assertIn('web', json.loads(record.read_text())['pending'])
            self.assertTrue(mac.system_proxy(self.ctx, render=False)['restore_available'])
            adapter.before = None
            mac.service_action(self.ctx, 'stop')
            stop.assert_called_once()
        self.assertEqual(adapter.current, original)
        self.assertFalse(record.exists())

    def test_pending_recovery_does_not_overwrite_later_takeover(self):
        record = self.proxy_record(proxies(7897, enabled=False))
        with self.proxy_network(proxies(17897)) as adapter:
            def fail(args):
                if args[0] == '-setwebproxystate':
                    raise common.InstallError('synthetic failure')
            adapter.before = fail
            with self.assertRaises(common.InstallError):
                mac.system_proxy(self.ctx, 'off', render=False)
            adapter.current['web'] = proxies(8888)['web']
            adapter.before = None
            adapter.writes.clear()
            mac.system_proxy(self.ctx, 'off', render=False)
        self.assertEqual(adapter.current['web'], proxies(8888)['web'])
        self.assertFalse(any(args[0] in ('-setwebproxy', '-setwebproxystate') for args, _ in adapter.writes))
        self.assertFalse(record.exists())

    def test_proxy_status_is_read_only_and_stale_backup_is_not_restore_available(self):
        record = self.proxy_record()
        saved = record.read_bytes()
        with self.proxy_network(proxies(7897, enabled=False)) as adapter:
            result = mac.system_proxy(self.ctx, render=False)
        self.assertIs(result['restore_available'], False)
        self.assertEqual(record.read_bytes(), saved)
        self.assertEqual(adapter.writes, [])

    def test_service_mismatch_does_not_restore_or_discard_another_services_record(self):
        record = self.proxy_record()
        saved = record.read_bytes()
        with self.proxy_network(proxies(17897)) as adapter:
            for action in ('on', 'off'):
                with self.assertRaises(common.InstallError):
                    mac.system_proxy(self.ctx, action, service='Ethernet', render=False)
            self.assertFalse(mac.system_proxy(self.ctx, service='Ethernet', render=False)['restore_available'])
        self.assertEqual(adapter.writes, [])
        self.assertEqual(record.read_bytes(), saved)

    def test_changed_port_cleanup_restores_old_port_and_disables_unbacked_current_port(self):
        record = self.proxy_record(port=17896)
        current = proxies(8888)
        current['web'] = proxies(17896)['web']
        current['secureweb'] = proxies(17897)['secureweb']
        with self.proxy_network(current) as adapter:
            mac.system_proxy(self.ctx, 'off', render=False)
        self.assertEqual(adapter.current['web'], proxies()['web'])
        self.assertEqual(adapter.current['secureweb'], dict(current['secureweb'], enabled=False))
        self.assertEqual(adapter.current['socksfirewall'], current['socksfirewall'])
        self.assertFalse(record.exists())

    def test_failed_on_commit_rolls_back_and_preserves_previous_record(self):
        record = self.proxy_record()
        saved = json.loads(record.read_text())
        current = proxies(17897)
        with self.proxy_network(current) as adapter:
            def write(path, text, mode=0o600):
                value = json.loads(text)
                if 'pending' not in value and 'rollback_record' not in value:
                    self.ctx.write_private = common.write_private
                    raise OSError('synthetic commit failure')
                common.write_private(path, text, mode)
            self.ctx.write_private = write
            with self.assertRaises(common.InstallError) as caught:
                mac.system_proxy(self.ctx, 'on', render=False)
        self.assertEqual(caught.exception.code, 'APPLY_ROLLED_BACK')
        self.assertEqual(adapter.current, current)
        self.assertEqual(json.loads(record.read_text()), saved)

    def test_failed_on_rollback_retry_preserves_baseline_across_port_change(self):
        original = proxies()
        record = self.proxy_record(original, port=17896)
        current = proxies(17896)
        with self.proxy_network(current) as adapter:
            def fail_apply_and_rollback(args):
                if args[0] == '-setsecurewebproxystate' and args[2] == 'on':
                    raise common.InstallError('synthetic apply failure')
                if args[0] == '-setwebproxy' and args[3] == '17896':
                    raise common.InstallError('synthetic rollback failure')
            adapter.before = fail_apply_and_rollback
            with self.assertRaises(common.InstallError) as caught:
                mac.system_proxy(self.ctx, 'on', render=False)
            self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
            self.assertEqual(json.loads(record.read_text())['rollback_record']['domino_port'], 17896)
            adapter.before = None
            mac.system_proxy(self.ctx, 'off', render=False)
        self.assertEqual(adapter.current, original)
        self.assertFalse(record.exists())

    def test_initial_record_write_failure_leaves_network_untouched(self):
        record = self.proxy_record()
        saved = record.read_bytes()
        current = proxies(8888)
        with self.proxy_network(current) as adapter, patch.object(self.ctx, 'write_private', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                mac.system_proxy(self.ctx, 'on', render=False)
        self.assertEqual(adapter.writes, [])
        self.assertEqual(adapter.current, current)
        self.assertEqual(record.read_bytes(), saved)

    def test_readback_mismatch_preserves_recovery_and_prevents_stop(self):
        self.service_plist()
        record = self.proxy_record(proxies(enabled=False))
        with self.proxy_network(proxies(17897)) as adapter, patch.object(mac, 'stop') as stop:
            def ignore_disable(args):
                if args[0] == '-setwebproxystate':
                    adapter.current['web']['enabled'] = True
            adapter.after = ignore_disable
            with self.assertRaises(common.InstallError) as caught:
                mac.service_action(self.ctx, 'stop')
            self.assertEqual(caught.exception.code, 'RECOVERY_INCOMPLETE')
            stop.assert_not_called()
            self.assertIn('web', json.loads(record.read_text())['pending'])
            adapter.after = None
            mac.service_action(self.ctx, 'stop')
            stop.assert_called_once()
        self.assertFalse(record.exists())

    def test_authorization_failure_does_not_stop_or_discard_recovery(self):
        self.service_plist()
        record = self.proxy_record()
        with self.proxy_network(proxies(17897)) as adapter, patch.object(mac, 'stop') as stop:
            def denied(args):
                raise mac.DomainError('synthetic auth failure', code='AUTH_REQUIRED', exit_code=4)
            adapter.before = denied
            with self.assertRaises(mac.DomainError) as caught:
                mac.service_action(self.ctx, 'stop', batch=True)
            self.assertEqual(caught.exception.code, 'AUTH_REQUIRED')
            stop.assert_not_called()
            self.assertTrue(json.loads(record.read_text())['pending'])
        self.assertEqual(adapter.current, proxies(17897))

    def test_off_is_idempotent_after_original_settings_restored(self):
        self.proxy_record()
        with self.proxy_network(proxies()) as adapter:
            for _ in range(2):
                mac.system_proxy(self.ctx, 'off', render=False)
        self.assertEqual(adapter.writes, [])

    def test_start_and_restart_connect_system_proxy_after_controller_is_ready(self):
        self.service_plist()
        for action in ['start', 'restart']:
            calls = []
            def controller(*args, **kwargs):
                calls.append('ready')
                if calls.count('ready') == 1: raise common.InstallError('starting')
                return b'{}'
            def proxy(*args, **kwargs):
                calls.append(('proxy', args[1], kwargs['batch']))
                return {'proxies': proxies(17897)}
            with patch.object(mac, 'start', side_effect=lambda _: calls.append('start')), \
                    patch.object(mac, 'stop', side_effect=lambda _: calls.append('stop')), \
                    patch.object(self.ctx, 'controller', side_effect=controller), patch.object(mac.time, 'sleep'), \
                    patch.object(mac, 'system_proxy', side_effect=proxy), \
                    redirect_stdout(io.StringIO()) as output:
                mac.service_action(self.ctx, action, batch=True)
            self.assertEqual(calls, (['stop'] if action == 'restart' else []) + ['start', 'ready', 'ready', ('proxy', 'on', True)])
            self.assertIn('系统代理已接通', output.getvalue())

    def test_start_proxy_failure_keeps_running_service_and_reports_partial_state(self):
        self.service_plist()
        from domino_model import DomainError
        with patch.object(mac, 'start') as start, patch.object(mac, 'stop') as stop, \
                patch.object(mac, 'system_proxy', side_effect=DomainError('需要认证', code='AUTH_REQUIRED', exit_code=4)), \
                redirect_stdout(io.StringIO()) as output, self.assertRaises(common.InstallError) as caught:
            mac.service_action(self.ctx, 'start', batch=True)
        start.assert_called_once_with(self.home)
        stop.assert_not_called()
        self.assertEqual((caught.exception.code,caught.exception.exit_code,caught.exception.effect), ('AUTH_REQUIRED',4,'unknown'))
        self.assertIn('服务已启动，但系统代理未接通', str(caught.exception))
        self.assertNotIn('已开启', output.getvalue())

    def test_start_does_not_change_proxy_before_controller_becomes_ready(self):
        self.service_plist()
        with patch.object(mac, 'start'), patch.object(self.ctx, 'controller', side_effect=common.InstallError('not ready')), \
                patch.object(mac.time, 'sleep'), patch.object(mac, 'system_proxy') as proxy, \
                self.assertRaisesRegex(common.InstallError, '控制接口未就绪'):
            mac.service_action(self.ctx, 'start')
        proxy.assert_not_called()

    def test_unified_start_stop_roundtrip_restores_previous_proxy_without_touching_shell(self):
        self.service_plist()
        (self.app/'data').mkdir(parents=True)
        (self.app/'data/config.json').write_text('{"mixed-port":17897}')
        policy = self.app/'shell-policy.json'
        policy.write_text('{"enabled":true}')
        rc = self.home/'.zshrc'
        rc.write_text('# existing shell settings\n')
        with self.proxy_network(proxies()) as adapter, patch.object(mac, 'start'), patch.object(mac, 'stop'), \
                patch.object(mac, 'state', return_value=(True,True)), redirect_stdout(io.StringIO()):
            for _ in range(2): mac.service_action(self.ctx, 'start', batch=True)
            self.assertEqual(adapter.current, proxies(17897))
            mac.service_action(self.ctx, 'stop', batch=True)
            self.assertEqual(adapter.current, proxies())
        self.assertEqual(policy.read_text(),'{"enabled":true}')
        self.assertEqual(rc.read_text(),'# existing shell settings\n')


if __name__ == '__main__':
    unittest.main()
