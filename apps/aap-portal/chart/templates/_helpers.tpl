{{/*
    Updates the Quay image tag in dynamic.plugins.package values - development env only
*/}}
{{- define "deployment.quay-image-tag" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "%s" (.Values.global.imageTagInfo) -}}
    {{- end -}}
{{- end -}}

{{/*
    Updates the image tag for stage environment
*/}}
{{- define "deployment.image-tag" -}}
    {{- if .Values.global._environment._stage -}}
        {{- printf "%s" (.Values.global.imageTagInfo) -}}
    {{- end -}}
{{- end -}}

{{/*
    Returns the container image registry.
    Supports override via global.imageRegistry for disconnected/air-gapped environments.
*/}}
{{- define "deployment.registry" -}}
    {{- if .Values.global.imageRegistry -}}
        {{- printf "%s" .Values.global.imageRegistry -}}
    {{- else -}}
        {{- printf "%s" "registry.redhat.io" -}}
    {{- end -}}
{{- end -}}

{{/*
    Returns the full OCI plugin image path (registry + repository).
    If ociPluginImage is set, uses it directly.
    Otherwise, constructs from deployment.registry + default repo path.
*/}}
{{- define "deployment.oci-plugin-image" -}}
    {{- if .Values.global.ociPluginImage -}}
        {{- printf "%s" .Values.global.ociPluginImage -}}
    {{- else -}}
        {{- printf "%s/ansible-automation-platform/automation-portal" (include "deployment.registry" .) -}}
    {{- end -}}
{{- end -}}

{{/*
    Updates the extraContainers image.
    Supports override via global.imageRegistry for disconnected/air-gapped environments.
*/}}
{{- define "deployment.container-image" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "%s" "ghcr.io/ansible/community-ansible-dev-tools:latest" -}}
    {{- else if or .Values.global._environment._stage .Values.global._environment._production -}}
        {{- printf "%s/ansible-automation-platform-26/ansible-dev-tools-rhel9:latest" (include "deployment.registry" .) -}}
    {{- end -}}
{{- end -}}

{{- define "deployment.test.imagePullSecret" }}
    {{- printf "{\"auths\": {\"%s\": {\"auth\": \"%s\"}}}" (index .Values "redhat-developer-hub" "testImageCredentials" "registry") (printf "%s:%s" (index .Values "redhat-developer-hub" "testImageCredentials" "username") (index .Values "redhat-developer-hub" "testImageCredentials" "password") | b64enc) | b64enc }}
{{- end }}

{{- define "deployment.test.registryCredentials" }}
    {{- printf "{\"auths\": {\"%s\": {\"auth\": \"%s\"}}}" (index .Values "redhat-developer-hub" "registryCredentials" "registry") (printf "%s:%s" (index .Values "redhat-developer-hub" "registryCredentials" "username") (index .Values "redhat-developer-hub" "registryCredentials" "password") | b64enc) | b64enc }}
{{- end }}

{{- define "plugins.load.auth" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-backstage-plugin-auth-backend-module-rhaap-provider" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-backstage-plugin-auth-backend-module-rhaap-provider" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-backstage-plugin-auth-backend-module-rhaap-provider" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-backstage-plugin-auth-backend-module-rhaap-provider-dynamic-2.1.1.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.load.catalog" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-backstage-plugin-catalog-backend-module-rhaap" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-backstage-plugin-catalog-backend-module-rhaap" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-backstage-plugin-catalog-backend-module-rhaap" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-backstage-plugin-catalog-backend-module-rhaap-dynamic-2.1.1.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.load.self-service" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-plugin-backstage-self-service" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-plugin-backstage-self-service" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-plugin-backstage-self-service" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-plugin-backstage-self-service-dynamic-2.1.1.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.load.scaffolder" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-plugin-scaffolder-backend-module-backstage-rhaap" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-plugin-scaffolder-backend-module-backstage-rhaap" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-plugin-scaffolder-backend-module-backstage-rhaap" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-plugin-scaffolder-backend-module-backstage-rhaap-dynamic-2.1.1.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.integrity.auth" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "sha512-JJP1fCX+z8tStb9WCctuY5vTxWI4kaG2eduEK3wMMg7NXodo2snCVyWd3CH5Kf5kcsTza6q50dpRwwER1Cg8kg==" -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.integrity.catalog" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "sha512-JkR79YuPqx+/0wZWFPWdzoUzNzm0hqXR53DNdWNh6so/oBA3+yYqQM7onp9N/StJCpXZXpMoWUGxot7C1cnRJA==" -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.integrity.self-service" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "sha512-ta8GLVlUsOYyUMccjocom1R308hrCBqjIDUO2oPmjO6GjhIWL6pbgxSQjDder7Al4hbK+mwW/wfFPAGyGaiyUA==" -}}
    {{- end -}}
{{- end -}}

{{- define "plugins.integrity.scaffolder" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "sha512-0V3LJ5IFfMmsHUcybP9oA7YU8WheoVyrmE9YTyEiv4MDzg2wXFZODmqKDoPDm6Yp3+OWDbSaAP0obeogg0XVSA==" -}}
    {{- end -}}
{{- end -}}

{{/*
    APME frontend plugin package URL
*/}}
{{- define "plugins.load.apme-frontend" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-plugin-apme" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-plugin-apme" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-plugin-apme" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-plugin-apme-dynamic-0.1.0.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{/*
    APME backend plugin package URL
*/}}
{{- define "plugins.load.apme-backend" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "oci://quay.io/redhat-user-workloads/ansible-plugins-tenant/ansible-plugins:%s!ansible-plugin-apme-backend" (include "deployment.quay-image-tag" .) -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "oci://registry.stage.redhat.io/ansible-automation-platform/automation-portal:%s!ansible-plugin-apme-backend" (include "deployment.image-tag" .) -}}
    {{- else if .Values.global._environment._production -}}
        {{- if eq .Values.global.pluginMode "oci" -}}
            {{- printf "oci://%s:%s!ansible-plugin-apme-backend" (include "deployment.oci-plugin-image" .) (.Values.global.imageTagInfo) -}}
        {{- else -}}
            {{- printf "http://plugin-registry:8080/ansible-plugin-apme-backend-dynamic-0.1.0.tgz" -}}
        {{- end -}}
    {{- end -}}
{{- end -}}

{{/*
    APME frontend plugin integrity hash (tarball mode only)
*/}}
{{- define "plugins.integrity.apme-frontend" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "" -}}
    {{- end -}}
{{- end -}}

{{/*
    APME backend plugin integrity hash (tarball mode only)
*/}}
{{- define "plugins.integrity.apme-backend" -}}
    {{- if and .Values.global._environment._production (eq .Values.global.pluginMode "tarball") -}}
        {{- printf "" -}}
    {{- end -}}
{{- end -}}

{{- define "catalog.providers.env" -}}
    {{- if .Values.global._environment._development -}}
        {{- printf "development" -}}
    {{- else if .Values.global._environment._stage -}}
        {{- printf "stage" -}}
    {{- else if .Values.global._environment._production -}}
        {{- printf "production" -}}
    {{- end -}}
{{- end -}}
