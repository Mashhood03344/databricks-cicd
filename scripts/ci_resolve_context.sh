#!/usr/bin/env bash
set -euo pipefail

EVENT_NAME="${1:?event name is required}"
BASE_REF="${2:-}"
REF_NAME="${3:-}"

if [ "${EVENT_NAME}" = "pull_request" ]; then
  BRANCH="${BASE_REF}"
else
  BRANCH="${REF_NAME}"
fi

case "${BRANCH}" in
  dev)
    BUNDLE_TARGET="dev"
    GITHUB_ENVIRONMENT="dev"
    ;;
  qa)
    BUNDLE_TARGET="uat"
    GITHUB_ENVIRONMENT="uat"
    ;;
  main)
    BUNDLE_TARGET="prod"
    GITHUB_ENVIRONMENT="prod"
    ;;
  *)
    echo "Unsupported branch: ${BRANCH}" >&2
    exit 1
    ;;
esac

if [ "${EVENT_NAME}" = "push" ] && [ "${BRANCH}" = "dev" ]; then
  SHOULD_BUILD_RELEASE="true"
else
  SHOULD_BUILD_RELEASE="false"
fi

echo "branch=${BRANCH}"
echo "bundle_target=${BUNDLE_TARGET}"
echo "github_environment=${GITHUB_ENVIRONMENT}"
echo "should_build_release=${SHOULD_BUILD_RELEASE}"