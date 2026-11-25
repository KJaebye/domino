import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import domino_tui as ui

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class TuiModelTests(unittest.TestCase):
    def test_workspace_refresh_event_is_created_inside_application_loop(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        async def execute(*args, **kwargs):
            return '{}'
        with create_pipe_input() as pipe:
            workspace = ui.Workspace('localhost', execute, 'test', input=pipe, output=DummyOutput())
            self.assertIsNone(workspace._refresh)
            async def finish():
                # Let poll reach its Event.wait before checking loop ownership.
                await asyncio.sleep(.1)
                self.assertIsNotNone(workspace._refresh)
                self.assertIs(workspace.refresh._loop, asyncio.get_running_loop())
                workspace.app.exit()
            with patch.object(workspace, 'animate', finish):
                workspace.run()

    def test_captured_command_colors_and_emphasis_reach_transcript_fragments(self):
        state=ui.State('localhost')
        state.append('info','\x1b[1;36mDomino\x1b[0m\n\x1b[2m入口出网\x1b[0m  \x1b[32m可用\x1b[0m\n\x1b[31m失败\x1b[0m',ansi=True)
        workspace=object.__new__(ui.Workspace)
        workspace.state=state
        fragments=workspace.transcript_text()
        self.assertTrue(any('ansicyan' in style and 'bold' in style and text=='Domino' for style,text in fragments))
        self.assertTrue(any('dim' in style and text=='入口出网' for style,text in fragments))
        self.assertTrue(any('ansigreen' in style and text=='可用' for style,text in fragments))
        self.assertTrue(any('ansired' in style and text=='失败' for style,text in fragments))
        self.assertEqual([str(text) for _,text in state.events],['Domino','入口出网  可用','失败'])
        self.assertNotIn('\x1b',str(state.events))

    def test_config_delay_summary_is_not_treated_as_node_delay_data(self):
        workspace=object.__new__(ui.Workspace)
        workspace.state=ui.State('localhost')
        workspace.delay_result(json.dumps([
            {'name':'feiniao','status':'tested','total':71,'available':60,'unavailable':11},
            {'name':'pending','status':'uncached','total':None,'available':None,'unavailable':None,'message':'尚未缓存'}]))
        text=str(workspace.state.events)
        self.assertIn('71 节点',text)
        self.assertIn('60 可用',text)
        self.assertIn('11 超时/不可用',text)
        self.assertIn('尚未缓存',text)
        self.assertEqual(workspace.state.delays,{})

    def test_command_style_parser_discards_other_terminal_controls(self):
        lines=ui.command_lines('\x1b[2J\x1b]0;PRIVATE-TITLE\x07\x01raw\x02\x1b[32m可用\x1b[0m')
        text=''.join(lines)
        self.assertEqual(text,'raw可用')
        self.assertNotIn('[ZeroWidthEscape]',str(lines[0].fragments))

    def test_commands_preserve_quoted_node_names_and_reject_unknown_operations(self):
        self.assertEqual(ui.parse_command('/test --node "US A"'), ('/test', ['--node', 'US A']))
        with self.assertRaises(ValueError): ui.parse_command('/log-level info')
        self.assertEqual(ui.parse_command('/delay'), ('/test', []))
        self.assertEqual(ui.parse_command('mode rule'), ('/mode', ['rule']))
        self.assertEqual(ui.parse_command('exit'),('/exit',[]))
        self.assertEqual(ui.parse_command('/scan --source "配置 A.yaml"'),('/scan',['--source','配置 A.yaml']))
        self.assertIn('/scan',dict(ui.COMMANDS))
        self.assertIn('/list',dict(ui.COMMANDS))
        with self.assertRaises(ValueError):
            ui.parse_command('/subs')
        with self.assertRaises(ValueError):
            ui.parse_command('/shell rm -rf anything')

    def test_panel_search_navigation_and_empty_results(self):
        panel = ui.Panel('nodes', [{'label': 'US A', 'value': 'a'}, {'label': '香港 B', 'value': 'b'}], None)
        panel.move(1)
        self.assertEqual(panel.selected()['value'], 'b')
        panel.query = 'us'
        panel.move(1)
        self.assertEqual(panel.selected()['value'], 'a')
        panel.query = 'missing'
        self.assertIsNone(panel.selected())

    def test_live_rates_handle_counter_reset_and_output_escapes(self):
        state = ui.State('localhost')
        state.update({'upload_total': 100, 'download_total': 200}, now=10)
        state.update({'upload_total': 300, 'download_total': 600}, now=12)
        self.assertEqual((state.up, state.down), (100, 200))
        state.update({'upload_total': 0, 'download_total': 0}, now=14)
        self.assertEqual((state.up, state.down), (None, None))
        self.assertNotIn('\x1b', ui.clean('\x1b[31mnode'))

    def test_small_rates_remain_visible_and_failure_is_not_a_fake_zero(self):
        self.assertEqual(ui.format_bytes(24,True),'24 B/s')
        self.assertEqual(ui.format_bytes(.5,True),'0.50 B/s')
        self.assertEqual(ui.format_bytes(4096),'4.0 KiB')
        state=ui.State('localhost')
        state.update({'upload_total':100,'download_total':200},now=1)
        self.assertIsNone(state.up)
        state.update({'upload_total':110,'download_total':220},now=3)
        self.assertEqual((state.up,state.down),(5,10))
        state.stale('unavailable')
        self.assertIsNone(state.up)
        self.assertIsNone(state.down)
        state.update({'upload_total':120,'download_total':240},now=10)
        self.assertIsNone(state.up)

    def test_traffic_scope_explains_clash_and_domino_port_mismatch(self):
        notice=ui.traffic_notice({'proxy_port':17897,'system_proxy':{'routing':'other','ports':[7897]}})
        self.assertIn('17897',notice)
        self.assertIn('7897',notice)
        self.assertIn('其他代理',notice)


class TuiTransportTests(unittest.TestCase):
    def test_public_log_and_test_commands_map_to_backend_actions(self):
        import domino_cli as cli
        for remote in [False, True]:
            for command, backend in [(['log', '--set', 'info'], 'log-level'), (['test', '--json'], 'delay')]:
                args = cli.build_parser().parse_args(['ui'])
                ssh = Mock() if remote else None
                if ssh: ssh.action_argv.return_value = ['ssh-command']
                process = Mock(returncode=0)
                process.communicate = AsyncMock(return_value=(b'{}', b''))
                spawn = AsyncMock(return_value=process)
                def run(target, execute, version):
                    asyncio.run(execute(command, capture=True))
                with patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                        patch.object(cli.asyncio, 'create_subprocess_exec', spawn), patch.object(ui, 'run', side_effect=run):
                    cli.terminal_ui(args, ssh)
                if remote:
                    self.assertEqual(ssh.action_argv.call_args.args[0], backend)
                else:
                    self.assertEqual(spawn.call_args.args[2], backend)

    def test_scan_reuses_current_local_or_ssh_transport_and_terminal_width(self):
        import domino_cli as cli
        for remote in [False,True]:
            args=cli.build_parser().parse_args(['ui','alice@host' if remote else 'localhost'])
            ssh=Mock() if remote else None
            if ssh: ssh.action_argv.return_value=['ssh-scan-command']
            process=Mock(returncode=0)
            process.communicate=AsyncMock(return_value=(b'Domino scan output',b''))
            spawn=AsyncMock(return_value=process)
            def run(target,execute,version):
                self.assertEqual(target,args.target)
                self.assertEqual(asyncio.run(execute(['scan'],capture=True)),'Domino scan output')
            with self.subTest(remote=remote), patch.object(cli.sys.stdin,'isatty',return_value=True), \
                    patch.object(cli.shutil,'get_terminal_size',return_value=os.terminal_size((80,24))), \
                    patch.object(cli.asyncio,'create_subprocess_exec',spawn), patch.object(ui,'run',side_effect=run):
                cli.terminal_ui(args,ssh)
            if remote:
                color=[] if 'NO_COLOR' in os.environ else ['--color']
                ssh.action_argv.assert_called_once_with('scan','--columns','76',*color,tty=False)
                self.assertEqual(spawn.call_args.args,('ssh-scan-command',))
            else:
                color=[] if 'NO_COLOR' in os.environ else ['--color']
                self.assertEqual(spawn.call_args.args,(cli.sys.executable,str(cli.REMOTE_SCRIPT),'scan','--columns','76',*color))

    def test_json_and_log_capture_do_not_request_human_color_codes(self):
        import domino_cli as cli
        args=cli.build_parser().parse_args(['ui'])
        process=Mock(returncode=0)
        process.communicate=AsyncMock(return_value=(b'{}',b''))
        spawn=AsyncMock(return_value=process)
        def run(target,execute,version):
            for arguments in [['scan','--json'],['status','localhost','--json'],['logs','localhost']]:
                asyncio.run(execute(arguments,capture=True))
        with patch.object(cli.sys.stdin,'isatty',return_value=True), \
                patch.object(cli.asyncio,'create_subprocess_exec',spawn), patch.object(ui,'run',side_effect=run):
            cli.terminal_ui(args)
        self.assertEqual(spawn.call_count,3)
        for call in spawn.call_args_list:
            self.assertNotIn('--color',call.args)

    def test_backend_forces_colors_for_ui_but_keeps_plain_and_json_output_clean(self):
        from contextlib import redirect_stdout
        import io
        import domino_cli as cli
        import install_domino as backend
        for options,no_color,colored in [(['--color'],False,True),([],False,False),
                                         (['--color','--json'],False,False),(['--color'],True,False)]:
            capture=io.StringIO()
            with self.subTest(options=options,no_color=no_color), patch.dict(os.environ,{'TERM':'xterm-256color'}), \
                    patch.object(cli,'collect_sources',return_value={'sources':[]}), redirect_stdout(capture):
                os.environ.pop('NO_COLOR',None)
                if no_color: os.environ['NO_COLOR']='1'
                self.assertEqual(backend.main(['scan',*options]),0)
            self.assertEqual('\x1b[' in capture.getvalue(),colored)
            if '--json' in options: self.assertEqual(json.loads(capture.getvalue()),{'sources':[]})

    def test_failed_source_check_still_shows_results_in_the_workspace(self):
        import domino_cli as cli
        args=cli.build_parser().parse_args(['ui'])
        process=Mock(returncode=3)
        process.communicate=AsyncMock(return_value=('入口出网 检查未通过'.encode(),b''))
        def run(target,execute,version):
            result=asyncio.run(execute(['scan','--source','config.yaml'],capture=True))
            self.assertIn('检查未通过',result)
        with patch.object(cli.sys.stdin,'isatty',return_value=True), \
                patch.object(cli.asyncio,'create_subprocess_exec',AsyncMock(return_value=process)), \
                patch.object(ui,'run',side_effect=run):
            cli.terminal_ui(args)


class TuiInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ui.load_toolkit()
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        self.context = create_pipe_input()
        self.pipe = self.context.__enter__()
        self.calls = []
        self.group = {'name': '出口', 'type': 'Selector', 'current': 'A', 'selectable': True, 'choices': ['A', 'B']}
        self.status_wait = asyncio.Event()
        async def execute(args, capture=False, timeout=75):
            self.calls.append(args)
            command = args[0] if args[0] in ['overview','catch-options'] else args[1]
            if command == 'overview':
                return json.dumps({'installed': True, 'active': True, 'reachable': True, 'groups': [self.group], 'mode': 'rule', 'node_count': 2})
            if command == 'nodes':
                return json.dumps({'groups': [self.group]})
            if command == 'list' and args[-1] == '--json':
                return json.dumps({'current_source':'原有配置', 'configs':[
                    {'name':'机场一', 'kind':'subscription', 'active':False, 'node_count':2, 'updated_at':None}]})
            if command=='catch-options':return json.dumps([{'name':'机场一','path':'/fixture/profile A.yaml'}])
            if command == 'status':
                self.status_wait.set()
                await asyncio.sleep(30)
            if command == 'test':
                return json.dumps([{'name':'A','delay_ms':42,'ok':True}])
            if command == 'scan':
                return '\n\x1b[1;36mDomino\x1b[0m  ·  部署来源\n  2 个来源 · 2 个出网可用\n\n  来源      Domino · 默认\n  入口出网  \x1b[32m可用\x1b[0m\n\n  来源      Clash Verge\n  配置状态  兼容\n'
            return '完成'
        self.workspace = ui.Workspace('localhost', execute, 'test', input=self.pipe, output=DummyOutput())
        self.task = asyncio.create_task(self.workspace.app.run_async(
            pre_run=lambda:self.workspace.app.create_background_task(self.workspace.poll())))
        await self.wait_for(lambda: bool(self.workspace.state.snapshot))

    async def asyncTearDown(self):
        if not self.task.done():
            self.workspace.app.exit()
        await asyncio.wait_for(self.task, 3)
        self.context.__exit__(None, None, None)

    async def wait_for(self, predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(.02)
        self.fail('UI condition did not become true')

    async def test_slash_nodes_filter_and_enter_use_existing_management_command(self):
        self.pipe.send_text('/nodes\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.pipe.send_text('出口\r')
        await self.wait_for(lambda:self.workspace.state.panel and self.workspace.state.panel.kind == 'nodes')
        self.pipe.send_text('B\r')
        await self.wait_for(lambda:any(args[1]=='select' for args in self.calls))
        self.assertIn(['localhost','select','--group','出口','--node','B'], self.calls)
        self.assertIsNone(self.workspace.state.panel)

    async def test_delay_shortcuts_use_current_target(self):
        self.workspace.state.target='lab-alias'
        for command,expected in [('/test 自动选择',['lab-alias','test','自动选择','--json']),
                                  ('/test --all',['lab-alias','test','--all','--json'])]:
            self.pipe.send_text(command+'\r')
            await self.wait_for(lambda:expected in self.calls and not self.workspace.state.busy)
            import domino_cli as cli
            args=cli.normalize_command(cli.build_parser().parse_args(expected))
            self.assertEqual(args.target,'lab-alias')

    async def test_scan_uses_session_transport_and_shows_shared_cli_output(self):
        self.workspace.state.target='lab-alias'
        self.pipe.send_text('/scan\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.assertFalse(any(v[:2]==['lab-alias','scan'] for v in self.calls))
        self.pipe.send_text('全部\r')
        await self.wait_for(lambda:['lab-alias','scan'] in self.calls and not self.workspace.state.busy)
        self.assertIn('2 个来源',str(self.workspace.state.events))
        self.assertIn('Clash Verge',str(self.workspace.state.events))
        self.assertTrue(any('ansigreen' in style and value=='可用' for style,value in self.workspace.transcript_text()))
        self.assertNotIn('\x1b',str(self.workspace.state.events))
        self.assertFalse(self.workspace.job_mutates)
        self.pipe.send_text('/scan --source "配置 A.yaml"\r')
        await self.wait_for(lambda:['lab-alias','scan','--source','配置 A.yaml'] in self.calls and not self.workspace.state.busy)

    async def test_scan_rejects_unrecognized_arguments(self):
        self.pipe.send_text('/scan anything\r')
        await self.wait_for(lambda:any('用法：/scan' in value for _,value in self.workspace.state.events))
        self.assertFalse(any(args[1]=='scan' for args in self.calls))

    async def test_subscription_picker_updates_selected_subscription_through_cli(self):
        self.pipe.send_text('/list\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.pipe.send_text('机场一\r')
        await self.wait_for(lambda:self.workspace.config_focus=='actions')
        self.assertTrue(self.workspace.config_open())
        self.pipe.send_bytes(b'\x1b[D')
        self.pipe.send_text('\r')
        await self.wait_for(lambda:['localhost','update','--','机场一'] in self.calls)

    async def test_inline_subscription_url_is_redacted_from_transcript(self):
        import domino_cli as cli
        for action,field in [('add','add'),('set-url','set_url')]:
            self.pipe.send_text('/'+action+' A --url "https://example.test/sub?token=PRIVATE-TOKEN"\r')
            await self.wait_for(lambda:any(args[:2]==['localhost',action] for args in self.calls) and not self.workspace.state.busy)
            self.assertNotIn('PRIVATE-TOKEN',str(self.workspace.state.events))
            self.assertIn('***',str(self.workspace.state.events))
            arguments=next(v for v in self.calls if v[:2]==['localhost',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(getattr(args,field),'A')
            self.assertEqual(args.target,'localhost')
            self.assertEqual(args.url,'https://example.test/sub?token=PRIVATE-TOKEN')

    async def test_short_subscription_commands_parse_with_the_current_target(self):
        import domino_cli as cli
        commands=[('/switch "-机场 A"','switch','use','-机场 A'),
                  ('/update all','update','update_all',True),
                  ('/rename "机场 A" "备用 B"','rename','new_name','备用 B'),
                  ('/remove "备用 B"','remove','remove','备用 B')]
        for text,action,field,value in commands:
            self.pipe.send_text(text+'\r')
            await self.wait_for(lambda:any(v[:2]==['localhost',action] for v in self.calls) and not self.workspace.state.busy)
            arguments=next(v for v in self.calls if v[:2]==['localhost',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target,'localhost')
            self.assertEqual(getattr(args,field),value)

    async def test_updating_selected_subscription_named_all_is_not_a_bulk_update(self):
        self.workspace.config_panel({'current_source':'原有配置','configs':[
            {'name':'all','kind':'subscription','active':False,'node_count':1,'updated_at':None}]})
        panel=self.workspace.state.panel
        self.workspace.config_manage('update')
        await self.wait_for(lambda:['localhost','list','--update','all'] in self.calls)
        self.assertFalse(any(v[:2]==['localhost','update'] for v in self.calls))

    async def test_rule_add_uses_the_current_target_and_preserves_rule_text(self):
        import domino_cli as cli
        rule='DOMAIN-SUFFIX,example.test,出口'
        self.pipe.send_text('/rules add "'+rule+'"\r')
        await self.wait_for(lambda:any(v[1]=='rules' for v in self.calls) and not self.workspace.state.busy)
        arguments=next(v for v in self.calls if v[1]=='rules')
        args=cli.normalize_command(cli.build_parser().parse_args(arguments))
        self.assertEqual(args.add_rule,rule)
        self.assertEqual(args.target,'localhost')

    async def test_proxy_actions_use_the_same_cli_grammar_and_target(self):
        import domino_cli as cli
        for action in ['status','on','off']:
            self.pipe.send_text('/proxy '+action+'\r')
            await self.wait_for(lambda:any(v[1:3]==['proxy',action] for v in self.calls) and not self.workspace.state.busy)
            arguments=next(v for v in self.calls if v[1:3]==['proxy',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target,'localhost')
            self.assertEqual(args.set,action if action!='status' else None)

    async def test_shell_actions_use_current_target_without_parent_application(self):
        import domino_cli as cli
        for action in ['status', 'on', 'off']:
            self.pipe.send_text('/shell ' + action + '\r')
            await self.wait_for(lambda: any(v[1:3] == ['shell', action] for v in self.calls) and not self.workspace.state.busy)
            arguments = next(v for v in self.calls if v[1:3] == ['shell', action])
            args = cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target, 'localhost')
            self.assertEqual(args.set, action if action != 'status' else None)

    async def test_slow_operation_does_not_block_input_and_ctrl_c_cancels(self):
        self.pipe.send_text('/status\r')
        await asyncio.wait_for(self.status_wait.wait(), 2)
        self.pipe.send_text('/traffic --inline\r')
        await self.wait_for(lambda:any('底部每 2 秒刷新' in text for _,text in self.workspace.state.events))
        self.pipe.send_bytes(b'\x03')
        await self.wait_for(lambda:not self.workspace.state.busy)
        self.assertTrue(any('已中断' in text for _,text in self.workspace.state.events))

    async def test_escape_closes_panel_and_exit_does_not_stop_service(self):
        self.pipe.send_text('/mode\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.pipe.send_bytes(b'\x1b')
        await self.wait_for(lambda:self.workspace.state.panel is None)
        self.pipe.send_text('/exit\r')
        await asyncio.wait_for(self.task, 3)
        self.assertFalse(any(args[1]=='stop' for args in self.calls))

    async def test_plain_exit_from_input_keeps_service_running(self):
        self.pipe.send_text('exit\r')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[1]=='stop' for args in self.calls))

    async def test_ctrl_d_exits_even_with_unsubmitted_input(self):
        self.pipe.send_text('unfinished command')
        self.pipe.send_bytes(b'\x04')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[1]=='stop' for args in self.calls))

    async def test_ctrl_d_exits_from_node_filter_without_switching(self):
        self.workspace.nodes(self.group)
        self.pipe.send_text('B')
        self.pipe.send_bytes(b'\x04')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[1] in ['stop','select'] for args in self.calls))

    async def test_plain_exit_from_picker_is_not_treated_as_node_filter(self):
        self.workspace.nodes(self.group)
        self.pipe.send_text('exit\r')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[1] in ['stop','select'] for args in self.calls))

    async def test_keyboard_selection_scrolls_beyond_first_page(self):
        self.group['choices'] = [f'Node {i:02d}' for i in range(20)]
        self.workspace.nodes(self.group)
        self.pipe.send_bytes(b'\x1b[B' * 10)
        await self.wait_for(lambda:self.workspace.state.panel.index == 10)
        await asyncio.sleep(.1)
        info = self.workspace.picker_window.render_info
        self.assertIn(10, info.displayed_lines)

    async def test_setting_commit_is_not_killed_by_ctrl_c(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.workspace.execute
        async def execute(args, **kwargs):
            if args[1]=='mode':
                entered.set()
                await release.wait()
                return '已保存'
            return await original(args, **kwargs)
        self.workspace.execute = execute
        self.pipe.send_text('/mode global\r')
        await asyncio.wait_for(entered.wait(), 2)
        self.pipe.send_bytes(b'\x03')
        await self.wait_for(lambda:any('此阶段不强行中断' in text for _,text in self.workspace.state.events))
        self.assertFalse(self.workspace.job.done())
        release.set()
        await self.wait_for(lambda:not self.workspace.state.busy)

    async def test_ctrl_t_tests_highlighted_node_without_switching_it(self):
        original=self.workspace.execute
        async def execute(args,**kwargs):
            if args[1]=='test':
                self.calls.append(args)
                return json.dumps([{'name':'B','delay_ms':42,'ok':True}])
            return await original(args,**kwargs)
        self.workspace.execute=execute
        self.workspace.nodes(self.group)
        self.pipe.send_bytes(b'\x1b[B\x14')
        await self.wait_for(lambda:self.workspace.state.delays.get('B')==42)
        self.assertIn(['localhost','test','--node','B','--json'],self.calls)
        self.assertFalse(any(args[1]=='select' for args in self.calls))
        self.assertIsNotNone(self.workspace.state.panel)

    async def test_compact_footer_keeps_routing_visible_and_traffic_command_shows_details(self):
        self.workspace.state.update({'reachable':True,'stats_available':True,'proxy_port':17897,
            'upload_total':1024,'download_total':4096,'system_proxy':{'routing':'other','ports':[7897]}},now=10)
        text=''.join(fragment[1] for fragment in self.workspace.footer())
        self.assertIn('7897',text)
        self.assertIn('17897',''.join(fragment[1] for fragment in self.workspace.header()))
        self.workspace.dispatch('/traffic --inline')
        frame=''.join(text for _,text in self.workspace.traffic_text())
        self.assertIn('1.0 KiB',frame)
        self.assertIn('4.0 KiB',frame)
        self.assertIn('仅统计 Domino :17897',str(self.workspace.state.events))

    async def test_select_keyword_filters_candidates_without_an_early_switch(self):
        self.group['choices']=['[HY2]美国BGP002','[Vless]香港BGP002']
        self.workspace.state.snapshot['groups']=[self.group]
        self.pipe.send_text('/select BGP002\r')
        await self.wait_for(lambda:self.workspace.state.panel and self.workspace.state.panel.kind=='select-matches')
        self.assertFalse(any(v[1]=='select' for v in self.calls if v[0]!='overview'))
        self.pipe.send_text('美国\r')
        await self.wait_for(lambda:any(v[1:2]==['select'] for v in self.calls))
        self.assertIn(['localhost','select','--group','出口','--node','[HY2]美国BGP002'],self.calls)

    async def test_catch_all_retains_the_current_target_and_confirmation_path(self):
        self.workspace.state.target='lab-alias'
        self.pipe.send_text('/catch all\r')
        await self.wait_for(lambda:['lab-alias','catch','all'] in self.calls and not self.workspace.state.busy)
        self.assertFalse(any('--yes' in v for v in self.calls))
        self.assertTrue(any('捕获流程已结束' in text for _,text in self.workspace.state.events))

    async def test_nodes_and_log_picker_show_current_configuration_and_choices(self):
        self.workspace.state.snapshot.update(subscription='xlink',log_level='error')
        self.workspace.dispatch('/nodes')
        self.assertIn('当前配置  xlink',str(self.workspace.state.events))
        self.assertIn('出口 → A',str(self.workspace.state.events))
        self.workspace.close_panel();self.workspace.dispatch('/log')
        selected=[v['value'] for v in self.workspace.state.panel.items if v.get('current')]
        self.assertEqual(selected,['error'])
        self.assertEqual(len(self.workspace.state.panel.items),5)

    async def test_traffic_panel_is_live_complete_and_closes_with_escape(self):
        self.workspace.state.update({'installed':True,'active':True,'reachable':True,'stats_available':True,
            'upload_total':100,'download_total':200,'memory':1048576,'connections':3},now=10)
        self.workspace.dispatch('/traffic --inline')
        self.assertTrue(self.workspace.state.traffic_open)
        self.workspace.state.update({'installed':True,'active':True,'reachable':True,'stats_available':True,
            'upload_total':2148,'download_total':4296,'memory':1048576,'connections':4},now=12)
        text=''.join(value for _,value in self.workspace.traffic_text())
        for label in ['累计上传','累计下载','内核内存','上传近期趋势','下载近期趋势','峰值','1.0 MiB']:
            self.assertIn(label,text)
        self.workspace.state.stale('fixture unavailable')
        self.assertIn('正在重试',''.join(value for _,value in self.workspace.traffic_text()))
        self.assertEqual(self.workspace.state.traffic_history,[])
        self.pipe.send_bytes(b'\x1b')
        await self.wait_for(lambda:not self.workspace.state.traffic_open)
        self.assertFalse(self.task.done())

    async def test_test_progress_and_current_node_markers_arrive_before_completion(self):
        release=asyncio.Event();original=self.workspace.execute
        async def execute(args,capture=False,timeout=75,on_progress=None):
            if args[0]!='overview' and args[1]=='test':
                self.calls.append(args)
                on_progress('正在检测 [====----] 50% · 节点 1/2 · 可用 1')
                await release.wait()
                return json.dumps({'configuration':'xlink','usage':{'active':True,'known':True,'nodes':['B'],'paths':['出口 → B']},
                                   'results':[{'name':'A','delay_ms':10,'ok':True},{'name':'B','delay_ms':20,'ok':True}]})
            return await original(args,capture=capture,timeout=timeout)
        self.workspace.execute=execute
        self.pipe.send_text('/test xlink\r')
        await self.wait_for(lambda:'节点 1/2' in self.workspace.state.progress)
        self.assertIn('节点 1/2',''.join(text for _,text in self.workspace.footer()))
        self.assertNotIn('B',self.workspace.state.delays)
        release.set();await self.wait_for(lambda:self.workspace.state.delays.get('B')==20)
        text=str(self.workspace.state.events)
        self.assertIn('● 当前配置  xlink',text);self.assertIn('● B',text)
        self.assertNotIn('● A',text);self.assertEqual(self.workspace.state.progress,'')

    async def test_config_actions_include_rename_and_single_configuration_test(self):
        self.workspace.config_panel({'active':'xlink','configs':[{'name':'all','kind':'snapshot','active':False,'node_count':2}]})
        actions=dict(self.workspace.config_actions())
        self.assertIn('rename',actions);self.assertIn('test',actions)
        self.workspace.config_manage('test')
        await self.wait_for(lambda:['localhost','test','--config','all','--json'] in self.calls)

    async def test_cancelling_a_rename_prompt_returns_to_ui_without_submitting(self):
        session=Mock();session.prompt_async=AsyncMock(side_effect=KeyboardInterrupt())
        with patch('prompt_toolkit.PromptSession',return_value=session):
            self.workspace.queue('重命名配置','rename','xlink',foreground=True,prompt='新配置名称：')
            await self.wait_for(lambda:not self.workspace.state.busy)
        self.assertFalse(self.task.done())
        self.assertFalse(any(v[1:2]==['rename'] for v in self.calls))
        self.assertTrue(any('已取消操作' in value for _,value in self.workspace.state.events))

    async def test_shell_enter_opens_actions_and_only_selection_changes_policy(self):
        self.workspace.state.target='lab-alias'
        for action in ['on','off','status']:
            self.pipe.send_text('/shell\r')
            await self.wait_for(lambda:self.workspace.state.panel is not None)
            self.assertEqual([v['value'] for v in self.workspace.state.panel.items],['/shell on','/shell off','/shell status'])
            before=len(self.calls)
            await asyncio.sleep(.03)
            self.assertEqual(len(self.calls),before)
            self.pipe.send_text(action+'\r')
            await self.wait_for(lambda:['lab-alias','shell',action] in self.calls and not self.workspace.state.busy)
        self.assertFalse(any('--apply' in value for value in self.calls))

    async def test_mouse_click_selects_a_menu_item_and_escape_submits_nothing(self):
        from types import SimpleNamespace
        from prompt_toolkit.mouse_events import MouseButton,MouseEventType
        self.workspace.dispatch('/shell')
        self.workspace.panel_text()[2][2](SimpleNamespace(button=MouseButton.LEFT,event_type=MouseEventType.MOUSE_UP))
        await self.wait_for(lambda:['localhost','shell','status'] in self.calls and not self.workspace.state.busy)
        self.workspace.dispatch('/shell')
        self.pipe.send_bytes(b'\x1b')
        await self.wait_for(lambda:self.workspace.state.panel is None)
        self.assertFalse(any(v[1:3] in [['shell','on'],['shell','off']] for v in self.calls))

    async def test_bare_configuration_commands_choose_a_configuration_before_submitting(self):
        import domino_cli as cli
        for action in ['switch','update','remove','rename','set-url']:
            self.pipe.send_text('/'+action+'\r')
            await self.wait_for(lambda:self.workspace.state.panel is not None and not self.workspace.state.busy)
            self.assertTrue(self.workspace.config_open())
            self.assertFalse(any(v[1:2]==[action] for v in self.calls))
            self.workspace.close_panel()
        self.workspace.dispatch('/switch')
        await self.wait_for(lambda:self.workspace.state.panel is not None and not self.workspace.state.busy)
        self.pipe.send_text('机场一\r')
        await self.wait_for(lambda:self.workspace.config_focus=='actions')
        self.pipe.send_text('\r')
        await self.wait_for(lambda:['localhost','switch','--','机场一'] in self.calls)
        command=cli.normalize_command(cli.build_parser().parse_args(next(v for v in self.calls if v[1:2]==['switch'])))
        self.assertEqual(command.use,'机场一')

    async def test_config_manager_protects_active_removal_and_offers_configuration_updates(self):
        self.workspace.config_panel({'configs':[{'name':'active','kind':'snapshot','active':True},
                           {'name':'all','kind':'subscription','active':False}]})
        self.assertNotIn('remove',dict(self.workspace.config_actions()))
        self.assertEqual(dict(self.workspace.config_actions())['update'],'更新配置')
        self.assertNotIn('refresh',dict(self.workspace.config_actions()))
        self.workspace.state.panel.index=1
        self.assertIn('remove',dict(self.workspace.config_actions()))
        self.workspace.config_manage('update')
        await self.wait_for(lambda:['localhost','list','--update','all'] in self.calls)

    async def test_test_picker_supports_all_configuration_and_single_node_without_switching(self):
        self.pipe.send_text('/test\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None and not self.workspace.state.busy)
        self.assertFalse(any(v[1:2]==['test'] for v in self.calls))
        self.pipe.send_text('全部\r')
        await self.wait_for(lambda:['localhost','test','--all','--json'] in self.calls and not self.workspace.state.busy)
        self.workspace.configuration_choices({'configs':[{'name':'all','active':False,'kind':'snapshot'}]},'test')
        self.pipe.send_text('all\r')
        await self.wait_for(lambda:['localhost','test','--config','all','--json'] in self.calls and not self.workspace.state.busy)
        self.workspace.test_node_picker()
        self.pipe.send_text('出口\r')
        await self.wait_for(lambda:self.workspace.state.panel and self.workspace.state.panel.kind=='nodes')
        self.pipe.send_text('B\r')
        await self.wait_for(lambda:['localhost','test','--node','B','--json'] in self.calls)
        self.assertFalse(any(v[1:2]==['select'] for v in self.calls))

    async def test_catch_and_traffic_offer_choices_before_starting(self):
        self.pipe.send_text('/catch\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.assertFalse(any(v[1:2]==['catch'] for v in self.calls))
        self.pipe.send_text('全部\r')
        await self.wait_for(lambda:['localhost','catch','all'] in self.calls and not self.workspace.state.busy)
        self.assertFalse(any('--yes' in v for v in self.calls))
        self.pipe.send_text('/traffic\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.assertFalse(self.workspace.state.traffic_open)
        self.pipe.send_text('内嵌\r')
        await self.wait_for(lambda:self.workspace.state.traffic_open)

    async def test_catch_source_picker_uses_current_target_and_retains_final_confirmation(self):
        self.workspace.state.target='lab-alias'
        self.pipe.send_text('/catch\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.pipe.send_text('一个\r')
        await self.wait_for(lambda:self.workspace.state.panel and self.workspace.state.panel.kind=='catch-sources' and not self.workspace.state.busy)
        self.assertIn(['catch-options','lab-alias'],self.calls)
        self.assertFalse(any(v[1:2]==['catch'] for v in self.calls))
        self.pipe.send_text('机场一\r')
        await self.wait_for(lambda:['lab-alias','catch','--source','/fixture/profile A.yaml'] in self.calls)
        self.assertFalse(any('--yes' in v for v in self.calls))

    async def test_providers_and_rule_removal_choose_kind_and_rule_before_writing(self):
        self.pipe.send_text('/providers\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.assertFalse(any(v[1:2]==['providers'] for v in self.calls))
        with patch.object(self.workspace,'queue') as queue:
            self.pipe.send_text('rule\r')
            await self.wait_for(lambda:queue.called)
            self.assertEqual(queue.call_args.args[:4],('读取集合','providers','--kind','rule'))
        self.workspace.rule_panel({'rules':['DOMAIN-SUFFIX,example.test,DIRECT']})
        self.assertFalse(any(v[1:2]==['rules'] for v in self.calls))
        self.pipe.send_text('example\r')
        await self.wait_for(lambda:['localhost','rules','--','remove','DOMAIN-SUFFIX,example.test,DIRECT'] in self.calls)

    async def test_connections_choose_an_id_and_dont_close_anything_on_open(self):
        self.pipe.send_text('/connections\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.assertFalse(any(v[1:2]==['connections'] for v in self.calls))
        self.workspace.connection_panel({'connections':[{'id':'fixture-id','host':'example.test','port':443,'network':'tcp'}]})
        self.pipe.send_text('example\r')
        await self.wait_for(lambda:['localhost','connections','--close','fixture-id'] in self.calls)

    def manager_fixture(self):
        import domino_cli as cli
        records=[{'name':'xlink','kind':'subscription','active':True,'node_count':32,'cached':True},
                 {'name':'feiniao','kind':'snapshot','active':False,'node_count':71,'cached':True}]
        def result():return {'active':next((v['name'] for v in records if v['active']),None),'configs':records}
        original=self.workspace.execute
        async def execute(args,capture=False,timeout=75):
            if args[0]=='overview':return await original(args,capture=capture,timeout=timeout)
            self.calls.append(args)
            if args[1]=='list':return json.dumps(result())
            command=cli.normalize_command(cli.build_parser().parse_args(args))
            if args[1]=='rename':next(v for v in records if v['name']==command.rename)['name']=command.new_name
            elif args[1]=='add':records.append({'name':command.add,'kind':'subscription','active':False,'node_count':None,'cached':False})
            elif args[1]=='remove':records[:]=[v for v in records if v['name']!=command.remove]
            elif args[1]=='switch':
                for v in records:v['active']=v['name']==command.use
            return '操作完成'
        self.workspace.execute=execute
        self.workspace.config_panel(json.loads(json.dumps(result())))
        return records

    async def test_unified_manager_keeps_list_visible_while_selecting_and_switching(self):
        self.manager_fixture()
        from types import SimpleNamespace
        from prompt_toolkit.mouse_events import MouseButton,MouseEventType
        self.workspace.panel_text()[1][2](SimpleNamespace(button=MouseButton.LEFT,event_type=MouseEventType.MOUSE_UP))
        self.assertTrue(self.workspace.config_open());self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'feiniao')
        self.assertFalse(any(v[1:2]==['switch'] for v in self.calls))
        self.pipe.send_text('\r')
        await self.wait_for(lambda:not self.workspace.state.busy and any(v[1:2]==['switch'] for v in self.calls))
        self.assertTrue(self.workspace.config_open())
        self.assertEqual(len(self.workspace.state.panel.items),2)
        self.assertTrue(self.workspace.state.panel.selected()['value']['active'])

    async def test_rename_is_inline_refreshes_list_and_preserves_the_renamed_selection(self):
        self.manager_fixture();self.workspace.state.panel.index=1
        self.workspace.config_manage('rename')
        self.assertTrue(self.workspace.config_open())
        self.assertIs(self.workspace.app.layout.current_control,self.workspace.form_input.control)
        self.pipe.send_text('备用 配置\r')
        await self.wait_for(lambda:not self.workspace.state.busy and self.workspace.config_form is None)
        self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'备用 配置')
        self.assertEqual(len(self.workspace.state.panel.items),2)
        self.assertIn(['localhost','rename','--','feiniao','备用 配置'],self.calls)
        self.assertTrue(self.workspace.config_open())

    async def test_inline_add_hides_subscription_and_never_puts_it_in_history(self):
        self.manager_fixture();self.workspace.config_manage('add')
        self.pipe.send_text('新增\r')
        await self.wait_for(lambda:self.workspace.config_form and self.workspace.config_form['fields'][0][0]=='url')
        self.assertFalse(any(v[1:2]==['add'] for v in self.calls))
        secret='https://example.test/sub?token=PRIVATE'
        self.pipe.send_text(secret+'\r')
        await self.wait_for(lambda:not self.workspace.state.busy and self.workspace.config_form is None)
        self.assertTrue(self.workspace.config_open());self.assertEqual(len(self.workspace.state.panel.items),3)
        self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'新增')
        self.assertNotIn('PRIVATE',str(self.workspace.state.events))
        self.assertNotIn('PRIVATE',str(self.workspace.input.buffer.history.get_strings()))
        self.assertEqual(self.workspace.form_input.buffer.history.get_strings(),[])
        self.assertEqual(self.workspace.form_input.text,'')

    async def test_inline_address_validation_and_cancel_leave_the_manager_unchanged(self):
        self.manager_fixture();self.workspace.config_manage('set-url')
        self.pipe.send_text('https://[INVALID\r')
        await self.wait_for(lambda:any('有效的 HTTPS' in v for _,v in self.workspace.state.events))
        self.assertIsNotNone(self.workspace.config_form)
        self.pipe.send_bytes(b'\x1b')
        await self.wait_for(lambda:self.workspace.config_form is None)
        self.assertTrue(self.workspace.config_open())
        self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'xlink')
        self.assertFalse(any(v[1:2]==['set-url'] for v in self.calls))

    async def test_update_configuration_fetches_selected_item_then_reloads_and_reports_success(self):
        records=self.manager_fixture();self.workspace.state.panel.index=1
        original=self.workspace.execute
        async def execute(args,**options):
            if args[1:2]==['update']:
                self.calls.append(args)
                records[1].update(kind='subscription',node_count=80)
                return 'updated'
            return await original(args,**options)
        self.workspace.execute=execute
        from types import SimpleNamespace
        from prompt_toolkit.mouse_events import MouseButton,MouseEventType
        fragments=self.workspace.config_toolbar()
        update=next(part for part in fragments if '更新配置' in part[1])
        update[2](SimpleNamespace(button=MouseButton.LEFT,event_type=MouseEventType.MOUSE_UP))
        await self.wait_for(lambda:not self.workspace.state.busy)
        self.assertIn(['localhost','update','--','feiniao'],self.calls)
        self.assertIn(['localhost','list','--json'],self.calls)
        self.assertTrue(self.workspace.config_open())
        selected=self.workspace.state.panel.selected()['value']
        self.assertEqual((selected['name'],selected['node_count']),('feiniao',80))
        self.assertIn('配置已更新：feiniao',str(self.workspace.state.events))
        self.assertNotIn('refresh',dict(self.workspace.config_actions()))

    async def test_failed_configuration_update_keeps_view_and_does_not_claim_success(self):
        self.manager_fixture();original=self.workspace.execute
        async def execute(args,**options):
            if args[1:2]==['update']:raise RuntimeError('订阅下载失败，保留原配置')
            return await original(args,**options)
        self.workspace.execute=execute
        self.workspace.config_manage('update')
        await self.wait_for(lambda:not self.workspace.state.busy)
        self.assertTrue(self.workspace.config_open())
        self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'xlink')
        events=str(self.workspace.state.events)
        self.assertIn('订阅下载失败',events)
        self.assertNotIn('配置已更新：',events)

    async def test_removing_an_inactive_configuration_refreshes_the_same_view(self):
        self.manager_fixture();self.workspace.state.panel.index=1
        self.workspace.config_manage('remove')
        await self.wait_for(lambda:not self.workspace.state.busy)
        self.assertTrue(self.workspace.config_open());self.assertEqual(len(self.workspace.state.panel.items),1)
        self.assertEqual(self.workspace.state.panel.selected()['value']['name'],'xlink')
        self.assertNotIn('remove',dict(self.workspace.config_actions()))

    async def test_failed_write_keeps_manager_open_and_refreshes_truthful_list(self):
        self.manager_fixture();original=self.workspace.execute
        async def execute(args,**options):
            if args[1:2]==['rename']:raise RuntimeError('合成写入失败')
            return await original(args,**options)
        self.workspace.execute=execute
        self.workspace.config_manage('rename');self.pipe.send_text('失败后的名称\r')
        await self.wait_for(lambda:not self.workspace.state.busy and self.workspace.config_form is None)
        self.assertTrue(self.workspace.config_open())
        self.assertEqual([v['value']['name'] for v in self.workspace.state.panel.items],['xlink','feiniao'])
        self.assertIn('合成写入失败',str(self.workspace.state.events))

    async def test_empty_manager_still_offers_add_and_cancel_does_not_write(self):
        self.workspace.config_panel({'configs':[]})
        self.assertIn('添加配置',''.join(v[1] for v in self.workspace.panel_text()))
        self.assertIn('add',dict(self.workspace.config_actions()))
        self.workspace.config_manage('add');self.pipe.send_text('未完成\r')
        await self.wait_for(lambda:self.workspace.config_form['fields'][0][0]=='url')
        self.pipe.send_bytes(b'\x03')
        await self.wait_for(lambda:self.workspace.config_form is None)
        self.assertTrue(self.workspace.config_open())
        self.assertFalse(any(v[1:2]==['add'] for v in self.calls))
