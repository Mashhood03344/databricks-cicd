#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


VALID_ENVIRONMENTS = {"dev", "uat", "prod"}
VALID_SCHEMA_VERSION = "1.0"
VALID_OPERATION_STATUSES = {"SUCCESS", "FAILED"}

DECISION_PROMOTION_VALID = "PROMOTION_VALID"
DECISION_PREVIOUS_MANIFEST_NOT_FOUND = "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_FOUND"
DECISION_PREVIOUS_DEPLOYMENT_NOT_SUCCESSFUL = "PREVIOUS_DEPLOYMENT_NOT_SUCCESSFUL"
DECISION_RELEASE_ID_MISMATCH = "RELEASE_ID_MISMATCH"
DECISION_ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
DECISION_INVALID_MANIFEST_SCHEMA = "INVALID_MANIFEST_SCHEMA"
DECISION_INVALID_PROMOTION_SEQUENCE = "INVALID_PROMOTION_SEQUENCE"
DECISION_WORKSPACE_TARGET_MISMATCH = "WORKSPACE_TARGET_MISMATCH"
DECISION_BUNDLE_TARGET_MISMATCH = "BUNDLE_TARGET_MISMATCH"
DECISION_PREVIOUS_ENVIRONMENT_MISMATCH = "PREVIOUS_ENVIRONMENT_MISMATCH"

SUCCESS_STATUS = "SUCCESS"


def utc_now_iso():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def previous_environment_for(target_environment):
    if target_environment == "dev":
        return None
    if target_environment == "uat":
        return "dev"
    if target_environment == "prod":
        return "uat"
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


def write_json_atomic(output_path, data):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")

    temp_path.replace(output_path)


def load_manifest(path):
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


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
        "databricks",
        "operation",
    ]

    for field in required_top_level_fields:
        if field not in manifest:
            return False, f"Missing top-level field: {field}"

    return True, "Required top-level fields exist"


def validate_required_section_types(manifest):
    required_object_sections = [
        "release",
        "promotion",
        "bundle",
        "git",
        "github_actions",
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
        ("bundle", "target"),
        ("git", "commit_sha"),
        ("databricks", "workspace_target"),
        ("operation", "status"),
    ]

    for path in required_string_fields:
        field_valid, field_message = validate_required_string_field(manifest, path)
        if not field_valid:
            return False, field_message

    schema_version = manifest["schema_version"]
    if schema_version != VALID_SCHEMA_VERSION:
        return False, f"Unsupported schema_version: {schema_version}"

    environment = manifest["environment"]
    if environment not in VALID_ENVIRONMENTS:
        return False, f"Invalid environment value: {environment}"

    bundle_target = manifest["bundle"]["target"]
    if bundle_target not in VALID_ENVIRONMENTS:
        return False, f"Invalid bundle.target value: {bundle_target}"

    workspace_target = manifest["databricks"]["workspace_target"]
    if workspace_target not in VALID_ENVIRONMENTS:
        return False, f"Invalid databricks.workspace_target value: {workspace_target}"

    operation_status = manifest["operation"]["status"]
    if operation_status not in VALID_OPERATION_STATUSES:
        return False, f"Invalid operation.status value: {operation_status}"

    return True, "Manifest schema is valid"


def validate_promotion(target_environment, release_id, artifact_hash, previous_manifest_path):
    checks = []
    previous_environment = previous_environment_for(target_environment)

    if target_environment not in VALID_ENVIRONMENTS:
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

    previous_manifest_path = Path(previous_manifest_path)

    if not previous_manifest_path.exists():
        checks.append(
            build_check(
                "previous_manifest_exists",
                "FAIL",
                "manifest file exists",
                "manifest file not found",
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
            "previous_manifest_exists",
            "PASS",
            "manifest file exists",
            "manifest file found",
        )
    )

    try:
        manifest = load_manifest(previous_manifest_path)
    except Exception as error:
        checks.append(
            build_check(
                "previous_manifest_json_is_readable",
                "FAIL",
                "valid JSON",
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
            message="Previous deployment manifest could not be parsed.",
            checks=checks,
        )

    checks.append(
        build_check(
            "previous_manifest_json_is_readable",
            "PASS",
            "valid JSON",
            "valid JSON",
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

    previous_operation_status = manifest["operation"]["status"]

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
            decision=DECISION_PREVIOUS_DEPLOYMENT_NOT_SUCCESSFUL,
            valid=False,
            target_environment=target_environment,
            release_id=release_id,
            artifact_hash=artifact_hash,
            previous_environment=previous_environment,
            previous_manifest_path=previous_manifest_path,
            message="Previous deployment was not successful.",
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

    if not is_non_empty_string(args.release_id):
        input_checks.append(
            build_check(
                "release_id_is_valid",
                "FAIL",
                "non-empty string",
                args.release_id,
            )
        )

    if not is_non_empty_string(args.artifact_hash):
        input_checks.append(
            build_check(
                "artifact_hash_is_valid",
                "FAIL",
                "non-empty string",
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
            message="Release ID and artifact hash must be non-empty strings.",
            checks=input_checks,
        )

        write_json_atomic(output_path, result)
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

    write_json_atomic(output_path, result)
    print(result["decision"])

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
