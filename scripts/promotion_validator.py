#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


VALID_ENVIRONMENTS = {"dev", "uat", "prod"}
VALID_SCHEMA_VERSION = "1.0"
VALID_OPERATION_STATUSES = {"SUCCESS", "FAILED"}

DECISION_PROMOTION_VALID = "PROMOTION_VALID"
DECISION_PREVIOUS_MANIFEST_NOT_CANONICAL = (
    "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_CANONICAL"
)
DECISION_PREVIOUS_MANIFEST_NOT_FOUND = "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_FOUND"
DECISION_RELEASE_ID_MISMATCH = "RELEASE_ID_MISMATCH"
DECISION_ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
DECISION_INVALID_MANIFEST_SCHEMA = "INVALID_MANIFEST_SCHEMA"
DECISION_INVALID_PROMOTION_SEQUENCE = "INVALID_PROMOTION_SEQUENCE"
DECISION_WORKSPACE_TARGET_MISMATCH = "WORKSPACE_TARGET_MISMATCH"
DECISION_BUNDLE_TARGET_MISMATCH = "BUNDLE_TARGET_MISMATCH"
DECISION_PREVIOUS_ENVIRONMENT_MISMATCH = "PREVIOUS_ENVIRONMENT_MISMATCH"

SUCCESS_STATUS = "SUCCESS"
EXPECTED_OPERATION_ACTION = "bundle_deploy"

EXPECTED_EVIDENCE_STORAGE_TYPE = "github_release_asset"
EXPECTED_EVIDENCE_ARTIFACT_VERSION = "1.0"

VALID_FAILURE_REASONS = {
    "DEPLOY_COMMAND_FAILED",
    "DEPLOY_TIMEOUT",
    "DEPLOY_CANCELLED",
    "UNKNOWN_DEPLOYMENT_FAILURE",
}

VALID_EVIDENCE_ROLES = {
    "canonical",
    "historical",
}

CANONICAL_EVIDENCE_ROLE = "canonical"
HISTORICAL_EVIDENCE_ROLE = "historical"

RELEASE_ID_PATTERN = re.compile(
    r"^rc-(\d{8})-([1-9]\d*)$"
)

ARTIFACT_HASH_PATTERN = re.compile(
    r"^sha256:[a-f0-9]{64}$"
)

UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}Z$"
)

MAX_MANIFEST_SIZE_BYTES = 1_048_576

EXPECTED_LOADABLE_MANIFEST = (
    "readable JSON within the maximum allowed size"
)

def utc_now_iso():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

def parse_utc_timestamp(value):
    if (
        not isinstance(value, str)
        or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None
    ):
        return None

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def previous_environment_for(target_environment):
    if target_environment == "dev":
        return None
    if target_environment == "uat":
        return "dev"
    if target_environment == "prod":
        return "uat"
    return None

def expected_promotion_metadata(environment):
    if environment == "dev":
        return {
            "from_environment": None,
            "to_environment": "dev",
            "required_previous_environment": None,
        }

    if environment == "uat":
        return {
            "from_environment": "dev",
            "to_environment": "uat",
            "required_previous_environment": "dev",
        }

    if environment == "prod":
        return {
            "from_environment": "uat",
            "to_environment": "prod",
            "required_previous_environment": "uat",
        }

    return None


def default_previous_manifest_path(target_environment):
    previous_environment = previous_environment_for(target_environment)

    if previous_environment is None:
        return None

    return f"{previous_environment}-deployment-manifest.json"


def default_output_path(target_environment):
    return f"{target_environment}-promotion-validation-result.json"


def build_check(name, status, expected, actual):
    return {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }


def build_result(
    decision,
    valid,
    target_environment,
    release_id,
    artifact_hash,
    previous_environment,
    previous_manifest_path,
    message,
    checks,
):
    return {
        "schema_version": "1.0",
        "generated_at_utc": utc_now_iso(),
        "decision": decision,
        "valid": valid,
        "target_environment": target_environment,
        "release_id": release_id,
        "artifact_hash": artifact_hash,
        "previous_environment": previous_environment,
        "previous_manifest_path": str(previous_manifest_path) if previous_manifest_path else None,
        "message": message,
        "checks": checks,
    }


