import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPT_PATH = Path(
    os.environ.get(
        "DEPLOYMENT_MANIFEST_SCRIPT",
        "scripts/deployment_manifest.py"
    )
).resolve()

from deployment_manifest import (
    build_manifest,
    validate_manifest_inputs,
)

STARTED_AT = "2026-06-12T10:00:00Z"
COMPLETED_AT = "2026-06-12T10:05:00Z"


def make_args(
    environment="dev",
    bundle_target=None,
    workspace_target=None,
    evidence_role="canonical",
    operation_status="SUCCESS",
    operation_exit_code=0,
    failure_reason=None,
):
    bundle_target = bundle_target or environment
    workspace_target = workspace_target or environment

    return Namespace(
        deployment_id = (
            f"github-run-123456789-attempt-1-{environment}"
        ),
        environment=environment,

        release_id="rc-20260624-123456789",
        artifact_name="rc-20260624-123456789.zip",
        artifact_hash=(
            "sha256:"
            "0123456789abcdef0123456789abcdef"
            "0123456789abcdef0123456789abcdef"
        ),

        bundle_name="databricks-cicd-bundle-poc",
        bundle_target=bundle_target,

        workspace_target=workspace_target,
        workspace_root_path=(
            "/Workspace/Users/sp/.bundle/"
            f"databricks-cicd-bundle-poc/{environment}"
        ),
        authenticated_principal=(
            f"sp-github-actions-dab-{environment}"
        ),

        started_at=STARTED_AT,

        source_branch="dev",
        target_branch="dev",
        commit_sha="abc123",
        commit_message="Test deployment manifest generation",

        github_repository="mashhood/databricks-cicd",
        github_actor="mashhoodhamid201",
        github_workflow="Databricks Bundle CD",
        github_run_id="123456789",
        github_run_number="42",
        github_run_attempt="1",
        github_job=f"deploy-{environment}",
        github_event_name="workflow_dispatch",

        evidence_role=evidence_role,

        databricks_host=(
            "https://dbc-example.cloud.databricks.com"
        ),

        operation_status=operation_status,
        operation_exit_code=operation_exit_code,
        failure_reason=failure_reason,
    )

def generate_manifest(args, completed_at=COMPLETED_AT):
    validate_manifest_inputs(args, completed_at)
    return build_manifest(args, completed_at)


def test_build_manifest_creates_valid_dev_manifest():
    manifest = generate_manifest(make_args("dev"))

    assert manifest["schema_version"] == "1.0"
    assert manifest["environment"] == "dev"
    assert manifest["promotion"]["from_environment"] is None
    assert manifest["promotion"]["to_environment"] == "dev"
    assert manifest["promotion"]["required_previous_environment"] is None


def test_build_manifest_creates_valid_uat_promotion_metadata():
    manifest = generate_manifest(make_args("uat", bundle_target="uat", workspace_target="uat"))

    assert manifest["environment"] == "uat"
    assert manifest["promotion"]["from_environment"] == "dev"
    assert manifest["promotion"]["to_environment"] == "uat"
    assert manifest["promotion"]["required_previous_environment"] == "dev"


def test_build_manifest_creates_valid_prod_promotion_metadata():
    manifest = generate_manifest(make_args("prod", bundle_target="prod", workspace_target="prod"))

    assert manifest["environment"] == "prod"
    assert manifest["promotion"]["from_environment"] == "uat"
    assert manifest["promotion"]["to_environment"] == "prod"
    assert manifest["promotion"]["required_previous_environment"] == "uat"

def test_build_manifest_accepts_positive_github_run_id():
    args = make_args()
    args.github_run_id = "987654321"
    args.deployment_id = (
        "github-run-987654321-attempt-1-dev"
    )

    manifest = generate_manifest(args)

    assert (
        manifest["github_actions"]["workflow_run_id"]
        == "987654321"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_id"
        ]
        == "987654321"
    )

def test_build_manifest_accepts_positive_github_run_number():
    args = make_args()
    args.github_run_number = "99"

    manifest = generate_manifest(args)

    assert (
        manifest["github_actions"]["workflow_run_number"]
        == "99"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_number"
        ]
        == "99"
    )

