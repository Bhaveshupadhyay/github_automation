"""Resolves a dispatched pull request against the QA target registry via the GitHub API."""
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from automation.domain.qa_target import (
    PullRequestContext,
    PullRequestSkipped,
    QAPlatform,
    QATargetRegistry,
)
from automation.interfaces.pr_context_interface import IPullRequestContextService

logger = logging.getLogger("automation.pr_context")

GITHUB_API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 15


class GitHubPullRequestContextService(IPullRequestContextService):
    """Fetches the pull request fresh rather than trusting the dispatch payload.

    The dispatch carries only a repository and a number. Everything else — the head
    commit, the branches, the description — is read from the API at run time, so a
    manual re-run and a webhook-triggered run resolve identically, and a push that
    landed after the dispatch is tested rather than silently skipped.
    """

    def __init__(
        self,
        registry: QATargetRegistry,
        token: Optional[str] = None,
        api_base: str = GITHUB_API_BASE,
    ):
        self._registry = registry
        self._token = token or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
        self._api_base = api_base.rstrip("/")

    def _get(self, url: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qa-preview-bot",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"GitHub API GET {url} failed ({e.code}): {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"GitHub API GET {url} unreachable: {e.reason}") from e

    def resolve(self, repository: str, pr_number: int, platform: QAPlatform) -> PullRequestContext:
        target = self._registry.find(repository)
        if target is None:
            raise PullRequestSkipped(f"{repository} is not registered in contracts/qa-targets.json.")
        if target.platform != platform:
            raise PullRequestSkipped(
                f"{repository} is registered for the {target.platform.value} pipeline, not {platform.value}."
            )

        pr = self._get(f"{self._api_base}/repos/{repository}/pulls/{pr_number}")

        if pr.get("state") != "open":
            raise PullRequestSkipped(f"{repository}#{pr_number} is {pr.get('state')}, not open.")

        # A fork's code would run here with this repository's secrets. The webhook
        # already filters forks; this is the check a manual dispatch cannot bypass.
        head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or ""
        if head_repo.lower() != repository.lower():
            raise PullRequestSkipped(
                f"{repository}#{pr_number} comes from a fork ({head_repo or 'deleted repository'}); "
                "fork code is never run with this repository's secrets."
            )

        return PullRequestContext(
            repository=repository,
            number=pr_number,
            head_sha=pr["head"]["sha"],
            head_ref=pr["head"]["ref"],
            base_ref=pr["base"]["ref"],
            body=pr.get("body") or "",
            target=target,
        )
