"""Unit tests for resolving a dispatched pull request against the QA target registry."""
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from automation.domain.qa_target import BackendMode, PullRequestSkipped, QAPlatform, QATargetRegistry
from automation.services.github_pr_context_service import GitHubPullRequestContextService
import automation.qa_pr_context_cli as cli

REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTRY = QATargetRegistry.model_validate(
    {
        "targets": {
            "Acme/Web": {
                "platform": "web",
                "backend_repo": "acme/api",
                "backend_default_branch": "develop",
                "slack_channel": "C123",
                "dev_api_url": "https://dev-api.acme.test",
            },
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


class TestBackendChoice:
    """What the requester answered when asked which backend to test against."""

    WEB = REGISTRY.find("acme/web")
    APP = REGISTRY.find("acme/app")

    def _service(self, pr: dict | None = None) -> GitHubPullRequestContextService:
        return _service(pr or _pr(head_repo="acme/api"))

    def test_no_choice_resolves_a_branch_automatically(self) -> None:
        choice = self._service().resolve_backend("", self.WEB)
        assert choice.mode is BackendMode.AUTO
        assert choice.repository == "acme/api"

    def test_a_backend_pr_is_tested_at_its_head_commit(self) -> None:
        choice = self._service().resolve_backend("acme/api#3", self.WEB)
        assert choice.mode is BackendMode.PULL_REQUEST
        assert choice.repository == "acme/api"
        assert choice.ref == "abc1234def"
        assert choice.label == "acme/api#3 (feat/x)"

    def test_a_fork_backend_pr_is_refused(self) -> None:
        with pytest.raises(PullRequestSkipped, match="fork"):
            self._service(_pr(head_repo="mallory/api")).resolve_backend("acme/api#3", self.WEB)

    def test_a_closed_backend_pr_is_refused(self) -> None:
        with pytest.raises(PullRequestSkipped, match="closed"):
            self._service(_pr(state="closed", head_repo="acme/api")).resolve_backend("acme/api#3", self.WEB)

    def test_main_uses_the_registered_backends_default_branch(self) -> None:
        choice = self._service().resolve_backend("main", self.WEB)
        assert (choice.mode, choice.repository, choice.ref) == (BackendMode.BRANCH, "acme/api", "develop")

    def test_main_of_another_repository(self) -> None:
        choice = self._service().resolve_backend("main:acme/other-api", self.WEB)
        assert (choice.repository, choice.ref) == ("acme/other-api", "main")

    def test_dev_points_at_the_configured_dev_apis(self) -> None:
        choice = self._service().resolve_backend("dev", self.WEB)
        assert choice.mode is BackendMode.DEV
        assert choice.api_base_url == "https://dev-api.acme.test"
        assert choice.repository is None

    def test_dev_without_a_dev_url_is_refused(self) -> None:
        """Pointing the frontend at a missing URL would fail every journey confusingly."""
        with pytest.raises(PullRequestSkipped, match="dev_api_url"):
            self._service().resolve_backend("dev", self.APP)

    def test_an_unknown_choice_is_refused(self) -> None:
        with pytest.raises(PullRequestSkipped, match="not a backend choice"):
            self._service().resolve_backend("staging please", self.WEB)


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

    def test_a_chosen_backend_is_output_and_recorded_for_the_report(self, tmp_path: Path) -> None:
        config = tmp_path / "targets.json"
        config.write_text(REGISTRY.model_dump_json(), encoding="utf-8")
        output = tmp_path / "out.txt"
        branch = tmp_path / "branch.json"
        argv = [
            "qa-pr-context", "--repository", "acme/web", "--pr", "7", "--platform", "web",
            "--config", str(config), "--backend", "dev", "--branch-result-out", str(branch),
            "--github-output", str(output),
        ]
        with patch.object(sys, "argv", argv), patch(
            "automation.services.github_pr_context_service.GitHubPullRequestContextService._get",
            lambda self, url: _pr(),
        ):
            assert cli.main() == 0
        outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        assert outputs["backend_mode"] == "dev"
        assert outputs["dev_api_url"] == "https://dev-api.acme.test"
        assert outputs["backend_repo"] == ""
        assert json.loads(branch.read_text(encoding="utf-8"))["resolution_source"] == "dev_api"

    def test_auto_mode_leaves_the_branch_result_to_the_resolver(self, tmp_path: Path) -> None:
        code, outputs = self._run(tmp_path, _pr())
        assert outputs["backend_mode"] == "auto"
        assert not (tmp_path / "branch.json").exists()

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
