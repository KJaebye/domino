"""Safe entry points: no real service, network or installation is used."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

import domino_cli as tool


class CatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        self.stack.enter_context(patch.object(tool.sys.stdin, 'isatty', return_value=True))
        self.out = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.err = self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.install = self.stack.enter_context(patch.object(tool, 'initialize'))
        self.ssh = self.stack.enter_context(patch.object(tool, 'SSH'))
        self.network = self.stack.enter_context(patch.object(tool, 'download_resource'))
        self.stack.enter_context(patch.object(tool, 'discover_proxy', return_value=None))
        self.stack.enter_context(patch.object(tool, 'discover_sources', return_value=[]))
        self.raw = {'mode': 'rule', 'proxies': [{'name': 'node', 'type': 'ss',
                    'server': 'example.test', 'port': 443, 'cipher': 'aes-128-gcm',
                    'password': 'TEST-PRIVATE-PASSWORD'}], 'rules': ['MATCH,node']}
        self.source = self.config('external/config.json')

    def config(self, relative, raw=None):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.raw if raw is None else raw))
        return path

    def run_catch(self, *extra):
        return tool.main(['catch', '--source', str(self.source), *extra])

    def test_bare_command_is_short_static_help(self):
        with patch.object(tool, 'build_parser') as parser, patch.object(tool, 'cache_dir') as cache, \
             patch.object(tool, 'collect_sources') as scan, patch.object(tool, 'discover_sources') as discover:
            self.assertEqual(tool.main([]), 0)
        text = self.out.getvalue()
        for command in ['catch', 'USER@IP', 'status', 'nodes', 'ui', '-h']:
            self.assertIn('domino ' + command, text)
        for command in ['connections', 'providers', 'rollback', 'traffic']:
            self.assertNotIn(command, text)
        for call in [parser, cache, scan, discover, self.install, self.network, self.ssh]:
            call.assert_not_called()

    def test_help_and_remote_shortcut(self):
        for args in [['-h'], ['catch', '-h'], ['--version']]:
            with self.subTest(args=args), self.assertRaises(SystemExit) as stopped:
                tool.main(args)
            self.assertEqual(stopped.exception.code, 0)
        self.assertIn('catch', tool.build_parser().format_help())
        parsed = tool.build_parser().parse_args(['alice@192.0.2.1'])
        self.assertEqual((parsed.command, parsed.target), ('deploy', 'alice@192.0.2.1'))
        for flag in ['--subscription', '--bundle']:
            with self.assertRaises(SystemExit):
                tool.build_parser().parse_args(['catch', flag, 'unused'])
        self.install.assert_not_called()

    def test_confirm_captures_once_and_keeps_original_command_for_read(self):
        raw = dict(self.raw, **{'proxy-groups': [{'name': 'Group', 'type': 'select', 'proxies': ['node']}]})
        self.source.write_text(json.dumps(raw))
        def selected(args, config, source):
            self.assertEqual(args.command, 'catch')
            return {'Group': 'node'}
        with patch.object(tool, 'live_selections', side_effect=selected) as live, \
             patch('builtins.input', return_value='yes'):
            self.assertEqual(self.run_catch(), 0)
        live.assert_called_once()
        prepared = self.install.call_args.args[0]
        self.assertEqual(prepared.command, 'init')
        self.assertIsNone(prepared.bundle)
        self.assertEqual(prepared._captured_source[0], self.source.resolve())
        self.assertEqual(prepared._captured_source[3], {'Group': 'node'})
        self.assertNotIn('TEST-PRIVATE-PASSWORD', self.out.getvalue() + self.err.getvalue())
        self.ssh.assert_not_called()
        self.network.assert_not_called()

    def test_refusal_eof_and_interrupt_never_install(self):
        for answer, expected in [('n', 0), ('', 0), (EOFError(), 0), (KeyboardInterrupt(), 130)]:
            with self.subTest(answer=answer):
                kwargs = {'side_effect': answer} if isinstance(answer, BaseException) else {'return_value': answer}
                with patch('builtins.input', **kwargs):
                    self.assertEqual(self.run_catch(), expected)
        self.install.assert_not_called()
        self.network.assert_not_called()
        self.ssh.assert_not_called()

    def test_noninteractive_requires_yes_and_batch_is_not_consent(self):
        with patch.object(tool.sys.stdin, 'isatty', return_value=False), patch.object(tool.sys, 'platform', 'darwin'), \
             patch('builtins.input') as prompt:
            self.assertEqual(self.run_catch(), 1)
            self.assertEqual(self.run_catch('--batch'), 1)
            self.install.assert_not_called()
            self.assertEqual(self.run_catch('--yes'), 0)
            prompt.assert_not_called()
        self.install.assert_called_once()

    def test_noninteractive_linux_requires_batch_for_auth(self):
        with patch.object(tool.sys.stdin, 'isatty', return_value=False), patch.object(tool.sys, 'platform', 'linux'):
            self.assertEqual(self.run_catch('--yes'), 1)
            self.install.assert_not_called()
            self.assertEqual(self.run_catch('--yes', '--batch'), 0)

    def test_auto_candidates_filter_owned_symlinks_duplicates_and_invalid_files(self):
        owned = self.config('.local/share/domino/data/config.json')
        legacy = self.config('.local/share/robot-clash/data/config.json')
        alias = self.home / 'alias.json'
        alias.symlink_to(owned)
        duplicate = self.home / 'external-alias.json'
        duplicate.symlink_to(self.source)
        invalid = self.config('invalid.json', {'mode': 'rule'})
        with patch.object(tool, 'discover_sources', return_value=[owned, legacy, alias, self.source, duplicate, invalid]), \
             patch.object(tool, 'check_source_proxy') as probe:
            self.assertEqual(tool.capture_candidates(), [self.source])
            self.assertEqual(tool.main(['catch', '--yes']), 0)
            probe.assert_not_called()
        self.install.assert_called_once()

    def test_no_external_source_fails_without_installing(self):
        self.assertEqual(tool.main(['catch', '--yes']), 1)
        self.assertIn('--source', self.err.getvalue())
        self.install.assert_not_called()

    def test_multiple_sources_require_selection_even_with_yes(self):
        second = self.config('other/config.json')
        with patch.object(tool, 'discover_sources', return_value=[self.source, second]), \
             patch('builtins.input', return_value='2') as prompt:
            self.assertEqual(tool.main(['catch', '--yes']), 0)
        prompt.assert_called_once()
        self.assertEqual(self.install.call_args.args[0]._captured_source[0], second.resolve())
        self.install.reset_mock()
        with patch.object(tool, 'discover_sources', return_value=[self.source, second]), \
             patch.object(tool.sys.stdin, 'isatty', return_value=False):
            self.assertEqual(tool.main(['catch', '--yes', '--batch']), 1)
        self.install.assert_not_called()

    def test_cancel_selection_or_invalid_selection_never_install(self):
        second = self.config('other/config.json')
        with patch.object(tool, 'discover_sources', return_value=[self.source, second]):
            for answer, code in [('', 0), ('3', 1), ('bad', 1), ('0', 1)]:
                with self.subTest(answer=answer), patch('builtins.input', return_value=answer):
                    self.assertEqual(tool.main(['catch']), code)
        self.install.assert_not_called()

    def test_explicit_invalid_or_owned_source_never_falls_back(self):
        owned = self.config('.local/share/domino/data/config.json')
        invalid = self.config('invalid.json', {'mode': 'rule'})
        with patch.object(tool, 'discover_sources', return_value=[self.source]) as discover:
            for source in [owned, invalid, self.home / 'missing.json']:
                with self.subTest(source=source):
                    self.assertEqual(tool.main(['catch', '--source', str(source), '--yes']), 1)
            discover.assert_not_called()
        self.install.assert_not_called()

    def test_malformed_explicit_source_has_a_safe_error_without_traceback(self):
        self.source.write_text(json.dumps({'proxies': ['TEST-PRIVATE-PASSWORD']}))
        self.assertEqual(self.run_catch('--yes'), 1)
        self.assertIn('数据结构无效', self.err.getvalue())
        self.assertNotIn('TEST-PRIVATE-PASSWORD', self.err.getvalue())
        self.install.assert_not_called()

    def test_preflight_validation_prevents_capture(self):
        with patch.object(tool, 'live_selections') as live:
            for options in [('--proxy-port', '19091'), ('--test-url', 'http://unsafe.test'),
                            ('--mihomo-version', '../unsafe')]:
                self.assertEqual(self.run_catch('--yes', *options), 1)
            live.assert_not_called()
        self.install.assert_not_called()

    def test_live_selection_failure_stops_and_missing_interface_is_explicit(self):
        with patch.object(tool, 'live_selections', side_effect=tool.ToolError('源接口不可用')):
            self.assertEqual(self.run_catch('--yes'), 1)
        self.install.assert_not_called()
        self.assertEqual(self.run_catch('--yes'), 0)
        self.assertIn('默认节点', self.err.getvalue())

    def test_catch_reads_live_selection_while_legacy_init_does_not(self):
        raw = copy.deepcopy(self.raw)
        raw.update({'external-controller': '127.0.0.1:9090', 'secret': 'TEST-PRIVATE-SECRET',
                    'mixed-port': 7897, 'proxy-groups': [{'name': 'Group', 'type': 'select', 'proxies': ['node']}]})
        self.source.write_text(json.dumps(raw))
        args = tool.build_parser().parse_args(['catch', '--source', str(self.source), '--yes'])
        response = type('Response', (), {'stdout': json.dumps({'proxies': {'Group': {'now': 'node', 'all': ['node']}}})})()
        with patch.object(tool, 'run', return_value=response) as run:
            _, config, proxy = tool.source_config(args)
            self.assertEqual(proxy, 'http://127.0.0.1:7897')
            self.assertEqual(tool.live_selections(args, config, self.source), {'Group': 'node'})
            self.assertNotIn('TEST-PRIVATE-SECRET', str(run.call_args.args))
            args.command = 'init'
            run.reset_mock()
            self.assertEqual(tool.live_selections(args, config, self.source), {})
            self.assertIsNone(tool.source_config(args)[2])
            run.assert_not_called()

    def test_prepare_consumes_confirmed_snapshot_without_rereading(self):
        args = tool.build_parser().parse_args(['catch', '--source', str(self.source), '--yes'])
        args.command = 'init'
        args._captured_source = (self.source, copy.deepcopy(self.raw), None, {})
        sentinel = RuntimeError('stop before resource work')
        with patch.object(tool, 'source_config') as source, patch.object(tool, 'live_selections') as live, \
             patch.object(tool, 'sanitize_profile', wraps=tool.sanitize_profile) as sanitize, \
             patch.object(tool, 'cache_dir', side_effect=sentinel):
            with self.assertRaisesRegex(RuntimeError, 'stop before resource work'):
                tool.prepare_source(args, 'arm64', self.home)
        source.assert_not_called()
        live.assert_not_called()
        self.assertEqual(sanitize.call_args.args[0], self.raw)

    def test_confirmed_snapshot_is_packed_with_choices_even_if_source_changes(self):
        captured = copy.deepcopy(self.raw)
        captured['proxies'].append(dict(captured['proxies'][0], name='other'))
        captured['proxy-groups'] = [{'name': 'Group', 'type': 'select', 'proxies': ['other', 'node']}]
        args = tool.build_parser().parse_args(['catch', '--source', str(self.source), '--yes'])
        args.command = 'init'
        args.target_system = 'darwin'
        args._captured_source = (self.source, captured, None, {'Group': 'node'})
        self.source.write_text('{}')
        cache = self.home / 'cache'
        cache.mkdir()
        binary = b'TEST-ONLY-NOT-EXECUTABLE'
        archive = cache / 'mihomo-darwin-arm64-v1.2.3.gz'
        archive.write_bytes(gzip.compress(binary))
        asset = {'name': archive.name, 'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}
        with patch.object(tool, 'cache_dir', return_value=cache), \
             patch.object(tool, 'cached_init_release', return_value=('v1.2.3', asset)), \
             patch.object(tool, 'copy_cli'), patch.object(tool, 'run'), \
             patch.object(tool, 'source_config') as source, patch.object(tool, 'live_selections') as live:
            package, manifest = tool.prepare(args, 'arm64', self.home)
        with tarfile.open(package) as bundle:
            profile = json.load(bundle.extractfile('data/config.json'))
            choices = json.load(bundle.extractfile('selections.json'))
            source_snapshot = json.load(bundle.extractfile('data/source/config.json'))
            source_metadata = json.load(bundle.extractfile('data/source/metadata.json'))
            registration = json.load(bundle.extractfile('registration.json'))
            self.assertEqual(bundle.extractfile('mihomo').read(), binary)
        self.assertEqual(source_snapshot, captured)
        self.assertEqual(source_snapshot['proxy-groups'][0]['proxies'], ['other', 'node'])
        self.assertEqual(source_metadata['capture_kind'], 'file')
        self.assertEqual(registration, {'version': 1, 'kind': 'snapshot'})
        self.assertEqual(choices, {'Group': 'node'})
        self.assertEqual(profile['proxy-groups'][0]['proxies'], ['node', 'other'])
        self.assertEqual(len(profile['proxies']), 2)
        self.assertFalse(profile['tun']['enable'])
        self.assertFalse(manifest['requires_source_online'])
        self.assertEqual(profile['external-controller'], '127.0.0.1:19091')
        self.assertEqual(package.stat().st_mode & 0o777, 0o600)
        source.assert_not_called()
        live.assert_not_called()
        self.network.assert_not_called()

    def test_machine_mode_rejects_catch_without_interaction(self):
        with patch('builtins.input') as prompt:
            self.assertEqual(tool.main(['--output', 'json', 'catch', '--yes']), 3)
        reply = json.loads(self.out.getvalue())
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['error']['code'], 'UNSUPPORTED_OPERATION')
        prompt.assert_not_called()
        self.install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
