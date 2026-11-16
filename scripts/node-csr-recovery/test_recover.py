"""Exercise authorization boundaries without creating real cluster CSRs."""
import base64
import copy
import datetime as dt
import ipaddress
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from recover import BOOTSTRAPPER, CLIENT, SERVING, validate


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.timezone.utc)
        self.policy = dict(node='ocp', node_uid='pinned', dns=['ocp'], ips=['192.168.2.120'], max_request_age_seconds=3600)
        self.node = {'metadata': {'name': 'ocp', 'uid': 'pinned'}, 'status': {'addresses': [{'address': '192.168.2.120'}]}}

    def csr(self, signer=CLIENT, cn='system:node:ocp', org='system:nodes', dns=None):
        builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
        ]))
        if signer == SERVING or dns is not None:
            builder = builder.add_extension(x509.SubjectAlternativeName([
                x509.DNSName(dns or 'ocp'), x509.IPAddress(ipaddress.ip_address('192.168.2.120')),
            ]), critical=False)
        req = builder.sign(ec.generate_private_key(ec.SECP256R1()), hashes.SHA256())
        return {
            'metadata': {'creationTimestamp': self.now.isoformat()},
            'spec': {
                'signerName': signer,
                'username': BOOTSTRAPPER if signer == CLIENT else 'system:node:ocp',
                'groups': ['system:serviceaccounts', 'system:serviceaccounts:openshift-machine-config-operator', 'system:authenticated'] if signer == CLIENT else ['system:nodes', 'system:authenticated'],
                'request': base64.b64encode(req.public_bytes(serialization.Encoding.PEM)).decode(),
                'usages': ['digital signature', 'client auth' if signer == CLIENT else 'server auth'],
            },
        }

    def test_valid_bootstrap_and_serving(self):
        for signer in (CLIENT, SERVING):
            validate(self.csr(signer), self.policy, self.node, self.now)

    def test_reject_wrong_certificate_identity(self):
        for csr in [self.csr(cn='system:node:evil'), self.csr(org='system:masters'), self.csr(SERVING, dns='evil')]:
            with self.assertRaises(ValueError):
                validate(csr, self.policy, self.node, self.now)

    def test_reject_invalid_requester_signer_usages_and_age(self):
        base = self.csr()
        variants = []
        for key, value in [('username', 'system:admin'), ('groups', ['system:masters']), ('signerName', 'kubernetes.io/kube-apiserver-client'), ('usages', ['cert sign'])]:
            csr = copy.deepcopy(base)
            csr['spec'][key] = value
            variants.append(csr)
        old = copy.deepcopy(base)
        old['metadata']['creationTimestamp'] = (self.now - dt.timedelta(hours=2)).isoformat()
        variants.append(old)
        for csr in variants:
            with self.assertRaises(ValueError):
                validate(csr, self.policy, self.node, self.now)

    def test_reject_node_replacement_or_ip_change(self):
        for node in [dict(metadata=dict(name='ocp', uid='replacement'), status=self.node['status']), dict(metadata=self.node['metadata'], status=dict(addresses=[dict(address='192.168.2.121')]))]:
            with self.assertRaises(ValueError):
                validate(self.csr(), self.policy, node, self.now)

    def test_reject_client_sans(self):
        with self.assertRaises(ValueError):
            validate(self.csr(dns='ocp'), self.policy, self.node, self.now)


if __name__ == '__main__':
    unittest.main()
