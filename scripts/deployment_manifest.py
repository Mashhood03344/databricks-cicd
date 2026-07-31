#!/usr/bin/env python3

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "1.0"

EVIDENCE_STORAGE_TYPE = "github_release_asset"
EVIDENCE_ARTIFACT_VERSION = "1.0"
EVIDENCE_RETENTION_DAYS = None

VALID_ENVIRONMENTS = {"dev", "uat", "prod"}

VALID_OPERATION_STATUSES = (
    "SUCCESS",
    "FAILED",
)

VALID_FAILURE_REASONS = (
    "DEPLOY_COMMAND_FAILED",
    "DEPLOY_TIMEOUT",
    "DEPLOY_CANCELLED",
    "UNKNOWN_DEPLOYMENT_FAILURE",
)

VALID_EVIDENCE_ROLES = (
    "historical",
    "canonical",
)

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

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def parse_utc_timestamp(
    field_name: str,
    value: str,
) -> datetime:
    if (
        not isinstance(value, str)
        or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be a valid UTC timestamp "
            "in YYYY-MM-DDTHH:MM:SSZ format"
        )

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid UTC timestamp "
            "in YYYY-MM-DDTHH:MM:SSZ format"
        ) from exc


def required_previous_environment(environment: str):
    if environment == "dev":
        return None
    if environment == "uat":
        return "dev"
    if environment == "prod":
        return "uat"
    raise ValueError(f"Unsupported environment: {environment}")


def promotion_from_environment(environment: str):
    return required_previous_environment(environment)


def expected_deployment_id(
    workflow_run_id: str,
    workflow_run_attempt: str,
    environment: str,
) -> str:
    return (
        f"github-run-{workflow_run_id}"
        f"-attempt-{workflow_run_attempt}"
        f"-{environment}"
    )

def validate_deployment_id(
    deployment_id: str,
    github_run_id: str,
    github_run_attempt: str,
    environment: str,
) -> None:
    expected_value = expected_deployment_id(
        github_run_id,
        github_run_attempt,
        environment,
    )

    if deployment_id != expected_value:
        raise ValueError(
            "deployment_id must match GitHub run metadata "
            f"and environment: expected {expected_value}"
        )


def validate_environment_targets(
    environment: str,
    bundle_target: str,
    workspace_target: str,
) -> None:
    if bundle_target != environment:
        raise ValueError(
            "bundle_target must match environment: "
            f"expected {environment}, actual {bundle_target}"
        )

    if workspace_target != environment:
        raise ValueError(
            "workspace_target must match environment: "
            f"expected {environment}, actual {workspace_target}"
        )

def validate_release_id(release_id: str) -> None:
    if not isinstance(release_id, str):
        raise ValueError(
            "release_id must match rc-YYYYMMDD-<positive numeric ID>"
        )

    match = RELEASE_ID_PATTERN.fullmatch(release_id)

    if match is None:
        raise ValueError(
            "release_id must match rc-YYYYMMDD-<positive numeric ID>"
        )

    date_part = match.group(1)

    try:
        datetime.strptime(date_part, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(
            "release_id must contain a valid calendar date"
        ) from exc

def validate_artifact_hash(artifact_hash: str) -> None:
    if (
        not isinstance(artifact_hash, str)
        or ARTIFACT_HASH_PATTERN.fullmatch(artifact_hash) is None
    ):
        raise ValueError(
            "artifact_hash must match "
            "sha256:<64 lowercase hexadecimal characters>"
        )

def validate_release_identity(
    release_id: str,
    artifact_name: str,
    artifact_hash: str,
) -> None:
    validate_release_id(release_id)
    validate_artifact_hash(artifact_hash)

    expected_artifact_name = f"{release_id}.zip"

    if artifact_name != expected_artifact_name:
        raise ValueError(
            "artifact_name must match release_id: "
            f"expected {expected_artifact_name}"
        )

def validate_positive_integer_string(
    field_name: str,
    value: str,
) -> None:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or value.startswith("0")
    ):
        raise ValueError(
            f"{field_name} must be a positive integer string"
        )

def validate_operation(
    operation_status: str,
    operation_exit_code: int,
    failure_reason: str | None,
) -> None:
    if (
        not isinstance(operation_exit_code, int)
        or isinstance(operation_exit_code, bool)
    ):
        raise ValueError(
            "operation_exit_code must be an integer"
        )

    if operation_status == "SUCCESS":
        if operation_exit_code != 0:
            raise ValueError(
                "operation_exit_code must be 0 when "
                "operation_status is SUCCESS"
            )

        if failure_reason is not None:
            raise ValueError(
                "failure_reason must be null when "
                "operation_status is SUCCESS"
            )

        return

    if operation_status == "FAILED":
        if operation_exit_code <= 0:
            raise ValueError(
                "operation_exit_code must be greater than zero "
                "when operation_status is FAILED"
            )

        if failure_reason not in VALID_FAILURE_REASONS:
            raise ValueError(
                "failure_reason must be one of the approved values "
                "when operation_status is FAILED"
            )

        return

    raise ValueError(
        f"Unsupported operation status: {operation_status}"
    )

