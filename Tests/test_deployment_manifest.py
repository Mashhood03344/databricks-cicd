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

from deployment_manifest import build_manifest


def make_args(environment="dev", bundle_target="dev", workspace_target="dev"):
    return Namespace(
        environment=environment,
        bundle_name="databricks-cicd-bundle-poc",
        bundle_target=bundle_target,
        workspace_target=workspace_target,
        workspace_root_path="/Workspace/Users/sp/.bundle/databricks-cicd-bundle-poc/dev",
        authenticated_principal="sp-github-actions-dab-dev",
        started_at="2026-06-12T10:00:00Z",
        source_branch="dev",
        target_branch="dev",
        commit_sha="abc123",
        commit_message="Test deployment manifest generation",
        github_repository="mashhood/databricks-cicd",
        github_actor="mashhoodhamid201",
        github_workflow="Databricks Bundle CI/CD",
        github_run_id="123456789",
        github_run_number="42",
        github_job="deploy-dev",
        github_event_name="workflow_dispatch",
        databricks_host="https://dbc-example.cloud.databricks.com",
        evidence_storage_type="github_actions_artifact",
        evidence_artifact_name=f"{environment}-deployment-evidence",
        evidence_artifact_version="1.0",
        evidence_artifact_retention_days=7,
    )


def test_build_manifest_creates_valid_dev_manifest():
    manifest = build_manifest(make_args("dev"))

    assert manifest["schema_version"] == "1.0"
    assert manifest["environment"] == "dev"
    assert manifest["promotion"]["from_environment"] is None
    assert manifest["promotion"]["to_environment"] == "dev"
    assert manifest["promotion"]["required_previous_environment"] is None


def test_build_manifest_creates_valid_uat_promotion_metadata():
    manifest = build_manifest(make_args("uat", bundle_target="uat", workspace_target="uat"))

    assert manifest["environment"] == "uat"
    assert manifest["promotion"]["from_environment"] == "dev"
    assert manifest["promotion"]["to_environment"] == "uat"
    assert manifest["promotion"]["required_previous_environment"] == "dev"


def test_build_manifest_creates_valid_prod_promotion_metadata():
    manifest = build_manifest(make_args("prod", bundle_target="prod", workspace_target="prod"))

    assert manifest["environment"] == "prod"
    assert manifest["promotion"]["from_environment"] == "uat"
    assert manifest["promotion"]["to_environment"] == "prod"
    assert manifest["promotion"]["required_previous_environment"] == "uat"


def test_invalid_environment_raises_value_error():
    with pytest.raises(ValueError, match="Invalid environment: qa"):
        build_manifest(make_args("qa"))


def test_completed_at_is_populated_and_ends_with_z():
    manifest = build_manifest(make_args())

    assert manifest["operation"]["completed_at"]
    assert manifest["operation"]["completed_at"].endswith("Z")


def test_deployment_id_format():
    manifest = build_manifest(make_args("dev"))

    assert manifest["deployment_id"] == "github-run-123456789-dev"


def test_operation_action_is_bundle_deploy():
    manifest = build_manifest(make_args())

    assert manifest["operation"]["action"] == "bundle_deploy"


def test_operation_status_is_success():
    manifest = build_manifest(make_args())

    assert manifest["operation"]["status"] == "SUCCESS"


def test_bundle_target_is_copied_exactly_from_args():
    manifest = build_manifest(make_args("uat", bundle_target="custom-uat-target"))

    assert manifest["bundle"]["target"] == "custom-uat-target"


def test_workspace_target_is_copied_exactly_from_args():
    manifest = build_manifest(make_args("uat", workspace_target="custom-workspace-target"))

    assert manifest["databricks"]["workspace_target"] == "custom-workspace-target"


def cli_args(environment="dev", output_path=None):
    args = [
        sys.executable,
        str(SCRIPT_PATH),
        "--environment", environment,
        "--bundle-name", "databricks-cicd-bundle-poc",
        "--bundle-target", environment,
        "--workspace-target", environment,
        "--workspace-root-path", f"/Workspace/Users/sp/.bundle/databricks-cicd-bundle-poc/{environment}",
        "--authenticated-principal", f"sp-github-actions-dab-{environment}",
        "--started-at", "2026-06-12T10:00:00Z",
        "--github-run-id", "123456789",
        "--github-run-number", "42",
    ]

    if output_path is not None:
        args.extend(["--output-path", str(output_path)])

    return args


