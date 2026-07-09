# scripts/cd_verify_release_manifest.sh
#!/usr/bin/env bash
set -euo pipefail

MANIFEST_PATH="${1:?release manifest path is required}"
INPUT_RELEASE_ID="${2:?release id is required}"

if [ ! -f "${MANIFEST_PATH}" ]; then
  echo "Release manifest not found: ${MANIFEST_PATH}" >&2
  exit 1
fi

MANIFEST_DIR="$(dirname "${MANIFEST_PATH}")"

required_field() {
  local field_path="$1"
  local value

  value="$(jq -r "${field_path} // empty" "${MANIFEST_PATH}")"

  if [ -z "${value}" ]; then
    echo "Required manifest field is missing or empty: ${field_path}" >&2
    exit 1
  fi

  echo "${value}"
}

SCHEMA_VERSION="$(required_field '.schema_version')"
RELEASE_ID="$(required_field '.release.release_id')"
ARTIFACT_NAME="$(required_field '.release.artifact_name')"
ARTIFACT_HASH="$(required_field '.release.artifact_hash')"
RELEASE_ASSET_NAME="$(required_field '.release.release_asset_name')"
REPOSITORY="$(required_field '.build.repository')"
SOURCE_BRANCH="$(required_field '.build.source_branch')"
COMMIT_SHA="$(required_field '.build.commit_sha')"
WORKFLOW_RUN_ID="$(required_field '.build.workflow_run_id')"
WORKFLOW_RUN_NUMBER="$(required_field '.build.workflow_run_number')"
CREATED_AT_UTC="$(required_field '.build.created_at_utc')"


if [ "${SCHEMA_VERSION}" != "1.0" ]; then
  echo "Unsupported schema_version: ${SCHEMA_VERSION}" >&2
  exit 1
fi

if [ "${RELEASE_ID}" != "${INPUT_RELEASE_ID}" ]; then
  echo "Release ID mismatch. Input: ${INPUT_RELEASE_ID}, Manifest: ${RELEASE_ID}" >&2
  exit 1
fi

if [ "${ARTIFACT_NAME}" != "${RELEASE_ID}.zip" ]; then
  echo "Invalid artifact name: ${ARTIFACT_NAME}" >&2
  exit 1
fi

if [ "${RELEASE_ASSET_NAME}" != "${ARTIFACT_NAME}" ]; then
  echo "Invalid release asset name: ${RELEASE_ASSET_NAME}" >&2
  exit 1
fi

if [ "${SOURCE_BRANCH}" != "dev" ]; then
  echo "Invalid release source branch: ${SOURCE_BRANCH}" >&2
  exit 1
fi

if [[ ! "${ARTIFACT_HASH}" =~ ^sha256:[a-fA-F0-9]{64}$ ]]; then
  echo "Invalid artifact hash: ${ARTIFACT_HASH}" >&2
  exit 1
fi

ARTIFACT_PATH="${MANIFEST_DIR}/${ARTIFACT_NAME}"

if [ ! -f "${ARTIFACT_PATH}" ]; then
  echo "Release artifact not found: ${ARTIFACT_PATH}" >&2
  exit 1
fi

COMPUTED_HASH="sha256:$(sha256sum "${ARTIFACT_PATH}" | awk '{print $1}')"

if [ "${COMPUTED_HASH}" != "${ARTIFACT_HASH}" ]; then
  echo "Release artifact hash verification failed." >&2
  echo "Manifest hash: ${ARTIFACT_HASH}" >&2
  echo "Computed hash: ${COMPUTED_HASH}" >&2
  exit 1
fi

echo "release_id=${RELEASE_ID}"
echo "artifact_name=${ARTIFACT_NAME}"
echo "artifact_hash=${ARTIFACT_HASH}"
echo "release_asset_name=${RELEASE_ASSET_NAME}"
echo "repository=${REPOSITORY}"
echo "source_branch=${SOURCE_BRANCH}"
echo "commit_sha=${COMMIT_SHA}"
echo "workflow_run_id=${WORKFLOW_RUN_ID}"
echo "workflow_run_number=${WORKFLOW_RUN_NUMBER}"
echo "created_at_utc=${CREATED_AT_UTC}"
echo "Release manifest verification passed."
