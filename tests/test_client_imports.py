"""Client conversion, WAL isolation, transport and real-core validation."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as cli
import domino_client_sources as clients
import domino_sources as sources
from domino_model import DomainError

UUID = '123e4567-e89b-12d3-a456-426614174000'
PASSWORD = 'FIXTURE-PRIVATE-PASSWORD'


class ClientImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(Path, 'home', return_value=self.home).start()
        patch.dict(os.environ, {'XDG_DATA_HOME': '', 'XDG_CONFIG_HOME': ''}).start()
        self.directory = self.home / '.local/share/v2rayN/guiConfigs'
        patch.object(clients, 'v2ray_directories', return_value=[self.directory]).start()
        self.probe = patch.object(cli, 'check_source_proxy', side_effect=AssertionError('unexpected probe')).start()
        self.download = patch.object(cli, 'download_resource', side_effect=AssertionError('unexpected download')).start()

    def row(self, kind=5, **extra):
        return dict(IndexId='a', ConfigType=kind, Remarks='Fixture', Address='fixture.example.test',
                    Port=443, Password=UUID if kind in (1, 5) else PASSWORD, **extra)

    def database(self, rows, wal=False):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'guiNDB.db'
        database = sqlite3.connect(path)
        self.addCleanup(database.close)
        if wal:
            database.execute('PRAGMA journal_mode=WAL')
            database.execute('PRAGMA wal_autocheckpoint=0')
        columns = list(dict.fromkeys(key for row in rows for key in row))
        declaration = ','.join('"' + name + '" ' + ('INTEGER' if name in ('ConfigType', 'Port', 'AlterId') else 'TEXT')
                               for name in columns)
        database.execute('CREATE TABLE ProfileItem (' + declaration + ')')
        for row in rows:
            database.execute('INSERT INTO ProfileItem VALUES (' + ','.join('?' for _ in columns) + ')',
                             [row.get(name) for name in columns])
        database.commit()
        return path

    def snapshot(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}

    def test_database_scan_catch_and_source_snapshot_never_change_client(self):
        path = self.database([self.row()], wal=True)
        before = self.snapshot(self.directory)
        result = cli.collect_sources()
        record = next(r for r in result['sources'] if r['config'] == str(path))
        self.assertTrue(record['compatible_config_found'])
        self.assertIsNone(record['proxy'])
        self.assertFalse(record['exit_checked'])
        self.assertEqual(record['name'], 'v2rayN · 节点快照')
        self.assertIn(path, cli.capture_candidates(include_saved=True))
        args = cli.build_parser().parse_args(['catch', '--source', str(path)])
        with patch.object(cli, 'discover_proxy', return_value=None):
            source, raw, proxy = cli.source_config(args)
        self.assertIsNone(proxy)
        sources.create_source(raw, source, self.home / 'snapshot')
        restored, metadata = sources.read_source(self.home / 'snapshot')
        self.assertEqual(restored['proxies'][0]['uuid'], UUID)
        self.assertIn('v2rayN', metadata['origin_label'])
        self.assertNotIn('guiNDB.db', metadata['files'])
        self.assertEqual(self.snapshot(self.directory), before)
        public = json.dumps(result)
        self.assertNotIn(UUID, public)
        self.assertNotIn(PASSWORD, public)

    def test_legacy_json_and_current_node_are_retained_without_client_routes(self):
        self.directory.mkdir(parents=True)
        path = self.directory / 'guiNConfig.json'
        rows = [self.row(), dict(self.row(), IndexId='b', Remarks='Active')]
        path.write_text(json.dumps({'indexId': 'b', 'vmess': rows, 'routing': {'private': PASSWORD}}))
        raw = clients.load(path)
        self.assertEqual(raw['proxy-groups'][0]['proxies'][0], raw['proxies'][1]['name'])
        self.assertEqual(raw['rules'], ['MATCH,v2rayN'])
        self.assertNotIn(PASSWORD, json.dumps(raw))
        self.assertIn(path, clients.discover())

    def test_database_is_preferred_over_modern_settings_and_selected_node_is_first(self):
        path = self.database([self.row(), dict(self.row(), IndexId='b', Remarks='Active')])
        (self.directory / 'guiNConfig.json').write_text(json.dumps({'indexId': 'b'}))
        self.assertEqual(clients.discover(), [path])
        raw = clients.load(path)
        self.assertTrue(raw['proxy-groups'][0]['proxies'][0].startswith('Active'))

    def test_backend_ui_catch_menu_names_the_actual_client(self):
        import install_domino as backend
        self.database([self.row()])
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(backend.main(['catch-options']))
        options = json.loads(output.getvalue())
        self.assertEqual(options[0]['name'], 'v2rayN · 节点快照')

    def test_supported_protocols_and_new_extra_fields_map_to_mihomo(self):
        rows = [self.row(kind) for kind in (1, 3, 4, 5, 6, 7, 8, 10, 11)]
        rows[1]['ProtoExtra'] = json.dumps({'SsMethod': 'aes-128-gcm'})
        rows[3].update(StreamSecurity='reality', PublicKey='yD0PzJG_Qh7MRAVWi5CVvKzg5VQMm_fvQMxW4MboX2s',
                       Sni='fixture.example.test', Fingerprint='chrome', ProtoExtra=json.dumps({'Flow': 'xtls-rprx-vision'}))
        rows[6]['Username'] = UUID
        converted = [clients._node(row, i) for i, row in enumerate(rows, 1)]
        self.assertEqual([row['type'] for row in converted],
                         ['vmess', 'ss', 'socks5', 'vless', 'trojan', 'hysteria2', 'tuic', 'http', 'anytls'])
        self.assertEqual(converted[3]['servername'], 'fixture.example.test')
        self.assertEqual(converted[3]['flow'], 'xtls-rprx-vision')
        self.assertEqual(converted[6]['uuid'], UUID)

    def test_ws_grpc_and_hysteria_obfuscation(self):
        ws = clients._node(self.row(Network='ws', StreamSecurity='tls',
            TransportExtra=json.dumps({'Host': 'fixture.example.test', 'Path': '/socket'})), 1)
        grpc = clients._node(self.row(Network='grpc', TransportExtra=json.dumps({'GrpcServiceName': 'service'})), 1)
        hy = clients._node(self.row(7, ProtoExtra=json.dumps({'SalamanderPass': PASSWORD, 'UpMbps': 100})), 1)
        self.assertEqual(ws['ws-opts'], {'path': '/socket', 'headers': {'Host': 'fixture.example.test'}})
        self.assertEqual(grpc['grpc-opts']['grpc-service-name'], 'service')
        self.assertEqual(hy['obfs-password'], PASSWORD)
        self.assertEqual(hy['up'], 100)

    def test_unsupported_rows_fail_the_whole_snapshot_without_leaking_credentials(self):
        path = self.database([self.row(), self.row(2)])
        record = cli.source_details(path)
        self.assertFalse(record['compatible_config_found'])
        self.assertIn('暂不支持', record['config_error'])
        self.assertNotIn(path, cli.capture_candidates(include_saved=True))
        with self.assertRaises(DomainError) as caught:
            clients.load(path)
        self.assertNotIn(PASSWORD, str(caught.exception))

    def test_unsupported_transports_extensions_and_invalid_database_have_safe_errors(self):
        for extra in ({'Network': 'xhttp'}, {'CertSha': PASSWORD},
                      {'ProtoExtra': json.dumps({'Hy2RealmUrl': PASSWORD})},
                      {'Network': 'ws', 'Path': '/?ed=2048'}):
            with self.subTest(extra=extra), self.assertRaises(DomainError) as caught:
                clients._node(self.row(**extra), 1)
            self.assertNotIn(PASSWORD, str(caught.exception))
        self.directory.mkdir(parents=True)
        path = self.directory / 'guiNDB.db'
        path.write_bytes(PASSWORD.encode())
        self.assertFalse(cli.source_details(path)['compatible_config_found'])
        self.assertNotIn(PASSWORD, cli.source_details(path)['config_error'])

    def test_clashx_lists_all_saved_yaml_and_marks_ports_as_unchecked(self):
        directory = self.home / '.config/clash'
        directory.mkdir(parents=True)
        raw = {'mixed-port': 7890, 'proxies': [clients._node(self.row(), 1)]}
        path = directory / 'Saved.yaml'
        path.write_text(json.dumps(raw))
        (directory / 'notes.txt').write_text('not a profile')
        (directory / 'escape.yaml').symlink_to(path)
        before = self.snapshot(directory)
        result = cli.collect_sources()
        self.assertEqual(len(result['sources']), 1)
        self.assertIn('ClashX', result['sources'][0]['name'])
        self.assertIsNone(result['sources'][0]['proxy'])
        self.assertFalse(result['sources'][0]['exit_checked'])
        self.assertIn(path, cli.capture_candidates(include_saved=True))
        output = io.StringIO()
        with redirect_stdout(output):
            cli.capture_choices([path])
        self.assertIn('ClashX', output.getvalue())
        self.assertEqual(self.snapshot(directory), before)

    def test_compact_ssh_source_keeps_license_ast_and_python39_syntax(self):
        import ast
        original = Path(clients.__file__).read_text()
        packed = cli.compact_remote_source(original)
        self.assertIn('SPDX-License-Identifier: GPL-3.0-only', packed)
        self.assertIn('Copyright', packed)
        self.assertEqual(ast.dump(ast.parse(packed), include_attributes=False),
                         ast.dump(ast.parse(cli.remote_source(original)), include_attributes=False))
        ast.parse(packed, feature_version=(3, 9))

    @unittest.skipUnless(os.environ.get('DOMINO_TEST_CORE'), 'set DOMINO_TEST_CORE for real-core validation')
    def test_converted_protocols_and_transports_pass_real_mihomo_validation(self):
        core = Path(os.environ['DOMINO_TEST_CORE']).resolve()
        rows = [self.row(kind) for kind in (1, 3, 4, 5, 6, 7, 8, 10, 11)]
        rows[1]['Security'] = 'aes-128-gcm'
        rows[3].update(StreamSecurity='reality', PublicKey='yD0PzJG_Qh7MRAVWi5CVvKzg5VQMm_fvQMxW4MboX2s',
                       Sni='fixture.example.test', ProtoExtra=json.dumps({'Flow': 'xtls-rprx-vision'}))
        rows[5]['ProtoExtra'] = json.dumps({'SalamanderPass': PASSWORD, 'UpMbps': 100, 'Ports': '443,8443'})
        rows[6]['Username'] = UUID
        rows.extend([self.row(Network='ws', StreamSecurity='tls', Sni='fixture.example.test'),
                     self.row(Network='grpc', Path='service')])
        path = self.database(rows)
        raw = clients.load(path)
        snapshot = self.home / 'source'
        sources.create_source(raw, path, snapshot)
        runtime = self.home / 'runtime'
        sources.derive_runtime(snapshot, runtime, {}, 17897, 19091)
        result = subprocess.run([str(core), '-t', '-d', str(runtime), '-f', str(runtime / 'config.json')],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, 'converted fixture configuration failed Mihomo validation')


if __name__ == '__main__':
    unittest.main()
