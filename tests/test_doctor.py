"""Read-only diagnostics must distinguish a CONNECT from completed HTTPS."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import domino_cli as cli
import domino_doctor as mac
import install_domino as common
import domino_macos_app as native


class DoctorTests(unittest.TestCase):
    def run_doctor(self, *, proxy_exit=35, uuid_output='', insecure=False, native_launcher=False,
                   proxy_status=200, native_status=200, native_exit=0, plain=False, verbose=False):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'data').mkdir()
            (app / 'data/config.json').write_text(json.dumps({'mixed-port':17897, 'secret':'PRIVATE-CONTROLLER-TOKEN'}))
            (app / 'mihomo').write_bytes(b'core')
            launcher = native.app_path(app) / native.EXECUTABLE
            if native_launcher:
                launcher.parent.mkdir(parents=True)
                launcher.write_bytes(b'launcher')
            ctx = SimpleNamespace(current_installation=lambda:(app,None), InstallError=common.InstallError, show=common.show,
                human_header=common.human_header,human_row=common.human_row,human_time=common.human_time)
            def run(args, **kwargs):
                output = ''
                code = 0
                if args[0] == 'curl':
                    proxy = bool(args[args.index('--proxy')+1])
                    code = proxy_exit if proxy else native_exit
                    output = '000' if code else str(proxy_status if proxy else native_status)
                elif args[0] == 'otool':
                    output = 'uuid 12345678-1234-1234-1234-123456789ABC' if native_launcher and args[-1] == str(launcher) else uuid_output
                elif args[0] == 'ps': output = '123 1'
                elif args[0] == 'route': output = 'interface: en0'
                elif args[0].endswith('/mihomo'): output = 'Mihomo test\n'
                return SimpleNamespace(returncode=code, stdout=output, stderr='PRIVATE-ERROR')
            with patch.object(mac.sys,'platform','darwin'), patch.object(mac.subprocess,'run',side_effect=run) as commands, \
                    patch.object(mac,'launch',return_value=SimpleNamespace(returncode=0,stdout='pid = 123' + ('\nprogram = ' + str(launcher) if native_launcher else ''))), \
                    patch.object(mac,'system_proxy_overview',return_value={'routing':'domino','ports':[17897]}), \
                    patch.object(mac,'resolve_system',return_value=['10.0.0.2']), patch.object(mac,'system_hosts',return_value=[]), \
                    patch.object(mac.socket,'socket'), redirect_stdout(io.StringIO()) as output:
                result = mac.doctor(ctx,'https://internal.example/',insecure=insecure,as_json=not plain,verbose=verbose)
                calls = commands.call_args_list
            self.assertNotIn('PRIVATE',output.getvalue())
            self.rendered = output.getvalue()
            if not plain:self.assertEqual(json.loads(output.getvalue()),result)
            self.assertTrue(all(call.args[0][0] not in ['networksetup','launchctl','codesign'] for call in calls))
            return result, calls

    def test_native_success_and_connect_only_failure_are_different(self):
        result, calls = self.run_doctor()
        self.assertTrue(result['native']['ok'])
        self.assertFalse(result['configured_proxy']['ok'])
        self.assertIsNone(result['configured_proxy']['http_status'])
        self.assertEqual(result['mach_o_uuids'],[])
        self.assertTrue(any('LC_UUID' in hint for hint in result['hints']))
        for call in calls:
            if call.args[0][0]=='curl':
                self.assertNotIn('--insecure',call.args[0])
                self.assertNotIn('--location',call.args[0])

    def test_valid_uuid_and_completed_https(self):
        result, calls = self.run_doctor(proxy_exit=0,uuid_output='uuid 12345678-1234-1234-1234-123456789ABC',insecure=True)
        self.assertTrue(result['configured_proxy']['ok'])
        self.assertEqual(len(result['mach_o_uuids']),1)
        self.assertEqual(result['hints'],[])
        self.assertFalse(result['certificate_verified'])
        self.assertTrue(all('--insecure' in c.args[0] for c in calls if c.args[0][0]=='curl'))

    def test_native_app_identity_is_distinguished_from_unchanged_backend_uuid(self):
        result, _ = self.run_doctor(proxy_exit=0, native_launcher=True)
        self.assertEqual(result['mach_o_uuids'], [])
        self.assertTrue(result['responsible_app']['agent_uses_launcher'])
        self.assertTrue(result['responsible_app']['mach_o_uuids'])
        self.assertEqual(result['hints'], [])

    def test_redirect_is_explicitly_connected_and_default_output_hides_technical_details(self):
        result, _ = self.run_doctor(proxy_exit=0, proxy_status=302, native_status=302, plain=True)
        self.assertEqual(result['conclusion']['state'], 'connected')
        self.assertTrue(result['conclusion']['domino_connected'])
        self.assertIn('已连通：通过 Domino 可以访问该地址', self.rendered)
        self.assertIn('网站要求跳转（HTTP 302）', self.rendered)
        self.assertNotIn('系统解析', self.rendered)
        self.assertNotIn('LC_UUID', self.rendered)
        self.assertIn('继续跳转或登录', self.rendered)
        self.run_doctor(proxy_exit=0, plain=True, verbose=True)
        self.assertIn('系统解析', self.rendered)

    def test_http_errors_are_connected_and_network_failures_are_not(self):
        for status in (401, 403, 404, 503):
            with self.subTest(status=status):
                result, _ = self.run_doctor(proxy_exit=0, proxy_status=status, plain=True)
                self.assertEqual(result['conclusion']['state'], 'http_error')
                self.assertTrue(result['conclusion']['domino_connected'])
                self.assertIn('已连通', self.rendered)
                self.assertNotIn('Domino 未连通', self.rendered)
        result, _ = self.run_doctor(plain=True)
        self.assertEqual(result['conclusion']['state'], 'proxy_failed')
        self.assertFalse(result['conclusion']['domino_connected'])
        self.assertIn('系统直连可以到达网站', self.rendered)
        result, _ = self.run_doctor(native_exit=7, plain=True)
        self.assertEqual(result['conclusion']['state'], 'both_failed')
        self.assertIn('都未收到网站响应', self.rendered)

    def test_insecure_response_does_not_claim_verified_connectivity(self):
        result, _ = self.run_doctor(proxy_exit=0, insecure=True, plain=True)
        self.assertIn('跳过了证书校验', self.rendered)
        self.assertIn('去掉 --insecure', result['conclusion']['next_step'])

    def test_verbose_option_is_forwarded_to_local_and_remote_backend(self):
        args = cli.build_parser().parse_args(['doctor', '--verbose'])
        options, privileged = cli.management_options(args)
        self.assertIn('--verbose', options)
        self.assertFalse(privileged)

    def test_private_or_non_https_url_rejected_before_any_io(self):
        ctx=SimpleNamespace(InstallError=common.InstallError)
        for url in ['http://internal/','https://user:password@internal/','https://internal/?token=x','https://internal/#x']:
            with self.subTest(url=url),self.assertRaises(common.InstallError):
                mac.doctor(ctx,url)

    def test_public_command_forwards_diagnostic_options(self):
        args=cli.build_parser().parse_args(['doctor','--url','https://internal/','--insecure','--json'])
        options, privileged=cli.management_options(args)
        self.assertEqual(options,['--url','https://internal/','--insecure','--json'])
        self.assertFalse(privileged)


if __name__ == '__main__': unittest.main()


class CrossPlatformDoctorTests(unittest.TestCase):
    def test_http_error_is_reachable_but_not_a_successful_business_response(self):
        value = mac.probe_result(SimpleNamespace(returncode=0, stdout='503'))
        self.assertTrue(value['reachable'])
        self.assertFalse(value['ok'])
        self.assertEqual(value['failure_stage'], 'http')
        self.assertEqual(mac.probe_result(SimpleNamespace(returncode=6, stdout='000'))['failure_stage'], 'dns')

    def test_linux_detects_hosts_mismatch_without_mac_commands_or_mutations(self):
        import domino_linux
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory); (app/'data').mkdir()
            path=app/'data/config.json'; path.write_text(json.dumps({'mixed-port':17897,'dns':{'enable':False}}))
            (app/'mihomo').write_bytes(b'fixture')
            before=path.read_bytes()
            ctx=SimpleNamespace(current_installation=lambda:(app,Path('domino.service')),
                InstallError=common.InstallError,show=common.show,
                api_json=lambda *args,**kwargs:{'Answer':[]})
            def run(args, **kwargs):
                if args[0]=='curl':
                    proxy=args[args.index('--proxy')+1]
                    return SimpleNamespace(returncode=35 if proxy else 0,stdout='000' if proxy else '302')
                if args[0]=='ip':return SimpleNamespace(returncode=0,stdout='[{"dev":"tun0"}]')
                return SimpleNamespace(returncode=0,stdout='Mihomo fixture')
            with patch.object(mac.sys,'platform','linux'),patch.object(mac.subprocess,'run',side_effect=run) as calls, \
                 patch.object(mac,'launch',side_effect=AssertionError('macOS service command on Linux')), \
                 patch.object(domino_linux,'system_proxy_overview',return_value={'routing':'unsupported','ports':[]}), \
                 patch.object(mac,'resolve_system',return_value=['10.0.0.5']), \
                 patch.object(mac,'system_hosts',return_value=['10.0.0.5']),patch.object(mac.socket,'socket'), \
                 redirect_stdout(io.StringIO()):
                result=mac.doctor(ctx,'https://internal.example/',as_json=True)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['dns_routes'][0]['interface'],'tun0')
            self.assertTrue(any('系统 hosts' in value for value in result['hints']))
            self.assertTrue(all(c.args[0][0] not in ('launchctl','otool','networksetup','sudo') for c in calls.call_args_list))

    def test_tui_diagnostic_rejects_private_urls_before_recording_input(self):
        import domino_tui as ui
        from unittest.mock import Mock
        workspace=object.__new__(ui.Workspace);workspace.state=ui.State('localhost');workspace.queue=Mock()
        workspace.dispatch('/doctor https://internal.example/?token=PRIVATE')
        workspace.queue.assert_not_called()
        self.assertNotIn('PRIVATE',str(workspace.state.events))
        workspace.dispatch('/doctor https://internal.example/')
        self.assertEqual(workspace.queue.call_args.args[1:],('doctor','--url','https://internal.example/'))
        workspace.dispatch('/doctor')
        self.assertEqual(workspace.queue.call_args.args[1:],('doctor',))
