from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import hashlib
import platform
import shutil
import tarfile
import unittest
from unittest.mock import patch

import domino_cli as cli
import domino_agent as agent
import install_domino as backend
from domino_model import DomainError, Result
from domino_service import Application, OPERATIONS, validate
from domino_store import OperationStore


class AgentProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home=Path(self.directory.name)

    def run_agent(self, arguments, data=None):
        process=subprocess.run([sys.executable,str(Path(cli.__file__)),'--output','json',*arguments],
            input=data,capture_output=True,text=True,env={**os.environ,'HOME':str(self.home)},timeout=15)
        result=json.loads(process.stdout)
        self.assertEqual(result['schema_version'],1)
        self.assertNotIn('\x1b',process.stdout)
        return process,result

    def test_capabilities_work_without_installation_or_tty(self):
        process,result=self.run_agent(['capabilities'])
        self.assertEqual(process.returncode,0)
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['installed'])
        entries={item['operation']:item for item in result['data']['operations']}
        self.assertTrue(entries['status.get']['available'])
        self.assertFalse(entries['nodes.list']['available'])
        self.assertIn('parameters',entries['rules.list'])
        self.assertIn('configs.list',entries)
        self.assertFalse(any(name.startswith('subs.') for name in entries))
        self.assertFalse(result['changed'])

    def test_scan_works_without_installation_and_matches_direct_call(self):
        config = self.home / '.config/mihomo/config.yaml'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'proxies': [
            {'name': 'A', 'type': 'socks5', 'server': 'node.example', 'port': 1080, 'password': 'PRIVATE-NODE'}]}))
        for command in [['scan'], ['call', 'source.list']]:
            process, result = self.run_agent(command)
            self.assertEqual(process.returncode, 0, result)
            self.assertTrue(result['ok'])
            self.assertEqual(result['operation'], 'source.list')
            self.assertFalse(result['changed'])
            self.assertEqual(len(result['data']['sources']), 1)
            self.assertEqual(result['data']['sources'][0]['config'], str(config))
            self.assertTrue(result['data']['sources'][0]['compatible_config_found'])
            self.assertFalse(result['data']['sources'][0]['healthy'])
            self.assertFalse(result['data']['sources'][0]['exit_checked'])
            self.assertNotIn('PRIVATE', process.stdout + process.stderr)

    def test_scan_rejects_removed_client_selector_and_commands(self):
        process, result = self.run_agent(['--client', 'missing', 'scan'])
        self.assertIsNone(result['operation'])
        self.assertEqual(result['client'], 'domino')
        self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
        self.assertEqual(process.returncode, 2)
        for command in [['source'], ['source', 'list']]:
            process, result = self.run_agent(command)
            self.assertEqual(process.returncode, 2, result)
            self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')

    def test_shell_status_without_installation_is_read_only_policy_status(self):
        process, result = self.run_agent(['shell', 'status'])
        self.assertEqual(process.returncode, 0, result)
        self.assertEqual(result['operation'], 'shell.status')
        self.assertFalse(result['data']['enabled'])
        self.assertTrue(result['data']['policy_only'])
        self.assertFalse(result['data']['current_shell_applied'])
        self.assertFalse(result['changed'])
        self.assertEqual(list(self.home.iterdir()), [])
        process, result = self.run_agent(['shell', 'stop'])
        self.assertEqual(process.returncode, 2, result)
        self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')

    def test_shell_policy_machine_dry_run_revisions_replay_and_noop(self):
        app = self.home / '.local/share/domino'
        (app / 'data').mkdir(parents=True)
        (app / 'data/config.json').write_text(json.dumps({'mixed-port': 17890}))
        (app / 'mihomo').touch()
        policy = app / 'shell-policy.json'
        process, preview = self.run_agent(['--dry-run', 'shell', 'on'])
        self.assertEqual(process.returncode, 0, preview)
        self.assertTrue(preview['data']['would_change'])
        self.assertTrue(preview['data']['policy_only'])
        self.assertFalse(preview['data']['current_shell_applied'])
        self.assertFalse(policy.exists())
        self.assertFalse((self.home / '.local/state/domino/operations').exists())
        process, conflict = self.run_agent(['--if-revision', '0' * 64, 'shell', 'on'])
        self.assertEqual(process.returncode, 6, conflict)
        self.assertEqual(conflict['error']['code'], 'REVISION_CONFLICT')
        self.assertFalse(policy.exists())
        process, enabled = self.run_agent(['--if-revision', preview['revision'], '--request-id', 'shell-on', 'shell', 'on'])
        self.assertEqual(process.returncode, 0, enabled)
        self.assertTrue(enabled['changed'])
        self.assertTrue(enabled['data']['enabled'])
        self.assertTrue(enabled['data']['policy_only'])
        self.assertFalse(enabled['data']['current_shell_applied'])
        self.assertNotEqual(enabled['revision'], preview['revision'])
        self.assertEqual(policy.stat().st_mode & 0o077, 0)
        process, noop = self.run_agent(['shell', 'on'])
        self.assertEqual(process.returncode, 0, noop)
        self.assertFalse(noop['changed'])
        process, disabled = self.run_agent(['shell', 'off'])
        self.assertEqual(process.returncode, 0, disabled)
        self.assertTrue(disabled['changed'])
        self.assertFalse(disabled['data']['enabled'])
        # Request replay returns the original outcome, not a second application.
        process, replay = self.run_agent(['--request-id', 'shell-on', 'shell', 'on'])
        self.assertEqual(process.returncode, 0, replay)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['operation_id'], enabled['operation_id'])
        self.assertFalse(json.loads(policy.read_text())['enabled'])
        process, noop = self.run_agent(['shell', 'off'])
        self.assertEqual(process.returncode, 0, noop)
        self.assertFalse(noop['changed'])

    def test_shell_policy_invalid_state_fails_without_overwrite(self):
        app = self.home / '.local/share/domino'
        (app / 'data').mkdir(parents=True)
        (app / 'mihomo').touch()
        (app / 'data/config.json').write_text('{"mixed-port": true}')
        policy = app / 'shell-policy.json'
        for flags in [[], ['--dry-run']]:
            process, result = self.run_agent([*flags, 'shell', 'on'])
            self.assertNotEqual(process.returncode, 0, result)
            self.assertEqual(result['error']['code'], 'SHELL_POLICY_INVALID')
            self.assertFalse(policy.exists())
        policy.write_text('PRIVATE-INVALID-POLICY')
        for action in ['status', 'off']:
            process, result = self.run_agent(['shell', action])
            self.assertNotEqual(process.returncode, 0, result)
            self.assertEqual(result['error']['code'], 'SHELL_POLICY_INVALID')
            self.assertNotIn('PRIVATE', process.stdout + process.stderr)
            self.assertEqual(policy.read_text(), 'PRIVATE-INVALID-POLICY')

    def test_embedded_remote_shell_policy_runs_without_checkout_or_caller_changes(self):
        app = self.home / '.local/share/domino'
        (app / 'data').mkdir(parents=True)
        (app / 'data/config.json').write_text('{"mixed-port":17890}')
        (app / 'mihomo').touch()
        ssh = cli.SSH(cli.build_parser().parse_args(['shell', 'on', 'alice@host', '--batch']))
        ssh.socket = '/tmp/not-used'
        command = shlex.split(ssh.action_argv('agent')[-1])
        request = {'schema_version': 1, 'operation': 'shell.on', 'arguments': {}, 'target': 'alice@host',
                   'operation_id': 'a' * 32, 'transport_token': 'b' * 32}
        inherited = dict(os.environ)
        process = subprocess.run([sys.executable, *command[1:]], input=json.dumps(request),
            capture_output=True, text=True, cwd=self.home, env={**os.environ, 'HOME': str(self.home)}, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = agent.decode_response(process.stdout, 'b' * 32)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['data']['enabled'])
        self.assertFalse(result['data']['current_shell_applied'])
        self.assertEqual(dict(os.environ), inherited)

    def test_unknown_proxy_action_returns_invalid_argument(self):
        process, result = self.run_agent(['proxy', 'stop'])
        self.assertEqual(process.returncode, 2, result)
        self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
        self.assertEqual(process.stderr, '')

    def test_remote_write_and_replay_use_the_same_protocol_without_installed_cli(self):
        args=cli.build_parser().parse_args(['status','alice@host','--batch'])
        ssh=cli.SSH(args)
        ssh.socket='/tmp/not-used'
        command=shlex.split(ssh.action_argv('agent')[-1])
        self.assertLess(len(ssh.action_argv('agent')[-1].encode()),128*1024-256)
        with self.assertRaises(cli.ToolError):ssh.action_argv('agent','x'*131072)
        request={'schema_version':1,'operation':'configs.add','arguments':{'name':'A','url':'https://example.test/PRIVATE-TOKEN'},
            'target':'alice@host','operation_id':'a'*32,'transport_token':'b'*32,'request_id':'remote-add'}
        def run():
            process=subprocess.run([sys.executable,*command[1:]],input=json.dumps(request),capture_output=True,text=True,
                cwd=self.home,env={**os.environ,'HOME':str(self.home)},timeout=15)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertNotIn('PRIVATE-TOKEN',process.stdout+process.stderr)
            return agent.decode_response(process.stdout,'b'*32)
        first=run()
        request['operation_id']='c'*32
        second=run()
        self.assertEqual(first['operation_id'],second['operation_id'])
        self.assertTrue(second['replayed'])
        self.assertEqual(second['target'],'alice@host')

    def test_unhealthy_state_is_a_successful_query_and_legacy_exit_codes_remain_separate(self):
        process,result=self.run_agent(['status'])
        self.assertEqual(process.returncode,0)
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['installed'])
        self.assertFalse(result['data']['healthy'])

    def test_installed_runpy_launcher_supports_machine_mode(self):
        process=subprocess.run([sys.executable,'-c','import runpy;runpy.run_module("domino_cli",run_name="__main__")',
            '--output','json','capabilities'],capture_output=True,text=True,env={**os.environ,'HOME':str(self.home)},cwd=Path(cli.__file__).parent,timeout=15)
        result=json.loads(process.stdout)
        self.assertEqual(process.returncode,0,result)
        self.assertTrue(result['ok'])
        self.assertIn('result_envelope',result['data'])

    def test_missing_runtime_returns_a_structured_precondition_error(self):
        process,result=self.run_agent(['nodes'])
        self.assertEqual(process.returncode,3)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'],'NOT_INSTALLED')
        self.assertEqual(result['effect'],'none')

    def test_parameter_failures_never_echo_sensitive_values(self):
        for arguments in [['delay','--timeout','PRIVATE-TOKEN'],['mode','--set','PRIVATE-TOKEN'],['missing-command']]:
            process,result=self.run_agent(arguments)
            self.assertEqual(process.returncode,2)
            self.assertEqual(result['error']['code'],'INVALID_ARGUMENT')
            self.assertNotIn('PRIVATE-TOKEN',process.stdout+process.stderr)
            self.assertNotIn('unknown-private-secret',process.stdout+process.stderr)

    def test_input_validation_and_unsupported_protocol_are_json_errors(self):
        process,result=self.run_agent(['--input','-','capabilities'],'{"extra":"PRIVATE-TOKEN"}')
        self.assertEqual(process.returncode,2)
        self.assertNotIn('PRIVATE-TOKEN',process.stdout+process.stderr)
        process,result=self.run_agent(['--protocol-version','99','capabilities'])
        self.assertEqual(result['error']['code'],'UNSUPPORTED_PROTOCOL')
        self.assertEqual(process.returncode,2)

    def test_remote_program_runs_from_memory_without_a_source_workspace(self):
        args=cli.build_parser().parse_args(['status','alice@host','--batch'])
        ssh=cli.SSH(args)
        ssh.socket='/tmp/not-used'
        command=shlex.split(ssh.action_argv('agent')[-1])
        request={'schema_version':1,'operation':'capabilities','arguments':{},'target':'alice@host',
                 'operation_id':'a'*32,'transport_token':'b'*32}
        process=subprocess.run([sys.executable,*command[1:]],input=json.dumps(request),capture_output=True,text=True,
            cwd=self.home,env={**os.environ,'HOME':str(self.home)},timeout=15)
        self.assertEqual(process.returncode,0,process.stderr)
        result=agent.decode_response(process.stdout,'b'*32)
        self.assertTrue(result['ok'])
        self.assertEqual(result['target'],'alice@host')
        self.assertFalse(result['data']['installed'])

    def test_transport_framing_excludes_login_banner_and_rejects_ambiguous_results(self):
        document=Result('capabilities',operation_id='a'*32).document()
        wire='PRIVATE-BANNER\nDOMINO_RPC_abc\n'+json.dumps(document)+'\nDOMINO_RPC_abc\n'
        self.assertEqual(agent.decode_response(wire,'abc'),document)
        with self.assertRaises(Exception): agent.decode_response(wire+wire,'abc')

    def test_private_subscription_write_replay_and_stable_id_rename(self):
        payload=json.dumps({'name':'A','url':'https://example.test/sub?token=PRIVATE-TOKEN'})
        process,first=self.run_agent(['--input','-','--request-id','add-A','call','configs.add'],payload)
        self.assertEqual(process.returncode,0,first)
        identifier=first['data']['configs'][0]['id']
        self.assertEqual(first['effect'],'applied')
        self.assertNotIn('PRIVATE-TOKEN',process.stdout+process.stderr)
        process,replayed=self.run_agent(['--input','-','--request-id','add-A','call','configs.add'],payload)
        self.assertEqual(process.returncode,0,replayed)
        self.assertTrue(replayed['replayed'])
        self.assertEqual(first['operation_id'],replayed['operation_id'])
        self.assertEqual(len(replayed['data']['configs']),1)
        process,renamed=self.run_agent(['--input','-','call','configs.rename'],json.dumps({'id':identifier,'new_name':'B'}))
        self.assertEqual(process.returncode,0,renamed)
        self.assertEqual(renamed['data']['configs'][0]['id'],identifier)
        process,conflict=self.run_agent(['--input','-','--request-id','add-A','call','configs.add'],payload.replace('"A"','"C"'))
        self.assertEqual(process.returncode,6,conflict)
        self.assertEqual(conflict['error']['code'],'REQUEST_CONFLICT')
        records=self.home/'.local/state/domino/operations'
        for path in records.rglob('*.json'):
            self.assertEqual(path.stat().st_mode & 0o077,0)
            self.assertNotIn('PRIVATE-TOKEN',path.read_text())

    def test_dry_run_and_revision_conflict_never_mutate_subscription_registry(self):
        payload=json.dumps({'name':'A','url':'https://example.test/sub'})
        process,preview=self.run_agent(['--dry-run','--input','-','call','configs.add'],payload)
        self.assertEqual(process.returncode,0,preview)
        self.assertTrue(preview['data']['dry_run'])
        self.assertFalse((self.home/'.config/domino/subscriptions/index.json').exists())
        self.assertFalse((self.home/'.local/state/domino/operations').exists())
        process,conflict=self.run_agent(['--if-revision','0'*64,'--input','-','call','configs.add'],payload)
        self.assertEqual(process.returncode,6,conflict)
        self.assertEqual(conflict['error']['code'],'REVISION_CONFLICT')
        process,applied=self.run_agent(['--if-revision',preview['revision'],'--input','-','call','configs.add'],payload)
        self.assertEqual(process.returncode,0,applied)
        process,record=self.run_agent(['--input','-','call','operations.get'],json.dumps({'id':applied['operation_id']}))
        self.assertEqual(process.returncode,0,record)
        self.assertEqual(record['data']['state'],'complete')
        self.assertEqual(record['data']['result']['operation_id'],applied['operation_id'])
        process,by_key=self.run_agent(['--input','-','call','operations.get'],json.dumps({'request_id':applied['operation_id']}))
        self.assertEqual(process.returncode,0,by_key)
        self.assertEqual(by_key['data']['operation_id'],applied['operation_id'])

    def test_missing_private_input_does_not_prompt(self):
        process,result=self.run_agent(['configs','add','A'])
        self.assertEqual(process.returncode,2,result)
        self.assertEqual(result['error']['code'],'MISSING_ARGUMENT')

    def test_private_file_permissions_are_checked(self):
        path=self.home/'input.json'
        path.write_text('{"name":"A","url":"https://example.test/PRIVATE-TOKEN"}')
        path.chmod(0o644)
        process,result=self.run_agent(['--input',str(path),'call','configs.add'])
        self.assertEqual(process.returncode,2,result)
        self.assertNotIn('PRIVATE-TOKEN',process.stdout+process.stderr)


