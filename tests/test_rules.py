import os
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import domino_cli as cli
import install_domino as control

REAL_RUN = control.run
REAL_API = control.api_json


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.app = self.home / '.local/share/domino'
        self.data = self.app / 'data'
        self.data.mkdir(parents=True)
        self.original = {'mixed-port':17897, 'external-controller':'127.0.0.1:19091', 'secret':'PRIVATE',
                         'mode':'rule', 'log-level':'warning', 'proxies':[
                             {'name':'A','type':'socks5','server':'node.example','port':1080},
                             {'name':'B','type':'socks5','server':'other.example','port':1080}],
                         'proxy-groups':[{'name':'出口','type':'select','proxies':['A','B']}],
                         'rules':['DOMAIN-SUFFIX,existing.test,DIRECT','MATCH,DIRECT']}
        self.path = self.data / 'config.json'
        self.path.write_text(json.dumps(self.original))
        (self.app / 'mihomo').write_text('synthetic core')
        self.mode = 'rule'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(control, HOME=self.home, APP=self.app, BACKUPS=self.home / 'backups'))
        self.stack.enter_context(patch.object(control,'current_installation',return_value=(self.app,Path('domino.service'))))
        self.run = self.stack.enter_context(patch.object(control,'run'))
        self.api = self.stack.enter_context(patch.object(control,'api_json',side_effect=self.respond))

    def respond(self, route, *args, **kwargs):
        if route == '/configs':
            return {'mode':self.mode,'log-level':'info'}
        if route == '/proxies':
            return {'proxies':{'出口':{'type':'Selector','all':['A','B'],'now':'B'}}}
        if route == '/rules':
            return {'rules':[]}

    def edit(self, value='DOMAIN-SUFFIX,example.test,DIRECT', remove=False):
        with redirect_stdout(io.StringIO()):
            control.edit_rule(value,remove=remove)

    def test_prepend_is_persistent_idempotent_and_preserves_runtime_settings(self):
        self.mode='global'
        self.edit()
        value=json.loads(self.path.read_text())
        self.assertEqual(value['rules'],['DOMAIN-SUFFIX,example.test,DIRECT',*self.original['rules']])
        for key in ['mixed-port','external-controller','secret']:
            self.assertEqual(value[key],self.original[key])
        self.assertEqual(value['mode'],'global')
        self.assertEqual(value['log-level'],'info')
        self.assertEqual(control.custom_rules_path().stat().st_mode & 0o777,0o600)
        self.assertIn(('/proxies/%E5%87%BA%E5%8F%A3',{'name':'B'}),[v.args for v in self.api.call_args_list])
        self.api.reset_mock()
        self.edit()
        self.api.assert_not_called()
        self.assertEqual(len(control.custom_rules()),1)

    def test_remove_custom_rule_restores_original_base_order_without_deleting_subscription_rules(self):
        rule=self.original['rules'][0]
        self.edit(rule)
        self.edit('DOMAIN-SUFFIX,example.test,REJECT')
        self.edit(rule,remove=True)
        self.assertEqual(json.loads(self.path.read_text())['rules'],['DOMAIN-SUFFIX,example.test,REJECT',*self.original['rules']])
        self.edit('DOMAIN-SUFFIX,example.test,REJECT',remove=True)
        self.assertEqual(json.loads(self.path.read_text())['rules'],self.original['rules'])
        with self.assertRaisesRegex(control.InstallError,'未找到该自定义规则'):
            self.edit('MATCH,DIRECT',remove=True)

    def test_invalid_rule_is_rejected_before_any_persistent_or_runtime_change(self):
        before=self.path.read_bytes()
        self.run.side_effect=control.InstallError('synthetic invalid policy')
        with self.assertRaisesRegex(control.InstallError,'规则校验失败'):
            self.edit('DOMAIN-SUFFIX,example.test,missing')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(control.custom_rules_path().exists())
        self.assertFalse((self.data / 'rules-base.json').exists())
        self.assertFalse(any(c.args[0].startswith('/configs?') for c in self.api.call_args_list))
        self.assertFalse(list(self.data.glob('.rules-*')))
        for value in ['', 'example.com', 'MATCH,DIRECT\nMATCH,REJECT']:
            with self.assertRaises(control.InstallError):
                self.edit(value)

    def test_failed_reload_rolls_back_files_and_runtime_selection_without_touching_kernel_cache(self):
        before=self.path.read_bytes()
        cache=self.data / 'cache.db'
        cache.write_bytes(b'live cache')
        reloads=[]
        def response(route,*args,**kwargs):
            if route.startswith('/configs?'):
                reloads.append(route)
                if len(reloads)==1:
                    raise OSError('synthetic connection reset')
            return self.respond(route,*args,**kwargs)
        self.api.side_effect=response
        with self.assertRaisesRegex(control.InstallError,'已恢复原配置'):
            self.edit()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertFalse(control.custom_rules_path().exists())
        self.assertFalse((self.data / 'rules-base.json').exists())
        self.assertEqual(cache.read_bytes(),b'live cache')
        self.assertEqual(len(reloads),2)

    def test_custom_query_returns_original_rule_text_without_needing_a_running_core(self):
        self.edit()
        self.api.reset_mock()
        output=io.StringIO()
        with redirect_stdout(output):
            control.rules(custom=True,as_json=True)
        self.assertEqual(json.loads(output.getvalue())['rules'],['DOMAIN-SUFFIX,example.test,DIRECT'])
        self.api.assert_not_called()

    def test_new_installation_composes_rules_and_keeps_an_unmodified_base(self):
        self.edit()
        bundle=self.home / 'bundle'
        bundle.mkdir()
        (bundle / 'config.json').write_text(json.dumps(self.original))
        control.prepare_custom_rules(bundle)
        self.assertEqual(json.loads((bundle/'rules-base.json').read_text()),self.original['rules'])
        self.assertEqual(json.loads((bundle/'config.json').read_text())['rules'][0],'DOMAIN-SUFFIX,example.test,DIRECT')

    def test_local_reinitialization_does_not_bake_custom_rules_into_the_base_but_deployment_copies_effective_rules(self):
        self.edit()
        with patch.object(Path,'home',return_value=self.home), patch.object(cli,'discover_proxy',return_value=None):
            args=cli.build_parser().parse_args(['init'])
            _,profile,_=cli.source_config(args)
            self.assertEqual(profile['rules'],self.original['rules'])
            args=cli.build_parser().parse_args(['deploy','alice@host'])
            _,profile,_=cli.source_config(args)
            self.assertEqual(profile['rules'][0],'DOMAIN-SUFFIX,example.test,DIRECT')

    def test_add_remove_and_query_commands_support_local_and_remote_targets(self):
        for action in ['add','remove']:
            for target in [None,'localhost','alice@host']:
                with self.subTest(action=action,target=target), patch.object(cli,'run') as run, patch.object(cli,'SSH') as ssh:
                    arguments=['rules',action,'DOMAIN-SUFFIX,example.test,出口',*([target] if target else []),'--json']
                    self.assertEqual(cli.main(arguments),0)
                    forwarded=(ssh.return_value.__enter__.return_value.action.call_args.args if target=='alice@host'
                               else run.call_args.args[0][2:])
                    self.assertEqual(forwarded[0],'rules')
                    self.assertIn('--'+action+'=DOMAIN-SUFFIX,example.test,出口',forwarded)
                    self.assertIn('--json',forwarded)
        with patch.object(cli,'run') as run, patch.object(cli,'SSH') as ssh:
            self.assertEqual(cli.main(['rules','localhost','--match','example']),0)
            self.assertIn('--match=example',run.call_args.args[0])
            ssh.assert_not_called()
        with patch.object(cli,'run') as run, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['rules','add']),1)
        run.assert_not_called()

    @unittest.skipUnless((Path(os.environ.get('DOMINO_TEST_CORE',str(Path.home()/'.local/share/domino/mihomo')))).is_file(),'requires a locally installed Mihomo binary')
    def test_isolated_real_kernel_validates_and_applies_rules_and_rejects_missing_policies(self):
        shutil.copy2(Path(os.environ.get('DOMINO_TEST_CORE',str(Path.home()/'.local/share/domino/mihomo'))),self.app/'mihomo')
        (self.app/'mihomo').chmod(0o755)
        with socket.socket() as a, socket.socket() as b:
            a.bind(('127.0.0.1',0))
            b.bind(('127.0.0.1',0))
            config=cli.sanitize_profile(self.original,{},a.getsockname()[1],b.getsockname()[1])
        self.path.write_text(json.dumps(config))
        self.run.side_effect=REAL_RUN
        self.api.side_effect=REAL_API
        with (self.home/'core.log').open('w') as log:
            core=subprocess.Popen([str(self.app/'mihomo'),'-d',str(self.data),'-f',str(self.path)],stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        control.api_json('/version')
                        break
                    except (OSError,control.InstallError):
                        time.sleep(.05)
                else:
                    self.fail('isolated core did not start')
                self.edit()
                first=control.api_json('/rules')['rules'][0]
                self.assertEqual((first['payload'],first['proxy']),('example.test','DIRECT'))
                before=self.path.read_bytes()
                with self.assertRaisesRegex(control.InstallError,'规则校验失败'):
                    self.edit('DOMAIN-SUFFIX,invalid.test,missing-policy')
                self.assertEqual(self.path.read_bytes(),before)
                self.edit(remove=True)
                self.assertEqual(json.loads(self.path.read_text())['rules'],self.original['rules'])
                self.assertEqual(control.api_json('/rules')['rules'][0]['payload'],'existing.test')
            finally:
                core.terminate()
                try:
                    core.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    core.kill()
                    core.wait()


if __name__=='__main__':
    unittest.main()
