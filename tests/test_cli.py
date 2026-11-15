import argparse
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as tool


class TargetTests(unittest.TestCase):
    def test_config_management_uses_configs_without_the_old_command(self):
        parser=tool.build_parser()
        args=parser.parse_args(['configs'])
        self.assertEqual((args.command,args.configs_action),('configs','list'))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            parser.parse_args(['subs'])
        self.assertEqual(caught.exception.code,2)

    def test_addresses_and_ssh_alias(self):
        for value, expected in [('192.168.8.21', '192.168.8.21'),
                                ('nvidia@192.168.8.21', 'nvidia@192.168.8.21'),
                                ('dvt-1-unilever-poc', 'dvt-1-unilever-poc'),
                                ('nvidia@[2001:db8::10]', 'nvidia@2001:db8::10')]:
            self.assertEqual(tool.destination(value), expected)
        self.assertEqual(tool.destination('10.0.0.1', 'alice'), 'alice@10.0.0.1')

    def test_option_and_shell_injection_rejected(self):
        for bad in ['-oProxyCommand=x', 'x;touch /tmp/x', 'user@host@evil', 'host\nname',
                    '$(id)', 'user name@host', 'ssh://host', 'host:2222', '999.999.999.999']:
            with self.subTest(bad=bad), self.assertRaises(tool.ToolError):
                tool.destination(bad)
        with self.assertRaises(tool.ToolError):
            tool.destination('alice@host', 'bob')

    def test_architecture_and_port_validation(self):
        self.assertEqual(tool.normalize_arch('x86_64'), 'amd64')
        self.assertEqual(tool.normalize_arch('aarch64'), 'arm64')
        with self.assertRaises(tool.ToolError):
            tool.normalize_arch('armv7l')
        for value in ['22', '65536', '-1', 'abc']:
            with self.assertRaises(argparse.ArgumentTypeError):
                tool.port(value)

    def test_conflicting_options_fail_before_ssh(self):
        with patch.object(tool, 'SSH') as ssh, redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(['deploy', 'alice@host', '--proxy-port', '7897', '--api-port', '7897']), 1)
            self.assertEqual(tool.main(['deploy', 'alice@host', '--restart-vscode']), 1)
            self.assertEqual(tool.main(['deploy', 'alice@host', '--test-url', 'http://unsafe/']), 1)
            self.assertEqual(tool.main(['deploy', 'alice@host', '--mihomo-version', '../evil']), 1)
            ssh.assert_not_called()

    def test_errors_do_not_echo_commands_or_secrets(self):
        secret = 'TEST-NODE-CREDENTIAL'
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, ['curl', secret], stderr=secret)):
            with self.assertRaises(tool.ToolError) as caught:
                tool.run(['curl', secret])
        self.assertNotIn(secret, str(caught.exception))

    def test_download_credentials_use_stdin_not_process_args(self):
        url = 'https://example.test/subscription?token=TEST-PRIVATE-TOKEN'
        proxy = 'http://alice:TEST-PROXY-PASSWORD@127.0.0.1:7897'
        with patch.object(tool, 'run') as run:
            tool.download(url, Path('/tmp/output'), proxy)
        argv = run.call_args.args[0]
        self.assertNotIn(url, argv)
        self.assertNotIn(proxy, argv)
        self.assertIn(url, run.call_args.kwargs['input'])

    def test_subscription_user_agent_is_in_request_config_and_http_status_is_captured(self):
        with patch.object(tool,'run') as run:
            tool.download('https://example.test/sub?token=PRIVATE',Path('/tmp/profile'),'http://127.0.0.1:17897',
                          user_agent=tool.SUBSCRIPTION_USER_AGENT)
        self.assertIn('user-agent = "clash.meta"',run.call_args.kwargs['input'])
        self.assertIn('--write-out',run.call_args.args[0])
        self.assertNotIn('PRIVATE',str(run.call_args.args[0]))

    def test_download_reports_http_failure_without_echoing_private_url_or_stderr(self):
        secret='https://example.test/sub?token=PRIVATE'
        error=subprocess.CalledProcessError(56,['curl',secret],output='403',stderr=secret)
        with patch.object(tool.subprocess,'run',side_effect=error), self.assertRaises(tool.ToolError) as caught:
            tool.download(secret,Path('/tmp/profile'))
        self.assertIn('HTTP 403',str(caught.exception))
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_local_management_failure_is_reported_once_and_preserves_exit_code(self):
        def child(*args,**kwargs):
            print('失败：本地快照没有订阅地址。',file=tool.sys.stderr)
            raise subprocess.CalledProcessError(3,args[0])
        output=io.StringIO()
        with patch.object(tool.subprocess,'run',side_effect=child), redirect_stderr(output):
            self.assertEqual(tool.main(['configs','update','snapshot']),3)
        self.assertEqual(output.getvalue().count('失败：'),1)
        self.assertNotIn('本机管理失败',output.getvalue())

    def test_vscode_preserves_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            path.write_text(json.dumps({'editor.fontSize': 13, 'remote.SSH.httpProxy': {'other': 'http://other:1234'}}))
            tool.update_vscode('alice@host', 17890, path)
            result = json.loads(path.read_text())
            self.assertEqual(result['editor.fontSize'], 13)
            self.assertEqual(result['remote.SSH.httpProxy']['other'], 'http://other:1234')
            self.assertEqual(result['remote.SSH.httpProxy']['alice@host'], 'http://127.0.0.1:17890')
            self.assertTrue(list(path.parent.glob('settings.json.bak-*')))

    def test_vscode_jsonc_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            original = '{\n// comment\n"editor.fontSize": 13\n}'
            path.write_text(original)
            with self.assertRaises(tool.ToolError):
                tool.update_vscode('host', 7897, path)
            self.assertEqual(path.read_text(), original)

    def test_private_artifact_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bundle.tar.gz'
            tool.private_write(path, b'TEST-CREDENTIAL')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
