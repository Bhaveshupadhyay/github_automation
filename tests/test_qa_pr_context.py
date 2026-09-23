"""Unit tests for resolving a dispatched pull request against the QA target registry."""
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from automation.domain.qa_target import PullRequestSkipped, QAPlatform, QATargetRegistry
from automation.services.github_pr_context_service import GitHubPullRequestContextService
import automation.qa_pr_context_cli as cli

REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTRY = QATargetRegistry.model_validate(
    {
        "targets": {
            "Acme/Web": {"platform": "web", "backend_repo": "acme/api", "slack_channel": "C123"},
            "acme/app": {"platform": "mobile", "backend_repo": "acme/api"},
        }
    }
)


def _pr(state: str = "open", head_repo: str = "Acme/Web", body: Any = "Backend: feat/x") -> dict:
    return {
        "state": state,
        "body": body,
        "head": {"sha": "abc1234def", "ref": "feat/x", "repo": {"full_name": head_repo} if head_repo else None},
        "base": {"ref": "main"},
    }


def _service(pr: dict) -> GitHubPullRequestContextService:
    service = GitHubPullRequestContextService(REGISTRY, token="t")
    service._get = lambda url: pr  # type: ignore[method-assign]
    return service


class TestRegistry:
    def test_lookup_ignores_case_like_github_does(self) -> None:
        assert REGISTRY.find("acme/web") is not None
        assert REGISTRY.find("ACME/APP").platform is QAPlatform.MOBILE
        assert REGISTRY.find("acme/other") is None

    def test_the_committed_registry_is_valid(self) -> None:
        """A malformed registry would fail every run at its first step."""
        raw = json.loads((REPO_ROOT / "contracts" / "qa-targets.json").read_text(encoding="utf-8"))
        registry = QATargetRegistry.model_validate(raw)
        assert registry.targets

    def test_unknown_fields_are_rejected(self) -> None:
        """A typo such as `require_lable` would otherwise silently fall back to the default."""
        with pytest.raises(ValueError):
            QATargetRegistry.model_validate({"targets": {"a/b": {"platform": "web", "backend_repo": "a/c", "typo": 1}}})


class TestResolve:
    def test_resolves_an_open_same_repository_pr(self) -> None:
        context = _service(_pr()).resolve("acme/web", 7, QAPlatform.WEB)
        assert context.head_sha == "abc1234def"
        assert context.head_ref == "feat/x"
        assert context.base_ref == "main"
        assert context.target.backend_repo == "acme/api"

    def test_a_missing_body_becomes_empty(self) -> None:
        assert _service(_pr(body=None)).resolve("acme/web", 7, QAPlatform.WEB).body == ""

    def test_unregistered_repository_is_skipped(self) -> None:
        with pytest.raises(PullRequestSkipped, match="not registered"):
            _service(_pr()).resolve("acme/unknown", 7, QAPlatform.WEB)

    def test_platform_mismatch_is_skipped(self) -> None:
        with pytest.raises(PullRequestSkipped, match="mobile pipeline"):
            _service(_pr()).resolve("acme/app", 7, QAPlatform.WEB)

    def test_closed_pr_is_skipped(self) -> None:
        with pytest.raises(PullRequestSkipped, match="closed"):
            _service(_pr(state="closed")).resolve("acme/web", 7, QAPlatform.WEB)

    def test_fork_pr_is_skipped(self) -> None:
        """Fork code must never run with this repository's secrets, even on a manual dispatch."""
        with pytest.raises(PullRequestSkipped, match="fork"):
            _service(_pr(head_repo="mallory/web")).resolve("acme/web", 7, QAPlatform.WEB)

    def test_deleted_fork_is_skipped(self) -> None:
        with pytest.raises(PullRequestSkipped, match="fork"):
            _service(_pr(head_repo="")).resolve("acme/web", 7, QAPlatform.WEB)


class TestCli:
    def _run(self, tmp_path: Path, pr: dict, repository: str = "acme/web") -> tuple[int, dict]:
        config = tmp_path / "targets.json"
        config.write_text(REGISTRY.model_dump_json(), encoding="utf-8")
        output = tmp_path / "out.txt"
        argv = [
            "qa-pr-context", "--repository", repository, "--pr", "7", "--platform", "web",
            "--config", str(config), "--body-file", str(tmp_path / "body.txt"), "--github-output", str(output),
        ]
        with patch.object(sys, "argv", argv), patch(
            "automation.services.github_pr_context_service.GitHubPullRequestContextService._get",
            lambda self, url: pr,
        ):
            code = cli.main()
        lines = output.read_text(encoding="utf-8").splitlines() if output.exists() else []
        return code, dict(line.split("=", 1) for line in lines)

    def test_writes_outputs_and_body(self, tmp_path: Path) -> None:
        code, outputs = self._run(tmp_path, _pr())
        assert code == 0
        assert outputs["skip"] == "false"
        assert outputs["head_sha"] == "abc1234def"
        assert outputs["backend_repo"] == "acme/api"
        assert outputs["slack_channel"] == "C123"
        assert (tmp_path / "body.txt").read_text(encoding="utf-8") == "Backend: feat/x"

    def test_skip_is_an_output_not_a_failure(self, tmp_path: Path) -> None:
        code, outputs = self._run(tmp_path, _pr(state="closed"))
        assert code == 0
        assert outputs["skip"] == "true"
        assert "closed" in outputs["skip_reason"]

    def test_api_failure_fails_the_step(self, tmp_path: Path) -> None:
        def boom(self: Any, url: str) -> Any:
            raise RuntimeError("GitHub API GET failed (404)")

        config = tmp_path / "targets.json"
        config.write_text(REGISTRY.model_dump_json(), encoding="utf-8")
        argv = ["qa-pr-context", "--repository", "acme/web", "--pr", "7", "--platform", "web",
                "--config", str(config), "--github-output", str(tmp_path / "out.txt")]
        with patch.object(sys, "argv", argv), patch(
            "automation.services.github_pr_context_service.GitHubPullRequestContextService._get", boom
        ):
            assert cli.main() == 1
