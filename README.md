# ocp_lab

## Quick Start

After a fresh OCP cluster install, run these two steps:

### Step 1: Storage (bootstrap-storage.yaml)

Apply the storage bootstrap first to install the LVMS operator, create the LVMCluster,
and set up the default StorageClass:

```bash
oc apply -f bootstrap-storage.yaml
```

Wait for the LVMS operator to install and the LVMCluster to become ready. The LVMCluster
CR will initially fail to apply until the CRD is registered by the operator -- re-apply
after a minute or two:

```bash
oc apply -f bootstrap-storage.yaml
```

Verify storage is ready:

```bash
oc get lvmcluster -n openshift-storage
oc get sc
```

### Step 2: GitOps + App-of-Apps (bootstrap.yaml)

Once storage is available, apply the main bootstrap to install the GitOps operator,
grant ArgoCD cluster-admin, and deploy the app-of-apps:

```bash
oc apply -f bootstrap.yaml
```

The GitOps operator takes a minute or two to install. Once the `openshift-gitops` namespace
is ready and the ArgoCD CRDs exist, the `app-of-apps` Application will be picked up
automatically. If you applied the bootstrap before the operator was ready, re-apply:

```bash
oc apply -f bootstrap.yaml
```

## What Gets Deployed


| Sync Wave  | Application                | Description                                                        |
| ---------- | -------------------------- | ------------------------------------------------------------------ |
| pre-argocd | lvms-operator + instance   | LVM Storage (via bootstrap-storage.yaml)                           |
| -3         | external-secrets-operator  | External Secrets operator                                          |
| -2         | external-secrets-bitwarden | Bitwarden provider for ESO                                         |
| -2         | ocp-virt-operator          | OpenShift Virtualization operator                                  |
| -2         | cert-manager-operator      | cert-manager operator                                              |
| -1         | aap-pg-operator            | CloudNativePG operator                                             |
| -1         | aap-operator               | Ansible Automation Platform operator                               |
| -1         | devspaces-operator         | Dev Spaces operator                                                |
| -1         | monitoring-operator        | Grafana + Prometheus operators                                     |
| -1         | loki-operator              | Loki logging operator                                              |
| 0          | aap-instance               | AAP deployment                                                     |
| 0          | devspaces-instance         | Dev Spaces instance                                                |
| 0          | ocp-virt-instance          | HyperConverged CR                                                  |
| 0          | cert-manager-instance      | ClusterIssuers (self-signed, Let's Encrypt)                        |
| 0          | loki-instance              | LokiStack + MinIO object storage                                   |
| 0          | authentik                  | Authentik SSO (server, worker, PostgreSQL, Redis)                  |
| 1          | aap-monitoring             | AAP monitoring components                                          |
| 1          | aap-portal-secrets         | AAP Self-Service Portal secrets                                    |
| 1          | tailscale                  | Tailscale exit node                                                |
| 1          | ollama                     | Ollama + Open WebUI                                                |
| 1          | ocp-mcp-server             | Kubernetes MCP Server                                              |
| 2          | aap-portal                 | AAP Self-Service Automation Portal (Helm)                          |
| 5          | monitoring-components      | Grafana dashboards, Prometheus, AlertManager, ServiceMonitors, external monitors |
| -1         | netobserv-operator         | Network Observability operator (eBPF-based)                        |
| 1          | netobserv-instance         | FlowCollector CR for network flow capture                          |
| -1         | graylog-mongodb-operator   | MongoDB Kubernetes Operator (for Graylog)                          |
| 1          | graylog                    | Graylog log management (Helm chart)                                |
| --         | pipelines                  | OpenShift Pipelines operator                                       |
| --         | web-terminal               | Web Terminal operator                                              |


## Secrets Management (Vaultwarden + External Secrets Operator)

All secrets are managed via External Secrets Operator pulling from a Vaultwarden instance.
Before deploying the ArgoCD applications, you must:

1. **Create items in your Vaultwarden vault** with the following names and fields:
  ### Core / AAP Secrets

  | Vaultwarden Item | Type | Fields / Properties |
  | -----------| --- | -------------------------- |
  | `ocp-lab/aap-admin` | Login | username: `admin`, password: (strong password) |
  | `ocp-lab/postgres-hub` | Login | username: `hub`, password: (strong password) |
  | `ocp-lab/postgres-gateway` | Login | username: `gateway`, password: (strong password) |
  | `ocp-lab/postgres-controller` | Login | username: `controller`, password: (strong password) |
  | `ocp-lab/postgres-eda` | Login | username: `eda`, password: (strong password) |
  | `ocp-lab/grafana-admin` | Login | username: `admin`, password: (strong password) |
  | `ocp-lab/quay-config` | Secure Note | Custom fields: `SECRET_KEY`, `DATABASE_SECRET_KEY`, `DB_PASSWORD` |
  | `ocp-lab/authentik-admin` | Login | username: `akadmin`, password: (strong password -- used for initial Authentik admin login and as the secret key) |
  | `ocp-lab/authentik-postgres` | Login | username: `authentik`, password: (strong password) |
  | `ocp-lab/loki-minio` | Login | username: `minioadmin`, password: (strong password -- used as MinIO root credentials and S3 access key) |
  | `ocp-lab/ipmi-bmc` | Login | username: (BMC/IPMI username), password: (BMC/IPMI password) |
  | `ocp-lab/tailscale` | Secure Note | Custom field: `authkey` = (Tailscale auth key with subnet-router + exit-node tags) |
  | `ocp-lab/aap-portal` | Secure Note | Custom fields: `aap-host-url` = `https://aap.apps.ocp.new.lab.danielsson.us.com`, `oauth-client-id` = (AAP OAuth client ID), `oauth-client-secret` = (AAP OAuth client secret), `aap-token` = (AAP admin API token with read scope), `github-token` = (GitHub PAT with repo, read:org), `registry-auth-b64` = (base64-encoded `username:password` for registry.redhat.io service account) |
  | `ocp-lab/telegram-alertmanager` | Secure Note | Custom fields: `bot_token` = (Telegram bot token from BotFather), `chat_id` = (Telegram chat/group ID for alerts) |

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

## External Monitoring Targets

The following external (non-cluster) services are monitored via Prometheus ServiceMonitors:


| Target              | IP Address         | Port                | Metrics Path                           |
| ------------------- | ------------------ | ------------------- | -------------------------------------- |
| TrueNAS (Netdata)   | 192.168.2.82       | 20489               | `/api/v1/allmetrics?format=prometheus` |
| Portainer (Netdata) | 192.168.2.213      | 19999               | `/api/v1/allmetrics?format=prometheus` |
| Klipper/Moonraker   | 192.168.2.105      | 7125 (via klipper-exporter) | `/probe` (multi-target pattern)  |
| Supermicro BMC/IPMI | 192.168.2.80       | 9290 (via ipmi-exporter)   | `/ipmi` (remote IPMI-over-LAN)   |


## Viewing Logs (Loki)

Loki does not have its own UI. To view logs, use Grafana:

1. Open Grafana at `https://grafana-monitoring.apps.ocp.new.lab.danielsson.us.com`
2. Navigate to **Explore** (compass icon in the sidebar)
3. Select the **loki** datasource from the dropdown
4. Use LogQL queries, e.g. `{kubernetes_namespace_name="default"}`

The Loki Route (`loki-loki.apps.ocp.new.lab.danielsson.us.com`) is the API gateway for log ingestion, not a web UI.

## AAP Self-Service Portal Setup

Before the AAP Portal Helm chart can connect to AAP, complete these steps in the AAP UI:

1. Navigate to **Access Management > Organizations** and select/create an organization
2. Navigate to **Access Management > OAuth Applications** and create a new OAuth Application:
  - Client type: `Confidential`
  - Authorization grant type: `Authorization code`
  - Redirect URIs: `https://aap-portal.apps.ocp.new.lab.danielsson.us.com/api/auth/callback/aap`
  - Copy the `clientId` and `clientSecret` values
3. Enable **Allow external users to create OAuth2 tokens** in Platform Gateway settings
4. Navigate to **Access Management > API Tokens** and create a token with `Read` scope
5. Store all values in the `ocp-lab/aap-portal` Vaultwarden item (see secrets table above)

## Authentik SSO Integration

After Authentik deploys, configure it as an OIDC provider for your services:

1. Log into Authentik at `https://authentik.apps.ocp.new.lab.danielsson.us.com`
  (default user: `akadmin`, password from Vaultwarden `ocp-lab/authentik-admin`)
2. Create OAuth2/OIDC providers and applications for:
  - **OpenShift** -- Add as an OAuth identity provider in OCP
  - **AAP** -- Configure OIDC authentication backend
  - **Vaultwarden** -- Configure OpenID Connect SSO
  - **Grafana** -- Configure OAuth authentication

## Post-Install Steps

```bash
oc label service aap -n aap monitor=metrics
```

```bash
oc patch AutomationController aap -n aap --type=merge -p '{"spec": {"extra_settings": [{"metrics_utility_enabled": "true"}]}}'
```

