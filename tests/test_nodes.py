from contextlib import redirect_stdout
import copy
import io
import json
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


if __name__ == '__main__':
    unittest.main()
