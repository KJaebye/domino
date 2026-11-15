from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import domino_agent as agent
import domino_agent_backend as agent_backend
import domino_cli as cli
import install_domino as backend
from domino_service import Application


class UnusedContext:
    def __getattribute__(self, name):
        raise AssertionError(f'rejected request accessed context: {name}')


class RemovedClientBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)

    def request(self, **extra):
        return dict(schema_version=1,operation='mode.set',arguments={'value':'global'},
            operation_id='a'*32,transport_token='b'*32,target='localhost',**extra)

    def assert_rejected(self, result, code='INVALID_ARGUMENT'):
        self.assertFalse(result['ok'])
        self.assertEqual(result['schema_version'],1)
        self.assertEqual(result['client'],'domino')
        self.assertEqual(result['error']['code'],code)
        self.assertEqual(result['effect'],'none')
        self.assertFalse(result['changed'])
        self.assertIsNone(result['revision'])
        self.assertIsNone(result['data'])

    def test_human_parser_rejects_removed_commands_and_selectors(self):
        commands=[['clients'],['clients','list'],['clients','discover'],
            ['clients','bind','clash'],['clients','remove','clash'],
            ['--client','clash','status'],['status','--client','clash'],
            ['scan','--client','clash'],['export','--arch','arm64','--client','clash'],
            ['deploy','alice@192.0.2.10','--client','clash']]
        for arguments in commands:
            with self.subTest(arguments=arguments),redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.build_parser().parse_args(arguments)
                self.assertEqual(caught.exception.code,2)

    def test_backend_parser_rejects_removed_commands_and_selectors(self):
        commands=[['clients'],['clients','--operation','list'],
            ['status','--client','clash'],['scan','--client','clash'],
            ['mode','--client','clash','--set','global'],['stop','--client','clash']]
        for arguments in commands:
            with self.subTest(arguments=arguments),redirect_stderr(io.StringIO()):
                with patch.object(backend,'current_installation') as installation,patch.object(backend,'service_action') as service:
                    with self.assertRaises(SystemExit) as caught:
                        backend.main(arguments)
                    self.assertEqual(caught.exception.code,2)
                installation.assert_not_called()
                service.assert_not_called()

    def test_machine_parser_rejects_selectors_before_dispatch(self):
        commands=[['--client','clash','status'],['--client','domino','status'],
            ['status','--client','clash'],['scan','--client','clash'],
            ['--client=clash','mode','--set','global'],['clients','list'],
            ['--client','clash','status','--help'],['--client=clash','--version']]
        for arguments in commands:
            output=io.StringIO()
            with self.subTest(arguments=arguments),redirect_stdout(output):
                with patch.object(agent.subprocess,'run') as dispatch,patch.object(cli,'SSH') as ssh:
                    code=agent.main(arguments,cli)
                dispatch.assert_not_called()
                ssh.assert_not_called()
                self.assertEqual(code,2)
                result=json.loads(output.getvalue())
                self.assert_rejected(result)
                self.assertIsNone(result['operation'])

    def test_removed_operations_and_export_selector_never_dispatch(self):
        commands=[(['call',operation],None,'UNSUPPORTED_OPERATION',3)
            for operation in ['clients.list','clients.discover','clients.bind','clients.remove']]
        commands.append((['--input','-','call','bundle.export'],json.dumps({
            'output':str(self.home/'private.tar.gz'),'arch':'arm64','source_client':'clash'}),'INVALID_ARGUMENT',2))
        for arguments,payload,error,expected_code in commands:
            output=io.StringIO()
            with self.subTest(arguments=arguments),redirect_stdout(output),patch.object(agent.sys,'stdin',io.StringIO(payload or '')):
                with patch.object(agent.subprocess,'run') as dispatch,patch.object(cli,'SSH') as ssh:
                    code=agent.main(arguments,cli)
                dispatch.assert_not_called()
                ssh.assert_not_called()
                self.assertEqual(code,expected_code)
                self.assert_rejected(json.loads(output.getvalue()),error)
        self.assertEqual(list(self.home.iterdir()),[])

    def test_application_rejects_external_and_wrong_type_clients_before_any_access(self):
        application=Application(UnusedContext())
        clients=['clash','',None,False,0,[],{},['domino']]
        operations=[('capabilities',{}),('status.get',{}),('source.inspect',{}),
            ('mode.set',{'value':'global'}),('service.stop',{}),
            ('configs.add',{'name':'A','url':'https://example.test/sub'})]
        for client in clients:
            for operation,arguments in operations:
                with self.subTest(client=client,operation=operation):
                    request=self.request(client=client,request_id='old-client-request')
                    request.update(operation=operation,arguments=arguments)
                    with patch.object(application,'read') as read,patch.object(application,'revision') as revision,patch.object(application,'mutate') as mutate,patch('domino_store.OperationStore') as store:
                        result=application.execute(request)
                    self.assertEqual(result.exit_code,2)
                    self.assert_rejected(result.document())
                    read.assert_not_called()
                    revision.assert_not_called()
                    mutate.assert_not_called()
                    store.assert_not_called()

    def test_private_backend_rejects_external_and_wrong_type_clients_without_context(self):
        for client in ['clash','',None,False,0,[],{},['domino']]:
            output=io.StringIO()
            request=self.request(client=client,request_id='old-client-request')
            with self.subTest(client=client),redirect_stdout(output),patch.object(agent_backend.sys,'stdin',io.StringIO(json.dumps(request))):
                with patch('domino_store.OperationStore') as store:
                    code=agent_backend.run(UnusedContext())
                store.assert_not_called()
                self.assertEqual(code,2)
                result=agent.decode_response(output.getvalue(),'b'*32)
                self.assert_rejected(result)
                self.assertEqual(result['operation'],'mode.set')
                self.assertEqual(result['operation_id'],'a'*32)

    def test_application_rejects_removed_operation_and_export_argument_without_context(self):
        application=Application(UnusedContext())
        for operation in ['clients.list','clients.discover','clients.bind','clients.remove']:
            with self.subTest(operation=operation):
                request=self.request()
                request.update(operation=operation,arguments={})
                result=application.execute(request)
                self.assertEqual(result.exit_code,3)
                self.assert_rejected(result.document(),'UNSUPPORTED_OPERATION')
        request=self.request()
        request.update(operation='bundle.export',arguments={
            'output':str(self.home/'private.tar.gz'),'arch':'arm64','source_client':'clash'})
        result=application.execute(request)
        self.assertEqual(result.exit_code,2)
        self.assert_rejected(result.document())

    def test_capabilities_omit_removed_management_and_binding_metadata(self):
        context=SimpleNamespace(HOME=self.home,current_installation=lambda:(self.home/'app',False))
        capabilities=Application(context).capabilities()
        self.assertEqual(capabilities['client'],'domino')
        operations={item['operation']:item for item in capabilities['operations']}
        self.assertFalse(any(name.startswith('clients.') for name in operations))
        self.assertNotIn('source_client',operations['bundle.export']['parameters']['properties'])
        source_schema=operations['source.list']['result']['properties']['sources']['items']
        self.assertNotIn('clients',source_schema['properties'])
        self.assertNotIn('clients',source_schema['required'])
        for name in ['status.get','source.list','source.inspect','nodes.select','bundle.export','service.stop']:
            self.assertIn(name,operations)
        self.assertIn('client',capabilities['result_envelope']['required'])

    def test_revision_ignores_stale_binding_registry_without_deleting_it(self):
        context=SimpleNamespace(HOME=self.home,current_installation=lambda:(self.home/'app',False))
        application=Application(context)
        before=application.revision()
        registry=self.home/'.config/domino/clients.json'
        registry.parent.mkdir(parents=True)
        original='{"clash":{"config":"/private/external.json"}}'
        registry.write_text(original)
        self.assertEqual(application.revision(),before)
        self.assertEqual(registry.read_text(),original)
        registry.write_text('not valid JSON')
        self.assertEqual(application.revision(),before)
        self.assertEqual(registry.read_text(),'not valid JSON')
