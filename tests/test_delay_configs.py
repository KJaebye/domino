"""Cached-profile delay runs use disposable cores, never the active service."""
from contextlib import ExitStack, contextmanager, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import domino_agent
import domino_cli as cli
import domino_subscriptions as subs
import install_domino as control

CORE = Path(os.environ.get('DOMINO_TEST_CORE', str(Path.home() / '.local/share/domino/mihomo')))
REAL_POPEN = subprocess.Popen


class ConfigDelayTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.app = self.home / '.local/share/domino'
        (self.app / 'data').mkdir(parents=True)
        (self.app / 'data/config.json').write_text('{"fixture":"active configuration"}')
        (self.app / 'data/subscription.json').write_text('{"id":"active-fixture"}')
        (self.app / 'mihomo').write_text('fake core')
        self.stack.enter_context(patch.multiple(control, HOME=self.home, APP=self.app))
        self.stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        self.stack.enter_context(patch.object(control, 'current_installation', return_value=(self.app, None)))
        self.stack.enter_context(patch.object(control, 'run'))
        self.raw = {'mode': 'rule', 'proxies': [
            {'name': name, 'type': 'socks5', 'server': 'node.example.invalid', 'port': 1080}
            for name in ['A', 'B']], 'rules': ['MATCH,A']}
        self.source = self.home / 'external.json'
        self.source.write_text(json.dumps(self.raw))
        manager = subs.Manager(control)
        item, _ = manager.capture(self.source, self.raw)
        item['name'] = 'feiniao'
        manager.replace(item); manager.save()
        self.before = {str(p): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}
        self.before_index = manager.index.read_bytes()

    @contextmanager
    def api(self, name, **options):
        self.assertEqual(name, 'feiniao')
        def request(route, **options):
            if route == '/proxies':
                return {'proxies': {'A': {'type': 'Socks5'}, 'B': {'type': 'Socks5'}}}
            return {'delay': 25}
        yield request

    def unchanged(self):
        self.assertEqual(self.before, {str(p): p.read_bytes() for p in self.app.rglob('*') if p.is_file()})
        self.assertEqual(subs.Manager(control).index.read_bytes(), self.before_index)

    def test_exact_config_name_and_explicit_selector_use_isolated_api(self):
        for options in [{'name': 'feiniao'}, {'config': 'feiniao'}]:
            with self.subTest(options=options), patch.object(control, 'isolated_delay_config', self.api), \
                    patch.object(control, 'api_json', side_effect=AssertionError('active API used')):
                result = control.delay(render=False, **options)
            self.assertEqual(result, [{'name': n, 'delay_ms': 25, 'ok': True} for n in ['A', 'B']])
        self.unchanged()

    def test_node_timeout_remains_a_per_node_result_and_does_not_use_active_api(self):
        @contextmanager
        def isolated(name):
            def api(route, **options):
                if route == '/proxies':
                    return {'proxies': {'A': {'type': 'Socks5'}, 'B': {'type': 'Socks5'}}}
                if '/B/' in route:
                    raise control.InstallError('fixture timeout', code='TIMEOUT')
                return {'delay': 30}
            yield api
        with patch.object(control, 'isolated_delay_config', isolated), patch.object(control, 'api_json') as active:
            result = control.delay(config='feiniao', render=False)
        self.assertEqual(result, [{'name': 'A', 'delay_ms': 30, 'ok': True}, {'name': 'B', 'delay_ms': None, 'ok': False}])
        active.assert_not_called()
        self.unchanged()

    def activate_fixture(self, other=False):
        manager=subs.Manager(control)
        item=manager.find('feiniao')
        if other:
            item=dict(item,id='e'*32,name='xlink')
            manager.registry['items'].append(item);manager.save()
            self.before_index=manager.index.read_bytes()
        (self.app/'data/subscription.json').write_text(json.dumps({'id':item['id']}))
        self.before={str(p):p.read_bytes() for p in self.app.rglob('*') if p.is_file()}

    def test_single_config_marks_only_the_real_runtime_selection(self):
        self.activate_fixture()
        live={'出口':{'type':'Selector','now':'自动','all':['自动','A']},
              '自动':{'type':'URLTest','now':'B','all':['A','B']},
              'A':{'type':'Socks5'},'B':{'type':'Socks5','password':'PRIVATE'}}
        def runtime(route,**options):
            return {'proxies':live} if route=='/proxies' else {'mode':'rule'}
        with patch.object(control,'isolated_delay_config',self.api),patch.object(control,'api_json',side_effect=runtime) as api, \
                redirect_stdout(io.StringIO()) as output:
            rows=control.delay(config='feiniao')
        text=output.getvalue()
        self.assertIn('配置 ● feiniao',text)
        self.assertIn('出口 → 自动 → B',text)
        self.assertIn('● B',text)
        self.assertNotIn('● A',text)
        self.assertNotIn('PRIVATE',text)
        self.assertEqual(rows,[{'name':n,'delay_ms':25,'ok':True} for n in ['A','B']])
        self.assertEqual([c.args[0] for c in api.call_args_list],['/proxies','/configs'])
        self.unchanged()

    def test_inactive_config_names_the_active_config_without_marking_its_nodes(self):
        self.activate_fixture(other=True)
        with patch.object(control,'isolated_delay_config',self.api),patch.object(control,'api_json') as api, \
                redirect_stdout(io.StringIO()) as output:
            control.delay(config='feiniao')
        text=output.getvalue()
        self.assertIn('未启用 · 当前使用 xlink',text)
        self.assertNotIn('配置 ● feiniao',text)
        self.assertNotIn('● A',text)
        self.assertNotIn('● B',text)
        api.assert_not_called()
        self.unchanged()

    def test_unavailable_runtime_does_not_prevent_testing_or_guess_a_current_node(self):
        self.activate_fixture()
        with patch.object(control,'isolated_delay_config',self.api), \
                patch.object(control,'api_json',side_effect=control.InstallError('PRIVATE failure')), \
                redirect_stdout(io.StringIO()) as output:
            rows=control.delay(config='feiniao')
        self.assertTrue(all(row['ok'] for row in rows))
        self.assertIn('读取失败，本次不标记',output.getvalue())
        self.assertNotIn('● A',output.getvalue())
        self.assertNotIn('PRIVATE',output.getvalue())
        self.unchanged()

    def test_default_summary_counts_every_config_and_retains_failure_rows(self):
        manager = subs.Manager(control)
        manager.registry['items'].extend([
            {'id':'c'*32,'name':'uncached','kind':'subscription'},
            {'id':'d'*32,'name':'broken','kind':'snapshot','revision':'e'*32,'node_count':9}])
        manager.save()
        before_index = manager.index.read_bytes()
        calls = []
        def measure(**options):
            calls.append(options['config'])
            if options['config']=='broken':
                raise control.InstallError('PRIVATE detail',code='DELAY_CORE_FAILED')
            return [{'name':'A','delay_ms':10,'ok':True},{'name':'B','delay_ms':None,'ok':False}]
        with patch.object(control,'delay',side_effect=measure), patch.object(control,'api_json') as active:
            rows=control.delay_summary(render=False)
        self.assertCountEqual(calls,['feiniao','broken'])
        self.assertEqual(rows[0]['total'],2)
        self.assertEqual((rows[0]['available'],rows[0]['unavailable']),(1,1))
        self.assertEqual(rows[1]['status'],'uncached')
        self.assertIsNone(rows[1]['available'])
        self.assertEqual(rows[2]['status'],'error')
        self.assertIsNone(rows[2]['unavailable'])
        self.assertNotIn('PRIVATE',json.dumps(rows))
        self.assertEqual(manager.index.read_bytes(),before_index)
        active.assert_not_called()

    def test_summary_empty_library_and_invalid_options_do_not_start_core(self):
        manager=subs.Manager(control)
        manager.registry['items']=[];manager.save()
        with patch.object(control,'isolated_delay_config') as core:
            self.assertEqual(control.delay_summary(render=False),[])
            with self.assertRaises(control.InstallError):control.delay_summary(timeout_ms=1,render=False)
            with self.assertRaises(control.InstallError):control.delay_summary(url='http://example.test',render=False)
            core.assert_not_called()

    def test_summary_json_human_output_and_agent_contract(self):
        with patch.object(control,'isolated_delay_config',self.api):
            output=io.StringIO()
            with redirect_stdout(output):control.delay_summary(as_json=True)
            rows=json.loads(output.getvalue())
            self.assertEqual(rows[0]['available'],2)
            self.assertEqual(rows[0]['unavailable'],0)
            output=io.StringIO()
            with redirect_stdout(output):control.delay_summary()
            for word in ['配置名称','节点总数','可用','超时/不可用','feiniao']:
                self.assertIn(word,output.getvalue())
        for argv in [['test'],['user@host','test'],['test','--all']]:
            args=cli.normalize_command(cli.build_parser().parse_args(argv))
            self.assertIn('--summary',cli.management_options(args)[0])
            self.assertEqual(domino_agent.command_request(args)[0],'delay.summary')
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(['test','--current'])
        self.unchanged()

    def test_summary_agent_operation_returns_the_summary_array(self):
        from domino_service import Application, OPERATIONS
        with patch.object(control,'delay_summary',return_value=[{'fixture':'summary'}]) as summary:
            result=Application(control).read('delay.summary',{'timeout':1000})
        self.assertEqual(result,[{'fixture':'summary'}])
        summary.assert_called_once_with(url='https://www.gstatic.com/generate_204',timeout_ms=1000,render=False)
        self.assertEqual(OPERATIONS['delay.summary']['result']['type'],'array')

    def test_summary_does_not_swallow_interrupt_or_test_later_configs(self):
        with patch.object(control,'delay',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            control.delay_summary(render=False)
        self.unchanged()

    def test_summary_parallelizes_configs_with_one_global_node_budget(self):
        from threading import Barrier, Event, Lock
        manager=subs.Manager(control)
        template=manager.registry['items'][0]
        manager.registry['items']=[dict(template,id=f'{index+1:032x}',name=f'config-{index}') for index in range(6)]
        manager.save();self.before_index=manager.index.read_bytes()
        lock=Lock(); ready=Barrier(control.DELAY_CONFIG_WORKERS); full=Event()
        active_cores=peak_cores=active_nodes=peak_nodes=0
        @contextmanager
        def isolated(name,**options):
            nonlocal active_cores,peak_cores,active_nodes,peak_nodes
            with lock:
                active_cores+=1;peak_cores=max(peak_cores,active_cores)
            try:
                ready.wait(timeout=5)
                def request(route,**kwargs):
                    nonlocal active_nodes,peak_nodes
                    if route=='/proxies':
                        return {'proxies': {f'node-{i}':{'type':'Socks5'} for i in range(16)}}
                    with lock:
                        active_nodes+=1;peak_nodes=max(peak_nodes,active_nodes)
                        if active_nodes==control.DELAY_NODE_WORKERS:full.set()
                    try:
                        if not full.wait(5):raise AssertionError('node probes did not overlap')
                        return {'delay':15}
                    finally:
                        with lock:active_nodes-=1
                yield request
            finally:
                with lock:active_cores-=1
        with patch.object(control,'isolated_delay_config',isolated),patch.object(control,'api_json') as current:
            rows=control.delay_summary(render=False)
        self.assertEqual([row['name'] for row in rows],[f'config-{i}' for i in range(6)])
        self.assertTrue(all(row['total']==16 and row['available']==16 for row in rows))
        self.assertEqual(peak_cores,control.DELAY_CONFIG_WORKERS)
        self.assertEqual(peak_nodes,control.DELAY_NODE_WORKERS)
        self.assertEqual((active_cores,active_nodes),(0,0))
        current.assert_not_called();self.unchanged()

    def test_single_config_uses_increased_node_parallelism(self):
        from threading import Event, Lock
        full=Event();lock=Lock();active=peak=0
        def api(route,**options):
            nonlocal active,peak
            if route=='/proxies':return {'proxies':{f'N{i}':{'type':'Socks5'} for i in range(64)}}
            with lock:
                active+=1;peak=max(peak,active)
                if active==control.DELAY_NODE_WORKERS:full.set()
            try:
                if not full.wait(5):raise AssertionError('probes were serialized')
                return {'delay':10}
            finally:
                with lock:active-=1
        rows=control.delay(_api=api,render=False)
        self.assertEqual(len(rows),64)
        self.assertTrue(all(row['ok'] for row in rows))
        self.assertEqual(peak,control.DELAY_NODE_WORKERS)
        self.unchanged()

    def test_parallel_interrupt_cancels_other_config_and_closes_all_contexts(self):
        from concurrent.futures import CancelledError
        from threading import Barrier, Lock
        manager=subs.Manager(control);template=manager.registry['items'][0]
        manager.registry['items'].append(dict(template,id='f'*32,name='other'))
        manager.save();self.before_index=manager.index.read_bytes()
        entered=Barrier(2);lock=Lock();closed=[]
        @contextmanager
        def isolated(name,**options):
            cancel=options['_cancel']
            try:
                entered.wait(timeout=5)
                def api(route,**kwargs):
                    if route=='/proxies':return {'proxies':{'A':{'type':'Socks5'}}}
                    if name=='feiniao':raise KeyboardInterrupt()
                    if not cancel.wait(5):raise AssertionError('cancellation did not reach other config')
                    raise CancelledError()
                yield api
            finally:
                with lock:closed.append(name)
        with patch.object(control,'isolated_delay_config',isolated),self.assertRaises(KeyboardInterrupt):
            control.delay_summary(render=False)
        self.assertCountEqual(closed,['feiniao','other'])
        self.unchanged()

    def test_concurrent_core_port_reservations_retry_collisions_and_release(self):
        before=set(control._DELAY_PORTS)
        with patch.object(control.socket,'socket') as socket:
            reservation=socket.return_value.__enter__.return_value
            reservation.getsockname.side_effect=[('127.0.0.1',31001),('127.0.0.1',31001),('127.0.0.1',31002)]
            with control._delay_port() as first:
                with self.assertRaises(ValueError):
                    with control._delay_port() as second:
                        self.assertNotEqual(first,second)
                        raise ValueError('fixture interrupted')
                self.assertEqual(control._DELAY_PORTS,before|{first})
        self.assertEqual(control._DELAY_PORTS,before)

    def test_progress_counts_completed_nodes_before_a_slow_first_result(self):
        from threading import Event
        updated = Event()
        class Terminal(io.StringIO):
            def isatty(self): return True
            def write(self, text):
                result = super().write(text)
                if '节点 2/3' in text:
                    updated.set()
                return result
        terminal = Terminal()
        def api(route, **options):
            if route == '/proxies':
                return {'proxies': {n: {'type': 'Socks5'} for n in ['A', 'B', 'C']}}
            if '/A/' in route and not updated.wait(3):
                raise AssertionError('progress waited for the first node instead of completed nodes')
            if '/C/' in route:
                raise control.InstallError('fixture timeout')
            return {'delay': 10}
        with redirect_stderr(terminal), redirect_stdout(io.StringIO()):
            rows = control.delay(_api=api)
        self.assertEqual([row['name'] for row in rows], ['A', 'B', 'C'])
        frames = terminal.getvalue()
        self.assertIn('节点 2/3', frames)
        self.assertIn('节点 3/3', frames)
        self.assertIn('100%', frames)
        self.assertIn('可用 2 · 不可用 1', frames)
        self.assertFalse(any(t.name == 'domino-delay-progress' for t in __import__('threading').enumerate()))
        self.unchanged()

    def test_summary_progress_handles_uncached_configs_and_unknown_totals(self):
        manager = subs.Manager(control)
        manager.registry['items'].append({'id': 'b'*32, 'name': 'uncached', 'kind': 'subscription'})
        manager.save(); self.before_index = manager.index.read_bytes()
        terminal = io.StringIO()
        with redirect_stderr(terminal), redirect_stdout(io.StringIO()), \
                patch.object(control, 'isolated_delay_config', self.api):
            # Forced output also covers a remote backend without a PTY.
            with control._DelayProgress(force=True, configs=True) as progress:
                rows = control.delay_summary(_progress=progress)
        frames = terminal.getvalue()
        self.assertIn('加载配置', frames)
        self.assertIn('节点 0/?', frames)
        self.assertIn('节点 2/2', frames)
        self.assertIn('配置 2/2', frames)
        self.assertEqual(rows[1]['status'], 'uncached')
        self.assertIsNone(progress.thread)
        self.unchanged()

    def test_progress_never_leaks_into_json_nonterminal_or_agent_output(self):
        class Terminal(io.StringIO):
            def isatty(self): return True
        for options in [{'as_json': True}, {'render': False}, {}]:
            terminal = Terminal() if options else io.StringIO()
            output = io.StringIO()
            with redirect_stderr(terminal), redirect_stdout(output), \
                    patch.object(control, 'isolated_delay_config', self.api):
                control.delay_summary(**options)
            self.assertEqual(terminal.getvalue(), '')
            self.assertNotIn('\r', output.getvalue())
            if options.get('as_json'):
                self.assertEqual(json.loads(output.getvalue())[0]['available'], 2)
        self.unchanged()

    def test_progress_stops_and_clears_on_interrupt(self):
        terminal = io.StringIO()
        with redirect_stderr(terminal), redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                with control._DelayProgress(force=True, configs=True) as progress:
                    with patch.object(control, 'delay', side_effect=KeyboardInterrupt):
                        control.delay_summary(_progress=progress)
            self.assertIsNone(progress.thread)
        self.assertTrue(terminal.getvalue().endswith('\r\033[2K'))
        self.assertNotIn('100%', terminal.getvalue())
        self.unchanged()

    def test_cli_forwards_terminal_progress_over_ssh_but_not_for_captures(self):
        for target in [None, 'user@host']:
            for capture, as_json in [(False, False), (True, False), (False, True)]:
                argv = ([target] if target else []) + ['test'] + (['--json'] if as_json else [])
                args = cli.build_parser().parse_args(argv)
                from unittest.mock import Mock
                ssh = Mock() if target else None
                with patch.object(cli.sys.stderr, 'isatty', return_value=True), patch.object(cli, 'run') as run:
                    cli.manage(args, ssh, capture=capture)
                call = ssh.action.call_args if ssh else run.call_args
                arguments = call.args if ssh else call.args[0]
                self.assertEqual('--progress' in arguments, not capture and not as_json)

    def test_config_missing_uncached_or_conflicting_selectors_fail_before_start(self):
        manager = subs.Manager(control)
        manager.registry['items'].append({'id': 'b' * 32, 'name': 'uncached', 'kind': 'subscription'})
        manager.save()
        with patch.object(control.subprocess, 'Popen') as start:
            for options in [{'config': 'missing'}, {'config': 'uncached'}, {'config': 'feiniao', 'node': 'A'}]:
                with self.subTest(options=options), self.assertRaises(control.InstallError):
                    control.delay(render=False, **options)
            start.assert_not_called()

    def test_cli_and_agent_carry_config_selector_locally_and_over_ssh(self):
        for argv in [['test', 'feiniao'], ['test', '--config', 'feiniao'],
                     ['user@host', 'test', '--config', 'feiniao']]:
            args = cli.normalize_command(cli.build_parser().parse_args(argv))
            options, _ = cli.management_options(args)
            selector = '--name=feiniao' if argv == ['test', 'feiniao'] else '--config=feiniao'
            self.assertIn(selector, options)
            if '--config' in argv:
                operation, parameters = domino_agent.command_request(args)
                self.assertEqual((operation, parameters['config']), ('delay.test', 'feiniao'))

    def test_temp_process_cleanup_on_interrupt_and_private_startup_failure(self):
        def start(command, **kwargs):
            data = Path(command[command.index('-d') + 1])
            self.temporary_data = data
            profile = json.loads((data / 'config.json').read_text())
            self.assertEqual(profile['mixed-port'], 0)
            self.assertEqual(profile['rules'], ['MATCH,DIRECT'])
            self.assertFalse(profile['tun']['enable'])
            self.assertFalse(profile['dns']['enable'])
            self.assertNotEqual(profile['external-controller'], '127.0.0.1:19091')
            return process
        from unittest.mock import MagicMock
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(control.subprocess, 'Popen', side_effect=start), \
                patch.object(control, 'controller', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                with control.isolated_delay_config('feiniao'):
                    self.fail('not ready')
        process.terminate.assert_called_once()
        self.assertFalse(self.temporary_data.exists())
        process.reset_mock(); process.poll.return_value = 1
        with patch.object(control.subprocess, 'Popen', side_effect=start):
            with self.assertRaises(control.InstallError) as caught:
                with control.isolated_delay_config('feiniao'):
                    self.fail('core failed')
        self.assertEqual(caught.exception.code, 'DELAY_CORE_FAILED')
        self.assertFalse(self.temporary_data.exists())
        self.unchanged()

    @unittest.skipUnless(CORE.is_file(), 'requires disposable Mihomo')
    def test_real_disposable_core_exposes_provider_nodes_and_cleans_up(self):
        shutil.copy2(CORE, self.app / 'mihomo')
        self.before = {str(p): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}
        manager = subs.Manager(control)
        item = manager.find('feiniao')
        cached = manager.cached(item)
        raw = dict(self.raw, proxies=[], **{'proxy-providers': {
            'pool': {'type': 'http', 'url': 'https://example.invalid/DO-NOT-DOWNLOAD', 'path': 'pool.json'}},
            'proxy-groups': [{'name': 'pool', 'type': 'select', 'use': ['pool']}]})
        (cached / 'pool.json').write_text(json.dumps({'proxies': self.raw['proxies']}))
        (cached / 'config.json').write_text(json.dumps(raw))
        with patch.object(control.subprocess, 'Popen', wraps=REAL_POPEN) as start:
            with control.isolated_delay_config('feiniao') as api:
                live = control.proxy_inventory(api('/proxies')['proxies'], api=api)
                self.assertIn('A', live); self.assertIn('B', live)
                command = start.call_args.args[0]
                data = Path(command[command.index('-d') + 1])
                profile = json.loads((data / 'config.json').read_text())
                self.assertEqual(profile['proxy-providers']['pool']['type'], 'file')
                self.assertNotIn('url', profile['proxy-providers']['pool'])
                self.assertFalse(profile['proxy-providers']['pool']['health-check']['enable'])
        self.assertFalse(data.exists())
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
