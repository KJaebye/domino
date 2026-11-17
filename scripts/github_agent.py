#!/usr/bin/env python3
"""Push branches and open PRs as a local GitHub App, never as the owner."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'KJaebye/domino'
STATE = Path.home() / '.local/share/domino-agent/state.json'
SERVICE = 'domino-agent/github-app'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Refusing to redirect an authenticated GitHub request')


def api(path, token, data=None, method=None):
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Expected a GitHub API path')
    request = urllib.request.Request('https://api.github.com' + path,
        data=json.dumps(data).encode() if data is not None else None,
        method=method, headers={'Authorization': 'Bearer ' + token,
            'Accept': 'application/vnd.github+json', 'User-Agent': 'domino-agent',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=45) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        # Do not echo response bodies, headers, or credentials on failure.
        raise RuntimeError('GitHub API failed: HTTP %s for %s' % (error.code, path)) from None


def load_state():
    state = json.loads(STATE.read_text())
    if state['repository'] != REPOSITORY:
        raise ValueError('This helper is restricted to ' + REPOSITORY)
    return state


def app_jwt(state):
    import jwt
    from keyring.backends.macOS import Keyring
    private_key = Keyring().get_password(SERVICE, str(state['app_id']))
    if not private_key:
        raise RuntimeError('App private key is missing from macOS Keychain')
    now = int(time.time())
    return jwt.encode({'iat': now - 60, 'exp': now + 540,
                       'iss': state['client_id']}, private_key, algorithm='RS256')


@contextmanager
def installation():
    state = load_state()
    signed = app_jwt(state)
    app = api('/app', signed)
    if app['id'] != state['app_id'] or app['slug'] != state['slug']:
        raise RuntimeError('Unexpected GitHub App identity')
    info = api('/repos/' + REPOSITORY + '/installation', signed)
    if info['id'] != state['installation_id']:
        raise RuntimeError('Unexpected GitHub App installation')
    issued = api('/app/installations/%s/access_tokens' % info['id'], signed,
        {'repositories': ['domino'],
         'permissions': {'contents': 'write', 'pull_requests': 'write'}})
    token = issued['token']
    try:
        repos = api('/installation/repositories', token)
        if repos['total_count'] != 1 or repos['repositories'][0]['full_name'] != REPOSITORY:
            raise RuntimeError('Installation token has unexpected repository access')
        yield token, app
    finally:
        try:
            api('/installation/token', token, method='DELETE')
        except Exception:
            print('Warning: token revocation failed; its GitHub expiry still applies.', file=sys.stderr)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def branch_name():
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
    if branch in ('main', 'master'):
        raise ValueError('Create a topic branch before pushing or opening a PR')
    subprocess.run(['git', 'check-ref-format', '--branch', branch], cwd=ROOT,
                   check=True, stdout=subprocess.DEVNULL)
    return branch


def push(token, branch):
    # No token in argv, remote URL, Git config, or the temporary askpass file.
    with tempfile.TemporaryDirectory(prefix='domino-agent-') as directory:
        askpass = Path(directory) / 'askpass'
        askpass.write_text('#!/bin/sh\ncase "$1" in\n'
            '*Username*) printf "%s\\n" x-access-token ;;\n'
            '*) printf "%s\\n" "$DOMINO_AGENT_TOKEN" ;;\nesac\n')
        askpass.chmod(0o700)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('GIT_TRACE', 'GIT_CONFIG_'))
               and k not in ('GIT_CURL_VERBOSE', 'GH_DEBUG')}
        env.update(DOMINO_AGENT_TOKEN=token, GIT_ASKPASS=str(askpass), GIT_TERMINAL_PROMPT='0')
        command = ['git', '-c', 'credential.helper=', '-c', 'http.extraHeader=',
                   '-c', 'http.version=HTTP/1.1']
        proxy = urllib.request.getproxies().get('https')
        if proxy:
            command += ['-c', 'http.proxy=' + proxy]
        command += ['push', 'https://github.com/' + REPOSITORY + '.git',
                    'HEAD:refs/heads/' + branch]
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        if result.returncode:
            print((result.stdout + result.stderr).replace(token, '[REDACTED]'), file=sys.stderr)
            raise RuntimeError('App branch push failed; personal authentication was not used')
    print('Pushed %s as GitHub App' % branch)


def create_pr(token, app, branch, title, body_file):
    head = api('/repos/' + REPOSITORY + '/git/ref/heads/' + branch, token)
    if head['object']['sha'] != git('rev-parse', 'HEAD'):
        raise RuntimeError('Push the current commit with this helper before creating the PR')
    pr = api('/repos/' + REPOSITORY + '/pulls', token,
             {'head': branch, 'base': 'main', 'title': title,
              'body': body_file.read_text(), 'maintainer_can_modify': True})
    if pr['user']['login'] != app['slug'] + '[bot]':
        raise RuntimeError('Unexpected PR author; inspect ' + pr['html_url'])
    print(pr['html_url'])
    print('Author: ' + pr['user']['login'] + '; waiting for human review')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('push')
    pr = commands.add_parser('pr')
    pr.add_argument('--title', required=True)
    pr.add_argument('--body-file', type=Path, required=True)
    args = parser.parse_args()
    branch = branch_name() if args.command != 'status' else None
    with installation() as (token, app):
        if args.command == 'status':
            print('Identity: %s[bot]\nRepository: %s' % (app['slug'], REPOSITORY))
        elif args.command == 'push':
            push(token, branch)
        else:
            create_pr(token, app, branch, args.title, args.body_file)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
