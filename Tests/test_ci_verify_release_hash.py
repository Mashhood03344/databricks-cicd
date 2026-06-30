import hashlib
import json
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/ci_verify_release_hash.sh")


def sha256_hash(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(path, artifact_hash):
    manifest = {
        "release": {
            "artifact_hash": artifact_hash
        }
    }

    path.write_text(json.dumps(manifest))


def run_verify(manifest_path, artifact_path):
    return subprocess.run(
        ["bash", str(SCRIPT), str(manifest_path), str(artifact_path)],
        capture_output=True,
        text=True,
    )


def test_valid_manifest_and_artifact_passes(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "release_manifest.json"

    artifact.write_text("release-content")
    write_manifest(manifest, sha256_hash(artifact))

    result = run_verify(manifest, artifact)

    assert result.returncode == 0
    assert "Release artifact hash verification passed." in result.stdout


def test_tampered_artifact_fails(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "release_manifest.json"

    artifact.write_text("original-content")
    write_manifest(manifest, sha256_hash(artifact))

    artifact.write_text("tampered-content")

    result = run_verify(manifest, artifact)

    assert result.returncode != 0
    assert "Release artifact hash verification failed." in result.stderr


def test_missing_manifest_fails(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "missing_release_manifest.json"

    artifact.write_text("release-content")

    result = run_verify(manifest, artifact)

    assert result.returncode != 0
    assert "Release manifest not found" in result.stderr


def test_missing_artifact_fails(tmp_path):
    artifact = tmp_path / "missing_release.zip"
    manifest = tmp_path / "release_manifest.json"

    write_manifest(manifest, "sha256:dummy")

    result = run_verify(manifest, artifact)

    assert result.returncode != 0
    assert "Release artifact not found" in result.stderr


def test_corrupt_manifest_fails(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "release_manifest.json"

    artifact.write_text("release-content")
    manifest.write_text("{ invalid json")

    result = run_verify(manifest, artifact)

    assert result.returncode != 0


def test_missing_artifact_hash_fails(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "release_manifest.json"

    artifact.write_text("release-content")
    manifest.write_text(json.dumps({"release": {}}))

    result = run_verify(manifest, artifact)

    assert result.returncode != 0
    assert "release.artifact_hash is missing or empty" in result.stderr


def test_empty_artifact_hash_fails(tmp_path):
    artifact = tmp_path / "release.zip"
    manifest = tmp_path / "release_manifest.json"

    artifact.write_text("release-content")
    write_manifest(manifest, "")

    result = run_verify(manifest, artifact)

    assert result.returncode != 0
    assert "release.artifact_hash is missing or empty" in result.stderr