def write_json_atomic(
    output_path: str | Path,
    data: dict,
) -> None:
    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

            temp_file.write(
                json.dumps(data, indent=2) + "\n"
            )

            temp_file.flush()
            os.fsync(temp_file.fileno())

        temp_path.replace(output_path)

    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

        raise

def write_validation_result_or_exit(
    output_path,
    result,
) -> None:
    try:
        write_json_atomic(
            output_path,
            result,
        )
    except OSError as exc:
        raise SystemExit(
            "Failed to write promotion validation "
            f"result to {output_path}: {exc}"
        ) from exc

def reject_duplicate_json_keys(pairs):
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError(
                f"Duplicate JSON key: {key}"
            )

        result[key] = value

    return result

def load_manifest(path):
    manifest_path = Path(path)

    with manifest_path.open("rb") as file:
        content = file.read(
            MAX_MANIFEST_SIZE_BYTES + 1
        )

    if len(content) > MAX_MANIFEST_SIZE_BYTES:
        raise ValueError(
            "Deployment manifest exceeds maximum "
            f"allowed size of "
            f"{MAX_MANIFEST_SIZE_BYTES} bytes"
        )

    try:
        decoded_content = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Deployment manifest must contain valid UTF-8"
        ) from exc

    return json.loads(
        decoded_content,
        object_pairs_hook=reject_duplicate_json_keys,
    )
    

def get_nested_value(data, path):
    current = data

    for key in path:
        if not isinstance(current, dict):
            return None

        if key not in current:
            return None

        current = current[key]

    return current


def is_non_empty_string(value):
    return isinstance(value, str) and value.strip() != ""


def is_valid_release_id(value):
    if (
        not is_non_empty_string(value)
        or RELEASE_ID_PATTERN.fullmatch(value) is None
    ):
        return False

    date_part = value.split("-")[1]

    try:
        datetime.strptime(date_part, "%Y%m%d")
    except ValueError:
        return False

    return True


def is_valid_artifact_hash(value):
    return is_non_empty_string(value) and ARTIFACT_HASH_PATTERN.fullmatch(value) is not None


def expected_artifact_name_for(release_id):
    return f"{release_id}.zip"

def is_positive_integer_string(value):
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and not value.startswith("0")
    )


def validate_required_top_level_fields(manifest):
    required_top_level_fields = [
        "schema_version",
        "deployment_id",
        "release",
        "environment",
        "promotion",
        "bundle",
        "git",
        "github_actions",
        "evidence_storage",
        "databricks",
        "operation",
    ]

    for field in required_top_level_fields:
        if field not in manifest:
            return False, f"Missing top-level field: {field}"

    return True, "Required top-level fields exist"

def canonical_evidence_artifact_name(environment):
    return f"{environment}-deployment-manifest.json"

def historical_evidence_artifact_name(
    environment,
    workflow_run_id,
    workflow_run_attempt,
):
    return (
        f"{environment}-deployment-manifest"
        f"-run-{workflow_run_id}"
        f"-attempt-{workflow_run_attempt}.json"
    )

def expected_evidence_artifact_name(
    artifact_role,
    environment,
    workflow_run_id,
    workflow_run_attempt,
):
    if artifact_role == CANONICAL_EVIDENCE_ROLE:
        return canonical_evidence_artifact_name(
            environment
        )

    if artifact_role == HISTORICAL_EVIDENCE_ROLE:
        return historical_evidence_artifact_name(
            environment,
            workflow_run_id,
            workflow_run_attempt,
        )

    return None


def validate_required_section_types(manifest):
    required_object_sections = [
        "release",
        "promotion",
        "bundle",
        "git",
        "github_actions",
        "evidence_storage",
        "databricks",
        "operation",
    ]

    for section in required_object_sections:
        if not isinstance(manifest.get(section), dict):
            return False, f"Field must be an object: {section}"

    return True, "Required sections have valid object types"


def validate_required_string_field(manifest, path):
    value = get_nested_value(manifest, path)
    field_name = ".".join(path)

    if not is_non_empty_string(value):
        return False, f"Field must be a non-empty string: {field_name}"

    return True, f"Field is valid: {field_name}"

def validate_promotion_identity(
    release_id,
    artifact_hash,
):
    if not is_valid_release_id(release_id):
        return (
            False,
            "release_id must match "
            "rc-YYYYMMDD-<numeric-id>",
        )

    if not is_valid_artifact_hash(artifact_hash):
        return (
            False,
            "artifact_hash must match "
            "sha256:<64 lowercase hexadecimal characters>",
        )

    return True, None