def test_build_manifest_uses_github_release_evidence_storage():
    manifest = generate_manifest(
        make_args(evidence_role="canonical")
    )

    assert (
        manifest["evidence_storage"]["storage_type"]
        == "github_release_asset"
    )
    assert (
        manifest["evidence_storage"]["artifact_version"]
        == "1.0"
    )
    assert (
        manifest["evidence_storage"]["artifact_retention_days"]
        is None
    )

def test_invalid_environment_raises_value_error():
    with pytest.raises(ValueError, match="Invalid environment: qa"):
        generate_manifest(make_args("qa"))

def test_completed_at_is_recorded_from_argument():
    manifest = generate_manifest(
        make_args(),
        completed_at=COMPLETED_AT,
    )

    assert (
        manifest["operation"]["completed_at"]
        == COMPLETED_AT
    )

def test_operation_action_is_bundle_deploy():
    manifest = generate_manifest(make_args())

    assert manifest["operation"]["action"] == "bundle_deploy"


def test_operation_status_is_success():
    manifest = generate_manifest(make_args())

    assert manifest["operation"]["status"] == "SUCCESS"


def test_success_operation_contains_expected_metadata():
    manifest = generate_manifest(make_args())

    assert manifest["operation"]["status"] == "SUCCESS"
    assert manifest["operation"]["exit_code"] == 0
    assert manifest["operation"]["failure_reason"] is None

def test_operation_status_required_when_missing(tmp_path):
    args = cli_args(
        output_directory=tmp_path,
    )

    index = args.index("--operation-status")
    del args[index:index + 2]

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "operation-status" in result.stderr.lower()


def test_operation_exit_code_required_when_missing(tmp_path):
    args = cli_args(
        output_directory=tmp_path,
    )

    index = args.index("--operation-exit-code")
    del args[index:index + 2]

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "operation-exit-code" in result.stderr.lower()

