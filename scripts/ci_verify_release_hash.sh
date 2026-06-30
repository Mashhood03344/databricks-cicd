#!/usr/bin/env bash
set -euo pipefail

MANIFEST_PATH="${1:?release manifest path is required}"
ARTIFACT_PATH="${2:?release artifact path is required}"

if [ ! -f "${MANIFEST_PATH}" ]; then
  echo "Release manifest not found: ${MANIFEST_PATH}" >&2
  exit 1
fi

if [ ! -f "${ARTIFACT_PATH}" ]; then
  echo "Release artifact not found: ${ARTIFACT_PATH}" >&2
  exit 1
fi

MANIFEST_HASH="$(jq -r '.release.artifact_hash // empty' "${MANIFEST_PATH}")"

if [ -z "${MANIFEST_HASH}" ]; then
  echo "release.artifact_hash is missing or empty" >&2
  exit 1
fi

COMPUTED_HASH="sha256:$(sha256sum "${ARTIFACT_PATH}" | awk '{print $1}')"

if [ "${MANIFEST_HASH}" != "${COMPUTED_HASH}" ]; then
  echo "Release artifact hash verification failed." >&2
  echo "Manifest hash: ${MANIFEST_HASH}" >&2
  echo "Computed hash: ${COMPUTED_HASH}" >&2
  exit 1
fi

echo "Release artifact hash verification passed."