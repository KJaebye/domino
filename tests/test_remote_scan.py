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

    def run_scan(self, *options, poison=False):
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
            tokens = shlex.split(command)
            return [sys.executable, '-I', '-c', prefix + tokens[2], *tokens[3:]]
        ssh.command_argv = command_argv
        argv = ssh.action_argv('scan', *options)
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')
               and not k.startswith(('DOMINO_', '_DOMINO'))}
        env['HOME'] = str(self.home)
        before = self.snapshot()
        result = subprocess.run(argv, cwd=self.home, env=env, text=True,
                                capture_output=True, timeout=15)
        diagnostic = '\n'.join(line for line in result.stderr.splitlines() if len(line) < 500)[-2400:]
        self.assertEqual(result.returncode, 0, diagnostic)
        self.assertNotIn('TEST-NODE-CREDENTIAL', result.stdout)
        self.assertEqual(self.snapshot(), before)
        return result.stdout

    def test_human_scan_without_runtime_does_not_import_backend_from_disk(self):
        self.assertIn('配置扫描', self.run_scan())

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
        result = json.loads(self.run_scan('--source', str(source), '--json'))
        self.assertEqual(result['current_config'], 'Fixture config')

    def test_installed_older_backend_is_not_mixed_with_client_payload(self):
        self.seed()
        result = json.loads(self.run_scan('--json', poison=True))
        self.assertEqual(result['sources'][0]['current_config'], 'Fixture config')

