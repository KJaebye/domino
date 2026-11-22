import argparse
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as tool
import domino_agent
from domino_service import OPERATIONS, validate


def assert_result_schema(case, value, schema):
    # Request validation lacks result-only nullable unions and array item traversal.
    schema = dict(schema)
    kind = schema.get('type')
    if isinstance(kind, list):
        actual = {str: 'string', bool: 'boolean', int: 'integer', float: 'number',
                  dict: 'object', list: 'array', type(None): 'null'}.get(type(value))
        case.assertIn(actual, kind)
        schema['type'] = actual
        if actual == 'null':
            schema.pop('type')
    properties = schema.get('properties', {})
    shallow = dict(schema)
    if properties:
        shallow['properties'] = dict.fromkeys(properties, {})
    validate(value, shallow)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in properties:
                assert_result_schema(case, item, properties[key])
    if isinstance(value, list) and 'items' in schema:
        for item in value:
            assert_result_schema(case, item, schema['items'])


class SourceTests(unittest.TestCase):
    def test_source_probe_uses_explicit_proxy_and_bounded_timeout(self):
        report={'http_status':'204','connect_status':'200','tcp_seconds':'0.001','tls_seconds':'0.1','total_seconds':'0.2'}
        process=subprocess.CompletedProcess([],0,stdout='\nDOMINO_PROBE '+json.dumps(report),stderr='')
        with patch.object(tool.subprocess, 'run',return_value=process) as run:
            tool.probe_source('http://127.0.0.1:7897', 'https://example.test/', timeout=5)
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index('--max-time') + 1], '5')
        self.assertEqual(argv[argv.index('--connect-timeout') + 1], '5')
        self.assertEqual(run.call_args.kwargs['timeout'], 10)
        self.assertIn('proxy = "http://127.0.0.1:7897"', run.call_args.kwargs['input'])

    def test_probe_reports_connection_tls_http_and_timeout_failures_without_leaking_output(self):
        cases=[(7,{},'PROBE_PORT_UNREACHABLE','proxy'),
               (28,{'tcp_seconds':'0'},'PROBE_CONNECT_TIMEOUT','proxy'),
               (28,{'tcp_seconds':'0.01'},'PROBE_TUNNEL_TIMEOUT','tunnel'),
               (28,{'tcp_seconds':'0.01','connect_status':'200'},'PROBE_TLS_TIMEOUT','tls'),
               (28,{'tcp_seconds':'0.01','connect_status':'200','tls_seconds':'0.2'},'PROBE_RESPONSE_TIMEOUT','http'),
               (35,{'tcp_seconds':'0.01','connect_status':'200'},'PROBE_TLS_FAILED','tls'),
               (60,{'tcp_seconds':'0.01','connect_status':'200'},'PROBE_TLS_CERTIFICATE','tls'),
               (22,{'tcp_seconds':'0.01','connect_status':'200','tls_seconds':'0.2','http_status':'403'},'PROBE_HTTP_ERROR','http'),
               (56,{'tcp_seconds':'0.01','connect_status':'407'},'PROBE_PROXY_AUTH','tunnel')]
        for code,changes,expected,stage in cases:
            data=dict(http_status='000',connect_status='000',tcp_seconds='0',tls_seconds='0',total_seconds='0.5')
            data.update(changes)
            process=subprocess.CompletedProcess([],code,stdout='PRIVATE-BODY\nDOMINO_PROBE '+json.dumps(data),stderr='PRIVATE-TOKEN')
            with self.subTest(code=code,changes=changes), patch.object(tool.subprocess,'run',return_value=process):
                result=tool.check_source_proxy('http://127.0.0.1:7897')
            self.assertFalse(result['healthy'])
            self.assertEqual(result['check_code'],expected)
            self.assertEqual(result['check_stage'],stage)
            self.assertTrue(result['check_hint'])
            self.assertEqual(result['check_details']['curl_exit_code'],code)
            self.assertNotIn('PRIVATE',json.dumps(result))

    def test_missing_timeout_metrics_do_not_claim_the_local_port_failed(self):
        error=subprocess.TimeoutExpired(['curl'],10)
        with patch.object(tool.subprocess,'run',side_effect=error):
            result=tool.check_source_proxy('http://127.0.0.1:7897')
        self.assertEqual(result['check_code'],'PROBE_REQUEST_TIMEOUT')
        self.assertEqual(result['check_stage'],'request')

    def test_single_source_and_list_share_detailed_failure_diagnostics(self):
        data=dict(http_status='000',connect_status='200',tcp_seconds='0.001',tls_seconds='0',total_seconds='0.5')
        process=subprocess.CompletedProcess([],35,stdout='\nDOMINO_PROBE '+json.dumps(data),stderr='PRIVATE')
        with patch.object(tool,'discover_source',return_value=None),patch.object(tool,'discover_proxy',return_value='http://127.0.0.1:7897'), \
                patch.object(tool.subprocess,'run',return_value=process):
            args=tool.build_parser().parse_args(['scan'])
            result=tool.collect_source(args)
        self.assertEqual(result['check_code'],'PROBE_TLS_FAILED')
        self.assertTrue(result['check_details']['proxy_connected'])
        self.assertIn('不能直接归因',result['check_hint'])

    def profile(self):
        return {'mixed-port': 7897, 'allow-lan': True, 'secret': 'TEST-OLD-SECRET',
                'tun': {'enable': True, 'auto-route': True},
                'external-controller-unix': '/tmp/mac-only.sock',
                'interface-name': 'en0', 'dns': {'enable': True},
                'proxies': [{'name': 'a', 'type': 'socks5', 'server': 'example.test', 'port': 1080,
                             'password': 'TEST-NODE-PASSWORD', 'interface-name': 'en0'}],
                'proxy-groups': [{'name': 'select', 'type': 'select', 'proxies': ['a', 'DIRECT']}],
                'rules': ['MATCH,select']}

    def test_export_adapts_mac_settings_and_preserves_credentials(self):
        raw = self.profile()
        before = copy.deepcopy(raw)
        result = tool.sanitize_profile(raw, {'select': 'DIRECT'}, 17890, 19091)
        self.assertEqual(raw, before)
        self.assertFalse(result['allow-lan'])
        self.assertFalse(result['tun']['enable'])
        self.assertTrue(result['dns']['enable'])
        self.assertTrue(result['dns']['use-system-hosts'])
        self.assertEqual(result['dns']['listen'], '')
        self.assertNotIn('external-controller-unix', result)
        self.assertNotIn('interface-name', result['proxies'][0])
        self.assertEqual(result['proxies'][0]['password'], 'TEST-NODE-PASSWORD')
        self.assertEqual(result['proxy-groups'][0]['proxies'][0], 'DIRECT')
        self.assertNotEqual(result['secret'], 'TEST-OLD-SECRET')

    def test_internal_dns_uses_target_hosts_without_copying_source_dns_or_opening_a_listener(self):
        raw = self.profile()
        raw['dns'].update({'listen': '0.0.0.0:53', 'enhanced-mode': 'fake-ip',
                           'nameserver': ['127.0.0.1:5553'], 'use-system-hosts': False})
        for ipv6 in (False, True):
            raw['ipv6'] = ipv6
            result = tool.sanitize_profile(raw, {}, 17890, 19091)
            self.assertEqual(result['dns']['nameserver'], ['system'])
            self.assertEqual(result['dns']['enhanced-mode'], 'redir-host')
            self.assertTrue(result['dns']['use-hosts'])
            self.assertTrue(result['dns']['use-system-hosts'])
            self.assertEqual(result['dns']['listen'], '')
            self.assertEqual(result['dns']['ipv6'], ipv6)
            self.assertFalse(result['tun']['enable'])
        self.assertEqual(raw['dns']['listen'], '0.0.0.0:53')

    def test_global_mode_is_preserved_and_disabled_source_is_refused(self):
        raw = self.profile()
        raw['mode'] = 'global'
        self.assertEqual(tool.sanitize_profile(raw, {}, 7897, 19090)['mode'], 'global')
        raw['mode'] = 'direct'
        with self.assertRaises(tool.ToolError):
            tool.sanitize_profile(raw, {}, 7897, 19090)

    def test_provider_cache_is_copied_and_path_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'cache.yaml').write_text('proxies: []\n')
            data = root / 'bundle'
            data.mkdir()
            profile = {'proxy-providers': {'private/subscription': {'type': 'http', 'path': 'cache.yaml',
                         'url': 'https://example.test/?token=TEST-SECRET'}}}
            with patch.object(tool, 'download') as download:
                tool.provider_resources(profile, source, data, None)
            download.assert_not_called()
            provider = profile['proxy-providers']['private/subscription']
            self.assertTrue(provider['path'].startswith('providers/proxy-providers/'))
            self.assertEqual((data / provider['path']).read_text(), 'proxies: []\n')
            self.assertEqual((data / provider['path']).stat().st_mode & 0o777, 0o600)
            self.assertIn('TEST-SECRET', provider['url'])

    def test_missing_provider_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = {'rule-providers': {'rules': {'type': 'file', 'path': 'missing.mrs'}}}
            with self.assertRaises(tool.ToolError):
                tool.provider_resources(profile, Path(temp), Path(temp) / 'bundle', None)

    def test_uncached_http_provider_is_bootstrapped_on_source(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = {'rule-providers': {'r': {'type': 'http', 'format': 'mrs', 'url': 'https://example.test/r'}}}
            def download(url, target, proxy):
                target.write_bytes(b'TEST-MRS')
            with patch.object(tool, 'download', side_effect=download):
                tool.provider_resources(profile, Path(temp), Path(temp) / 'data', 'http://127.0.0.1:7897')
            target = Path(temp) / 'data' / profile['rule-providers']['r']['path']
            self.assertEqual(target.suffix, '.mrs')
            self.assertEqual(target.read_bytes(), b'TEST-MRS')

    def test_release_uses_portable_x86_binary_and_requires_hash(self):
        tag = 'v1.2.3'
        def asset(name):
            return {'name': name, 'digest': 'sha256:' + 'a' * 64,
                    'browser_download_url': f'https://github.com/MetaCubeX/mihomo/releases/download/{tag}/{name}'}
        release = {'tag_name': tag, 'assets': [asset('mihomo-linux-amd64-v3-v1.2.3.gz'),
                    asset('mihomo-linux-amd64-v1-v1.2.3.gz'), asset('mihomo-linux-arm64-v1.2.3.gz')]}
        self.assertEqual(tool.release_asset(release, 'amd64')[1]['name'], 'mihomo-linux-amd64-v1-v1.2.3.gz')
        self.assertEqual(tool.release_asset(release, 'arm64')[1]['name'], 'mihomo-linux-arm64-v1.2.3.gz')
        release['assets'][1]['digest'] = None
        with self.assertRaises(tool.ToolError):
            tool.release_asset(release, 'amd64')

    def test_nonofficial_release_url_rejected(self):
        release = {'tag_name': 'v1.2.3', 'assets': [{'name': 'mihomo-linux-arm64-v1.2.3.gz',
                   'digest': 'sha256:' + 'a' * 64, 'browser_download_url': 'https://evil.test/binary'}]}
        with self.assertRaises(tool.ToolError):
            tool.release_asset(release, 'arm64')


class SourceListingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.patch = patch.object(Path, 'home', return_value=self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.probe_patch = patch.object(tool, 'probe_source')
        self.probe = self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)

    def config(self, relative, data=None):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data if data is not None else {
            'mixed-port': 7897, 'secret': 'PRIVATE-CONTROLLER',
            'proxies': [{'name': 'A', 'type': 'socks5', 'server': 'node.example',
                         'port': 1080, 'password': 'PRIVATE-NODE'}],
            'rules': ['MATCH,DIRECT']}))
        return path

    def test_lists_and_probes_sources_once_per_endpoint_without_changing_files(self):
        domino = self.config('.local/share/domino/data/config.json')
        verge = self.config('Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml')
        other = self.config('.config/mihomo/config.yaml')
        alias = self.home / '.config/clash/config.yaml'
        alias.parent.mkdir(parents=True)
        alias.symlink_to(verge)
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        output = io.StringIO()
        with patch.object(tool, 'probe_source') as probe, patch.object(tool, 'discover_proxy') as proxy, \
                patch.object(tool, 'SSH') as ssh, redirect_stdout(output):
            self.assertEqual(tool.main(['scan', '--json']), 0)
        result = json.loads(output.getvalue())
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        rows = {item['config']: item for item in result['sources']}
        self.assertEqual(set(rows), {str(domino), str(verge), str(other)})
        self.assertTrue(rows[str(domino)]['default'])
        self.assertFalse(rows[str(verge)]['default'])
        self.assertTrue(all('clients' not in item for item in rows.values()))
        self.assertTrue(all(item['compatible_config_found'] for item in rows.values()))
        self.assertTrue(all(item['healthy'] and item['exit_checked'] for item in rows.values()))
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        probe.assert_called_once_with('http://127.0.0.1:7897', 'https://www.cloudflare.com/cdn-cgi/trace', timeout=5)
        proxy.assert_not_called()
        ssh.assert_not_called()

    def test_domino_source_paths_are_public_read_only_and_do_not_add_runtime_entries(self):
        from domino_sources import create_source
        domino = self.config('.local/share/domino/data/config.json')
        original = self.config('external/original.yaml')
        create_source(tool.load_yaml(original), original, domino.parent / 'source')
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = tool.collect_sources()
        self.assertEqual(len(result['sources']), 1)
        item = result['sources'][0]
        self.assertEqual(item['import_source']['status'], 'known')
        self.assertEqual(Path(item['import_source']['snapshot_path']).resolve(), (domino.parent / 'source/config.json').resolve())
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        text = io.StringIO()
        with patch.object(tool, 'collect_sources', return_value=result), redirect_stdout(text):
            tool.list_sources(argparse.Namespace(json=False))
        self.assertIn('── Domino 管理', text.getvalue())
        self.assertNotIn('运行配置', text.getvalue())
        self.assertNotIn('源快照', text.getvalue())
        self.assertNotIn('导入时间', text.getvalue())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_managed_source_inspect_never_probes_old_port_or_environment_proxy(self):
        from domino_sources import create_source
        domino = self.config('.local/share/domino/data/config.json')
        original = self.config('external/original.yaml')
        create_source(tool.load_yaml(original), original, domino.parent / 'source')
        self.probe.reset_mock()
        with patch.object(tool, 'discover_proxy') as discover:
            result = tool.collect_source(argparse.Namespace(source=str(domino.parent / 'source/config.json')))
        self.assertEqual(result['source_kind'], 'import-snapshot')
        self.assertTrue(result['compatible_config_found'])
        self.assertIsNone(result['proxy'])
        self.assertFalse(result['exit_checked'])
        self.probe.assert_not_called()
        discover.assert_not_called()
        assert_result_schema(self, result, OPERATIONS['source.inspect']['result'])

    def test_corrupt_or_missing_managed_metadata_never_borrows_health(self):
        from domino_sources import create_source
        domino = self.config('.local/share/domino/data/config.json')
        original = self.config('external/original.yaml')
        create_source(tool.load_yaml(original), original, domino.parent / 'source')
        snapshot = domino.parent / 'source/config.json'
        snapshot.write_text(json.dumps(dict(tool.load_yaml(snapshot), mode='global')))
        for missing in [False, True]:
            if missing:
                (snapshot.parent / 'metadata.json').unlink()
            self.probe.reset_mock()
            with patch.object(tool, 'discover_proxy') as discover:
                result = tool.collect_source(argparse.Namespace(source=str(snapshot)))
            self.assertEqual(result['source_kind'], 'import-snapshot')
            self.assertFalse(result['compatible_config_found'])
            self.assertFalse(result['exit_checked'])
            self.assertIsNone(result['proxy'])
            self.probe.assert_not_called()
            discover.assert_not_called()

    def test_legacy_domino_scan_does_not_invent_or_save_source(self):
        self.config('.local/share/domino/data/config.json')
        result = tool.collect_sources()
        self.assertEqual(result['sources'][0]['import_source']['status'], 'unknown')
        self.assertFalse((self.home / '.local/share/domino/data/source').exists())
        text = io.StringIO()
        with patch.object(tool, 'collect_sources', return_value=result), redirect_stdout(text):
            tool.list_sources(argparse.Namespace(json=False))
        self.assertIn('Domino 管理 0 个', text.getvalue())
        self.assertNotIn('导入来源', text.getvalue())
        self.assertNotIn('源快照    ~/', text.getvalue())

    def test_bad_and_missing_configs_do_not_hide_other_sources(self):
        self.config('.local/share/domino/data/config.json', {})
        clash = self.config('.config/clash/config.yaml')
        broken = self.config('broken.json')
        broken.write_bytes(b'\xffPRIVATE-PARSE-CONTENT')
        bad_port = self.config('bad-port.json')
        data = json.loads(bad_port.read_text())
        bad_port.write_text(json.dumps(dict(data, **{'mixed-port': 'PRIVATE-INVALID-PORT'})))
        bad_nodes = self.config('bad-nodes.json', {'proxies': ['PRIVATE-INVALID-NODE']})
        missing = self.home / 'missing.yaml'
        paths = [self.home / '.local/share/domino/data/config.json', clash, broken, missing, bad_port, bad_nodes]
        with patch.object(tool, 'discover_sources', return_value=paths):
            result = tool.collect_sources()
        self.assertEqual(len(result['sources']), 6)
        valid = [item for item in result['sources'] if item['compatible_config_found']]
        self.assertEqual([item['config'] for item in valid], [str(clash)])
        self.assertEqual(sum(item['default'] for item in result['sources']), 1)
        self.assertTrue(all(item.get('config_error') for item in result['sources'] if not item['compatible_config_found']))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_each_endpoint_health_is_independent_and_missing_ports_are_not_probed(self):
        domino = self.config('.local/share/domino/data/config.json')
        raw = json.loads(domino.read_text())
        domino.write_text(json.dumps(dict(raw, **{'mixed-port': 17897})))
        clash = self.config('.config/clash/config.yaml')
        no_port = self.config('.config/mihomo/config.yaml', {key: value for key, value in raw.items() if key != 'mixed-port'})
        def probe(proxy, url, **kwargs):
            if proxy.endswith(':7897'):
                raise tool.ToolError('PRIVATE-PROBE-FAILURE')
        self.probe.side_effect = probe
        rows = {item['config']: item for item in tool.collect_sources()['sources']}
        self.assertTrue(rows[str(domino)]['healthy'])
        self.assertTrue(rows[str(clash)]['exit_checked'])
        self.assertFalse(rows[str(clash)]['healthy'])
        self.assertIn('check_error', rows[str(clash)])
        self.assertFalse(rows[str(no_port)]['exit_checked'])
        self.assertFalse(rows[str(no_port)]['healthy'])
        self.assertIsNone(rows[str(no_port)]['proxy'])
        self.assertEqual(self.probe.call_count, 2)
        self.assertNotIn('PRIVATE', json.dumps(rows))

    def test_no_nodes_still_checks_the_configured_proxy_endpoint(self):
        self.config('.local/share/domino/data/config.json', {'mixed-port': 17897})
        item = tool.collect_sources()['sources'][0]
        self.assertFalse(item['compatible_config_found'])
        self.assertTrue(item['healthy'])
        self.assertTrue(item['exit_checked'])

    def test_empty_list_is_successful_and_does_not_discover_special_clients(self):
        self.config('Library/Application Support/com.gcapp.clients.apex/config.json')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(tool.main(['scan', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), {'sources': []})

    def test_legacy_bindings_are_ignored_without_reading_or_changing_them(self):
        domino = self.config('.local/share/domino/data/config.json')
        custom = self.config('custom/config.json')
        legacy = self.config('.config/domino/clients.json', {'old': {'config': str(custom)}})
        legacy.write_bytes(b'not valid JSON - must not be read')
        saved = legacy.read_bytes()
        result = tool.collect_sources()
        self.assertEqual([item['config'] for item in result['sources']], [str(domino)])
        self.assertEqual(legacy.read_bytes(), saved)
        explicit = tool.collect_source(argparse.Namespace(source=str(custom)))
        self.assertTrue(explicit['compatible_config_found'])
        self.assertEqual(explicit['config'], str(custom.resolve()))

    def test_explicit_scan_checks_config_and_proxy_exit(self):
        config = self.config('.local/share/domino/data/config.json')
        output = io.StringIO()
        with patch.object(tool, 'probe_source') as probe, \
                patch.object(tool, 'discover_proxy', return_value=None), redirect_stdout(output):
            self.assertEqual(tool.main(['scan', '--source', str(config), '--json']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(Path(result['config']).resolve(), config.resolve())
        self.assertTrue(result['healthy'])
        self.assertNotIn('sources', result)
        probe.assert_called_once()

    def test_human_list_displays_both_sources_and_default_marker(self):
        self.config('.local/share/domino/data/config.json')
        self.config('Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml')
        self.probe.side_effect = tool.ToolError('PRIVATE-FAILURE')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(tool.main(['scan']), 0)
        text = output.getvalue()
        for expected in ['外部配置 1 个', 'Domino 管理 0 个', 'Clash Verge',
                         '代理入口', '入口出网', 'http://127.0.0.1:7897', '检查未通过']:
            self.assertIn(expected, text)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('clash-verge.yaml',text)

    def managed_registry(self):
        items = [dict(id=f'{i+1:032x}', name=name, kind='snapshot', revision=f'{i+10:032x}',
                      node_count=count, updated_at='2026-11-15T15:18:00+00:00')
                 for i, (name, count) in enumerate([('xlink-xqEiJS', 32), ('xlink', 32), ('feiniao', 71)])]
        path = self.config('.config/domino/subscriptions/index.json', {'schema': 1, 'items': items})
        return path, items

    def test_scan_groups_all_managed_configs_after_external_sources_read_only(self):
        import domino_subscriptions
        runtime = self.config('.local/share/domino/data/config.json')
        raw = json.loads(runtime.read_text());raw['mixed-port'] = 17897
        runtime.write_text(json.dumps(raw))
        external = self.config('.config/mihomo/config.yaml')
        _, items = self.managed_registry()
        self.config('.local/share/domino/data/subscription.json', {'id': items[1]['id']})
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with patch.object(domino_subscriptions.Manager, 'cached', side_effect=AssertionError('scan loaded a saved cache')):
            collected = tool.collect_sources()
        managed = collected['managed_configs']
        self.assertEqual([item['name'] for item in managed['configs']], ['xlink-xqEiJS', 'xlink', 'feiniao'])
        self.assertEqual(managed['active'], 'xlink')
        self.assertEqual([item['active'] for item in managed['configs']], [False, True, False])
        self.assertEqual(len(collected['sources']), 2)
        self.assertEqual(self.probe.call_count, 2)
        assert_result_schema(self, collected, OPERATIONS['source.list']['result'])
        output = io.StringIO()
        with patch.object(tool, 'collect_sources', return_value=collected), redirect_stdout(output):
            tool.list_sources(argparse.Namespace(json=False))
        text = output.getvalue()
        self.assertLess(text.index('Mihomo'), text.index('── Domino 管理'))
        block = text[text.index('── Domino 管理'):]
        for word in ['3 个配置', 'xlink-xqEiJS', '● xlink', 'feiniao', '71']:
            self.assertIn(word, block)
        self.assertEqual(text.count('xlink-xqEiJS'), 1)
        self.assertIn('外部配置 1 个 · Domino 管理 3 个', text)
        for removed in ['运行配置', '入口出网', '代理入口', '导入来源', '源快照', '导入时间', 'domino test', 'deploy --source']:
            self.assertNotIn(removed, block)
        self.assertNotIn('PRIVATE', text + json.dumps(collected))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        self.assertEqual(collected['sources'][0]['config'], str(runtime))
        self.assertEqual(collected['sources'][1]['config'], str(external))

    def test_scan_shows_uncached_managed_configs_without_a_runtime(self):
        index, items = self.managed_registry()
        items[2].pop('revision');items[2]['kind'] = 'subscription'
        items[2]['url'] = 'https://subscription.example.test/profile?token=PRIVATE-TOKEN'
        index.write_text(json.dumps({'schema': 1, 'items': items}))
        before = index.read_bytes()
        result = tool.collect_sources()
        self.assertEqual(result['sources'], [])
        self.assertFalse(result['managed_configs']['configs'][2]['cached'])
        output = io.StringIO()
        with patch.object(tool, 'collect_sources', return_value=result), redirect_stdout(output):
            tool.list_sources(argparse.Namespace(json=False))
        for word in ['Domino 管理', 'xlink-xqEiJS', 'feiniao', '未缓存', '在线订阅']:
            self.assertIn(word, output.getvalue())
        self.assertNotIn('PRIVATE', json.dumps(result) + output.getvalue())
        self.assertNotIn('https://subscription', json.dumps(result))
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        self.assertEqual(before, index.read_bytes())
        self.probe.assert_not_called()

    def test_unreadable_managed_registry_does_not_hide_external_sources(self):
        self.config('.config/mihomo/config.yaml')
        index, _ = self.managed_registry()
        index.write_text('PRIVATE broken registry')
        before = index.read_bytes()
        result = tool.collect_sources()
        self.assertEqual(len(result['sources']), 1)
        self.assertIn('error', result['managed_configs'])
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        output = io.StringIO()
        with patch.object(tool, 'collect_sources', return_value=result), redirect_stdout(output):
            tool.list_sources(argparse.Namespace(json=False))
        self.assertIn('Mihomo', output.getvalue())
        self.assertIn('配置库无法读取', output.getvalue())
        self.assertNotIn('PRIVATE', json.dumps(result) + output.getvalue())
        self.assertEqual(before, index.read_bytes())

    def test_agent_maps_list_and_inspection_to_distinct_operations(self):
        parser = tool.build_parser()
        self.assertEqual(domino_agent.command_request(parser.parse_args(['scan'])), ('source.list', {}))
        self.assertEqual(domino_agent.command_request(parser.parse_args(['scan', '--source', '/tmp/config.yaml'])),
                         ('source.inspect', {'path': '/tmp/config.yaml'}))

    def test_source_and_source_list_are_not_entry_points(self):
        for arguments in [['source'], ['source', 'list']]:
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                tool.build_parser().parse_args(arguments)
            self.assertEqual(caught.exception.code, 2)


class VergeProfileTests(unittest.TestCase):
    config = SourceListingTests.config
    root = 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        home = patch.object(Path, 'home', return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        probe = patch.object(tool, 'probe_source')
        self.probe = probe.start()
        self.addCleanup(probe.stop)

    def index(self, items, current='remote-1'):
        return self.config(self.root + '/profiles.yaml', {'current': current, 'items': items})

    def saved(self, filename='remote.yaml'):
        return self.config(self.root + '/profiles/' + filename)

    def entry(self, uid='remote-1', filename='remote.yaml', name='Saved subscription', kind='remote'):
        return {'uid': uid, 'name': name, 'file': filename, 'type': kind,
                'url': 'https://subscription.example/?token=PRIVATE-URL',
                'option': {'password': 'PRIVATE-OPTION'}}

    def assert_unchecked(self, row):
        self.assertEqual(row['source_kind'], 'profile')
        self.assertIsNone(row['proxy'])
        self.assertFalse(row['healthy'])
        self.assertFalse(row['exit_checked'])
        self.assertTrue(row['check_note'])

    def test_real_yaml_index_exposes_only_local_remote_identity_without_reading_profiles(self):
        index = self.config(self.root + '/profiles.yaml')
        index.write_text('''current: remote-1
items:
  - uid: remote-1
    type: remote
    name: "Work subscription"
    file: remote.yaml
    url: "https://subscription.example/?token=PRIVATE-URL"
    option:
      user-agent: PRIVATE-AGENT
      merge: merge-1
      script: script-1
  - uid: local-1
    type: local
    name: "Local backup"
    file: local.yaml
  - uid: merge-1
    type: merge
    name: PRIVATE-MERGE
    file: merge.yaml
  - uid: script-1
    type: script
    name: PRIVATE-SCRIPT
    file: script.js
''')
        with patch.object(tool, 'load_yaml', wraps=tool.load_yaml) as load:
            profiles, warnings = tool.read_verge_profiles()
        load.assert_called_once_with(index)
        self.assertEqual(warnings, [])
        remote = self.home / self.root / 'profiles/remote.yaml'
        local = self.home / self.root / 'profiles/local.yaml'
        self.assertEqual(set(profiles), {remote.resolve(), local.resolve()})
        self.assertEqual(profiles[remote]['profile_id'], 'remote-1')
        self.assertEqual(profiles[remote]['profile_name'], 'Work subscription')
        self.assertIs(profiles[remote]['client_current'], True)
        self.assertIs(profiles[local]['client_current'], False)
        self.assertTrue(profiles[remote]['check_note'])
        self.assertNotIn('PRIVATE', json.dumps(list(profiles.values())))
        self.assertEqual(tool.source_identity(remote, profiles=profiles), profiles[remote])
        self.assertEqual(tool.source_identity(self.home / 'unindexed.yaml', profiles=profiles), {})
        self.probe.assert_not_called()

    def test_missing_index_does_not_create_or_read_alternative_roots(self):
        alternate = self.config('.config/io.github.clash-verge-rev.clash-verge-rev/profiles.yaml',
                                {'items': [self.entry()]})
        before = alternate.read_bytes()
        with patch.object(tool, 'load_yaml') as load:
            self.assertEqual(tool.read_verge_profiles(), ({}, []))
        load.assert_not_called()
        self.assertFalse((self.home / self.root).exists())
        self.assertEqual(alternate.read_bytes(), before)

    def test_outside_source_identity_does_not_read_the_profile_index(self):
        for path in [self.home / 'ordinary.yaml', self.home / self.root / 'profiles-other/ordinary.yaml']:
            with self.subTest(path=path), patch.object(tool, 'read_verge_profiles') as read:
                self.assertEqual(tool.source_identity(path), {})
            read.assert_not_called()

    def test_source_schemas_declare_profile_fields_and_optional_warnings(self):
        inspect = OPERATIONS['source.inspect']['result']
        listing = OPERATIONS['source.list']['result']
        item = listing['properties']['sources']['items']
        for schema in [inspect, item]:
            for field in ['source_kind', 'profile_id', 'profile_name', 'client_current', 'check_note']:
                self.assertIn(field, schema['properties'])
            self.assertEqual(set(schema['properties']['client_current']['type']), {'boolean', 'null'})
        self.assertFalse(item['additionalProperties'])
        self.assertIn('warnings', listing['properties'])
        self.assertNotIn('warnings', listing['required'])

    def test_runtime_order_default_and_capture_candidates_remain_separate_from_saved_profiles(self):
        domino = self.config('.local/share/domino/data/config.json')
        runtime = self.config(self.root + '/clash-verge.yaml')
        first, second = self.saved(), self.saved('local.yaml')
        self.index([self.entry(), self.entry('local-1', 'local.yaml', 'Backup', 'local')])
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        with patch.object(tool, 'discover_proxy') as discover_proxy:
            result = tool.collect_sources()
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        self.assertEqual([r['config'] for r in result['sources']], list(map(str, [domino, runtime, first, second])))
        self.assertEqual([r['default'] for r in result['sources']], [True, False, False, False])
        for row in result['sources'][2:]:
            self.assert_unchecked(row)
            self.assertTrue(row['compatible_config_found'])
        self.assertIs(result['sources'][2]['client_current'], True)
        self.assertIs(result['sources'][3]['client_current'], False)
        self.assertEqual(tool.discover_sources(), [domino, runtime])
        self.assertEqual(tool.discover_source(), domino)
        self.assertEqual(tool.capture_candidates(), [runtime])
        self.probe.assert_called_once()
        discover_proxy.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_saved_only_is_not_default_or_automatic_capture_and_never_borrows_environment_proxy(self):
        path = self.saved()
        self.index([self.entry()])
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:PRIVATE-PROXY@127.0.0.1:7897'}), \
                patch.object(tool, 'discover_proxy', return_value='http://127.0.0.1:7897') as proxy:
            result = tool.collect_sources()
        row, = result['sources']
        self.assert_unchecked(row)
        self.assertEqual(row['config'], str(path))
        self.assertFalse(row['default'])
        self.assertIsNone(tool.discover_source())
        self.assertEqual(tool.capture_candidates(), [])
        self.probe.assert_not_called()
        proxy.assert_not_called()
        self.assertNotIn('warnings', result)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_explicit_profile_scan_never_uses_raw_port_or_environment_proxy(self):
        path = self.saved()
        self.index([self.entry()])
        output = io.StringIO()
        with patch.object(tool, 'discover_proxy', return_value='http://127.0.0.1:7897'), redirect_stdout(output):
            self.assertEqual(tool.main(['scan', '--source', str(path), '--json']), 3)
        result = json.loads(output.getvalue())
        assert_result_schema(self, result, OPERATIONS['source.inspect']['result'])
        self.assert_unchecked(result)
        self.assertEqual(result['profile_id'], 'remote-1')
        self.assertTrue(result['compatible_config_found'])
        self.probe.assert_not_called()
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_missing_and_malformed_profile_rows_retain_identity_and_generic_errors(self):
        missing = self.home / self.root / 'profiles/missing.yaml'
        broken = self.saved('broken.yaml')
        broken.write_bytes(b'\xffPRIVATE-PASSWORD https://private.example/?token=PRIVATE-TOKEN')
        self.index([self.entry(filename='missing.yaml'), self.entry('broken-1', 'broken.yaml', 'Broken', 'local')])
        result = tool.collect_sources()
        assert_result_schema(self, result, OPERATIONS['source.list']['result'])
        self.assertEqual([r['config'] for r in result['sources']], [str(missing), str(broken)])
        for row in result['sources']:
            self.assert_unchecked(row)
            self.assertFalse(row['compatible_config_found'])
            self.assertTrue(row['config_error'])
            self.assertTrue(row['profile_id'])
        for path in [missing, broken]:
            with patch.object(tool, 'discover_proxy', return_value='http://127.0.0.1:7897'):
                inspected = tool.collect_source(argparse.Namespace(source=str(path)))
            self.assert_unchecked(inspected)
            self.assertFalse(inspected['compatible_config_found'])
            self.assertTrue(inspected['config_error'])
            self.assertNotIn('PRIVATE', json.dumps(inspected))
        self.probe.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('https://private.example', json.dumps(result))

    def test_path_validation_rejects_traversal_absolute_backslash_and_escaping_symlinks(self):
        safe = self.saved()
        outside = self.config('outside.yaml')
        escaped = safe.parent / 'escaped.yaml'
        escaped.symlink_to(outside)
        cases = ['../outside.yaml', str(outside), r'..\outside.yaml', 'escaped.yaml', '.', '', 'bad\0.yaml']
        for filename in cases:
            with self.subTest(filename=repr(filename)):
                self.index([self.entry(), self.entry('unsafe', filename, 'PRIVATE-UNSAFE')])
                profiles, warnings = tool.read_verge_profiles()
                self.assertEqual(set(profiles), {safe.resolve()})
                self.assertTrue(warnings)
                self.assertNotIn('PRIVATE', json.dumps(warnings))
                self.assertNotIn(str(outside), json.dumps(warnings))
        self.probe.assert_not_called()

    def test_index_symlink_oversize_and_parse_failures_are_generic_and_do_not_hide_runtime(self):
        runtime = self.config('.config/mihomo/config.yaml')
        index = self.index([self.entry()])
        target = self.config('index-target.json', {'items': [self.entry()]})
        for mode in ['symlink', 'oversize', 'parse', 'yaml', 'shape']:
            with self.subTest(mode=mode):
                index.unlink()
                if mode == 'symlink':
                    index.symlink_to(target)
                elif mode == 'oversize':
                    index.write_text('PRIVATE-INDEX' + ' ' * (2 * 1024 * 1024))
                elif mode == 'parse':
                    index.write_bytes(b'\xffhttps://private.example/?token=PRIVATE-INDEX')
                elif mode == 'yaml':
                    index.write_text('items: [PRIVATE-INDEX\nurl: https://private.example')
                else:
                    index.write_text('{"items": "PRIVATE-INDEX"}')
                with patch.object(tool, 'load_yaml', wraps=tool.load_yaml) as load:
                    profiles, warnings = tool.read_verge_profiles()
                if mode in ['symlink', 'oversize']:
                    load.assert_not_called()
                self.assertEqual(profiles, {})
                self.assertTrue(warnings)
                result = tool.collect_sources()
                self.assertEqual([r['config'] for r in result['sources']], [str(runtime)])
                self.assertTrue(result['warnings'])
                assert_result_schema(self, result, OPERATIONS['source.list']['result'])
                self.assertNotIn('PRIVATE', json.dumps(result))
                self.assertNotIn('https://private.example', json.dumps(result))

    def test_symlinked_profile_directory_cannot_escape_client_root(self):
        outside = self.home / 'outside-profiles'
        outside.mkdir()
        index = self.index([self.entry()])
        (index.parent / 'profiles').symlink_to(outside, target_is_directory=True)
        with patch.object(tool, 'load_yaml') as load:
            profiles, warnings = tool.read_verge_profiles()
        self.assertEqual(profiles, {})
        self.assertTrue(warnings)
        load.assert_not_called()

    def test_duplicate_uid_or_path_is_ambiguous_and_resolved_paths_are_deduplicated(self):
        first, second = self.saved(), self.saved('second.yaml')
        alias = first.parent / 'alias.yaml'
        alias.symlink_to(first)
        self.index([self.entry(), self.entry('remote-1', 'second.yaml', 'Other'),
                    self.entry('alias-1', 'alias.yaml', 'Alias')])
        profiles, warnings = tool.read_verge_profiles()
        self.assertEqual(set(profiles), {first.resolve(), second.resolve()})
        self.assertTrue(warnings)
        self.assertTrue(all(item['client_current'] is None for item in profiles.values()))
        self.assertEqual(profiles[first]['profile_name'], 'Saved subscription')
        existing = self.home / '.config/clash/config.yaml'
        existing.parent.mkdir(parents=True)
        existing.symlink_to(first)
        result = tool.collect_sources()
        self.assertEqual([r['config'] for r in result['sources']], [str(existing), str(second)])
        self.assertTrue(result['sources'][0]['default'])
        for row in result['sources']:
            self.assert_unchecked(row)
            self.assertIsNone(row['client_current'])
        self.probe.assert_not_called()

    def test_missing_unknown_or_invalid_current_does_not_claim_profiles_are_noncurrent(self):
        path = self.saved()
        for current in [None, 'unknown-uid', 42]:
            with self.subTest(current=current):
                index = self.index([self.entry()], current=current)
                if current is None:
                    index.write_text(json.dumps({'items': [self.entry()]}))
                profiles, _ = tool.read_verge_profiles()
                self.assertIsNone(profiles[path]['client_current'])

    def test_human_scan_distinguishes_runtime_current_and_other_saved_rows(self):
        self.config(self.root + '/clash-verge.yaml')
        self.saved()
        self.saved('other.yaml')
        self.index([self.entry(), self.entry('other-1', 'other.yaml', 'Backup', 'local'), None])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(tool.main(['scan']), 0)
        text = output.getvalue()
        for expected in ['Saved subscription', 'Backup', '默认导入来源',
                         '客户端当前启用', '非当前', '未检查（保存配置）', '扫描提示']:
            self.assertIn(expected, text)
        self.assertNotIn('PRIVATE', text)
        self.probe.assert_called_once()

    def test_human_scan_merges_current_profile_and_runtime_but_json_stays_separate(self):
        runtime = self.config(self.root + '/clash-verge.yaml')
        current = self.saved()
        self.saved('other.yaml')
        self.index([self.entry(name='xlink'), self.entry('other-1', 'other.yaml', 'feiniao')])
        collected = tool.collect_sources()
        before = copy.deepcopy(collected)
        with patch.object(tool, 'collect_sources', return_value=collected):
            output = io.StringIO()
            with redirect_stdout(output):
                tool.main(['scan','--verbose'])
            text = output.getvalue()
            self.assertIn('外部配置 2 个 · Domino 管理 0 个', text)
            self.assertEqual(len(re.findall(r'(?m)^  来源 +',text)), 2)
            self.assertIn('Clash Verge · xlink', text)
            self.assertIn('Clash Verge · feiniao', text)
            self.assertNotIn('Clash Verge · 运行配置', text)
            self.assertIn('运行配置', text)
            self.assertIn('原始配置', text)
            self.assertIn('未关联运行入口', text)
            self.assertIn('出网结果属于运行入口', text)
            self.assertEqual(len(re.findall(r'(?m)^  入口出网 +可用$',text)), 1)
            json_output = io.StringIO()
            with redirect_stdout(json_output):
                tool.main(['scan', '--json'])
        self.assertEqual(json.loads(json_output.getvalue()), before)
        self.assertEqual(collected, before)
        self.assertEqual(len(collected['sources']), 3)
        self.assertTrue(collected['sources'][0]['default'])
        self.assertEqual(collected['sources'][0]['config'], str(runtime))
        self.assertEqual(collected['sources'][1]['config'], str(current))
        self.assert_unchecked(collected['sources'][1])

    def test_human_merge_falls_back_when_current_or_runtime_cannot_be_identified(self):
        runtime = self.config(self.root + '/clash-verge.yaml')
        current = self.saved()
        self.index([self.entry()])
        collected = tool.collect_sources()['sources']
        for case in ['unknown', 'missing_runtime', 'broken_profile', 'duplicate_current']:
            with self.subTest(case=case):
                rows = copy.deepcopy(collected)
                if case == 'unknown':
                    rows[1]['client_current'] = None
                elif case == 'missing_runtime':
                    rows.pop(0)
                elif case == 'broken_profile':
                    rows[1]['compatible_config_found'] = False
                else:
                    rows.append(dict(rows[1], config=str(current.with_name('duplicate.yaml'))))
                self.assertEqual(tool.source_display_groups(rows), rows)
        runtime.unlink()
        self.assertEqual(len(tool.collect_sources()['sources']), 1)

    def test_human_merge_preserves_runtime_failure_instead_of_profile_unchecked_status(self):
        self.config(self.root + '/clash-verge.yaml')
        self.saved()
        self.index([self.entry()])
        self.probe.side_effect = tool.ToolError('not available')
        output = io.StringIO()
        with redirect_stdout(output):
            tool.main(['scan'])
        text = output.getvalue()
        self.assertIn('外部配置 1 个 · Domino 管理 0 个', text)
        self.assertIn('检查未通过', text)
        self.assertNotIn('未检查（保存配置）', text)
        self.assertNotIn('原始配置', text)

    def test_invalid_items_are_skipped_without_hiding_valid_profile(self):
        path = self.saved()
        self.index([None, 'PRIVATE-ITEM', self.entry(uid=12), self.entry(name=None),
                    self.entry(kind='merge'), self.entry(kind='script'), self.entry()])
        profiles, warnings = tool.read_verge_profiles()
        self.assertEqual(set(profiles), {path.resolve()})
        self.assertTrue(warnings)
        self.assertNotIn('PRIVATE', json.dumps(warnings))

    def test_profile_import_uses_explicit_or_discovered_proxy_not_saved_port(self):
        path = self.saved()
        self.index([self.entry()])
        args = tool.build_parser().parse_args(['export', '--source', str(path), '--arch', 'arm64', '--output', str(self.home / 'unused.tar.gz')])
        with patch.object(tool, 'discover_proxy', return_value='http://127.0.0.1:18888') as proxy:
            self.assertEqual(tool.source_config(args)[2], 'http://127.0.0.1:18888')
            proxy.assert_called_once()
            proxy.reset_mock()
            args.local_proxy = 'http://127.0.0.1:19999'
            self.assertEqual(tool.source_config(args)[2], args.local_proxy)
            proxy.assert_not_called()
        ordinary = self.config('ordinary.json')
        args.source, args.local_proxy = str(ordinary), None
        with patch.object(tool, 'discover_proxy') as proxy:
            self.assertEqual(tool.source_config(args)[2], 'http://127.0.0.1:7897')
        proxy.assert_not_called()

    def test_profile_live_selections_ignore_raw_and_explicit_controllers(self):
        path = self.saved()
        self.index([self.entry()])
        raw = json.loads(path.read_text())
        raw['external-controller'] = '127.0.0.1:9090'
        raw['external-controller-unix'] = '/tmp/PRIVATE-SOCKET'
        raw['proxy-groups'] = [{'name': 'Choice', 'type': 'select', 'proxies': ['A', 'DIRECT']}]
        for flags in [[], ['--controller', '127.0.0.1:9091'], ['--controller-socket', '/tmp/PRIVATE-EXPLICIT']]:
            with self.subTest(flags=flags):
                args = tool.build_parser().parse_args(['export', '--source', str(path), '--arch', 'arm64', '--output', str(self.home / 'unused.tar.gz'), *flags])
                with patch.object(tool, 'run') as run, redirect_stderr(io.StringIO()):
                    self.assertEqual(tool.live_selections(args, raw, path), {})
                run.assert_not_called()
        ordinary = self.config('ordinary.json')
        args.source, args.controller, args.controller_socket = str(ordinary), None, None
        response = {'proxies': {'Choice': {'now': 'DIRECT', 'all': ['A', 'DIRECT']}}}
        with patch.object(tool, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(response))) as run:
            self.assertEqual(tool.live_selections(args, raw, ordinary), {'Choice': 'DIRECT'})
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
