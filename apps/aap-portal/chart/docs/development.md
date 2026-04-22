# Developing with Ansible Backstage plugins and this Helm chart

There are two environments set up in this chart: **development** and **production**. This chart defaults to using the production environment and can be switched to development if you are testing changes to the Ansible plugins or this chart.  

The production environment requires a plugin-registry set up in your OpenShift project, while the development environment pulls plugin images from the [ansible-backstage-plugins Quay repository](https://quay.io/repository/ansible/ansible-backstage-plugins). This repository stores images built from pull request changes on the [ansible-backstage-plugins repository](https://github.com/ansible/ansible-backstage-plugins/tree/main). The `main` tag is pulled by default. 

## Development Environment

To switch to using the development environment, see the instructions in the values section below. 

### Create secret to access private Quay repository

Ensure your podman/docker credentials are stored in an auth.json file. Next, use the below command to add a secret to your OpenShift environment using the auth file.

```console
oc create secret generic <install-name>-dynamic-plugins-registry-auth --from-file=<path-to-auth.json>
```

Example:
```console
oc create secret generic my-installation-dynamic-plugins-registry-auth --from-file=<path-to-auth.json>
```

**Note:** The secret must have this exact name pattern in order to work correctly.

### Update values file

**If installing from the OpenShift Helm Catalog:** Update the values shown below in the "Create Helm Release" YAML view. 

**If installing locally from chart source:** Create your own values.yaml file and populate the keys below. 

- Update the `global._environment._production` key to `false`, and the `global._environment._development` key to `true`.
 
     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         global:
           _environment:
             _production: false
             _development: true
     ```

- To get proper connection between frontend and backend of Backstage, update the clusterRouteBase key value to your cluster host URL:

     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         global:
           clusterRouterBase: apps.your.cluster.url.com
     ```

- Under global.imageTagInfo, you can either update the Quay image tag inside your values file, or pass the value via the command line using `--set global.imageTagInfo=<image-tag>`. This tag defaults to `main`. 

     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         global:
           imageTagInfo: pr-number # Required: Update here or pass using --set
     ```

- **Optional**: If you are using a development environment where you need to disable SSL checks, under the `appConfig.ansible.rhaap` section, update the `checkSSL` value from `true` to `false`. Also, update the `appConfig.auth.providers.rhaap.production` `checkSSL` value from `true` to `false`. 

    Under extraEnvVars in values.yaml, add the environment variable `NODE_TLS_REJECT_UNAUTHORIZED` with `value: '0'`. Make sure to add this in the `values.yaml` file, not your custom values file, as adding an entry into the extraEnvVars will override env vars in other value files. This is a known issue, with updates tracked [here](https://issues.redhat.com/browse/RHIDP-6082). 

    To allow users to sign in even if they are not present in the catalog, add `appConfig.dangerouslyAllowSignInWithoutUserInCatalog` and set its value to `true`.

     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         upstream:
           backstage:
             appConfig:
               ansible:
                 rhaap:
                   checkSSL: false
     ```

     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         upstream:
           backstage:
             appConfig:
               auth:
                 providers:
                   rhaap:
                     production:
                       checkSSL: false
     ```

     ```yaml
     # values.yaml
       redhat-developer-hub:
         upstream:
           backstage:
             extraEnvVars:
               - name: NODE_TLS_REJECT_UNAUTHORIZED
                 value: '0'
     ```

     ```yaml
     # my-values.yaml
       redhat-developer-hub:
         upstream:
           backstage:
             appConfig:
               dangerouslyAllowSignInWithoutUserInCatalog: true
     ```

### Installing from local chart repository

**Procedure**

1. Ensure you have already completed the steps as indicated in the README ["Create plugin registry"](../README.md#create-plugin-registry) section, or switched to the development environment. 
2. Create secrets as detailed in the README ['Create OpenShift secrets](../README.md#create-openshift-secrets) section.
3. Update your own values file as shown in the ["Update values file" section](#update-values-file) section. 
4. Use the following command to install the chart:

    ```console
    helm install <install-name> <path-to-chart> -f <your-values-file>
    ```

    Example:
    ```console
    helm install my-installation . -f my-values.yaml
    ```

## Contributing

For contributions to this chart, utilize the production or development environment as needed for testing.

### Pull Requests

If you want to submit code changes to this project, here are some guidelines:

1. **Create a branch - not from a fork.**

    Our PR test workflows utilize Github secrets, which are only accessible on branches of this repository, not from forks. If you receive an error during tests related to Quay authentication, verify that the PR was not opened from a fork.

2. **Implement your changes**

    If you make changes to required values that users must update before deployment, document this in the **"Values"** section above.

3. **Testing and Linting**

    You can use the `helm lint` command to test if your changes pass the linting check.

    For "local" testing, try deploying the helm chart with the development and production environments to your own OpenShift cluster.

4. **Open a pull request**

    Open a PR to automatically run our test workflows. Provide a clear description of the changes, including any Jira tickets or Github issues associated with the work. Provide an example of how to test your changes, if relevant.
