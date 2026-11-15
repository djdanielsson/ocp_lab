"""Application API boundaries; all credentials and APIs here are synthetic."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
import applications
from reconcile import ReconcileError


class AAPSSO(unittest.TestCase):
    def run_configuration(self, callback, existing=False):
        self.calls = []
        auth = {'id': 12, 'name': 'Lab SSO', 'configuration': {'CALLBACK_URL': callback}}
        class Fake:
            def request(fake, method, path, body=None, **kwargs):
                self.calls.append((method, path, body))
                if 'authenticators/?' in path:
                    return {'results': [auth] if existing else []}
                if 'authenticators/' in path:
                    return auth
                if 'authenticator_maps/?' in path:
                    return {'results': []}
                if path.endswith('settings/all/'):
                    return {'ALLOW_OAUTH2_FOR_EXTERNAL_USERS': False}
                if 'openid-connect/token' in path:
                    return {'access_token': 'test-token'}
        settings = {'issuer': 'https://idp.example.test/realms/lab', 'realm': 'lab',
                    'applications': {'aap': {'url': 'https://aap.example.test'}}}
        self.client = MagicMock()
        with patch.object(applications, 'API', return_value=Fake()), patch.object(applications, 'kube_secret', return_value='admin-test-password'), patch.object(applications, 'read_secret', return_value='machine-test-password'), patch.object(applications, 'upsert_client', self.client):
            applications.configure_aap(object(), settings)

    def test_registers_only_gateway_generated_exact_callback(self):
        callback = 'https://aap.example.test/api/gateway/social/complete/lab-sso-42/'
        self.run_configuration(callback)
        client = self.client.call_args.args[2]
        self.assertEqual(client['redirectUris'], [callback])
        self.assertNotIn('*', callback)
        body = next(body for method, path, body in self.calls if method == 'POST' and path.endswith('authenticators/'))
        self.assertTrue(body['configuration']['VERIFY_SSL'])
        maps = [body for method, path, body in self.calls if path.endswith('authenticator_maps/')]
        admin = next(body for body in maps if body['map_type'] == 'is_superuser')
        self.assertEqual(admin['triggers'], {'groups': {'has_or': ['lab-admins']}})
        self.assertTrue(admin['revoke'])
        self.assertTrue(any(method == 'PATCH' and path.endswith('settings/all/') and body == {'ALLOW_OAUTH2_FOR_EXTERNAL_USERS': True} for method, path, body in self.calls))

    def test_existing_authenticator_keeps_identity(self):
        self.run_configuration('https://aap.example.test/api/gateway/social/complete/existing/', existing=True)
        self.assertTrue(any(method == 'PATCH' and path.endswith('authenticators/12/') for method, path, _ in self.calls))
        self.assertFalse(any(method == 'POST' and path.endswith('authenticators/') for method, path, _ in self.calls))

    def test_cross_origin_callback_is_rejected(self):
        with self.assertRaisesRegex(ReconcileError, 'unexpected OIDC callback'):
            self.run_configuration('https://attacker.example.test/api/gateway/social/complete/lab/')
        self.client.assert_not_called()


class VaultSSO(unittest.TestCase):
    def configure(self, sealed=False, mount_type='oidc'):
        self.calls = []
        class Fake:
            def request(fake, method, path, body=None, **kwargs):
                self.calls.append((method, path, body))
                if path.endswith('seal-status'):
                    return {'initialized': True, 'sealed': sealed}
                if path == '/v1/sys/auth':
                    return {'data': {'oidc/': {'type': mount_type}}}
        self.api = MagicMock(return_value=Fake())
        settings = {'issuer': 'https://idp.example.test/realms/lab',
                    'applications': {'vault': {'url': 'http://vault.vault.svc:8200', 'publicUrl': 'https://vault.example.test'}}}
        with patch.object(applications, 'API', self.api), patch.object(applications, 'kube_secret', return_value='scoped-bootstrap-test-token'), patch.object(applications, 'read_secret', return_value='client-test-secret'), patch.object(applications.Path, 'read_text', return_value='synthetic-policy'):
            applications.configure_vault(object(), settings)

    def test_default_role_has_read_policy_and_admin_requires_admin_group(self):
        self.configure()
        bodies = {path: body for method, path, body in self.calls if body is not None}
        user = bodies['/v1/auth/oidc/role/lab-users']
        admin = bodies['/v1/auth/oidc/role/lab-admins']
        self.assertEqual(user['token_policies'], ['default', 'lab-sso-readonly'])
        self.assertEqual(admin['bound_claims'], {'groups': 'lab-admins'})
        self.assertNotIn('*', ''.join(user['allowed_redirect_uris']))
        self.assertEqual(bodies['/v1/auth/oidc/config']['default_role'], 'lab-users')
        self.assertEqual(self.api.call_args.kwargs['headers'], {'X-Vault-Token': 'scoped-bootstrap-test-token'})

    def test_existing_mount_is_not_recreated(self):
        self.configure()
        self.assertFalse(any(method == 'POST' and path == '/v1/sys/auth/oidc' for method, path, _ in self.calls))

    def test_sealed_vault_is_not_reported_as_configured(self):
        with self.assertRaisesRegex(ReconcileError, 'unsealed'):
            self.configure(sealed=True)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))

    def test_different_auth_mount_is_not_overwritten(self):
        with self.assertRaisesRegex(ReconcileError, 'different auth type'):
            self.configure(mount_type='jwt')
        self.assertTrue(all(method == 'GET' for method, _, _ in self.calls))


class OrchestratorSSO(unittest.TestCase):
    def test_existing_provider_is_updated_with_explicit_group_mapping(self):
        calls = []
        class AO:
            def request(self, method, path, body=None, **kwargs):
                calls.append((method, path, body))
                if path.endswith('/auth/login'):
                    return {'access_token': 'synthetic-token'}
                if '/groups?' in path:
                    return {'resources': [{'name': 'users', 'id': 'users-id'}, {'name': 'admins', 'id': 'admins-id'}]}
                if '/identity_providers?' in path:
                    return {'resources': [{'name': 'Lab SSO', 'id': 'provider-id'}]}
        settings = {'issuer': 'https://idp.example.test/realms/lab', 'applications': {'orchestrator': {'url': 'https://ao.example.test'}}}
        with patch.object(applications, 'API', return_value=AO()), patch.object(applications, 'kube_secret', return_value='synthetic-admin-password'), patch.object(applications, 'read_secret', return_value='synthetic-client-secret'):
            applications.configure_orchestrator(object(), settings)
        body = next(body for method, path, body in calls if method == 'PATCH')
        self.assertFalse(body['configuration']['allow_all_authenticated'])
        self.assertFalse(body['configuration']['disable_tls_verify'])
        self.assertIn({'idp_group_value': 'lab-admins', 'mapped_group_id': 'admins-id'}, body['configuration']['group_mapping_entries'])
        self.assertFalse(any(method == 'POST' and path.endswith('/identity_providers') for method, path, _ in calls))


class ProviderBoundaries(unittest.TestCase):
    def test_duplicate_named_identity_provider_fails(self):
        with self.assertRaises(ReconcileError):
            applications.exact_one([{'name': 'Lab SSO'}, {'name': 'Lab SSO'}], 'Lab SSO')


if __name__ == '__main__':
    unittest.main()
