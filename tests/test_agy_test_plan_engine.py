"""Unit tests for AgyTestPlanEngine and the agy-first order of the diff test generator."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from automation.interfaces.test_plan_engine_interface import ITestPlanEngine
from automation.services.agy_test_plan_engine import INPUT_DIR_NAME, AgyTestPlanEngine
from automation.services.gemini_diff_test_generator_service import (
    GEMINI_TEST_PLAN_SCHEMA,
    GeminiDiffTestGeneratorService,
)

PLAN = {
    "has_ui_changes": True,
    "summary": "Adds an admin panel.",
    "journeys": [
        {
            "name": "Open the admin panel",
            "entry_route": "/admin",
            "actions": [{"action_type": "click", "target": "Add Post", "description": "Open the form"}],
            "assertions": [{"type": "visible_text", "target": "New Post", "description": "Form opens"}],
        }
    ],
}


def envelope(**fields) -> str:
    body = {"conversation_id": "c", "status": "SUCCESS", "response": "", "num_turns": 1}
    body.update(fields)
    return json.dumps(body)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repository with one commit, so the engine's worktree can be created."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "App.jsx").write_text('<Route path="/admin" />\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        check=True,
    )
    return tmp_path


class FakeAgy:
    """Stands in for the agy process while letting git commands run for real."""

    def __init__(self, stdout: str = "", returncode: int = 0, raises: Exception = None):
        self.stdout = stdout
        self.returncode = returncode
        self.raises = raises
        self.calls = []
        self.seen_inputs = {}

    def __call__(self, cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.run(cmd, **kwargs)
        self.calls.append((cmd, kwargs))
        cwd = Path(kwargs["cwd"])
        for f in (cwd / INPUT_DIR_NAME).iterdir():
            self.seen_inputs[f.name] = f.read_text()
        # agy may write files; they must not reach the checkout under test.
        (cwd / "App.jsx").write_text("edited by agy\n")
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="boom")


def make_engine(repo: Path, fake: FakeAgy) -> AgyTestPlanEngine:
    return AgyTestPlanEngine(repo_dir=str(repo), binary_finder=lambda: "/bin/agy", run=fake)


class TestAgyEngine:
    def test_returns_structured_output(self, repo):
        fake = FakeAgy(stdout=envelope(structured_output=PLAN))

        plan = make_engine(repo, fake).generate_plan_json("RULES", "diff --git a b", "Declared routes:\n- /admin", {"type": "object"})

        assert plan == PLAN
        cmd, kwargs = fake.calls[0]
        assert cmd[:2] == ["/bin/agy", "--print"]
        assert "RULES" in cmd[2]
        assert "--json-schema" in cmd and "--dangerously-skip-permissions" in cmd
        assert fake.seen_inputs["diff.patch"] == "diff --git a b"
        assert "/admin" in fake.seen_inputs["context.md"]

    def test_runs_in_a_throwaway_worktree_and_leaves_the_checkout_untouched(self, repo):
        fake = FakeAgy(stdout=envelope(structured_output=PLAN))

        make_engine(repo, fake).generate_plan_json("RULES", "d", "", {})

        _, kwargs = fake.calls[0]
        assert Path(kwargs["cwd"]).resolve() != repo.resolve()
        assert not Path(kwargs["cwd"]).exists()
        assert (repo / "App.jsx").read_text() == '<Route path="/admin" />\n'
        worktrees = subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True)
        assert len(worktrees.stdout.strip().splitlines()) == 1

    def test_falls_back_to_the_text_response(self, repo):
        fake = FakeAgy(stdout=envelope(response=json.dumps(PLAN)))

        assert make_engine(repo, fake).generate_plan_json("R", "d", "", {}) == PLAN

    def test_ignores_status_lines_before_the_envelope(self, repo):
        fake = FakeAgy(stdout="[agy] something\n" + envelope(structured_output=PLAN))

        assert make_engine(repo, fake).generate_plan_json("R", "d", "", {}) == PLAN

    @pytest.mark.parametrize(
        "fake, message",
        [
            (FakeAgy(stdout=envelope()), "empty response"),
            (FakeAgy(stdout=envelope(status="ERROR")), "status"),
            (FakeAgy(stdout="not json"), "no JSON"),
            (FakeAgy(returncode=1), "exited with code 1"),
            (FakeAgy(raises=subprocess.TimeoutExpired("agy", 1)), "did not finish"),
        ],
    )
    def test_failures_raise(self, repo, fake, message):
        with pytest.raises(RuntimeError, match=message):
            make_engine(repo, fake).generate_plan_json("R", "d", "", {})
        assert (repo / "App.jsx").read_text() == '<Route path="/admin" />\n'

    def test_unavailable_without_the_binary(self, repo):
        assert AgyTestPlanEngine(repo_dir=str(repo), binary_finder=lambda: None).is_available() is False


class FakeEngine(ITestPlanEngine):
    def __init__(self, result=None, error=None, available=True):
        self.result, self.error, self.available = result, error, available
        self.calls = 0

    name = "agy"
    cache_identity = "agy:test"

    def is_available(self):
        return self.available

    def generate_plan_json(self, system_prompt, diff, component_context, schema):
        self.calls += 1
        assert schema is GEMINI_TEST_PLAN_SCHEMA
        if self.error:
            raise self.error
        return self.result


def api_client(response_json: dict) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps(response_json)
    return client


def service(engine, client) -> GeminiDiffTestGeneratorService:
    return GeminiDiffTestGeneratorService(
        api_key="k", gemini_model="gemini-2.0-flash", genai_client=client, primary_engine=engine, sleep=lambda s: None
    )


class TestAgyFirstOrder:
    def test_agy_plan_is_used_without_calling_the_api(self):
        engine, client = FakeEngine(result=PLAN), api_client({"has_ui_changes": False, "summary": ""})

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert plan.source == "agy"
        assert plan.journeys[0].entry_route == "/admin"
        client.models.generate_content.assert_not_called()

    def test_agy_failure_falls_back_to_the_api(self):
        engine, client = FakeEngine(error=RuntimeError("quota")), api_client(PLAN)

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert engine.calls == 1
        assert plan.source == "gemini"

    def test_unusable_agy_plan_falls_back_to_the_api(self):
        engine, client = FakeEngine(result={"has_ui_changes": True, "summary": "s", "journeys": []}), api_client(PLAN)

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert plan.source == "gemini"

    def test_agy_no_ui_changes_verdict_is_kept(self):
        engine, client = FakeEngine(result={"has_ui_changes": False, "summary": "docs only"}), api_client(PLAN)

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert plan.source == "fallback_baseline"
        assert plan.degraded is False
        client.models.generate_content.assert_not_called()

    def test_unavailable_agy_is_skipped(self):
        engine, client = FakeEngine(result=PLAN, available=False), api_client(PLAN)

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert engine.calls == 0
        assert plan.source == "gemini"

    def test_both_failing_gives_a_degraded_fallback(self):
        engine = FakeEngine(error=RuntimeError("down"))
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("API down")

        plan = service(engine, client).generate_test_plan(diff="diff", commit_sha="sha")

        assert plan.source == "fallback_baseline"
        assert plan.degraded is True

    def test_cache_key_covers_the_engine(self):
        client = api_client(PLAN)
        with_agy = service(FakeEngine(), client).cache_key("diff")
        without = service(None, client).cache_key("diff")

        assert with_agy != without
