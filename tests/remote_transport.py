"""Exercise real inline and streamed SSH payloads locally without an SSH server."""
import json
import shlex
import sys


ADAPTER = r'''
import sys, shlex, runpy, re
from pathlib import Path
prefix, command = sys.argv[1:3]
tokens = shlex.split(command)
exec(prefix)
if tokens[:2] == ['python3', '-c']:
    sys.argv = ['-c', *tokens[3:]]
    exec(compile(tokens[2], '<local-remote>', 'exec'))
elif tokens and tokens[0] == 'python3' and len(tokens) >= 2:
    sys.argv = tokens[1:]
    runpy.run_path(tokens[1], run_name='__main__')
elif tokens[:3] == ['rm', '-f', '--'] and len(tokens) == 4:
    if not re.fullmatch(r'/tmp/domino-command-[A-Za-z0-9_-]+\.py', tokens[3]):
        raise SystemExit('Unexpected remote cleanup path')
    Path(tokens[3]).unlink(missing_ok=True)
else:
    raise SystemExit('Unexpected local remote command')
'''


def local_command_argv(command, tty=False, *, prefix=''):
    # The command must be last: the production bridge replaces an empty command
    # with the uploaded program invocation and preserves all preceding arguments.
    return [sys.executable, '-I', '-c', ADAPTER, prefix, command]


def local_action_argv(ssh, action, *options, prefix=''):
    ssh.command_argv = lambda command, tty=False: local_command_argv(command, tty, prefix=prefix)
    return ssh.action_argv(action, *options)


def embedded_command(argv):
    """Inspect the same encoded payload regardless of its transport envelope."""
    if argv[:3] == [sys.executable, '-I', '-c']:
        setup = json.loads(argv[4])
        program = ''.join(argv[5:])
        cleanup = 'from pathlib import Path\nPath(__file__).unlink()\n'
        if not program.startswith(cleanup):
            raise AssertionError('Unexpected streamed program envelope')
        return ['python3', '-c', program[len(cleanup):], *setup['arguments']]
    return shlex.split(argv[-1])
