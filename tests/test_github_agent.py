import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import github_agent as agent


class GitHubAgentTests(unittest.TestCase):
    def test_main_is_rejected_before_authentication(self):
        with patch.object(agent, 'git', return_value='main'), \
                patch.object(agent, 'installation') as authenticate:
            with self.assertRaisesRegex(ValueError, 'topic branch'):
                agent.branch_name()
            authenticate.assert_not_called()

    def test_authenticated_redirect_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'redirect'):
            agent.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com')

    def session(self, repositories=None):
        state = {'app_id': 123, 'installation_id': 456, 'slug': 'test-agent'}
        app = {'id': 123, 'slug': 'test-agent'}
        responses = [app, {'id': 456}, {'token': 'test-only-token'},
                     repositories or {'total_count': 1, 'repositories': [
                         {'full_name': agent.REPOSITORY}]}, None]
        return state, responses

    def test_token_is_scoped_and_revoked_even_on_failure(self):
        state, responses = self.session()
        with patch.object(agent, 'load_state', return_value=state), \
                patch.object(agent, 'app_jwt', return_value='test-only-jwt'), \
                patch.object(agent, 'api', side_effect=responses) as api:
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                with agent.installation():
                    raise RuntimeError('simulated operation failure')
        self.assertEqual(api.call_args_list[2].args[2], {
            'repositories': ['domino'],
            'permissions': {'contents': 'write', 'pull_requests': 'write'}})
        self.assertEqual(api.call_args.args, ('/installation/token', 'test-only-token'))
        self.assertEqual(api.call_args.kwargs, {'method': 'DELETE'})

    def test_broader_repository_access_is_rejected_and_revoked(self):
        state, responses = self.session({'total_count': 2, 'repositories': []})
        with patch.object(agent, 'load_state', return_value=state), \
                patch.object(agent, 'app_jwt', return_value='test-only-jwt'), \
                patch.object(agent, 'api', side_effect=responses) as api:
            with self.assertRaisesRegex(RuntimeError, 'unexpected repository'):
                with agent.installation():
                    self.fail('Must reject overbroad token')
        self.assertEqual(api.call_args.kwargs, {'method': 'DELETE'})

    def test_push_uses_ephemeral_credentials_without_personal_fallback(self):
        secret = 'disposable-test-token'
        def run(command, **kwargs):
            self.assertNotIn(secret, str(command))
            self.assertIn('credential.helper=', command)
            self.assertNotIn('--force', command)
            self.assertEqual(kwargs['env']['DOMINO_AGENT_TOKEN'], secret)
            self.assertNotIn('GIT_TRACE', kwargs['env'])
            askpass = Path(kwargs['env']['GIT_ASKPASS'])
            self.assertNotIn(secret, askpass.read_text())
            self.assertEqual(askpass.stat().st_mode & 0o777, 0o700)
            self.askpass = askpass
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(agent.subprocess, 'run', side_effect=run), \
                patch.dict(agent.os.environ, {'GIT_TRACE': '1'}), \
                patch.object(agent.urllib.request, 'getproxies', return_value={}):
            agent.push(secret, 'fix/example')
        self.assertFalse(self.askpass.exists())

    def test_pr_cannot_use_unpushed_commit(self):
        with patch.object(agent, 'api', return_value={'object': {'sha': 'old'}}) as api, \
                patch.object(agent, 'git', return_value='new'):
            with self.assertRaisesRegex(RuntimeError, 'Push the current commit'):
                agent.create_pr('test-only-token', {}, 'fix/example', 'Title', Path('unused'))
        self.assertEqual(api.call_count, 1)

    @unittest.skipUnless(importlib.util.find_spec('jwt') and importlib.util.find_spec('cryptography'),
                         'optional GitHub App signing dependencies are not installed')
    def test_app_jwt_is_signed_with_keychain_key(self):
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        backend = SimpleNamespace(Keyring=lambda: SimpleNamespace(get_password=lambda *args: pem))
        with patch.dict(sys.modules, {'keyring.backends.macOS': backend}), \
                patch.object(agent.time, 'time', return_value=1000000):
            encoded = agent.app_jwt({'app_id': 123, 'client_id': 'test-client'})
        claims = jwt.decode(encoded, key.public_key(), algorithms=['RS256'],
                            options={'verify_exp': False})
        self.assertEqual(claims, {'iat': 999940, 'exp': 1000540, 'iss': 'test-client'})


if __name__ == '__main__':
    unittest.main()
