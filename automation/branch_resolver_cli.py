"""CLI tool for cross-repository branch dependency resolution in CI/CD workflows."""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from automation.core.dependency import get_branch_resolver_service


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve backend repository branch for an incoming frontend/mobile PR."
    )
    parser.add_argument(
        "--source-branch",
        required=True,
        help="Incoming frontend or mobile feature branch name (e.g. feat/cart-redesign)",
    )
    parser.add_argument(
        "--backend-repo-url",
        required=True,
        help="Target backend repository URL or path",
    )
    parser.add_argument(
        "--pr-body",
        default="",
        help="Pull request description body text",
    )
    parser.add_argument(
        "--pr-body-file",
        help="Path to file containing pull request description text (preferred for multiline markdown)",
    )
    parser.add_argument(
        "--default-branch",
        default="dev",
        help="Fallback target branch (default: dev)",
    )
    parser.add_argument(
        "--new-backend-routes",
        action="store_true",
        help="Flag indicating the PR diff introduces unmerged backend routes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output resolution result as JSON",
    )
    parser.add_argument(
        "--output-env",
        action="store_true",
        help="Write RESOLVED_BACKEND_BRANCH to $GITHUB_ENV if present",
    )

    args = parser.parse_args()

    pr_body: Optional[str] = args.pr_body
    if args.pr_body_file:
        body_file = Path(args.pr_body_file)
        if body_file.exists():
            pr_body = body_file.read_text(encoding="utf-8")
        else:
            print(f"⚠️ Warning: PR body file not found: {body_file}", file=sys.stderr)

    resolver = get_branch_resolver_service()

    try:
        result = resolver.resolve_branch(
            pr_body=pr_body,
            source_branch=args.source_branch,
            backend_repo_url=args.backend_repo_url,
            default_branch=args.default_branch,
            new_backend_routes_detected=args.new_backend_routes,
        )

        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print(f"✅ Resolved Backend Branch: {result.target_branch}")
            print(f"   - Resolution Strategy: {result.resolution_source.value}")
            print(f"   - Target Repo: {result.target_repo_url}")
            if result.clarification_needed:
                print(f"   - ⚠️ Clarification Needed: Yes")
                if result.clarification_message:
                    print(f"   - Message:\n{result.clarification_message}")

        if args.output_env:
            github_env_path = os.environ.get("GITHUB_ENV")
            if github_env_path:
                with open(github_env_path, "a", encoding="utf-8") as f:
                    f.write(f"RESOLVED_BACKEND_BRANCH={result.target_branch}\n")
                    f.write(f"CLARIFICATION_NEEDED={'true' if result.clarification_needed else 'false'}\n")
                    f.write(f"RESOLUTION_SOURCE={result.resolution_source.value}\n")
                print(f"ℹ️ Exported RESOLVED_BACKEND_BRANCH={result.target_branch} to $GITHUB_ENV")
            else:
                print(f"RESOLVED_BACKEND_BRANCH={result.target_branch}")

        sys.exit(0)

    except Exception as e:
        print(f"❌ Branch Resolution Error:\n   {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
