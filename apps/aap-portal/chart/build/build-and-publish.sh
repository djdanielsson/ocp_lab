#!/usr/bin/bash

CHART_VERSION="" # Developer Hub version (used as 'appVersion' in Chart.yaml and as image tag)
CHART_NAME="redhat-rhaap-portal"

# Check that appVersion key matches what's in the helper. TODO: Remove this section when plugin images are used. 
PACKAGED_PLUGIN_VERSION=$(grep -o 'ansible-backstage-plugin-auth[^ ]*-[0-9.]\+\.tgz' templates/_helpers.tpl | sed -E 's/.*-([0-9.]+)\.tgz/\1/')
APP_VERSION=$(yq -r '.appVersion' Chart.yaml)

if [[ "$PACKAGED_PLUGIN_VERSION" == "$APP_VERSION" ]]; then
    echo "Plugin package versions match appVersion key."
else
    echo "[ERROR] Plugin package versions do not match appVersion key. Check these values before attempting to publish."
    echo "Plugin package versions: $PACKAGED_PLUGIN_VERSION"
    echo "appVersion key value: $APP_VERSION"
    echo "Exiting..."
    exit 1
fi

# Check that RHDH chart version matches the image used in values
IMAGE_VALUES_VERSION=$(yq -r '."redhat-developer-hub".upstream.backstage.image.tag' values.yaml)
RHDH_CHART_VERSION=$(yq -r '.dependencies[] | select(.name == "redhat-developer-hub") | .version' Chart.yaml)

if [[ "$IMAGE_VALUES_VERSION" == "$RHDH_CHART_VERSION" ]]; then
    echo "Version of backstage image used matches the dependent chart."
else
    echo "[ERROR] Version of backstage image does NOT match the chart dependency."
    echo "Image version: $IMAGE_VALUES_VERSION"
    echo "Dependency version: $RHDH_CHART_VERSION"
    exit 1
fi

# Check that release tag matches version key
CHART_VERSION=$(yq -r '.version' Chart.yaml)
ADJUSTED_RELEASE_TAG=${RELEASE_TAG#v}

if [[ "$CHART_VERSION" == "$ADJUSTED_RELEASE_TAG" ]]; then
    echo "Chart version matches release tag value."
else
    echo "[ERROR] Chart version does not match release tag. Update the chart version before attempting to publish."
    echo "Chart version: $CHART_VERSION"
    echo "Release tag: $ADJUSTED_RELEASE_TAG"
    echo "Exiting..."
    exit 1
fi

echo "========== Publishing helm chart to openshift-helm-charts =========="

# Pull dependencies
if [[ $DEBUG -eq 1 ]]; then
    echo "Building dependencies..."
fi
helm repo add --force-update redhat-developer-hub https://charts.openshift.io 1>/dev/null
helm dependency build 1>/dev/null

# Clone openshift-helm-charts
CHART_DEST_PATH="/tmp/openshift-helm-charts-main/charts/redhat/redhat/${CHART_NAME}/${ADJUSTED_RELEASE_TAG}"
FULL_CHART_PATH="${CHART_DEST_PATH}/${CHART_NAME}-${CHART_VERSION}.tgz"

pushd /tmp >/dev/null || exit 1
rm -fr /tmp/openshift-helm-charts-main
git clone https://github.com/openshift-helm-charts/charts.git -q --depth=1 -b "main" "openshift-helm-charts-main"  >/dev/null
popd >/dev/null || exit 1

# Package chart

if [ -f "${FULL_CHART_PATH}" ]; then
  echo "[ERROR] Chart version v${CHART_VERSION} already exists. Exiting."
  exit 1
fi

rm -f "${FULL_CHART_PATH}"
helm package "${GITHUB_WORKSPACE}" -d "${CHART_DEST_PATH}"

if [ ! -f "${FULL_CHART_PATH}" ]; then
  echo "[ERROR] Packaged chart was not found in the expected destination: ${CHART_DEST_PATH}. Exiting."
  exit 1
else
  echo "Chart packaged successfully to ${FULL_CHART_PATH}."
fi

# TODO: Change user to service account
git config --global user.email "aap-portal-bot-admins@redhat.com"
git config --global user.name "aap-portal-bot"
git config --global push.default matching
git config --global pull.rebase false

# Pull openshift-helm-charts main
pushd "/tmp/openshift-helm-charts-main/charts/redhat/redhat/${CHART_NAME}/" >/dev/null || exit 1
git checkout main >/dev/null 2>&1 
git pull origin main >/dev/null
git pull origin >/dev/null

# Get chart repository fork and commit changes
git remote add aap-portal-bot https://x-access-token:"${GH_TOKEN}"@github.com/aap-portal-bot/charts.git

git checkout origin/main -b "release-${CHART_VERSION}" >/dev/null 2>&1 || true
git checkout "release-${CHART_VERSION}" >/dev/null 2>&1 || true
git add "${CHART_VERSION}"

COMMIT_MSG="Chart Release: redhat-rhaap-portal ${CHART_VERSION}"
git commit --no-gpg-sign -s -m "${COMMIT_MSG}" "${CHART_VERSION}"

# Delete branch (if it exists)
echo "Delete branch (if it exists)"
if [[ $(git ls-remote --heads https://github.com/aap-portal-bot/charts.git "refs/heads/release-${CHART_VERSION}") ]]; then
    git push aap-portal-bot --delete "release-${CHART_VERSION}"
fi

# Create new branch
echo "Create new branch"
git push aap-portal-bot release-"${CHART_VERSION}" >/dev/null 2>&1

# Create PR
echo "[INFO] Create PR https://github.com/openshift-helm-charts/charts/compare/main...aap-portal-bot:charts:release-${CHART_VERSION}?expand=1 ..."

gh repo set-default openshift-helm-charts/charts
gh pr create -t "${COMMIT_MSG}" -b "${COMMIT_MSG}" --base main --head aap-portal-bot:release-"${CHART_VERSION}"

popd >/dev/null || exit 1
rm -fr /tmp/openshift-helm-charts-main