def run_script(environment="dev", output_path=None, cwd=None, extra_args=None, env=None):
    args = cli_args(environment=environment, output_path=output_path)

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
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = run_script(output_path=output_path)

    assert_success(result)
    assert output_path.exists()


def test_cli_output_json_is_valid(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = run_script(output_path=output_path)

    assert_success(result)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["environment"] == "dev"


def test_cli_nested_output_directory_is_created_automatically(tmp_path):
    output_path = tmp_path / "artifacts" / "dev" / "dev-deployment-manifest.json"

    result = run_script(output_path=output_path)

    assert_success(result)
    assert output_path.exists()

def test_cli_output_includes_evidence_storage(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = run_script(output_path=output_path)

    assert_success(result)

    data = json.loads(output_path.read_text(encoding="utf-8"))

    assert data["evidence_storage"]["storage_type"] == "github_actions_artifact"
    assert data["evidence_storage"]["artifact_name"] == "dev-deployment-evidence"
    assert data["evidence_storage"]["artifact_version"] == "1.0"
    assert data["evidence_storage"]["artifact_generated_by_run_id"] == "123456789"
    assert data["evidence_storage"]["artifact_generated_by_run_number"] == "42"
    assert data["evidence_storage"]["artifact_retention_days"] == 7


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


def test_output_path_override_wins(tmp_path):
    output_path = tmp_path / "custom-manifest.json"

    result = run_script(environment="dev", output_path=output_path, cwd=tmp_path)

    assert_success(result)
    assert output_path.exists()
    assert not (tmp_path / "dev-deployment-manifest.json").exists()


def test_github_run_id_required_when_env_var_absent(tmp_path):
    env = os.environ.copy()
    env.pop("GITHUB_RUN_ID", None)

    args = cli_args(environment="dev", output_path=tmp_path / "dev-deployment-manifest.json")
    run_id_index = args.index("--github-run-id")
    del args[run_id_index:run_id_index + 2]

    result = subprocess.run(args, env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "github-run-id" in result.stderr.lower() or "github_run_id" in result.stderr.lower()


def test_github_run_number_required_when_env_var_absent(tmp_path):
    env = os.environ.copy()
    env.pop("GITHUB_RUN_NUMBER", None)

    args = cli_args(environment="dev", output_path=tmp_path / "dev-deployment-manifest.json")
    run_number_index = args.index("--github-run-number")
    del args[run_number_index:run_number_index + 2]

    result = subprocess.run(args, env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "github-run-number" in result.stderr.lower() or "github_run_number" in result.stderr.lower()

def test_build_manifest_includes_evidence_storage():
    manifest = build_manifest(make_args("dev"))

    assert manifest["evidence_storage"]["storage_type"] == "github_actions_artifact"
    assert manifest["evidence_storage"]["artifact_name"] == "dev-deployment-evidence"
    assert manifest["evidence_storage"]["artifact_version"] == "1.0"
    assert manifest["evidence_storage"]["artifact_generated_by_run_id"] == "123456789"
    assert manifest["evidence_storage"]["artifact_generated_by_run_number"] == "42"
    assert manifest["evidence_storage"]["artifact_retention_days"] == 7


def test_cli_missing_required_args_fails_with_non_zero_exit_code(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--environment", "dev",
            "--output-path", str(output_path),
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
            "--output-path", str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Invalid environment: qa" in result.stderr + result.stdout


def test_cli_atomic_write_leaves_no_tmp_file_after_success(tmp_path):
    output_path = tmp_path / "dev-deployment-manifest.json"
    tmp_file = tmp_path / "dev-deployment-manifest.json.tmp"

    result = run_script(output_path=output_path)

    assert_success(result)
    assert output_path.exists()
    assert not tmp_file.exists()

def run_script_for_environment(
    environment,
    cwd,
    output_path=None,
    include_github_run_id=True,
    include_github_run_number=True,
):
    args = [
        sys.executable,
        str(SCRIPT_PATH),
        "--environment", environment,
        "--bundle-name", "databricks-cicd-bundle-poc",
        "--bundle-target", environment,
        "--workspace-target", environment,
        "--workspace-root-path", f"/Workspace/Users/sp/.bundle/databricks-cicd-bundle-poc/{environment}",
        "--authenticated-principal", f"sp-github-actions-dab-{environment}",
        "--started-at", "2026-06-12T10:00:00Z",
    ]

    if include_github_run_id:
        args.extend(["--github-run-id", "123456789"])

    if include_github_run_number:
        args.extend(["--github-run-number", "42"])

    if output_path:
        args.extend(["--output-path", str(output_path)])

    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)