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



def test_github_release_publish_only_exists_inside_build_release_job():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")
    validate = extract_job(workflow, "validate")
    resolve_context = extract_job(workflow, "resolve-context")

    assert "softprops/action-gh-release@v2" in build_release
    assert "softprops/action-gh-release@v2" not in validate
    assert "softprops/action-gh-release@v2" not in resolve_context


def test_workflow_does_not_use_github_actions_artifact_upload_for_release():
    workflow = read_workflow()

    assert "actions/upload-artifact@v4" not in workflow
    assert "Upload immutable release artifact" not in workflow


def test_github_release_publish_happens_after_hash_verification():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    hash_step_index = build_release.index("Verify release artifact hash")
    publish_step_index = build_release.index("Publish immutable GitHub release")

    assert hash_step_index < publish_step_index


def test_github_release_assets_include_zip_and_manifest():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    publish_step_index = build_release.index("Publish immutable GitHub release")
    publish_section = build_release[publish_step_index:]

    assert "softprops/action-gh-release@v2" in publish_section
    assert "tag_name: ${{ env.RELEASE_ID }}" in publish_section
    assert "${{ env.ARTIFACT_NAME }}" in publish_section
    assert "release_manifest.json" in publish_section
    assert "fail_on_unmatched_files: true" in publish_section


def test_release_asset_name_matches_artifact_name_contract():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert 'RELEASE_ASSET_NAME="${ARTIFACT_NAME}"' in build_release
    assert 'RELEASE_ASSET_NAME="release-${RELEASE_ID}"' not in build_release


def test_workflow_calls_release_hash_verification_script():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert "scripts/ci_verify_release_hash.sh release_manifest.json" in build_release


def test_workflow_does_not_use_inline_hash_verification_logic():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert "MANIFEST_HASH=" not in build_release
    assert "COMPUTED_HASH=" not in build_release


def test_release_zip_is_created_outside_release_package_directory():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert 'zip -r "../${ARTIFACT_NAME}" .' in build_release
    assert 'zip -r "./${ARTIFACT_NAME}" .' not in build_release


def test_build_release_does_not_run_on_workflow_dispatch():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    assert "should_build_release == 'true'" in build_release


def test_github_release_is_not_draft_and_is_prerelease():
    workflow = read_workflow()
    build_release = extract_job(workflow, "build-release")

    publish_step_index = build_release.index("Publish immutable GitHub release")
    publish_section = build_release[publish_step_index:]

    assert "draft: false" in publish_section
    assert "prerelease: true" in publish_section

    
def test_validate_job_does_not_create_or_upload_release_artifact():
    workflow = read_workflow()
    validate = extract_job(workflow, "validate")

    forbidden_terms = [
        "Create release artifact zip",
        "Generate external release_manifest.json",
        "Publish immutable GitHub release",
        "softprops/action-gh-release@v2",
        "actions/upload-artifact@v4",
    ]

    for term in forbidden_terms:
        assert term not in validate