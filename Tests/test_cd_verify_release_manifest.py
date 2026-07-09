import hashlib
import json
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/cd_verify_release_manifest.sh")

VALID_RELEASE_ID = "rc-20260630-123456"


def sha256_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_release_package(tmp_path, release_id=VALID_RELEASE_ID, artifact_content="release-content", overrides=None):
    artifact_name = f"{release_id}.zip"
    artifact_path = tmp_path / artifact_name
    artifact_path.write_text(artifact_content, encoding="utf-8")

    manifest = {
        "schema_version": "1.0",
        "release": {
            "release_id": release_id,
            "artifact_name": artifact_name,
            "artifact_hash": sha256_hash(artifact_path),
            "release_asset_name": artifact_name,
        },
        "build": {
            "repository": "Mashhood03344/databricks-cicd",
            "source_branch": "dev",
            "commit_sha": "abc123",
            "workflow_run_id": "123456",
            "workflow_run_number": "42",
            "created_at_utc": "2026-06-30T15:11:26Z",
        },
    }

    if overrides:
        for dotted_key, value in overrides.items():
            parts = dotted_key.split(".")
            current = manifest

            for part in parts[:-1]:
                current = current[part]

            final_key = parts[-1]

            if value is None:
                current.pop(final_key, None)
            else:
                current[final_key] = value

    manifest_path = tmp_path / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest_path, artifact_path


def run_verify(manifest_path, release_id=VALID_RELEASE_ID):
    return subprocess.run(
        ["bash", str(SCRIPT), str(manifest_path), release_id],
        capture_output=True,
        text=True,
    )


def test_valid_release_manifest_and_artifact_passes(tmp_path):
    manifest_path, _ = write_release_package(tmp_path)

    result = run_verify(manifest_path)

    assert result.returncode == 0
    assert "Release manifest verification passed." in result.stdout
    assert f"release_id={VALID_RELEASE_ID}" in result.stdout


def test_missing_release_manifest_fails(tmp_path):
    result = run_verify(tmp_path / "missing_release_manifest.json")

    assert result.returncode != 0
    assert "Release manifest not found" in result.stderr


def test_release_id_mismatch_fails(tmp_path):
    manifest_path, _ = write_release_package(tmp_path)

    result = run_verify(manifest_path, release_id="rc-20260630-999999")

    assert result.returncode != 0
    assert "Release ID mismatch" in result.stderr


def test_missing_schema_version_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"schema_version": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .schema_version" in result.stderr


def test_invalid_schema_version_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"schema_version": "2.0"},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Unsupported schema_version: 2.0" in result.stderr


def test_missing_release_id_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.release_id": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .release.release_id" in result.stderr


def test_missing_artifact_name_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.artifact_name": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .release.artifact_name" in result.stderr


def test_artifact_name_mismatch_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.artifact_name": "different.zip"},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Invalid artifact name: different.zip" in result.stderr


def test_missing_release_asset_name_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.release_asset_name": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .release.release_asset_name" in result.stderr


def test_release_asset_name_mismatch_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.release_asset_name": "wrong.zip"},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Invalid release asset name: wrong.zip" in result.stderr


def test_missing_artifact_hash_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.artifact_hash": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .release.artifact_hash" in result.stderr


def test_invalid_artifact_hash_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"release.artifact_hash": "sha256:abc123"},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Invalid artifact hash: sha256:abc123" in result.stderr


def test_missing_artifact_zip_fails(tmp_path):
    manifest_path, artifact_path = write_release_package(tmp_path)
    artifact_path.unlink()

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Release artifact not found" in result.stderr


def test_tampered_artifact_zip_fails(tmp_path):
    manifest_path, artifact_path = write_release_package(tmp_path)
    artifact_path.write_text("tampered-content", encoding="utf-8")

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Release artifact hash verification failed." in result.stderr


def test_invalid_source_branch_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.source_branch": "feature/test"},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Invalid release source branch: feature/test" in result.stderr


def test_missing_build_repository_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.repository": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .build.repository" in result.stderr


def test_missing_build_commit_sha_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.commit_sha": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .build.commit_sha" in result.stderr


def test_missing_workflow_run_id_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.workflow_run_id": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .build.workflow_run_id" in result.stderr


def test_missing_workflow_run_number_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.workflow_run_number": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .build.workflow_run_number" in result.stderr


def test_missing_created_at_utc_fails(tmp_path):
    manifest_path, _ = write_release_package(
        tmp_path,
        overrides={"build.created_at_utc": None},
    )

    result = run_verify(manifest_path)

    assert result.returncode != 0
    assert "Required manifest field is missing or empty: .build.created_at_utc" in result.stderr