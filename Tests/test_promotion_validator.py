import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

def get_validator_script():
    env_path = os.getenv("PROMOTION_VALIDATOR_SCRIPT")

    if env_path:
        script = Path(env_path).expanduser().resolve()
    else:
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "promotion_validator.py"
        ).resolve()

    if not script.exists():
        raise FileNotFoundError(
            f"Promotion validator script not found: {script}"
        )

    return script


SCRIPT = get_validator_script()

VALID_RELEASE_ID = "rc-20260630-28454858980"
VALID_ARTIFACT_HASH = (
    "sha256:0123456789abcdef0123456789abcdef"
    "0123456789abcdef0123456789abcdef"
)


def load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "promotion_validator_under_test",
        SCRIPT,
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Unable to load promotion validator: {SCRIPT}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module

def release_args(
    release_id=VALID_RELEASE_ID,
    artifact_hash=VALID_ARTIFACT_HASH,
):
    return [
        "--release-id", release_id,
        "--artifact-hash", artifact_hash,
    ]


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def valid_manifest(
    *,
    environment="dev",
    release_id=VALID_RELEASE_ID,
    artifact_name=None,
    artifact_hash=VALID_ARTIFACT_HASH,
    operation_status="SUCCESS",
    exit_code=None,
    failure_reason=None,
    workspace_target=None,
    bundle_target=None,
    schema_version="1.0",
    artifact_role=None,
):
    promotion_metadata = {
        "dev": {
            "from_environment": None,
            "to_environment": "dev",
            "required_previous_environment": None,
        },
        "uat": {
            "from_environment": "dev",
            "to_environment": "uat",
            "required_previous_environment": "dev",
        },
        "prod": {
            "from_environment": "uat",
            "to_environment": "prod",
            "required_previous_environment": "uat",
        },
    }

    if exit_code is None:
        exit_code = 0 if operation_status == "SUCCESS" else 1

    if operation_status == "FAILED" and failure_reason is None:
        failure_reason = "DEPLOY_COMMAND_FAILED"

    if artifact_role is None:
        artifact_role = (
            "canonical"
            if operation_status == "SUCCESS"
            else "historical"
        )

    if artifact_role == "canonical":
        evidence_artifact_name = (
            f"{environment}-deployment-manifest.json"
        )
    else:
        evidence_artifact_name = (
            f"{environment}-deployment-manifest"
            "-run-123-attempt-1.json"
        )

    return {
        "schema_version": schema_version,
        "environment": environment,
        "deployment_id": (
            f"github-run-123-attempt-1-{environment}"
        ),
        "release": {
            "release_id": release_id,
            "artifact_name": artifact_name or f"{release_id}.zip",
            "artifact_hash": artifact_hash,
        },
        "promotion": promotion_metadata[environment].copy(),
        "bundle": {
            "name": "databricks-cicd-bundle-poc",
            "target": bundle_target or environment,
        },
        "git": {
            "repository": "mashhood/databricks-cicd",
            "source_branch": environment,
            "target_branch": environment,
            "commit_sha": "abc123",
            "commit_message": "test commit",
            "actor": "mashhoodhamid201",
        },
        "github_actions": {
            "workflow_name": "Databricks Bundle CI/CD",
            "workflow_run_id": "123",
            "workflow_run_number": "1",
            "workflow_run_attempt": "1",
            "job_name": f"deploy-{environment}",
            "event_name": "workflow_dispatch",
        },
        "evidence_storage": {
            "storage_type": "github_release_asset",
            "artifact_name": evidence_artifact_name,
            "artifact_version": "1.0",
            "artifact_role": artifact_role,
            "artifact_generated_by_run_id": "123",
            "artifact_generated_by_run_number": "1",
            "artifact_generated_by_run_attempt": "1",
            "artifact_retention_days": None,
        },
        "databricks": {
            "workspace_target": workspace_target or environment,
            "workspace_host": (
                "https://example.cloud.databricks.com"
            ),
            "authenticated_principal": "sp-github-actions",
            "workspace_root_path": "/Workspace/test",
        },
        "operation": {
            "action": "bundle_deploy",
            "status": operation_status,
            "exit_code": exit_code,
            "failure_reason": failure_reason,
            "started_at": "2026-06-22T10:00:00Z",
            "completed_at": "2026-06-22T10:01:00Z",
        },
    }


