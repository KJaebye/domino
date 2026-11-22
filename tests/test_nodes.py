from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import install_domino as remote
import domino_cli as tool


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.live = {
            '🚀 节点选择': {'type': 'Selector', 'now': 'US A', 'all': ['US A', 'JP B', '自动选择']},
            '自动选择': {'type': 'URLTest', 'now': 'US A', 'all': ['US A', 'JP B']},
            'GLOBAL': {'type': 'Selector', 'now': 'US A', 'all': ['US A', 'JP B']},
            'US A': {'type': 'VLESS', 'password': 'TEST-SECRET-NOT-FOR-OUTPUT'},
            'JP B': {'type': 'Trojan'},
            'DIRECT': {'type': 'Direct'},
        }

    def test_list_reports_choices_and_hides_credentials(self):
        output = io.StringIO()
        with patch.object(remote, 'proxy_state', return_value=({'mode': 'rule'}, self.live)), redirect_stdout(output):
            remote.nodes(as_json=True)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result['groups']), 2)
        self.assertEqual(result['groups'][0]['current'], 'US A')
        self.assertEqual(len(result['nodes']), 2)
        self.assertNotIn('TEST-SECRET-NOT-FOR-OUTPUT', output.getvalue())

    def test_global_group_shown_in_global_mode(self):
        output = io.StringIO()
        with patch.object(remote, 'proxy_state', return_value=({'mode': 'global'}, self.live)), redirect_stdout(output):
            remote.nodes(as_json=True)
        self.assertIn('GLOBAL', [g['name'] for g in json.loads(output.getvalue())['groups']])

    def test_provider_members_are_listed_and_delay_uses_provider_healthcheck(self):
        live={'出口':{'type':'Selector','now':'A','all':['A']}}
        calls=[]
        def api(route,**kwargs):
            calls.append(route)
            if route=='/proxies': return {'proxies':live}
            if route=='/providers/proxies': return {'providers':{'pool':{'vehicleType':'File','proxies':[{'name':'A','type':'Trojan','password':'PRIVATE'}]}}}
            return {'delay':23}
        with patch.object(remote,'proxy_state',return_value=({'mode':'rule'},live)),patch.object(remote,'api_json',side_effect=api):
            result=remote.collect_nodes()
            self.assertEqual(result['nodes'],[{'name':'A','type':'Trojan'}])
            self.assertNotIn('PRIVATE',json.dumps(result))
            result=remote.delay(render=False)
        self.assertEqual(result,[{'name':'A','delay_ms':23,'ok':True}])
        self.assertTrue(any(route.startswith('/providers/proxies/pool/A/healthcheck?') for route in calls))

    def test_group_detail_marks_current_choice(self):
        output = io.StringIO()
        with patch.object(remote, 'proxy_state', return_value=({'mode': 'rule'}, self.live)), redirect_stdout(output):
            remote.nodes('🚀 节点选择')
        self.assertIn('* US A', output.getvalue())
        self.assertIn('JP B', output.getvalue())

    def test_current_proxy_resolves_nested_runtime_selection_in_the_header(self):
        self.live['🚀 节点选择']['now'] = '自动选择'
        self.live['自动选择']['now'] = 'JP B'
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);app=home/'app';(app/'data').mkdir(parents=True)
            (app/'data/subscription.json').write_text('{"id":"fixture","name":"old name"}')
            index=home/'.config/domino/subscriptions/index.json';index.parent.mkdir(parents=True)
            index.write_text('{"items":[{"id":"fixture","name":"xlink"}]}')
            with patch.object(remote,'HOME',home),patch.object(remote,'current_installation',return_value=(app,None)), \
                    patch.object(remote,'proxy_state',return_value=({'mode':'rule'},self.live)), redirect_stdout(io.StringIO()) as output:
                remote.nodes()
        text=output.getvalue()
        self.assertRegex(text,r'当前配置 +xlink')
        self.assertNotIn('old name',text)
        self.assertNotIn('手动选择',text)
        self.assertNotRegex(text,r'(?m)^  策略组\s+当前选择\s+类型$')
        self.assertIn('当前代理',text)
        self.assertIn('🚀 节点选择 → 自动选择 → JP B',text)
        self.assertLess(text.index('🚀 节点选择 → 自动选择 → JP B'),text.index('节点名称'))
        self.assertNotIn('TEST-SECRET-NOT-FOR-OUTPUT',text)
        self.assertEqual(remote.current_proxy_paths('rule',self.live,'🚀 节点选择'),['🚀 节点选择 → 自动选择 → JP B'])

    def test_current_proxy_respects_global_and_direct_modes(self):
        self.live['GLOBAL']['now']='自动选择'
        self.live['自动选择']['now']='JP B'
        self.assertEqual(remote.current_proxy_paths('global',self.live),['GLOBAL → 自动选择 → JP B'])
        self.assertEqual(remote.current_proxy_paths('direct',self.live),['DIRECT（直连）'])

    def test_current_proxy_handles_cycles_missing_choices_and_load_balancing(self):
        live={'A':{'type':'Selector','now':'B','all':['B']},'B':{'type':'Selector','now':'A','all':['A']}}
        self.assertIn('循环引用',remote.current_proxy_paths('rule',live)[0])
        live['A']['now']='missing'
        self.assertIn('节点信息不可用',remote.current_proxy_paths('rule',live)[0])
        self.assertEqual(remote.current_proxy_paths('rule',{'A':{'type':'LoadBalance','all':['B']}}),['A（按连接分配）'])

    def test_node_list_marks_selections_and_identifies_manual_and_automatic_groups(self):
        self.live['自动选择']['now'] = 'JP B'
        self.live['媒体'] = {'type': 'Selector', 'now': '🚀 节点选择', 'all': ['🚀 节点选择']}
        self.live['Unused'] = {'type': 'Trojan'}
        output = io.StringIO()
        with patch.object(remote, 'proxy_state', return_value=({'mode': 'rule'}, self.live)), \
                patch.object(remote, 'proxy_inventory', side_effect=lambda live: live), redirect_stdout(output):
            remote.nodes()
        text = output.getvalue()
        us = next(line for line in text.splitlines() if '* US A' in line)
        jp = next(line for line in text.splitlines() if '* JP B' in line)
        unused = next(line for line in text.splitlines() if 'Unused' in line)
        self.assertIn('🚀 节点选择（手动）', us)
        self.assertIn('自动选择（自动）', jp)
        self.assertNotIn('GLOBAL', text)
        self.assertNotIn('*', unused)
        self.assertIn('不代表所有请求都走该节点', text)
        self.assertNotIn('TEST-SECRET-NOT-FOR-OUTPUT', text)

    def test_node_markers_include_multiple_groups_and_global_only_in_global_mode(self):
        for mode in ['rule', 'global']:
            with self.subTest(mode=mode):
                output = io.StringIO()
                with patch.object(remote, 'proxy_state', return_value=({'mode': mode}, self.live)), \
                        patch.object(remote, 'proxy_inventory', side_effect=lambda live: live), redirect_stdout(output):
                    remote.nodes()
                row = next(line for line in output.getvalue().splitlines() if '* US A' in line)
                self.assertIn('🚀 节点选择（手动）', row)
                self.assertIn('自动选择（自动）', row)
                self.assertEqual('GLOBAL（手动）' in row, mode == 'global')

    def test_node_markers_do_not_change_json_node_names_or_fields(self):
        output = io.StringIO()
        with patch.object(remote, 'proxy_state', return_value=({'mode': 'rule'}, self.live)), \
                patch.object(remote, 'proxy_inventory', side_effect=lambda live: live), redirect_stdout(output):
            remote.nodes(as_json=True)
        result = json.loads(output.getvalue())
        self.assertEqual(result['nodes'], [{'name': 'US A', 'type': 'VLESS'}, {'name': 'JP B', 'type': 'Trojan'}])
        self.assertNotIn('* ', output.getvalue())

    def test_select_requires_membership_and_manual_group(self):
        with patch.object(remote, 'proxy_state', return_value=({}, self.live)), patch.object(remote, 'controller') as controller:
            for group, node in [('🚀 节点选择', 'missing'), ('自动选择', 'JP B'), ('missing', 'JP B')]:
                with self.assertRaises(remote.InstallError):
                    remote.select_node(group, node)
            controller.assert_not_called()

    def test_select_changes_one_group_and_reads_back_confirmation(self):
        calls = []
        def controller(data, route, payload=None):
            calls.append((route, payload))
            if payload is not None:
                self.live['🚀 节点选择']['now'] = payload['name']
                return b''
            return json.dumps(self.live['🚀 节点选择']).encode()
        with patch.object(remote, 'proxy_state', return_value=({}, self.live)), \
                patch.object(remote, 'controller', side_effect=controller), redirect_stdout(io.StringIO()):
            remote.select_node('🚀 节点选择', 'JP B')
        self.assertEqual(calls[0][1], {'name': 'JP B'})
        self.assertEqual(calls[1][1], None)
        self.assertIn('%', calls[0][0])
        self.assertEqual(self.live['自动选择']['now'], 'US A')

    def test_already_selected_does_not_write(self):
        with patch.object(remote, 'proxy_state', return_value=({}, self.live)), \
                patch.object(remote, 'controller') as controller, redirect_stdout(io.StringIO()):
            remote.select_node('🚀 节点选择', 'US A')
        controller.assert_not_called()

    def test_failed_readback_is_not_reported_as_success(self):
        with patch.object(remote, 'proxy_state', return_value=({}, self.live)), \
                patch.object(remote, 'controller', side_effect=[b'', b'{"now":"US A"}']):
            with self.assertRaises(remote.InstallError):
                remote.select_node('🚀 节点选择', 'JP B')

    def test_node_management_does_not_read_source_profile_or_deploy(self):
        with patch.object(tool, 'SSH') as ssh, patch.object(tool, 'source_config') as source, \
                patch.object(tool, 'deploy') as deploy:
            self.assertEqual(tool.main(['nodes', 'alice@host', '--group', '🚀 节点选择']), 0)
            action = ssh.return_value.__enter__.return_value.action
            action.assert_called_with('nodes', '--group=🚀 节点选择')
            self.assertEqual(tool.main(['select', 'alice@host', '--group', '🚀 节点选择', '--node', 'JP B']), 0)
            action.assert_called_with('select', '--group=🚀 节点选择', '--node=JP B')
            source.assert_not_called()
            deploy.assert_not_called()


