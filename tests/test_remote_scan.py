"""Execute the real SSH payload against fixtures without a backend on disk."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import domino_cli as cli
from tests.remote_transport import local_command_argv


class RemoteScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.app = self.home / '.local/share/domino'

    def seed(self):
        data = self.app / 'data'
        data.mkdir(parents=True)
        profile = {'mode': 'rule', 'proxies': [{'name': 'Fixture node', 'type': 'ss',
            'server': 'fixture.example.test', 'port': 443, 'cipher': 'aes-128-gcm',
            'password': 'TEST-NODE-CREDENTIAL'}], 'rules': ['MATCH,DIRECT']}
        (data / 'config.json').write_text(json.dumps(profile))
        (data / 'subscription.json').write_text(json.dumps({'id': 'a' * 32}))
        registry = self.home / '.config/domino/subscriptions/index.json'
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({'schema': 1, 'items': [
            {'id': 'a' * 32, 'name': 'Fixture config', 'kind': 'snapshot'}]}))
        return data / 'config.json'

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob('*') if p.is_file()}

    def run_scan(self, *options, poison=False, expected_exit=0):
        args = cli.build_parser().parse_args(['fixture.example.test', 'scan', '--batch'])
        ssh = cli.SSH(args)
        prefix = ''
        if poison:
            runtime = self.app / 'cli'
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / 'install_domino.py').write_text('raise RuntimeError("STALE_BACKEND_ON_DISK")\n')
            prefix = 'import sys;sys.path.insert(0,' + repr(str(runtime)) + ')\n'
        else:
            prefix = ('import sys\n'
                      'class NoInstalledBackend:\n'
                      ' def find_spec(self, fullname, path=None, target=None):\n'
                      '  if fullname == "install_domino": raise ModuleNotFoundError("No backend on disk")\n'
                      'sys.meta_path.insert(0, NoInstalledBackend())\n')
        def command_argv(command, tty=False):
            return local_command_argv(command, tty, prefix=prefix)
        ssh.command_argv = command_argv
        argv = ssh.action_argv('scan', *options)
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME')
               and k.lower() not in ('http_proxy','https_proxy','all_proxy','no_proxy')
               and not k.startswith(('DOMINO_', '_DOMINO'))}
        # Also suppress macOS urllib's fallback to the real desktop proxy.
        env['no_proxy'] = '*'
        env['HOME'] = str(self.home)
        before = self.snapshot()
        result = subprocess.run(argv, cwd=self.home, env=env, text=True,
                                capture_output=True, timeout=15)
        diagnostic = '\n'.join(line for line in result.stderr.splitlines() if len(line) < 500)[-2400:]
        self.assertEqual(result.returncode, expected_exit, diagnostic)
        self.assertNotIn('TEST-NODE-CREDENTIAL', result.stdout)
        self.assertEqual(self.snapshot(), before)
        return result.stdout

    def test_human_scan_without_runtime_does_not_import_backend_from_disk(self):
        self.assertIn('Profile scan', self.run_scan())

    def test_json_scan_reads_target_configuration_using_embedded_backend(self):
        self.seed()
        result = json.loads(self.run_scan('--json'))
        self.assertEqual(result['sources'][0]['current_config'], 'Fixture config')
        self.assertEqual(result['managed_configs']['configs'][0]['name'], 'Fixture config')

    def test_human_scan_reads_target_configuration_without_disk_backend(self):
        self.seed()
        self.assertIn('Fixture config', self.run_scan())

    def test_explicit_source_scan_uses_same_embedded_backend(self):
        source = self.seed()
        result = json.loads(self.run_scan('--source', str(source), '--json', expected_exit=3))
        self.assertEqual(result['current_config'], 'Fixture config')
        self.assertFalse(result['healthy'])
        self.assertFalse(result['exit_checked'])

    def test_installed_older_backend_is_not_mixed_with_client_payload(self):
        self.seed()
        result = json.loads(self.run_scan('--json', poison=True))
        self.assertEqual(result['sources'][0]['current_config'], 'Fixture config')

    def test_remote_scan_discovers_linux_verge_without_domino_runtime(self):
        root = self.home / '.local/share/io.github.clash-verge-rev.clash-verge-rev'
        profiles = root / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'saved.yaml').write_text(json.dumps({'proxies': [
            {'name': 'Fixture node', 'type': 'socks5', 'server': 'fixture.example.test', 'port': 1080}]}))
        (root / 'profiles.yaml').write_text(json.dumps({'current': 'saved', 'items': [
            {'uid': 'saved', 'type': 'remote', 'name': 'Linux subscription', 'file': 'saved.yaml'}]}))
        result = json.loads(self.run_scan('--json'))
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['profile_name'], 'Linux subscription')
        self.assertTrue(result['sources'][0]['client_current'])
        self.assertIn('External profiles: 1 · Domino-managed: 0', self.run_scan())

    def test_remote_scan_transmits_v2rayn_database_adapter(self):
        import sqlite3
        root = self.home / '.local/share/v2rayN/guiConfigs'
        root.mkdir(parents=True)
        with sqlite3.connect(root / 'guiNDB.db') as database:
            database.execute('CREATE TABLE ProfileItem (IndexId TEXT, ConfigType INTEGER, Remarks TEXT, Address TEXT, Port INTEGER, Password TEXT)')
            database.execute('INSERT INTO ProfileItem VALUES (?,?,?,?,?,?)',
                ('a', 6, 'Fixture node', 'fixture.example.test', 443, 'TEST-NODE-CREDENTIAL'))
        result = json.loads(self.run_scan('--json'))
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['name'], 'v2rayN · Node snapshot')
        self.assertTrue(result['sources'][0]['compatible_config_found'])
        self.assertIsNone(result['sources'][0]['proxy'])