def validate_manifest_schema(manifest):
    if not isinstance(manifest, dict):
        return False, "Manifest root must be a JSON object"

    top_level_valid, top_level_message = validate_required_top_level_fields(manifest)
    if not top_level_valid:
        return False, top_level_message

    section_types_valid, section_types_message = validate_required_section_types(manifest)
    if not section_types_valid:
        return False, section_types_message

    required_string_fields = [
        ("schema_version",),
        ("deployment_id",),
        ("release", "release_id"),
        ("release", "artifact_name"),
        ("release", "artifact_hash"),
        ("environment",),
        ("bundle", "name"),
        ("bundle", "target"),
        ("git", "commit_sha"),
        ("git", "commit_message"),
        ("git", "repository"),
        ("git", "source_branch"),
        ("git", "target_branch"),
        ("git", "actor"),
        ("github_actions", "workflow_run_id"),
        ("github_actions", "workflow_run_number"),
        ("github_actions", "workflow_run_attempt"),
        ("github_actions", "workflow_name"),
        ("github_actions", "job_name"),
        ("github_actions", "event_name"),
        ("evidence_storage", "storage_type"),
        ("evidence_storage", "artifact_name"),
        ("evidence_storage", "artifact_version"),
        (
            "evidence_storage",
            "artifact_role",
        ),
        ("evidence_storage", "artifact_generated_by_run_id"),
        ("evidence_storage", "artifact_generated_by_run_number"),
        (
            "evidence_storage",
            "artifact_generated_by_run_attempt",
        ),
        ("databricks", "workspace_target"),
        ("databricks", "workspace_host"),
        ("databricks", "authenticated_principal"),
        ("databricks", "workspace_root_path"),
        ("operation", "action"),
        ("operation", "status"),
        ("operation", "started_at"),
        ("operation", "completed_at"),
    ]

    for path in required_string_fields:
        field_valid, field_message = validate_required_string_field(manifest, path)
        if not field_valid:
            return False, field_message

    operation = manifest["operation"]

    if "exit_code" not in operation:
        return False, "Missing field: operation.exit_code"

    if "failure_reason" not in operation:
        return False, "Missing field: operation.failure_reason"

    operation_status = operation["status"]
    operation_exit_code = operation["exit_code"]
    failure_reason = operation["failure_reason"]

    if operation_status not in VALID_OPERATION_STATUSES:
        return False, f"Invalid operation.status value: {operation_status}"

    if (
        not isinstance(operation_exit_code, int)
        or isinstance(operation_exit_code, bool)
    ):
        return False, "operation.exit_code must be an integer"

    if operation_status == "SUCCESS":
        if operation_exit_code != 0:
            return (
                False,
                "operation.exit_code must be 0 when "
                "operation.status is SUCCESS",
            )

        if failure_reason is not None:
            return (
                False,
                "operation.failure_reason must be null when "
                "operation.status is SUCCESS",
            )

    elif operation_status == "FAILED":
        if operation_exit_code <= 0:
            return (
                False,
                "operation.exit_code must be greater than zero when "
                "operation.status is FAILED",
            )

        if failure_reason not in VALID_FAILURE_REASONS:
            return (
                False,
                "operation.failure_reason must be an approved value "
                "when operation.status is FAILED",
            )
            
    schema_version = manifest["schema_version"]
    if schema_version != VALID_SCHEMA_VERSION:
        return False, f"Unsupported schema_version: {schema_version}"

    environment = manifest["environment"]
    if environment not in VALID_ENVIRONMENTS:
        return False, f"Invalid environment value: {environment}"
    
    promotion = manifest["promotion"]

    required_promotion_fields = (
        "from_environment",
        "to_environment",
        "required_previous_environment",
    )

    for field in required_promotion_fields:
        if field not in promotion:
            return False, f"Missing field: promotion.{field}"

    expected_promotion = expected_promotion_metadata(environment)

    for field, expected_value in expected_promotion.items():
        actual_value = promotion[field]

        if actual_value != expected_value:
            return (
                False,
                f"Invalid promotion.{field} value: "
                f"expected {expected_value}, actual {actual_value}",
            )

    bundle_target = manifest["bundle"]["target"]

    if bundle_target not in VALID_ENVIRONMENTS:
        return False, f"Invalid bundle.target value: {bundle_target}"

    if bundle_target != environment:
        return False, "bundle.target must match environment"

    workspace_target = manifest["databricks"]["workspace_target"]

    if workspace_target not in VALID_ENVIRONMENTS:
        return (
            False,
            f"Invalid databricks.workspace_target value: {workspace_target}",
        )

    if workspace_target != environment:
        return (
            False,
            "databricks.workspace_target must match environment",
        )

    workspace_host = manifest["databricks"]["workspace_host"]
    parsed_workspace_host = urlparse(workspace_host)

    try:
        workspace_port = parsed_workspace_host.port
    except ValueError:
        return (
            False,
            "databricks.workspace_host must contain "
            "a valid port",
        )

    if (
        parsed_workspace_host.scheme != "https"
        or not parsed_workspace_host.hostname
        or parsed_workspace_host.username is not None
        or parsed_workspace_host.password is not None
        or workspace_port is not None
        or parsed_workspace_host.query
        or parsed_workspace_host.fragment
        or parsed_workspace_host.path not in {"", "/"}
    ):
        return (
            False,
            "databricks.workspace_host must be a valid "
            "HTTPS workspace base URL",
        )

    operation_action = manifest["operation"]["action"]
    if operation_action != EXPECTED_OPERATION_ACTION:
        return False, f"Invalid operation.action value: {operation_action}"

    release_id = manifest["release"]["release_id"]
    if not is_valid_release_id(release_id):
        return False, f"Invalid release.release_id format: {release_id}"

    artifact_hash = manifest["release"]["artifact_hash"]
    if not is_valid_artifact_hash(artifact_hash):
        return False, f"Invalid release.artifact_hash format: {artifact_hash}"

    artifact_name = manifest["release"]["artifact_name"]
    expected_artifact_name = expected_artifact_name_for(release_id)
    if artifact_name != expected_artifact_name:
        return False, f"Invalid release.artifact_name value: {artifact_name}"

    evidence_storage = manifest[
        "evidence_storage"
    ]

    evidence_storage_type = evidence_storage[
        "storage_type"
    ]

    artifact_role = evidence_storage[
        "artifact_role"
    ]

    if artifact_role not in VALID_EVIDENCE_ROLES:
        return (
            False,
            "Invalid evidence_storage.artifact_role value: "
            f"{artifact_role}",
        )

    if (
        evidence_storage_type
        != EXPECTED_EVIDENCE_STORAGE_TYPE
    ):
        return (
            False,
            "Invalid evidence_storage.storage_type value: "
            f"{evidence_storage_type}",
        )

    if (
        artifact_role == CANONICAL_EVIDENCE_ROLE
        and operation_status != SUCCESS_STATUS
    ):
        return (
            False,
            "Canonical deployment evidence may only "
            "represent a successful deployment",
        )

    

    workflow_run_id = manifest[
        "github_actions"
    ]["workflow_run_id"]

    workflow_run_attempt = manifest[
        "github_actions"
    ]["workflow_run_attempt"]

    expected_artifact_name = (
        expected_evidence_artifact_name(
            artifact_role,
            environment,
            workflow_run_id,
            workflow_run_attempt,
        )
    )

    actual_artifact_name = evidence_storage[
        "artifact_name"
    ]

    if actual_artifact_name != expected_artifact_name:
        return (
            False,
            "Invalid evidence_storage.artifact_name value: "
            f"expected {expected_artifact_name}, "
            f"actual {actual_artifact_name}",
        )

    evidence_artifact_version = evidence_storage[
        "artifact_version"
    ]

    if evidence_artifact_version != EXPECTED_EVIDENCE_ARTIFACT_VERSION:
        return (
            False,
            "Invalid evidence_storage.artifact_version value: "
            f"{evidence_artifact_version}",
        )

    if "artifact_retention_days" not in evidence_storage:
        return (
            False,
            "Missing field: evidence_storage.artifact_retention_days",
        )

    if evidence_storage["artifact_retention_days"] is not None:
        return (
            False,
            "evidence_storage.artifact_retention_days must be null "
            "for GitHub Release assets",
        )
    
    github_actions = manifest["github_actions"]

    github_run_fields = (
        "workflow_run_id",
        "workflow_run_number",
        "workflow_run_attempt",
    )

    for field in github_run_fields:
        value = github_actions[field]

        if not is_positive_integer_string(value):
            return (
                False,
                f"github_actions.{field} must be a "
                "positive integer string",
            )

    deployment_id = manifest["deployment_id"]
    workflow_run_id = github_actions["workflow_run_id"]
    workflow_run_attempt = github_actions["workflow_run_attempt"]

    expected_deployment_id = (
        f"github-run-{workflow_run_id}"
        f"-attempt-{workflow_run_attempt}"
        f"-{environment}"
    )

    if deployment_id != expected_deployment_id:
        return (
            False,
            "deployment_id does not match GitHub run metadata "
            f"and environment: expected {expected_deployment_id}, "
            f"actual {deployment_id}",
        )

    evidence_run_fields = (
        "artifact_generated_by_run_id",
        "artifact_generated_by_run_number",
        "artifact_generated_by_run_attempt",
    )

    for field in evidence_run_fields:
        value = evidence_storage[field]

        if not is_positive_integer_string(value):
            return (
                False,
                f"evidence_storage.{field} must be a "
                "positive integer string",
            )

    workflow_run_id = github_actions["workflow_run_id"]
    evidence_run_id = evidence_storage[
        "artifact_generated_by_run_id"
    ]

    if evidence_run_id != workflow_run_id:
        return (
            False,
            "Evidence generating run ID does not match "
            "github_actions.workflow_run_id",
        )

    workflow_run_number = github_actions["workflow_run_number"]
    evidence_run_number = evidence_storage[
        "artifact_generated_by_run_number"
    ]

    if evidence_run_number != workflow_run_number:
        return (
            False,
            "Evidence generating run number does not match "
            "github_actions.workflow_run_number",
        )

    workflow_run_attempt = github_actions["workflow_run_attempt"]
    evidence_run_attempt = evidence_storage[
        "artifact_generated_by_run_attempt"
    ]

    if evidence_run_attempt != workflow_run_attempt:
        return (
            False,
            "Evidence generating run attempt does not match "
            "github_actions.workflow_run_attempt",
        )

    started_at = operation["started_at"]
    completed_at = operation["completed_at"]

    started_at_value = parse_utc_timestamp(started_at)
    completed_at_value = parse_utc_timestamp(completed_at)

    if started_at_value is None:
        return False, "operation.started_at must be a valid UTC timestamp"

    if completed_at_value is None:
        return False, "operation.completed_at must be a valid UTC timestamp"

    if completed_at_value < started_at_value:
        return (
            False,
            "operation.completed_at must not be earlier than "
            "operation.started_at",
        )

    return True, "Manifest schema is valid"


