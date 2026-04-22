# Installing the self-service automation portal in an air-gapped environment

You can install the Ansible self-service automation portal in a fully disconnected or partially disconnected environment using the Helm chart.

## Prerequisites

In addition to the standard prerequisites, you need the following for air-gapped environments:

- You have installed Red Hat OpenShift Container Platform 4.16 or later.
- You have access to a mirror registry that can be reached from the disconnected cluster.
- You have installed the OpenShift CLI (`oc`) on your workstation.
- Recommended: You have installed the [oc-mirror OpenShift CLI plugin v2](https://docs.openshift.com/container-platform/latest/installing/disconnected_install/installing-mirroring-disconnected.html).

## Images to mirror

The following container images must be available in your mirror registry:

| Image | Description |
|-------|-------------|
| `registry.redhat.io/rhdh/rhdh-hub-rhel9:1.8` | Red Hat Developer Hub |
| `registry.redhat.io/rhel9/postgresql-15` | PostgreSQL database |
| `registry.redhat.io/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest` | Ansible Dev Tools sidecar |
| `registry.redhat.io/ansible-automation-platform/automation-portal:<plugin-version>` | Ansible plugins OCI artifacts |

Replace `<plugin-version>` with the version specified in `imageTagInfo` in your Helm chart configuration (for example, `2.2`).

## Mirroring the RHDH chart images using oc-mirror

The RHDH base images (RHDH hub and PostgreSQL) can be mirrored using `oc-mirror`. Create an `ImageSetConfiguration` file:

```yaml
apiVersion: mirror.openshift.io/v2alpha1
kind: ImageSetConfiguration
mirror:
  helm:
    repositories:
      - name: openshift-charts
        url: https://charts.openshift.io
        charts:
          - name: redhat-rhaap-portal
            version: "2.1"
```

Mirror the resources to your target registry:

```console
$ oc mirror --v2 -c ImageSetConfiguration.yaml docker://<target-mirror-registry>
```

Then apply the generated IDMS and ITMS manifests to your cluster:

```console
$ oc apply -f <workspace_directory>/working-dir/cluster-resources
```

This configures OpenShift to redirect image pulls from `registry.redhat.io` to your mirror registry for the RHDH and PostgreSQL container images.

## Mirroring the Ansible plugin OCI artifacts and Dev Tools images

The Ansible-specific images are not included in the RHDH chart mirror set and must be mirrored separately. The Ansible plugin OCI artifacts image is pulled by `skopeo` inside the dynamic plugin init container, which does **not** use the cluster-level IDMS/ITMS mirror configuration.

Mirror the images from a connected host:

```console
podman pull registry.redhat.io/ansible-automation-platform/automation-portal:<plugin-version>
podman tag registry.redhat.io/ansible-automation-platform/automation-portal:<plugin-version> \
  <your-mirror-registry>/ansible-automation-platform/automation-portal:<plugin-version>
podman push <your-mirror-registry>/ansible-automation-platform/automation-portal:<plugin-version>

podman pull registry.redhat.io/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest
podman tag registry.redhat.io/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest \
  <your-mirror-registry>/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest
podman push <your-mirror-registry>/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest
```

When mirroring images, you must preserve the original repository paths. For example, mirror `registry.redhat.io/ansible-automation-platform/automation-portal:2.2` to `<your-mirror-registry>/ansible-automation-platform/automation-portal:2.2`.

## Registry authentication (required)

The `install-dynamic-plugins` init container uses `skopeo` to pull OCI plugin artifacts. It does **not** use cluster pull secrets, global pull secrets, or `imagePullSecrets`. A dedicated auth secret is **required** -- even when pulling directly from `registry.redhat.io`.

### Creating the auth secret for registry.redhat.io

If pulling plugins directly from Red Hat's registry, use your Red Hat service account credentials. You can create a service account at [access.redhat.com/terms-based-registry](https://access.redhat.com/terms-based-registry/).

```console
AUTHB64=$(printf '%s' '<service-account-username>:<service-account-password>' | base64 -w0)
cat > auth.json <<EOF
{
  "auths": {
    "registry.redhat.io": {
      "auth": "${AUTHB64}"
    }
  }
}
EOF

oc create secret generic <release-name>-dynamic-plugins-registry-auth \
  --from-file=auth.json=./auth.json -n <namespace>
```

### Creating the auth secret for a private/mirror registry

```console
AUTHB64=$(printf '%s' '<username>:<password>' | base64 -w0)
cat > auth.json <<EOF
{
  "auths": {
    "<your-mirror-registry-host>": {
      "auth": "${AUTHB64}"
    }
  }
}
EOF

oc create secret generic <release-name>-dynamic-plugins-registry-auth \
  --from-file=auth.json=./auth.json -n <namespace>
```

**Important:**

- The `base64` command must use the `-w0` flag to produce single-line output. Without it, the base64 value may contain line breaks that corrupt the `auth.json` file.
- The secret name must be `<helm-release-name>-dynamic-plugins-registry-auth`. For example, if your Helm release is `redhat-rhaap-portal`, the secret must be `redhat-rhaap-portal-dynamic-plugins-registry-auth`.

### Verifying the secret

```console
oc get secret <release-name>-dynamic-plugins-registry-auth \
  -o jsonpath='{.data.auth\.json}' -n <namespace> | base64 -d
```

The output should show the valid `auth.json` content with your credentials.

## Configuring the Helm chart

Create a values file for your air-gapped deployment:

```yaml
redhat-developer-hub:
  global:
    pluginMode: oci
    imageTagInfo: "2.2"
    # Replace registry.redhat.io with your mirror registry host.
    # This must be the registry host ONLY (e.g., "mirror.example.com" or
    # "mirror.example.com:5000"). Do NOT include any repository path.
    imageRegistry: "<your-mirror-registry-host>"
  upstream:
    backstage:
      image:
        repository: rhdh/rhdh-hub-rhel9
        tag: "1.8"
    postgresql:
      image:
        repository: rhel9/postgresql-15
        tag: "latest"
```

Setting `imageRegistry` replaces `registry.redhat.io` across **all** container images:

- **RHDH hub** and **PostgreSQL** -- via the Bitnami common chart helper built into the RHDH subchart
- **OCI plugin artifacts** (`automation-portal`) and **Ansible Dev Tools sidecar** -- via the Ansible portal chart helpers

The `imageRegistry` value must be the **registry host only** (for example, `mirror.example.com` or `mirror.example.com:5000`). Do not include any repository path:

```
# Correct -- registry host only:
imageRegistry: "yb-artifactory"
# Results in: yb-artifactory/ansible-automation-platform/automation-portal:2.2

# Incorrect -- includes repository path:
imageRegistry: "yb-artifactory/ansible-automation-platform"
# Results in: yb-artifactory/ansible-automation-platform/ansible-automation-platform/automation-portal:2.2 (duplicate path)
```

### Using a custom repository path for plugin OCI artifacts

If your mirror uses a different repository structure and you cannot preserve the default path (`ansible-automation-platform/automation-portal`), use the `ociPluginImage` value to specify the full image path:

```yaml
redhat-developer-hub:
  global:
    imageRegistry: "yb-artifactory"          # For RHDH hub, PostgreSQL, Dev Tools
    ociPluginImage: "yb-artifactory/custom-path/automation-portal"  # For OCI plugins only
```

Alternatively, you can override the individual plugin `package` URLs directly in your values file. This follows the same approach used by RHDH for its dynamic plugins:

1. Copy the default `values.yaml` from the chart to create your custom values file:

   ```console
   cp values.yaml my-values.yaml
   ```

2. In `my-values.yaml`, update each plugin `package` entry under `global.dynamic.plugins` to point to your mirror:

   ```yaml
   redhat-developer-hub:
     global:
       pluginMode: oci
       imageTagInfo: "2.2"
       dynamic:
         plugins:
           - package: "oci://<your-mirror-registry>/<your-repository-path>:<plugin-version>!ansible-plugin-scaffolder-backend-module-backstage-rhaap"
             disabled: false
             pluginConfig:
               dynamicPlugins:
                 backend:
                   ansible.plugin-scaffolder-backend-module-backstage-rhaap:
           - package: "oci://<your-mirror-registry>/<your-repository-path>:<plugin-version>!ansible-backstage-plugin-catalog-backend-module-rhaap"
             disabled: false
           - package: "oci://<your-mirror-registry>/<your-repository-path>:<plugin-version>!ansible-plugin-backstage-self-service"
             disabled: false
             pluginConfig:
               # ... (keep existing pluginConfig from values.yaml)
           - package: "oci://<your-mirror-registry>/<your-repository-path>:<plugin-version>!ansible-backstage-plugin-auth-backend-module-rhaap-provider"
             disabled: false
             pluginConfig: {}
   ```

   **Note:** When overriding `global.dynamic.plugins`, you must include **all** plugins in the list (including the RHDH built-in plugins you want enabled), since Helm replaces the entire list rather than merging individual entries.

3. You can include any other overrides (such as `checkSSL` or `orgs`) in the same values file.

4. Install or upgrade the chart:

   ```console
   helm install <release-name> <chart> -f my-values.yaml
   ```

   You can combine `-f` with `--set` flags. Values passed via `--set` take precedence:

   ```console
   helm install <release-name> <chart> -f my-values.yaml \
     --set global.clusterRouterBase="apps.mycluster.com"
   ```

### Digest-pinned image references

The RHDH chart defaults pin the RHDH hub and PostgreSQL images by SHA256 digest (for example, `rhel9/postgresql-15@sha256:ce71be...`). When mirroring with `podman tag` and `podman push`, the original digest is not preserved in the target registry. You must override the `repository` and `tag` fields as shown in the values example above to use tag-based references. Alternatively, use `skopeo copy` to mirror images, which preserves the original manifest digest.

### IDMS/ITMS and the dynamic plugin init container

If you have applied IDMS/ITMS manifests via `oc-mirror`, the RHDH hub and PostgreSQL images will already be redirected by the cluster. However, `imageRegistry` must still be set because the dynamic plugin init container uses `skopeo` directly to pull OCI plugin artifacts and does not use the cluster-level mirror configuration.

## SSL certificate verification

### AAP connection

Air-gapped environments often use self-signed or internal CA certificates for the AAP instance. If the AAP server uses such certificates, disable SSL certificate verification:

```yaml
redhat-developer-hub:
  upstream:
    backstage:
      appConfig:
        ansible:
          rhaap:
            checkSSL: false
        auth:
          providers:
            rhaap:
              production:
                checkSSL: false
```

Or pass via `--set` during installation:

```console
--set redhat-developer-hub.upstream.backstage.appConfig.ansible.rhaap.checkSSL=false \
--set redhat-developer-hub.upstream.backstage.appConfig.auth.providers.rhaap.production.checkSSL=false
```

### Plugin registry CA certificate

If your mirror registry uses a certificate signed by an internal or self-signed CA, the `install-dynamic-plugins` init container will fail with:

```
x509: certificate signed by unknown authority
```

You must mount your CA certificate into the init container so that `skopeo` trusts the registry. For detailed instructions on all available approaches, see the RHDH documentation: [Install plugins from OCI registries by using custom certificates](https://redhat-developer.github.io/red-hat-developers-documentation-rhdh/main/plugins-rhdh-install/#rinstall-plugins-from-oci-registries-by-using-custom-certificates).

The recommended approach is the **per-registry certificate** method, which mounts the CA certificate at the skopeo-native per-registry trust path. This does not modify system CA bundles and targets only the specific registry.

#### Step 1: Obtain the CA certificate

Get the CA certificate that signed your mirror registry's TLS certificate. If the registry uses a certificate chain (registry cert + intermediate CA + root CA), you must include the **full chain**:

```console
cat registry.crt intermediate.crt corporate-root.crt > ca-bundle.crt
```

You can verify the chain is correct:

```console
openssl verify -CAfile ca-bundle.crt registry.crt
```

Alternatively, you can extract the certificate from the registry directly:

```console
openssl s_client -showcerts -connect <registry-host>:443 </dev/null 2>/dev/null \
  | openssl x509 -outform PEM > ca-bundle.crt
```

Or request the CA certificate files from your infrastructure team.

#### Step 2: Create the ConfigMap

```console
oc create configmap registry-ca-crt \
  --from-file=ca.crt=ca-bundle.crt -n <namespace>
```

The key name must be `ca.crt` -- this is what skopeo looks for in the per-registry directory.

#### Step 3: Update the Helm values

Add the CA certificate volume and mount to your values file. Because Helm replaces arrays entirely (it cannot merge individual entries), you must provide the full `initContainers` and `extraVolumes` specification.

Add the volume to `extraVolumes`:

```yaml
redhat-developer-hub:
  upstream:
    backstage:
      extraVolumes:
        # ... all other existing volumes ...
        - name: registry-ca-crt
          configMap:
            name: registry-ca-crt
```

Add the volume mount to `initContainers`:

```yaml
      initContainers:
        - name: install-dynamic-plugins
          # ... keep all existing config (image, command, env, resources, etc.) ...
          volumeMounts:
            # ... all other existing volume mounts ...
            - name: registry-ca-crt
              mountPath: /etc/containers/certs.d/<registry-host>
              readOnly: true
```

**Important:**

- The `mountPath` must use the **registry hostname only** (for example, `/etc/containers/certs.d/mirror.example.com`). Do not include repository paths or the port for standard HTTPS (443). Skopeo matches the directory name against the registry host in the image URL.
- If the registry uses a non-standard port, include it in the path (for example, `/etc/containers/certs.d/mirror.example.com:5000`).

> **Note:** When upgrading to a new RHDH subchart version, review the upstream `initContainers` definition for any changes and update your override accordingly.

#### Debugging TLS certificate issues

If the CA certificate mount does not resolve the TLS error, temporarily override the init container command to `sleep infinity` and exec in to debug:

```yaml
initContainers:
  - name: install-dynamic-plugins
    command:
      - sleep
      - infinity
    # ... keep everything else the same ...
```

Then exec into the running init container:

```console
POD=$(oc get pods -n <namespace> -l app.kubernetes.io/component=backstage -o name)
oc exec -it $POD -c install-dynamic-plugins -n <namespace> -- bash

# Verify the cert file is mounted at the correct path
ls -la /etc/containers/certs.d/<registry-host>/

# Test skopeo with debug output
skopeo inspect --debug docker://<registry-host>/<image-path>:<tag>

# Test with TLS verification disabled to confirm it is a cert issue
skopeo inspect --tls-verify=false docker://<registry-host>/<image-path>:<tag>

# Test with an explicit cert directory (useful if the mount path is wrong)
skopeo inspect --debug --cert-dir=/etc/containers/certs.d/<actual-mount-path> \
  docker://<registry-host>/<image-path>:<tag>
```

After debugging, remove the `sleep infinity` command override and redeploy.

## Installing the chart

Deploy the Helm chart:

```console
CLUSTER_ROUTER_BASE=$(oc get route console -n openshift-console \
  -o=jsonpath='{.spec.host}' | sed 's/[.]*\.//')

helm install <release-name> <chart-archive> \
  --namespace <your-namespace> --create-namespace \
  -f values.yaml \
  --set global.clusterRouterBase="$CLUSTER_ROUTER_BASE"
```

## Complete air-gapped values example

Below is a complete values file for air-gapped deployments. Adjust values for your environment.

```yaml
redhat-developer-hub:
  global:
    clusterRouterBase: apps.mycluster.example.com

    # Plugin installation mode -- must be "oci" for air-gapped
    pluginMode: oci

    # Plugin OCI image tag version
    imageTagInfo: "2.2"

    # ---------------------------------------------------------------
    # Registry override (REQUIRED for air-gapped)
    # Set to your mirror registry HOST only. Do NOT include repo paths.
    # This replaces registry.redhat.io for: RHDH hub, PostgreSQL,
    # OCI plugin artifacts, and Ansible Dev Tools sidecar.
    # ---------------------------------------------------------------
    imageRegistry: "<your-mirror-registry-host>"

    # ---------------------------------------------------------------
    # Custom OCI plugin image path (OPTIONAL)
    # Only needed if your mirror uses a different repository structure
    # than the default (ansible-automation-platform/automation-portal).
    # When set, overrides imageRegistry for plugin OCI artifacts only.
    # Example: "my-registry.example.com/custom-repo/automation-portal"
    # ---------------------------------------------------------------
    # ociPluginImage: ""

  upstream:
    backstage:
      image:
        # Override RHDH hub image to use tag instead of digest
        repository: rhdh/rhdh-hub-rhel9
        tag: "1.8"

      appConfig:
        ansible:
          rhaap:
            # Set to false if AAP uses self-signed/internal CA certs
            checkSSL: true
        auth:
          providers:
            rhaap:
              production:
                # Set to false if AAP uses self-signed/internal CA certs
                checkSSL: true

    postgresql:
      image:
        # Override PostgreSQL image to use tag instead of digest
        repository: rhel9/postgresql-15
        tag: "latest"
```

**Before installing, create the required secrets:**

```console
# 1. Registry auth for the dynamic plugin init container (REQUIRED)
# Use your mirror registry credentials, or Red Hat service account for registry.redhat.io
AUTHB64=$(printf '%s' '<username>:<password>' | base64 -w0)
cat > auth.json <<EOF
{
  "auths": {
    "<your-mirror-registry-host>": {
      "auth": "${AUTHB64}"
    }
  }
}
EOF
oc create secret generic <release-name>-dynamic-plugins-registry-auth \
  --from-file=auth.json=./auth.json -n <namespace>

# 2. AAP authentication secrets
oc create secret generic secrets-rhaap-portal \
  --from-literal=aap-host-url="https://aap.example.com" \
  --from-literal=oauth-client-id="<client-id>" \
  --from-literal=oauth-client-secret="<client-secret>" \
  --from-literal=aap-token="<aap-token>" \
  -n <namespace>

# 3. SCM tokens (optional)
oc create secret generic secrets-scm \
  --from-literal=github-token="<token>" \
  --from-literal=gitlab-token="<token>" \
  -n <namespace>
```

## Troubleshooting

### Skopeo authentication failure pulling OCI plugins

**Symptom:** The `install-dynamic-plugins` init container fails. Pod logs show `authentication required` or `unauthorized: access denied`.

**Cause:** The auth secret is missing or malformed. The init container uses `skopeo` which requires its own auth secret -- it does **not** use cluster pull secrets or `imagePullSecrets`. This is required even when pulling from `registry.redhat.io`.

**Solution:** Create the auth secret. See [Registry authentication](#registry-authentication-required). Ensure you use `base64 -w0` (not `base64` alone) to avoid multiline base64 values that corrupt `auth.json`.

**Verify:** Check the init container logs and the secret content:

```console
oc logs <pod-name> -c install-dynamic-plugins -n <namespace>
oc get secret <release-name>-dynamic-plugins-registry-auth \
  -o jsonpath='{.data.auth\.json}' -n <namespace> | base64 -d
```

### Duplicate path in OCI plugin URL

**Symptom:** Pod logs show an error like:

```
failed to pull: oci://yb-artifactory/ansible-automation-platform/ansible-automation-platform/automation-portal:2.2
```

**Cause:** `imageRegistry` was set to include a repository path (e.g., `yb-artifactory/ansible-automation-platform`) instead of just the registry host. The chart appends `ansible-automation-platform/automation-portal` automatically, causing duplication.

**Solution:** Set `imageRegistry` to the registry host only:

```yaml
# Wrong:
imageRegistry: "yb-artifactory/ansible-automation-platform"

# Correct:
imageRegistry: "yb-artifactory"
```

If your mirror uses a different repository structure and you cannot preserve the default path, use `ociPluginImage` instead:

```yaml
global:
  imageRegistry: "yb-artifactory"          # For RHDH hub, PostgreSQL, Dev Tools
  ociPluginImage: "yb-artifactory/custom-path/automation-portal"  # For OCI plugins only
```

### x509 certificate error pulling OCI plugins

**Symptom:** The `install-dynamic-plugins` init container fails. Pod logs show `x509: certificate signed by unknown authority` or `tls: failed to verify certificate`.

**Cause:** The private registry uses a self-signed or internal CA certificate that `skopeo` inside the init container does not trust. The init container does not use cluster-level CA trust or OpenShift proxy CA settings automatically.

**Solution:** Mount the registry CA certificate into the init container using the per-registry certificate approach. See [Plugin registry CA certificate](#plugin-registry-ca-certificate) for complete instructions.

Quick steps:

1. Create a ConfigMap from the registry CA cert (include the full certificate chain if applicable):
   ```console
   cat registry.crt intermediate.crt corporate-root.crt > ca-bundle.crt
   oc create configmap registry-ca-crt --from-file=ca.crt=ca-bundle.crt -n <namespace>
   ```

2. Add the volume and mount to your values file:
   ```yaml
   extraVolumes:
     - name: registry-ca-crt
       configMap:
         name: registry-ca-crt

   initContainers:
     - name: install-dynamic-plugins
       volumeMounts:
         - name: registry-ca-crt
           mountPath: /etc/containers/certs.d/<registry-host>
           readOnly: true
   ```

**Important:** The `mountPath` must be the registry **hostname only** (for example, `/etc/containers/certs.d/mirror.example.com`). Do not include repository paths in the mount path.

### PostgreSQL image pull fails with digest-pinned reference

**Symptom:** The PostgreSQL pod fails with `ImagePullBackOff`. The image reference contains `@sha256:`.

**Cause:** The RHDH subchart pins PostgreSQL images by SHA256 digest by default. When mirroring with `podman tag/push`, the digest is not preserved.

**Solution:** Override with tag-based references in your values file:

```yaml
redhat-developer-hub:
  upstream:
    postgresql:
      image:
        repository: rhel9/postgresql-15
        tag: "latest"
```

Alternatively, use `skopeo copy` to mirror images (preserves the digest).

### Wrong value name for registry override

**Symptom:** Images still pull from `registry.redhat.io` despite setting a registry override.

**Cause:** Common mistakes include using `registry`, `image.registry`, or placing the value at the wrong nesting level.

**Solution:** The correct value path is:

```yaml
redhat-developer-hub:
  global:
    imageRegistry: "<your-mirror-registry-host>"
```

Not `global.registry`, not `imageRegistry` at the top level, and not `upstream.backstage.image.registry` (which only affects the RHDH hub image, not plugins or Dev Tools).

### Auth secret shows "Save file" instead of content in OpenShift console

**Symptom:** When viewing the auth secret in the OpenShift web console and clicking "Reveal values", the value shows "Save file" instead of the `auth.json` content.

**Cause:** The secret was created with the wrong key name or format.

**Solution:** Delete and recreate the secret ensuring the key is `auth.json`:

```console
oc delete secret <release-name>-dynamic-plugins-registry-auth -n <namespace>

AUTHB64=$(printf '%s' '<username>:<password>' | base64 -w0)
cat > auth.json <<EOF
{
  "auths": {
    "<registry-host>": {
      "auth": "${AUTHB64}"
    }
  }
}
EOF

oc create secret generic <release-name>-dynamic-plugins-registry-auth \
  --from-file=auth.json=./auth.json -n <namespace>
```
