"""Public command grammar: target first, flat configuration management."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import domino_agent
import domino_cli as cli


class CommandSyntaxTests(unittest.TestCase):
    def parse(self, argv):
        return cli.normalize_command(cli.build_parser().parse_args(argv))

    def test_flat_config_actions_map_to_shared_backend_and_agent(self):
        cases=[(['list'],None,'configs.list'),(['add','A'],'add','configs.add'),
               (['switch','A'],'use','configs.switch'),(['update','A'],'update','configs.update'),
               (['update','all'],'update_all','configs.update_all'),(['remove','A'],'remove','configs.remove'),
               (['rename','A','B'],'rename','configs.rename'),(['set-url','A'],'set_url','configs.set-url')]
        for command,field,operation in cases:
            for prefix in [[],['user@host']]:
                with self.subTest(command=command,prefix=prefix):
                    args=self.parse([*prefix,*command])
                    self.assertEqual(args.command,'configs')
                    self.assertEqual(args.target,'user@host' if prefix else None)
                    if field:self.assertTrue(getattr(args,field))
                    self.assertEqual(domino_agent.command_request(args)[0],operation)

    def test_target_prefix_covers_every_command_family(self):
        cases=[['status'],['nodes'],['select','--group','G','--node','N'],['start'],['stop'],['restart'],
               ['logs'],['mode','--set','global'],['log'],['test','feiniao'],['traffic'],['connections'],
               ['rules'],['rules','add','DOMAIN,a.example,DIRECT'],['rules','remove','DOMAIN,a.example,DIRECT'],
               ['providers'],['proxy','on'],['shell','off'],['ui'],['env'],['rollback'],['scan'],
               ['catch','all','--yes'],['export','--arch','arm64','--output','bundle.tar.gz'],['deploy'],['plan'],['init']]
        for command in cases:
            for target in ['user@host','192.0.2.20','lab-alias','localhost']:
                with self.subTest(command=command,target=target):
                    args=self.parse([target,*command])
                    self.assertEqual(args.target,target)
                    self.assertEqual(args.command,command[0])

    def test_delay_never_guesses_a_target_from_its_local_name(self):
        for name in ['feiniao','user@host','192.0.2.20','localhost']:
            args=self.parse(['test',name])
            self.assertIsNone(args.target)
            self.assertEqual(args.name,name)
        args=self.parse(['user@host','test','feiniao'])
        self.assertEqual((args.target,args.name),('user@host','feiniao'))

    def test_different_prefix_and_suffix_targets_rejected_before_ssh(self):
        with patch.object(cli,'SSH') as ssh,redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            cli.main(['user@host','status','other@host'])
        ssh.assert_not_called()

    def test_remote_scan_and_config_management_use_ssh_backend(self):
        for arguments,action in [(['user@host','scan'],'scan'),(['user@host','list'],'configs'),
                                 (['user@host','rename','A','B'],'configs')]:
            with self.subTest(arguments=arguments),patch.object(cli,'SSH') as ssh,patch.object(cli,'collect_sources') as local:
                self.assertEqual(cli.main(arguments),0)
                self.assertEqual(ssh.return_value.__enter__.return_value.action.call_args.args[0],action)
                local.assert_not_called()

    def test_remote_full_cli_payload_runs_on_target_home_without_installed_cli(self):
        args=self.parse(['user@host','list','--batch'])
        ssh=cli.SSH(args)
        ssh.command_argv=lambda command,tty=False:['sh','-c',command]
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)/'home';home.mkdir()
            env=dict(os.environ,HOME=str(home));env.pop('PYTHONPATH',None)
            result=subprocess.run(ssh.action_argv('cli','list','--json'),cwd=directory,env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['configs'],[])
            self.assertFalse((home/'.config/domino/subscriptions/index.json').exists())

    def test_remote_source_commands_strip_transport_options_from_target_cli(self):
        with patch.object(cli,'SSH') as ssh:
            self.assertEqual(cli.main(['user@host','catch','all','--yes','--batch','--identity','/local/key']),0)
            call=ssh.return_value.__enter__.return_value.action.call_args
            self.assertEqual(call.args,('cli','catch','all','--yes','--batch'))
            self.assertFalse(call.kwargs['tty'])

    def test_remote_lifecycle_transmits_the_current_macos_implementation(self):
        import base64, bz2, shlex
        args=self.parse(['user@host','start','--batch'])
        ssh=cli.SSH(args)
        ssh.command_argv=lambda command,tty=False:shlex.split(command)
        for action in ['start','stop','restart','status','logs','overview']:
            argv=ssh.action_argv(action)
            wrapper=argv[2]
            import ast
            decode=next(node for node in ast.walk(ast.parse(wrapper)) if isinstance(node,ast.Call)
                        and isinstance(node.func,ast.Attribute) and node.func.attr=='b85decode')
            code=bz2.decompress(base64.b85decode(ast.literal_eval(decode.args[0]))).decode()
            assignment=ast.parse(code).body[2]
            modules=ast.literal_eval(assignment.value)
            self.assertEqual(modules['domino_macos'],Path(cli.__file__).with_name('domino_macos.py').read_text())
            self.assertEqual(modules['domino_linux'],Path(cli.__file__).with_name('domino_linux.py').read_text())

    def test_machine_parser_supports_prefix_and_flat_commands(self):
        for argv in [['user@host','list'],['user@host','test','feiniao'],['user@host','call','operations.list']]:
            args=cli.normalize_command(cli.build_parser(machine_mode=True).parse_args(argv))
            self.assertEqual(args.target,'user@host')
            self.assertIsInstance(domino_agent.command_request(args)[0],str)

    def test_help_advertises_flat_commands(self):
        parser=cli.build_parser()
        help_text=parser.format_help()
        for name in cli.CONFIG_COMMANDS:self.assertIn(name,help_text)
        self.assertIn('[USER@IP] COMMAND',help_text)
        self.assertNotIn('configs ',help_text)

    def test_test_command_replaces_delay_in_help_and_keeps_backend_protocol(self):
        help_text = cli.build_parser().format_help()
        self.assertIn('    test ', help_text)
        self.assertNotIn('delay', help_text)
        for command in ['test', 'delay']:
            for prefix in [[], ['user@host']]:
                for selector, operation in [([], 'delay.summary'), (['feiniao'], 'delay.test')]:
                    with self.subTest(command=command, prefix=prefix, selector=selector):
                        args = self.parse([*prefix, command, *selector])
                        self.assertEqual(args.command, 'test')
                        self.assertEqual(args.target, prefix[0] if prefix else None)
                        self.assertEqual(domino_agent.command_request(args)[0], operation)

    def test_log_command_preserves_protocol_and_rejects_the_retired_name(self):
        for prefix in [[], ['user@host']]:
            for command, operation, value in [(['log'], 'log-level.get', None),
                    (['log', 'debug'], 'log-level.set', 'debug'),
                    (['log', '--set', 'info'], 'log-level.set', 'info'),
                    *[(['log', level], 'log-level.set', level)
                      for level in ['debug', 'info', 'warning', 'error', 'silent']],
                    (['log', '--json', 'debug'], 'log-level.set', 'debug')]:
                args = self.parse([*prefix, *command])
                self.assertEqual(args.command, 'log')
                self.assertEqual(args.target, prefix[0] if prefix else None)
                self.assertEqual(domino_agent.command_request(args), (operation, {'value': value} if value else {}))
                with patch.object(cli, 'run') as run:
                    cli.manage(args)
                self.assertEqual(run.call_args.args[0][2], 'log-level')
        with patch.object(cli, 'run') as run, patch.object(cli, 'SSH') as ssh, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['log', 'debug', '--set', 'error']), 1)
            run.assert_not_called(); ssh.assert_not_called()
            for argv in [['log', 'debgu'], ['log-level'], ['log-level', 'debug'],
                         ['log-level', 'log'], ['log-level', 'logs'], ['user@host', 'log-level', 'debug']]:
                with self.assertRaises(SystemExit): cli.main(argv)
                run.assert_not_called(); ssh.assert_not_called()


if __name__=='__main__':unittest.main()
