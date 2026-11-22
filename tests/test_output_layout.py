"""Complete human-output contracts, including subprocesses and parent shells."""
from contextlib import redirect_stderr, redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

import domino_cli as cli
import domino_shell as shell
import install_domino as output


ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


class OutputLayoutTests(unittest.TestCase):
    def assert_frame(self,text):
        text=ANSI.sub('',text).replace('\r\n','\n')
        self.assertTrue(text.startswith('\n'),repr(text))
        self.assertFalse(text.startswith('\n\n'),repr(text))
        self.assertTrue(text.endswith('\n\n'),repr(text))
        self.assertNotRegex(text,r'\n[ \t]*\n[ \t]*\n')
        return text

    def test_nested_frames_whitespace_and_partial_prompts(self):
        result=io.StringIO()
        with redirect_stdout(result),output.human_output():
            print('\n \n\033[0m\nTitle\n\n\n')
            with output.human_output():
                print('Body\n\n\n')
            print('Choose: ',end='',flush=True)
            print('one\n\n')
        self.assertEqual(self.assert_frame(result.getvalue()),'\nTitle\n\nBody\n\nChoose: one\n\n')

    def test_long_bilingual_labels_and_continuations_share_the_value_column(self):
        for language in ('zh','en'):
            with self.subTest(language=language),patch.dict(os.environ,DOMINO_LANG=language,NO_COLOR='1'):
                result=io.StringIO()
                with redirect_stdout(result),output.human_output():
                    output.human_header('Title')
                    output.human_row('短', 'VALUE-A')
                    output.human_row('https_proxy / HTTPS_PROXY','VALUE-B')
                    output.human_row('no_proxy / NO_PROXY','X'*90,wrap=True,columns=64)
                text=self.assert_frame(result.getvalue())
                lines=text.splitlines()
                positions=[output.human_width(line.split('VALUE-')[0]) for line in lines if 'VALUE-' in line]
                self.assertEqual(positions,[29,29])
                for line in lines:
                    match=re.search('X{2,}',line)
                    if match:
                        self.assertEqual(output.human_width(line[:match.start()]),29)
                        self.assertLessEqual(output.human_width(line),64)

    def test_subprocess_sections_join_the_outer_frame_without_losing_exit_status(self):
        result=io.StringIO()
        with redirect_stdout(result),output.human_output():
            print('\nBefore\n\n')
            cli.run([sys.executable,'-c',"print('\\n\\nChild\\n\\n\\n')"])
            print('\nAfter\n')
        self.assertEqual(self.assert_frame(result.getvalue()),'\nBefore\n\nChild\n\nAfter\n\n')
        with redirect_stdout(io.StringIO()),output.human_output(),self.assertRaises(cli.ReportedCommandError) as caught:
            cli.run([sys.executable,'-c',"print('Failure');raise SystemExit(17)"],stage=cli._t('本机管理'))
        self.assertEqual(caught.exception.returncode,17)

    def test_error_after_partial_output_keeps_one_frame_and_stderr_routing(self):
        result=io.StringIO()
        with redirect_stdout(result),redirect_stderr(result),output.human_output():
            print('Before')
            output.human_error('Failure')
        self.assertEqual(self.assert_frame(result.getvalue()),'\nBefore\n\nFailure\n\n')
        result=subprocess.run([str(self.home/'bin/domino'),'select','A','--node','B'],env=self.environment,
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(result.stdout,'')
        self.assert_frame(result.stderr)
        self.assertNotIn('Traceback',result.stderr)
        for arguments in (['shell','--unknown'],['language','fr']):
            result=subprocess.run([str(self.home/'bin/domino'),*arguments],env=self.environment,
                                  capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertEqual(result.stdout,'')
            self.assert_frame(result.stderr)

    def test_prompt_without_newline_is_visible_before_child_reads_stdin(self):
        class Prompt(io.StringIO):
            def write(self,value):
                count=super().write(value)
                if 'Ready: ' in self.getvalue():os.write(write_fd,b'continue\n')
                return count
        read_fd,write_fd=os.pipe()
        self.addCleanup(os.close,write_fd)
        with os.fdopen(read_fd,'rb') as input_stream,redirect_stdout(Prompt()) as result,output.human_output():
            cli.run([sys.executable,'-c',"answer=input('Ready: ');print(answer)"],stdin=input_stream,timeout=5)
        self.assertIn('Ready: continue',result.getvalue())

    def test_dynamic_panels_and_followed_logs_bypass_the_human_frame(self):
        raw='\x1b[2Jpanel\n\n\nframe\rnext\n'
        for arguments,entry in ((['ui'],'terminal_ui'),(['traffic'],'manage'),(['logs','--follow'],'manage')):
            with self.subTest(arguments=arguments),redirect_stdout(io.StringIO()) as result, \
                    patch.object(result,'isatty',return_value=True),patch.object(sys.stdin,'isatty',return_value=True), \
                    patch.dict(os.environ,TERM='xterm-256color'),patch.object(cli,entry,side_effect=lambda *_:print(raw,end='')):
                self.assertEqual(cli.main(arguments),0)
                self.assertEqual(result.getvalue(),raw)

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='domino-output-')
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.app=self.home/'.local/share/domino'
        (self.app/'data').mkdir(parents=True)
        (self.app/'data/config.json').write_text('{"mixed-port":19876}')
        (self.app/'shell-policy.json').write_text('{"version":1,"enabled":false}')
        (self.app/'cli').mkdir()
        for name in cli.CLI_MODULES+cli.CLI_RESOURCES:
            (self.app/'cli'/name).parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(Path(cli.__file__).parent/name,self.app/'cli'/name)
        from domino_completion import SCRIPTS
        for name,text in SCRIPTS.items():
            (self.app/'cli'/('completion.'+name)).write_text(text)
        loader=self.home/'.config/domino/proxy.env'
        loader.parent.mkdir(parents=True)
        loader.write_text(shell.integration(self.app,sys.executable))
        self.loader=loader
        binary=self.home/'bin/domino'
        binary.parent.mkdir()
        binary.write_text('#!'+sys.executable+'\nimport sys\nsys.path.insert(0,'+
                          repr(str(Path(cli.__file__).parent))+')\nfrom domino_cli import main\nraise SystemExit(main())\n')
        binary.chmod(0o700)
        self.environment={k:v for k,v in os.environ.items() if k not in shell.VARIABLES and
                          not k.startswith(('DOMINO_','_DOMINO','PYTHON','BASH_ENV','ENV','ZDOTDIR'))}
        self.environment.update(HOME=str(self.home),ZDOTDIR=str(self.home),PATH=str(binary.parent)+':'+os.environ['PATH'],
                                TERM='xterm-256color',DOMINO_LANG='zh')

    def test_real_cli_human_commands_and_raw_protocols(self):
        for arguments in ([],['--help'],['list'],['scan'],['shell','status'],['shell','off'],['language']):
            with self.subTest(arguments=arguments):
                result=subprocess.run([str(self.home/'bin/domino'),*arguments],env=self.environment,
                                      capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assert_frame(result.stdout)
        for arguments in (['shell','status','--json'],['list','--json'],['--version'],['env'],['completion','--query','--','sw']):
            with self.subTest(arguments=arguments):
                result=subprocess.run([str(self.home/'bin/domino'),*arguments],env=self.environment,
                                      capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertFalse(result.stdout.startswith('\n'),repr(result.stdout))
                self.assertFalse(result.stdout.endswith('\n\n'),repr(result.stdout))
                if '--json' in arguments:json.loads(result.stdout)

    def terminal(self,name,script,*,color,columns=100):
        executable=shutil.which(name)
        if not executable:self.skipTest(name+' unavailable')
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,columns,0,0))
        flags=termios.tcgetattr(slave);flags[3]&=~termios.ECHO;termios.tcsetattr(slave,termios.TCSANOW,flags)
        environment={**self.environment,'COLUMNS':str(columns)}
        if not color:environment['NO_COLOR']='1'
        else:environment.pop('NO_COLOR',None)
        args=[executable,*(['--noprofile','--norc'] if name=='bash' else ['-f']),'-ic',script]
        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(0,termios.TIOCSCTTY,0)
        process=subprocess.Popen(args,stdin=slave,stdout=slave,stderr=slave,env=environment,cwd=self.home,
                                 preexec_fn=controlling_terminal)
        os.close(slave)
        chunks=[];deadline=time.monotonic()+25
        try:
            while time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:chunk=os.read(master,65536)
                    except OSError:break
                    if not chunk:break
                    chunks.append(chunk)
                elif process.poll() is not None:break
            self.assertEqual(process.wait(timeout=2),0,b''.join(chunks).decode(errors='replace'))
        finally:
            if process.poll() is None:process.kill();process.wait()
            os.close(master)
        return b''.join(chunks).decode(errors='replace')

    def test_complete_bash_and_zsh_transcripts_include_post_sync_footer(self):
        for name in ('bash','zsh'):
            for language in ('zh','en'):
                for color in (False,True):
                    with self.subTest(shell=name,language=language,color=color):
                        self.environment['DOMINO_LANG']=language
                        script=f'. {shlex.quote(str(self.loader))}\n'
                        script+='domino shell off\nprintf "END-OFF\\n"\n'
                        script+='domino shell status\nprintf "END-STATUS\\n"\n'
                        script+='domino shell status --json\nprintf "END-JSON\\n"\n'
                        raw=self.terminal(name,script,color=color)
                        if color:self.assertIn('\x1b[',raw)
                        else:self.assertNotIn('\x1b[',raw)
                        text=ANSI.sub('',raw).replace('\r\n','\n')
                        off,rest=text.split('END-OFF\n',1)
                        status,encoded=rest.split('END-STATUS\n',1)
                        self.assert_frame(off);self.assert_frame(status)
                        label='当前终端' if language=='zh' else 'Current terminal'
                        self.assertIn(label,status)
                        self.assertNotIn('Current shell:',status)
                        values=[]
                        for line in status.splitlines():
                            match=re.search(r'使用原有代理设置|Using previous proxy settings',line)
                            if match:values.append(output.human_width(line[:match.start()]))
                        self.assertTrue(values)
                        self.assertEqual(set(values),{18 if language=='zh' else 20})
                        encoded=encoded.split('END-JSON\n')[0]
                        self.assertFalse(encoded.startswith('\n'))
                        self.assertFalse(encoded.endswith('\n\n'))
                        json.loads(encoded)


if __name__=='__main__':unittest.main()