def validate_operation_timestamps(
    started_at: str,
    completed_at: str,
) -> None:
    started_at_value = parse_utc_timestamp(
        "started_at",
        started_at,
    )
    completed_at_value = parse_utc_timestamp(
        "completed_at",
        completed_at,
    )

    if completed_at_value < started_at_value:
        raise ValueError(
            "completed_at must not be earlier than started_at"
        )


def validate_evidence_role(
    evidence_role: str,
    operation_status: str,
) -> None:
    if evidence_role not in VALID_EVIDENCE_ROLES:
        raise ValueError(
            f"Unsupported evidence role: {evidence_role}"
        )

    if (
        evidence_role == "canonical"
        and operation_status != "SUCCESS"
    ):
        raise ValueError(
            "canonical deployment evidence may only be "
            "generated for a successful deployment"
        )

def evidence_artifact_name(
    evidence_role: str,
    environment: str,
    github_run_id: str,
    github_run_attempt: str,
) -> str:
    if evidence_role == "canonical":
        return canonical_evidence_artifact_name(
            environment
        )

    if evidence_role == "historical":
        return historical_evidence_artifact_name(
            environment,
            github_run_id,
            github_run_attempt,
        )

    raise ValueError(
        f"Unsupported evidence role: {evidence_role}"
    )

def canonical_evidence_artifact_name(
    environment: str,
) -> str:
    return f"{environment}-deployment-manifest.json"

def historical_evidence_artifact_name(
    environment: str,
    github_run_id: str,
    github_run_attempt: str,
) -> str:
    return (
        f"{environment}-deployment-manifest"
        f"-run-{github_run_id}"
        f"-attempt-{github_run_attempt}.json"
    )


def validate_manifest_inputs(
    args,
    completed_at: str,
) -> None:
    environment = args.environment

    if environment not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Invalid environment: {environment}"
        )

    validate_positive_integer_string(
        "github_run_id",
        args.github_run_id,
    )

    validate_positive_integer_string(
        "github_run_number",
        args.github_run_number,
    )

    validate_positive_integer_string(
        "github_run_attempt",
        args.github_run_attempt,
    )

    validate_deployment_id(
        args.deployment_id,
        args.github_run_id,
        args.github_run_attempt,
        environment,
    )

    validate_environment_targets(
        environment,
        args.bundle_target,
        args.workspace_target,
    )

    validate_release_identity(
        args.release_id,
        args.artifact_name,
        args.artifact_hash,
    )

    validate_operation(
        args.operation_status,
        args.operation_exit_code,
        args.failure_reason,
    )

    validate_operation_timestamps(
        args.started_at,
        completed_at,
    )

    validate_evidence_role(
        args.evidence_role,
        args.operation_status,
    )

