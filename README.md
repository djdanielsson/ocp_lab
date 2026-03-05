# ocp_lab

## Quick Start

After a fresh OCP cluster install, apply the bootstrap file to install the GitOps operator,
grant ArgoCD cluster-admin, and deploy the app-of-apps:

```bash
oc apply -f bootstrap.yaml
```

The GitOps operator takes a minute or two to install. Once the `openshift-gitops` namespace
is ready and the ArgoCD CRDs exist, the `app-of-apps` Application will be picked up
automatically. If you applied the bootstrap before the operator was ready, simply re-apply:

```bash
oc apply -f bootstrap.yaml
```

ArgoCD will then sync all applications in the configured order via sync waves.

## What Gets Deployed

| Sync Wave | Application | Description |
|-----------|-------------|-------------|
| -5 | lvms-operator | LVM Storage operator |
| -4 | lvms-instance | LVMCluster + default StorageClass |
| -3 | external-secrets-operator | External Secrets operator |
| -2 | external-secrets-bitwarden | Bitwarden provider for ESO |
| -2 | ocp-virt-operator | OpenShift Virtualization operator |
| -1 | aap-pg-operator | CloudNativePG operator |
| -1 | aap-operator | Ansible Automation Platform operator |
| -1 | devspaces-operator | Dev Spaces operator |
| -1 | monitoring-operator | Grafana + Prometheus operators |
| 0 | aap-instance | AAP deployment |
| 0 | devspaces-instance | Dev Spaces instance |
| 0 | ocp-virt-instance | HyperConverged CR |
| 1 | aap-monitoring | AAP monitoring components |
| 1 | ollama | Ollama + Open WebUI |
| 1 | ocp-mcp-server | Kubernetes MCP Server |
| 5 | monitoring-components | Grafana dashboards, Prometheus, ServiceMonitors |
| -- | pipelines | OpenShift Pipelines operator |
| -- | web-terminal | Web Terminal operator |

## Prerequisites

### Data Partition (Optional)

If your cluster uses a data partition for LVM storage, apply the MachineConfig before bootstrap:

```bash
oc apply -f data-storage.yaml
```

### Secrets Management (Vaultwarden + External Secrets Operator)

All secrets are managed via External Secrets Operator pulling from a Vaultwarden instance.
Before deploying the ArgoCD applications, you must:

1. **Create items in your Vaultwarden vault** with the following names and fields:

   | Vaultwarden Item | Type | Fields |
   |---|---|---|
   | `ocp-lab/aap-admin` | Login | username: `admin`, password: (strong password) |
   | `ocp-lab/postgres-hub` | Login | username: `hub`, password: (strong password) |
   | `ocp-lab/postgres-gateway` | Login | username: `gateway`, password: (strong password) |
   | `ocp-lab/postgres-controller` | Login | username: `controller`, password: (strong password) |
   | `ocp-lab/postgres-eda` | Login | username: `eda`, password: (strong password) |
   | `ocp-lab/quay-config` | Secure Note | Custom fields: `SECRET_KEY`, `DATABASE_SECRET_KEY`, `DB_PASSWORD` |

2. **Generate API keys** in Vaultwarden: Log in to the web vault, go to
   Settings > Security > Keys, and generate an API key (Client ID + Client Secret).

3. **Create the bootstrap secret** on the cluster (this is the only secret not managed by ESO):

   ```bash
   oc create namespace external-secrets
   oc create secret generic bitwarden-cli -n external-secrets \
     --from-literal=BW_HOST=https://your-vaultwarden-url \
     --from-literal=BW_CLIENTID=your-api-client-id \
     --from-literal=BW_CLIENTSECRET=your-api-client-secret \
     --from-literal=BW_PASSWORD=your-master-password
   ```

## Post-Install Steps

```bash
oc label service aap -n aap monitor=metrics
```

```bash
oc patch AutomationController aap -n aap --type=merge -p '{"spec": {"extra_settings": [{"metrics_utility_enabled": "true"}]}}'
```
