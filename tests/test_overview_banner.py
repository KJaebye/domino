"""Bare-command branding uses bounded read-only data and leaves other interfaces alone."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import domino_cli as cli
import domino_tui as ui
import install_domino as control

from tests.locale_fixture import chinese_ui

setUpModule, tearDownModule = chinese_ui()


class OverviewBannerTests(unittest.TestCase):
    def test_snapshot_uses_runtime_mode_and_registry_name_without_probing_or_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);app=home/'app';(app/'data').mkdir(parents=True)
            (app/'data/config.json').write_text('{"mode":"rule","mixed-port":17897,"secret":"PRIVATE"}')
            (app/'data/subscription.json').write_text('{"id":"fixture","name":"old"}')
            index=home/'.config/domino/subscriptions/index.json';index.parent.mkdir(parents=True)
            index.write_text('{"items":[{"id":"fixture","name":"xlink"}]}')
            before={str(p):p.read_bytes() for p in home.rglob('*') if p.is_file()}
            live={'GLOBAL':{'type':'Selector','all':['A'],'now':'A'},'出口':{'type':'Selector','all':['A'],'now':'A'},
                  'A':{'type':'Socks5','password':'PRIVATE'},'DIRECT':{'type':'Direct'}}
            def read(data,route,**options):
                self.assertEqual(options,{'timeout':.5})
                return json.dumps({'mode':'global'} if route=='/configs' else {'proxies':live}).encode()
            with patch.object(control,'HOME',home),patch.object(control,'current_installation',return_value=(app,None)), \
                    patch.object(control,'controller',side_effect=read) as request, \
                    patch.object(control,'systemctl',side_effect=AssertionError('service query')), \
                    patch.object(control,'probe',side_effect=AssertionError('external probe')):
                snapshot=cli.command_overview_snapshot()
            self.assertEqual({c.args[1] for c in request.call_args_list},{'/configs','/proxies'})
            self.assertEqual((snapshot['subscription'],snapshot['mode'],snapshot['node_count'],snapshot['group_count']),('xlink','global',1,2))
            self.assertTrue(snapshot['reachable'])
            self.assertNotIn('PRIVATE',json.dumps(snapshot))
            self.assertEqual(before,{str(p):p.read_bytes() for p in home.rglob('*') if p.is_file()})

    def test_absent_or_offline_installation_stays_unknown_without_fake_zero_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory)
            with patch.object(control,'current_installation',return_value=(app,None)),patch.object(control,'controller') as request:
                self.assertFalse(cli.command_overview_snapshot()['installed']);request.assert_not_called()
                (app/'data').mkdir();(app/'data/config.json').write_text('{"mixed-port":18888,"mode":"rule"}')
                request.side_effect=control.InstallError('PRIVATE timeout')
                value=cli.command_overview_snapshot()
            self.assertFalse(value['reachable']);self.assertIsNone(value['node_count'])
            self.assertIn('接口离线',ui.command_banner(value,cli.VERSION,color=False))
            self.assertNotIn('PRIVATE',str(value))

    def test_banner_reuses_logo_sanitizes_names_and_fits_narrow_terminals(self):
        snapshot={'installed':True,'reachable':True,'subscription':'xlink\x1b[2J\n'+('机场'*60),
                  'mode':'rule','proxy_port':17897,'node_count':33,'group_count':11}
        for columns in [12,36,75,76,100,140]:
            text=ui.command_banner(snapshot,cli.VERSION,columns=columns,color=False)
            self.assertNotIn('\x1b',text)
            self.assertEqual(len(text.splitlines()),3)
            self.assertTrue(all(control.human_width(line)<=columns for line in text.splitlines()))
            if columns>=76:self.assertIn(ui.LOGO_LINES[0],text)
        text=ui.command_banner(dict(snapshot,subscription='xlink'),cli.VERSION,columns=140,color=True)
        self.assertIn('localhost',text);self.assertIn('xlink',text);self.assertIn('33 节点 / 11 组',text)
        self.assertIn('\x1b[32m●\x1b[0m',text)
        self.assertIn('接口在线',text)
        self.assertIn('v'+cli.VERSION,text)

    def test_only_the_bare_command_uses_the_banner(self):
        with patch.object(cli,'command_overview_snapshot',side_effect=AssertionError('unexpected banner')) as snapshot, \
                patch.object(cli,'run',return_value=Mock(returncode=0)),redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['env']),0)
            self.assertEqual(cli.main(['nodes']),0)
            self.assertEqual(cli.main(['nodes','--json']),0)
            for args in [['-h'],['--version']]:
                with self.assertRaises(SystemExit):cli.main(args)
        snapshot.assert_not_called()
        with patch.object(cli,'command_overview_snapshot',return_value={'installed':False}) as snapshot,redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main([]),0)
        self.assertIn(ui.LOGO_LINES[0],output.getvalue());snapshot.assert_called_once()