def test_failed_operation_contains_expected_metadata():
    args = make_args(
        evidence_role="historical",
        operation_status="FAILED",
        operation_exit_code=1,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    manifest = generate_manifest(args)

    assert manifest["operation"]["status"] == "FAILED"
    assert manifest["operation"]["exit_code"] == 1
    assert (
        manifest["operation"]["failure_reason"]
        == "DEPLOY_COMMAND_FAILED"
    )

@pytest.mark.parametrize(
    "failure_reason",
    [
        "DEPLOY_COMMAND_FAILED",
        "DEPLOY_TIMEOUT",
        "DEPLOY_CANCELLED",
        "UNKNOWN_DEPLOYMENT_FAILURE",
    ],
)

def test_failed_operation_accepts_approved_failure_reasons(
    failure_reason,
):
    args = make_args(
        evidence_role="historical",
        operation_status="FAILED",
        operation_exit_code=1,
        failure_reason=failure_reason,
    )

    manifest = generate_manifest(args)

    assert manifest["operation"]["failure_reason"] == failure_reason

def test_failed_operation_accepts_exit_code_greater_than_one():
    args = make_args(
        evidence_role="historical",
        operation_status="FAILED",
        operation_exit_code=137,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    manifest = generate_manifest(args)

    assert manifest["operation"]["exit_code"] == 137

def test_build_manifest_rejects_success_with_nonzero_exit_code():
    args = make_args()
    args.operation_status = "SUCCESS"
    args.operation_exit_code = 1

    with pytest.raises(
        ValueError,
        match=(
            "operation_exit_code must be 0 when "
            "operation_status is SUCCESS"
        ),
    ):
        generate_manifest(args)

def test_build_manifest_rejects_success_with_failure_reason():
    args = make_args()
    args.operation_status = "SUCCESS"
    args.operation_exit_code = 0
    args.failure_reason = "DEPLOY_COMMAND_FAILED"

    with pytest.raises(
        ValueError,
        match=(
            "failure_reason must be null when "
            "operation_status is SUCCESS"
        ),
    ):
        generate_manifest(args)


def test_build_manifest_rejects_failed_with_zero_exit_code():
    args = make_args()
    args.operation_status = "FAILED"
    args.operation_exit_code = 0
    args.failure_reason = "DEPLOY_COMMAND_FAILED"

    with pytest.raises(
        ValueError,
        match=(
            "operation_exit_code must be greater than zero "
            "when operation_status is FAILED"
        ),
    ):
        generate_manifest(args)

def test_build_manifest_rejects_failed_with_negative_exit_code():
    args = make_args()
    args.operation_status = "FAILED"
    args.operation_exit_code = -1
    args.failure_reason = "DEPLOY_COMMAND_FAILED"

    with pytest.raises(
        ValueError,
        match="operation_exit_code must be greater than zero",
    ):
        generate_manifest(args)

def test_build_manifest_rejects_failed_without_failure_reason():
    args = make_args()
    args.operation_status = "FAILED"
    args.operation_exit_code = 1
    args.failure_reason = None

    with pytest.raises(
        ValueError,
        match="failure_reason must be one of the approved values",
    ):
        generate_manifest(args)

def test_build_manifest_rejects_unapproved_failure_reason():
    args = make_args()
    args.operation_status = "FAILED"
    args.operation_exit_code = 1
    args.failure_reason = "DATABASE_ERROR"

    with pytest.raises(
        ValueError,
        match="failure_reason must be one of the approved values",
    ):
        generate_manifest(args)

def test_build_manifest_rejects_boolean_exit_code():
    args = make_args()
    args.operation_exit_code = True

    with pytest.raises(
        ValueError,
        match="operation_exit_code must be an integer",
    ):
        generate_manifest(args)

def test_build_manifest_rejects_unsupported_operation_status():
    args = make_args()
    args.operation_status = "CANCELLED"

    with pytest.raises(
        ValueError,
        match="Unsupported operation status: CANCELLED",
    ):
        generate_manifest(args)

@pytest.mark.parametrize(
    "operation_exit_code",
    [
        "1",
        1.5,
    ],
)

def test_build_manifest_rejects_non_integer_exit_code(
    operation_exit_code,
):
    args = make_args()
    args.operation_exit_code = operation_exit_code

    with pytest.raises(
        ValueError,
        match="operation_exit_code must be an integer",
    ):
        generate_manifest(args)

def test_canonical_evidence_uses_environment_filename():
    args = make_args(evidence_role="canonical")

    manifest = generate_manifest(args)

    assert (
        manifest["evidence_storage"]["artifact_role"]
        == "canonical"
    )
    assert (
        manifest["evidence_storage"]["artifact_name"]
        == "dev-deployment-manifest.json"
    )

def test_historical_evidence_uses_run_specific_filename():
    args = make_args(evidence_role="historical")

    manifest = generate_manifest(args)

    assert (
        manifest["evidence_storage"]["artifact_role"]
        == "historical"
    )
    assert (
        manifest["evidence_storage"]["artifact_name"]
        == (
            "dev-deployment-manifest"
            "-run-123456789-attempt-1.json"
        )
    )

def test_historical_evidence_uses_output_directory(tmp_path):
    output_directory = tmp_path / "historical-output"

    result = run_script(
        environment="dev",
        output_directory=output_directory,
        evidence_role="historical",
    )

    assert_success(result)

    expected_path = (
        output_directory
        / (
            "dev-deployment-manifest"
            "-run-123456789-attempt-1.json"
        )
    )

    assert expected_path.exists()

def test_failed_deployment_can_generate_historical_evidence():
    args = make_args(
        evidence_role="historical",
        operation_status="FAILED",
        operation_exit_code=1,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    manifest = generate_manifest(args)

    assert manifest["operation"]["status"] == "FAILED"
    assert (
        manifest["evidence_storage"]["artifact_role"]
        == "historical"
    )

def test_failed_deployment_cannot_generate_canonical_evidence():
    args = make_args(
        evidence_role="canonical",
        operation_status="FAILED",
        operation_exit_code=1,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    with pytest.raises(
        ValueError,
        match=(
            "canonical deployment evidence may only be "
            "generated for a successful deployment"
        ),
    ):
        generate_manifest(args)

def test_rejects_unsupported_evidence_role():
    args = make_args()
    args.evidence_role = "primary"

    with pytest.raises(
        ValueError,
        match="Unsupported evidence role: primary",
    ):
        generate_manifest(args)

def test_rejects_bundle_target_mismatch():
    args = make_args()
    args.bundle_target = "uat"

    with pytest.raises(
        ValueError,
        match="bundle_target must match environment",
    ):
        generate_manifest(args)

def test_rejects_workspace_target_mismatch():
    args = make_args()
    args.workspace_target = "uat"

    with pytest.raises(
        ValueError,
        match="workspace_target must match environment",
    ):
        generate_manifest(args)

@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-06-12 10:00:00",
        "2026-06-12T10:00:00+00:00",
        "2026-06-12T10:00:00.123Z",
        "not-a-timestamp",
        "",
    ],
)
def test_rejects_invalid_started_at(timestamp):
    args = make_args()
    args.started_at = timestamp

    with pytest.raises(
        ValueError,
        match="started_at must be a valid UTC timestamp",
    ):
        generate_manifest(args)

def test_rejects_completed_at_before_started_at():
    args = make_args()
    args.started_at = "2026-06-12T10:05:00Z"

    with pytest.raises(
        ValueError,
        match="completed_at must not be earlier than started_at",
    ):
        generate_manifest(
            args,
            completed_at="2026-06-12T10:00:00Z",
        )

@pytest.mark.parametrize(
    "release_id",
    [
        "rc-20260230-123",
        "rc-20261301-123",
        "rc-20260001-123",
    ],
)
def test_rejects_invalid_release_calendar_date(release_id):
    args = make_args()
    args.release_id = release_id
    args.artifact_name = f"{release_id}.zip"

    with pytest.raises(
        ValueError,
        match="release_id must contain a valid calendar date",
    ):
        generate_manifest(args)

def test_rejects_artifact_name_not_matching_release_id():
    args = make_args()
    args.artifact_name = "different-release.zip"

    with pytest.raises(
        ValueError,
        match="artifact_name must match release_id",
    ):
        generate_manifest(args)

@pytest.mark.parametrize(
    "artifact_hash",
    [
        "sha256:abc123",
        "SHA256:" + "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "g" * 64,
        "a" * 64,
    ],
)
def test_rejects_invalid_artifact_hash(artifact_hash):
    args = make_args()
    args.artifact_hash = artifact_hash

    with pytest.raises(
        ValueError,
        match="artifact_hash must match",
    ):
        generate_manifest(args)

@pytest.mark.parametrize(
    "field_name,replacement",
    [
        ("github_run_id", "987654321"),
        ("github_run_attempt", "2"),
        ("environment", "uat"),
    ],
)
def test_rejects_deployment_id_mismatch(
    field_name,
    replacement,
):
    args = make_args()
    setattr(args, field_name, replacement)

    if field_name == "environment":
        args.bundle_target = replacement
        args.workspace_target = replacement

    with pytest.raises(
        ValueError,
        match="deployment_id must match GitHub run metadata",
    ):
        generate_manifest(args)


def test_accepts_valid_deployment_id():
    args = make_args()

    manifest = generate_manifest(args)

    assert manifest["deployment_id"] == (
        "github-run-123456789-attempt-1-dev"
    )

def cli_args(
    environment="dev",
    output_directory=None,
    evidence_role="canonical",
):
    deployment_id = (
        f"github-run-123456789-attempt-1-{environment}"
    )

    args = [
        sys.executable,
        str(SCRIPT_PATH),

        "--environment", environment,
        "--bundle-name", "databricks-cicd-bundle-poc",
        "--bundle-target", environment,

        "--workspace-target", environment,
        "--workspace-root-path",
        (
            "/Workspace/Users/sp/.bundle/"
            f"databricks-cicd-bundle-poc/{environment}"
        ),
        "--authenticated-principal",
        f"sp-github-actions-dab-{environment}",

        "--started-at", STARTED_AT,

        "--github-run-id", "123456789",
        "--github-run-number", "42",
        "--github-run-attempt", "1",

        "--deployment-id", deployment_id,

        "--release-id", "rc-20260624-123456789",
        "--artifact-name", "rc-20260624-123456789.zip",
        "--artifact-hash",
        (
            "sha256:"
            "0123456789abcdef0123456789abcdef"
            "0123456789abcdef0123456789abcdef"
        ),

        "--operation-status", "SUCCESS",
        "--operation-exit-code", "0",

        "--evidence-role", evidence_role,
    ]

    if output_directory is not None:
        args.extend(
            ["--output-directory", str(output_directory)]
        )

    return args


def run_script(
    environment="dev",
    output_directory=None,
    evidence_role="canonical",
    cwd=None,
    extra_args=None,
    env=None,
):
    args = cli_args(
        environment=environment,
        output_directory=output_directory,
        evidence_role=evidence_role,
    )

    if extra_args:
        args.extend(extra_args)

    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def assert_success(result):
    assert result.returncode == 0, result.stderr + result.stdout


def test_cli_running_script_creates_deployment_manifest_json(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = tmp_path / "dev-deployment-manifest.json"
    assert output_path.exists()


def test_cli_output_json_is_valid(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = tmp_path / "dev-deployment-manifest.json"
    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["environment"] == "dev"

def test_cli_nested_output_directory_is_created_automatically(tmp_path):
    output_directory = tmp_path / "artifacts" / "dev"

    result = run_script(
        output_directory=output_directory,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = (
        output_directory
        / "dev-deployment-manifest.json"
    )
    assert output_path.exists()

def test_cli_output_includes_evidence_storage(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = (
        tmp_path
        / "dev-deployment-manifest.json"
    )

    data = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert (
        data["evidence_storage"]["storage_type"]
        == "github_release_asset"
    )
    assert (
        data["evidence_storage"]["artifact_role"]
        == "canonical"
    )
    assert (
        data["evidence_storage"]["artifact_name"]
        == "dev-deployment-manifest.json"
    )
    assert (
        data["evidence_storage"]["artifact_version"]
        == "1.0"
    )
    assert (
        data["evidence_storage"][
            "artifact_generated_by_run_id"
        ]
        == "123456789"
    )
    assert (
        data["evidence_storage"][
            "artifact_generated_by_run_number"
        ]
        == "42"
    )
    assert (
        data["evidence_storage"][
            "artifact_generated_by_run_attempt"
        ]
        == "1"
    )
    assert (
        data["evidence_storage"]["artifact_retention_days"]
        is None
    )
    assert (
        data["github_actions"]["workflow_run_attempt"]
        == "1"
    )

def test_cli_rejects_unapproved_failure_reason(tmp_path):
    output_path = (
        tmp_path
        / "dev-deployment-manifest.json"
    )

    args = cli_args(
        output_directory=tmp_path,
        evidence_role="historical",
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )

    args.extend(
        [
            "--failure-reason",
            "DATABASE_ERROR",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr.lower()
    assert not output_path.exists()

def test_default_output_path_for_dev(tmp_path):
    result = run_script(environment="dev", cwd=tmp_path)

    assert_success(result)
    assert (tmp_path / "dev-deployment-manifest.json").exists()
    assert not (tmp_path / "deployment-manifest.json").exists()


def test_default_output_path_for_uat(tmp_path):
    result = run_script(environment="uat", cwd=tmp_path)

    assert_success(result)
    assert (tmp_path / "uat-deployment-manifest.json").exists()
    assert not (tmp_path / "deployment-manifest.json").exists()


def test_default_output_path_for_prod(tmp_path):
    result = run_script(environment="prod", cwd=tmp_path)

    assert_success(result)
    assert (tmp_path / "prod-deployment-manifest.json").exists()
    assert not (tmp_path / "deployment-manifest.json").exists()

def test_output_directory_override_is_used(tmp_path):
    output_directory = tmp_path / "custom-output"

    result = run_script(
        environment="dev",
        output_directory=output_directory,
        evidence_role="canonical",
    )

    assert_success(result)

    expected_path = (
        output_directory
        / "dev-deployment-manifest.json"
    )

    assert expected_path.exists()


def test_github_run_id_required_when_env_var_absent(tmp_path):
    env = os.environ.copy()
    env.pop("GITHUB_RUN_ID", None)

    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )
    run_id_index = args.index("--github-run-id")
    del args[run_id_index:run_id_index + 2]

    result = subprocess.run(args, env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "github-run-id" in result.stderr.lower() or "github_run_id" in result.stderr.lower()


def test_github_run_number_required_when_env_var_absent(tmp_path):
    env = os.environ.copy()
    env.pop("GITHUB_RUN_NUMBER", None)

    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )
    run_number_index = args.index("--github-run-number")
    del args[run_number_index:run_number_index + 2]

    result = subprocess.run(args, env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "github-run-number" in result.stderr.lower() or "github_run_number" in result.stderr.lower()

def test_github_run_attempt_recorded_in_both_evidence_sections():
    manifest = generate_manifest(make_args())

    assert (
        manifest["github_actions"]["workflow_run_attempt"]
        == "1"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_attempt"
        ]
        == "1"
    )

def test_github_run_attempt_required_when_env_var_absent(tmp_path):
    env = os.environ.copy()
    env.pop("GITHUB_RUN_ATTEMPT", None)

    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )

    run_attempt_index = args.index("--github-run-attempt")
    del args[run_attempt_index:run_attempt_index + 2]

    result = subprocess.run(
        args,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "github-run-attempt" in result.stderr.lower()
        or "github_run_attempt" in result.stderr.lower()
    )

def test_github_run_attempt_uses_environment_variable(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    env = os.environ.copy()
    env["GITHUB_RUN_ATTEMPT"] = "3"

    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )
    
    index = args.index("--github-run-attempt")
    del args[index:index + 2]

    replace_cli_argument(
        args,
        "--deployment-id",
        "github-run-123456789-attempt-3-dev",
    )

    result = subprocess.run(
        args,
        env=env,
        capture_output=True,
        text=True,
    )

    assert_success(result)

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["github_actions"]["workflow_run_attempt"] == "3"
    assert (
        data["evidence_storage"]["artifact_generated_by_run_attempt"]
        == "3"
    )




@pytest.mark.parametrize(
    "argument_name,field_name",
    [
        ("--github-run-id", "github_run_id"),
        ("--github-run-number", "github_run_number"),
        ("--github-run-attempt", "github_run_attempt"),
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        "0",
        "-1",
        "abc",
        "1.5",
    ],
)
def test_cli_rejects_invalid_github_run_metadata(
    tmp_path,
    argument_name,
    field_name,
    invalid_value,
):
    output_path = (
        tmp_path
        / "dev-deployment-manifest.json"
    )

    args = cli_args(
        output_directory=tmp_path,
    )
    replace_cli_argument(
        args,
        argument_name,
        invalid_value,
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        f"{field_name} must be a positive integer string"
        in result.stderr.lower()
    )
    assert not output_path.exists()


def test_build_manifest_accepts_positive_github_run_attempt():
    args = make_args()
    args.github_run_attempt = "2"
    args.deployment_id = (
        "github-run-123456789-attempt-2-dev"
    )

    manifest = generate_manifest(args)

    assert (
        manifest["github_actions"]["workflow_run_attempt"]
        == "2"
    )

@pytest.mark.parametrize(
    "field_name",
    [
        "github_run_id",
        "github_run_number",
        "github_run_attempt",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        "",
        "0",
        "-1",
        "1.5",
        "abc",
        None,
        1,
        True,
    ],
)
def test_build_manifest_rejects_invalid_github_run_metadata(
    field_name,
    invalid_value,
):
    args = make_args()
    setattr(args, field_name, invalid_value)

    with pytest.raises(
        ValueError,
        match=(
            rf"{field_name} must be a positive integer string"
        ),
    ):
        generate_manifest(args)



def test_build_manifest_includes_evidence_storage():
    manifest = generate_manifest(make_args("dev"))

    assert (
    manifest["evidence_storage"]["storage_type"]
    == "github_release_asset"
    )
    assert (
        manifest["evidence_storage"]["artifact_role"]
        == "canonical"
    )
    assert (
        manifest["evidence_storage"]["artifact_name"]
        == "dev-deployment-manifest.json"
    )
    assert (
        manifest["evidence_storage"]["artifact_version"]
        == "1.0"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_id"
        ]
        == "123456789"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_number"
        ]
        == "42"
    )
    assert (
        manifest["evidence_storage"][
            "artifact_generated_by_run_attempt"
        ]
        == "1"
    )
    assert (
        manifest["evidence_storage"]["artifact_retention_days"]
        is None
    )

@pytest.mark.parametrize("environment", ["dev", "uat", "prod"])
def test_accepts_matching_environment_targets(environment):
    args = make_args(environment=environment)

    manifest = generate_manifest(args)

    assert manifest["bundle"]["target"] == environment
    assert (
        manifest["databricks"]["workspace_target"]
        == environment
    )

def test_accepts_equal_started_and_completed_timestamps():
    args = make_args()
    args.started_at = COMPLETED_AT

    manifest = generate_manifest(
        args,
        completed_at=COMPLETED_AT,
    )

    assert (
        manifest["operation"]["started_at"]
        == manifest["operation"]["completed_at"]
    )

def test_github_release_asset_accepts_null_retention():
    args = make_args("dev")
    args.evidence_storage_type = "github_release_asset"
    args.evidence_artifact_name = "dev-deployment-manifest.json"
    args.evidence_artifact_retention_days = None

    manifest = generate_manifest(args)

    assert manifest["evidence_storage"]["storage_type"] == "github_release_asset"
    assert (
        manifest["evidence_storage"]["artifact_name"]
        == "dev-deployment-manifest.json"
    )
    assert manifest["evidence_storage"]["artifact_retention_days"] is None

def test_build_manifest_contains_release_section():
    manifest = generate_manifest(make_args())

    assert "release" in manifest


def test_release_id_copied_exactly_from_args():
    manifest = generate_manifest(make_args())

    assert (
        manifest["release"]["release_id"]
        == "rc-20260624-123456789"
    )


def test_artifact_name_copied_exactly_from_args():
    manifest = generate_manifest(make_args())

    assert (
        manifest["release"]["artifact_name"]
        == "rc-20260624-123456789.zip"
    )


def test_artifact_hash_copied_exactly_from_args():
    manifest = generate_manifest(make_args())

    assert manifest["release"]["artifact_hash"] == (
        "sha256:"
        "0123456789abcdef0123456789abcdef"
        "0123456789abcdef0123456789abcdef"
    )

def test_deployment_id_required_when_missing(tmp_path):
    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )

    deployment_id_index = args.index("--deployment-id")
    del args[deployment_id_index:deployment_id_index + 2]

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "deployment-id" in result.stderr.lower()


def test_release_id_required_when_missing(tmp_path):
    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )

    release_id_index = args.index("--release-id")
    del args[release_id_index:release_id_index + 2]

    result = subprocess.run(args, capture_output=True, text=True)

    assert result.returncode != 0
    assert "release-id" in result.stderr.lower()


def test_artifact_name_required_when_missing(tmp_path):
    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )

    artifact_name_index = args.index("--artifact-name")
    del args[artifact_name_index:artifact_name_index + 2]

    result = subprocess.run(args, capture_output=True, text=True)

    assert result.returncode != 0
    assert "artifact-name" in result.stderr.lower()


def test_artifact_hash_required_when_missing(tmp_path):
    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
    )

    artifact_hash_index = args.index("--artifact-hash")
    del args[artifact_hash_index:artifact_hash_index + 2]

    result = subprocess.run(args, capture_output=True, text=True)

    assert result.returncode != 0
    assert "artifact-hash" in result.stderr.lower()
    