def run_validator(tmp_path: Path, *args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )

    output_files = sorted(tmp_path.glob("*promotion-validation-result.json"))
    output_data = None

    if output_files:
        output_data = json.loads(output_files[0].read_text(encoding="utf-8"))

    return result, output_data


def assert_decision(output_data, expected_code):
    assert output_data is not None, "Validator did not create an output JSON file"
    assert output_data["decision"] == expected_code

@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("started_at", "2026-06-22T10:00:00.123Z"),
        ("completed_at", "2026-06-22T10:01:00.456Z"),
        ("started_at", "2026-06-22 10:00:00Z"),
        ("completed_at", "2026-06-22 10:01:00Z"),
        ("started_at", "2026-06-22T10:00:00"),
        ("completed_at", "2026-06-22T10:01:00"),
        ("started_at", "2026-06-22T10:00:00+00:00"),
        ("completed_at", "2026-06-22T10:01:00+00:00"),
        ("started_at", "not-a-timestamp"),
        ("completed_at", "not-a-timestamp"),
        ("started_at", "2026-02-30T10:00:00Z"),
        ("completed_at", "2026-13-22T10:01:00Z"),
    ],
)
def test_invalid_operation_utc_timestamp_rejected(
    tmp_path,
    field,
    value,
):
    manifest = valid_manifest(environment="dev")
    manifest["operation"][field] = value

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_utc_timestamps_with_fractional_seconds_rejected(
    tmp_path,
):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["started_at"] = (
        "2026-06-22T10:00:00.123Z"
    )
    manifest["operation"]["completed_at"] = (
        "2026-06-22T10:01:00.456Z"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"]
        == "previous_manifest_schema_is_valid"
    )

    assert failed_check["status"] == "FAIL"
    assert (
        failed_check["actual"]
        == "operation.started_at must be a valid UTC timestamp"
    )


