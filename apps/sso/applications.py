"""Native application API reconciliation, run by separate Kubernetes Jobs."""
import base64
import json
from pathlib import Path
import re
import sys
import urllib.parse

from reconcile import API, ReconcileError, read_secret, upsert_client


def kube_api():
    sa = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    return API('https://kubernetes.default.svc', read_secret(sa, 'token'), str(sa / 'ca.crt'))


def kube_secret(kube, namespace, name, key):
    value = kube.request('GET', f'/api/v1/namespaces/{namespace}/secrets/{name}')
    try:
        result = base64.b64decode(value['data'][key], validate=True).decode()
    except (KeyError, ValueError):
        raise ReconcileError('Application bootstrap credential is missing or invalid') from None
    if not result:
        raise ReconcileError('Application bootstrap credential is empty')
    return result


def exact_one(items, name):
    matches = [item for item in items if item.get('name') == name]
    if len(matches) > 1:
        raise ReconcileError('Application identity configuration has duplicate names')
    return matches[0] if matches else None


def configure_aap(kube, settings):
    config = settings['applications']['aap']
    password = kube_secret(kube, 'aap', 'aap-admin-password', 'password')
    basic = base64.b64encode((config.get('adminUsername', 'admin') + ':' + password).encode()).decode()
    aap = API(config['url'], headers={'Authorization': 'Basic ' + basic})
    root = '/api/gateway/v1/'
    secret = read_secret('/credentials/clients', 'aap-client-secret')
    body = {
        'name': 'Lab SSO', 'enabled': True, 'create_objects': True, 'remove_users': True,
        'type': 'ansible_base.authentication.authenticator_plugins.oidc',
        'configuration': {'OIDC_ENDPOINT': settings['issuer'], 'KEY': 'aap', 'SECRET': secret,
                          'VERIFY_SSL': True, 'USERNAME_KEY': 'preferred_username',
                          'GROUPS_CLAIM': 'groups', 'SCOPE': ['openid', 'profile', 'email'],
                          'JWT_ALGORITHMS': ['RS256']},
    }
    current = exact_one(aap.request('GET', root + 'authenticators/?name=Lab%20SSO')['results'], 'Lab SSO')
    if current:
        # Keep the existing authenticator and generated callback identity.
        auth = aap.request('PATCH', root + f"authenticators/{current['id']}/", body)
    else:
        auth = aap.request('POST', root + 'authenticators/', body)
    callback = auth.get('configuration', {}).get('CALLBACK_URL', '')
    base = re.escape(config['url'].rstrip('/'))
    if not re.fullmatch(base + r'/api/gateway/social/complete/[a-zA-Z0-9_-]+/', callback):
        raise ReconcileError('AAP returned an unexpected OIDC callback URL')
    kc = API('http://keycloak.sso.svc:8080')
    kc.token = kc.request('POST', '/realms/master/protocol/openid-connect/token', form={
        'client_id': 'admin-cli', 'grant_type': 'password', 'username': 'bootstrap-admin',
        'password': read_secret('/credentials/admin', 'password')})['access_token']
    upsert_client(kc, '/admin/realms/' + urllib.parse.quote(settings['realm'], safe=''),
                  {'clientId': 'aap', 'secretKey': 'aap-client-secret',
                   'redirectUris': [callback], 'webOrigins': [config['url']]}, '/credentials/clients')
    maps_path = root + 'authenticator_maps/'
    maps = aap.request('GET', maps_path + '?' + urllib.parse.urlencode({'authenticator': auth['id'], 'page_size': 200}))['results']
    for name, kind, group, order in [('Lab SSO access', 'allow', 'lab-users', 0),
                                     ('Lab SSO administrators', 'is_superuser', 'lab-admins', 1)]:
        desired = {'name': name, 'authenticator': auth['id'], 'map_type': kind, 'enabled': True,
                   'revoke': True, 'order': order, 'triggers': {'groups': {'has_or': [group]}}}
        existing = exact_one(maps, name)
        if existing:
            aap.request('PATCH', maps_path + str(existing['id']) + '/', desired)
        else:
            aap.request('POST', maps_path, desired)
    # The portal exchanges the externally authenticated user's authorization
    # code for an AAP token; gateway disables this permission by default.
    gateway_settings = aap.request('GET', root + 'settings/all/')
    if gateway_settings.get('ALLOW_OAUTH2_FOR_EXTERNAL_USERS') is not True:
        aap.request('PATCH', root + 'settings/all/', {'ALLOW_OAUTH2_FOR_EXTERNAL_USERS': True})
    print('AAP authenticator, exact Keycloak callback, group mappings, and portal token access reconciled.')


