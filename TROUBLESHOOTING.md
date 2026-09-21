# OCP Lab Troubleshooting Guide

Practical runbook for the single-node OpenShift cluster in this lab. Add new
sections as you hit and fix issues — future you will thank present you.

## Lab Reference

| Item | Value |
|------|-------|
| Cluster | Single-node OpenShift (SNO) |
| Node hostname | `ocp.new.lab.danielsson.us.com` |
| Node IP | `192.168.2.120` |
| API | `https://api.ocp.new.lab.danielsson.us.com:6443` |
| Apps domain | `*.apps.ocp.new.lab.danielsson.us.com` |
| Console | `https://console-openshift-console.apps.ocp.new.lab.danielsson.us.com` |
| Supermicro BMC (IPMI) | `192.168.2.80` (credentials in your password manager) |
| DNS upstream | `192.168.2.1` (see `apps/cluster-config/dns-forwarders.yaml`) |

**Note:** `192.168.2.80` is the BMC/IPMI interface, not the OCP node. The node
runs at `192.168.2.120`.

---

## Quick Triage

Run these first when "the cluster isn't responding":

```bash
# 1. Is the host reachable?
ping -c 3 192.168.2.120

# 2. Is the Kubernetes API up? (control plane / etcd)
curl -k -s -o /dev/null -w "API healthz: HTTP %{http_code}\n" \
  https://api.ocp.new.lab.danielsson.us.com:6443/healthz

# 3. Can oc talk to the cluster?
oc whoami
oc get nodes

# 4. Are apps/console reachable? (ingress router on 443)
curl -k -s -o /dev/null -w "Console: HTTP %{http_code}\n" \
  https://console-openshift-console.apps.ocp.new.lab.danielsson.us.com

# 5. Is the node heartbeat current?
oc get --raw /api/v1/nodes/ocp.new.lab.danielsson.us.com | \
  python3 -c "import sys,json; n=json.load(sys.stdin); \
  print('Ready:', [c for c in n['status']['conditions'] if c['type']=='Ready']); \
  print('Last heartbeat:', n['status']['conditions'][0]['lastHeartbeatTime'])"

# 6. Any pending certificate requests?
oc get csr
```

### What the symptoms usually mean

| Symptom | API (6443) | Console/Apps (443) | Likely cause |
|---------|------------|---------------------|--------------|
| Nothing works | down | down | Host powered off, network issue, or full cluster crash |
| API works, apps don't | up | down | Ingress router not running, or kubelet not starting pods |
| API works, stale node heartbeat | up | down | Kubelet cert renewal stuck — check CSRs |
| oc works, browser can't resolve | up | DNS fail | Local DNS / `/etc/hosts` / router DNS forwarder |
| Pods stuck `Pending` | up | varies | Kubelet broken, ports held, or scheduling issue |
| Pods stuck `Terminating` | up | varies | Kubelet not cleaning up after unclean shutdown |

---

## After Power-Off or Long Downtime

**Most common post-reboot issue:** pending kubelet CSRs block certificate
renewal. The API server may still respond (static pods), but the kubelet cannot
sync pods, update node status, or bring up the ingress router.

### Symptoms

- `oc get nodes` shows `Ready`, but last heartbeat is days old
- Console and all `*.apps` URLs return connection refused or time out
- Ingress router pod stuck in `Pending` or `ContainerCreating`
- `oc get csr` shows `Pending` requests from `node-bootstrapper` or `system:node:...`
- Kubelet log/exec requests fail with TLS errors

### Fix

```bash
# List pending CSRs
oc get csr | grep -v Approved

# Approve all pending CSRs
oc get csr -o name | while read csr; do
  status=$(oc get "$csr" -o jsonpath='{.status.conditions[?(@.type=="Approved")].status}')
  if [ "$status" != "True" ]; then
    oc adm certificate approve "$csr"
  fi
done

# Watch recovery (heartbeat should update within a minute or two)
watch -n5 'oc get nodes; echo; oc get pods -n openshift-ingress; echo; oc get csr | grep Pending'
```