def test_completed_at_before_started_at_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["started_at"] = (
        "2026-06-22T10:02:00Z"
    )
    manifest["operation"]["completed_at"] = (
        "2026-06-22T10:01:00Z"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_equal_operation_timestamps_valid(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["started_at"] = (
        "2026-06-22T10:00:00Z"
    )
    manifest["operation"]["completed_at"] = (
        "2026-06-22T10:00:00Z"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


@pytest.mark.parametrize(
    "release_id",
    [
        "rc-20260230-28454858980",
        "rc-20261301-28454858980",
        "rc-20260010-28454858980",
        "rc-20260431-28454858980",
        "rc-20250229-28454858980",
    ],
)
def test_invalid_release_id_calendar_date_rejected(
    tmp_path,
    release_id,
):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id=release_id),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")

def test_valid_release_id_leap_year_date(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(
            release_id="rc-20240229-28454858980",
        ),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

def test_manifest_release_id_invalid_calendar_date(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["release_id"] = (
        "rc-20260230-28454858980"
    )
    manifest["release"]["artifact_name"] = (
        "rc-20260230-28454858980.zip"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "deployment_id",
    [
        "github-run-999-attempt-1-dev",
        "github-run-123-attempt-2-dev",
        "github-run-123-attempt-1-uat",
        "github-run-123-dev",
        "arbitrary-deployment-id",
    ],
)
def test_deployment_id_metadata_mismatch_rejected(
    tmp_path,
    deployment_id,
):
    manifest = valid_manifest(environment="dev")
    manifest["deployment_id"] = deployment_id

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_dev_promotion_valid(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_valid_uat_promotion_release_identity_matches(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")
    assert output["previous_environment"] == "dev"
    assert output["previous_manifest_path"] == "dev-deployment-manifest.json"


def test_valid_prod_promotion_release_identity_matches(tmp_path):
    write_json(
        tmp_path / "uat-deployment-manifest.json",
        valid_manifest(environment="uat"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "prod",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")
    assert output["previous_environment"] == "uat"
    assert output["previous_manifest_path"] == "uat-deployment-manifest.json"
    
@pytest.mark.parametrize(
    "target_environment",
    [
        None,
        123,
        [],
        {},
        True,
    ],
)
def test_validate_promotion_rejects_invalid_target_type(
    target_environment,
):
    validator_module = load_validator_module()

    result = validator_module.validate_promotion(
        target_environment=target_environment,
        release_id=VALID_RELEASE_ID,
        artifact_hash=VALID_ARTIFACT_HASH,
        previous_manifest_path=None,
    )

    assert result["valid"] is False
    assert (
        result["decision"]
        == "INVALID_PROMOTION_SEQUENCE"
    )
    assert result["message"] == (
        "Invalid target environment."
    )

    assert result["checks"] == [
        {
            "name": "target_environment_is_valid",
            "status": "FAIL",
            "expected": "dev, uat, or prod",
            "actual": target_environment,
        }
    ]

def test_deployment_manifest_contract_is_accepted_by_promotion_validator(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

@pytest.mark.parametrize(
    "release_id",
    [
        "rc-20260230-28454858980",
        "rc-20260630-abc",
        "20260630-28454858980",
        "rc-20260630-",
    ],
)

def test_invalid_manifest_release_id_rejected(
    tmp_path,
    release_id,
):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["release_id"] = release_id
    manifest["release"]["artifact_name"] = (
        f"{release_id}.zip"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "artifact_hash",
    [
        "sha256:abc123",
        "0123456789abcdef",
        "sha256:" + ("z" * 64),
        "sha512:" + ("a" * 64),
    ],
)
def test_invalid_manifest_artifact_hash_rejected(
    tmp_path,
    artifact_hash,
):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_hash"] = artifact_hash

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")




def test_missing_previous_manifest(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_FOUND")

@pytest.mark.parametrize(
    ("environment", "target_environment", "manifest_name"),
    [
        ("dev", "uat", "dev-deployment-manifest.json"),
        ("uat", "prod", "uat-deployment-manifest.json"),
    ],
)
def test_valid_promotion_metadata(
    tmp_path,
    environment,
    target_environment,
    manifest_name,
):
    write_json(
        tmp_path / manifest_name,
        valid_manifest(environment=environment),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        target_environment,
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

@pytest.mark.parametrize(
    ("environment", "field", "invalid_value"),
    [
        ("dev", "from_environment", "uat"),
        ("dev", "to_environment", "uat"),
        ("dev", "required_previous_environment", "dev"),
        ("uat", "from_environment", None),
        ("uat", "to_environment", "prod"),
        ("uat", "required_previous_environment", None),
    ],
)
def test_invalid_promotion_metadata_rejected(
    tmp_path,
    environment,
    field,
    invalid_value,
):
    manifest = valid_manifest(environment=environment)
    manifest["promotion"][field] = invalid_value

    manifest_name = (
        f"{environment}-deployment-manifest.json"
    )

    write_json(tmp_path / manifest_name, manifest)

    target_environment = (
        "uat" if environment == "dev" else "prod"
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        target_environment,
        *release_args(),
        "--previous-manifest-path",
        manifest_name,
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "field",
    [
        "from_environment",
        "to_environment",
        "required_previous_environment",
    ],
)
def test_missing_promotion_metadata_field_invalid_schema(
    tmp_path,
    field,
):
    manifest = valid_manifest(environment="dev")
    del manifest["promotion"][field]

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")



def test_previous_environment_mismatch(tmp_path):
    manifest = valid_manifest(
        environment="uat",
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "PREVIOUS_ENVIRONMENT_MISMATCH",
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_environment_matches"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == "dev"
    assert failed_check["actual"] == "uat"

def test_historical_failed_manifest_cannot_authorize_promotion(
    tmp_path,
):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(
            environment="dev",
            operation_status="FAILED",
            exit_code=1,
            failure_reason="DEPLOY_COMMAND_FAILED",
        ),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_CANONICAL",
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_manifest_is_canonical"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == "canonical"
    assert failed_check["actual"] == "historical"

    assert not any(
        check["name"]
        == "previous_deployment_status_is_success"
        for check in output["checks"]
    )


def test_release_id_mismatch(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev", release_id="rc-20260630-99999999999"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "RELEASE_ID_MISMATCH")


def test_artifact_hash_mismatch(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(
    environment="dev",
    artifact_hash="sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    ),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "ARTIFACT_HASH_MISMATCH")


def test_workspace_target_mismatch(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev", workspace_target="uat"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "workspace_host",
    [
        "https://example.cloud.databricks.com",
        "https://adb-123456789.12.azuredatabricks.net",
        "https://example.cloud.databricks.com/",
    ],
)
def test_valid_workspace_https_url(
    tmp_path,
    workspace_host,
):
    manifest = valid_manifest(environment="dev")
    manifest["databricks"]["workspace_host"] = workspace_host

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

@pytest.mark.parametrize(
    "workspace_host",
    [
        "http://example.cloud.databricks.com",
        "example.cloud.databricks.com",
        "https://",
        "ftp://example.cloud.databricks.com",
        "",
    ],
)
def test_invalid_workspace_url_rejected(
    tmp_path,
    workspace_host,
):
    manifest = valid_manifest(environment="dev")
    manifest["databricks"]["workspace_host"] = workspace_host

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_bundle_target_environment_mismatch_invalid_schema(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev", bundle_target="uat"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_invalid_schema_version(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev", schema_version="2.0"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_invalid_json_manifest(tmp_path):
    (tmp_path / "dev-deployment-manifest.json").write_text(
        "{ invalid json",
        encoding="utf-8",
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_missing_release_section_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["release"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_release_section_not_object_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"] = "not-an-object"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_missing_release_id_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["release"]["release_id"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_missing_artifact_name_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["release"]["artifact_name"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_missing_artifact_hash_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["release"]["artifact_hash"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_empty_release_id_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["release_id"] = ""

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_empty_artifact_name_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_name"] = ""

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_empty_artifact_hash_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_hash"] = ""

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(tmp_path, "--target-environment", "uat", *release_args())

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_valid_release_id_format(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id=VALID_RELEASE_ID),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_invalid_release_id_missing_prefix(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id="20260630-28454858980"),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_release_id_invalid_date_format(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id="rc-2026-06-30-28454858980"),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_release_id_missing_numeric_identifier(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id="rc-20260630-"),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_release_id_non_numeric_identifier(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(release_id="rc-20260630-abc123"),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_valid_artifact_hash_format(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(artifact_hash=VALID_ARTIFACT_HASH),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_invalid_artifact_hash_missing_prefix(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(
            artifact_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_artifact_hash_too_short(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(artifact_hash="sha256:abc123"),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_artifact_hash_invalid_hex(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(
            artifact_hash="sha256:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
        ),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")


def test_invalid_artifact_hash_empty(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(artifact_hash=""),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_PROMOTION_SEQUENCE")

def test_valid_github_release_storage_type(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_invalid_storage_type(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["storage_type"] = "github_actions_artifact"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_valid_evidence_artifact_version(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["artifact_version"] = "1.0"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_invalid_evidence_artifact_version(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["artifact_version"] = "2.0"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_valid_evidence_artifact_name(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_evidence_artifact_name_environment_mismatch(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["artifact_name"] = (
        "uat-deployment-manifest.json"
    )

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_missing_artifact_retention_days_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_retention_days"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_artifact_retention_days_null_valid(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["artifact_retention_days"] = None

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_artifact_retention_days_not_null_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"]["artifact_retention_days"] = 7

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_missing_evidence_storage_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_evidence_storage_not_object_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"] = "not-an-object"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_missing_evidence_storage_type_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["storage_type"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "field",
    [
        "storage_type",
        "artifact_name",
        "artifact_version",
        "artifact_generated_by_run_id",
        "artifact_generated_by_run_number",
        "artifact_generated_by_run_attempt",
    ],
)
def test_empty_evidence_storage_string_field_invalid_schema(
    tmp_path,
    field,
):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"][field] = ""

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")
    


def test_missing_evidence_artifact_name_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_name"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_missing_evidence_artifact_version_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_version"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_missing_evidence_artifact_role_invalid_schema(
    tmp_path,
):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_role"]

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )



@pytest.mark.parametrize(
    "artifact_role",
    [
        "",
        "latest",
        "archive",
        None,
        123,
    ],
)
def test_invalid_evidence_artifact_role_rejected(
    tmp_path,
    artifact_role,
):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"][
        "artifact_role"
    ] = artifact_role

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )


def test_missing_evidence_generated_run_id_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_generated_by_run_id"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_missing_evidence_generated_run_attempt_invalid_schema(
    tmp_path,
):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"][
        "artifact_generated_by_run_attempt"
    ]

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")



def test_missing_evidence_generated_run_number_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["evidence_storage"]["artifact_generated_by_run_number"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "field",
    [
        "artifact_generated_by_run_id",
        "artifact_generated_by_run_number",
        "artifact_generated_by_run_attempt",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        "",
        "0",
        "01",
        "-1",
        "abc",
        1,
        None,
        True,
        "١",
    ],
)
def test_invalid_evidence_run_metadata_rejected(
    tmp_path,
    field,
    invalid_value,
):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"][field] = invalid_value

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    ("evidence_field", "mismatched_value"),
    [
        ("artifact_generated_by_run_id", "999"),
        ("artifact_generated_by_run_number", "2"),
        ("artifact_generated_by_run_attempt", "2"),
    ],
)
def test_evidence_run_metadata_mismatch_rejected(
    tmp_path,
    evidence_field,
    mismatched_value,
):
    manifest = valid_manifest(environment="dev")
    manifest["evidence_storage"][
        evidence_field
    ] = mismatched_value

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")



def test_matching_workflow_run_id(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["github_actions"]["workflow_run_id"] = "123"
    manifest["evidence_storage"]["artifact_generated_by_run_id"] = "123"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

@pytest.mark.parametrize(
    "field",
    [
        "workflow_run_id",
        "workflow_run_number",
        "workflow_run_attempt",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        "",
        "0",
        "01",
        "-1",
        "1.5",
        "abc",
        1,
        None,
        True,
        "١",
    ],
)
def test_invalid_github_run_metadata_rejected(
    tmp_path,
    field,
    invalid_value,
):
    manifest = valid_manifest(environment="dev")
    manifest["github_actions"][field] = invalid_value

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_valid_github_run_metadata(tmp_path):
    manifest = valid_manifest(environment="dev")

    manifest["github_actions"]["workflow_run_id"] = "987654321"
    manifest["github_actions"]["workflow_run_number"] = "42"
    manifest["github_actions"]["workflow_run_attempt"] = "3"

    manifest["deployment_id"] = (
        "github-run-987654321-attempt-3-dev"
    )

    manifest["evidence_storage"][
        "artifact_generated_by_run_id"
    ] = "987654321"
    manifest["evidence_storage"][
        "artifact_generated_by_run_number"
    ] = "42"
    manifest["evidence_storage"][
        "artifact_generated_by_run_attempt"
    ] = "3"

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

def test_workflow_run_id_mismatch(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["github_actions"]["workflow_run_id"] = "123"
    manifest["evidence_storage"]["artifact_generated_by_run_id"] = "999"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_matching_workflow_run_number(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["github_actions"]["workflow_run_number"] = "1"
    manifest["evidence_storage"]["artifact_generated_by_run_number"] = "1"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_workflow_run_number_mismatch(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["github_actions"]["workflow_run_number"] = "1"
    manifest["evidence_storage"]["artifact_generated_by_run_number"] = "2"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_valid_operation_action(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_missing_operation_action_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    del manifest["operation"]["action"]

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_empty_operation_action_invalid_schema(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["action"] = ""

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_invalid_operation_action_value(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["action"] = "bundle_validate"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_valid_success_operation_contract(tmp_path):
    manifest = valid_manifest(
        environment="dev",
        operation_status="SUCCESS",
        exit_code=0,
        failure_reason=None,
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")

@pytest.mark.parametrize(
    "exit_code",
    [1, -1, 2],
)
def test_success_operation_nonzero_exit_code_rejected(
    tmp_path,
    exit_code,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="SUCCESS",
        exit_code=exit_code,
        failure_reason=None,
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_success_operation_failure_reason_must_be_null(
    tmp_path,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="SUCCESS",
        exit_code=0,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "failure_reason",
    [
        "DEPLOY_COMMAND_FAILED",
        "DEPLOY_TIMEOUT",
        "DEPLOY_CANCELLED",
        "UNKNOWN_DEPLOYMENT_FAILURE",
    ],
)

def test_valid_historical_failed_manifest_rejected_before_status_check(
    tmp_path,
    failure_reason,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="FAILED",
        exit_code=1,
        failure_reason=failure_reason,
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert_decision(
        output,
        "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_CANONICAL",
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_manifest_is_canonical"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == "canonical"
    assert failed_check["actual"] == "historical"

    assert not any(
        check["name"]
        == "previous_deployment_status_is_success"
        for check in output["checks"]
    )

@pytest.mark.parametrize(
    "exit_code",
    [0, -1, -10],
)
def test_failed_operation_requires_positive_exit_code(
    tmp_path,
    exit_code,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="FAILED",
        exit_code=exit_code,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )


@pytest.mark.parametrize(
    "failure_reason",
    [
        None,
        "",
        "UNKNOWN",
        "COMMAND_FAILED",
        123,
    ],
)
def test_failed_operation_rejects_unapproved_failure_reason(
    tmp_path,
    failure_reason,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="FAILED",
        exit_code=1,
        failure_reason="DEPLOY_COMMAND_FAILED",
    )

    manifest["operation"]["failure_reason"] = failure_reason

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )


@pytest.mark.parametrize(
    "missing_field",
    ["exit_code", "failure_reason"],
)
def test_missing_operation_contract_field_invalid_schema(
    tmp_path,
    missing_field,
):
    manifest = valid_manifest(environment="dev")
    del manifest["operation"][missing_field]

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

@pytest.mark.parametrize(
    "exit_code",
    ["0", 1.0, None, True, False],
)
def test_exit_code_must_be_integer(
    tmp_path,
    exit_code,
):
    manifest = valid_manifest(environment="dev")
    manifest["operation"]["exit_code"] = exit_code

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")



def test_valid_artifact_name_matches_release_id(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")


def test_artifact_name_mismatch(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_name"] = "different-release.zip"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_artifact_name_wrong_extension(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_name"] = f"{VALID_RELEASE_ID}.tar.gz"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_artifact_name_missing_release_id(tmp_path):
    manifest = valid_manifest(environment="dev")
    manifest["release"]["artifact_name"] = "artifact.zip"

    write_json(tmp_path / "dev-deployment-manifest.json", manifest)

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_empty_manifest_file(tmp_path):
    (tmp_path / "dev-deployment-manifest.json").write_text("", encoding="utf-8")

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")


def test_wrong_root_type_manifest(tmp_path):
    (tmp_path / "dev-deployment-manifest.json").write_text(
        json.dumps([]),
        encoding="utf-8",
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "INVALID_MANIFEST_SCHEMA")

def test_duplicate_json_key_rejected(tmp_path):
    manifest_json = json.dumps(
        valid_manifest(environment="dev"),
        indent=2,
    )

    duplicate_manifest_json = manifest_json.replace(
        '"schema_version": "1.0",',
        (
            '"schema_version": "1.0",\n'
            '  "schema_version": "1.0",'
        ),
        1,
    )

    (
        tmp_path / "dev-deployment-manifest.json"
    ).write_text(
        duplicate_manifest_json,
        encoding="utf-8",
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )

    assert output["message"] == (
        "Previous deployment manifest could not be loaded."
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_manifest_is_loadable"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == (
        "readable JSON within the maximum allowed size"
    )
    assert failed_check["actual"] == (
        "Duplicate JSON key: schema_version"
    )

def test_oversized_manifest_rejected(tmp_path):
    validator_module = load_validator_module()

    manifest_path = (
        tmp_path / "dev-deployment-manifest.json"
    )

    manifest_path.write_bytes(
        b"{" + (
            b" " * validator_module.MAX_MANIFEST_SIZE_BYTES
        ) + b"}"
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )

    assert output["message"] == (
        "Previous deployment manifest could not be loaded."
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_manifest_is_loadable"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == (
        "readable JSON within the maximum allowed size"
    )
    assert failed_check["actual"] == (
        "Deployment manifest exceeds maximum "
        f"allowed size of "
        f"{validator_module.MAX_MANIFEST_SIZE_BYTES} bytes"
    )

def test_invalid_utf8_manifest_rejected(tmp_path):
    manifest_path = (
        tmp_path / "dev-deployment-manifest.json"
    )

    manifest_path.write_bytes(
        b'{"schema_version": "\xff"}'
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )

    assert output["message"] == (
        "Previous deployment manifest could not be loaded."
    )

    failed_check = next(
        check
        for check in output["checks"]
        if check["name"] == "previous_manifest_is_loadable"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == (
        "readable JSON within the maximum allowed size"
    )
    assert failed_check["actual"] == (
        "Deployment manifest must contain valid UTF-8"
    )


def test_canonical_failed_evidence_rejected(
    tmp_path,
):
    manifest = valid_manifest(
        environment="dev",
        operation_status="FAILED",
        exit_code=1,
        failure_reason="DEPLOY_COMMAND_FAILED",
        artifact_role="canonical",
    )

    manifest["evidence_storage"]["artifact_name"] = (
        "dev-deployment-manifest.json"
    )

    write_json(
        tmp_path / "dev-deployment-manifest.json",
        manifest,
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment",
        "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(
        output,
        "INVALID_MANIFEST_SCHEMA",
    )

def test_manual_previous_manifest_override(tmp_path):
    write_json(
        tmp_path / "custom-dev-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
        "--previous-manifest-path", "custom-dev-manifest.json",
    )

    assert result.returncode == 0
    assert_decision(output, "PROMOTION_VALID")
    assert output["previous_manifest_path"] == "custom-dev-manifest.json"

def test_manual_output_path_override(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, _ = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
        "--output-path", "custom-result.json",
    )

    assert result.returncode == 0

    custom_output = json.loads(
        (tmp_path / "custom-result.json").read_text(encoding="utf-8")
    )

    assert custom_output["decision"] == "PROMOTION_VALID"

def test_output_write_failure_returns_controlled_cli_error(
    tmp_path,
):
    blocking_file = tmp_path / "not-a-directory"

    blocking_file.write_text(
        "blocking file",
        encoding="utf-8",
    )

    invalid_output_path = (
        blocking_file / "result.json"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--target-environment",
            "dev",
            *release_args(),
            "--output-path",
            str(invalid_output_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0

    assert (
        "Failed to write promotion validation result"
        in result.stderr
    )

    assert "Traceback" not in result.stderr

def test_default_dev_output_name(tmp_path):
    result, _ = run_validator(
        tmp_path,
        "--target-environment", "dev",
        *release_args(),
    )

    assert result.returncode == 0
    assert (tmp_path / "dev-promotion-validation-result.json").exists()


def test_default_uat_output_name(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev"),
    )

    result, _ = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode == 0
    assert (tmp_path / "uat-promotion-validation-result.json").exists()


def test_default_prod_output_name(tmp_path):
    write_json(
        tmp_path / "uat-deployment-manifest.json",
        valid_manifest(environment="uat"),
    )

    result, _ = run_validator(
        tmp_path,
        "--target-environment", "prod",
        *release_args(),
    )

    assert result.returncode == 0
    assert (tmp_path / "prod-promotion-validation-result.json").exists()