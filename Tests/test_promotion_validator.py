import json
import subprocess
import sys
from pathlib import Path
import os

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
    workspace_target=None,
    bundle_target=None,
    schema_version="1.0",
):
    return {
        "schema_version": schema_version,
        "environment": environment,
        "deployment_id": f"github-run-123-{environment}",
        "release": {
            "release_id": release_id,
            "artifact_name": artifact_name or f"{release_id}.zip",
            "artifact_hash": artifact_hash,
        },
        "promotion": {
            "from_environment": None if environment == "dev" else "dev",
            "to_environment": environment,
            "required_previous_environment": None,
        },
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
            "job_name": f"deploy-{environment}",
            "event_name": "workflow_dispatch",
        },
        "databricks": {
            "workspace_target": workspace_target or environment,
            "host": "https://example.cloud.databricks.com",
            "authenticated_principal": "sp-github-actions",
            "workspace_root_path": "/Workspace/test",
        },
        "operation": {
            "action": "bundle_deploy",
            "status": operation_status,
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


def test_missing_previous_manifest(tmp_path):
    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "PREVIOUS_DEPLOYMENT_MANIFEST_NOT_FOUND")

def test_previous_environment_mismatch(tmp_path):
    manifest = valid_manifest(
        environment="dev",
        workspace_target="dev",
        bundle_target="dev",
    )

    manifest["environment"] = "uat"

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
    assert_decision(output, "PREVIOUS_ENVIRONMENT_MISMATCH")

    failed_check = next(
        check for check in output["checks"]
        if check["name"] == "previous_environment_matches"
    )

    assert failed_check["status"] == "FAIL"
    assert failed_check["expected"] == "dev"
    assert failed_check["actual"] == "uat"


def test_previous_deployment_failed(tmp_path):
    write_json(
        tmp_path / "dev-deployment-manifest.json",
        valid_manifest(environment="dev", operation_status="FAILED"),
    )

    result, output = run_validator(
        tmp_path,
        "--target-environment", "uat",
        *release_args(),
    )

    assert result.returncode != 0
    assert_decision(output, "PREVIOUS_DEPLOYMENT_NOT_SUCCESSFUL")


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
    assert_decision(output, "WORKSPACE_TARGET_MISMATCH")


def test_bundle_target_mismatch(tmp_path):
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
    assert_decision(output, "BUNDLE_TARGET_MISMATCH")


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