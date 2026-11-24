import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as tool
import domino_sources as sources
from domino_model import DomainError

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class SourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / 'client/config.json'
        self.input.parent.mkdir()
        self.raw = {'mode': 'global', 'mixed-port': 7897, 'secret': 'CONTROL-PRIVATE',
                    'proxies': [{'name': 'A', 'type': 'socks5', 'server': 'node.example', 'port': 1080}],
                    'proxy-groups': [{'name': '出口', 'type': 'select', 'proxies': ['A', 'DIRECT']}],
                    'rules': ['MATCH,出口'], 'tun': {'enable': True}}
        self.input.write_text(json.dumps(self.raw))
        self.source = self.root / 'data/source'
        self.addCleanup(patch.stopall)
        patch('domino_resources.resource_base', return_value=None).start()
        self.download = patch.object(tool, 'download', side_effect=AssertionError('unexpected network')).start()
        self.profiles = patch.object(tool, 'read_verge_profiles', return_value=({}, [])).start()

    def capture(self, **kwargs):
        return sources.create_source(self.raw, self.input, self.source, **kwargs)

    def test_pre_sanitize_capture_and_runtime_derivation_are_separate_private_and_immutable(self):
        before = copy.deepcopy(self.raw)
        self.capture()
        config, metadata = sources.read_source(self.source)
        self.assertEqual(self.raw, before)
        self.assertEqual(config, before)
        files_before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        runtime = sources.derive_runtime(self.source, self.root / 'runtime', {'出口': 'DIRECT'}, 17897, 19091)
        self.assertEqual(runtime['mixed-port'], 17897)
        self.assertFalse(runtime['tun']['enable'])
        self.assertEqual(runtime['proxy-groups'][0]['proxies'], ['DIRECT', 'A'])
        self.assertEqual(files_before, {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
        self.assertNotEqual(metadata['parsed_digest'], metadata['snapshot_digest'])
        for p in [self.source, *self.source.rglob('*')]:
            self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)
        self.profiles.assert_not_called()
        self.download.assert_not_called()

    def test_saved_verge_profile_reuses_shared_geo_without_changing_client_files(self):
        with patch.object(Path, 'home', return_value=self.root):
            client = self.root / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
            source = client / 'profiles/saved.json'
            source.parent.mkdir(parents=True)
            raw = dict(self.raw, rules=['GEOIP,CN,DIRECT', 'MATCH,出口'])
            source.write_text(json.dumps(raw))
            database = client / 'Country.mmdb'
            database.write_bytes(b'fixture shared mmdb')
            sources.create_source(raw, source, self.source, require_geo=True)
            self.assertEqual((self.source / 'Country.mmdb').read_bytes(), database.read_bytes())
            self.assertEqual(database.read_bytes(), b'fixture shared mmdb')
            _, metadata = sources.read_source(self.source)
            self.assertIn('Country.mmdb', metadata['files'])
            sources.derive_runtime(self.source, self.root / 'runtime', {}, 17897, 19091)
            self.assertEqual((self.root / 'runtime/Country.mmdb').read_bytes(), database.read_bytes())
        self.download.assert_not_called()

    def test_missing_geo_fails_before_core_with_specific_error_and_cleans_staging(self):
        raw = dict(self.raw, rules=['GEOIP,CN,DIRECT', 'MATCH,出口'])
        # An unrelated parent is deliberately not a recognized resource root.
        (self.input.parent.parent / 'Country.mmdb').write_bytes(b'unrelated')
        with self.assertRaises(DomainError) as caught:
            sources.create_source(raw, self.input, self.source, require_geo=True)
        self.assertEqual(caught.exception.code, 'GEO_RESOURCE_MISSING')
        self.assertIn('Country.mmdb', str(caught.exception))
        self.assertNotIn('CONTROL-PRIVATE', str(caught.exception))
        self.assertFalse(self.source.exists())
        self.download.assert_not_called()

    def test_geo_fallback_cannot_follow_symlinks_and_respects_geodata_mode(self):
        raw = dict(self.raw, rules=['GEOIP,CN,DIRECT', 'GEOSITE,cn,DIRECT'], **{'geodata-mode': True})
        fallback = self.root / 'installed'
        fallback.mkdir()
        outside = self.root / 'outside.dat'
        outside.write_bytes(b'outside')
        (fallback / 'geoip.dat').symlink_to(outside)
        (fallback / 'geosite.dat').write_bytes(b'fixture geosite')
        with self.assertRaises(DomainError) as caught:
            sources.create_source(raw, self.input, self.source, geo_dirs=(fallback,), require_geo=True)
        self.assertEqual(caught.exception.code, 'GEO_RESOURCE_MISSING')
        (fallback / 'geoip.dat').unlink()
        (fallback / 'geoip.dat').write_bytes(b'fixture geoip')
        sources.create_source(raw, self.input, self.source, geo_dirs=(fallback,), require_geo=True)
        self.assertEqual((self.source / 'geoip.dat').read_bytes(), b'fixture geoip')
        self.assertEqual((self.source / 'geosite.dat').read_bytes(), b'fixture geosite')

    def test_verge_shared_providers_geo_and_provider_relative_keys_survive_client_removal(self):
        with patch.object(Path, 'home', return_value=self.root):
            client = self.root / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
            source = client / 'profiles/saved.json'
            source.parent.mkdir(parents=True)
            (client / 'providers/tls').mkdir(parents=True)
            (client / 'providers/tls/key.pem').write_bytes(b'provider private key')
            (client / 'providers/nodes.json').write_text(json.dumps({'proxies': [
                dict(self.raw['proxies'][0], **{'private-key': 'tls/key.pem'})]}))
            (client / 'rules').mkdir()
            (client / 'rules/rules.yaml').write_text('payload:\n  - GEOIP,CN,DIRECT\n')
            (client / 'tls').mkdir()
            (client / 'tls/key.pem').write_bytes(b'profile certificate')
            (client / 'Country.mmdb').write_bytes(b'fixture country')
            raw = dict(self.raw, proxies=[dict(self.raw['proxies'][0], certificate='tls/key.pem')],
                       **{'proxy-providers': {'local': {'type': 'file', 'path': 'providers/nodes.json'}},
                          'rule-providers': {'local': {'type': 'file', 'path': 'rules/rules.yaml', 'behavior': 'classical'}}})
            source.write_text(json.dumps(raw))
            sources.create_source(raw, source, self.source, require_geo=True)
            shutil.rmtree(client)
            data = self.root / 'runtime'
            runtime = sources.derive_runtime(self.source, data, {}, 17897, 19091)
            self.assertEqual((data / runtime['proxies'][0]['certificate']).read_bytes(), b'profile certificate')
            provider = tool.load_yaml(data / runtime['proxy-providers']['local']['path'])
            self.assertEqual((data / provider['proxies'][0]['private-key']).read_bytes(), b'provider private key')
            self.assertTrue((data / runtime['rule-providers']['local']['path']).is_file())
            self.assertEqual((data / 'Country.mmdb').read_bytes(), b'fixture country')
            self.assertNotIn(str(client), json.dumps(runtime))
        self.download.assert_not_called()

    def test_custom_resource_directory_is_used_without_searching_unrelated_parents(self):
        resources = self.root / 'custom-resources'
        resources.mkdir()
        (resources / 'nodes.json').write_text(json.dumps({'proxies': self.raw['proxies']}))
        (resources / 'client.pem').write_bytes(b'fixture certificate')
        raw = dict(self.raw, proxies=[dict(self.raw['proxies'][0], certificate='client.pem')],
                   **{'proxy-providers': {'local': {'type': 'file', 'path': 'nodes.json'}}})
        with self.assertRaises(DomainError) as caught:
            sources.create_source(raw, self.input, self.source)
        self.assertEqual(caught.exception.code, 'SOURCE_RESOURCE_MISSING')
        self.assertIn('--resource-dir', str(caught.exception))
        sources.create_source(raw, self.input, self.source, resource_dirs=[resources])
        shutil.rmtree(resources)
        runtime = sources.derive_runtime(self.source, self.root / 'runtime', {}, 17897, 19091)
        self.assertEqual((self.root / 'runtime' / runtime['proxies'][0]['certificate']).read_bytes(), b'fixture certificate')
        self.download.assert_not_called()

    def test_config_directory_wins_over_shared_and_explicit_resource_roots(self):
        resources = self.root / 'resources'
        resources.mkdir()
        (resources / 'client.pem').write_bytes(b'wrong certificate')
        (self.input.parent / 'client.pem').write_bytes(b'correct certificate')
        raw = dict(self.raw, proxies=[dict(self.raw['proxies'][0], certificate='client.pem')])
        sources.create_source(raw, self.input, self.source, resource_dirs=[resources])
        profile, _ = sources.read_source(self.source)
        self.assertEqual((self.source / profile['proxies'][0]['certificate']).read_bytes(), b'correct certificate')

    def test_resource_symlink_is_rejected_without_falling_back_or_downloading(self):
        outside = self.root / 'private.pem'
        outside.write_bytes(b'PRIVATE CONTENT')
        (self.input.parent / 'nodes.json').symlink_to(outside)
        raw = dict(self.raw, **{'proxy-providers': {'remote': {
            'type': 'http', 'path': 'nodes.json', 'url': 'https://provider.test?PRIVATE'}}})
        with self.assertRaises(DomainError) as caught:
            sources.create_source(raw, self.input, self.source)
        self.assertEqual(caught.exception.code, 'INVALID_RESOURCE_PATH')
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertFalse(self.source.exists())
        self.download.assert_not_called()

    def test_offline_local_provider_can_use_explicit_resource_directory(self):
        resources = self.root / 'resources'
        resources.mkdir()
        (resources / 'nodes.json').write_text(json.dumps({'proxies': self.raw['proxies']}))
        raw = dict(self.raw, **{'proxy-providers': {'local': {'type': 'file', 'path': 'nodes.json'}}})
        sources.create_source(raw, self.input, self.source, resource_dirs=[resources], _offline=True)
        sources.read_source(self.source)
        self.download.assert_not_called()

    def test_file_identity_is_path_stable_while_parsed_digest_tracks_content_not_mapping_order(self):
        first = sources.origin_info(self.raw, self.input)
        changed = copy.deepcopy(self.raw)
        changed['proxies'].append({'name': 'B'})
        second = sources.origin_info(changed, self.input)
        reordered = sources.origin_info(dict(reversed(list(self.raw.items()))), self.input)
        self.assertEqual(first['identity'], second['identity'])
        self.assertNotEqual(first['parsed_digest'], second['parsed_digest'])
        self.assertEqual(first['parsed_digest'], reordered['parsed_digest'])
        other = sources.origin_info(self.raw, self.input.with_name('other.json'))
        self.assertNotEqual(first['identity'], other['identity'])

    def test_frozen_verge_index_association_and_unknown_runtime_identity(self):
        with patch.object(Path, 'home', return_value=self.root):
            verge = self.root / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
            runtime = verge / 'clash-verge.yaml'
            profile = verge / 'profiles/uid.yaml'
            index = {profile: {'profile_id': 'uid', 'profile_name': 'xlink', 'client_current': True}}
            self.profiles.return_value = index, []
            first = sources.origin_info(self.raw, runtime)
            self.assertEqual(first['association'], 'index')
            self.assertEqual(first['capture_kind'], 'verge-runtime')
            selected = sources.origin_info(self.raw, profile)
            self.assertEqual(selected['association'], 'selected-profile')
            self.assertNotEqual(selected['identity'], first['identity'])
            changed = dict(self.raw, rules=['MATCH,DIRECT'])
            self.assertEqual(first['identity'], sources.origin_info(changed, runtime)['identity'])
            self.profiles.return_value = {}, []
            unknown = sources.origin_info(self.raw, runtime)
            self.assertNotIn('profile_name', unknown)
            self.assertNotEqual(unknown['identity'], sources.origin_info(changed, runtime)['identity'])
            sources.create_source(self.raw, self.input, self.source, metadata=first)
            self.assertEqual(sources.read_source(self.source)[1]['profile_name'], 'xlink')

    def test_online_origin_and_public_projection_never_expose_private_url_or_configuration(self):
        info = sources.origin_info(self.raw, self.input, subscription='https://example.test/sub?TOKEN-PRIVATE')
        self.assertNotIn('original_path', info)
        self.assertNotIn('TOKEN-PRIVATE', json.dumps(info))
        self.capture(metadata=info, online=True)
        public = sources.public_info(self.source.parent)
        self.assertEqual(public['status'], 'known')
        text = json.dumps(public)
        for secret in ('TOKEN-PRIVATE', 'CONTROL-PRIVATE', 'node.example', 'files', 'original_path', 'identity'):
            self.assertNotIn(secret, text)
        self.assertEqual(public['label'], '在线订阅')

    def test_missing_unknown_and_corrupt_snapshots_are_distinct_and_read_only(self):
        self.assertEqual(sources.public_info(self.source.parent)['status'], 'unknown')
        with self.assertRaises(FileNotFoundError):
            sources.read_source(self.source)
        self.capture()
        path = self.source / 'config.json'
        path.write_text('{"PRIVATE":"TOKEN"}')
        before = path.read_bytes()
        self.assertEqual(sources.public_info(self.source.parent)['status'], 'invalid')
        with self.assertRaisesRegex(DomainError, '导入源快照无效'):
            sources.read_source(self.source)
        self.assertEqual(path.read_bytes(), before)

    def test_file_inline_and_provider_payload_certificates_survive_original_deletion(self):
        (self.input.parent / 'key.pem').write_bytes(b'PRIVATE-KEY')
        provider = self.input.parent / 'nodes.yaml'
        provider.write_text(json.dumps({'proxies': [dict(self.raw['proxies'][0], certificate='key.pem')]}))
        self.raw['proxies'][0]['private-key'] = str(self.input.parent / 'key.pem')
        self.raw['proxy-providers'] = {
            'file': {'type': 'file', 'path': str(provider)},
            'inline': {'type': 'inline', 'payload': [dict(self.raw['proxies'][0], certificate='key.pem')]}}
        self.capture()
        shutil.rmtree(self.input.parent)
        runtime = sources.derive_runtime(self.source, self.root / 'runtime', {}, 17897, 19091)
        for _, _, value in sources._walk_certs(runtime):
            self.assertTrue((self.root / 'runtime' / value).is_file())
        provider_path = self.root / 'runtime' / runtime['proxy-providers']['file']['path']
        payload = tool.load_yaml(provider_path)
        for _, _, value in sources._walk_certs(payload):
            self.assertEqual((self.root / 'runtime' / value).read_bytes(), b'PRIVATE-KEY')
        self.download.assert_not_called()

    def test_http_dependency_is_materialized_once_then_runtime_uses_owned_copy(self):
        self.raw['proxy-providers'] = {'remote': {'type': 'http', 'url': 'https://provider.test?PRIVATE', 'path': '/stale/cache'}}
        self.download.side_effect = lambda url, path, proxy=None, **kw: path.write_text(json.dumps({'proxies': self.raw['proxies']}))
        self.capture(online=True)
        self.assertEqual(self.download.call_count, 1)
        sources.derive_runtime(self.source, self.root / 'runtime', {}, 17897, 19091)
        sources.derive_runtime(self.source, self.root / 'runtime2', {}, 17897, 19091)
        self.assertEqual(self.download.call_count, 1)

    def test_online_external_file_and_cert_dependencies_are_rejected_privately(self):
        (self.input.parent / 'key.pem').write_text('PRIVATE-KEY')
        cases = [dict(self.raw, **{'proxy-providers': {'bad': {'type': 'file', 'path': 'key.pem'}}}),
                 dict(self.raw, proxies=[dict(self.raw['proxies'][0], certificate='key.pem')])]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(DomainError) as error:
                sources.create_source(raw, self.input, self.source, online=True)
            self.assertNotIn('PRIVATE', str(error.exception))
            self.assertFalse(self.source.exists())
        self.raw['proxy-providers'] = {'remote': {'type': 'http', 'url': 'https://provider.test'}}
        self.download.side_effect = lambda url, path, proxy=None, **kw: path.write_text(json.dumps({'proxies': [dict(self.raw['proxies'][0], certificate=str(self.input.parent / 'key.pem'))]}))
        with self.assertRaises(DomainError):
            self.capture(online=True)

    def test_missing_local_dependency_fails_without_deleting_existing_destination(self):
        self.raw['proxies'][0]['certificate'] = 'MISSING-PRIVATE.pem'
        with self.assertRaises(DomainError):
            self.capture()
        self.assertFalse(self.source.exists())
        self.source.mkdir(parents=True)
        (self.source / 'keep').write_text('keep')
        with self.assertRaises(DomainError):
            self.capture()
        self.assertEqual((self.source / 'keep').read_text(), 'keep')

    def test_symlink_and_tampered_containment_rejected_even_with_recomputed_digest(self):
        self.capture()
        (self.source / 'escape').symlink_to(self.input)
        with self.assertRaises(DomainError):
            sources.read_source(self.source)
        (self.source / 'escape').unlink()
        profile, metadata = sources.read_source(self.source)
        profile['proxies'][0]['certificate'] = str(self.input)
        (self.source / 'config.json').write_text(json.dumps(profile))
        metadata['files'] = sources._manifest(self.source)
        metadata['snapshot_digest'] = sources._digest(metadata['files'])
        (self.source / 'metadata.json').write_text(json.dumps(metadata))
        with self.assertRaises(DomainError):
            sources.read_source(self.source)

    def test_metadata_strict_schema_rejects_objects_invalid_labels_and_time(self):
        self.capture()
        path = self.source / 'metadata.json'
        original = json.loads(path.read_text())
        for key, value in [('profile_name', {'SECRET': 'PRIVATE'}), ('association', 'https://private.test'),
                           ('captured_at', 'https://private.test/TOKEN'), ('origin_label', 'https://private.test'),
                           ('unknown', 'PRIVATE'), ('profile_id', ['PRIVATE'])]:
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(original, **{key: value})))
                self.assertEqual(sources.public_info(self.source.parent)['status'], 'invalid')
        path.write_text(json.dumps(original))
        self.assertEqual(sources.public_info(self.source.parent)['status'], 'known')

    def test_nested_metadata_named_dependency_is_hashed(self):
        self.capture()
        nested = self.source / 'resources/metadata.json'
        nested.parent.mkdir()
        nested.write_text('one')
        path = self.source / 'metadata.json'
        metadata = json.loads(path.read_text())
        metadata['files'] = sources._manifest(self.source)
        metadata['snapshot_digest'] = sources._digest(metadata['files'])
        path.write_text(json.dumps(metadata))
        sources.read_source(self.source)
        nested.write_text('two')
        with self.assertRaises(DomainError):
            sources.read_source(self.source)

    def test_known_managed_snapshot_classification_does_not_need_valid_metadata(self):
        owned = self.root / '.local/share/domino/data/source/config.json'
        self.assertTrue(sources.is_managed_snapshot(owned))
        cached = self.root / '.config/domino/subscriptions/cache' / ('a' * 32) / 'source/config.json'
        self.assertTrue(sources.is_managed_snapshot(cached))
        self.assertFalse(sources.is_managed_snapshot(self.root / 'unrelated/source/config.json'))


if __name__ == '__main__':
    unittest.main()
