"""Cross-platform client discovery using private-free, read-only fixtures."""
from contextlib import redirect_stdout
import argparse
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as cli
import domino_sources as sources


class ClientDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(Path, 'home', return_value=self.home).start()
        patch.dict(os.environ, {'XDG_DATA_HOME': '', 'XDG_CONFIG_HOME': ''}).start()
        self.probe = patch.object(cli, 'check_source_proxy',
                                  side_effect=AssertionError('unexpected endpoint probe')).start()
        self.raw = {'proxies': [{'name': 'Fixture node', 'type': 'socks5',
                                'server': 'fixture.example.test', 'port': 1080}],
                    'rules': ['MATCH,DIRECT']}

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def client(self, root, name='Fixture subscription'):
        profile = self.write(root / 'profiles/saved.yaml', self.raw)
        self.write(root / 'profiles.yaml', {'current': 'saved', 'items': [
            {'type': 'remote', 'uid': 'saved', 'file': 'saved.yaml', 'name': name},
            {'type': 'script', 'uid': 'script', 'file': 'script.js', 'name': 'ignored'}]})
        runtime = self.write(root / 'clash-verge.yaml', self.raw)
        return profile, runtime

    def snapshot(self):
        return {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()}

    def test_scan_and_catch_recognize_rev_on_both_platforms_and_legacy_verge(self):
        for root in cli.verge_roots():
            with self.subTest(root=root):
                profile, runtime = self.client(root)
                before = self.snapshot()
                result = cli.collect_sources()
                records = [r for r in result['sources'] if r['config'] in (str(profile), str(runtime))]
                self.assertEqual(len(records), 2)
                self.assertTrue(all(r['compatible_config_found'] for r in records))
                self.assertTrue(cli.source_identity(profile)['client_current'])
                grouped = cli.source_display_groups(records)
                self.assertEqual(len(grouped), 1)
                self.assertEqual(grouped[0]['display_profile']['config'], str(profile))
                self.assertIn(profile, cli.capture_candidates(include_saved=True))
                self.assertIn(runtime, cli.capture_candidates(include_saved=True))
                origin = sources.origin_info(self.raw, profile)
                self.assertEqual(origin['capture_kind'], 'verge-profile')
                runtime_origin = sources.origin_info(self.raw, runtime)
                self.assertEqual(runtime_origin['profile_name'], 'Fixture subscription')
                self.assertEqual(self.snapshot(), before)

    def test_linux_human_summary_counts_external_and_managed_separately(self):
        self.client(cli.verge_roots()[1])
        output = io.StringIO()
        with redirect_stdout(output):
            cli.list_sources(argparse.Namespace(json=False, columns=100))
        self.assertIn('外部配置 1 个 · Domino 管理 0 个', output.getvalue())
        self.assertIn('Fixture subscription', output.getvalue())

    def test_xdg_paths_and_yml_extension(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home / 'data'),
                                     'XDG_CONFIG_HOME': str(self.home / 'settings')}):
            root = self.home / 'data/io.github.clash-verge-rev.clash-verge-rev'
            profile, runtime = self.client(root)
            other = self.write(self.home / 'settings/mihomo/config.yml', self.raw)
            self.assertEqual(set(cli.discover_sources()), {runtime, other})
            self.assertIn(profile, cli.read_verge_profiles()[0])
            self.assertEqual(len(cli.source_display_groups(cli.collect_sources()['sources'])), 2)

    def test_relative_xdg_values_fall_back_to_home(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': 'relative', 'XDG_CONFIG_HOME': 'relative'}):
            self.assertEqual(cli.verge_roots()[1].parent, self.home / '.local/share')
            self.assertEqual(cli.verge_roots()[2], self.home / '.config/clash-verge')

    def test_bad_index_does_not_hide_other_client_and_resource_roots_stay_separate(self):
        first, second = cli.verge_roots()[:2]
        self.write(first / 'profiles.yaml', {'items': 'invalid'})
        profile, _ = self.client(second)
        profiles, warnings = cli.read_verge_profiles()
        self.assertIn(profile, profiles)
        self.assertTrue(warnings)
        database = second / 'Country.mmdb'
        database.write_bytes(b'fixture mmdb')
        resolver = sources.ResourceResolver(profile)
        self.assertEqual(resolver.find('Country.mmdb'), database)
        self.assertNotIn(first, resolver.roots)


if __name__ == '__main__':
    unittest.main()
