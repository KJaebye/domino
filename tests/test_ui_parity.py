"""UI transport parity: no real installation, subscription, node or service changes."""
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import AsyncMock,Mock,patch

import domino_cli as cli
import domino_tui as ui


class UiParityTests(unittest.TestCase):
    def test_capture_options_are_read_only_and_exclude_config_contents(self):
        from types import SimpleNamespace
        import install_domino as control
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profile.yaml';content='secret: PRIVATE\n';path.write_text(content)
            output=io.StringIO()
            with patch.object(cli,'capture_candidates',return_value=[path]),patch.object(cli,'source_identity',return_value={'profile_name':'机场一'}),redirect_stdout(output):
                control._run_command(SimpleNamespace(action='catch-options'))
            self.assertEqual(json.loads(output.getvalue()),[{'name':'Clash Verge · 机场一','path':str(path)}])
            self.assertNotIn('PRIVATE',output.getvalue());self.assertEqual(path.read_text(),content)

    def test_capture_option_transport_uses_the_current_host_without_color_or_writes(self):
        for remote in [False,True]:
            ssh=Mock() if remote else None
            if ssh:ssh.action_argv.return_value=['ssh-fixture']
            process=Mock(returncode=0);process.communicate=AsyncMock(return_value=(b'[]',b''))
            spawn=AsyncMock(return_value=process)
            def run(target,execute,version):asyncio.run(execute(['catch-options','lab' if remote else 'localhost'],capture=True))
            with patch.object(cli.sys.stdin,'isatty',return_value=True),patch.object(ui,'run',side_effect=run),patch.object(cli.asyncio,'create_subprocess_exec',spawn):
                cli.terminal_ui(cli.build_parser().parse_args(['ui']),ssh)
            if remote:self.assertEqual(ssh.action_argv.call_args.args,('catch-options',))
            else:self.assertEqual(spawn.call_args.args[2:3],('catch-options',))
            self.assertNotIn('--color',spawn.call_args.args)

    def test_embedded_capture_options_work_without_an_installed_cli_or_network_probe(self):
        import shlex
        ssh=cli.SSH(cli.build_parser().parse_args(['lab','ui','--batch']));ssh.socket='/tmp/not-used'
        command=shlex.split(ssh.action_argv('catch-options')[-1])
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);source=home/'.config/clash/config.yaml';source.parent.mkdir(parents=True)
            content=json.dumps({'mixed-port':17897,'proxies':[{'name':'fixture','type':'ss','server':'192.0.2.1','port':9,'cipher':'aes-128-gcm','password':'PRIVATE'}]})
            source.write_text(content)
            p=subprocess.run([cli.sys.executable,*command[1:]],env={**os.environ,'HOME':str(home)},cwd=home,capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(p.stdout),[{'name':'ClashX / Clash','path':str(source)}])
            self.assertNotIn('PRIVATE',p.stdout+p.stderr);self.assertEqual(source.read_text(),content)
            self.assertFalse((home/'.local/share/domino').exists())

    def test_stopped_header_has_a_red_solid_dot_and_no_fake_node_count(self):
        from types import SimpleNamespace
        workspace=object.__new__(ui.Workspace);workspace.state=ui.State('localhost',snapshot={
            'installed':True,'active':False,'reachable':False,'subscription':'xlink','node_count':None,'groups':[]})
        workspace.version='fixture';workspace.app=SimpleNamespace(output=SimpleNamespace(get_size=lambda:SimpleNamespace(rows=36,columns=100)))
        parts=workspace.header();text=''.join(value for _,value in parts)
        self.assertIn('● 服务已停止',text)
        self.assertTrue(any(style=='class:error' and '●' in value for style,value in parts))
        self.assertNotIn('None',text);self.assertNotIn('0 节点',text)

    def test_package_managed_ui_capture_uses_package_entry_in_child_process(self):
        process=Mock(returncode=0);process.communicate=AsyncMock(return_value=(None,None))
        spawn=AsyncMock(return_value=process)
        def run(target,execute,version):
            asyncio.run(execute(['localhost','catch','all'],capture=False))
        with patch.object(cli,'PACKAGE_MANAGED',True), \
                patch.object(cli.sys.stdin,'isatty',return_value=True), \
                patch.object(ui,'run',side_effect=run), \
                patch.object(cli.asyncio,'create_subprocess_exec',spawn):
            cli.terminal_ui(cli.build_parser().parse_args(['ui']))
        self.assertEqual(spawn.call_args.args[1:3],(str(Path(cli.__file__).with_name('domino_install.py')),'--package-cli'))
        self.assertIn('catch',spawn.call_args.args)
        self.assertIn('all',spawn.call_args.args)

    def test_catch_uses_the_full_cli_and_preserves_confirmation_locally_and_remotely(self):
        for remote in [False,True]:
            args=cli.build_parser().parse_args(['ui']);ssh=Mock() if remote else None
            if ssh:ssh.action_argv.return_value=['ssh-fixture']
            process=Mock(returncode=0);process.communicate=AsyncMock(return_value=(b'',b''))
            spawn=AsyncMock(return_value=process)
            def run(target,execute,version):
                asyncio.run(execute(['lab' if remote else 'localhost','catch','all'],capture=False))
            with patch.object(cli.sys.stdin,'isatty',return_value=True),patch.object(ui,'run',side_effect=run), \
                    patch.object(cli.asyncio,'create_subprocess_exec',spawn):
                cli.terminal_ui(args,ssh)
            if remote:
                self.assertEqual(ssh.action_argv.call_args.args,('cli','catch','all'))
                self.assertTrue(ssh.action_argv.call_args.kwargs['tty'])
            else:
                self.assertEqual(spawn.call_args.args[:4],(cli.sys.executable,str(Path(cli.__file__)),'catch','all'))
            self.assertNotIn('--yes',spawn.call_args.args)

    def test_full_traffic_requests_a_pty_even_in_batch_ui(self):
        args=cli.build_parser().parse_args(['ui','--batch']);ssh=Mock();ssh.action_argv.return_value=['ssh-fixture']
        process=Mock(returncode=0);process.communicate=AsyncMock(return_value=(None,None))
        def run(target,execute,version):asyncio.run(execute(['lab','traffic','--full'],capture=False,timeout=None))
        with patch.object(cli.sys.stdin,'isatty',return_value=True),patch.object(ui,'run',side_effect=run), \
                patch.object(cli.asyncio,'create_subprocess_exec',AsyncMock(return_value=process)):
            cli.terminal_ui(args,ssh)
        self.assertEqual(ssh.action_argv.call_args.args[0],'traffic')
        self.assertIn('--dashboard',ssh.action_argv.call_args.args)
        self.assertTrue(ssh.action_argv.call_args.kwargs['tty'])

    def test_inactive_usage_does_not_mark_a_matching_node_from_another_config(self):
        workspace=object.__new__(ui.Workspace);workspace.state=ui.State('localhost')
        workspace.delay_result(json.dumps({'configuration':'feiniao','usage':{'active':False,'current':'xlink','nodes':[],'paths':[]},
            'results':[{'name':'A','delay_ms':12,'ok':True}]}))
        text=str(workspace.state.events)
        self.assertIn('当前使用 xlink',text);self.assertNotIn('● A',text)

    def test_live_backend_streams_progress_and_a_private_usage_envelope(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/proxies':
                    data={'proxies':{'出口':{'type':'Selector','now':'A','all':['A']},'A':{'type':'Socks5','password':'PRIVATE'}}}
                elif self.path=='/configs':data={'mode':'rule'}
                else:
                    time.sleep(.2);data={'delay':22}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);data=home/'.local/share/domino/data';data.mkdir(parents=True)
            config=data/'config.json';content=json.dumps({'mixed-port':17897,'external-controller':f'127.0.0.1:{server.server_port}','secret':'synthetic'})
            config.write_text(content);progress=[];answer={}
            async def drive(execute):
                finished=False
                def update(value):progress.append((value,finished))
                output=await execute(['localhost','test','--node','A','--json'],capture=True,on_progress=update)
                finished=True;answer.update(json.loads(output))
            def run(target,execute,version):asyncio.run(drive(execute))
            with patch.dict(os.environ,HOME=str(home)),patch.object(cli.sys.stdin,'isatty',return_value=True), \
                    patch.object(ui,'run',side_effect=run),redirect_stdout(io.StringIO()):
                cli.terminal_ui(cli.build_parser().parse_args(['ui']))
            self.assertTrue(progress)
            self.assertTrue(all(not finished for _,finished in progress))
            self.assertTrue(any('节点' in value for value,_ in progress))
            self.assertEqual(answer['results'],[{'name':'A','delay_ms':22,'ok':True}])
            self.assertEqual(answer['usage']['nodes'],['A'])
            self.assertNotIn('PRIVATE',json.dumps(answer))
            self.assertEqual(config.read_text(),content)

    def test_cancelling_a_streaming_test_reaps_its_isolated_process_group(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data={'proxies':{'A':{'type':'Socks5'}}} if self.path=='/proxies' else {'mode':'rule'} if self.path=='/configs' else {'delay':12}
                if '/delay?' in self.path:time.sleep(.3)
                self.send_response(200);self.end_headers()
                try:self.wfile.write(json.dumps(data).encode())
                except BrokenPipeError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        processes=[];spawn=asyncio.create_subprocess_exec
        async def record(*args,**options):
            process=await spawn(*args,**options);processes.append(process);return process
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);data=home/'.local/share/domino/data';data.mkdir(parents=True)
            (data/'config.json').write_text(json.dumps({'mixed-port':17897,'external-controller':f'127.0.0.1:{server.server_port}','secret':'synthetic'}))
            async def drive(execute):
                ready=asyncio.Event()
                task=asyncio.create_task(execute(['localhost','test','--node','A','--json'],capture=True,on_progress=lambda _:ready.set()))
                await asyncio.wait_for(ready.wait(),3);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            def run(target,execute,version):asyncio.run(drive(execute))
            with patch.dict(os.environ,HOME=str(home)),patch.object(cli.sys.stdin,'isatty',return_value=True), \
                    patch.object(ui,'run',side_effect=run),patch.object(cli.asyncio,'create_subprocess_exec',side_effect=record):
                cli.terminal_ui(cli.build_parser().parse_args(['ui']))
        self.assertIsNotNone(processes[0].returncode)
        with self.assertRaises(ProcessLookupError):os.killpg(processes[0].pid,0)
