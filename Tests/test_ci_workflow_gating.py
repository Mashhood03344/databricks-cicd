from pathlib import Path
import re

WORKFLOW = Path(".github/workflows/databricks-bundle-ci.yml")


def read_workflow():
    return WORKFLOW.read_text()


def extract_job(workflow_text, job_name):
    pattern = rf"\n  {job_name}:\n(.*?)(?=\n  [a-zA-Z0-9_-]+:\n|\Z)"
    match = re.search(pattern, workflow_text, re.DOTALL)
    assert match, f"Job '{job_name}' not found"
    return match.group(1)


def test_push_trigger_only_allows_dev_branch():
    workflow = read_workflow()

    assert "push:" in workflow
    assert re.search(r"push:\s*\n\s+branches:\s*\n\s+- dev", workflow)
    assert not re.search(r"push:\s*\n\s+branches:\s*(?:\n\s+- .*)*qa", workflow)
    assert not re.search(r"push:\s*\n\s+branches:\s*(?:\n\s+- .*)*main", workflow)


def test_pull_request_validation_targets_dev_qa_main():
    workflow = read_workflow()

    assert "pull_request:" in workflow
    assert re.search(r"pull_request:\s*\n\s+branches:\s*(?:\n\s+- .*)*dev", workflow)
    assert re.search(r"pull_request:\s*\n\s+branches:\s*(?:\n\s+- .*)*qa", workflow)
    assert re.search(r"pull_request:\s*\n\s+branches:\s*(?:\n\s+- .*)*main", workflow)


def test_build_release_job_is_gated_by_should_build_release():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert "if: needs.resolve-context.outputs.should_build_release == 'true'" in build_release


def test_build_release_requires_context_and_validation():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert "needs:" in build_release
    assert "- resolve-context" in build_release
    assert "- validate" in build_release


def test_upload_artifact_only_exists_inside_build_release_job():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")
    validate = extract_job(workflow, "validate")
    resolve_context = extract_job(workflow, "resolve-context")

    assert "actions/upload-artifact@v4" in build_release
    assert "actions/upload-artifact@v4" not in validate
    assert "actions/upload-artifact@v4" not in resolve_context


def test_release_artifact_upload_happens_after_hash_verification():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    hash_step_index = build_release.index("Verify release artifact hash")
    upload_step_index = build_release.index("Upload immutable release artifact")

    assert hash_step_index < upload_step_index


def test_validate_job_does_not_create_or_upload_release_artifact():
    workflow = read_workflow()
    validate = extract_job(workflow, "validate")

    forbidden_terms = [
        "Create release artifact zip",
        "Generate external release_manifest.json",
        "Upload immutable release artifact",
        "actions/upload-artifact@v4",
    ]

    for term in forbidden_terms:
        assert term not in validate