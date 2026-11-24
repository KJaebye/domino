"""Real parent-shell tests; no user rc files, network, or installed state."""
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import domino_shell as shell
import install_domino as control

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class ShellPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / 'app'
        self.app.mkdir()

    def test_policy_missing_and_strict_validation(self):
        self.assertEqual(shell.read_policy(self.app), {'version': 1, 'enabled': False})
        path = self.app / 'shell-policy.json'
        for value in ('{', '[]', '{"version":true,"enabled":true}',
                      '{"version":1,"enabled":1}', '{"version":2,"enabled":false}',
                      '{"version":1,"enabled":false,"extra":1}'):
            path.write_text(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                shell.read_policy(self.app)
        path.write_text('{"version":1,"enabled":true}')
        self.assertTrue(shell.read_policy(self.app)['enabled'])

    def test_policy_status_does_not_claim_parent_application(self):
        before = set(self.app.iterdir())
        result = shell.status(self.app, self.app)
        self.assertTrue(result['policy_only'])
        self.assertFalse(result['current_shell_applied'])
        self.assertFalse(result['integration_available'])
        self.assertEqual(set(self.app.iterdir()), before)

    def test_integration_available_requires_loader_marker_and_installed_helper(self):
        loader = self.app / '.config/domino/proxy.env'
        loader.parent.mkdir(parents=True)
        loader.write_text('export http_proxy=http://manual:7897\n')
        self.assertFalse(shell.status(self.app, self.app)['integration_available'])
        loader.write_text(shell.integration(self.app, sys.executable))
        self.assertFalse(shell.status(self.app, self.app)['integration_available'])
        helper = self.app / 'cli/domino_shell.py'
        helper.parent.mkdir()
        helper.touch()
        self.assertTrue(shell.status(self.app, self.app)['integration_available'])

    def test_human_status_distinguishes_policy_from_current_environment_and_uses_red_off_color(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                (self.app / 'shell-policy.json').write_text(json.dumps({'version': 1, 'enabled': enabled}))
                before = (self.app / 'shell-policy.json').read_bytes()
                (self.app / 'data').mkdir(exist_ok=True)
                (self.app / 'data/config.json').write_text('{"mixed-port":19876}')
                output = io.StringIO()
                with patch.object(control, 'current_installation', return_value=(self.app, None)), \
                        patch.object(control, 'HOME', self.app), redirect_stdout(output), \
                        patch.object(output, 'isatty', return_value=True), \
                        patch.dict(os.environ, {'TERM': 'xterm-256color'}):
                    with patch.dict(os.environ):
                        os.environ.pop('NO_COLOR', None)
                        control.shell_proxy(verbose=True)
                text = output.getvalue()
                if enabled:
                    self.assertIn('\033[32m● 策略已开启\033[0m', text)
                    self.assertIn('使用 Domino 代理', text)
                else:
                    self.assertIn('\033[31m● 策略已关闭\033[0m', text)
                    self.assertNotIn('\033[32m', text)
                    self.assertIn('恢复原代理设置', text)
                    self.assertIn('保留手动修改', text)
                self.assertIn('已接入终端返回命令行后同步', text)
                self.assertIn('终端（Terminal）', text)
                self.assertIn('http://127.0.0.1:19876', text)
                self.assertIn('socks5h://127.0.0.1:19876', text)
                self.assertIn('http_proxy / HTTP_PROXY', text)
                self.assertIn('https_proxy / HTTPS_PROXY', text)
                self.assertIn('all_proxy / ALL_PROXY', text)
                self.assertIn('no_proxy / NO_PROXY', text)
                self.assertIn('本次命令继承的已导出变量', text)
                self.assertNotIn('env | grep', text)
                self.assertEqual((self.app / 'shell-policy.json').read_bytes(), before)

    def test_status_shows_inherited_exports_without_credentials_or_policy_writes(self):
        variables = {'http_proxy': 'http://user:PRIVATE@127.0.0.1:7897/path?token=SECRET',
                     'HTTPS_PROXY': 'http://[::1]:19876', 'all_proxy': 'not-a-url-PRIVATE',
                     'NO_PROXY': 'localhost,.example.org'}
        output = io.StringIO()
        with patch.object(control, 'current_installation', return_value=(self.app, None)), \
                patch.object(control, 'HOME', self.app), \
                patch.dict(os.environ, variables), redirect_stdout(output):
            control.shell_proxy(verbose=True)
        text = output.getvalue()
        self.assertIn('http://127.0.0.1:7897', text)
        self.assertIn('http://[::1]:19876', text)
        self.assertIn('localhost,.example.org', text)
        for secret in ['PRIVATE', 'SECRET', 'user:', '/path', 'token=']:
            self.assertNotIn(secret, text)
        self.assertFalse((self.app / 'shell-policy.json').exists())

    def test_environment_value_display_masks_invalid_urls_and_terminal_controls(self):
        for value in ['http://user:PRIVATE@host:bad', 'http://host:123456',
                      'http://host\x1b[31m:7897', 'PRIVATE', 'http://[broken']:
            with self.subTest(value=value):
                displayed = shell.display_value('http_proxy', value)
                self.assertNotIn('PRIVATE', displayed)
                self.assertNotIn('\x1b', displayed)
                self.assertIn('隐藏', displayed)
        self.assertEqual(shell.display_value('http_proxy', None), '未设置')
        self.assertEqual(shell.display_value('https_proxy', ''), '空值')

    def test_human_status_respects_no_color_and_json_contract_is_unchanged(self):
        for as_json in (False, True):
            with self.subTest(as_json=as_json):
                output = io.StringIO()
                with patch.object(control, 'current_installation', return_value=(self.app, None)), \
                        patch.object(control, 'HOME', self.app), redirect_stdout(output), \
                        patch.object(output, 'isatty', return_value=True), \
                        patch.dict(os.environ, {'NO_COLOR': '1'}):
                    result = control.shell_proxy(as_json=as_json)
                self.assertNotIn('\033[', output.getvalue())
                if as_json:
                    self.assertEqual(json.loads(output.getvalue()), result)
                    self.assertFalse(result['enabled'])
                    self.assertFalse(result['current_shell_applied'])
                else:
                    self.assertIn('● 策略已关闭', output.getvalue())

    def test_exact_legacy_templates(self):
        for platform in ('darwin', 'linux'):
            https = '$https_proxy' if platform == 'linux' else '$http_proxy'
            text = f'''export PATH="$HOME/.local/bin:$PATH"
export http_proxy=http://127.0.0.1:17898
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="{https}"
export all_proxy=socks5h://127.0.0.1:17898
export ALL_PROXY="$all_proxy"
export no_proxy={shell.NO_PROXY}
export NO_PROXY="$no_proxy"
'''
            self.assertEqual(shell.legacy_environment_port(text, platform), 17898)
            self.assertIsNone(shell.legacy_environment_port(text + '# custom\n', platform))
            self.assertIsNone(shell.legacy_environment_port(text, 'linux' if platform == 'darwin' else 'darwin'))
            self.assertIsNone(shell.legacy_environment_port(text.replace('17898', '0'), platform))

    def test_metadata_validation_and_child_baselines(self):
        snapshot = {'present': True, 'exported': False, 'value': 'secret'}
        state = {'version': 1, 'app': str(self.app), 'pid': '1', 'owned': {
            'http_proxy': {'baseline': snapshot, 'last': dict(snapshot, exported=True)}}, 'detached': []}
        encoded = base64.b64encode(json.dumps(state).encode()).decode()
        child = shell._decode_state(encoded, self.app, '2')
        self.assertFalse(child['owned']['http_proxy']['baseline']['present'])
        self.assertFalse(shell._decode_state('$(touch bad)', self.app, '1')['owned'])
        state['owned']['evil; bad'] = state['owned']['http_proxy']
        encoded = base64.b64encode(json.dumps(state).encode()).decode()
        self.assertFalse(shell._decode_state(encoded, self.app, '1')['owned'])


class RealShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='domino-shell-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.app = self.root / 'app with spaces'
        (self.app / 'cli').mkdir(parents=True)
        (self.app / 'data').mkdir()
        shutil.copyfile(Path(shell.__file__), self.app / 'cli/domino_shell.py')
        (self.app / 'data/config.json').write_text('{"mixed-port":19876}')
        self.policy(False)
        self.loader = self.root / 'proxy.env'
        self.loader.write_text(shell.integration(self.app, sys.executable))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        command = self.bin / 'domino'
        command.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if len(args)>1 and args[1]=='shell' and args[0].lower().rstrip('.') in ('localhost','127.0.0.1','::1','[::1]'):
    args=args[1:]
if args == ['fail']:
    print('original-output')
    raise SystemExit(17)
if args[:1] == ['env']:
    print('export http_proxy=http://manual:444; export DOMINO_SHELL_MODE=manual')
elif args[:1] == ['shell'] and len(args) > 1 and args[1] in ('on', 'off'):
    Path({str(self.app / 'shell-policy.json')!r}).write_text(json.dumps({{'version': 1, 'enabled': args[1] == 'on'}}))
elif '--json' in args:
    print('{{"ok":true}}')
''')
        command.chmod(0o700)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in shell.VARIABLES and not key.startswith('_DOMINO')
                    and key not in ('DOMINO_SHELL_MODE', 'BASH_ENV', 'ENV', 'ZDOTDIR')}
        self.env.update(HOME=str(self.home), ZDOTDIR=str(self.home),
                        PATH=str(self.bin) + ':/usr/bin:/bin:/usr/sbin:/sbin')

    def policy(self, enabled):
        (self.app / 'shell-policy.json').write_text(json.dumps({'version': 1, 'enabled': enabled}))

    def run_shell(self, name, script, *, interactive=True):
        executable = shutil.which(name)
        if not executable:
            self.skipTest(f'{name} unavailable')
        if name == 'bash':
            args = [executable, '--noprofile', '--norc']
        elif name == 'zsh':
            args = [executable, '-f']
        else:
            args = [executable]
        args += ['-ic' if interactive else '-c', script]
        result = subprocess.run(args, env=self.env, cwd=self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + '\n' + result.stdout)
        return result

    def source(self):
        return '. ' + shlex.quote(str(self.loader))

    def test_on_repeat_off_restores_export_presence_and_empty(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                result = self.run_shell(name, f'''
http_proxy=http://manual:7897
export https_proxy=''
unset HTTP_PROXY
{self.source()}
domino shell on
printf 'ON=%s,%s\\n' "$http_proxy" "$all_proxy"
domino shell on
domino shell off
printf 'RESTORED=%s,https=<%s>,HTTP=<%s>\\n' "$http_proxy" "$https_proxy" "${{HTTP_PROXY+set}}"
{shlex.quote(sys.executable)} -I -c 'import os; print("EXPORT=" + str("http_proxy" in os.environ) + "," + str("https_proxy" in os.environ))'
''')
                self.assertIn('ON=http://127.0.0.1:19876,socks5h://127.0.0.1:19876', result.stdout)
                self.assertIn('RESTORED=http://manual:7897,https=<>,HTTP=<>', result.stdout)
                self.assertIn('EXPORT=False,True', result.stdout)

    def test_auto_only_unset_and_manual_set_and_unset_detach(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(True)
                result = self.run_shell(name, f'''
export http_proxy=http://manual:7897
{self.source()}
printf 'AUTO=%s,%s\\n' "$http_proxy" "$https_proxy"
https_proxy=http://new:7890
unset HTTP_PROXY
_domino_shell_sync
printf 'MANUAL=%s,UNSET=<%s>\\n' "$https_proxy" "${{HTTP_PROXY+set}}"
domino shell off
printf 'OFF=%s,%s,UNSET=<%s>\\n' "$http_proxy" "$https_proxy" "${{HTTP_PROXY+set}}"
domino shell on
printf 'REON=%s\\n' "$https_proxy"
domino shell off
printf 'REOFF=%s\\n' "$https_proxy"
''')
                self.assertIn('AUTO=http://manual:7897,http://127.0.0.1:19876', result.stdout)
                self.assertIn('MANUAL=http://new:7890,UNSET=<>', result.stdout)
                self.assertIn('OFF=http://manual:7897,http://new:7890,UNSET=<>', result.stdout)
                self.assertIn('REON=http://127.0.0.1:19876', result.stdout)
                self.assertIn('REOFF=http://new:7890', result.stdout)

    def test_manual_pause_and_explicit_retake(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(True)
                result = self.run_shell(name, f'''
{self.source()}
eval "$(domino env)"
_domino_shell_sync
printf 'PAUSE=%s,%s\\n' "$http_proxy" "$DOMINO_SHELL_MODE"
domino shell on
printf 'RETAKE=%s,%s\\n' "$http_proxy" "$DOMINO_SHELL_MODE"
domino shell off
printf 'BASELINE=%s\\n' "$http_proxy"
''')
                self.assertIn('PAUSE=http://manual:444,manual', result.stdout)
                self.assertIn('RETAKE=http://127.0.0.1:19876,auto', result.stdout)
                self.assertIn('BASELINE=http://manual:444', result.stdout)

    def test_wrapper_preserves_output_status_and_json(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                result = self.run_shell(name, f'''
{self.source()}
domino fail
printf 'RC=%s\\n' "$?"
domino shell status --json
''')
                self.assertEqual(result.stdout, 'original-output\nRC=17\n{"ok":true}\n')

    def test_current_shell_summary_is_readable_and_preserves_manual_settings(self):
        for name in ('bash','zsh'):
            with self.subTest(shell=name):
                result=self.run_shell(name,f'''
{self.source()}
domino shell on
domino shell status
export http_proxy=http://user:PRIVATE@manual:7897
domino shell status
domino shell off
domino shell status
''')
                self.assertIn('Domino 已接管终端代理',result.stdout)
                self.assertIn('Domino 已接管部分变量 · 保留手动设置',result.stdout)
                self.assertIn('使用原有代理设置 · 保留手动设置',result.stdout)
                for text in ['managed=','restorable=','PRIVATE']:self.assertNotIn(text,result.stdout)

    def test_remote_and_noncanonical_commands_do_not_force_takeover(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(True)
                result = self.run_shell(name, f'''
export http_proxy=http://manual:7897
{self.source()}
domino remote user@host shell on
domino shell on --target user@host
printf 'REMOTE=%s\\n' "$http_proxy"
''')
                self.assertIn('REMOTE=http://manual:7897', result.stdout)

    def test_noninteractive_startup_including_posix(self):
        for name in ('bash', 'zsh', 'sh'):
            with self.subTest(shell=name):
                self.policy(True)
                result = self.run_shell(name, f'''
{self.source()}
printf 'START=%s\\n' "$http_proxy"
command -v domino
''', interactive=False)
                self.assertIn('START=http://127.0.0.1:19876', result.stdout)
                self.assertIn(str(self.bin / 'domino'), result.stdout)

    def test_readonly_partial_not_fatal(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                result = self.run_shell(name, f'''
readonly http_proxy=http://readonly:7897
{self.source()}
domino shell on
printf 'READONLY=%s,OTHER=%s\\n' "$http_proxy" "$https_proxy"
domino shell off
printf 'OFF=%s\\n' "$http_proxy"
''')
                self.assertIn('READONLY=http://readonly:7897,OTHER=http://127.0.0.1:19876', result.stdout)
                self.assertIn('OFF=http://readonly:7897', result.stdout)
                self.assertIn('readonly proxy parameters skipped', result.stderr)

    def test_nested_shell_preserves_exported_not_unexported_baseline(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                child = f'''{self.source()}
domino shell off
printf 'CHILD=http:<%s>,https:<%s>\\n' "${{http_proxy+set}}" "$https_proxy"
'''
                child_args = ('bash --noprofile --norc' if name == 'bash' else 'zsh -f')
                result = self.run_shell(name, f'''
http_proxy=http://unexported:7897
export https_proxy=http://exported:7897
{self.source()}
domino shell on
{child_args} -ic {shlex.quote(child)}
_domino_shell_sync
printf 'PARENT=%s,%s\\n' "$http_proxy" "$https_proxy"
''')
                self.assertIn('CHILD=http:<>,https:<http://exported:7897>', result.stdout)
                self.assertIn('PARENT=http://unexported:7897,http://exported:7897', result.stdout)

    def test_corrupt_policy_and_port_fail_closed(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                (self.app / 'shell-policy.json').write_text('{broken')
                result = self.run_shell(name, f'export http_proxy=http://manual:7897\n{self.source()}\nprintf "%s\\n" "$http_proxy"')
                self.assertEqual(result.stdout, 'http://manual:7897\n')
        self.policy(True)
        (self.app / 'data/config.json').write_text('{"mixed-port":"19876"}')
        result = self.run_shell('bash', f'{self.source()}\nprintf "PRESENT=<%s>\\n" "${{http_proxy+set}}"')
        self.assertIn('PRESENT=<>', result.stdout)

    def test_values_are_data_and_never_helper_arguments(self):
        secret = "http://user:password@host/'; $(touch PWNED);\nnext line"
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                result = self.run_shell(name, f'''
http_proxy={shlex.quote(secret)}
{self.source()}
domino shell on
domino shell status
domino shell off
printf 'BASE=%s\\n' "$http_proxy"
''')
                self.assertIn('BASE=' + secret, result.stdout)
                self.assertNotIn('password', result.stdout.split('BASE=')[0])
                self.assertFalse((self.root / 'PWNED').exists())
                self.assertNotIn('password', result.stderr)

    def test_prompt_hooks_idempotent_and_exit_status_preserved(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                if name == 'bash':
                    script = f'''
PROMPT_COMMAND='printf "OLD=%s\\n" "$?"'
{self.source()}
{self.source()}
false
eval "$PROMPT_COMMAND"
printf 'HOOKS=%s\\n' "$PROMPT_COMMAND"
'''
                else:
                    script = f'''
old_hook() {{ :; }}
precmd_functions=(old_hook)
{self.source()}
{self.source()}
false
_domino_shell_prompt
printf 'RC=%s\\n' "$?"
printf 'HOOKS=%s\\n' "${{precmd_functions[*]}}"
'''
                result = self.run_shell(name, script)
                self.assertEqual(result.stdout.count('_domino_shell_prompt'), 1)
                self.assertIn('OLD=1' if name == 'bash' else 'RC=1', result.stdout)
                self.assertIn('OLD=' if name == 'bash' else 'old_hook', result.stdout)

    def test_bash_array_hook_preserved_and_not_duplicated(self):
        result = self.run_shell('bash', f'''
PROMPT_COMMAND=('printf "ARRAY=%s\\n" "$?"' ':')
{self.source()}
{self.source()}
printf 'COUNT=%s,FIRST=%s\\n' "${{#PROMPT_COMMAND[@]}}" "${{PROMPT_COMMAND[0]}}"
false
_domino_shell_prompt
eval "${{PROMPT_COMMAND[1]}}"
''')
        self.assertIn('COUNT=3,FIRST=_domino_shell_prompt', result.stdout)
        self.assertIn('ARRAY=1', result.stdout)

    def test_prompt_observes_other_terminal_policy_changes_and_keeps_rc(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                update = f"from pathlib import Path; Path({str(self.app / 'shell-policy.json')!r}).write_text('{{\\\"version\\\":1,\\\"enabled\\\":true}}')"
                result = self.run_shell(name, f'''
{self.source()}
{shlex.quote(sys.executable)} -I -c {shlex.quote(update)}
false
_domino_shell_prompt
printf 'RC=%s,PROXY=%s\\n' "$?" "$http_proxy"
''')
                self.assertIn('RC=1,PROXY=http://127.0.0.1:19876', result.stdout)

    def test_explicit_localhost_and_machine_output(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                result = self.run_shell(name, f'''
export http_proxy=http://manual:7897
{self.source()}
domino localhost shell on
printf 'LOCAL=%s\\n' "$http_proxy"
domino shell status --json
''')
                self.assertIn('LOCAL=http://127.0.0.1:19876', result.stdout)
                self.assertNotIn('Current shell:', result.stdout)

    def test_local_aliases_force_explicit_takeover_like_cli(self):
        for name in ('bash', 'zsh'):
            for target in ('LOCALHOST', 'localhost.', '127.0.0.1', '::1', '[::1]'):
                with self.subTest(shell=name, target=target):
                    self.policy(False)
                    result = self.run_shell(name, f'''
export http_proxy=http://manual:7897
{self.source()}
domino {shlex.quote(target)} shell on
printf 'LOCAL=%s\\n' "$http_proxy"
domino {shlex.quote(target)} shell off
printf 'BASELINE=%s\\n' "$http_proxy"
''')
                    self.assertIn('LOCAL=http://127.0.0.1:19876', result.stdout)
                    self.assertIn('BASELINE=http://manual:7897', result.stdout)

    def test_failed_sync_never_reports_a_stale_managed_summary(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(True)
                result = self.run_shell(name, f'''
{self.source()}
printf '{{broken' > {shlex.quote(str(self.app / 'shell-policy.json'))}
domino shell status
printf 'KEPT=%s\\n' "$http_proxy"
''')
                self.assertIn('当前终端', result.stdout)
                self.assertIn('无法确认', result.stdout)
                self.assertIn('KEPT=http://127.0.0.1:19876', result.stdout)
                self.assertNotIn('Domino 已接管终端代理', result.stdout)

    def test_unexporting_owned_parameter_is_a_manual_override(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(True)
                unexport = 'export -n http_proxy' if name == 'bash' else 'typeset -g +x http_proxy'
                result = self.run_shell(name, f'''
{self.source()}
{unexport}
_domino_shell_sync
domino shell off
printf 'KEPT=%s\\n' "$http_proxy"
{shlex.quote(sys.executable)} -I -c 'import os; print("EXPORTED=" + str("http_proxy" in os.environ))'
''')
                self.assertIn('KEPT=http://127.0.0.1:19876', result.stdout)
                self.assertIn('EXPORTED=False', result.stdout)

    def test_nonstandard_parameter_attributes_are_skipped(self):
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                self.policy(False)
                setup = 'declare -i http_proxy=7' if name == 'bash' else 'typeset -i http_proxy=7'
                result = self.run_shell(name, f'''
{setup}
{self.source()}
domino shell on
printf 'INTEGER=%s,OTHER=%s\\n' "$http_proxy" "$https_proxy"
''')
                self.assertIn('INTEGER=7,OTHER=http://127.0.0.1:19876', result.stdout)

    def test_legacy_only_matching_values_removed_with_warning(self):
        self.loader.write_text(shell.integration(self.app, sys.executable, legacy_port=17897))
        for name in ('bash', 'zsh'):
            with self.subTest(shell=name):
                result = self.run_shell(name, f'''
export http_proxy=http://127.0.0.1:17897
export https_proxy=http://manual:7897
{self.source()}
printf 'LEGACY=<%s>,CUSTOM=%s\\n' "${{http_proxy+set}}" "$https_proxy"
''')
                self.assertIn('LEGACY=<>,CUSTOM=http://manual:7897', result.stdout)
                self.assertIn('baseline is unknown', result.stderr)


if __name__ == '__main__':
    unittest.main()
