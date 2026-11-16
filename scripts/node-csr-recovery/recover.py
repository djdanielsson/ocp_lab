#!/usr/bin/env python3
"""Approve only validated CSRs for the pinned existing lab node, from outside OCP."""
import argparse
import base64
import datetime as dt
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from cryptography import x509
from cryptography.x509.oid import ExtensionOID, NameOID

CSR_API = '/apis/certificates.k8s.io/v1/certificatesigningrequests'
POLICY_API = '/api/v1/namespaces/openshift-config/configmaps/node-csr-recovery-policy'
CLIENT = 'kubernetes.io/kube-apiserver-client-kubelet'
SERVING = 'kubernetes.io/kubelet-serving'
BOOTSTRAPPER = 'system:serviceaccount:openshift-machine-config-operator:node-bootstrapper'


def validate(csr, policy, node, now):
    """Fail closed on unexpected identity, extensions, usages, or node replacement."""
    if node['metadata']['uid'] != policy['node_uid'] or node['metadata']['name'] != policy['node']:
        raise ValueError('node identity differs from pinned policy')
    actual = {a['address'] for a in node['status']['addresses']}
    if not set(policy['ips']).issubset(actual):
        raise ValueError('node IP differs from pinned policy')
    created = dt.datetime.fromisoformat(csr['metadata']['creationTimestamp'].replace('Z', '+00:00'))
    if not 0 <= (now - created).total_seconds() <= policy['max_request_age_seconds']:
        raise ValueError('request is stale or from the future')
    spec = csr['spec']
    signer = spec['signerName']
    if signer not in (CLIENT, SERVING):
        raise ValueError('unmanaged signer')
    req = x509.load_pem_x509_csr(base64.b64decode(spec['request'], validate=True))
    if not req.is_signature_valid:
        raise ValueError('invalid CSR signature')
    expected = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:nodes'),
        x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:' + policy['node']),
    ])
    if len(req.subject) != 2 or set(req.subject) != set(expected):
        raise ValueError('unexpected certificate subject')
    usages = set(spec['usages'])
    required = {'digital signature', 'client auth' if signer == CLIENT else 'server auth'}
    if usages not in (required, required | {'key encipherment'}):
        raise ValueError('unexpected key usages')
    node_user = 'system:node:' + policy['node']
    groups = set(spec.get('groups', []))
    if spec['username'] == node_user:
        if groups != {'system:nodes', 'system:authenticated'}:
            raise ValueError('unexpected node requester groups')
    elif signer == CLIENT and spec['username'] == BOOTSTRAPPER:
        if groups != {'system:serviceaccounts', 'system:serviceaccounts:openshift-machine-config-operator', 'system:authenticated'}:
            raise ValueError('unexpected bootstrapper groups')
    else:
        raise ValueError('unexpected requester')
    if signer == CLIENT:
        if len(req.extensions):
            raise ValueError('client CSR has extensions')
    else:
        if len(req.extensions) != 1 or req.extensions[0].oid != ExtensionOID.SUBJECT_ALTERNATIVE_NAME:
            raise ValueError('serving CSR must have only SAN extension')
        sans = req.extensions[0].value
        dns = set(sans.get_values_for_type(x509.DNSName))
        ips = {str(ip) for ip in sans.get_values_for_type(x509.IPAddress)}
        if len(sans) != len(dns) + len(ips) or dns != set(policy['dns']) or ips != set(policy['ips']):
            raise ValueError('unexpected serving certificate SANs')


class API:
    def __init__(self, path):
        config = json.loads(Path(path).read_text())
        self.server = config['server'].rstrip('/')
        if not self.server.startswith('https://'):
            raise ValueError('HTTPS API required')
        self.token = config['token']
        self.context = ssl.create_default_context(cadata=config['ca'])

    def request(self, path, body=None):
        request = urllib.request.Request(
            self.server + path,
            data=json.dumps(body).encode() if body is not None else None,
            method='PUT' if body is not None else 'GET',
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, context=self.context, timeout=15) as response:
            return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--approve', action='store_true', help='write validated approvals; default is dry run')
    args = parser.parse_args()
    api = API(args.credentials)
    policy = json.loads(api.request(POLICY_API)['data']['policy.json'])
    node = api.request('/api/v1/nodes/' + quote(policy['node'], safe=''))
    pending = 0
    approved = 0
    for listed in api.request(CSR_API)['items']:
        if listed['spec']['signerName'] not in (CLIENT, SERVING):
            continue
        # Refresh resourceVersion before approval so concurrent approval/denial
        # causes a conflict instead of overwriting another controller's decision.
        path = CSR_API + '/' + quote(listed['metadata']['name'], safe='')
        csr = api.request(path)
        if csr.get('status', {}).get('certificate') or csr.get('status', {}).get('conditions'):
            continue
        pending += 1
        try:
            validate(csr, policy, node, dt.datetime.now(dt.timezone.utc))
        except (ValueError, KeyError, TypeError) as exc:
            print(f'SKIP {csr["metadata"]["name"]}: {exc}', flush=True)
            continue
        if args.approve:
            stamp = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
            csr['status'] = {'conditions': [{
                'type': 'Approved', 'status': 'True', 'reason': 'PinnedLabNodeRecovery',
                'message': 'Validated against GitOps node identity and certificate policy',
                'lastUpdateTime': stamp, 'lastTransitionTime': stamp,
            }]}
            api.request(path + '/approval', csr)
            approved += 1
        print(('APPROVED ' if args.approve else 'WOULD APPROVE ') + csr['metadata']['name'], flush=True)
    print(f'Checked pending node CSRs: {pending}; approved: {approved}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Recovery failed: {exc}', file=sys.stderr)
        sys.exit(1)
