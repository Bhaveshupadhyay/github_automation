"""CLI entry point for generating QA test plans from git diffs using Gemini analysis.

Usage:
    qa-test-gen [--commit-sha SHA] [--cache-dir DIR] [--fallback-dir DIR] [--output FILE]

Generates a structured test plan by analyzing the git diff between the current
HEAD and the target base branch. Uses Gemini Flash for semantic analysis and
supports commit-SHA-based caching for deterministic re-runs.
"""
import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qa-test-gen")


def get_git_diff(base_branch: str = "origin/main") -> str:
    """Extracts the git diff between HEAD and the target base branch."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base_branch}...HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"git diff failed (exit {result.returncode}): {result.stderr.strip()}")
            # Fallback to simple diff
            result = subprocess.run(
                ["git", "diff", "HEAD~1", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error("git diff command timed out after 30 seconds.")
        return ""
    except FileNotFoundError:
        logger.error("git binary not found. Ensure git is installed and on PATH.")
        return ""


def get_commit_sha() -> str:
    """Returns the current HEAD commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Generate QA test plans from git diffs using Gemini analysis.",
        prog="qa-test-gen",
    )
    parser.add_argument(
        "--commit-sha",
        default=None,
        help="Git commit SHA to use as cache key. Defaults to current HEAD.",
    )
    parser.add_argument(
        "--base-branch",
        default="origin/main",
        help="Base branch for diff comparison (default: origin/main).",
    )
    parser.add_argument(
        "--cache-dir",
        default=".qa-cache/test-plans",
        help="Directory for caching generated test plans (default: .qa-cache/test-plans).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path for the generated test plan JSON. Prints to stdout if not set.",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Additional component context to include with the diff analysis.",
    )

    args = parser.parse_args()

    from automation.core import get_diff_test_generator_service

    service = get_diff_test_generator_service()
    commit_sha = args.commit_sha or get_commit_sha()

    logger.info(f"Commit SHA: {commit_sha[:12]}")
    logger.info(f"Base branch: {args.base_branch}")
    logger.info(f"Cache directory: {args.cache_dir}")

    # Step 1: Check cache
    cached_plan = service.load_cached_plan(commit_sha, args.cache_dir)
    if cached_plan is not None:
        logger.info(
            f"✅ Cache HIT for SHA {commit_sha[:12]}. "
            f"Reusing cached plan ({cached_plan.source}, {len(cached_plan.journeys)} journeys)."
        )
        plan = cached_plan
    else:
        # Step 2: Get diff and generate
        logger.info(f"Cache MISS for SHA {commit_sha[:12]}. Generating new test plan...")
        diff = get_git_diff(args.base_branch)

        if not diff.strip():
            logger.warning("Empty diff detected. Generating baseline smoke test plan.")

        plan = service.generate_test_plan(
            diff=diff,
            commit_sha=commit_sha,
            component_context=args.context,
        )

        # Step 3: Cache the result
        service.save_cached_plan(plan, args.cache_dir)

    # Step 4: Output
    plan_json = plan.model_dump_json(indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(plan_json, encoding="utf-8")
        logger.info(f"Test plan written to: {output_path}")
    else:
        print(plan_json)

    # Summary
    logger.info(
        f"📋 Test Plan Summary: source={plan.source}, "
        f"journeys={len(plan.journeys)}, commit={commit_sha[:12]}"
    )
    for j in plan.journeys:
        logger.info(f"  → {j.name} ({len(j.actions)} actions, {len(j.assertions)} assertions)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
