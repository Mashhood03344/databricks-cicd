#!/usr/bin/env bash
set -euo pipefail

TARGET_ENVIRONMENT="${1:?target environment is required}"
RELEASE_ID="${2:?release id is required}"
ARTIFACT_HASH="${3:?artifact hash is required}"



if [[ ! "${RELEASE_ID}" =~ ^rc-[0-9]{8}-[0-9]+$ ]]; then
  echo "Invalid release id: ${RELEASE_ID}" >&2
  exit 1
fi

if [[ ! "${ARTIFACT_HASH}" =~ ^sha256:[a-fA-F0-9]{64}$ ]]; then
  echo "Invalid artifact hash: ${ARTIFACT_HASH}" >&2
  exit 1
fi

case "${TARGET_ENVIRONMENT}" in
  dev)
    BUNDLE_TARGET="dev"
    GITHUB_ENVIRONMENT="dev"
    WORKSPACE_TARGET="dev"
    PREVIOUS_ENVIRONMENT=""
    PREVIOUS_MANIFEST_PATH=""
    DEPLOYMENT_MANIFEST_NAME="dev-deployment-manifest.json"
    ;;
  uat)
    BUNDLE_TARGET="uat"
    GITHUB_ENVIRONMENT="uat"
    WORKSPACE_TARGET="uat"
    PREVIOUS_ENVIRONMENT="dev"
    PREVIOUS_MANIFEST_PATH="dev-deployment-manifest.json"
    DEPLOYMENT_MANIFEST_NAME="uat-deployment-manifest.json"
    ;;
  prod)
    BUNDLE_TARGET="prod"
    GITHUB_ENVIRONMENT="prod"
    WORKSPACE_TARGET="prod"
    PREVIOUS_ENVIRONMENT="uat"
    PREVIOUS_MANIFEST_PATH="uat-deployment-manifest.json"
    DEPLOYMENT_MANIFEST_NAME="prod-deployment-manifest.json"
    ;;
  *)
    echo "Unsupported target environment: ${TARGET_ENVIRONMENT}" >&2
    exit 1
    ;;
esac

echo "target_environment=${TARGET_ENVIRONMENT}"
echo "release_id=${RELEASE_ID}"
echo "artifact_hash=${ARTIFACT_HASH}"
echo "bundle_target=${BUNDLE_TARGET}"
echo "github_environment=${GITHUB_ENVIRONMENT}"
echo "workspace_target=${WORKSPACE_TARGET}"
echo "previous_environment=${PREVIOUS_ENVIRONMENT}"
echo "previous_manifest_path=${PREVIOUS_MANIFEST_PATH}"
echo "deployment_manifest_name=${DEPLOYMENT_MANIFEST_NAME}"