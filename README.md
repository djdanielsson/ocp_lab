# ocp_lab

Required to run before installing OpenShift GitOps Operator

```bash
oc patch storageclass lvms-vg1 -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

Required to run after installing OpenShift GitOps Operator

```bash
oc adm policy add-cluster-role-to-user cluster-admin -z openshift-gitops-argocd-application-controller -n openshift-gitops
```

Required to run after adding applications of apps (at least until I can figure out how to make Argo apply them)

```bash
oc patch secret aap-admin-password -n aap -p '{"metadata": {"annotations": {"replicator.v1.mittwald.de/replicate-to": "monitoring"}}}'
```

```bash
oc label service aap -n aap monitor=metrics
```

```bash
oc patch AutomationController aap-controller -n aap --type=merge -p '{"spec": {"extra_settings": [{"metrics_utility_enabled": "true"}]}}'
```
