"""CLI entry point resolving the pull request a central QA run was dispatched for.

Usage:
    qa-pr-context --repository owner/name --pr 42 --platform web \
        [--config contracts/qa-targets.json] [--body-file pr-body.txt] [--github-output $GITHUB_OUTPUT]

Writes the resolved context as `key=value` lines to --github-output (stdout when unset),
and the PR description to --body-file. A pull request that must not be previewed is not
an error: `skip=true` and a reason are written, and the exit code is 0.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, TextIO

from pydantic import ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qa-pr-context")

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "contracts" / "qa-targets.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve a dispatched pull request for the QA pipeline.")
    parser.add_argument("--repository", required=True, help="Repository under test, as owner/name.")
    parser.add_argument("--pr", type=int, required=True, help="Pull request number.")
    parser.add_argument("--platform", required=True, choices=["web", "mobile"], help="Pipeline being run.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to the QA target registry.")
    parser.add_argument("--body-file", default=None, help="Where to write the PR description.")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"), help="Step output file.")
    return parser


def _write_outputs(outputs: Dict[str, str], destination: Optional[str]) -> None:
    def emit(stream: TextIO) -> None:
        for key, value in outputs.items():
            # Every value is a single line by construction; a newline would let one
            # value forge another output.
            stream.write(f"{key}={str(value).replace(chr(10), ' ')}\n")

    if destination:
        with open(destination, "a", encoding="utf-8") as stream:
            emit(stream)
    else:
        emit(sys.stdout)


def main() -> int:
    args = _build_parser().parse_args()

    from automation.core import get_pr_context_service
    from automation.domain.qa_target import PullRequestSkipped, QAPlatform, QATargetRegistry

    try:
        registry = QATargetRegistry.model_validate(json.loads(Path(args.config).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as e:
        logger.error(f"Could not load the QA target registry at {args.config}: {e}")
        return 1

    service = get_pr_context_service(registry)
    try:
        context = service.resolve(args.repository, args.pr, QAPlatform(args.platform))
    except PullRequestSkipped as e:
        logger.warning(f"Skipping: {e}")
        _write_outputs({"skip": "true", "skip_reason": str(e)}, args.github_output)
        return 0
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    if args.body_file:
        Path(args.body_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.body_file).write_text(context.body, encoding="utf-8")

    target = context.target
    _write_outputs(
        {
            "skip": "false",
            "repository": context.repository,
            "pr_number": str(context.number),
            "head_sha": context.head_sha,
            "head_ref": context.head_ref,
            "base_ref": context.base_ref,
            "backend_repo": target.backend_repo,
            "backend_default_branch": target.backend_default_branch,
            "slack_channel": target.slack_channel or "",
            "db_strategy": target.db_strategy,
            "startup_timeout_seconds": str(target.startup_timeout_seconds),
            "python_version": target.python_version,
            "frontend_url": target.frontend_url,
            "node_version": target.node_version,
            "api_base_url": target.api_base_url,
            "android_api_level": str(target.android_api_level),
            "java_version": target.java_version,
        },
        args.github_output,
    )
    logger.info(
        f"Resolved {context.repository}#{context.number} at {context.head_sha[:7]} "
        f"against {target.backend_repo}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