After CSRs are approved, expect:

1. Node heartbeat updates to today's date
2. Ingress router moves to `Running` and binds ports 80/443
3. Console returns HTTP 200 or 302

### Verify recovery

```bash
oc get nodes
oc get co
oc get pods -n openshift-ingress
curl -k -s -o /dev/null -w "Console: HTTP %{http_code}\n" \
  https://console-openshift-console.apps.ocp.new.lab.danielsson.us.com
```

### Why CSRs pile up

On SNO, kubelet client certificates normally auto-approve via the
`node-bootstrapper` service account. After an unclean shutdown or extended
power-off, the approval loop can fall behind. Manual approval is safe and is
the standard recovery step.

---

## Ingress / Console Not Loading

The default ingress controller runs as a `hostNetwork` pod on the control-plane
node, binding host ports 80, 443, and 1936.

### Check router status

```bash
oc get pods -n openshift-ingress -o wide
oc get ingresscontroller default -n openshift-ingress-operator
oc describe pod -n openshift-ingress -l \
  ingresscontroller.operator.openshift.io/deployment-ingresscontroller=default
```

### Common router failure modes

**Pod stuck `Pending` — "didn't have free ports"**

Another process (or a stuck terminating router pod) is holding 80/443/1936.

```bash
# Force-delete a stuck router pod
oc delete pod -n openshift-ingress -l \
  ingresscontroller.operator.openshift.io/deployment-ingresscontroller=default \
  --force --grace-period=0

# Restart the deployment
oc rollout restart deployment/router-default -n openshift-ingress
```

If ports are still blocked and you have node SSH access:

```bash
# On the node (as core user)
sudo ss -tlnp | grep -E ':443|:80|:1936'
```

**Pod `Running` but not `Ready` — startup probe 500**

Usually resolves once the openshift-apiserver route backend syncs after kubelet
recovery. Give it 1–2 minutes after CSR approval. Check router logs:

```bash
oc logs -n openshift-ingress -l \
  ingresscontroller.operator.openshift.io/deployment-ingresscontroller=default \
  --tail=50
```

**Console returns 503 then 200**

Normal during router startup. Wait for the pod to pass readiness on port 1936.

---

## Kubelet / Node Issues

### Stale node heartbeat

If `lastHeartbeatTime` is days or weeks old while the node shows `Ready`, the
kubelet is not communicating with the API server. Start with CSRs (see above).

### Kubelet TLS errors

```bash
# From a machine that can reach the node
curl -vk https://192.168.2.120:10250/healthz
```

A `tls: internal error` response often accompanies expired or unapproved kubelet
serving certificates. Approve pending `kubernetes.io/kubelet-serving` CSRs:

```bash
oc get csr | grep kubelet-serving
oc adm certificate approve <csr-name>
```

### Pods stuck Terminating

After unclean shutdown, cleanup can stall until kubelet recovers:

```bash
oc get pods -A --field-selector=status.phase=Failed
oc get pods -A | grep Terminating

# After kubelet is healthy, force-delete if needed
oc delete pod <name> -n <namespace> --force --grace-period=0
```

### oc exec / oc debug fails (webhook timeout)

If exec is blocked by a validating webhook (e.g. DevSpaces), the underlying
cluster networking or kubelet may still be unhealthy. Fix kubelet/CSRs first;
webhook timeouts often clear once pod networking recovers.

---

## BMC / IPMI (Out-of-Band Management)

Use the Supermicro BMC at `192.168.2.80` when the host is unresponsive and you
need power control without OS access.

```bash
# Install ipmitool (Fedora)
sudo dnf install -y ipmitool

# Check power state
ipmitool -I lanplus -H 192.168.2.80 -U ADMIN -P '<password>' power status

# Graceful hard reset
ipmitool -I lanplus -H 192.168.2.80 -U ADMIN -P '<password>' power reset

# Full power cycle (if reset is not enough)
ipmitool -I lanplus -H 192.168.2.80 -U ADMIN -P '<password>' power off
# wait ~30 seconds, confirm host is down (ping fails)
ipmitool -I lanplus -H 192.168.2.80 -U ADMIN -P '<password>' power on
```

