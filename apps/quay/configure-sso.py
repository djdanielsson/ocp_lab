"""Render the existing Quay configuration plus its native OIDC provider."""
import json
from pathlib import Path

base = Path('/source/config.yaml').read_text()
if 'LAB_SSO_LOGIN_CONFIG:' in base:
    raise RuntimeError('The base Quay configuration already defines Lab SSO')
secret = Path('/credentials/client-secret').read_text()
if not secret:
    raise RuntimeError('Missing Quay SSO client credential')
provider = {
    'CLIENT_ID': 'quay', 'CLIENT_SECRET': secret,
    'OIDC_SERVER': 'https://sso.apps.ocp.lab.danielsson.us.com/realms/lab/',
    'SERVICE_NAME': 'Lab SSO', 'PREFERRED_USERNAME_CLAIM_NAME': 'preferred_username',
    'LOGIN_SCOPES': ['openid', 'profile', 'email'],
}
# JSON values are valid YAML and quote arbitrary secret characters safely.
fragment = '\nLAB_SSO_LOGIN_CONFIG:\n' + ''.join('  ' + k + ': ' + json.dumps(v) + '\n' for k, v in provider.items())
Path('/rendered/config.yaml').write_text(base + fragment)