def configure_orchestrator(kube, settings):
    config = settings['applications']['orchestrator']
    ao = API(config['url'])
    password = kube_secret(kube, 'automation-orchestrator', 'automation-orchestrator-admin-password', 'password')
    ao.token = ao.request('POST', '/api/v1/auth/login', {
        'username': config.get('adminUsername', 'admin'), 'password': password})['access_token']
    groups = ao.request('GET', '/api/v1/groups?limit=100')['resources']
    users = exact_one(groups, 'users')
    admins = exact_one(groups, 'admins')
    if users is None or admins is None:
        raise ReconcileError('Automation Orchestrator built-in groups are unavailable')
    body = {'name': 'Lab SSO', 'configuration': {
        'provider_type': 'oidc', 'idp_type': 'custom', 'auto_discovery': True,
        'issuer_url': settings['issuer'], 'client_id': 'orchestrator',
        'client_secret': read_secret('/credentials/clients', 'orchestrator-client-secret'),
        'redirect_uri': config['url'] + '/api/v1/auth/oidc/callback',
        'scopes': 'openid profile email', 'group_jmespath_expression': 'groups[*]',
        'allow_all_authenticated': False, 'disable_tls_verify': False,
        'enable_rp_initiated_logout': False,
        'group_mapping_entries': [{'idp_group_value': 'lab-users', 'mapped_group_id': users['id']},
                                  {'idp_group_value': 'lab-admins', 'mapped_group_id': admins['id']}],
    }}
    current = exact_one(ao.request('GET', '/api/v1/identity_providers?limit=100')['resources'], 'Lab SSO')
    if current:
        body['enabled'] = True
        ao.request('PATCH', '/api/v1/identity_providers/' + current['id'], body)
    else:
        ao.request('POST', '/api/v1/identity_providers', body)
    print('Automation Orchestrator OIDC provider and group mappings reconciled.')


def configure_vault(kube, settings):
    config = settings['applications']['vault']
    token = kube_secret(kube, 'vault', 'vault-sso-bootstrap', 'token')
    vault = API(config['url'], headers={'X-Vault-Token': token})
    status = vault.request('GET', '/v1/sys/seal-status')
    if not status.get('initialized') or status.get('sealed'):
        raise ReconcileError('Vault must be initialized and unsealed before SSO configuration')
    mounts = vault.request('GET', '/v1/sys/auth')['data']
    mount = mounts.get('oidc/')
    if mount and mount.get('type') != 'oidc':
        raise ReconcileError('Vault oidc/ mount already exists with a different auth type')
    if not mount:
        vault.request('POST', '/v1/sys/auth/oidc', {'type': 'oidc', 'description': 'Lab SSO'})
    vault.request('POST', '/v1/auth/oidc/config', {
        'oidc_discovery_url': settings['issuer'], 'oidc_client_id': 'vault',
        'oidc_client_secret': read_secret('/credentials/clients', 'vault-client-secret'),
        'default_role': 'lab-users'})
    for role, policy in [('lab-users', 'lab-sso-readonly'), ('lab-admins', 'lab-sso-admin')]:
        text = Path('/config/' + policy + '.hcl').read_text()
        vault.request('PUT', '/v1/sys/policies/acl/' + policy, {'policy': text})
        vault.request('POST', '/v1/auth/oidc/role/' + role, {
            'role_type': 'oidc', 'user_claim': 'sub', 'groups_claim': 'groups',
            'bound_audiences': ['vault'], 'bound_claims': {'groups': role},
            'allowed_redirect_uris': [config['publicUrl'] + '/ui/vault/auth/oidc/oidc/callback',
                                      'http://localhost:8250/oidc/callback'],
            'oidc_scopes': ['profile', 'email'], 'token_policies': ['default', policy],
            'token_ttl': '1h', 'token_max_ttl': '8h'})
    print('Vault OIDC auth mount, constrained roles, and policies reconciled.')


def main():
    settings = json.loads(Path('/config/settings.json').read_text())
    target = sys.argv[1]
    functions = {'aap': configure_aap, 'orchestrator': configure_orchestrator, 'vault': configure_vault}
    if target not in functions:
        raise ReconcileError('Unknown application SSO target')
    functions[target](kube_api(), settings)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, ReconcileError) else 'Application SSO reconciliation failed; response omitted to protect credentials', file=sys.stderr)
        sys.exit(1)