def test_cli_output_contains_release_metadata(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = run_script(
        output_directory=tmp_path,
    )

    assert_success(result)

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["deployment_id"] == "github-run-123456789-attempt-1-dev"
    assert data["release"]["release_id"] == "rc-20260624-123456789"
    assert data["release"]["artifact_name"] == "rc-20260624-123456789.zip"
    assert data["release"]["artifact_hash"] == (
        "sha256:"
        "0123456789abcdef0123456789abcdef"
        "0123456789abcdef0123456789abcdef"
    )


def test_cli_missing_required_args_fails_with_non_zero_exit_code(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--environment", "dev",
            "--output-directory", str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "required" in result.stderr.lower()


def test_cli_invalid_environment_fails_with_non_zero_exit_code(tmp_path):
    output_path = tmp_path / "qa-deployment-manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--environment", "qa",
            "--bundle-name", "databricks-cicd-bundle-poc",
            "--bundle-target", "qa",
            "--workspace-target", "qa",
            "--workspace-root-path", "/Workspace/test",
            "--authenticated-principal", "sp-test",
            "--started-at", "2026-06-12T10:00:00Z",
            "--github-run-id", "123456789",
            "--github-run-number", "42",
            "--github-run-attempt", "1",
            "--output-directory", str(tmp_path),
            "--deployment-id", "github-run-123456789-attempt-1-dev",
            "--release-id", "rc-20260624-123456789",
            "--artifact-name", "rc-20260624-123456789.zip",
            "--artifact-hash",
            (
                "sha256:"
                "0123456789abcdef0123456789abcdef"
                "0123456789abcdef0123456789abcdef"
            ),
            "--operation-status", "SUCCESS",
            "--operation-exit-code", "0",
            "--evidence-role", "canonical",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Invalid environment: qa" in result.stderr + result.stdout


def test_cli_atomic_write_leaves_no_tmp_file_after_success(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    tmp_file = tmp_path / "dev-deployment-manifest.json.tmp"

    result = run_script(
        output_directory=tmp_path,
    )

    assert_success(result)
    assert output_path.exists()
    assert not tmp_file.exists()

def test_cli_generates_success_operation_metadata(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = (
        tmp_path
        / "dev-deployment-manifest.json"
    )

    data = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert data["operation"]["status"] == "SUCCESS"
    assert data["operation"]["exit_code"] == 0
    assert data["operation"]["failure_reason"] is None

def replace_cli_argument(args, argument_name, value):
    argument_index = args.index(argument_name)
    args[argument_index + 1] = str(value)

def test_cli_generates_failed_operation_metadata(tmp_path):
    output_path = (
        tmp_path
        / (
            "dev-deployment-manifest"
            "-run-123456789-attempt-1.json"
        )
    )

    args = cli_args(
        environment="dev",
        output_directory=tmp_path,
        evidence_role="historical",
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )
    args.extend(
        [
            "--failure-reason",
            "DEPLOY_COMMAND_FAILED",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert_success(result)

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["operation"]["status"] == "FAILED"
    assert data["operation"]["exit_code"] == 1
    assert (
        data["operation"]["failure_reason"]
        == "DEPLOY_COMMAND_FAILED"
    )

def test_cli_generates_failed_historical_evidence(tmp_path):
    args = cli_args(
        output_directory=tmp_path,
        evidence_role="historical",
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )
    args.extend(
        [
            "--failure-reason",
            "DEPLOY_COMMAND_FAILED",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert_success(result)

    output_path = (
        tmp_path
        / (
            "dev-deployment-manifest"
            "-run-123456789-attempt-1.json"
        )
    )

    data = json.loads(
        output_path.read_text(encoding="utf-8")
    )

    assert data["operation"]["status"] == "FAILED"
    assert (
        data["evidence_storage"]["artifact_role"]
        == "historical"
    )

def test_cli_rejects_failed_canonical_evidence(tmp_path):
    args = cli_args(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )
    args.extend(
        [
            "--failure-reason",
            "DEPLOY_COMMAND_FAILED",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "canonical deployment evidence may only be"
        in result.stderr.lower()
    )



def test_cli_rejects_success_with_nonzero_exit_code(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    args = cli_args(
        output_directory=tmp_path,
    )

    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "operation_exit_code must be 0"
        in result.stderr.lower()
    )
    assert not output_path.exists()

def test_cli_rejects_success_with_failure_reason(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    args = cli_args(
        output_directory=tmp_path,
    )

    args.extend(
        [
            "--failure-reason",
            "DEPLOY_COMMAND_FAILED",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "failure_reason must be null"
        in result.stderr.lower()
    )
    assert not output_path.exists()

def test_cli_rejects_failed_with_zero_exit_code(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    args = cli_args(
        output_directory=tmp_path,
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    args.extend(
        [
            "--failure-reason",
            "DEPLOY_COMMAND_FAILED",
        ]
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "operation_exit_code must be greater than zero"
        in result.stderr.lower()
    )
    assert not output_path.exists()

def test_cli_rejects_failed_without_failure_reason(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    args = cli_args(
        output_directory=tmp_path,
    )

    replace_cli_argument(
        args,
        "--operation-status",
        "FAILED",
    )
    replace_cli_argument(
        args,
        "--operation-exit-code",
        "1",
    )

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "failure_reason must be one of the approved values"
        in result.stderr.lower()
    )
    assert not output_path.exists()

def test_cli_creates_canonical_manifest(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="canonical",
    )

    assert_success(result)

    output_path = tmp_path / "dev-deployment-manifest.json"
    assert output_path.exists()

def test_cli_creates_historical_manifest(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        evidence_role="historical",
    )

    assert_success(result)

    output_path = (
        tmp_path
        / (
            "dev-deployment-manifest"
            "-run-123456789-attempt-1.json"
        )
    )
    assert output_path.exists()

def test_cli_rejects_removed_evidence_storage_argument(tmp_path):
    result = run_script(
        output_directory=tmp_path,
        extra_args=[
            "--evidence-storage-type",
            "github_actions_artifact",
        ],
    )

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr.lower()

def test_cli_creates_nested_output_directory(tmp_path):
    output_directory = tmp_path / "artifacts" / "deployment"

    result = run_script(
        output_directory=output_directory,
    )

    assert_success(result)
    assert (
        output_directory / "dev-deployment-manifest.json"
    ).exists()

    