After a BMC power cycle, wait 3–5 minutes for the host to ping, then 1–2 more
minutes for the API. **Always check CSRs** — a power cycle alone may not fix
cert renewal if requests are still pending.

BMC web UI: `https://192.168.2.80`

---

## Cluster Operators and API Aggregation

```bash
# All operators should be Available=True, Degraded=False
oc get co

# Degraded or Progressing operators
oc get co | awk '$3!="True" || $4!="False" || $5!="False" {print}'

# OpenShift API groups failing discovery (routes, builds, etc.)
oc get apiservice | grep False
```

If `route.openshift.io` or other OpenShift API groups show `FailedDiscoveryCheck`,
the openshift-apiserver pod may still be starting. Usually clears once kubelet and
networking recover.

---

## etcd

If the console shows an etcd defrag warning or you see `NOSPACE` alarms, follow
the etcdctl procedure in [README.md](README.md#etcdctl-defragmentation).

Quick check from inside the etcd pod:

```bash
oc rsh -n openshift-etcd -c etcdctl \
  $(oc get pods -n openshift-etcd -l k8s-app=etcd -o name | head -1)
etcdctl endpoint status --cluster -w table
etcdctl alarm list
```

---

## External Dependencies

These run outside the cluster but affect lab apps:

| Service | IP | Notes |
|---------|-----|-------|
| Vaultwarden / Bitwarden | `192.168.2.82` (via ESO config) | External Secrets pulls secrets from here |
| DNS / gateway | `192.168.2.1` | Cluster DNS forwarder upstream |
| TrueNAS | `192.168.2.82` | Monitored via Netdata |
| BMC / IPMI | `192.168.2.80` | Server out-of-band management |

If many ExternalSecrets are failing after downtime, confirm Vaultwarden is
reachable and the `bitwarden-cli` sync cronjob in `external-secrets` is running.

---

## Useful One-Liners

```bash
# Recent cluster events
oc get events -A --sort-by='.lastTimestamp' | tail -30

# Non-running pods
oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded

# Ingress and console smoke test
for url in \
  https://api.ocp.new.lab.danielsson.us.com:6443/healthz \
  https://console-openshift-console.apps.ocp.new.lab.danielsson.us.com \
  https://oauth-openshift.apps.ocp.new.lab.danielsson.us.com; do
  echo -n "$url -> "
  curl -k -s -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 5 "$url"
done

# Approve all pending CSRs (safe recovery shortcut)
oc get csr -o json | python3 -c "
import sys, json
for item in json.load(sys.stdin)['items']:
    approved = any(c.get('type')=='Approved' and c.get('status')=='True'
                   for c in item.get('status', {}).get('conditions', []))
    if not approved:
        print(item['metadata']['name'])
" | xargs -r oc adm certificate approve
```

---

## Issue Log (add your own entries)

Use this section to record problems and fixes specific to your environment.

### Template

```markdown
### YYYY-MM-DD — Short title

**Symptoms:**
- ...

**Root cause:**
- ...

**Fix:**
- ...

**Prevent:**
- ...
```

### 2026-09-21 — Cluster unresponsive after server power-on

**Symptoms:**
- API (`oc`, port 6443) worked; console and all app routes did not
- Node showed `Ready` but heartbeat was stuck on 2026-09-08
- Ingress router pod stuck `Pending` (ports unavailable) or not starting pods
- Five pending `kubernetes.io/kube-apiserver-client-kubelet` CSRs

**Root cause:**
- Kubelet could not renew TLS certificates after extended power-off
- Without valid certs, kubelet could not sync pods or update node status

**Fix:**
- `oc get csr -o name | xargs oc adm certificate approve`
- Approved follow-up `kubelet-serving` CSR once kubelet restarted
- Router came up; console returned HTTP 200

**Prevent:**
- After any power-off or long downtime, run `oc get csr` before assuming the
  cluster is healthy
- Consider a post-boot check script that alerts on pending CSRs
