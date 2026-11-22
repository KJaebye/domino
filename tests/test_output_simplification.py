"""Task-focused output without losing state, diagnostics or machine contracts."""
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
import io
import json
from pathlib import Path
import shlex
import subprocess
import unittest
from unittest.mock import patch

import domino_cli as cli
import install_domino as control
from tests import test_output_layout as layout


class ProductOutputTests(unittest.TestCase):
    def setUp(self):
        self.fixture=layout.OutputLayoutTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home=self.fixture.home
        self.app=self.fixture.app

    def run_cli(self,*arguments,expected=0):
        result=subprocess.run([str(self.home/'bin/domino'),*arguments],env=self.fixture.environment,
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,expected,result.stderr)
        return result.stdout

    def profiles(self):
        data={'schema':1,'items':[{'id':'a'*32,'name':'primary','kind':'snapshot','node_count':1,
            'usage':{'upload':0,'download':54,'total':100,'expire':1924992000},
            'usage_checked_at':(datetime.now(timezone.utc)-timedelta(hours=8)).isoformat()},
            {'id':'b'*32,'name':'secondary','kind':'snapshot','node_count':2}]}
        registry=self.home/'.config/domino/subscriptions/index.json';registry.parent.mkdir(parents=True,exist_ok=True)
        registry.write_text(json.dumps(data))
        (self.app/'data/subscription.json').write_text(json.dumps({'id':'a'*32}))
        return registry

    def test_config_actions_confirm_the_object_without_reprinting_other_profiles(self):
        registry=self.profiles()
        text=self.run_cli('rename','primary','renamed')
        self.assertIn('已重命名：primary → renamed',text)
        self.assertNotIn('secondary',text)
        self.assertNotIn('套餐已用',text)
        self.assertEqual(json.loads(registry.read_text())['items'][0]['id'],'a'*32)
        data=json.loads(self.run_cli('rename','renamed','primary','--json'))
        self.assertEqual([item['name'] for item in data['configs']],['primary','secondary'])
        self.assertIn('active',data)
        verbose=self.run_cli('rename','primary','renamed','--verbose')
        self.assertIn('已重命名：primary → renamed',verbose)
        self.assertIn('secondary',verbose)
        self.assertIn('流量更新',verbose)

    def test_list_keeps_quota_and_stale_warning_with_details_available(self):
        registry=self.profiles();before=registry.read_bytes()
        text=self.run_cli('list')
        self.assertIn('54.0%',text)
        self.assertIn('缓存待刷新',text)
        self.assertIn('套餐到期',text)
        self.assertNotIn('套餐剩余',text)
        self.assertNotIn('流量更新',text)
        self.assertNotIn('--refresh-usage',text)
        detailed=self.run_cli('list','--verbose')
        self.assertIn('套餐剩余',detailed)
        self.assertIn('流量更新',detailed)
        self.assertEqual(before,registry.read_bytes())

    def test_shell_parent_state_survives_compaction_details_and_language_override(self):
        for name in ('bash','zsh'):
            with self.subTest(shell=name):
                script='. '+shlex.quote(str(self.fixture.loader))+'\n'
                script+='domino --lang en shell on\nprintf "ON-END\\n"\n'
                script+='domino shell status --verbose --lang en\nprintf "DETAIL-END\\n"\n'
                script+='domino shell off\nprintf "OFF-END\\n"\n'
                script+='domino shell on --json\nprintf "JSON-END\\n"\n'
                script+='domino shell off >/dev/null\n'
                raw=self.fixture.terminal(name,script,color=False)
                raw=raw.replace('\r\n','\n')
                compact,tail=raw.split('ON-END\n',1)
                detailed,tail=tail.split('DETAIL-END\n',1)
                off,tail=tail.split('OFF-END\n',1)
                encoded=tail.split('JSON-END\n',1)[0]
                self.fixture.assert_frame(compact);self.fixture.assert_frame(detailed);self.fixture.assert_frame(off)
                self.assertIn('Policy enabled',compact)
                self.assertIn('Current terminal',compact)
                self.assertIn('19876',compact)
                self.assertNotIn('http_proxy / HTTP_PROXY',compact)
                self.assertIn('http_proxy / HTTP_PROXY',detailed)
                self.assertIn('Current terminal',detailed)
                self.assertIn('当前终端',off)
                self.assertIn('使用原有代理设置',off)
                self.assertTrue(json.loads(encoded)['enabled'])
                self.assertFalse(encoded.startswith('\n'))

    def test_verbose_shell_json_is_identical_and_machine_only(self):
        plain=self.run_cli('shell','status','--json')
        detailed=self.run_cli('shell','status','--verbose','--json')
        self.assertEqual(plain,detailed)
        self.assertFalse(json.loads(plain)['current_shell_applied'])
        self.assertNotIn('当前终端',plain)

    def test_compact_status_preserves_unchecked_failure_and_build_mismatch(self):
        state={'installed':True,'active':True,'healthy':False,'enabled':True,'exit_checked':False,
               'cli_build':{'version':'1.3.0','channel':'development','build_id':'new'},
               'runtime_cli_build':{'version':'1.3.0','build_id':'old'}}
        plain=control.status_text(state)
        self.assertIn('出网尚未检测',plain)
        self.assertIn('new',plain);self.assertIn('old',plain)
        self.assertNotIn('内网检测',plain)
        self.assertNotIn('HTTPS 检测',plain)
        self.assertIn('内网检测',control.status_text(state,verbose=True))
        state['exit_checked']=True
        self.assertIn('连通检查未通过',control.status_text(state))

    def test_proxy_grouping_does_not_hide_protocol_differences_or_authentication(self):
        values={key:{'enabled':True,'server':'127.0.0.1','port':19876,'authenticated':False}
                for key in ('http','https','socks')}
        labels=[(key,key.upper()) for key in values]
        def render(verbose=False):
            with redirect_stdout(io.StringIO()) as result,control.human_output():
                control.human_proxy_rows(values,labels,verbose=verbose)
            return result.getvalue()
        self.assertEqual(render().count('127.0.0.1:19876'),1)
        self.assertEqual(render(True).count('127.0.0.1:19876'),3)
        values['https']['enabled']=False
        values['http']['authenticated']=True
        mixed=render()
        self.assertIn('未开启',mixed);self.assertIn('需要认证',mixed)
        self.assertNotIn('HTTP / HTTPS / SOCKS',mixed)

    def test_unsupported_desktop_remains_visible_in_default_output(self):
        import domino_linux
        result={'supported':False,'routing':'unsupported','service':'无 GNOME 桌面会话','proxies':{}}
        with redirect_stdout(io.StringIO()) as rendered,control.human_output():
            domino_linux.show(control,result,False,True)
        self.assertIn('无 GNOME 桌面会话',rendered.getvalue())

    def test_detail_flag_reaches_remote_operations_without_changing_agent_request(self):
        from domino_agent import command_request
        for tokens in (['status'],['shell','status'],['list'],['nodes'],['mode'],['scan'],['providers']):
            with self.subTest(command=tokens):
                args=cli.normalize_command(cli.build_parser().parse_args([*tokens,'--verbose']))
                options,_=cli.management_options(args)
                self.assertIn('--verbose',options)
                # The presentation flag is deliberately absent from RPC parameters.
                _,parameters=command_request(args)
                self.assertNotIn('verbose',parameters)
        for tokens in (['shell','--verbose','status'],['configs','--verbose','list'],['proxy','--verbose','status']):
            args=cli.build_parser().parse_args(tokens)
            self.assertTrue(args.verbose)
            self.assertIsNone(args.target)


if __name__=='__main__':unittest.main()
