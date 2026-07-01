import subprocess
from pathlib import Path

SCRIPT = Path("scripts/cd_resolve_context.sh")


VALID_RELEASE_ID = "rc-20260630-123456"
VALID_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def run_context(
    target_environment,
    release_id=VALID_RELEASE_ID,
    artifact_hash=VALID_HASH,
):
    result = subprocess.run(
        ["bash", str(SCRIPT), target_environment, release_id, artifact_hash],
        capture_output=True,
        text=True,
    )

    output = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            output[key] = value

    return result, output


def test_dev_outputs_are_exactly_expected():
    result, output = run_context("dev")

    assert result.returncode == 0
    assert output == {
        "target_environment": "dev",
        "release_id": VALID_RELEASE_ID,
        "artifact_hash": VALID_HASH,
        "bundle_target": "dev",
        "github_environment": "dev",
        "workspace_target": "dev",
        "previous_environment": "",
        "previous_manifest_path": "",
        "deployment_manifest_name": "dev-deployment-manifest.json",
    }


def test_uat_outputs_are_exactly_expected():
    result, output = run_context("uat")

    assert result.returncode == 0
    assert output == {
        "target_environment": "uat",
        "release_id": VALID_RELEASE_ID,
        "artifact_hash": VALID_HASH,
        "bundle_target": "uat",
        "github_environment": "uat",
        "workspace_target": "uat",
        "previous_environment": "dev",
        "previous_manifest_path": "dev-deployment-manifest.json",
        "deployment_manifest_name": "uat-deployment-manifest.json",
    }


def test_prod_outputs_are_exactly_expected():
    result, output = run_context("prod")

    assert result.returncode == 0
    assert output == {
        "target_environment": "prod",
        "release_id": VALID_RELEASE_ID,
        "artifact_hash": VALID_HASH,
        "bundle_target": "prod",
        "github_environment": "prod",
        "workspace_target": "prod",
        "previous_environment": "uat",
        "previous_manifest_path": "uat-deployment-manifest.json",
        "deployment_manifest_name": "prod-deployment-manifest.json",
    }


def test_release_id_is_passed_through():
    release_id = "rc-20260630-999999"

    result, output = run_context("dev", release_id=release_id)

    assert result.returncode == 0
    assert output["release_id"] == release_id


def test_artifact_hash_is_passed_through():
    artifact_hash = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    result, output = run_context("dev", artifact_hash=artifact_hash)

    assert result.returncode == 0
    assert output["artifact_hash"] == artifact_hash


def test_invalid_environment_fails():
    result, _ = run_context("qa")

    assert result.returncode != 0
    assert "Unsupported target environment: qa" in result.stderr


def test_uppercase_environment_is_rejected():
    result, _ = run_context("DEV")

    assert result.returncode != 0
    assert "Unsupported target environment: DEV" in result.stderr


def test_mixed_case_environment_is_rejected():
    result, _ = run_context("Dev")

    assert result.returncode != 0
    assert "Unsupported target environment: Dev" in result.stderr


def test_environment_with_whitespace_is_rejected():
    result, _ = run_context(" dev ")

    assert result.returncode != 0
    assert "Unsupported target environment:  dev " in result.stderr


def test_invalid_release_id_format_fails():
    result, _ = run_context("dev", release_id="release-123")

    assert result.returncode != 0
    assert "Invalid release id: release-123" in result.stderr


def test_invalid_artifact_hash_format_fails():
    result, _ = run_context("dev", artifact_hash="sha256:abcd")

    assert result.returncode != 0
    assert "Invalid artifact hash: sha256:abcd" in result.stderr


def test_missing_target_environment_fails():
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_missing_release_id_fails():
    result = subprocess.run(
        ["bash", str(SCRIPT), "dev", "", VALID_HASH],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_missing_artifact_hash_fails():
    result = subprocess.run(
        ["bash", str(SCRIPT), "dev", VALID_RELEASE_ID, ""],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_output_contains_expected_keys_only():
    result, output = run_context("uat")

    assert result.returncode == 0
    assert set(output.keys()) == {
        "target_environment",
        "release_id",
        "artifact_hash",
        "bundle_target",
        "github_environment",
        "workspace_target",
        "previous_environment",
        "previous_manifest_path",
        "deployment_manifest_name",
    }

def test_release_id_with_bad_date_format_fails():
    result, _ = run_context("dev", release_id="rc-2026-0630-123456")

    assert result.returncode != 0
    assert "Invalid release id" in result.stderr

def test_release_id_with_non_numeric_suffix_fails():
    result, _ = run_context("dev", release_id="rc-20260630-abc123")

    assert result.returncode != 0
    assert "Invalid release id" in result.stderr

def test_artifact_hash_without_sha256_prefix_fails():
    result, _ = run_context(
        "dev",
        artifact_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert result.returncode != 0
    assert "Invalid artifact hash" in result.stderrd

def test_artifact_hash_with_non_hex_characters_fails():
    result, _ = run_context(
        "dev",
        artifact_hash="sha256:gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg",
    )

    assert result.returncode != 0
    assert "Invalid artifact hash" in result.stderr