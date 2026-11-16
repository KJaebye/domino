"""Ubuntu desktop/session behavior through a synthetic GSettings adapter only."""
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import domino_linux as linux
import domino_cli as cli
import install_domino as control
from domino_model import DomainError


def baseline():
    values={'mode':"'none'",'same':'true','auth':'false'}
    for kind in (*linux.KINDS,'ftp'):
        values.update({kind+'.host':"'old.example'" if kind!='ftp' else "''",kind+'.port':'7897' if kind!='ftp' else '0'})
    return values


class FakeSettings:
    def __init__(self): self.values=baseline();self.writes=[];self.failure=None
    def state(self): return copy.deepcopy(self.values)
    def get(self,key): return self.values[key]
    def writable(self,keys): pass
    def set(self,key,value):
        self.values[key]=value;self.writes.append((key,value))
        if self.failure:self.failure(key,value)


class LinuxProxyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.home=Path(self.directory.name);self.app=self.home/'app';(self.app/'data').mkdir(parents=True)
        (self.app/'data/config.json').write_text('{"mixed-port":17897,"proxies":[{}]}')
        self.ctx=SimpleNamespace(HOME=self.home,current_installation=lambda:(self.app,None),
            subscription_pending=lambda *args:False,systemctl=Mock(return_value=True),controller=Mock(return_value=b'{}'),
            write_private=control.write_private,show=control.show,human_header=control.human_header,human_row=control.human_row)
        self.settings=FakeSettings();self.patch=patch.object(linux,'Settings',return_value=self.settings)
        self.patch.start();self.addCleanup(self.patch.stop)
    def action(self,action=None): return linux.system_proxy(self.ctx,action,render=False)

    def test_repeat_start_stop_restores_original_and_leaves_shell_alone(self):
        shell=self.home/'shell-policy.json';shell.write_text('unchanged')
        for _ in range(2):
            result=self.action('on');self.assertEqual(result['routing'],'domino')
        record=linux.record_path(self.ctx)
        self.assertEqual(json.loads(record.read_text())['original'],baseline())
        self.assertEqual(record.stat().st_mode&0o777,0o600)
        self.action('off');self.assertEqual(self.settings.values,baseline())
        self.assertFalse(record.exists());self.assertEqual(shell.read_text(),'unchanged')

    def test_stop_preserves_another_client_and_a_user_disabled_mode(self):
        self.action('on');self.settings.values['https.host']="'another.example'";self.settings.values['https.port']='8888'
        self.action('off')
        self.assertEqual(self.settings.values['https.port'],'8888')
        self.assertEqual(self.settings.values['http.port'],'7897')
        self.assertEqual(self.settings.values['mode'],"'manual'")
        self.action('on');self.settings.values['mode']="'none'";self.action('off')
        self.assertEqual(self.settings.values['mode'],"'none'")

    def test_pac_and_authentication_are_rejected_before_writes(self):
        for key,value in [('mode',"'auto'"),('auth','true')]:
            self.settings.values=baseline();self.settings.values[key]=value
            with self.assertRaises(DomainError):self.action('on')
            self.assertFalse(self.settings.writes)
            self.assertFalse(linux.record_path(self.ctx).exists())

    def test_failed_apply_restores_its_entry_state(self):
        def fail(key,value):
            if len(self.settings.writes)==3:raise DomainError('write failure')
        self.settings.failure=fail
        with self.assertRaises(DomainError) as caught:self.action('on')
        self.assertEqual(caught.exception.effect,'rolled_back')
        self.assertEqual(self.settings.values,baseline())
        self.assertFalse(linux.record_path(self.ctx).exists())

    def test_stop_does_not_restore_a_backup_pointing_at_the_same_stopped_core(self):
        self.settings.values['mode']="'manual'"
        for kind in linux.KINDS:
            self.settings.values[kind+'.host']="'127.0.0.1'";self.settings.values[kind+'.port']='17897'
        self.action('on');result=self.action('off')
        self.assertEqual(result['routing'],'off')
        self.assertTrue(all(not value['enabled'] for value in result['proxies'].values()))

    def test_failed_recovery_retains_a_retryable_record(self):
        self.settings.failure=lambda *args:(_ for _ in ()).throw(DomainError('write failure'))
        with self.assertRaises(DomainError) as caught:self.action('on')
        self.assertEqual(caught.exception.code,'RECOVERY_INCOMPLETE')
        self.assertTrue(linux.record_path(self.ctx).exists())
        self.settings.failure=None;self.action('off')
        self.assertEqual(self.settings.values,baseline())
        self.assertFalse(linux.record_path(self.ctx).exists())

    def test_failed_stop_can_finish_original_mode_on_retry(self):
        self.action('on')
        def fail(*args):
            self.settings.failure=None
            raise DomainError('interrupted write')
        self.settings.failure=fail
        with self.assertRaises(DomainError):self.action('off')
        self.assertTrue(linux.record_path(self.ctx).exists())
        self.action('off');self.assertEqual(self.settings.values,baseline())
        self.assertFalse(linux.record_path(self.ctx).exists())

    def test_headless_has_no_desktop_writes_and_pending_restore_blocks_stop(self):
        unavailable=DomainError('no session',code='DESKTOP_UNAVAILABLE')
        with patch.object(linux,'Settings',side_effect=unavailable):
            self.assertFalse(self.action('on')['supported'])
            self.assertFalse(self.action('off')['supported'])
        self.ctx.controller.assert_not_called()
        self.action('on')
        with patch.object(linux,'Settings',side_effect=unavailable),self.assertRaises(DomainError):self.action('off')
        self.assertTrue(linux.record_path(self.ctx).exists())

    def test_locked_keys_refuse_before_a_backup_or_write(self):
        with patch.object(self.settings,'writable',side_effect=DomainError('locked',code='AUTH_REQUIRED')):
            with self.assertRaises(DomainError):self.action('on')
        self.assertFalse(self.settings.writes);self.assertFalse(linux.record_path(self.ctx).exists())

    def test_corrupt_restore_plan_cannot_partially_write_settings(self):
        self.action('on');path=linux.record_path(self.ctx);record=json.loads(path.read_text())
        record['restore']={'before':{},'target':{}}
        path.write_text(json.dumps(record));self.settings.writes=[]
        with self.assertRaises(DomainError):self.action('off')
        self.assertFalse(self.settings.writes)

    def test_custom_port_and_overview_match_desktop_state(self):
        (self.app/'data/config.json').write_text('{"mixed-port":18888,"proxies":[{}]}')
        self.assertEqual(self.action('on')['proxies']['http']['port'],18888)
        self.assertEqual(linux.system_proxy_overview(18888)['routing'],'domino')
        self.assertEqual(linux.system_proxy_overview(17897)['routing'],'other')
        self.settings.values['mode']="'auto'"
        self.assertEqual(linux.system_proxy_overview(18888)['routing'],'pac')

    def test_real_adapter_uses_arguments_and_does_not_expose_dconf_errors(self):
        self.patch.stop()
        schemas='\n'.join(sorted({schema for schema,_ in linux.KEYS.values()}))
        def run(args,**options):
            return SimpleNamespace(returncode=0,stdout=schemas if args[1]=='list-schemas' else "'none'",stderr='PRIVATE failure' if args[1]=='set' else '')
        with patch.object(linux,'desktop_environment',return_value={}),patch.object(linux.subprocess,'run',side_effect=run):
            settings=linux.Settings()
            with self.assertRaises(DomainError) as caught:settings.set('mode',"'manual'")
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_unified_linux_service_orders_restore_before_stop(self):
        calls=[]
        with patch.object(control,'APP',self.app),patch.object(control.sys,'platform','linux'), \
                patch.object(control,'current_installation',return_value=(self.app,Path('domino.service'))), \
                patch.object(control,'owned_service'),patch.object(control,'run'), \
                patch.object(control,'sudo',side_effect=lambda *args:calls.append(args[1])), \
                patch.object(control,'system_proxy',side_effect=lambda action,**kw:(calls.append('proxy.'+action) or {'supported':False})), \
                redirect_stdout(io.StringIO()) as output:
            control.service_action('start',True);control.service_action('stop',True)
        self.assertEqual(calls,['start','proxy.on','proxy.off','stop'])
        self.assertIn('无 GNOME 桌面会话',output.getvalue())

    def test_restore_failure_prevents_systemd_stop(self):
        with patch.object(control,'APP',self.app),patch.object(control.sys,'platform','linux'), \
                patch.object(control,'current_installation',return_value=(self.app,Path('domino.service'))), \
                patch.object(control,'owned_service'),patch.object(control,'run'),patch.object(control,'sudo') as sudo, \
                patch.object(control,'system_proxy',side_effect=DomainError('recovery incomplete')):
            with self.assertRaises(DomainError):control.service_action('stop',True)
        sudo.assert_not_called()

    def test_overview_help_is_platform_neutral_and_headless_status_is_truthful(self):
        with redirect_stdout(io.StringIO()) as output:cli.main([])
        self.assertNotIn('macOS',output.getvalue())
        result={'installed':True,'active':True,'enabled':True,'healthy':True,'system_proxy':{'routing':'unsupported'}}
        text=control.status_text(result)
        self.assertIn('代理出网正常',text);self.assertIn('无 GNOME 桌面会话',text)
        self.assertNotIn('系统代理未接通',text)
