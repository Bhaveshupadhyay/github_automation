"""Unit tests for the qa-publish CLI argument resolution."""
import json

import pytest

from automation.qa_publish_cli import _default_head_sha, _default_pr_number, main

HEAD_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MERGE_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("GITHUB_EVENT_PATH", "GITHUB_SHA", "GITHUB_REPOSITORY", "SLACK_CHANNEL"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def write_event(tmp_path, payload: dict) -> str:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestHeadShaResolution:
    def test_event_payload_head_sha_wins_over_github_sha(self, clean_env, tmp_path):
        """GITHUB_SHA is the synthetic merge commit on pull_request events."""
        clean_env.setenv("GITHUB_SHA", MERGE_SHA)
        clean_env.setenv(
            "GITHUB_EVENT_PATH",
            write_event(tmp_path, {"pull_request": {"head": {"sha": HEAD_SHA}}}),
        )

        assert _default_head_sha() == HEAD_SHA

    def test_falls_back_to_github_sha_without_an_event_payload(self, clean_env):
        clean_env.setenv("GITHUB_SHA", MERGE_SHA)

        assert _default_head_sha() == MERGE_SHA

    def test_falls_back_when_payload_has_no_pull_request(self, clean_env, tmp_path):
        clean_env.setenv("GITHUB_SHA", MERGE_SHA)
        clean_env.setenv("GITHUB_EVENT_PATH", write_event(tmp_path, {"ref": "refs/heads/main"}))

        assert _default_head_sha() == MERGE_SHA

    def test_malformed_payload_does_not_raise(self, clean_env, tmp_path):
        bad = tmp_path / "event.json"
        bad.write_text("{not json", encoding="utf-8")
        clean_env.setenv("GITHUB_EVENT_PATH", str(bad))
        clean_env.setenv("GITHUB_SHA", MERGE_SHA)

        assert _default_head_sha() == MERGE_SHA

    def test_returns_empty_when_nothing_is_available(self, clean_env):
        assert _default_head_sha() == ""


class TestPrNumberResolution:
    def test_reads_the_number_from_the_event_payload(self, clean_env, tmp_path):
        clean_env.setenv("GITHUB_EVENT_PATH", write_event(tmp_path, {"number": 42}))

        assert _default_pr_number() == 42

    def test_reads_a_nested_pull_request_number(self, clean_env, tmp_path):
        clean_env.setenv(
            "GITHUB_EVENT_PATH", write_event(tmp_path, {"pull_request": {"number": 7}})
        )

        assert _default_pr_number() == 7

    def test_returns_none_without_a_payload(self, clean_env):
        assert _default_pr_number() is None


class TestRequiredArguments:
    def _result_file(self, tmp_path) -> str:
        path = tmp_path / "result.json"
        path.write_text(
            json.dumps({"overall_outcome": "passed", "total_tests": 1, "passed": 1}), encoding="utf-8"
        )
        return str(path)

    def test_missing_sha_fails_rather_than_reusing_one_key(self, clean_env, tmp_path, monkeypatch):
        """An empty SHA would collapse every run onto one object key."""
        monkeypatch.setattr(
            "sys.argv",
            ["qa-publish", "--repo", "acme/web", "--pr", "42", "--test-result", self._result_file(tmp_path)],
        )

        assert main() == 1

    def test_missing_repo_fails(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["qa-publish", "--pr", "42", "--sha", HEAD_SHA, "--test-result", self._result_file(tmp_path)],
        )

        assert main() == 1

    def test_missing_pr_fails(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["qa-publish", "--repo", "acme/web", "--sha", HEAD_SHA, "--test-result", self._result_file(tmp_path)],
        )

        assert main() == 1

    def test_dry_run_renders_without_network_access(self, clean_env, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            [
                "qa-publish",
                "--repo", "acme/web",
                "--pr", "42",
                "--sha", HEAD_SHA,
                "--test-result", self._result_file(tmp_path),
                "--dry-run",
            ],
        )

        assert main() == 0
        assert "QA_Preview-passed" in capsys.readouterr().out