class SelectionCLITests(unittest.TestCase):
    def setUp(self):
        self.inventory = {'mode': 'rule', 'groups': [
            {'name': '🚀 节点选择', 'current': 'US A', 'selectable': True, 'choices': ['US A', 'JP B', '自动选择']},
            {'name': '自动选择', 'current': 'US A', 'selectable': False, 'choices': ['US A', 'JP B']}], 'nodes': []}

    def run_local(self, arguments, answers=(), interactive=True):
        calls = []
        def run(command, **kwargs):
            calls.append(command[2:])
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(self.inventory))
        with patch.object(tool, 'run', side_effect=run), patch.object(tool.sys.stdin, 'isatty', return_value=interactive), \
                patch('builtins.input', side_effect=list(answers)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = tool.main(arguments)
        return code, calls

    def test_bare_select_opens_node_menu_and_changes_only_explicit_choice(self):
        code, calls = self.run_local(['select'], ['2'])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [['nodes', '--json'], ['select', '--group=🚀 节点选择', '--node=JP B']])
        for answer in ['', EOFError(), KeyboardInterrupt()]:
            code, calls = self.run_local(['select'], [answer])
            self.assertEqual(code, 130 if isinstance(answer, KeyboardInterrupt) else 0)
            self.assertEqual(calls, [['nodes', '--json']])

    def test_unique_node_name_and_group_keywords_resolve_without_prompting(self):
        for arguments in [['select', 'JP'], ['select', 'JP', '--group', '节点选择'], ['select', '--node', 'JP']]:
            code, calls = self.run_local(arguments, interactive=False)
            self.assertEqual(code, 0)
            self.assertEqual(calls[-1], ['select', '--group=🚀 节点选择', '--node=JP B'])

    def test_multiple_groups_require_a_choice_and_noninteractive_never_guesses(self):
        self.inventory['groups'].append({'name': '视频', 'current': 'US A', 'selectable': True, 'choices': ['US A', 'JP B']})
        code, calls = self.run_local(['select', 'JP'], ['2'])
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ['select', '--group=视频', '--node=JP B'])
        code, calls = self.run_local(['select', 'JP'], interactive=False)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [['nodes', '--json']])
        code, calls = self.run_local(['select'], ['2', '1'])
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ['select', '--group=视频', '--node=US A'])

    def test_global_mode_targets_global_selector(self):
        self.inventory['mode'] = 'global'
        self.inventory['groups'].append({'name': 'GLOBAL', 'current': 'US A', 'selectable': True, 'choices': ['JP B']})
        code, calls = self.run_local(['select', 'JP'], interactive=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ['select', '--group=GLOBAL', '--node=JP B'])

    def test_ambiguous_nodes_open_a_filtered_menu_and_only_use_a_containing_group(self):
        self.inventory['groups'][0]['choices'] = ['[HY2]日本BGP002', '[HY2]美国BGP002', '无关节点']
        self.inventory['groups'].append({'name': '视频', 'current': 'US A', 'selectable': True,
                                         'choices': ['[Vless]香港BGP002']})
        for answer, group, node in [('2', '🚀 节点选择', '[HY2]美国BGP002'), ('3', '视频', '[Vless]香港BGP002')]:
            code, calls = self.run_local(['select', 'BGP002'], [answer])
            self.assertEqual(code, 0)
            self.assertEqual(calls[-1], ['select', '--group='+group, '--node='+node])
        code, calls = self.run_local(['select', 'BGP002'], ['HY2', '美国'])
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1][-1], '--node=[HY2]美国BGP002')
        code, calls = self.run_local(['select', 'BGP002', '--group', '视频'], interactive=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ['select', '--group=视频', '--node=[Vless]香港BGP002'])
        # Complete names keep priority over substring matches and require no menu.
        code, calls = self.run_local(['select', '[HY2]美国BGP002'], interactive=False)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1][-1], '--node=[HY2]美国BGP002')

    def test_ambiguous_node_menu_cancel_or_script_error_never_switches(self):
        self.inventory['groups'][0]['choices'] = ['[HY2]美国BGP002', '[Vless]香港BGP002']
        for answer in ['', EOFError(), KeyboardInterrupt()]:
            code, calls = self.run_local(['select', 'BGP002'], [answer])
            self.assertEqual(code, 130 if isinstance(answer, KeyboardInterrupt) else 0)
            self.assertEqual(calls, [['nodes', '--json']])
        with self.assertRaisesRegex(tool.ToolError, "'\\[HY2\\]美国BGP002'"):
            tool.select_match('BGP002', self.inventory['groups'][0]['choices'], '节点')

    def test_invalid_ambiguous_or_automatic_choices_never_write(self):
        self.inventory['groups'][0]['choices'].append('JP backup')
        for arguments in [['select', 'JP'], ['select', 'missing'], ['select', 'JP B', '--group', '自动选择'],
                          ['select', 'JP', '--node', 'US A'], ['select']]:
            code, calls = self.run_local(arguments, interactive=False)
            self.assertEqual(code, 1)
            self.assertFalse(any(call[0] == 'select' for call in calls))

    def test_remote_menu_reads_and_changes_only_the_remote_target(self):
        with patch.object(tool, 'SSH') as ssh, patch.object(tool, 'run') as local, \
                patch.object(tool.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='2'), \
                redirect_stdout(io.StringIO()):
            action = ssh.return_value.__enter__.return_value.action
            action.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps(self.inventory))
            self.assertEqual(tool.main(['user@host', 'select']), 0)
        self.assertEqual(action.call_args_list[0].args, ('nodes', '--json'))
        self.assertEqual(action.call_args_list[0].kwargs, {'capture_output': True, 'text': True})
        self.assertEqual(action.call_args_list[1].args, ('select', '--group=🚀 节点选择', '--node=JP B'))
        local.assert_not_called()

    def test_node_positional_never_becomes_a_target_and_agent_retains_explicit_fields(self):
        for name in ['JP B', 'user@host', 'localhost', '192.0.2.5']:
            args = tool.normalize_command(tool.build_parser().parse_args(['select', name]))
            self.assertIsNone(args.target)
            self.assertEqual(args.name, name)
        import domino_agent
        args = tool.normalize_command(tool.build_parser(machine_mode=True).parse_args(['user@host', 'select', '--group', 'G', '--node', 'N']))
        self.assertEqual(domino_agent.command_request(args), ('nodes.select', {'group': 'G', 'node': 'N'}))


if __name__ == '__main__':
    unittest.main()
