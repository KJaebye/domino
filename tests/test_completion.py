import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import domino_cli
import domino_completion as completion
import install_domino as installer


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.config/domino/subscriptions/index.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({'items': [{'name': 'xlink'}, {'name': '机场 配置'}]}))
        data = self.home / '.local/share/domino/data'
        data.mkdir(parents=True)
        self.node = "[HY2]美国 BGP002 O'Reilly $(touch SHOULD_NOT_EXIST)"
        (data / 'config.json').write_text(json.dumps({'proxies': [{'name': self.node}],
            'proxy-groups': [{'name': '节点选择'}]}))
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        cli = self.bin / 'domino'
        cli.write_text('#!' + sys.executable + '\nimport sys,json,os\nfrom pathlib import Path\n'
                       'sys.path.insert(0,' + repr(str(Path(domino_cli.__file__).parent)) + ')\n'
                       'Path(os.environ["RESULT"]+".calls").write_text(json.dumps(sys.argv[1:]))\n'
                       'if sys.argv[1:2]==["completion"]:\n'
                       ' from domino_completion import main\n raise SystemExit(main(sys.argv[2:]))\n'
                       'Path(os.environ["RESULT"]).write_text(json.dumps(sys.argv[1:]))\n')
        cli.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'ZDOTDIR': str(self.home),
                    'PATH': str(self.bin) + ':' + os.environ['PATH'], 'RESULT': str(self.home / 'result'),
                    'TERM': 'xterm-256color'}

    def query(self, *words):
        with patch.object(Path, 'home', return_value=self.home):
            return completion.candidates(words)

    def test_context_commands_options_and_choices(self):
        root = self.query('')[1]
        self.assertTrue({'select', 'test', 'list', 'shell', 'completion'} <= set(root))
        self.assertFalse({'configs', 'proxy', 'delay', 'log-level'} & set(root))
        self.assertEqual(self.query('shell', ''), ('values', ['off', 'on', 'status']))
        self.assertEqual(self.query('catch', 'a'), ('values', ['all']))
        self.assertEqual(self.query('mode', '--set', 'g'), ('values', ['global']))
        self.assertIn('--full', self.query('traffic', '--')[1])
        self.assertNotIn('--full', self.query('select', '--')[1])
        self.assertEqual(self.query('completion', ''), ('values', ['bash', 'zsh']))

    def test_local_names_are_read_only_and_never_connect(self):
        from scripts.package_home import snapshot
        before = snapshot(self.home)
        with patch.object(domino_cli, 'run', side_effect=AssertionError('Completion ran a process')):
            self.assertEqual(self.query('switch', 'x'), ('values', ['xlink']))
            self.assertEqual(self.query('select', '['), ('values', [self.node]))
            self.assertEqual(self.query('select', '--group', ''), ('values', ['节点选择']))
            self.assertIn('机场 配置', self.query('test', '--timeout', '1000', '')[1])
            self.assertEqual(self.query('user@example.test', 'select', ''), ('values', []))
            self.assertIn('status', self.query('my-ssh-host', '')[1])
        self.assertEqual(snapshot(self.home), before)

    def test_incomplete_or_malformed_files_do_not_break_tab(self):
        self.config.write_text('{')
        self.assertEqual(self.query('switch', ''), ('values', []))
        self.config.write_text(json.dumps({'items': [{'name': 'evil\nname'}, {'name': 'valid'}]}))
        self.assertEqual(self.query('switch', ''), ('values', ['valid']))
        self.assertEqual(self.query('catch', '--source', ''), ('files', []))

    def test_provider_names_come_only_from_existing_local_cache(self):
        data = self.home / '.local/share/domino/data'
        (data / 'provider.yaml').write_text('proxies:\n  - name: cached-node\n')
        (data / 'config.json').write_text(json.dumps({'proxy-providers': {
            'saved': {'path': 'provider.yaml', 'url': 'https://example.invalid/never-fetch'},
            'missing': {'path': 'missing.yaml'}, 'outside': {'path': '../../outside.yaml'}}}))
        self.assertEqual(self.query('select', 'cached'), ('values', ['cached-node']))

    def test_remote_source_preserves_executable_unicode_strings_and_future_imports(self):
        source = '''# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
"""Transport-only documentation."""
from __future__ import annotations
# A comment that is not needed on the wire.
def 中文():
    """文档字符。"""
    return "literal # comment and triple quotes: \\\"\\\"\\\""
def empty(): "empty docstring"
value = """data, not a docstring"""
'''
        compact = domino_cli.remote_source(source)
        self.assertEqual(source.count('\n'), compact.count('\n'))
        self.assertIn('SPDX-License-Identifier', compact)
        self.assertIn('Copyright', compact)
        self.assertNotIn('not needed on the wire', compact)
        original, reduced = {}, {}
        exec(source, original)
        exec(compact, reduced)
        self.assertEqual(original['中文'](), reduced['中文']())
        self.assertEqual(original['empty'](), reduced['empty']())
        self.assertEqual(original['value'], reduced['value'])

    def test_bundles_include_both_completion_scripts(self):
        bundle = self.home / 'bundle'
        bundle.mkdir()
        domino_cli.copy_cli(bundle)
        for shell in ['bash', 'zsh']:
            path = bundle / ('cli/completion.' + shell)
            self.assertEqual(path.read_text(), completion.SCRIPTS[shell])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(shutil.which('bash'), 'Bash is not installed')
    def test_bash_function_preserves_space_and_special_characters(self):
        script = self.home / 'completion.bash'
        script.write_text(completion.SCRIPTS['bash'])
        for words, expected in [(['select', '['], [self.node]), (['shell', 'o'], ['off', 'on']),
                                 (['switch', 'no-match'], [])]:
            code = 'source ' + shlex.quote(str(script)) + '\nCOMP_WORDS=(domino ' + shlex.join(words) + ')\n'
            code += f'COMP_CWORD={len(words)}\n_domino_complete\nprintf "%s\\n" "${{COMPREPLY[@]}}"\n'
            result = subprocess.run(['bash', '--noprofile', '--norc', '-c', code], env=self.env,
                                    capture_output=True, text=True, check=True, timeout=10)
            replies = [shlex.split(value)[0] for value in result.stdout.splitlines() if value]
            self.assertEqual(replies, expected)

    def test_install_only_edits_platform_default_rc_and_preserves_other_shell(self):
        for linux, selected, other in ((True, '.bashrc', '.zshrc'), (False, '.zshrc', '.bashrc')):
            with self.subTest(linux=linux), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                app = home / '.local/share/domino'
                installer.configure_shell_environment(app, home, linux=linux)
                self.assertIn('proxy.env', (home / selected).read_text())
                self.assertFalse((home / other).exists())
                vscode = home / '.vscode-server/server-env-setup'
                self.assertEqual(vscode.exists(), linux)
                # An upgrade must not edit a user's non-default shell settings,
                # including old Domino integration that they may still use.
                text = '# user shell settings\n' + installer.managed_block('', 'export KEEP=1')
                (home / other).write_text(text)
                (home / other).chmod(0o640)
                before = (home / selected).read_bytes()
                installer.configure_shell_environment(app, home, linux=linux)
                self.assertEqual((home / selected).read_bytes(), before)
                self.assertEqual((home / other).read_text(), text)
                self.assertEqual((home / other).stat().st_mode & 0o777, 0o640)

    def test_new_terminals_complete_switch_after_install_and_reinstall_without_manual_source(self):
        # Use the real installed loader and rc writer. Only the final command is
        # recorded by our fixture CLI, so pressing Enter cannot change a service.
        app = self.home / '.local/share/domino'
        domino_cli.copy_cli(app)
        local_bin = self.home / '.local/bin'
        local_bin.mkdir(parents=True)
        shutil.copy2(self.bin / 'domino', local_bin / 'domino')
        (self.home / '.bashrc').write_text('export DOMINO_STARTUP_KEEP=preserved\n')
        (self.home / '.zshrc').write_text('export DOMINO_STARTUP_KEEP=preserved\n'
                                          'autoload -Uz compinit; compinit -D -i\n')
        # Ubuntu's existing login profile loads .bashrc; preserve that contract.
        profile = self.home / '.profile'
        profile.write_text('[ -z "$BASH_VERSION" ] || . "$HOME/.bashrc"\n')
        original_profile = profile.read_bytes()
        for name in ('.bashrc', '.zshrc'):
            (self.home / name).chmod(0o640)
        cases = [('macOS-zsh', False, 'zsh', ['-i']),
                 ('macOS-login-zsh', False, 'zsh', ['-il']),
                 ('Ubuntu-bash', True, 'bash', ['-i']),
                 ('Ubuntu-login-bash', True, 'bash', ['--login', '-i'])]
        for label, linux, shell, flags in cases:
            if not shutil.which(shell):
                continue
            with self.subTest(startup=label):
                installer.configure_shell_environment(app, self.home, linux=linux)
                before = {name: (self.home / name).read_bytes() for name in ('.bashrc', '.zshrc')}
                installer.configure_shell_environment(app, self.home, linux=linux)
                self.assertEqual(before, {name: (self.home / name).read_bytes() for name in before})
                self.assertEqual(profile.read_bytes(), original_profile)
                for name in before:
                    self.assertEqual((self.home / name).stat().st_mode & 0o777, 0o640)
                for session in range(2):
                    with self.subTest(session=session):
                        result = self.home / 'result'
                        result.unlink(missing_ok=True)
                        master, slave = pty.openpty()
                        process = subprocess.Popen([shell, *flags], stdin=slave, stdout=slave, stderr=slave,
                            env={**self.env, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                                 'SHELL_SESSION_DID_INIT': '1'}, cwd=self.home, start_new_session=True)
                        os.close(slave)
                        try:
                            # No source, eval, compdef or manual completion setup here.
                            os.write(master, b'printf "\\nREADY:%s\\n" "$DOMINO_STARTUP_KEEP"\n')
                            output, deadline = b'', time.monotonic() + 12
                            while b'\r\nREADY:preserved\r\n' not in output and time.monotonic() < deadline:
                                if select.select([master], [], [], .1)[0]:
                                    output += os.read(master, 65536)
                            self.assertIn(b'\r\nREADY:preserved\r\n', output)
                            os.write(master, b'domino sw\t\n')
                            deadline = time.monotonic() + 12
                            while not result.exists() and time.monotonic() < deadline:
                                if select.select([master], [], [], .1)[0]:
                                    output += os.read(master, 65536)
                            self.assertTrue(result.exists(), output.decode(errors='replace'))
                            self.assertEqual(json.loads(result.read_text()), ['switch'])
                        finally:
                            process.kill()
                            process.wait(timeout=5)
                            os.close(master)

    def test_real_tab_quotes_node_names_in_bash_and_zsh(self):
        data = self.home / '.local/share/domino/data/config.json'
        data.write_text(json.dumps({'proxies': [{'name': self.node}]}))
        for shell, flags, autoload in [('bash', ['--noprofile', '--norc', '-i'], False),
                                       ('zsh', ['-dfi'], False), ('zsh', ['-dfi'], True)]:
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell, autoload=autoload):
                result = self.home / 'result'
                result.unlink(missing_ok=True)
                script = self.home / ('_domino' if autoload else 'completion.' + shell)
                script.write_text(completion.SCRIPTS[shell])
                master, slave = pty.openpty()
                process = subprocess.Popen([shell, *flags], stdin=slave, stdout=slave, stderr=slave,
                                           env=self.env, cwd=self.home, start_new_session=True)
                os.close(slave)
                try:
                    setup = 'source ' + shlex.quote(str(script))
                    if autoload:
                        setup = ('autoload -Uz compinit; compinit -D -i; fpath=(' + shlex.quote(str(self.home)) +
                                 ' $fpath); unfunction _domino 2>/dev/null; autoload -Uz _domino; compdef _domino domino')
                    os.write(master, (setup + '; printf "\\nREADY\\n"\n').encode())
                    output, deadline = b'', time.monotonic() + 10
                    while b'\r\nREADY\r\n' not in output and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            output += os.read(master, 65536)
                    self.assertIn(b'\r\nREADY\r\n', output)
                    os.write(master, b'domino select \t\n')
                    deadline = time.monotonic() + 10
                    while not result.exists() and time.monotonic() < deadline:
                        if select.select([master], [], [], .1)[0]:
                            output += os.read(master, 65536)
                    self.assertTrue(result.exists(), output.decode(errors='replace') + '\nCalls: ' +
                                    Path(str(result)+'.calls').read_text())
                    self.assertEqual(json.loads(result.read_text()), ['select', self.node])
                    self.assertFalse((self.home / 'SHOULD_NOT_EXIST').exists())
                finally:
                    process.kill()
                    process.wait(timeout=5)
                    os.close(master)
