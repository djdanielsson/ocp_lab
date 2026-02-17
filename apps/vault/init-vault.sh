#!/usr/bin/env bash
set -euo pipefail

# Vault Initialization Script for OpenShift
# This script initializes Vault, unseals it, enables the KV v2 secrets engine,
# configures Kubernetes authentication, seeds placeholder secrets, and creates
# the policy and role needed by the External Secrets Operator.
#
# Prerequisites:
#   - oc CLI logged in to the cluster
#   - Vault pod running in the 'vault' namespace (deployed via ArgoCD)
#
# Usage:
#   ./init-vault.sh
#
# The script will output unseal keys and root token -- save them securely!

VAULT_NAMESPACE="${VAULT_NAMESPACE:-vault}"
VAULT_POD="${VAULT_POD:-vault-0}"
ESO_NAMESPACE="${ESO_NAMESPACE:-openshift-external-secrets-operator}"
ESO_SA="${ESO_SA:-external-secrets-sa}"

vault_exec() {
  oc exec -n "${VAULT_NAMESPACE}" "${VAULT_POD}" -- sh -c "$1"
}

echo "=== Step 1: Initialize Vault ==="
INIT_OUTPUT=$(vault_exec "vault operator init -key-shares=1 -key-threshold=1 -format=json")
UNSEAL_KEY=$(echo "${INIT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['unseal_keys_b64'][0])")
ROOT_TOKEN=$(echo "${INIT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['root_token'])")

echo ""
echo "=========================================="
echo "  SAVE THESE CREDENTIALS SECURELY!"
echo "=========================================="
echo "  Unseal Key: ${UNSEAL_KEY}"
echo "  Root Token: ${ROOT_TOKEN}"
echo "=========================================="
echo ""

echo "=== Step 2: Unseal Vault ==="
vault_exec "vault operator unseal ${UNSEAL_KEY}"

echo "=== Step 3: Login with root token ==="
vault_exec "vault login ${ROOT_TOKEN}"

echo "=== Step 4: Enable KV v2 secrets engine ==="
vault_exec "vault secrets enable -path=secret kv-v2" || echo "KV engine may already be enabled"

echo "=== Step 5: Seed placeholder secrets ==="
echo "Writing AAP admin password..."
vault_exec "vault kv put secret/aap/admin-password password=CHANGEME"

echo "Writing AAP admin username..."
vault_exec "vault kv put secret/aap/admin username=admin"

echo "Writing Postgres controller config..."
vault_exec "vault kv put secret/aap/postgres-controller \
  host=aap-postgres-rw.aap.svc.cluster.local \
  port=5432 \
  database=controller \
  username=controller \
  password=CHANGEME \
  type=unmanaged"

echo "Writing Postgres EDA config..."
vault_exec "vault kv put secret/aap/postgres-eda \
  host=aap-postgres-rw.aap.svc.cluster.local \
  port=5432 \
  database=eda \
  username=eda \
  password=CHANGEME \
  type=unmanaged"

echo "Writing Postgres Hub config..."
vault_exec "vault kv put secret/aap/postgres-hub \
  host=aap-postgres-rw.aap.svc.cluster.local \
  port=5432 \
  database=hub \
  username=hub \
  password=CHANGEME \
  type=unmanaged"

echo "Writing Postgres Gateway config..."
vault_exec "vault kv put secret/aap/postgres-gateway \
  host=aap-postgres-rw.aap.svc.cluster.local \
  port=5432 \
  database=gateway \
  username=gateway \
  password=CHANGEME \
  type=unmanaged"

echo "=== Step 6: Create Vault policy for ESO ==="
vault_exec "vault policy write external-secrets - <<EOF
path \"secret/data/*\" {
  capabilities = [\"read\"]
}
path \"secret/metadata/*\" {
  capabilities = [\"read\", \"list\"]
}
EOF"

echo "=== Step 7: Enable and configure Kubernetes auth ==="
vault_exec "vault auth enable kubernetes" || echo "Kubernetes auth may already be enabled"

vault_exec "vault write auth/kubernetes/config \
  kubernetes_host=https://kubernetes.default.svc:443"

echo "=== Step 8: Create Vault role for ESO ==="
vault_exec "vault write auth/kubernetes/role/external-secrets \
  bound_service_account_names=${ESO_SA} \
  bound_service_account_namespaces=${ESO_NAMESPACE} \
  policies=external-secrets \
  ttl=1h"

echo ""
echo "=== Vault initialization complete! ==="
echo ""
echo "Vault is initialized, unsealed, and configured for External Secrets Operator."
echo "Update the placeholder passwords (CHANGEME) with real values:"
echo "  oc exec -n ${VAULT_NAMESPACE} ${VAULT_POD} -- vault kv put secret/aap/admin-password password=YOUR_REAL_PASSWORD"
echo "  oc exec -n ${VAULT_NAMESPACE} ${VAULT_POD} -- vault kv put secret/aap/postgres-controller ... password=YOUR_REAL_PASSWORD"
echo "  (repeat for postgres-eda, postgres-hub, postgres-gateway)"
echo ""
