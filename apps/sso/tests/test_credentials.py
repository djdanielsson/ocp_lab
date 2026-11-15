"""Credential formats and confidential/public client boundaries."""
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('credential_reconcile', Path(__file__).resolve().parents[1] / 'reconcile.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GeneratedCredentialContracts(unittest.TestCase):
    def test_cookie_material_matches_upstream_hex_and_aes_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'material').write_text('a high entropy synthetic generated credential')
            writes = []
            class Kube:
                def request(self, method, path, body=None, **kwargs):
                    if method == 'GET':
                        return {'metadata': {'resourceVersion': '7'}, 'data': {'unrelated': 'retained'}}
                    writes.append(body)
            module.publish_secret(Kube(), {'namespace': 'app', 'keys': {}, 'sha256': {'hex-cookie': 'material'}, 'base64sha256': {'aes-cookie': 'material'}}, directory)
            data = writes[0]['data']
            self.assertEqual(len(bytes.fromhex(base64.b64decode(data['hex-cookie']).decode())), 32)
            self.assertEqual(len(base64.b64decode(base64.b64decode(data['aes-cookie']))), 32)
            self.assertNotIn('unrelated', data)
            self.assertEqual(writes[0]['metadata']['resourceVersion'], '7')

    def test_existing_sibling_fields_do_not_cause_repeated_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'material').write_text('test-password')
            class Kube:
                def request(self, method, path, *args, **kwargs):
                    if method != 'GET':
                        raise AssertionError('Matching owned fields should not be patched')
                    return {'data': {'client-secret': base64.b64encode(b'test-password').decode(), 'LICENSE': 'other-controller-owned'}}
            module.publish_secret(Kube(), {'namespace': 'app', 'keys': {'client-secret': 'material'}}, directory)

    def test_remote_generated_client_uses_confidential_authentication(self):
        calls = []
        class Keycloak:
            def request(self, method, path, body=None, **kwargs):
                calls.append((method, path, body))
                return [] if method == 'GET' else None
        module.upsert_client(Keycloak(), '/admin/realms/lab', {'clientId': 'optional-app', 'redirectUris': ['https://app.example.test/callback']}, '/unused', supplied_secret='generated-test-secret')
        client = calls[-1][2]
        self.assertFalse(client['publicClient'])
        self.assertEqual(client['clientAuthenticatorType'], 'client-secret')
        self.assertEqual(client['secret'], 'generated-test-secret')
        self.assertFalse(client['directAccessGrantsEnabled'])

    def test_api_cli_is_public_pkce_and_retains_required_audience_mapper(self):
        calls = []
        class Keycloak:
            def request(self, method, path, body=None, **kwargs):
                calls.append((method, path, body))
                return [] if method == 'GET' else None
        mapper = {'name': 'api-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper', 'config': {'included.custom.audience': 'api'}}
        module.upsert_client(Keycloak(), '/admin/realms/lab', {'clientId': 'api-cli', 'pkce': True, 'additionalProtocolMappers': [mapper]}, '/unused')
        client = calls[-1][2]
        self.assertTrue(client['publicClient'])
        self.assertEqual(client['attributes']['pkce.code.challenge.method'], 'S256')
        self.assertIn(mapper, client['protocolMappers'])
        self.assertNotIn('secret', client)


if __name__ == '__main__':
    unittest.main()
