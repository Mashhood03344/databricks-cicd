import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/ci_resolve_context.sh")


def run_context(event_name, base_ref="", ref_name=""):
    result = subprocess.run(
        ["bash", str(SCRIPT), event_name, base_ref, ref_name],
        capture_output=True,
        text=True,
    )

    output = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            output[key] = value

    return result, output


def test_pr_to_dev_does_not_build_release():
    result, output = run_context("pull_request", "dev", "feature/test")

    assert result.returncode == 0
    assert output["branch"] == "dev"
    assert output["bundle_target"] == "dev"
    assert output["github_environment"] == "dev"
    assert output["should_build_release"] == "false"


def test_pr_to_qa_maps_to_uat_and_does_not_build_release():
    result, output = run_context("pull_request", "qa", "dev")

    assert result.returncode == 0
    assert output["branch"] == "qa"
    assert output["bundle_target"] == "uat"
    assert output["github_environment"] == "uat"
    assert output["should_build_release"] == "false"


def test_pr_to_main_maps_to_prod_and_does_not_build_release():
    result, output = run_context("pull_request", "main", "qa")

    assert result.returncode == 0
    assert output["branch"] == "main"
    assert output["bundle_target"] == "prod"
    assert output["github_environment"] == "prod"
    assert output["should_build_release"] == "false"


def test_push_to_dev_builds_release():
    result, output = run_context("push", "", "dev")

    assert result.returncode == 0
    assert output["branch"] == "dev"
    assert output["bundle_target"] == "dev"
    assert output["github_environment"] == "dev"
    assert output["should_build_release"] == "true"


def test_push_to_qa_does_not_build_release():
    result, output = run_context("push", "", "qa")

    assert result.returncode == 0
    assert output["branch"] == "qa"
    assert output["bundle_target"] == "uat"
    assert output["github_environment"] == "uat"
    assert output["should_build_release"] == "false"


def test_push_to_main_does_not_build_release():
    result, output = run_context("push", "", "main")

    assert result.returncode == 0
    assert output["branch"] == "main"
    assert output["bundle_target"] == "prod"
    assert output["github_environment"] == "prod"
    assert output["should_build_release"] == "false"


def test_unsupported_branch_fails():
    result, output = run_context("push", "", "random")

    assert result.returncode != 0
    assert "Unsupported branch: random" in result.stderr