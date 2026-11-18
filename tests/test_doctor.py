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
    def run_doctor(self, *, proxy_exit=35, uuid_output='', insecure=False, native_launcher=False):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'data').mkdir()
            (app / 'data/config.json').write_text(json.dumps({'mixed-port':17897, 'secret':'PRIVATE-CONTROLLER-TOKEN'}))
            (app / 'mihomo').write_bytes(b'core')
            launcher = native.app_path(app) / native.EXECUTABLE
            if native_launcher:
                launcher.parent.mkdir(parents=True)
                launcher.write_bytes(b'launcher')
            ctx = SimpleNamespace(current_installation=lambda:(app,None), InstallError=common.InstallError, show=common.show)
            def run(args, **kwargs):
                output = ''
                code = 0
                if args[0] == 'curl':
                    code = proxy_exit if args[args.index('--proxy')+1] else 0
                    output = '000' if code else '200'
                elif args[0] == 'otool':
                    output = 'uuid 12345678-1234-1234-1234-123456789ABC' if native_launcher and args[-1] == str(launcher) else uuid_output
                elif args[0] == 'ps': output = '123 1'
                elif args[0] == 'route': output = 'interface: en0'
                elif args[0].endswith('/mihomo'): output = 'Mihomo test\n'
                return SimpleNamespace(returncode=code, stdout=output, stderr='PRIVATE-ERROR')
            with patch.object(mac.subprocess,'run',side_effect=run) as commands, \
                    patch.object(mac,'launch',return_value=SimpleNamespace(returncode=0,stdout='pid = 123' + ('\nprogram = ' + str(launcher) if native_launcher else ''))), \
                    patch.object(mac,'system_proxy_overview',return_value={'routing':'domino','ports':[17897]}), \
                    patch.object(mac.socket,'getaddrinfo',return_value=[(2,1,6,'',('10.0.0.2',443))]), \
                    patch.object(mac.socket,'socket'), redirect_stdout(io.StringIO()) as output:
                result = mac.doctor(ctx,'https://internal.example/',insecure=insecure,as_json=True)
                calls = commands.call_args_list
            self.assertNotIn('PRIVATE',output.getvalue())
            self.assertEqual(json.loads(output.getvalue()),result)
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
