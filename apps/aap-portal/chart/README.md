# Ansible self-service automation portal Helm Chart

A Helm chart for deploying self-service automation portal.

## Introduction

This chart deploys Ansible self-service automation portal using the Helm chart packaging format. This chart is designed for use alongside an Ansible Automation Platform (AAP) instance, so you can authenticate with AAP.

The telemetry data collection feature is enabled by default. For more information, see the [Telemetry capturing](#telemetry-capturing) section. 

## Usage

This chart is available in the following formats:

- [OpenShift Helm Catalog](https://docs.redhat.com/en/documentation/openshift_container_platform)
- [Chart Repository](https://helm.sh/docs/topics/chart_repository/)

## Installing from OpenShift Helm Catalog

**Note:** The install name must be unique for each deployment to avoid conflicts with existing releases. If a release with the same name already exists, the installation will fail.

### Prerequisites

The following prerequisites are needed before installation:

- Kubernetes 1.25+ (OpenShift 4.12+)
- Helm 3.10+ or [latest release](https://github.com/helm/helm/releases)
- `PersistentVolume` provisioner support in the underlying infrastructure is available
- [Backstage container image](https://backstage.io/docs/deployment/docker)
- A plugin registry containing the required plugins deployed in the OpenShift environment (see the [Create plugin registry](#create-plugin-registry) section below for details)
- Secrets containing AAP authentication values and SCM tokens created as shown in the [Create OpenShift secrets](#create-openshift-secrets) section below.

### Procedure

1. Ensure you have completed all prerequistes listed above. 
2. Click the "Create" button at the top of the modal dialog on the chart page.
3. Update the values shown below in the "Create Helm Release" YAML view. 
    - To get proper connection between frontend and backend of Backstage, update the `clusterRouterBase` key to match your cluster host URL:

        ```yaml
        redhat-developer-hub:
        global:
            clusterRouterBase: apps.example.com
        ```

    - (Optional) Update the Support link URL in the header to point to your customer support portal. By default, it points to `https://access.redhat.com/support`:

        ```yaml
        redhat-developer-hub:
          upstream:
            backstage:
              extraEnvVars:
                - name: CUSTOMER_SUPPORT_URL
                  value: https://your-support-portal.example.com
        ```

4. Click "Create" at the bottom of the page to launch the deployment. 

## Plugin Deployment Options

There are two options for deploying the Ansible plugins:

1. **Container Image (Recommended)**: Pull plugins directly from the Red Hat container registry as OCI artifacts. See [Using Container Image from registry.redhat.io](#using-container-image-from-registryredhatio).
2. **Plugin Registry (Deprecated)**: Deploy a local plugin registry with downloaded tarball files. See [Create plugin registry](#create-plugin-registry).

### Using Container Image from registry.redhat.io

The recommended approach is to consume plugins directly from the `registry.redhat.io/ansible-automation-platform/automation-portal` container image as OCI artifacts.

#### Prerequisites for registry.redhat.io

To pull OCI plugin artifacts from `registry.redhat.io`, you must configure authentication for the dynamic plugin installer.

1. **Create a Red Hat account**: If you don't have one, register at [Red Hat Customer Portal](https://access.redhat.com/).

2. **Create a registry service account** (recommended for production):
   - Navigate to [Registry Service Accounts](https://access.redhat.com/terms-based-registry/)
   - Create a new service account token
   - Note the generated username (format: `<random-string>|<your-token-name>`) and token

3. **Create the dynamic-plugins-registry-auth secret**:

   This secret is used by the dynamic plugin installer to authenticate when downloading plugins from the OCI registry.

   First, create an `auth.json` file with your credentials:
   ```json
   {
     "auths": {
       "registry.redhat.io": {
         "auth": "<base64-encoded-username:password>"
       }
     }
   }
   ```

   To generate the base64-encoded auth value:
   ```console
   echo -n '<username>:<password>' | base64 -w0
   ```

   Then create the secret. The secret name must follow the pattern `<release-name>-dynamic-plugins-registry-auth`:

   - **OpenShift Catalog installation**: The default release name is `redhat-rhaap-portal`, so create:
     ```console
     oc create secret generic redhat-rhaap-portal-dynamic-plugins-registry-auth \
       --from-file=auth.json=./auth.json
     ```

   - **Manual Helm installation**: Use the release name you specify during `helm install <release-name> ...`:
     ```console
     oc create secret generic <release-name>-dynamic-plugins-registry-auth \
       --from-file=auth.json=./auth.json
     ```

   **Note:** The secret must be created in the same namespace as the Helm release and before installing/upgrading the chart.

   Alternatively, if you already have podman/docker credentials configured locally:
   ```console
   oc create secret generic redhat-rhaap-portal-dynamic-plugins-registry-auth \
     --from-file=auth.json=${XDG_RUNTIME_DIR}/containers/auth.json
   ```

#### Configuring the Helm Chart for Container Image

The chart uses `pluginMode` to control how plugins are loaded in production. By default, it is set to `oci` (recommended). To explicitly configure it, update your values.yaml:

```yaml
redhat-developer-hub:
  global:
    # Plugin installation mode for production environment:
    # - oci: (Recommended) Pull plugins from registry.redhat.io as OCI artifacts
    # - tarball: (Deprecated) Use local plugin registry with downloaded tarball files
    pluginMode: oci
    imageTagInfo: "2.2"  # Specify the plugin version tag
```

When using OCI mode, the plugins are automatically pulled from `registry.redhat.io/ansible-automation-platform/automation-portal` using the version specified in `imageTagInfo`.

---

## Create plugin registry

> **DEPRECATION WARNING**: The plugin registry approach using tarball files is deprecated and will be removed in a future release. Please migrate to using the [Container Image from registry.redhat.io](#using-container-image-from-registryredhatio) approach described above.

To use the deprecated tarball mode, set `pluginMode` to `tarball` in your values.yaml:

```yaml
redhat-developer-hub:
  global:
    pluginMode: tarball
```

### Log into OpenShift CLI

To deploy a plugin registry or to manually install the Helm chart, follow the [instructions](https://docs.redhat.com/en/documentation/openshift_container_platform/4.8/html/cli_tools/openshift-cli-oc#installing-openshift-cli) for installing OpenShift CLI (`oc`) locally, then follow the [instructions](https://docs.redhat.com/en/documentation/openshift_container_platform/4.8/html/cli_tools/openshift-cli-oc#cli-logging-in_cli-developer-commands) to log in.

Use the following command to create a new OpenShift project:
```console
oc new-project <project-name>
```

Or, switch to an existing project with the following command:
```console
oc project <project-name>
```

### Download plugins and push to the registry

First, create a local directory to store the plugin .tar files.

```console
mkdir /path/to/<ansible-backstage-plugins-local-dir-changeme>
```

Set an environment variable `DYNAMIC_PLUGIN_ROOT_DIR` to represent the directory path.

```console
export DYNAMIC_PLUGIN_ROOT_DIR=/path/to/<ansible-backstage-plugins-local-dir-changeme>
```

Download the the latest .tar file for the plugins from the [Red Hat Ansible Automation Platform Product Software downloads page](https://access.redhat.com/downloads/content/480/ver=2.5/rhel---9/2.5/x86_64/product-software) to the `DYNAMIC_PLUGIN_ROOT_DIR` path. The format of the filename is ansible-backstage-rhaap-bundle-x.y.z.tar.gz. Substitute the Ansible plugins release version, for example 1.0.0, for x.y.z. Extract the contents inside the directory and run `ls` to ensure the plugin .tar and integrity files are present.

Next, create an httpd service as part of your OpenShift project. Ensure you're using the correct OpenShift project before deploying the service (verify using `oc projects`).

```console
oc new-build httpd --name=plugin-registry --binary
oc start-build plugin-registry --from-dir=$DYNAMIC_PLUGIN_ROOT_DIR --wait
oc new-app --image-stream=plugin-registry
```

## Create OpenShift secrets

Before installing the chart, you must create a set of secrets in your OpenShift project. 

In the OpenShift console, ensure your project is selected. Navigate to "Secrets" on the sidebar panel, and click on the blue "Create" dropdown on the page. Select the "Key/value secret" option and add the keys and values as indicated below.

NOTE: The secrets must have the **exact** name and key names shown below to work properly! 

### AAP authentication secrets

Create a secret named `secrets-rhaap-portal`. Add the following keys with the appropriate values to the secret:

1. Key: `aap-host-url`

    Value needed: AAP instance URL

2. Key: `oauth-client-id`

   Value needed: AAP OAuth client ID

3. Key: `oauth-client-secret`

   Value needed: AAP OAuth client secret value

4. Key: `aap-token`

   Value needed: Token for AAP user authentication (must have `write` access)

### Github and Gitlab secrets

Create a secret named `secrets-scm`. Add the following key/value pairs to the secret:

1. Key: `github-token`

   Value needed: Github Personal Access Token (PAT)

2. Key: `gitlab-token`

   Value needed: Gitlab Personal Access Token (PAT)

For details on generating a token and setting up integrations for Github and Gitlab, refer to [GitHub Integration Guide](https://backstage.io/docs/integrations/github/locations#configuration) or [GitLab Integration Guide](https://backstage.io/docs/integrations/gitlab/locations).

## Manual Installation from the chart repository

### Prerequisites

- See the [Installation prerequisites](#installation-prerequisites) section above
- Log into OpenShift CLI and create a new project (see the [Log into OpenShift CLI](#log-into-openshift-cli) section)

**Procedure**

1. Ensure you have completed all prerequisites.
2. Create your own values.yaml file and populate the keys below.

    - To get proper connection between frontend and backend of Backstage, update the clusterRouterBase key to match your cluster host URL:

        ```yaml
        redhat-developer-hub:
          global:
            clusterRouterBase: apps.example.com
        ```
3. (Optional) Update the Support link URL in the header to point to your customer support portal:

        ```yaml
        redhat-developer-hub:
          upstream:
            backstage:
              extraEnvVars:
                - name: CUSTOMER_SUPPORT_URL
                  value: https://your-support-portal.example.com
        ```

4. Add the chart repository using the following command:

    ```console
    helm repo add openshift-helm-charts https://charts.openshift.io/
    ```

5. Install the chart:

    ```console
    helm install <release-name> openshift-helm-charts/redhat-rhaap-portal -f <your-values-file>
    ```

    Example:
    ```console
    helm install my-release openshift-helm-charts/redhat-rhaap-portal -f my-values.yaml
    ```

## Uninstalling the chart

To uninstall/delete the Helm deployment, run:

```console
helm uninstall <release-name>
```

Example:
```console
helm uninstall my-release
```

This command removes all the Kubernetes components associated with the chart and deletes the release. 

Releases can also be deleted in the OpenShift console, from the Helm -> Helm Releases page. 

## Upgrading the chart

### Upgrade procedure

To upgrade an existing installation to a new version:

1. **Update the Helm repository**:
   ```console
   helm repo update openshift-helm-charts
   ```

2. **Review release notes**: Check the [Ansible RHDH Plugins releases](https://github.com/ansible/ansible-rhdh-plugins/releases) for any breaking changes or new features.

3. **Update imageTagInfo** (if using OCI mode): Update the `imageTagInfo` value to the desired plugin version:
   ```yaml
   redhat-developer-hub:
     global:
       imageTagInfo: "2.2"  # Update to new version
   ```

4. **Upgrade the release**:
   ```console
   helm upgrade <release-name> openshift-helm-charts/redhat-rhaap-portal -f <your-values-file>
   ```

### Version compatibility matrix

| Chart Version | Plugin Version | RHDH Version | Notes |
|---------------|----------------|--------------|-------|
| 2.1.x         | 2.2.0          | 1.9          | Current stable release |

### Migrating from tarball to OCI mode

If you are currently using the deprecated tarball/plugin-registry approach and want to migrate to OCI mode:

1. **Create the registry authentication secret** (see [Prerequisites for registry.redhat.io](#prerequisites-for-registryredhatio)):
   ```console
   oc create secret generic <release-name>-dynamic-plugins-registry-auth \
     --from-file=auth.json=./auth.json
   ```

2. **Update your values.yaml** to use OCI mode:
   ```yaml
   redhat-developer-hub:
     global:
       pluginMode: oci
       imageTagInfo: "2.2"
   ```

3. **Upgrade the release**:
   ```console
   helm upgrade <release-name> openshift-helm-charts/redhat-rhaap-portal -f <your-values-file>
   ```

4. **(Optional) Clean up the old plugin registry**: Once you've verified the upgrade is successful, you can remove the httpd plugin registry deployment:
   ```console
   oc delete deployment plugin-registry
   oc delete service plugin-registry
   oc delete buildconfig plugin-registry
   oc delete imagestream plugin-registry
   ```

## Installing in an air-gapped environment

For detailed instructions on installing in a disconnected or air-gapped environment, see [docs/air-gapped-installation.md](docs/air-gapped-installation.md).

The air-gapped documentation covers:

- Prerequisites and images to mirror
- Mirroring RHDH chart images using `oc-mirror`
- Mirroring Ansible plugin OCI artifacts and Dev Tools images
- Registry authentication (required for OCI plugin mode)
- Configuring `imageRegistry` and `ociPluginImage` values
- SSL certificate verification and custom CA certificates
- Complete air-gapped values example
- Troubleshooting common issues

## Telemetry capturing

The telemetry data collection feature helps in collecting and analyzing the telemetry data to improve your experience with Automation Portal. This feature is enabled by default.

Red Hat collects and analyses the following data:

- Events of page visits and clicks on links or buttons.
- System-related information, for example, locale, timezone, user agent including browser and OS details.
- Page-related information, for example, title, category, extension name, URL, path, referrer, and search parameters.
- Anonymized IP addresses, recorded as 0.0.0.0.
- Anonymized username hashes, which are unique identifiers used solely to identify the number of unique users of the application.

## Chart Values List

| Key | Description | Type | Default |
|-----|-------------|------|---------|
| global.clusterRouterBase | Shorthand for users who do not want to specify a custom HOSTNAME. Used ONLY with the DEFAULT upstream.backstage.appConfig value and with OCP Route enabled. | string | `"apps.example.com"` |
| global.imageTagInfo | The image tag for ansible-backstage-plugins images. Used as the OCI image tag when `pluginMode` is set to `oci`. | string | `"2.2"` |
| global.pluginMode | Plugin installation mode for production environment. Use `tarball` to use local plugin registry with downloaded tarball files, or `oci` to pull plugins from registry.redhat.io as OCI artifacts. | string | `"tarball"` |
| global.imageRegistry | Global container image registry for disconnected/air-gapped environments. Replaces `registry.redhat.io` across all images (RHDH hub, PostgreSQL, OCI plugin artifacts, and Dev Tools sidecar). Must be the registry host only. | string | `""` |
| global.ociPluginImage | Full OCI plugin image path (registry + repository) for mirrors with non-standard repository paths. Overrides `imageRegistry` and the default `ansible-automation-platform/automation-portal` path for plugin OCI artifacts only. | string | `""` |
| upstream.backstage.extraEnvVars | List of additional environment variables for the deployment. | list | (See the chart) |
| upstream.backstage.appConfig | Application configuration for the self-service automation installation. | object | `{"ansible":"","auth":"","catalog":""}` |
| upstream.backstage.appConfig.ansible.rhaap.checkSSL | Enable or disable SSL certificate verification for the AAP API connection. Set to `false` when AAP uses self-signed or internal CA certificates. | bool | `true` |
| upstream.backstage.appConfig.auth.providers.rhaap.production.checkSSL | Enable or disable SSL certificate verification for AAP OAuth authentication. Set to `false` when AAP uses self-signed or internal CA certificates. | bool | `true` |
| upstream.backstage.appConfig.catalog.providers.rhaap.production.orgs | The AAP organization name to sync catalog entities from. Set to your AAP organization name. | string | `"Default"` |
| upstream.backstage.image | RHDH image registry parameters. | object | `{"registry":"registry.redhat.io","repository":"rhdh/rhdh-hub-rhel9","tag":"1.8"}` |
| upstream.backstage.image.registry | Registry to pull the RHDH image from. | string | `registry.redhat.io` |
| upstream.backstage.image.repository | Repository to pull the RHDH image from. | string | `rhdh/rhdh-hub-rhel9` |
| upstream.backstage.image.tag | RHDH image tag. | string | `1.8` |
| upstream.backstage.extraEnvVars.CUSTOMER_SUPPORT_URL | URL for the Support link in the application header. Update this to point to your customer support portal. | string | `https://access.redhat.com/support` |
