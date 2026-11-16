from contextlib import ExitStack, redirect_stdout, redirect_stderr
import gzip
import hashlib
import io
import json
import os
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
        if 'domino_cli_sync.py' in command and self.fail:
            raise tool.ToolError('synthetic install failure')
        if 'cat ' in command and 'deployment-summary.json' in command:
            return SimpleNamespace(stdout=json.dumps({'schema': 1, 'verified': True,
                'cli_version': tool.VERSION, 'cli_before': '1.0.2', 'node_count': 32,
                'exit_country': 'JP', 'shell_enabled': False,
                'system_proxy_supported': True, 'system_proxy_enabled': True}))
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
        install_calls = [options for command, options in ssh.calls if 'domino_cli_sync.py' in command]
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

    def test_default_output_is_a_single_summary_and_verbose_is_forwarded(self):
        for verbose in [False, True]:
            self.args.verbose = verbose
            ssh, output = FakeSSH(), io.StringIO()
            with patch.object(tool, 'prepare', return_value=(self.package, self.manifest)), redirect_stdout(output):
                tool.deploy(self.args, ssh, {'home': '/home/alice', 'arch': 'aarch64'}, self.root)
            text = output.getvalue()
            self.assertEqual(text.count('部署完成'), 1)
            self.assertIn('JP · 32 个节点', text)
            self.assertIn('系统代理', text)
            self.assertIn('已接通', text)
            self.assertIn('1.0.2 → ' + tool.VERSION, text)
            self.assertNotIn('部署前备份', text)
            sync_command = next(command for command, _ in ssh.calls if 'domino_cli_sync.py' in command)
            self.assertEqual('--verbose' in sync_command, verbose)

    def test_missing_or_malformed_summary_never_reports_success(self):
        ssh, output = FakeSSH(), io.StringIO()
        original = ssh.call
        def call(command, **kwargs):
            if 'deployment-summary.json' in command:
                return SimpleNamespace(stdout='[]')
            return original(command, **kwargs)
        ssh.call = call
        with patch.object(tool, 'prepare', return_value=(self.package, self.manifest)), \
                redirect_stdout(output), self.assertRaises(tool.ToolError):
            tool.deploy(self.args, ssh, {'home': '/home/alice', 'arch': 'aarch64'}, self.root)
        self.assertNotIn('部署完成', output.getvalue())

    def test_ssh_deployment_suppresses_only_routine_connection_messages(self):
        args = tool.build_parser().parse_args(['alice@192.0.2.10'])
        self.assertIn('LogLevel=ERROR', tool.SSH(args).options)
        args.verbose = True
        self.assertNotIn('LogLevel=ERROR', tool.SSH(args).options)

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


class DeploymentSourceChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        self.stack.enter_context(patch.dict(os.environ, {
            'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_DATA_HOME': str(self.home / '.local/share'),
            'NO_COLOR': '1',
        }))
        self.stack.enter_context(patch.object(tool.sys.stdin, 'isatty', return_value=True))
        self.runtime = self.home / '.local/share/domino/data/config.json'
        verge = tool.verge_roots()[0]
        self.external = verge / 'clash-verge.yaml'
        self.saved = verge / 'profiles/saved.yaml'
        profile = {'proxies': [{'name': 'fixture', 'type': 'socks5',
                               'server': 'example.test', 'port': 1080, 'password': 'PRIVATE-NODE'}]}
        for path in [self.runtime, self.external, self.saved]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(profile))
        (verge / 'profiles.yaml').write_text(json.dumps({'current': 'saved', 'items': [
            {'uid': 'saved', 'name': '保存的测试配置', 'type': 'remote', 'file': 'saved.yaml',
             'url': 'https://example.test/subscription?token=PRIVATE-TOKEN'}]}))
        invalid = self.home / '.config/clash/config.yaml'
        invalid.parent.mkdir(parents=True)
        invalid.write_text('{}')
        self.ssh = self.stack.enter_context(patch.object(tool, 'SSH'))
        connected = self.ssh.return_value.__enter__.return_value
        connected.target = 'alice@192.0.2.10'
        connected.info.return_value = {'home': '/home/alice', 'arch': 'aarch64', 'system': 'Linux'}
        connected.call.side_effect = FakeSSH().call
        package = self.home / 'bundle.tar.gz'
        package.write_bytes(b'TEST-PACKAGE')
        self.prepare = self.stack.enter_context(patch.object(tool, 'prepare', return_value=(package, {'proxy_port': 7897})))
        self.cache = self.stack.enter_context(patch.object(tool, 'cache_dir', return_value=self.home))
        self.download = self.stack.enter_context(patch.object(tool, 'download_resource'))
        self.output, self.errors = io.StringIO(), io.StringIO()
        self.stack.enter_context(redirect_stdout(self.output))
        self.stack.enter_context(redirect_stderr(self.errors))

    def test_menu_includes_owned_runtime_and_saved_profiles_but_capture_stays_external(self):
        self.assertEqual(tool.source_candidates(include_saved=True, include_owned=True),
                         [self.runtime, self.external, self.saved])
        self.assertEqual(tool.capture_candidates(include_saved=True), [self.external, self.saved])

    def test_shorthand_and_explicit_deploy_select_before_ssh_and_packaging(self):
        for argv in [['alice@192.0.2.10'], ['alice@192.0.2.10', 'deploy']]:
            with self.subTest(argv=argv):
                self.ssh.reset_mock()
                self.prepare.reset_mock()
                def choose(prompt):
                    self.ssh.assert_not_called()
                    self.prepare.assert_not_called()
                    self.download.assert_not_called()
                    return '3'
                with patch('builtins.input', side_effect=choose):
                    self.assertEqual(tool.main(argv), 0)
                self.assertEqual(self.prepare.call_args.args[0].source, str(self.saved))
        menu = self.output.getvalue()
        for label in ['选择部署配置', 'Domino · 当前配置', 'Clash Verge · 运行配置', '保存的测试配置']:
            self.assertIn(label, menu)
        self.assertNotIn('PRIVATE-NODE', menu)
        self.assertNotIn('PRIVATE-TOKEN', menu)
        self.assertNotIn('全部配置', menu)

    def test_single_source_still_requires_a_choice(self):
        with patch.object(tool, 'source_candidates', return_value=[self.runtime]), \
                patch('builtins.input', return_value='1') as prompt:
            self.assertEqual(tool.main(['alice@192.0.2.10']), 0)
        prompt.assert_called_once()
        self.assertEqual(self.prepare.call_args.args[0].source, str(self.runtime))

    def test_default_menu_omits_paths_and_verbose_keeps_them(self):
        with patch('builtins.input', return_value='3'):
            self.assertEqual(tool.main(['alice@192.0.2.10']), 0)
        self.assertNotIn('配置文件', self.output.getvalue())
        self.assertNotIn('saved.yaml', self.output.getvalue())
        self.assertIn('当前保存项', self.output.getvalue())
        self.output.seek(0)
        self.output.truncate()
        with patch('builtins.input', return_value='3'):
            self.assertEqual(tool.main(['alice@192.0.2.10', '--verbose']), 0)
        self.assertIn('配置文件', self.output.getvalue())
        self.assertIn('saved.yaml', self.output.getvalue())

    def test_cancel_invalid_input_and_empty_sources_never_connect_or_download(self):
        for answer, expected in [('', 0), (EOFError(), 0), (KeyboardInterrupt(), 130),
                                 ('0', 1), ('4', 1), ('all', 1), ('invalid', 1)]:
            with self.subTest(answer=answer):
                options = {'side_effect': answer} if isinstance(answer, BaseException) else {'return_value': answer}
                with patch('builtins.input', **options):
                    self.assertEqual(tool.main(['alice@192.0.2.10']), expected)
        with patch.object(tool, 'source_candidates', return_value=[]), patch('builtins.input') as prompt:
            self.assertEqual(tool.main(['alice@192.0.2.10']), 1)
            prompt.assert_not_called()
        self.ssh.assert_not_called()
        self.prepare.assert_not_called()
        self.cache.assert_not_called()
        self.download.assert_not_called()

    def test_explicit_sources_and_noninteractive_invocations_bypass_the_menu(self):
        for flags in [['--source', str(self.saved)], ['--subscription', 'https://example.test/config']]:
            with self.subTest(flags=flags), patch('builtins.input') as prompt, \
                    patch.object(tool, 'source_candidates') as candidates:
                self.assertEqual(tool.main(['alice@192.0.2.10', *flags]), 0)
                prompt.assert_not_called()
                candidates.assert_not_called()
        with patch.object(tool.sys.stdin, 'isatty', return_value=False), \
                patch('builtins.input') as prompt:
            self.assertEqual(tool.main(['alice@192.0.2.10', '--batch']), 0)
            prompt.assert_not_called()

    def test_invalid_targets_are_rejected_before_source_discovery(self):
        with patch('builtins.input') as prompt, patch.object(tool, 'source_candidates') as candidates:
            self.assertEqual(tool.main(['alice@host;invalid']), 1)
            prompt.assert_not_called()
            candidates.assert_not_called()
        self.ssh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
