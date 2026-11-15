import os
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import copy
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import domino_subscriptions as subscriptions
import install_domino as control
import domino_cli as tool

REAL_API_JSON = control.api_json
REAL_RUN = control.run


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        if hasattr(control, '_domino_registry_backup'):
            del control._domino_registry_backup
        self.addCleanup(lambda: control.__dict__.pop('_domino_registry_backup', None))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = self.home / '.local/share/domino'
        (self.app / 'data').mkdir(parents=True)
        self.original = {'mixed-port': 17897, 'external-controller': '127.0.0.1:19091',
                         'secret': 'CONTROLLER-PRIVATE', 'mode': 'global', 'log-level': 'info',
                         'proxies': [{'name': 'A', 'type': 'socks5', 'server': 'node.example', 'port': 1080}],
                         'proxy-groups': [{'name': '出口', 'type': 'select', 'proxies': ['A']}],
                         'rules': ['MATCH,出口']}
        (self.app / 'data/config.json').write_text(json.dumps(self.original))
        (self.app / 'manifest.json').write_text('{"version":"v1.19.33"}')
        (self.app / 'mihomo').write_text('fixture kernel')
        self.content = copy.deepcopy(self.original)
        self.content['mixed-port'] = 7897
        self.content['external-controller'] = '0.0.0.0:9090'
        self.content['proxies'].append({'name': 'B', 'type': 'socks5', 'server': 'other.example', 'port': 1080})
        self.content['proxy-groups'][0]['proxies'].append('B')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(control, HOME=self.home, APP=self.app, BACKUPS=self.home / 'backups'))
        self.stack.enter_context(patch.object(control, 'current_installation', return_value=(self.app, Path('domino.service'))))
        self.stack.enter_context(patch.object(control, 'systemctl', return_value=True))
        self.validation = self.stack.enter_context(patch.object(control, 'run'))
        self.probe = self.stack.enter_context(patch.object(control, 'probe', return_value={'healthy': True}))
        self.api = self.stack.enter_context(patch.object(control, 'api_json', side_effect=self.response))
        self.download = self.stack.enter_context(patch.object(tool, 'download', side_effect=self.download_config))
        self.stack.enter_context(patch.object(tool, 'discover_proxy', return_value=None))
        self.stack.enter_context(patch('domino_resources.resource_base', return_value=None))

    def response(self, route, *args, **kwargs):
        if route == '/configs':
            return {'mode': 'global', 'log-level': 'info'}
        if route == '/proxies':
            return {'proxies': {'出口': {'type': 'Selector', 'all': ['A', 'B'], 'now': 'B'}}}
        return None

    def download_config(self, url, path, proxy, *, user_agent=None):
        self.assertEqual(user_agent,tool.SUBSCRIPTION_USER_AGENT)
        self.assertEqual(proxy, 'http://127.0.0.1:17897')
        path.write_text(json.dumps(self.content))

    def args(self, *argv):
        parser = argparse.ArgumentParser()
        control.subscription_arguments(parser)
        return parser.parse_args(argv)

    def execute(self, *argv):
        output = io.StringIO()
        with redirect_stdout(output):
            subscriptions.run(control, self.args(*argv))
        return output.getvalue()

    def add(self, name='机场一'):
        self.execute('--add', name, '--url', 'https://airport.example/config?token=SUBSCRIPTION-PRIVATE')

    def manager(self):
        return subscriptions.Manager(control)

    def test_empty_list_is_read_only_and_does_not_assume_a_subscription_url(self):
        result = json.loads(self.execute('--json'))
        self.assertEqual(result['configs'], [])
        self.assertIn('未关联', result['current_source'])
        self.assertFalse(self.manager().index.exists())
        self.download.assert_not_called()
        self.api.assert_not_called()

    def test_named_urls_are_private_and_add_does_not_change_current_configuration(self):
        self.add()
        self.add('机场二')
        text = self.execute()
        self.assertNotIn('SUBSCRIPTION-PRIVATE',text)
        self.assertNotIn('CONTROLLER-PRIVATE',text)
        result = self.execute('--json')
        self.assertNotIn('SUBSCRIPTION-PRIVATE', result)
        self.assertNotIn('CONTROLLER-PRIVATE', result)
        self.assertEqual(len(json.loads(result)['configs']), 2)
        self.assertEqual(self.manager().index.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manager().root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((self.app / 'data/config.json').read_text()), self.original)
        self.download.assert_not_called()
        self.api.assert_not_called()

    def test_first_subscription_uses_available_network_then_activates_on_empty_install(self):
        baseline=dict(self.original,proxies=[],**{'proxy-groups':[],'rules':['MATCH,REJECT']})
        (self.app/'data/config.json').write_text(json.dumps(baseline))
        (self.app/'manifest.json').write_text('{"awaiting_subscription":true}')
        self.add()
        def fetch(url,path,proxy,*,user_agent=None):
            self.assertIsNone(proxy)
            self.assertEqual(user_agent,tool.SUBSCRIPTION_USER_AGENT)
            path.write_text(json.dumps(self.content))
        self.download.side_effect=fetch
        self.execute('--use','机场一')
        self.assertEqual(self.manager().listing()['active'],'机场一')
        self.assertFalse(control.subscription_pending(self.app))
        self.assertEqual((self.app/'mihomo').read_text(),'fixture kernel')
        self.probe.assert_not_called()

    def test_failed_first_subscription_download_keeps_empty_install_and_saved_address(self):
        baseline=dict(self.original,proxies=[],**{'proxy-groups':[],'rules':['MATCH,REJECT']})
        path=self.app/'data/config.json'
        path.write_text(json.dumps(baseline))
        (self.app/'manifest.json').write_text('{"awaiting_subscription":true}')
        self.add()
        before=path.read_bytes()
        self.download.side_effect=tool.ToolError('下载失败')
        with self.assertRaisesRegex(tool.ToolError,'下载失败'):
            self.execute('--use','机场一')
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(control.subscription_pending(self.app))
        self.assertIsNone(self.manager().listing()['active'])
        self.assertEqual(len(self.manager().registry['items']),1)
        self.api.assert_not_called()

    def test_duplicate_names_and_non_https_urls_do_not_overwrite_registry(self):
        self.add()
        before = self.manager().index.read_bytes()
        for argv in [('--add', '机场一', '--url', 'https://other.example'),
                     ('--add', 'bad', '--url', 'http://example.test'),
                     ('--add', 'bad', '--url', 'https://user:password@example.test')]:
            with self.subTest(argv=argv), self.assertRaises(control.InstallError):
                self.execute(*argv)
        self.assertEqual(self.manager().index.read_bytes(), before)

    def test_update_inactive_subscription_validates_and_caches_without_reloading(self):
        self.add()
        self.execute('--update', '机场一')
        item = self.manager().find('机场一')
        self.assertEqual(item['node_count'], 2)
        self.assertTrue(self.manager().cached(item).is_dir())
        self.assertEqual(self.validation.call_args.kwargs['timeout'], 90)
        self.api.assert_not_called()
        self.probe.assert_not_called()

    def test_invalid_update_preserves_old_cache_and_registry(self):
        self.add()
        self.execute('--update', '机场一')
        before = self.manager().index.read_bytes()
        old = self.manager().cached(self.manager().find('机场一'))
        self.validation.side_effect = control.InstallError('配置校验失败')
        with self.assertRaises(control.InstallError):
            self.execute('--update', '机场一')
        self.assertEqual(self.manager().index.read_bytes(), before)
        self.assertTrue(old.exists())
        self.api.assert_not_called()

    def test_first_use_fetches_once_preserves_ports_secret_mode_and_kernel(self):
        self.add()
        self.execute('--use', '机场一')
        current = json.loads((self.app / 'data/config.json').read_text())
        for field in ['mixed-port', 'external-controller', 'secret', 'mode', 'log-level']:
            self.assertEqual(current[field], self.original[field])
        self.assertEqual((self.app / 'mihomo').read_text(), 'fixture kernel')
        self.assertEqual(self.manager().listing()['active'], '机场一')
        self.assertEqual(self.download.call_count, 1)
        self.execute('--use', '机场一')
        self.assertEqual(self.download.call_count, 1)
        self.assertTrue(any(call.args[0] == '/configs?force=true' for call in self.api.call_args_list))

    def test_current_subscription_update_reloads_without_switching_to_another(self):
        self.add()
        self.add('机场二')
        self.execute('--use', '机场一')
        old_revision = self.manager().find('机场一')['revision']
        self.execute('--update', '机场一')
        self.assertEqual(self.manager().listing()['active'], '机场一')
        self.assertNotEqual(self.manager().find('机场一')['revision'], old_revision)
        self.probe.assert_not_called()

    def test_unreachable_cached_subscription_switches_without_probe_or_download(self):
        self.add()
        self.execute('--use', '机场一')
        self.add('机场二')
        self.content['proxies'].append(dict(self.content['proxies'][0], name='C'))
        self.execute('--update', '机场二')
        self.probe.side_effect = control.InstallError('出网失败')
        self.download.reset_mock()
        self.execute('--use', '机场二')
        self.assertEqual(self.manager().listing()['active'], '机场二')
        current = json.loads((self.app / 'data/config.json').read_text())
        self.assertIn('C', [node['name'] for node in current['proxies']])
        import domino_sources as sources
        manager = self.manager()
        self.assertEqual(sources.read_source(self.app / 'data/source')[1],
                         sources.read_source(manager.cached(manager.find('机场二')) / 'source')[1])
        self.probe.assert_not_called()
        self.download.assert_not_called()

    def test_first_use_and_active_update_do_not_require_egress(self):
        self.add()
        self.probe.side_effect = control.InstallError('出网失败')
        self.execute('--use', '机场一')
        first_revision = self.manager().find('机场一')['revision']
        self.content['proxies'].append(dict(self.content['proxies'][0], name='C'))
        self.execute('--update', '机场一')
        manager = self.manager()
        self.assertEqual(manager.listing()['active'], '机场一')
        self.assertNotEqual(manager.find('机场一')['revision'], first_revision)
        self.assertIn('C', [node['name'] for node in manager.config()['proxies']])
        self.probe.assert_not_called()

    def test_failed_reload_restores_previous_config_and_selection(self):
        self.add()
        self.execute('--use', '机场一')
        self.add('机场二')
        before = (self.app / 'data/config.json').read_bytes()
        index_before = self.manager().index.read_bytes()
        cache = self.app / 'data/cache.db'
        cache.write_bytes(b'old kernel cache')
        original_response = self.response
        def fail(route, *args, **kwargs):
            if route == '/configs?force=true' and not getattr(fail, 'failed', False):
                fail.failed = True
                cache.write_bytes(b'live kernel cache')
                raise control.InstallError('配置加载失败')
            return original_response(route, *args, **kwargs)
        self.api.side_effect = fail
        with self.assertRaisesRegex(control.InstallError, '已恢复原配置'):
            self.execute('--use', '机场二')
        self.assertEqual((self.app / 'data/config.json').read_bytes(), before)
        self.assertEqual(self.manager().index.read_bytes(), index_before)
        self.assertEqual(self.manager().listing()['active'], '机场一')
        self.assertEqual(cache.read_bytes(), b'live kernel cache')
        self.assertTrue(any(call.args[:2] == ('/proxies/%E5%87%BA%E5%8F%A3', {'name': 'B'}) for call in self.api.call_args_list))

    def test_failed_first_use_restores_unassociated_configuration(self):
        self.add()
        original_response = self.response
        def fail(route, *args, **kwargs):
            if route == '/configs?force=true' and not getattr(fail, 'failed', False):
                fail.failed = True
                raise control.InstallError('配置加载失败')
            return original_response(route, *args, **kwargs)
        self.api.side_effect = fail
        with self.assertRaisesRegex(control.InstallError, '已恢复原配置'):
            self.execute('--use', '机场一')
        self.assertEqual(json.loads((self.app / 'data/config.json').read_text()), self.original)
        self.assertFalse((self.app / 'data/subscription.json').exists())
        self.assertFalse(self.manager().find('机场一').get('revision'))

    def test_snapshot_can_be_switched_back_without_a_url(self):
        self.execute('--import-current', '原有配置')
        self.add()
        self.execute('--use', '机场一')
        self.execute('--use', '原有配置')
        self.assertEqual(self.manager().listing()['active'], '原有配置')
        current = json.loads((self.app / 'data/config.json').read_text())
        self.assertEqual(len(current['proxies']), 1)
        with self.assertRaisesRegex(control.InstallError, '本地快照'):
            self.execute('--update', '原有配置')

    def test_rename_address_change_and_delete_with_current_subscription_guard(self):
        self.add()
        self.execute('--rename', '机场一', '--new-name', '主力')
        self.execute('--use', '主力')
        with self.assertRaisesRegex(control.InstallError, '不能删除当前'):
            self.execute('--remove', '主力')
        self.execute('--set-url', '主力', '--url', 'https://new.example/sub?token=OTHER-PRIVATE')
        self.assertFalse(self.manager().find('主力').get('revision'))
        self.add('备用')
        self.execute('--remove', '备用')
        self.assertEqual(len(self.manager().listing()['configs']), 1)

    def test_update_all_reports_failure_and_still_updates_other_subscriptions(self):
        self.add()
        self.add('机场二')
        original_download = self.download_config
        calls = []
        def download(url, path, proxy, *, user_agent=None):
            calls.append(url)
            if len(calls) == 1:
                raise tool.ToolError('下载失败')
            return original_download(url, path, proxy, user_agent=user_agent)
        self.download.side_effect = download
        with self.assertRaisesRegex(control.InstallError, '部分订阅更新失败'):
            self.execute('--update-all')
        self.assertFalse(self.manager().find('机场一').get('revision'))
        self.assertTrue(self.manager().find('机场二').get('revision'))

    def test_http_provider_is_downloaded_fresh_and_copied_to_runtime_resources(self):
        self.content['proxies'] = []
        self.content['proxy-providers'] = {'机场': {'type': 'http', 'url': 'https://provider.example/nodes', 'path': '/stale/config.yaml'}}
        self.content['proxy-groups'] = [{'name': '出口', 'type': 'select', 'use': ['机场']}]
        def download(url, path, proxy, *, user_agent=None):
            value = {'proxies': self.original['proxies']} if 'provider.example' in url else self.content
            path.write_text(json.dumps(value))
        self.download.side_effect = download
        self.add()
        self.execute('--use', '机场一')
        config = json.loads((self.app / 'data/config.json').read_text())
        resource = Path(config['proxy-providers']['机场']['path'])
        self.assertTrue(resource.is_relative_to(self.app / 'data/subscription-resources'))
        self.assertTrue(resource.is_file())
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(self.manager().find('机场一')['node_count'], 1)

    def test_init_subscription_registration_reuses_existing_name_and_marks_current(self):
        self.add('主力')
        self.manager().register_current('https://airport.example/config?token=SUBSCRIPTION-PRIVATE')
        self.assertEqual(self.manager().listing()['active'], '主力')
        self.assertEqual(len(self.manager().listing()['configs']), 1)
        self.download.assert_not_called()

    def test_global_selection_uses_new_group_if_previous_exit_disappeared(self):
        self.api.side_effect = None
        self.api.return_value = {'proxies': {'GLOBAL': {'all': ['DIRECT', '出口'], 'now': 'DIRECT'}}}
        self.manager().restore_selections({'GLOBAL':'removed'}, ['出口'])
        self.api.assert_called_with('/proxies/GLOBAL', {'name':'出口'})
        self.api.reset_mock()
        self.manager().restore_selections({'GLOBAL':'DIRECT'}, ['出口'])
        self.assertEqual(self.api.call_count, 2)
        self.api.assert_called_with('/proxies/GLOBAL', {'name':'DIRECT'})

    def test_malformed_profile_is_rejected_without_changing_live_configuration(self):
        self.add()
        for key, value in [('proxies', ['PRIVATE']), ('proxy-groups', [{}]), ('proxy-providers', [])]:
            with self.subTest(key=key):
                previous = self.content.get(key)
                self.content[key] = value
                with self.assertRaises(control.InstallError):
                    self.execute('--update', '机场一')
                if previous is None:
                    self.content.pop(key)
                else:
                    self.content[key] = previous
        self.api.assert_not_called()

    @unittest.skipUnless((Path(os.environ.get('DOMINO_TEST_CORE',str(Path.home() / '.local/share/domino/mihomo')))).is_file(), 'requires a locally installed Mihomo binary')
    def test_isolated_real_mihomo_offline_switch_and_failed_reload_restore_runtime(self):
        # Independent process, ephemeral ports, synthetic config, no external requests.
        source = Path(os.environ.get('DOMINO_TEST_CORE',str(Path.home() / '.local/share/domino/mihomo')))
        shutil.copy2(source, self.app / 'mihomo')
        (self.app / 'mihomo').chmod(0o755)
        with socket.socket() as first, socket.socket() as second:
            first.bind(('127.0.0.1', 0))
            second.bind(('127.0.0.1', 0))
            proxy_port, api_port = first.getsockname()[1], second.getsockname()[1]
        config = tool.sanitize_profile(self.original, {}, proxy_port, api_port)
        config['mode'] = 'global'
        config['rules'] = ['MATCH,DIRECT']
        (self.app / 'data/config.json').write_text(json.dumps(config))
        self.api.side_effect = REAL_API_JSON
        self.validation.side_effect = REAL_RUN
        self.download.side_effect = lambda url, path, proxy, **kwargs:path.write_text(json.dumps(self.content))
        with (self.home / 'core.log').open('w') as log:
            process = subprocess.Popen([str(self.app / 'mihomo'), '-d', str(self.app / 'data'), '-f', str(self.app / 'data/config.json')],
                                       stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        control.api_json('/version')
                        break
                    except (OSError,control.InstallError):
                        time.sleep(.05)
                else:
                    self.fail('isolated Mihomo did not start')
                self.add()
                self.execute('--use', '机场一')
                self.assertIn('B', control.api_json('/proxies')['proxies'])
                self.assertEqual(control.api_json('/configs')['mixed-port'], proxy_port)
                before = (self.app / 'data/config.json').read_bytes()
                self.add('备用')
                self.content['proxies'].append({'name': 'C', 'type': 'socks5', 'server': 'third.example', 'port': 1080})
                self.probe.side_effect = control.InstallError('synthetic health failure')
                self.execute('--use', '备用')
                self.assertIn('C', control.api_json('/proxies')['proxies'])
                self.assertNotEqual((self.app / 'data/config.json').read_bytes(), before)
                self.assertEqual(self.manager().listing()['active'], '备用')
                self.probe.assert_not_called()
                before = (self.app / 'data/config.json').read_bytes()
                def fail_reload(route, *args, **kwargs):
                    if route == '/configs?force=true' and not getattr(fail_reload, 'failed', False):
                        fail_reload.failed = True
                        raise control.InstallError('synthetic reload failure')
                    return REAL_API_JSON(route, *args, **kwargs)
                self.api.side_effect = fail_reload
                with self.assertRaisesRegex(control.InstallError, '已恢复原配置'):
                    self.execute('--use', '机场一')
                self.assertIn('C', control.api_json('/proxies')['proxies'])
                self.assertEqual((self.app / 'data/config.json').read_bytes(), before)
                self.assertEqual(self.manager().listing()['active'], '备用')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def test_subscription_cli_routes_local_and_remote_options(self):
        for target in ['localhost', 'alice@host']:
            with self.subTest(target=target), patch.object(tool, 'run') as run, patch.object(tool, 'SSH') as ssh:
                self.assertEqual(tool.main(['configs', target, '--use', '机场一', '--json']), 0)
                if target == 'localhost':
                    argv = run.call_args.args[0]
                    self.assertIn('--use=机场一', argv)
                    ssh.assert_not_called()
                else:
                    action = ssh.return_value.__enter__.return_value.action
                    self.assertIn('--use=机场一', action.call_args.args)

    def test_batch_add_without_url_fails_without_prompting(self):
        for action in ['add','set-url']:
            with self.subTest(action=action), patch.object(tool, 'run') as run, redirect_stderr(io.StringIO()):
                self.assertEqual(tool.main(['configs',action,'机场','--batch']),1)
            run.assert_not_called()

    def test_short_commands_preserve_names_and_target_for_local_and_remote_management(self):
        commands = [(['add','机场 A'], ['--add=机场 A']),
                    (['set-url','机场 A'], ['--set-url=机场 A']),
                    (['switch','机场 A'], ['--use=机场 A']),
                    (['update','机场 A'], ['--update=机场 A']),
                    (['update','all'], ['--update-all']),
                    (['rename','机场 A','备用 B'], ['--rename=机场 A','--new-name=备用 B']),
                    (['remove','备用 B'], ['--remove=备用 B'])]
        for command, expected in commands:
            for target in [None,'localhost','alice@host']:
                with self.subTest(command=command,target=target), patch.object(tool,'run') as run, patch.object(tool,'SSH') as ssh:
                    argv=['configs',*command]+([target] if target else [])+['--json']
                    self.assertEqual(tool.main(argv),0)
                    if target=='alice@host':
                        forwarded=ssh.return_value.__enter__.return_value.action.call_args.args
                    else:
                        forwarded=run.call_args.args[0][2:]
                        ssh.assert_not_called()
                    self.assertEqual(forwarded[0],'configs')
                    for flag in expected:
                        self.assertIn(flag,forwarded)
                    self.assertIn('--json',forwarded)
                    if command==['update','all']:
                        self.assertNotIn('--update=all',forwarded)

    def test_add_preserves_explicit_url_in_batch_mode_without_requesting_a_terminal(self):
        url='https://example.test/config?token=PRIVATE-TOKEN'
        for action, target in [(action,target) for action in ['add','set-url'] for target in ['localhost','alice@host']]:
            with self.subTest(action=action,target=target), patch.object(tool,'run') as run, patch.object(tool,'SSH') as ssh:
                self.assertEqual(tool.main(['configs',action,'机场 A',target,'--url',url,'--batch']),0)
                if target=='localhost':
                    forwarded=run.call_args.args[0]
                else:
                    call=ssh.return_value.__enter__.return_value.action.call_args
                    forwarded=call.args
                    self.assertNotIn('tty',call.kwargs)
                self.assertIn('--'+action+'=机场 A',forwarded)
                self.assertIn('--url='+url,forwarded)

    def test_subscription_named_all_can_be_updated_without_updating_every_subscription(self):
        with patch.object(tool,'run') as run:
            self.assertEqual(tool.main(['configs','--update','all']),0)
        self.assertIn('--update=all',run.call_args.args[0])
        self.assertNotIn('--update-all',run.call_args.args[0])

    def test_custom_rules_survive_subscription_updates_and_switches_without_baking_into_snapshots(self):
        rule='DOMAIN-SUFFIX,custom.test,DIRECT'
        control.write_private(control.custom_rules_path(),json.dumps({'schema':1,'prepend':[rule]}))
        self.add()
        self.add('备用')
        self.execute('--use','机场一')
        self.assertEqual(json.loads((self.app/'data/config.json').read_text())['rules'],[rule,*self.content['rules']])
        self.content['rules']=['DOMAIN-SUFFIX,new.test,DIRECT','MATCH,出口']
        self.execute('--update','机场一')
        self.assertEqual(json.loads((self.app/'data/config.json').read_text())['rules'],[rule,*self.content['rules']])
        self.execute('--import-current','快照')
        manager=self.manager()
        snapshot=json.loads((manager.cached(manager.find('快照'))/'config.json').read_text())
        self.assertNotIn(rule,snapshot['rules'])
        self.execute('--use','备用')
        self.assertEqual(json.loads((self.app/'data/config.json').read_text())['rules'][0],rule)

    def test_failed_subscription_switch_restores_rule_base_and_custom_preferences(self):
        rule='DOMAIN-SUFFIX,custom.test,DIRECT'
        control.write_private(control.custom_rules_path(),json.dumps({'schema':1,'prepend':[rule]}))
        self.add()
        self.execute('--use','机场一')
        old_base=(self.app/'data/rules-base.json').read_bytes()
        self.add('备用')
        self.content['rules']=['MATCH,DIRECT']
        self.execute('--update','备用')
        self.validation.side_effect=control.InstallError('synthetic validation failure')
        with self.assertRaisesRegex(control.InstallError,'已恢复原配置'):
            self.execute('--use','备用')
        self.assertEqual((self.app/'data/rules-base.json').read_bytes(),old_base)
        self.assertEqual(control.custom_rules(),[rule])

    def prepared_bundle(self, profile_id='profile-one', profile_name='xlink'):
        import domino_sources as sources
        bundle = self.home / ('bundle-' + __import__('uuid').uuid4().hex)
        data = bundle / 'data'
        data.mkdir(parents=True)
        origin = sources.origin_info(self.content, self.home / 'selected.yaml')
        origin.update(capture_kind='verge-runtime', origin_label='Clash Verge 运行配置',
                      profile_id=profile_id, profile_name=profile_name, association='index',
                      identity=sources._digest({'kind': 'verge-runtime', 'profile': profile_id}))
        sources.create_source(self.content, self.home / 'selected.yaml', data / 'source', metadata=origin)
        runtime = sources.derive_runtime(data / 'source', data, {}, 17897, 19091)
        (data / 'config.json').write_text(json.dumps(runtime))
        (bundle / 'selections.json').write_text('{"出口":"B"}')
        (bundle / 'registration.json').write_text('{"version":1,"kind":"snapshot"}')
        return bundle

    def test_prepared_capture_registration_preserves_same_name_online_item_and_user_rename(self):
        import domino_sources as sources
        self.add('xlink')
        online_id = self.manager().find('xlink')['id']
        bundle = self.prepared_bundle()
        self.download.reset_mock()
        subscriptions.register_installed(control, bundle)
        manager = self.manager()
        snapshot = next(v for v in manager.registry['items'] if v['kind'] == 'snapshot')
        self.assertEqual(manager.listing()['active'], snapshot['name'])
        self.assertEqual(manager.find('xlink')['id'], online_id)
        self.assertEqual(snapshot['node_count'], 2)
        self.assertRegex(snapshot['name'], r'^xlink-[A-Za-z0-9]{6}$')
        self.assertNotIn('url', snapshot)
        self.execute('--rename', snapshot['name'], '--new-name', '我的捕获')
        old_revision = snapshot['revision']
        self.content['proxies'].append(dict(self.content['proxies'][0], name='C'))
        second = self.prepared_bundle()
        subscriptions.register_installed(control, second)
        updated = self.manager().find('我的捕获')
        self.assertEqual(updated['id'], snapshot['id'])
        self.assertNotEqual(updated['revision'], old_revision)
        self.assertEqual(len(self.manager().registry['items']), 2)
        self.assertEqual(sources.read_source(self.manager().cached(updated) / 'source')[0]['proxies'][-1]['name'], 'C')
        subscriptions.register_installed(control, self.prepared_bundle('different-profile'))
        self.assertEqual(len(self.manager().registry['items']), 3)
        self.download.assert_not_called()

    def test_capture_uses_plain_name_without_collision_and_reuses_name_on_recapture(self):
        bundle = self.prepared_bundle()
        subscriptions.register_installed(control, bundle)
        first = self.manager().registry['items'][0]
        self.assertEqual(first['name'], 'xlink')
        subscriptions.register_installed(control, bundle)
        manager = self.manager()
        self.assertEqual(len(manager.registry['items']), 1)
        self.assertEqual(manager.registry['items'][0]['id'], first['id'])
        self.assertEqual(manager.registry['items'][0]['name'], 'xlink')

    def test_generated_name_retries_suffix_collision_and_preserves_length_limit(self):
        self.add('xlink')
        self.add('xlink-aaaaaa')
        with patch.object(subscriptions.secrets, 'choice', side_effect=list('aaaaaaxqEiJS')):
            self.assertEqual(self.manager().unique_name('xlink'), 'xlink-xqEiJS')
        base = '长' * 100
        self.add(base)
        with patch.object(subscriptions.secrets, 'choice', return_value='Z'):
            name = self.manager().unique_name(base)
        self.assertEqual(len(name), 100)
        self.assertTrue(name.endswith('-ZZZZZZ'))

    def test_installed_registration_uses_prepared_baseline_not_target_overlay_or_live_api(self):
        bundle = self.prepared_bundle()
        base = json.loads((bundle / 'data/config.json').read_text())
        (bundle / 'data/rules-base.json').write_text(json.dumps(base['rules']))
        effective = dict(base, rules=['DOMAIN,overlay.test,DIRECT', *base['rules']])
        (self.app / 'data/config.json').write_text(json.dumps(effective))
        subscriptions.register_installed(control, bundle)
        manager = self.manager()
        item = manager.registry['items'][0]
        cached = json.loads((manager.cached(item) / 'config.json').read_text())
        self.assertEqual(cached['rules'], base['rules'])
        self.assertEqual(item['selections'], {'出口': 'B'})
        self.api.assert_not_called()
        self.download.assert_not_called()

    def test_install_registry_rollback_restores_exact_index_and_only_transaction_revisions(self):
        self.add()
        self.execute('--update', '机场一')
        manager = self.manager()
        manager.index.chmod(0o640)
        before = manager.index.read_bytes()
        old_cache = manager.cached(manager.registry['items'][0])
        cache_before = (old_cache / 'config.json').read_bytes()
        backup = self.home / 'install-backup'
        backup.mkdir()
        subscriptions.snapshot_registry(control, backup)
        unrelated = manager.root / 'cache' / ('f' * 32)
        unrelated.mkdir()
        (unrelated / 'unrelated').write_text('leave alone')
        subscriptions.register_installed(control, self.prepared_bundle())
        created = self.manager().registry['items'][-1]['revision']
        shutil.rmtree(old_cache)
        subscriptions.restore_registry(control, backup)
        self.assertEqual(manager.index.read_bytes(), before)
        self.assertEqual(manager.index.stat().st_mode & 0o777, 0o640)
        self.assertEqual((old_cache / 'config.json').read_bytes(), cache_before)
        self.assertFalse((manager.root / 'cache' / created).exists())
        self.assertEqual((unrelated / 'unrelated').read_text(), 'leave alone')

    def test_registry_absence_restored_but_legacy_backup_has_no_authority(self):
        backup = self.home / 'install-backup'
        backup.mkdir()
        subscriptions.snapshot_registry(control, backup)
        subscriptions.register_installed(control, self.prepared_bundle())
        manager = self.manager()
        revision = manager.registry['items'][0]['revision']
        subscriptions.restore_registry(control, backup)
        self.assertFalse(manager.index.exists())
        self.assertFalse((manager.root / 'cache' / revision).exists())
        self.add()
        before = manager.index.read_bytes()
        subscriptions.restore_registry(control, self.home / 'old-backup')
        self.assertEqual(manager.index.read_bytes(), before)

    def test_pending_install_and_malformed_registration_are_read_only(self):
        bundle = self.prepared_bundle()
        (bundle / 'data/config.json').write_text('{"proxies":[],"proxy-groups":[]}')
        subscriptions.register_installed(control, bundle)
        self.assertFalse(self.manager().index.exists())
        for envelope in [{'version': 1, 'kind': 'snapshot', 'url': 'https://private.test'},
                         {'version': 1, 'kind': 'subscription', 'url': 'https://private.test', 'preserve_current': True}]:
            (bundle / 'registration.json').write_text(json.dumps(envelope))
            with self.assertRaises(Exception):
                subscriptions.validate_install_registration(control, bundle)
        self.assertFalse(self.manager().index.exists())

    def test_cached_and_active_sources_track_revisions_inactive_update_switch_and_rollback(self):
        import domino_sources as sources
        self.add()
        self.execute('--use', '机场一')
        first = sources.read_source(self.app / 'data/source')[1]
        self.add('备用')
        self.content['proxies'].append(dict(self.content['proxies'][0], name='C'))
        self.execute('--update', '备用')
        self.assertEqual(sources.read_source(self.app / 'data/source')[1], first)
        self.execute('--use', '备用')
        second = sources.read_source(self.app / 'data/source')[1]
        self.assertNotEqual(first['parsed_digest'], second['parsed_digest'])
        self.validation.side_effect = control.InstallError('fail')
        with self.assertRaises(control.InstallError):
            self.execute('--use', '机场一')
        self.assertEqual(sources.read_source(self.app / 'data/source')[1], second)
        self.assertEqual(self.manager().listing()['active'], '备用')

    def test_switch_to_legacy_cache_clears_stale_source_and_import_current_is_runtime_snapshot(self):
        import domino_sources as sources
        self.add()
        self.execute('--use', '机场一')
        self.execute('--import-current', '运行快照')
        manager = self.manager()
        snapshot = manager.find('运行快照')
        self.assertEqual(sources.read_source(manager.cached(snapshot) / 'source')[1]['capture_kind'], 'runtime-snapshot')
        shutil.rmtree(manager.cached(snapshot) / 'source')
        self.execute('--use', '运行快照')
        self.assertFalse((self.app / 'data/source').exists())
        self.assertEqual(sources.public_info(self.app / 'data')['status'], 'unknown')

    def test_explicit_online_registration_matches_url_only_and_verified_reinstall_preserves_association(self):
        import domino_sources as sources
        self.add('xlink')
        online = self.manager().find('xlink')
        bundle = self.prepared_bundle()
        envelope = {'version': 1, 'kind': 'subscription', 'name': 'xlink',
                    'url': 'https://different.example/sub?PRIVATE'}
        (bundle / 'registration.json').write_text(json.dumps(envelope))
        subscriptions.register_installed(control, bundle)
        manager = self.manager()
        installed = next(v for v in manager.registry['items'] if v['id'] != online['id'])
        self.assertRegex(installed['name'], r'^xlink-[A-Za-z0-9]{6}$')
        self.assertEqual(installed['kind'], 'subscription')
        reinstall = self.prepared_bundle()
        (reinstall / 'data/subscription.json').write_text(json.dumps({'id': installed['id']}))
        (reinstall / 'registration.json').write_text(json.dumps({'version': 1, 'kind': 'snapshot', 'preserve_current': True}))
        subscriptions.register_installed(control, reinstall)
        self.assertEqual(len(self.manager().registry['items']), 2)
        self.assertEqual(self.manager().listing()['active'], installed['name'])
        self.assertEqual(self.manager().find(installed['name'])['url'], envelope['url'])
        stale = self.prepared_bundle('unrelated-profile')
        (stale / 'data/subscription.json').write_text(json.dumps({'id': installed['id']}))
        (stale / 'registration.json').write_text(json.dumps({'version': 1, 'kind': 'snapshot', 'preserve_current': True}))
        subscriptions.register_installed(control, stale)
        self.assertEqual(len(self.manager().registry['items']), 3)
        self.assertEqual(self.manager().registry['items'][-1]['kind'], 'snapshot')
        self.download.assert_not_called()

    def test_registry_restore_rejects_symlink_before_any_index_or_cache_mutation(self):
        self.add()
        before = self.manager().index.read_bytes()
        backup = self.home / 'backup'
        subscriptions.snapshot_registry(control, backup)
        (backup / 'registry/evil').symlink_to(self.app / 'data/config.json')
        with self.assertRaises(Exception):
            subscriptions.restore_registry(control, backup)
        self.assertEqual(self.manager().index.read_bytes(), before)

    def test_provider_payload_certificate_rebased_when_cached_snapshot_is_applied(self):
        import domino_sources as sources
        cert = self.app / 'data/client.pem'
        cert.write_text('PRIVATE-CERT')
        provider = self.app / 'data/client-provider.json'
        provider.write_text(json.dumps({'proxies': [dict(self.original['proxies'][0], certificate='client.pem')]}))
        current = copy.deepcopy(self.original)
        current['proxy-providers'] = {'file': {'type': 'file', 'path': 'client-provider.json'}}
        (self.app / 'data/config.json').write_text(json.dumps(current))
        self.execute('--import-current', '证书快照')
        self.execute('--use', '证书快照')
        runtime = json.loads((self.app / 'data/config.json').read_text())
        payload = tool.load_yaml(Path(runtime['proxy-providers']['file']['path']))
        certificate = Path(payload['proxies'][0]['certificate'])
        self.assertTrue(certificate.is_relative_to(self.app / 'data/subscription-resources'))
        self.assertEqual(certificate.read_text(), 'PRIVATE-CERT')
        source = sources.read_source(self.app / 'data/source')[0]
        owned = tool.load_yaml(self.app / 'data/source' / source['proxy-providers']['file']['path'])
        self.assertFalse(Path(owned['proxies'][0]['certificate']).is_absolute())


if __name__ == '__main__':
    unittest.main()