def validate_promotion(target_environment, release_id, artifact_hash, previous_manifest_path):
    checks = []
    previous_environment = previous_environment_for(target_environment)

    if (
        not isinstance(target_environment, str)
        or target_environment not in VALID_ENVIRONMENTS
    ):
        return build_result(
            decision=DECISION_INVALID_PROMOTION_SEQUENCE,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=None,
            previous_manifest_path=previous_manifest_path,
            message="Invalid target environment.",
            checks=[
                build_check(
                    "target_environment_is_valid",
                    "FAIL",
                    "dev, uat, or prod",
                    target_environment,
                )
            ],
        )

    identity_valid, identity_message = (
        validate_promotion_identity(
            release_id,
            artifact_hash,
        )
    )

    if not identity_valid:
        return build_result(
            decision=DECISION_INVALID_PROMOTION_SEQUENCE,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message=identity_message,
            checks=[
                build_check(
                    "promotion_identity_is_valid",
                    "FAIL",
                    (
                        "valid release ID and "
                        "artifact hash"
                    ),
                    identity_message,
                )
            ],
        )

    if target_environment == "dev":
        return build_result(
            decision=DECISION_PROMOTION_VALID,
            valid=True,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=None,
            previous_manifest_path=None,
            message="DEV promotion is valid. No previous deployment manifest is required.",
            checks=[
                build_check(
                    "dev_requires_no_previous_manifest",
                    "PASS",
                    "no previous manifest required",
                    "no previous manifest required",
                )
            ],
        )

    if previous_manifest_path is None:
        return build_result(
            decision=DECISION_PREVIOUS_MANIFEST_NOT_FOUND,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=None,
            message=(
                "Previous deployment manifest path "
                "was not provided."
            ),
            checks=[
                build_check(
                    "previous_manifest_path_is_provided",
                    "FAIL",
                    "previous manifest path",
                    None,
                )
            ],
        )

    previous_manifest_path = Path(previous_manifest_path)

    if not previous_manifest_path.is_file():
        checks.append(
            build_check(
                "previous_manifest_is_regular_file",
                "FAIL",
                "manifest path is a regular file",
                "manifest file not found or not a file",
            )
        )

        return build_result(
            decision=DECISION_PREVIOUS_MANIFEST_NOT_FOUND,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment manifest was not found.",
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_manifest_is_regular_file",
            "PASS",
            "manifest path is a regular file",
            "manifest path is a regular file",
        )
    )

    try:
        manifest = load_manifest(
            previous_manifest_path
        )
    except Exception as error:
        checks.append(
            build_check(
                "previous_manifest_is_loadable",
                "FAIL",
                EXPECTED_LOADABLE_MANIFEST,
                str(error),
            )
        )

        return build_result(
            decision=DECISION_INVALID_MANIFEST_SCHEMA,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message=(
                "Previous deployment manifest "
                "could not be loaded."
            ),
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_manifest_is_loadable",
            "PASS",
            EXPECTED_LOADABLE_MANIFEST,
            EXPECTED_LOADABLE_MANIFEST,
        )
    )

    schema_valid, schema_message = validate_manifest_schema(manifest)

    if not schema_valid:
        checks.append(
            build_check(
                "previous_manifest_schema_is_valid",
                "FAIL",
                "valid deployment manifest schema",
                schema_message,
            )
        )

        return build_result(
            decision=DECISION_INVALID_MANIFEST_SCHEMA,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment manifest schema is invalid.",
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_manifest_schema_is_valid",
            "PASS",
            "valid deployment manifest schema",
            "valid deployment manifest schema",
        )
    )

    previous_manifest_environment = manifest["environment"]

    if previous_manifest_environment != previous_environment:
        checks.append(
            build_check(
                "previous_environment_matches",
                "FAIL",
                previous_environment,
                previous_manifest_environment,
            )
        )

        return build_result(
            decision=DECISION_PREVIOUS_ENVIRONMENT_MISMATCH,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment manifest environment does not match expected previous environment.",
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_environment_matches",
            "PASS",
            previous_environment,
            previous_manifest_environment,
        )
    )

    previous_artifact_role = manifest[
        "evidence_storage"
    ]["artifact_role"]

    if (
        previous_artifact_role
        != CANONICAL_EVIDENCE_ROLE
    ):
        checks.append(
            build_check(
                "previous_manifest_is_canonical",
                "FAIL",
                CANONICAL_EVIDENCE_ROLE,
                previous_artifact_role,
            )
        )

        return build_result(
            decision=(
                DECISION_PREVIOUS_MANIFEST_NOT_CANONICAL
            ),
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message=(
                "Historical deployment evidence cannot "
                "authorize promotion."
            ),
            checks=checks,
        )
    checks.append(
        build_check(
            "previous_manifest_is_canonical",
            "PASS",
            CANONICAL_EVIDENCE_ROLE,
            previous_artifact_role,
        )
    )

    previous_operation_status = manifest[
        "operation"
    ]["status"]

    if previous_operation_status != SUCCESS_STATUS:
        checks.append(
            build_check(
                "previous_deployment_status_is_success",
                "FAIL",
                SUCCESS_STATUS,
                previous_operation_status,
            )
        )

        return build_result(
            decision=DECISION_INVALID_MANIFEST_SCHEMA,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message=(
                "Canonical deployment evidence must represent "
                "a successful deployment."
            ),
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_deployment_status_is_success",
            "PASS",
            SUCCESS_STATUS,
            previous_operation_status,
        )
    )
    
    previous_release_id = manifest["release"]["release_id"]

    if previous_release_id != release_id:
        checks.append(
            build_check(
                "release_id_matches",
                "FAIL",
                release_id,
                previous_release_id,
            )
        )

        return build_result(
            decision=DECISION_RELEASE_ID_MISMATCH,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment release ID does not match requested release ID.",
            checks=checks,
        )

    checks.append(
        build_check(
            "release_id_matches",
            "PASS",
            release_id,
            previous_release_id,
        )
    )

    previous_artifact_hash = manifest["release"]["artifact_hash"]

    if previous_artifact_hash != artifact_hash:
        checks.append(
            build_check(
                "artifact_hash_matches",
                "FAIL",
                artifact_hash,
                previous_artifact_hash,
            )
        )

        return build_result(
            decision=DECISION_ARTIFACT_HASH_MISMATCH,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment artifact hash does not match requested artifact hash.",
            checks=checks,
        )

    checks.append(
        build_check(
            "artifact_hash_matches",
            "PASS",
            artifact_hash,
            previous_artifact_hash,
        )
    )

    previous_workspace_target = manifest["databricks"]["workspace_target"]

    if previous_workspace_target != previous_environment:
        checks.append(
            build_check(
                "workspace_target_matches",
                "FAIL",
                previous_environment,
                previous_workspace_target,
            )
        )

        return build_result(
            decision=DECISION_WORKSPACE_TARGET_MISMATCH,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment workspace target does not match expected environment.",
            checks=checks,
        )

    checks.append(
        build_check(
            "workspace_target_matches",
            "PASS",
            previous_environment,
            previous_workspace_target,
        )
    )

    previous_bundle_target = manifest["bundle"]["target"]

    if previous_bundle_target != previous_environment:
        checks.append(
            build_check(
                "bundle_target_matches",
                "FAIL",
                previous_environment,
                previous_bundle_target,
            )
        )

        return build_result(
            decision=DECISION_BUNDLE_TARGET_MISMATCH,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment bundle target does not match expected environment.",
            checks=checks,
        )

    checks.append(
        build_check(
            "bundle_target_matches",
            "PASS",
            previous_environment,
            previous_bundle_target,
        )
    )

    return build_result(
        decision=DECISION_PROMOTION_VALID,
        valid=True,
        target_environment=target_environment,
        release_id=release_id,
        artifact_hash=artifact_hash,
        previous_environment=previous_environment,
        previous_manifest_path=previous_manifest_path,
        message="Promotion validation passed.",
        checks=checks,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate Databricks release promotion prerequisites."
    )

    parser.add_argument(
        "--target-environment",
        required=True,
        help="Target environment for the requested deployment: dev, uat, or prod.",
    )

    parser.add_argument(
        "--release-id",
        required=True,
        help="Immutable release ID being promoted.",
    )

    parser.add_argument(
        "--artifact-hash",
        required=True,
        help="Hash of the immutable release artifact being promoted.",
    )

    parser.add_argument(
        "--previous-manifest-path",
        required=False,
        help="Path to the previous environment deployment manifest.",
    )

    parser.add_argument(
        "--output-path",
        required=False,
        help="Path where promotion validation result JSON should be written.",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    target_environment = args.target_environment.lower()

    output_path = args.output_path or default_output_path(target_environment)

    input_checks = []

    if not is_valid_release_id(args.release_id):
        input_checks.append(
            build_check(
                "release_id_is_valid",
                "FAIL",
                "rc-YYYYMMDD-<numeric-id>",
                args.release_id,
            )
        )

    if not is_valid_artifact_hash(args.artifact_hash):
        input_checks.append(
            build_check(
                "artifact_hash_is_valid",
                "FAIL",
                "sha256:<64 hex characters>",
                args.artifact_hash,
            )
        )

    if input_checks:
        result = build_result(
            decision=DECISION_INVALID_PROMOTION_SEQUENCE,
            valid=False,
            target_environment=target_environment,
            release_id=args.release_id,
            artifact_hash=args.artifact_hash,
            previous_environment=previous_environment_for(target_environment),
            previous_manifest_path=args.previous_manifest_path,
            message="Release ID and artifact hash must match the required formats.",
            checks=input_checks,
        )

        write_validation_result_or_exit(
            output_path,
            result,
        )
        print(result["decision"])
        return 1

    previous_manifest_path = (
        args.previous_manifest_path
        or default_previous_manifest_path(target_environment)
    )

    result = validate_promotion(
        target_environment=target_environment,
        release_id=args.release_id,
        artifact_hash=args.artifact_hash,
        previous_manifest_path=previous_manifest_path,
    )

    write_validation_result_or_exit(
        output_path,
        result,
    )
    print(result["decision"])

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
