from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_domino as control
import domino_cli as tool


class ControlTests(unittest.TestCase):
    def test_pending_install_status_checks_controller_without_claiming_proxy_health(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory)
            (app/'data').mkdir()
            (app/'data/config.json').write_text('{"mixed-port":17897,"proxies":[]}')
            (app/'manifest.json').write_text('{"awaiting_subscription":true}')
            output=io.StringIO()
            with patch.object(control,'current_installation',return_value=(app,Path('domino.service'))), \
                    patch.object(control,'systemctl',return_value=True), patch.object(control,'controller',return_value=b'{}'), \
                    patch.object(control,'probe') as probe, redirect_stdout(output):
                self.assertEqual(control.status(True),3)
            result=json.loads(output.getvalue())
            self.assertTrue(result['installed'])
            self.assertTrue(result['active'])
            self.assertTrue(result['awaiting_subscription'])
            self.assertFalse(result['healthy'])
            probe.assert_not_called()
    def test_delay_auto_detects_partial_group_and_node_names(self):
        live = {'♻️ 自动选择':{'all':['[HY2]美国TRI002','日本001']},
                '[HY2]美国TRI002':{'type':'Hysteria2'},'日本001':{'type':'Trojan'}}
        for query,expected in [('自动选择',['[HY2]美国TRI002','日本001']),('美国TRI002',['[HY2]美国TRI002'])]:
            with self.subTest(query=query):
                output=io.StringIO()
                def api(route,**kwargs):
                    return {'proxies':live} if route=='/proxies' else {'delay':214}
                with patch.object(control,'api_json',side_effect=api) as calls, redirect_stdout(output):
                    control.delay(name=query,as_json=True,timeout_ms=10000)
                values=json.loads(output.getvalue())
                self.assertEqual([item['name'] for item in values],expected)
                self.assertTrue(all(item['delay_ms']==214 for item in values))
                self.assertTrue(all('timeout=10000' in call.args[0] for call in calls.call_args_list[1:]))

    def test_delay_all_skips_groups_and_builtin_policies(self):
        live={'♻️ 自动选择':{'all':['A']},'A':{'type':'Trojan'},'B':{'type':'Hysteria2'},
              'DIRECT':{'type':'Direct'},'REJECT':{'type':'Reject'},'PASS-RULE':{'type':'PassRule'}}
        output=io.StringIO()
        with patch.object(control,'api_json',side_effect=lambda route,**kwargs:{'proxies':live} if route=='/proxies' else {'delay':10}), \
                redirect_stdout(output):
            control.delay(as_json=True)
        self.assertEqual([item['name'] for item in json.loads(output.getvalue())],['A','B'])

    def test_delay_ambiguous_or_missing_names_do_not_start_measurements(self):
        live={'♻️ 自动选择':{'all':['A']},'备用自动选择':{'all':['B']},'HY2 A':{},'HY2 B':{}}
        for options,candidates in [({'name':'自动选择'},['♻️ 自动选择','备用自动选择']),
                                   ({'group':'自动选择'},['♻️ 自动选择','备用自动选择']),
                                   ({'node':'HY2'},['HY2 A','HY2 B']),({'name':''},[]),({'name':'missing'},[])]:
            with self.subTest(options=options), patch.object(control,'api_json',return_value={'proxies':live}) as api:
                with self.assertRaises(control.InstallError) as caught:
                    control.delay(**options)
                for candidate in candidates:
                    self.assertIn(candidate,str(caught.exception))
                self.assertTrue(all(call.args[0] in ['/proxies','/providers/proxies'] for call in api.call_args_list))

    def test_delay_exact_name_wins_over_partial_matches(self):
        live={'美国':{'type':'Trojan'},'美国备用':{'type':'Trojan'}}
        output=io.StringIO()
        with patch.object(control,'api_json',side_effect=lambda route,**kwargs:{'proxies':live} if route=='/proxies' else {'delay':1}), \
                redirect_stdout(output):
            control.delay(name='美国',as_json=True)
        self.assertEqual([item['name'] for item in json.loads(output.getvalue())],['美国'])

    def test_simple_delay_syntax_routes_local_and_remote_and_preserves_legacy_forms(self):
        cases=[(['delay'],None,'--all'),(['delay','自动选择'],None,'--name=自动选择'),
               (['delay','美国TRI002','nvidia@192.168.8.21'],'nvidia@192.168.8.21','--name=美国TRI002'),
               (['delay','all','lab-alias'],'lab-alias','--all'),
               (['delay','nvidia@192.168.8.21'],'nvidia@192.168.8.21','--all'),
               (['delay','192.168.8.21'],'192.168.8.21','--all'),
               (['delay','[2001:db8::21]'],'[2001:db8::21]','--all'),
               (['delay','localhost'], 'localhost','--all'),
               (['delay','localhost','--node','Japan'],'localhost','--node=Japan'),
               (['delay','--group','自动选择','lab-alias'],'lab-alias','--group=自动选择')]
        for argv,target,selector in cases:
            with self.subTest(argv=argv):
                args=tool.normalize_command(tool.build_parser().parse_args(argv))
                options,_=tool.management_options(args)
                self.assertEqual(args.target,target)
                self.assertIn(selector,options)
                self.assertIn('--timeout',options)

    def test_overview_is_credential_free_and_does_not_probe_external_network(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'data').mkdir()
            (app / 'data/config.json').write_text('{"mixed-port":17897,"secret":"PRIVATE"}')
            responses = [{'mode':'rule'}, {'proxies':{
                '出口': {'type':'Selector','all':['A'],'now':'A','password':'PRIVATE'},
                'A': {'type':'Trojan','password':'PRIVATE'}}},
                {'connections':[],'uploadTotal':100,'downloadTotal':200}]
            output = io.StringIO()
            with patch.object(control,'current_installation',return_value=(app,Path('domino.service'))), \
                    patch.object(control,'systemctl',return_value=True), patch.object(control,'api_json',side_effect=responses), \
                    patch.object(control,'probe') as probe, redirect_stdout(output):
                control.overview()
            value=json.loads(output.getvalue())
            self.assertTrue(value['reachable'])
            self.assertEqual(value['node_count'],1)
            self.assertNotIn('PRIVATE',output.getvalue())
            probe.assert_not_called()

    def test_mode_change_is_read_back_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'data').mkdir()
            path = app / 'data/config.json'
            path.write_text('{"mode":"rule","secret":"PRIVATE"}')
            with patch.object(control, 'current_installation', return_value=(app, None)), \
                    patch.object(control, 'api_json', side_effect=[{'mode': 'rule'}, None, {'mode': 'global'}]) as api, \
                    redirect_stdout(io.StringIO()):
                control.set_option('mode', 'global')
            self.assertEqual(json.loads(path.read_text())['mode'], 'global')
            self.assertEqual(json.loads(path.read_text())['secret'], 'PRIVATE')
            self.assertEqual(api.call_args_list[1].kwargs['method'], 'PATCH')

    def test_failed_mode_persistence_restores_runtime_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory)
            (app/'data').mkdir()
            path=app/'data/config.json'
            path.write_text('{"mode":"rule"}')
            with patch.object(control,'current_installation',return_value=(app,None)), \
                    patch.object(control,'api_json',side_effect=[{'mode':'rule'},None,{'mode':'direct'},None,{'mode':'rule'}]) as api, \
                    patch.object(control,'write_private',side_effect=OSError('disk full')):
                with self.assertRaises(control.InstallError) as caught: control.set_option('mode','direct')
            self.assertEqual(caught.exception.effect,'rolled_back')
            self.assertEqual(json.loads(path.read_text())['mode'],'rule')
            self.assertEqual(api.call_args_list[-2].args,('/configs',{'mode':'rule'}))

    def test_connections_hide_unrelated_fields_and_encode_close_id(self):
        output = io.StringIO()
        data = {'connections': [{'id': 'ABC', 'metadata': {'host': 'example.test', 'destinationPort': '443'},
                                 'chains': ['Japan'], 'password': 'PRIVATE'}]}
        with patch.object(control, 'api_json', return_value=data), redirect_stdout(output):
            control.connections(as_json=True)
        self.assertNotIn('PRIVATE', output.getvalue())
        with patch.object(control, 'api_json') as api, redirect_stdout(io.StringIO()):
            control.connections(close='a/b')
        api.assert_called_once_with('/connections/a%2Fb', method='DELETE')

    def test_provider_output_does_not_expose_subscription_urls(self):
        for as_json in [False,True]:
            output = io.StringIO()
            with patch.object(control, 'api_json', return_value={'providers': {'airport': {'url': 'https://host?token=PRIVATE', 'proxies': [{}]}}}), \
                    redirect_stdout(output):
                control.providers(as_json=as_json)
            self.assertNotIn('PRIVATE', output.getvalue())
            if as_json: self.assertEqual(json.loads(output.getvalue())[0]['count'], 1)

    def test_builtin_provider_cannot_be_reported_as_a_subscription_update(self):
        with patch.object(control, 'api_json', return_value={'providers': {'inline': {'vehicleType': 'Compatible'}}}) as api:
            with self.assertRaises(control.InstallError):
                control.providers(update='inline')
        self.assertEqual(api.call_count, 1)

    def test_shell_environment_contains_only_validated_local_port(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'data').mkdir()
            (app / 'data/config.json').write_text('{"mixed-port":17897,"secret":"PRIVATE"}')
            output = io.StringIO()
            with patch.object(control, 'current_installation', return_value=(app, None)), redirect_stdout(output):
                control.shell_environment()
            self.assertIn('http://127.0.0.1:17897', output.getvalue())
            self.assertNotIn('PRIVATE', output.getvalue())

    def test_all_new_management_commands_support_localhost_and_remote(self):
        commands = [['mode', '--set', 'global'], ['log-level', '--set', 'info'],
                    ['delay', '--node', 'Japan'], ['connections', '--close', 'ID'],
                    ['traffic', '--watch', '--count', '2'], ['rules', '--match', 'google'],
                    ['providers', '--update', 'airport']]
        for command in commands:
            with self.subTest(command=command), patch.object(tool, 'run') as run, patch.object(tool, 'SSH') as ssh:
                self.assertEqual(tool.main([command[0], 'localhost', *command[1:]]), 0)
                self.assertEqual(run.call_args.args[0][2], command[0])
                ssh.assert_not_called()
                self.assertEqual(tool.main([command[0], 'alice@host', *command[1:]]), 0)
                self.assertEqual(ssh.return_value.__enter__.return_value.action.call_args.args[0], command[0])


if __name__ == '__main__':
    unittest.main()
