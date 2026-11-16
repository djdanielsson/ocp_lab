# Node certificate recovery from the workstation

This single-node bare-metal cluster has no Machine API records. The built-in
machine approver cannot authorize bootstrap requests or expired serving
certificate recovery using a Machine record. An external workstation timer
can approve validated requests while kubelet is unable to start regular pods.

`apps/cluster-config/node-csr-recovery.yaml` is reconciled by the existing
`cluster-config` Argo CD application. It provides the dedicated service account,
RBAC, credential Secret, and node policy. The timer and Python program are kept
in this repository and installed on the workstation; Argo CD does not manage
workstation services. Run the installer again after moving the checkout or
changing the timer/service installation. Script changes take effect next run.

## Install on the recovery workstation

Requires Linux with a running systemd user manager, `/usr/bin/python3`, the
Python `cryptography` package, and `oc` logged in as an administrator for initial
installation only. First sync `cluster-config`, then run from this checkout:

```bash
scripts/node-csr-recovery/install.sh
systemctl --user status ocp-node-csr-recovery.timer
journalctl --user -u ocp-node-csr-recovery.service -n 20
```

The installer stores a dedicated credential under
`~/.config/ocp-node-csr-recovery/credentials.json` with mode 0600. It is never
committed. Routine approval uses this service account, not the admin kubeconfig.
The token is a deliberately persistent service-account token so it remains
usable across weeks of node downtime. It has approval permissions for only the
two kubelet signers and cannot access secrets or modify workloads. RBAC cannot
restrict approval by certificate subject; the validator enforces that boundary.
Treat the workstation credential as sensitive. To revoke it, disable the timer,
delete `node-csr-recovery-token` in `openshift-config`, and remove the local
credentials file. Argo CD recreates the Secret with a new token; reinstall to
resume recovery.

The validator checks the existing node UID, name, and address against GitOps
policy; CSR signature, subject, usages, requester and groups; exact serving
SANs; and request age (at most one hour). It ignores already decided requests
and every other signer. Replacing the node or changing its address requires a
reviewed policy update. This does not provide hardware attestation: it trusts
OpenShift authentication of the node/bootstrapper plus the pinned node record.

## Availability and scope

The timer checks every minute while this workstation is awake and the user
service manager is running. It resumes when the workstation/user session
returns. It does not need the console, ingress, kubelet, or the administrator's
certificate. The Kubernetes API and cluster token authentication must recover
far enough to accept its requests. If this workstation is off too, approval
waits until it is back on. For recovery without a logged-in user, install on an
always-on machine with an appropriately managed systemd user session.

Certificate lifetimes stay at OpenShift defaults. In particular the node signer
currently issues certificates for at most 720 hours (30 days). This does not
extend every internal certificate or guarantee recovery from every shutdown
failure. Test a real shutdown/resume during a maintenance window; simulated
CSRs verify approval behavior, not the entire hibernation process.

```bash
# Read-only evaluation:
python3 scripts/node-csr-recovery/recover.py \
  --credentials ~/.config/ocp-node-csr-recovery/credentials.json
# Disable automatic approval:
systemctl --user disable --now ocp-node-csr-recovery.timer
# Offline authorization checks:
python3 -m unittest discover -s scripts/node-csr-recovery -v
```

References:
- [Red Hat: approving CSRs on platforms without Machine API](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/pdf/postinstallation_configuration/OpenShift_Container_Platform-4.20-Postinstallation_configuration-en-US.pdf)
- [Kubernetes: CSR approval authorization](https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/)
