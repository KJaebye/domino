import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import domino_tui as ui


class TuiModelTests(unittest.TestCase):
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

    def test_command_style_parser_discards_other_terminal_controls(self):
        lines=ui.command_lines('\x1b[2J\x1b]0;PRIVATE-TITLE\x07\x01raw\x02\x1b[32m可用\x1b[0m')
        text=''.join(lines)
        self.assertEqual(text,'raw可用')
        self.assertNotIn('[ZeroWidthEscape]',str(lines[0].fragments))

    def test_commands_preserve_quoted_node_names_and_reject_unknown_operations(self):
        self.assertEqual(ui.parse_command('/delay --node "US A"'), ('/delay', ['--node', 'US A']))
        self.assertEqual(ui.parse_command('mode rule'), ('/mode', ['rule']))
        self.assertEqual(ui.parse_command('exit'),('/exit',[]))
        self.assertEqual(ui.parse_command('/scan --source "配置 A.yaml"'),('/scan',['--source','配置 A.yaml']))
        self.assertIn('/scan',dict(ui.COMMANDS))
        self.assertIn('/configs',dict(ui.COMMANDS))
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
        self.assertEqual((state.up, state.down), (0, 0))
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
            if args[0] == 'overview':
                return json.dumps({'installed': True, 'active': True, 'reachable': True, 'groups': [self.group], 'mode': 'rule', 'node_count': 2})
            if args[0] == 'nodes':
                return json.dumps({'groups': [self.group]})
            if args[0] == 'configs' and args[-1] == '--json':
                return json.dumps({'current_source':'原有配置', 'configs':[
                    {'name':'机场一', 'kind':'subscription', 'active':False, 'node_count':2, 'updated_at':None}]})
            if args[0] == 'status':
                self.status_wait.set()
                await asyncio.sleep(30)
            if args[0] == 'delay':
                return json.dumps([{'name':'A','delay_ms':42,'ok':True}])
            if args[0] == 'scan':
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
        await self.wait_for(lambda:any(args[0]=='select' for args in self.calls))
        self.assertIn(['select','localhost','--group','出口','--node','B'], self.calls)
        self.assertIsNone(self.workspace.state.panel)

    async def test_simple_delay_uses_current_target_and_no_arguments_tests_all(self):
        self.workspace.state.target='lab-alias'
        for command,expected in [('/delay 自动选择',['delay','自动选择','lab-alias','--json']),
                                  ('/delay',['delay','lab-alias','--all','--json'])]:
            self.pipe.send_text(command+'\r')
            await self.wait_for(lambda:expected in self.calls and not self.workspace.state.busy)
            import domino_cli as cli
            args=cli.normalize_command(cli.build_parser().parse_args(expected))
            self.assertEqual(args.target,'lab-alias')

    async def test_scan_uses_session_transport_and_shows_shared_cli_output(self):
        self.workspace.state.target='lab-alias'
        self.pipe.send_text('/scan\r')
        await self.wait_for(lambda:['scan'] in self.calls and not self.workspace.state.busy)
        self.assertIn('2 个来源',str(self.workspace.state.events))
        self.assertIn('Clash Verge',str(self.workspace.state.events))
        self.assertTrue(any('ansigreen' in style and value=='可用' for style,value in self.workspace.transcript_text()))
        self.assertNotIn('\x1b',str(self.workspace.state.events))
        self.assertFalse(self.workspace.job_mutates)
        self.pipe.send_text('/scan --source "配置 A.yaml"\r')
        await self.wait_for(lambda:['scan','--source','配置 A.yaml'] in self.calls and not self.workspace.state.busy)

    async def test_scan_rejects_unrecognized_arguments(self):
        self.pipe.send_text('/scan anything\r')
        await self.wait_for(lambda:any('用法：/scan' in value for _,value in self.workspace.state.events))
        self.assertFalse(any(args[0]=='scan' for args in self.calls))

    async def test_subscription_picker_updates_selected_subscription_through_cli(self):
        self.pipe.send_text('/configs\r')
        await self.wait_for(lambda:self.workspace.state.panel is not None)
        self.pipe.send_text('机场一\r')
        await self.wait_for(lambda:self.workspace.state.panel and self.workspace.state.panel.kind=='configs-actions')
        self.pipe.send_bytes(b'\x1b[B')
        self.pipe.send_text('\r')
        await self.wait_for(lambda:['configs','update','--','机场一','localhost'] in self.calls)

    async def test_inline_subscription_url_is_redacted_from_transcript(self):
        import domino_cli as cli
        for action,field in [('add','add'),('set-url','set_url')]:
            self.pipe.send_text('/configs '+action+' A --url "https://example.test/sub?token=PRIVATE-TOKEN"\r')
            await self.wait_for(lambda:any(args[:2]==['configs',action] for args in self.calls) and not self.workspace.state.busy)
            self.assertNotIn('PRIVATE-TOKEN',str(self.workspace.state.events))
            self.assertIn('***',str(self.workspace.state.events))
            arguments=next(v for v in self.calls if v[:2]==['configs',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(getattr(args,field),'A')
            self.assertEqual(args.target,'localhost')
            self.assertEqual(args.url,'https://example.test/sub?token=PRIVATE-TOKEN')

    async def test_short_subscription_commands_parse_with_the_current_target(self):
        import domino_cli as cli
        commands=[('/configs switch "-机场 A"','switch','use','-机场 A'),
                  ('/configs update all','update','update_all',True),
                  ('/configs rename "机场 A" "备用 B"','rename','new_name','备用 B'),
                  ('/configs remove "备用 B"','remove','remove','备用 B')]
        for text,action,field,value in commands:
            self.pipe.send_text(text+'\r')
            await self.wait_for(lambda:any(v[:2]==['configs',action] for v in self.calls) and not self.workspace.state.busy)
            arguments=next(v for v in self.calls if v[:2]==['configs',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target,'localhost')
            self.assertEqual(getattr(args,field),value)

    async def test_updating_selected_subscription_named_all_is_not_a_bulk_update(self):
        self.workspace.config_panel({'current_source':'原有配置','configs':[
            {'name':'all','kind':'subscription','active':False,'node_count':1,'updated_at':None}]})
        panel=self.workspace.state.panel
        panel.callback(panel.items[0]['value'])
        self.workspace.state.panel.callback('update')
        await self.wait_for(lambda:['configs','localhost','--update','all'] in self.calls)
        self.assertFalse(any(v[:2]==['configs','update'] for v in self.calls))

    async def test_rule_add_uses_the_current_target_and_preserves_rule_text(self):
        import domino_cli as cli
        rule='DOMAIN-SUFFIX,example.test,出口'
        self.pipe.send_text('/rules add "'+rule+'"\r')
        await self.wait_for(lambda:any(v[0]=='rules' for v in self.calls) and not self.workspace.state.busy)
        arguments=next(v for v in self.calls if v[0]=='rules')
        args=cli.normalize_command(cli.build_parser().parse_args(arguments))
        self.assertEqual(args.add_rule,rule)
        self.assertEqual(args.target,'localhost')

    async def test_proxy_actions_use_the_same_cli_grammar_and_target(self):
        import domino_cli as cli
        for action in ['status','on','off']:
            self.pipe.send_text('/proxy '+action+'\r')
            await self.wait_for(lambda:any(v[:2]==['proxy',action] for v in self.calls) and not self.workspace.state.busy)
            arguments=next(v for v in self.calls if v[:2]==['proxy',action])
            args=cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target,'localhost')
            self.assertEqual(args.set,action if action!='status' else None)

    async def test_shell_actions_use_current_target_without_parent_application(self):
        import domino_cli as cli
        for action in ['status', 'on', 'off']:
            self.pipe.send_text('/shell ' + action + '\r')
            await self.wait_for(lambda: any(v[:2] == ['shell', action] for v in self.calls) and not self.workspace.state.busy)
            arguments = next(v for v in self.calls if v[:2] == ['shell', action])
            args = cli.normalize_command(cli.build_parser().parse_args(arguments))
            self.assertEqual(args.target, 'localhost')
            self.assertEqual(args.set, action if action != 'status' else None)

    async def test_slow_operation_does_not_block_input_and_ctrl_c_cancels(self):
        self.pipe.send_text('/status\r')
        await asyncio.wait_for(self.status_wait.wait(), 2)
        self.pipe.send_text('/traffic\r')
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
        self.assertFalse(any(args[0]=='stop' for args in self.calls))

    async def test_plain_exit_from_input_keeps_service_running(self):
        self.pipe.send_text('exit\r')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[0]=='stop' for args in self.calls))

    async def test_ctrl_d_exits_even_with_unsubmitted_input(self):
        self.pipe.send_text('unfinished command')
        self.pipe.send_bytes(b'\x04')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[0]=='stop' for args in self.calls))

    async def test_ctrl_d_exits_from_node_filter_without_switching(self):
        self.workspace.nodes(self.group)
        self.pipe.send_text('B')
        self.pipe.send_bytes(b'\x04')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[0] in ['stop','select'] for args in self.calls))

    async def test_plain_exit_from_picker_is_not_treated_as_node_filter(self):
        self.workspace.nodes(self.group)
        self.pipe.send_text('exit\r')
        await asyncio.wait_for(self.task,3)
        self.assertFalse(any(args[0] in ['stop','select'] for args in self.calls))

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
            if args[0]=='mode':
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
            if args[0]=='delay':
                self.calls.append(args)
                return json.dumps([{'name':'B','delay_ms':42,'ok':True}])
            return await original(args,**kwargs)
        self.workspace.execute=execute
        self.workspace.nodes(self.group)
        self.pipe.send_bytes(b'\x1b[B\x14')
        await self.wait_for(lambda:self.workspace.state.delays.get('B')==42)
        self.assertIn(['delay','localhost','--node','B','--json'],self.calls)
        self.assertFalse(any(args[0]=='select' for args in self.calls))
        self.assertIsNotNone(self.workspace.state.panel)

    async def test_compact_footer_keeps_routing_visible_and_traffic_command_shows_details(self):
        self.workspace.state.update({'reachable':True,'stats_available':True,'proxy_port':17897,
            'upload_total':1024,'download_total':4096,'system_proxy':{'routing':'other','ports':[7897]}},now=10)
        text=''.join(fragment[1] for fragment in self.workspace.footer())
        self.assertIn('7897',text)
        self.assertIn('17897',''.join(fragment[1] for fragment in self.workspace.header()))
        self.workspace.dispatch('/traffic')
        self.assertIn('累计 ↑ 1.0 KiB ↓ 4.0 KiB',str(self.workspace.state.events))
        self.assertIn('仅统计 Domino :17897',str(self.workspace.state.events))
