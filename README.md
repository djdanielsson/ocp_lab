# ocp_lab

## Prerequisites

### Storage Class

Required to run before installing OpenShift GitOps Operator

```bash
oc patch storageclass lvms-vg1 -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

### GitOps Permissions

Required to run after installing OpenShift GitOps Operator

```bash
oc adm policy add-cluster-role-to-user cluster-admin -z openshift-gitops-argocd-application-controller -n openshift-gitops
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

2. **Create the bootstrap secret** on the cluster (this is the only secret not managed by ESO):

   ```bash
   oc create namespace external-secrets
   oc create secret generic bitwarden-cli -n external-secrets \
     --from-literal=BW_HOST=https://your-vaultwarden-url \
     --from-literal=BW_USERNAME=your-email \
     --from-literal=BW_PASSWORD=your-master-password
   ```

3. **Apply the ArgoCD kustomization** -- sync-wave ordering ensures ESO operator (-2) and
   bitwarden provider (-1) deploy before any ExternalSecret CRs are synced.

### Post-Install Steps

```bash
oc label service aap -n aap monitor=metrics
```

```bash
oc patch AutomationController aap-controller -n aap --type=merge -p '{"spec": {"extra_settings": [{"metrics_utility_enabled": "true"}]}}'
```
