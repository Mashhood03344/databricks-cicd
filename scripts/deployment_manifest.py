#!/usr/bin/env python3

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


VALID_ENVIRONMENTS = {"dev", "uat", "prod"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def required_previous_environment(environment: str):
    if environment == "dev":
        return None
    if environment == "uat":
        return "dev"
    if environment == "prod":
        return "uat"
    raise ValueError(f"Unsupported environment: {environment}")


def promotion_from_environment(environment: str):
    if environment == "dev":
        return None
    if environment == "uat":
        return "dev"
    if environment == "prod":
        return "uat"
    raise ValueError(f"Unsupported environment: {environment}")


def default_output_path(environment: str) -> str:
    return f"{environment}-deployment-manifest.json"


def build_manifest(args):
    environment = args.environment.lower()

    if environment not in VALID_ENVIRONMENTS:
        raise ValueError(f"Invalid environment: {environment}")

    now = utc_now()
    previous_env = required_previous_environment(environment)

    manifest = {
        "schema_version": "1.0",
        "deployment_id": f"github-run-{args.github_run_id}-{environment}",
        "environment": environment,
        "promotion": {
            "from_environment": promotion_from_environment(environment),
            "to_environment": environment,
            "required_previous_environment": previous_env,
        },
        "bundle": {
            "name": args.bundle_name,
            "target": args.bundle_target,
        },
        "git": {
            "repository": args.github_repository,
            "source_branch": args.source_branch,
            "target_branch": args.target_branch,
            "commit_sha": args.commit_sha,
            "commit_message": args.commit_message,
            "actor": args.github_actor,
        },
        "github_actions": {
            "workflow_name": args.github_workflow,
            "workflow_run_id": args.github_run_id,
            "workflow_run_number": args.github_run_number,
            "job_name": args.github_job,
            "event_name": args.github_event_name,
        },
        "evidence_storage": {
            "storage_type": args.evidence_storage_type,
            "artifact_name": args.evidence_artifact_name,
            "artifact_version": args.evidence_artifact_version,
            "artifact_generated_by_run_id": args.github_run_id,
            "artifact_generated_by_run_number": args.github_run_number,
            "artifact_retention_days": args.evidence_artifact_retention_days,
        },
        "databricks": {
            "workspace_target": args.workspace_target,
            "workspace_host": args.databricks_host,
            "authenticated_principal": args.authenticated_principal,
            "workspace_root_path": args.workspace_root_path,
        },
        "operation": {
            "action": "bundle_deploy",
            "status": "SUCCESS",
            "started_at": args.started_at,
            "completed_at": now,
        },
    }

    return manifest


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an environment-specific deployment manifest after a successful Databricks bundle deployment."
    )

    github_run_id = env("GITHUB_RUN_ID")
    github_run_number = env("GITHUB_RUN_NUMBER")

    parser.add_argument("--environment", required=True, help="Deployment environment: dev, uat, or prod")
    parser.add_argument("--bundle-name", required=True)
    parser.add_argument("--bundle-target", required=True)

    parser.add_argument("--workspace-target", required=True)
    parser.add_argument("--workspace-root-path", required=True)
    parser.add_argument("--authenticated-principal", required=True)

    parser.add_argument("--started-at", required=True)

    parser.add_argument("--source-branch", default=env("GITHUB_REF_NAME"))
    parser.add_argument("--target-branch", default="")
    parser.add_argument("--commit-sha", default=env("GITHUB_SHA"))
    parser.add_argument("--commit-message", default="")

    parser.add_argument("--github-repository", default=env("GITHUB_REPOSITORY"))
    parser.add_argument("--github-actor", default=env("GITHUB_ACTOR"))
    parser.add_argument("--github-workflow", default=env("GITHUB_WORKFLOW"))
    parser.add_argument("--github-run-id", default=github_run_id, required=not bool(github_run_id))
    parser.add_argument("--github-run-number", default=github_run_number, required=not bool(github_run_number))
    parser.add_argument("--github-job", default=env("GITHUB_JOB"))
    parser.add_argument("--github-event-name", default=env("GITHUB_EVENT_NAME"))

    parser.add_argument("--evidence-storage-type", default="github_actions_artifact")
    parser.add_argument("--evidence-artifact-name", default=None)
    parser.add_argument("--evidence-artifact-version", default="1.0")
    parser.add_argument("--evidence-artifact-retention-days", type=int, default=7)

    parser.add_argument("--databricks-host", default=env("DATABRICKS_HOST"))

    parser.add_argument(
        "--output-path",
        default=None,
        help="Output manifest path. Defaults to <environment>-deployment-manifest.json",
    )

    args = parser.parse_args()

    if args.evidence_artifact_name is None:
        args.evidence_artifact_name = f"{args.environment.lower()}-deployment-evidence"

    return args


def main():
    args = parse_args()
    manifest = build_manifest(args)

    environment = manifest["environment"]
    output_path = Path(args.output_path or default_output_path(environment))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    temp_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    temp_path.replace(output_path)

    print(f"Deployment manifest created: {output_path}")


if __name__ == "__main__":
    main()