class SavedProfileAgentTests(unittest.TestCase):
    # Inject only network guards; execute the real machine/embedded request pipeline.
    guard = '''
def probe_source(*args, **kwargs):
    raise AssertionError("Saved profiles must not probe a proxy")
def discover_proxy():
    return "http://user:PRIVATE-ENV@127.0.0.1:7897"
'''

    def setUp(self):
        AgentProcessTests.setUp(self)
        self.home = self.home.resolve()
        root = self.home / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        self.saved = root / 'profiles/saved.yaml'
        self.saved.parent.mkdir(parents=True)
        self.saved.write_text(json.dumps({'mixed-port': 7897, 'secret': 'PRIVATE-CONTROLLER',
            'proxies': [{'name': 'A', 'type': 'socks5', 'server': 'node.example',
                         'port': 1080, 'password': 'PRIVATE-NODE'}]}))
        self.index = root / 'profiles.yaml'
        self.index.write_text(json.dumps({'current': 'saved-1', 'items': [
            {'uid': 'saved-1', 'type': 'remote', 'name': 'Saved subscription', 'file': 'saved.yaml',
             'url': 'https://subscription.example/?token=PRIVATE-URL'}]}))
        self.runtime = self.home / '.config/mihomo/config.yaml'
        self.runtime.parent.mkdir(parents=True)
        self.runtime.write_text(self.saved.read_text().replace('"mixed-port": 7897, ', ''))

    def assert_result_schema(self, value, schema):
        # Keep result-schema checks independent of the request validator's subset.
        schema = dict(schema)
        if isinstance(schema.get('type'), list):
            actual = {str: 'string', bool: 'boolean', type(None): 'null'}.get(type(value))
            self.assertIn(actual, schema['type'])
            schema['type'] = actual
            if actual == 'null':
                schema.pop('type')
        properties = schema.get('properties', {})
        shallow = dict(schema)
        if properties:
            shallow['properties'] = dict.fromkeys(properties, {})
        validate(value, shallow)
        if isinstance(value, dict):
            for key, item in value.items():
                if key in properties:
                    self.assert_result_schema(item, properties[key])
        if isinstance(value, list) and 'items' in schema:
            for item in value:
                self.assert_result_schema(item, schema['items'])

    def run_source(self, arguments, data=None):
        code = ('import sys;sys.path.insert(0,' + repr(str(Path(cli.__file__).parent)) + ');'
                'import domino_cli as cli\nexec(' + repr(self.guard) + ',cli.__dict__)\n'
                'raise SystemExit(cli.main(sys.argv[1:]))')
        process = subprocess.run([sys.executable, '-c', code, '--output', 'json', *arguments],
            input=data, capture_output=True, text=True, cwd=self.home,
            env={**os.environ, 'HOME': str(self.home), 'HTTPS_PROXY': 'http://user:PRIVATE-ENV@127.0.0.1:7897'}, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertNotIn('PRIVATE', process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['changed'])
        self.assertEqual(result['schema_version'], 1)
        self.assert_result_schema(result['data'], OPERATIONS[result['operation']]['result'])
        return result

    def assert_saved(self, row):
        self.assertEqual(row['config'], str(self.saved))
        self.assertEqual(row['source_kind'], 'profile')
        self.assertEqual(row['profile_id'], 'saved-1')
        self.assertEqual(row['profile_name'], 'Saved subscription')
        self.assertIs(row['client_current'], True)
        self.assertTrue(row['compatible_config_found'])
        self.assertIsNone(row['proxy'])
        self.assertFalse(row['healthy'])
        self.assertFalse(row['exit_checked'])
        self.assertTrue(row['check_note'])

    def test_machine_scan_list_and_explicit_inspect_validate_saved_metadata_without_installation(self):
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        for arguments in [['scan'], ['call', 'source.list']]:
            result = self.run_source(arguments)
            self.assertEqual(result['operation'], 'source.list')
            rows = result['data']['sources']
            self.assertEqual([row['config'] for row in rows], [str(self.runtime), str(self.saved)])
            self.assertEqual([row['default'] for row in rows], [True, False])
            self.assert_saved(rows[1])
        for arguments, data in [(['scan', '--source', str(self.saved)], None),
                                (['--input', '-', 'call', 'source.inspect'], json.dumps({'path': str(self.saved)}))]:
            result = self.run_source(arguments, data)
            self.assertEqual(result['operation'], 'source.inspect')
            self.assert_saved(result['data'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_machine_list_keeps_runtime_and_redacts_invalid_index_warning(self):
        self.index.write_bytes(b'\xffhttps://private.example/?password=PRIVATE-INDEX')
        result = self.run_source(['call', 'source.list'])
        self.assertEqual([row['config'] for row in result['data']['sources']], [str(self.runtime)])
        self.assertTrue(result['data']['warnings'])
        self.assertNotIn('https://private.example', json.dumps(result))

    def test_embedded_ssh_list_and_inspect_include_saved_profiles_without_checkout(self):
        ssh = cli.SSH(cli.build_parser().parse_args(['status', 'alice@host', '--batch']))
        ssh.socket = '/tmp/not-used'
        read_text = Path.read_text
        def guarded_source(path, *args, **kwargs):
            source = read_text(path, *args, **kwargs)
            return source + self.guard if path.name == 'domino_cli.py' else source
        with patch.object(Path, 'read_text', guarded_source):
            command = shlex.split(ssh.action_argv('agent')[-1])
        for operation, arguments in [('source.list', {}), ('source.inspect', {'path': str(self.saved)})]:
            request = {'schema_version': 1, 'operation': operation, 'arguments': arguments,
                       'target': 'alice@host', 'operation_id': 'a' * 32, 'transport_token': 'b' * 32}
            process = subprocess.run([sys.executable, *command[1:]], input=json.dumps(request),
                capture_output=True, text=True, cwd=self.home, env={**os.environ, 'HOME': str(self.home)}, timeout=15)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertNotIn('PRIVATE', process.stdout + process.stderr)
            result = agent.decode_response(process.stdout, 'b' * 32)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['changed'])
            self.assertEqual(result['target'], 'alice@host')
            self.assert_result_schema(result['data'], OPERATIONS[operation]['result'])
            row = result['data']['sources'][1] if operation == 'source.list' else result['data']
            self.assert_saved(row)


class OperationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home=Path(self.directory.name)
        self.patch=patch.multiple(backend,HOME=self.home,APP=self.home/'.local/share/domino',LEGACY_APP=self.home/'legacy')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.application=Application(backend)

    def request(self,**extra):
        return dict(schema_version=1,operation='configs.add',arguments={'name':'A','url':'https://example.test/sub'},
                    operation_id='a'*32,target='localhost',**extra)

    def test_source_metadata_and_active_marker_change_optimistic_revision(self):
        data = self.home / '.local/share/domino/data'
        data.mkdir(parents=True)
        initial = self.application.revision()
        (data / 'subscription.json').write_text(json.dumps({'id': 'c' * 32}))
        associated = self.application.revision()
        self.assertNotEqual(initial, associated)
        source = data / 'source'
        source.mkdir()
        (source / 'metadata.json').write_text(json.dumps({'test': 'source-metadata'}))
        recorded = self.application.revision()
        self.assertNotEqual(associated, recorded)
        (source / 'config.json').write_text(json.dumps({'proxies': []}))
        self.assertNotEqual(recorded, self.application.revision())

    def test_explicit_domino_identity_replays_request_omitting_client(self):
        first=self.application.execute(self.request(request_id='own-client'))
        self.assertTrue(first.document()['ok'],first.document())
        request=self.request(request_id='own-client',client='domino')
        request['operation_id']='b'*32
        with patch.object(self.application,'write') as write:
            replayed=self.application.execute(request)
        write.assert_not_called()
        self.assertTrue(replayed.replayed)
        self.assertEqual(replayed.operation_id,first.operation_id)
        self.assertEqual(replayed.client,'domino')

    def test_incomplete_record_blocks_automatic_repeat(self):
        with patch.object(self.application,'write',side_effect=KeyboardInterrupt):
            result=self.application.execute(self.request(request_id='same'))
        self.assertEqual(result.effect,'unknown')
        self.assertIsNone(result.changed)
        store=OperationStore(backend)
        record=store.load('a'*32)
        record['state']='applying'
        store.save(record)
        request=self.request(request_id='same')
        request['operation_id']='b'*32
        with patch.object(self.application,'write') as write:
            result=self.application.execute(request)
        self.assertEqual(result.error.code,'OPERATION_UNCERTAIN')
        self.assertEqual(result.operation_id,'a'*32)
        write.assert_not_called()

    def test_batch_reports_unattempted_items_after_uncertain_failure(self):
        from types import SimpleNamespace
        manager=SimpleNamespace(registry={'items':[{'id':str(i),'name':str(i),'url':'https://example.test'} for i in range(3)]})
        def update(item):
            if item['id']=='1': raise DomainError('uncertain',effect='unknown')
        manager.update=update
        with patch.object(self.application,'manager',return_value=manager):
            with self.assertRaises(DomainError) as caught:
                self.application.write('configs.update_all',{}, {})
        self.assertEqual(caught.exception.exit_code,9)
        outcomes=caught.exception.details['results']
        self.assertEqual([item['effect'] for item in outcomes],['applied','unknown','none'])
        self.assertEqual(outcomes[-1]['error']['code'],'NOT_ATTEMPTED')

    def bundle(self):
        directory=self.home/'fixture'
        (directory/'data').mkdir(parents=True)
        (directory/'mihomo').write_text('fixture')
        (directory/'selections.json').write_text('{}')
        (directory/'data/config.json').write_text(json.dumps({'mixed-port':17897,'external-controller':'127.0.0.1:19091'}))
        (directory/'manifest.json').write_text(json.dumps({'platform':platform.system().lower(),
            'arch':cli.normalize_arch(platform.machine()),'version':'v1.2.3','proxy_port':17897,'api_port':19091}))
        archive=self.home/'bundle.tar.gz'
        with tarfile.open(archive,'w:gz') as bundle:
            for path in directory.iterdir(): bundle.add(path,arcname=path.name)
        archive.chmod(0o600)
        return {'bundle':str(archive),'bundle_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}

    def test_install_preview_validates_bundle_without_service_changes(self):
        request=self.request(dry_run=True)
        request.update(operation='service.install',arguments=self.bundle())
        with patch.object(backend,'run') as validate,patch.object(backend,'install') as install:
            result=self.application.execute(request)
        self.assertTrue(result.document()['ok'],result.document())
        self.assertFalse(result.changed)
        validate.assert_called_once()
        install.assert_not_called()
        self.assertFalse((self.home/'.local/share/domino').exists())
        self.assertFalse(OperationStore(backend).root.exists())

    def test_install_journal_survives_replacing_application_directory(self):
        request=self.request(request_id='install-1')
        request.update(operation='service.install',arguments=self.bundle())
        def replace_app(ctx,directory):
            shutil.rmtree(backend.APP,ignore_errors=True)
            backend.APP.mkdir(parents=True)
        import domino_macos
        with patch.object(backend,'run'),patch.object(domino_macos,'install',side_effect=replace_app),patch.object(backend,'install',side_effect=lambda directory:replace_app(backend,directory)),patch.object(backend,'collect_status',return_value={'installed':True}),patch.object(self.application,'revision',side_effect=['1'*64,'2'*64]):
            result=self.application.execute(request)
        self.assertEqual(result.effect,'applied',result.document())
        record=OperationStore(backend).find('install-1')
        self.assertEqual(record['state'],'complete')
        with patch.object(self.application,'write') as write:
            replayed=self.application.execute(dict(request,operation_id='b'*32))
        write.assert_not_called()
        self.assertTrue(replayed.replayed)

    def test_export_writes_private_archive_and_replay_does_not_build_again(self):
        archive=self.bundle()
        source=self.home/'source.json'
        source.write_text(json.dumps({'mode':'rule','proxies':[{'name':'A','type':'socks5','server':'example.test','port':1080}],'rules':['MATCH,DIRECT']}))
        output=self.home/'export.tar.gz'
        request=self.request(request_id='export-1')
        request.update(operation='bundle.export',arguments={'source':str(source),'arch':'arm64','output':str(output)})
        prepared=(Path(archive['bundle']),{'version':'v1.2.3','arch':'arm64','platform':'linux'})
        with patch.object(cli,'prepare',return_value=prepared) as build:
            result=self.application.execute(request)
            replayed=self.application.execute(dict(request,operation_id='b'*32))
        self.assertTrue(result.document()['ok'],result.document())
        self.assertTrue(result.changed)
        self.assertEqual(output.stat().st_mode & 0o077,0)
        self.assertEqual(result.data['bundle_sha256'],archive['bundle_sha256'])
        build.assert_called_once()
        self.assertTrue(replayed.replayed)
        request['request_id']='different-export'
        request['operation_id']='c'*32
        with patch.object(cli,'prepare') as build:
            conflict=self.application.execute(request)
        build.assert_not_called()
        self.assertEqual(conflict.error.code,'OUTPUT_EXISTS')


class ServiceSeparationTests(unittest.TestCase):
    def test_service_preview_accounts_for_system_proxy_even_when_service_already_running_or_stopped(self):
        from types import SimpleNamespace
        import domino_macos
        with tempfile.TemporaryDirectory() as directory:
            app=Path(directory);(app/'data').mkdir()
            (app/'data/config.json').write_text('{"mixed-port":17897}')
            ctx=SimpleNamespace(HOME=app,current_installation=lambda:(app,None),systemctl=lambda _:True)
            application=Application(ctx)
            with patch('domino_service.platform.system',return_value='Darwin'), \
                    patch.object(domino_macos,'system_proxy_overview',return_value={'routing':'off'}):
                self.assertTrue(application.plan('service.start',{})['would_change'])
            ctx.systemctl=lambda _:False
            with patch('domino_service.platform.system',return_value='Darwin'), \
                    patch.object(domino_macos,'system_proxy_overview',return_value={'routing':'domino'}):
                self.assertTrue(application.plan('service.stop',{})['would_change'])
            with patch('domino_service.platform.system',return_value='Linux'):
                self.assertFalse(application.plan('service.stop',{})['would_change'])

    def test_query_collectors_return_data_without_terminal_output(self):
        output=io.StringIO()
        with patch.object(backend,'proxy_state',return_value=({'mode':'rule'},{'A':{'type':'Trojan'}})),redirect_stdout(output):
            result=backend.collect_nodes()
        self.assertEqual(result['nodes'],[{'name':'A','type':'Trojan'}])
        self.assertEqual(output.getvalue(),'')
        with patch.object(backend,'api_json',return_value={'rules':[]}),redirect_stdout(output):
            self.assertEqual(backend.collect_rules(),{'total':0,'rules':[]})
        self.assertEqual(output.getvalue(),'')
