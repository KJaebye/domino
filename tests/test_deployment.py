from contextlib import redirect_stdout, redirect_stderr
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import domino_cli as tool


class FakeSSH:
    target = 'alice@192.0.2.10'
    def __init__(self, fail=False, bad_stage=False):
        self.calls = []
        self.actions = []
        self.fail = fail
        self.bad_stage = bad_stage
    def call(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command.startswith('umask'):
            return SimpleNamespace(stdout='/tmp/unrelated\n' if self.bad_stage else '/home/alice/.domino-deploy.ABCD1234\n')
        if ' install ' in command and self.fail:
            raise tool.ToolError('synthetic install failure')
        return SimpleNamespace(stdout='')
    def action(self, *args, **kwargs):
        self.actions.append((args, kwargs))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.args = tool.build_parser().parse_args(['deploy', 'alice@192.0.2.10', '--batch'])
        self.package = self.root / 'bundle.tar.gz'
        self.package.write_bytes(b'TEST-PACKAGE')
        self.manifest = {'proxy_port': 7897}
    def tearDown(self):
        self.temp.cleanup()

    def test_default_deploy_does_not_modify_vscode_or_restart_apps(self):
        ssh = FakeSSH()
        with patch.object(tool, 'prepare', return_value=(self.package, self.manifest)), \
                patch.object(tool, 'update_vscode') as vscode, redirect_stdout(io.StringIO()):
            tool.deploy(self.args, ssh, {'home': '/home/alice', 'arch': 'aarch64'}, self.root)
        vscode.assert_not_called()
        self.assertEqual(ssh.actions, [])
        self.assertTrue(any(c.startswith('rm -rf -- /home/alice/.domino-deploy.') for c, _ in ssh.calls))
        install_calls = [options for command, options in ssh.calls if ' install ' in command]
        self.assertFalse(install_calls[0]['tty'])

    def test_remote_failure_does_not_change_local_settings(self):
        self.args.vscode = True
        ssh = FakeSSH(fail=True)
        with patch.object(tool, 'prepare', return_value=(self.package, self.manifest)), \
                patch.object(tool, 'update_vscode') as vscode, self.assertRaises(tool.ToolError):
            tool.deploy(self.args, ssh, {'home': '/home/alice', 'arch': 'aarch64'}, self.root)
        vscode.assert_not_called()
        self.assertTrue(ssh.calls[-1][0].startswith('rm -rf --'))

    def test_invalid_staging_path_is_not_uploaded_to_or_deleted(self):
        ssh = FakeSSH(bad_stage=True)
        with patch.object(tool, 'prepare', return_value=(self.package, self.manifest)), self.assertRaises(tool.ToolError):
            tool.deploy(self.args, ssh, {'home': '/home/alice', 'arch': 'aarch64'}, self.root)
        self.assertEqual(len(ssh.calls), 1)

    def test_batch_deployment_can_run_without_a_terminal(self):
        info = {'home': '/home/alice', 'arch': 'aarch64'}
        with patch.object(tool.sys.stdin, 'isatty', return_value=False), \
                patch.object(tool, 'SSH') as ssh_cls, patch.object(tool, 'deploy') as deploy:
            ssh_cls.return_value.__enter__.return_value.info.return_value = info
            self.assertEqual(tool.main(['deploy', 'alice@host', '--batch']), 0)
            deploy.assert_called_once()

    def test_target_shorthand_checks_target_and_performs_deployment(self):
        info={'home':'/home/alice','arch':'aarch64','system':'Linux'}
        for target in ['alice@192.0.2.10','192.0.2.10','alice@[2001:db8::10]','alice@lab-alias']:
            with self.subTest(target=target), patch.object(tool,'SSH') as ssh, patch.object(tool,'deploy') as deploy:
                ssh.return_value.__enter__.return_value.info.return_value=info
                self.assertEqual(tool.main([target,'--batch']),0)
                self.assertEqual(ssh.call_args.args[0].target,target)
                ssh.return_value.__enter__.return_value.info.assert_called_once()
                deploy.assert_called_once()
                self.assertEqual(deploy.call_args.args[0].command,'deploy')

    def test_target_shorthand_keeps_deployment_options(self):
        args=tool.build_parser().parse_args(['alice@192.0.2.10','--batch','--source','/tmp/profile.json',
            '--proxy-port','17898','--api-port','19092'])
        self.assertEqual(args.command,'deploy')
        self.assertEqual(args.target,'alice@192.0.2.10')
        self.assertEqual(args.source,'/tmp/profile.json')
        self.assertEqual((args.proxy_port,args.api_port),(17898,19092))
        self.assertTrue(args.batch)

    def test_unknown_commands_and_invalid_targets_never_connect(self):
        with patch.object(tool,'SSH') as ssh, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                tool.main(['statu','--batch'])
            self.assertEqual(caught.exception.code,2)
            ssh.assert_not_called()
        with patch.object(tool.subprocess,'run') as run, redirect_stderr(io.StringIO()):
            for target in ['alice@host@evil','alice@host;touch']:
                self.assertEqual(tool.main([target,'--batch']),1)
            run.assert_not_called()

    def test_corrupt_release_binary_is_rejected_before_packaging(self):
        self.args = tool.build_parser().parse_args(['export', '--arch', 'arm64', '--output', str(self.root / 'out.tar.gz')])
        config = {'mixed-port': 7897, 'proxies': [{'name': 'test', 'type': 'socks5', 'server': 'example.test', 'port': 1080}]}
        profile = self.root / 'source.json'
        profile.write_text(json.dumps(config))
        release = {'tag_name': 'v1.2.3', 'assets': [{'name': 'mihomo-linux-arm64-v1.2.3.gz',
                   'digest': 'sha256:' + hashlib.sha256(b'GOOD').hexdigest(),
                   'browser_download_url': 'https://github.com/MetaCubeX/mihomo/releases/download/v1.2.3/mihomo-linux-arm64-v1.2.3.gz'}]}
        def download(url, path, proxy):
            path.write_text(json.dumps(release)) if 'api.github.com' in url else path.write_bytes(b'CORRUPT')
        cache = self.root / 'cache'
        cache.mkdir()
        work = self.root / 'work'
        work.mkdir()
        with patch.object(tool, 'source_config', return_value=(profile, config, None)), \
                patch.object(tool, 'live_selections', return_value={}), \
                patch.object(tool, 'cache_dir', return_value=cache), \
                patch.object(tool, 'download', side_effect=download), redirect_stdout(io.StringIO()):
            with self.assertRaises(tool.ToolError):
                tool.prepare(self.args, 'arm64', work)
        self.assertFalse((work / 'domino.tar.gz').exists())
        self.assertEqual(list(cache.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
