from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import domino_cli as tool

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class ManagementTests(unittest.TestCase):
    def test_shell_actions_and_default_status_route_only_to_requested_target(self):
        for action in [None, 'status', 'on', 'off']:
            for target in [None, 'localhost', 'alice@host']:
                argv = ['shell', *([action] if action else []), *([target] if target else []), '--json', '--batch']
                with self.subTest(argv=argv), patch.object(tool, 'run') as run, patch.object(tool, 'SSH') as ssh:
                    self.assertEqual(tool.main(argv), 0)
                    if target == 'alice@host':
                        forwarded = ssh.return_value.__enter__.return_value.action.call_args.args
                        run.assert_not_called()
                    else:
                        forwarded = run.call_args.args[0][2:]
                        ssh.assert_not_called()
                    self.assertEqual(forwarded[0], 'shell')
                    self.assertIn('--json', forwarded)
                    if action in ('on', 'off'):
                        self.assertEqual(forwarded[forwarded.index('--set') + 1], action)
                    else:
                        self.assertNotIn('--set', forwarded)

    def test_unknown_shell_actions_fail_before_ssh_or_backend(self):
        for action in ['stop', 'restart', 'of', 'host']:
            with self.subTest(action=action), patch.object(tool, 'run') as run, patch.object(tool, 'SSH') as ssh, redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as error:
                    tool.main(['shell', action])
                self.assertEqual(error.exception.code, 2)
                self.assertIn('domino shell off', output.getvalue())
                self.assertIn('domino HOST shell status', output.getvalue())
                run.assert_not_called()
                ssh.assert_not_called()
        for action in ['on', 'off', 'status']:
            args = tool.build_parser().parse_args(['shell', action, 'host'])
            self.assertEqual((args.shell_action, args.target), (action, 'host'))

    def test_proxy_verbs_route_to_existing_backend_for_local_and_remote_targets(self):
        for action in ['status','on','off']:
            for target in [None,'localhost','alice@host']:
                with self.subTest(action=action,target=target), patch.object(tool,'run') as run, patch.object(tool,'SSH') as ssh:
                    self.assertEqual(tool.main(['proxy',action,*([target] if target else []),'--json','--batch']),0)
                    if target=='alice@host':
                        call=ssh.return_value.__enter__.return_value.action.call_args
                        forwarded=call.args
                        self.assertFalse(call.kwargs['tty'])
                    else:
                        forwarded=run.call_args.args[0][2:]
                        ssh.assert_not_called()
                    self.assertEqual(forwarded[0],'proxy')
                    if action=='status':
                        self.assertNotIn('--set',forwarded)
                    else:
                        offset=forwarded.index('--set')
                        self.assertEqual(forwarded[offset+1],action)
                    self.assertIn('--json',forwarded)
        for arguments in [['proxy'],['proxy','localhost']]:
            with patch.object(tool,'run') as run:
                self.assertEqual(tool.main(arguments),0)
                self.assertNotIn('--set',run.call_args.args[0])

    def test_unknown_proxy_verbs_fail_before_opening_ssh_or_running_backend(self):
        for action in ['stop', 'start', 'restart', 'statsu', 'of', 'host']:
            with self.subTest(action=action), patch.object(tool, 'run') as run, \
                    patch.object(tool, 'SSH') as ssh, redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as error:
                    tool.main(['proxy', action])
                self.assertEqual(error.exception.code, 2)
                self.assertIn('未知系统代理动作：' + action, output.getvalue())
                self.assertIn('domino proxy off', output.getvalue())
                self.assertIn('domino HOST proxy status', output.getvalue())
                run.assert_not_called()
                ssh.assert_not_called()

    def test_proxy_default_status_keeps_unambiguous_targets_and_options(self):
        parser = tool.build_parser()
        for target in ['localhost', 'LOCALHOST', 'localhost.', '127.0.0.1', '::1', '[::1]',
                       '192.0.2.10', 'alice@host']:
            with self.subTest(target=target):
                args = parser.parse_args(['proxy', target, '--json'])
                self.assertEqual(args.proxy_action, 'status')
                self.assertEqual(args.target, target)
                self.assertTrue(args.json)
        args = parser.parse_args(['proxy', '--json'])
        self.assertEqual(args.proxy_action, 'status')
        self.assertTrue(args.json)
        for action in ['status', 'on', 'off']:
            for host in ['host', 'stop', 'server.example.com']:
                with self.subTest(action=action,host=host):
                    args = parser.parse_args(['proxy', action, host])
                    self.assertEqual(args.proxy_action, action)
                    self.assertEqual(args.target, host)

    def test_conflicting_proxy_verbs_fail_before_changing_settings(self):
        with patch.object(tool,'run') as run, patch.object(tool,'SSH') as ssh, redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(['proxy','on','--set','off']),1)
        run.assert_not_called()
        ssh.assert_not_called()

    def test_local_commands_do_not_open_ssh_or_read_source_configuration(self):
        for command in [['nodes', '--json'], ['select', '--group', '出口', '--node', 'Japan'],
                        ['start', '--batch'], ['stop', '--batch'], ['restart', '--batch'],
                        ['logs', '--batch', '--lines', '50', '--follow']]:
            with self.subTest(command=command), patch.object(tool, 'SSH') as ssh, \
                    patch.object(tool, 'run') as run, patch.object(tool, 'source_config') as source:
                self.assertEqual(tool.main(command), 0)
                self.assertEqual(run.call_args.args[0][:2], [tool.sys.executable, str(tool.REMOTE_SCRIPT)])
                self.assertEqual(run.call_args.args[0][2], command[0])
                ssh.assert_not_called()
                source.assert_not_called()

    def test_remote_management_passes_noninteractive_sudo_and_terminal_options(self):
        with patch.object(tool, 'SSH') as ssh, patch.object(tool, 'source_config') as source:
            self.assertEqual(tool.main(['restart', 'alice@192.0.2.10', '--batch']), 0)
            action = ssh.return_value.__enter__.return_value.action
            action.assert_called_with('restart', '--non-interactive', tty=False)
            self.assertEqual(tool.main(['logs', 'alice@192.0.2.10', '--lines', '20', '--follow']), 0)
            action.assert_called_with('logs', '--lines', '20', '--follow', tty=True)
            source.assert_not_called()

    def test_explicit_localhost_commands_never_use_ssh(self):
        commands = [['status', '--json'], ['nodes', '--json'],
                    ['select', '--group', '出口', '--node', 'Japan'],
                    ['start', '--batch'], ['stop', '--batch'], ['restart', '--batch'],
                    ['logs', '--batch', '--lines', '50', '--follow'],
                    ['rollback', '--batch', '--backup', '20261111-test']]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.local/share/domino/data/config.json'
            config.parent.mkdir(parents=True)
            config.write_text('{}')
            for command in commands:
                with self.subTest(command=command), patch.object(Path, 'home', return_value=home), \
                        patch.object(tool, 'SSH') as ssh, patch.object(tool, 'run') as run:
                    self.assertEqual(tool.main([command[0], 'localhost', *command[1:]]), 0)
                    argv = run.call_args.args[0]
                    self.assertEqual(argv[:3], [tool.sys.executable, str(tool.REMOTE_SCRIPT), command[0]])
                    self.assertNotIn('localhost', argv)
                    if command[0] == 'rollback':
                        self.assertEqual(argv[3:], ['--backup', '20261111-test', '--non-interactive'])
                    ssh.assert_not_called()

    def test_uninstalled_status_still_uses_domino_backend_not_other_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/clash/config.yaml'
            config.parent.mkdir(parents=True)
            config.write_text('mixed-port: 7897\n')
            for target in [[], ['localhost']]:
                with self.subTest(target=target), patch.object(Path, 'home', return_value=home), \
                        patch.object(tool, 'inspect_source') as inspect, patch.object(tool, 'SSH') as ssh, \
                        patch.object(tool, 'run') as run:
                    self.assertEqual(tool.main(['status', *target, '--json']), 0)
                self.assertEqual(run.call_args.args[0],
                                 [tool.sys.executable, str(tool.REMOTE_SCRIPT), 'status', '--json'])
                inspect.assert_not_called()
                ssh.assert_not_called()

    def test_local_aliases_and_explicit_ssh_user_are_distinguished(self):
        for target in [None, 'localhost', 'LOCALHOST', 'localhost.', '127.0.0.1', '::1', '[::1]']:
            self.assertTrue(tool.is_local_target(target), target)
        for target in ['nvidia@localhost', 'nvidia@127.0.0.1', '192.168.8.21', 'dvt-1-unilever-poc']:
            self.assertFalse(tool.is_local_target(target), target)
        with patch.object(tool, 'SSH') as ssh:
            self.assertEqual(tool.main(['status', 'nvidia@localhost', '--json']), 0)
            ssh.return_value.__enter__.return_value.action.assert_called_once_with('status', '--json')

    def test_localhost_rejects_ssh_options_without_silently_ignoring_them(self):
        for option in [['--user', 'other'], ['--identity', '/tmp/key'], ['--ssh-port', '2222']]:
            with self.subTest(option=option), patch.object(tool, 'SSH') as ssh, \
                    patch.object(tool, 'run') as run, redirect_stderr(io.StringIO()):
                self.assertEqual(tool.main(['nodes', 'localhost', *option]), 1)
                ssh.assert_not_called()
                run.assert_not_called()

    def test_remote_rollback_keeps_ssh_target_and_backup_options(self):
        with patch.object(tool, 'SSH') as ssh:
            self.assertEqual(tool.main(['rollback', 'nvidia@192.168.8.21', '--batch', '--backup', '20261111-test']), 0)
        ssh.return_value.__enter__.return_value.action.assert_called_once_with(
            'rollback', '--backup', '20261111-test', '--non-interactive', tty=False)

    def test_invalid_log_count_and_targetless_ssh_options_fail_before_ssh(self):
        with patch.object(tool, 'SSH') as ssh, redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(['logs', 'alice@host', '--lines', '0']), 1)
            self.assertEqual(tool.main(['logs', 'alice@host', '--lines', '10001']), 1)
            self.assertEqual(tool.main(['nodes', '--identity', '/tmp/key']), 1)
            ssh.assert_not_called()

    def test_source_separates_working_local_proxy_from_exportable_configuration(self):
        output = io.StringIO()
        with patch.object(tool, 'discover_source', return_value=None), \
                patch.object(tool, 'getproxies', return_value={'https': 'http://alice:PRIVATE@127.0.0.1:8888'}), \
                patch.object(tool, 'probe_source'), redirect_stdout(output):
            self.assertEqual(tool.inspect_source(tool.build_parser().parse_args(['scan', '--json'])), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result['healthy'])
        self.assertFalse(result['compatible_config_found'])
        self.assertEqual(result['proxy'], 'http://127.0.0.1:8888')
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_domino_source_is_discovered_before_other_client_configurations(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.local/share/domino/data/config.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'mixed-port': 7897, 'proxies': [
                {'name': 'Japan', 'type': 'socks5', 'server': 'node.example', 'port': 1080}]}))
            args = tool.build_parser().parse_args(['deploy', 'alice@next'])
            with patch.object(Path, 'home', return_value=home):
                source, raw, proxy = tool.source_config(args)
            self.assertEqual(source, config)
            self.assertEqual(proxy, 'http://127.0.0.1:7897')
            self.assertEqual(raw['proxies'][0]['server'], 'node.example')

    def test_local_proxy_endpoint_cannot_be_exported_as_independent_nodes(self):
        for server in ['127.0.0.1', '127.0.1.2', '::1', '0.0.0.0', 'localhost', 'LOCALHOST.', 'node.localhost']:
            with self.subTest(server=server), self.assertRaises(tool.ToolError):
                tool.sanitize_profile({'proxies': [{'type': 'http', 'server': server, 'port': 7897}]}, {}, 7897, 19090)

    def test_deployment_ssh_is_closed_and_never_creates_proxy_forwarding(self):
        args = tool.build_parser().parse_args(['deploy', 'alice@192.0.2.10', '--batch'])
        with patch.object(tool, 'run') as run, patch.object(tool.subprocess, 'run') as subprocess_run:
            with tool.SSH(args) as ssh:
                socket = Path(ssh.socket)
                directory = socket.parent
            command = run.call_args.args[0]
            self.assertIn('ClearAllForwardings=yes', command)
            self.assertFalse(any(flag in command for flag in ['-R', '-D', '-L']))
            self.assertIn('exit', subprocess_run.call_args.args[0])
            self.assertFalse(directory.exists())

    def test_copy_bundle_contains_cli_and_has_no_source_connection_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'source.json'
            config.write_text('{}')
            archive = root / 'cache/mihomo-linux-arm64-v1.2.3.gz'
            archive.parent.mkdir()
            import gzip
            import hashlib
            import tarfile
            archive.write_bytes(gzip.compress(b'FAKE-MIHOMO'))
            asset = {'name': archive.name, 'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}
            args = tool.build_parser().parse_args(['export', '--arch', 'arm64', '--output', str(root / 'out.tar.gz')])
            raw = {'proxies': [{'name': 'Japan', 'type': 'socks5', 'server': 'node.example', 'port': 1080}]}
            with patch.object(tool, 'source_config', return_value=(config, raw, None)), \
                    patch.object(tool, 'live_selections', return_value={}), \
                    patch.object(tool, 'cache_dir', return_value=archive.parent), \
                    patch.object(tool, 'release_asset', return_value=('v1.2.3', asset)), \
                    patch.object(tool, 'download', side_effect=lambda url, path, proxy: path.write_text('{}')), \
                    patch.object(tool, 'run'), redirect_stdout(io.StringIO()):
                package, manifest = tool.prepare(args, 'arm64', root)
            self.assertEqual(manifest['deployment_method'], 'independent')
            self.assertFalse(manifest['requires_source_online'])
            with tarfile.open(package) as bundle:
                self.assertIn('cli/domino_cli.py', bundle.getnames())
                self.assertIn('cli/install_domino.py', bundle.getnames())
                self.assertIn('cli/domino_shell.py', bundle.getnames())
                deployed = json.load(bundle.extractfile('data/config.json'))
            self.assertEqual(deployed['proxies'][0]['server'], 'node.example')


if __name__ == '__main__':
    unittest.main()