def build_manifest(
    args,
    completed_at: str,
):
    environment = args.environment

    previous_env = required_previous_environment(
        environment
    )

    evidence_name = evidence_artifact_name(
        args.evidence_role,
        environment,
        args.github_run_id,
        args.github_run_attempt,
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": args.deployment_id,
        "release": {
            "release_id": args.release_id,
            "artifact_name": args.artifact_name,
            "artifact_hash": args.artifact_hash,
        },
        "environment": environment,
        "promotion": {
            "from_environment": promotion_from_environment(environment),
            "to_environment": environment,
            "required_previous_environment": previous_env,
        },
        "bundle": {
            "name": args.bundle_name,
            "target": args.bundle_target,
        },
        "git": {
            "repository": args.github_repository,
            "source_branch": args.source_branch,
            "target_branch": args.target_branch,
            "commit_sha": args.commit_sha,
            "commit_message": args.commit_message,
            "actor": args.github_actor,
        },
        "github_actions": {
            "workflow_name": args.github_workflow,
            "workflow_run_id": args.github_run_id,
            "workflow_run_number": args.github_run_number,
            "workflow_run_attempt": args.github_run_attempt,
            "job_name": args.github_job,
            "event_name": args.github_event_name,
        },
        "evidence_storage": {
            "storage_type": EVIDENCE_STORAGE_TYPE,
            "artifact_role": args.evidence_role,
            "artifact_name": evidence_name,
            "artifact_version": EVIDENCE_ARTIFACT_VERSION,
            "artifact_generated_by_run_id": args.github_run_id,
            "artifact_generated_by_run_number": args.github_run_number,
            "artifact_generated_by_run_attempt": args.github_run_attempt,
            "artifact_retention_days": EVIDENCE_RETENTION_DAYS,
        },
        "databricks": {
            "workspace_target": args.workspace_target,
            "workspace_host": args.databricks_host,
            "authenticated_principal": args.authenticated_principal,
            "workspace_root_path": args.workspace_root_path,
        },
        "operation": {
            "action": "bundle_deploy",
            "status": args.operation_status,
            "exit_code": args.operation_exit_code,
            "failure_reason": args.failure_reason,
            "started_at": args.started_at,
            "completed_at": completed_at,
        },
    }

    return manifest


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate environment-specific evidence for "
            "a Databricks bundle deployment attempt."
        )
    )

    github_run_id = env("GITHUB_RUN_ID")
    github_run_number = env("GITHUB_RUN_NUMBER")
    github_run_attempt = env("GITHUB_RUN_ATTEMPT")

    parser.add_argument("--deployment-id", required=True)

    parser.add_argument("--environment", required=True, help="Deployment environment: dev, uat, or prod")

    parser.add_argument("--release-id", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-hash", required=True)

    parser.add_argument("--bundle-name", required=True)
    parser.add_argument("--bundle-target", required=True)

    parser.add_argument("--workspace-target", required=True)
    parser.add_argument("--workspace-root-path", required=True)
    parser.add_argument("--authenticated-principal", required=True)

    parser.add_argument("--started-at", required=True)

    parser.add_argument(
        "--operation-status",
        required=True,
        choices=VALID_OPERATION_STATUSES,
    )

    parser.add_argument(
        "--operation-exit-code",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--failure-reason",
        choices=VALID_FAILURE_REASONS,
        default=None,
    )

    parser.add_argument("--source-branch", default=env("GITHUB_REF_NAME"))
    parser.add_argument("--target-branch", default="")
    parser.add_argument("--commit-sha", default=env("GITHUB_SHA"))
    parser.add_argument("--commit-message", default="")

    parser.add_argument("--github-repository", default=env("GITHUB_REPOSITORY"))
    parser.add_argument("--github-actor", default=env("GITHUB_ACTOR"))
    parser.add_argument("--github-workflow", default=env("GITHUB_WORKFLOW"))
    parser.add_argument("--github-run-id", default=github_run_id, required=not bool(github_run_id))
    parser.add_argument("--github-run-number", default=github_run_number, required=not bool(github_run_number))
    parser.add_argument(
        "--github-run-attempt",
        default=github_run_attempt,
        required=not bool(github_run_attempt),
    )
    parser.add_argument("--github-job", default=env("GITHUB_JOB"))
    parser.add_argument("--github-event-name", default=env("GITHUB_EVENT_NAME"))
    parser.add_argument(
        "--evidence-role",
        required=True,
        choices=VALID_EVIDENCE_ROLES,
    )

    parser.add_argument("--databricks-host", default=env("DATABRICKS_HOST"))

    parser.add_argument(
        "--output-directory",
        default=".",
        help=(
            "Directory where the deployment evidence artifact "
            "will be written. Defaults to the current directory."
        ),
    )

    return parser

def resolve_output_path(
    output_directory: str,
    artifact_name: str,
) -> Path:
    return (
        Path(output_directory)
        / artifact_name
    )

def write_manifest(
    manifest: dict,
    output_path: Path,
) -> None:
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
                json.dumps(manifest, indent=2) + "\n"
            )

            temp_file.flush()
            os.fsync(temp_file.fileno())

        temp_path.replace(output_path)

    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        raise
    
def main():
    parser = create_parser()
    args = parser.parse_args()
    completed_at = utc_now()

    try:
        validate_manifest_inputs(
            args,
            completed_at,
        )

        manifest = build_manifest(
            args,
            completed_at,
        )
    except ValueError as exc:
        parser.error(str(exc))

    expected_artifact_name = (
        manifest["evidence_storage"]["artifact_name"]
    )

    output_path = resolve_output_path(
        args.output_directory,
        expected_artifact_name,
    )

    try:
        write_manifest(
            manifest,
            output_path,
        )
    except OSError as exc:
        parser.exit(
            status=1,
            message=(
                "Failed to write deployment manifest "
                f"to {output_path}: {exc}\n"
            ),
        )

    print(
        f"Deployment manifest created: {output_path}"
    )

if __name__ == "__main__":
    main()