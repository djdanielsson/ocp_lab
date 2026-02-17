# ocp_lab

OpenShift GitOps lab environment managed by ArgoCD. Secrets are stored in HashiCorp Vault and synced to Kubernetes via the External Secrets Operator.

## Architecture

```
Git Repo (ArgoCD Applications)
  |
  ├── Vault (Helm chart, standalone mode)
  ├── External Secrets Operator (OLM Subscription)
  ├── ClusterSecretStore + ExternalSecrets (Vault -> K8s Secrets)
  ├── AAP Operator + Instances
  ├── Monitoring (Prometheus, Grafana)
  ├── DevSpaces, Pipelines, Web Terminal
  └── ...
```

Secrets flow: **Vault** -> **External Secrets Operator** -> **Kubernetes Secrets** -> **Applications**

## Prerequisites

Required to run before installing OpenShift GitOps Operator

```bash
oc patch storageclass lvms-vg1 -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

Required to run after installing OpenShift GitOps Operator

```bash
oc adm policy add-cluster-role-to-user cluster-admin -z openshift-gitops-argocd-application-controller -n openshift-gitops
```

## Vault Setup (Post-Deploy)

After ArgoCD deploys the Vault Helm chart, Vault will be running but **sealed and uninitialized**. The ExternalSecret resources will remain in a degraded state until Vault is ready.

### Automated Setup

Run the initialization script which handles all steps (init, unseal, KV engine, K8s auth, policy, role, and placeholder secrets):

```bash
./apps/vault/init-vault.sh
```

**Save the unseal key and root token** output by the script -- you will need these to unseal Vault after any pod restart.

### Update Placeholder Secrets

The init script seeds placeholder values (`CHANGEME`). Update them with real passwords:

```bash
oc exec -n vault vault-0 -- vault kv put secret/aap/admin-password password=YOUR_REAL_PASSWORD
oc exec -n vault vault-0 -- vault kv put secret/aap/postgres-controller \
  host=aap-postgres-rw.aap.svc.cluster.local port=5432 database=controller \
  username=controller password=YOUR_REAL_PASSWORD type=unmanaged
oc exec -n vault vault-0 -- vault kv put secret/aap/postgres-eda \
  host=aap-postgres-rw.aap.svc.cluster.local port=5432 database=eda \
  username=eda password=YOUR_REAL_PASSWORD type=unmanaged
oc exec -n vault vault-0 -- vault kv put secret/aap/postgres-hub \
  host=aap-postgres-rw.aap.svc.cluster.local port=5432 database=hub \
  username=hub password=YOUR_REAL_PASSWORD type=unmanaged
oc exec -n vault vault-0 -- vault kv put secret/aap/postgres-gateway \
  host=aap-postgres-rw.aap.svc.cluster.local port=5432 database=gateway \
  username=gateway password=YOUR_REAL_PASSWORD type=unmanaged
```

### Manual Setup (Alternative)

If you prefer to run steps individually:

1. Initialize: `oc exec -n vault vault-0 -- vault operator init -key-shares=1 -key-threshold=1`
2. Unseal: `oc exec -n vault vault-0 -- vault operator unseal <UNSEAL_KEY>`
3. Login: `oc exec -n vault vault-0 -- vault login <ROOT_TOKEN>`
4. Enable KV: `oc exec -n vault vault-0 -- vault secrets enable -path=secret kv-v2`
5. Enable K8s auth: `oc exec -n vault vault-0 -- vault auth enable kubernetes`
6. Configure K8s auth: `oc exec -n vault vault-0 -- vault write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc:443`
7. Create policy: see `apps/vault/init-vault.sh` for the policy document
8. Create role: `oc exec -n vault vault-0 -- vault write auth/kubernetes/role/external-secrets bound_service_account_names=external-secrets-sa bound_service_account_namespaces=openshift-external-secrets-operator policies=external-secrets ttl=1h`
9. Write secrets (see above)

### Unsealing After Restart

Vault must be unsealed every time the pod restarts:

```bash
oc exec -n vault vault-0 -- vault operator unseal <UNSEAL_KEY>
```

### Vault UI

The Vault UI is available at: `https://vault.apps.ocp.lab.danielsson.us.com`

## Post-Deploy Steps (Other)

Required to run after adding applications of apps (at least until I can figure out how to make Argo apply them)

```bash
oc label service aap -n aap monitor=metrics
```

```bash
oc patch AutomationController aap-controller -n aap --type=merge -p '{"spec": {"extra_settings": [{"metrics_utility_enabled": "true"}]}}'
```

## Sync Wave Order

| Wave | Application |
|------|-------------|
| -2   | Vault (Helm) |
| -1   | ESO Operator, AAP PG Operator, AAP Operator, Monitoring Operator, DevSpaces Operator |
| 0    | ESO Instances (ClusterSecretStore + ExternalSecrets), AAP Instance, DevSpaces Instance |
| 1    | AAP Monitoring |
| 5    | Monitoring Components |
