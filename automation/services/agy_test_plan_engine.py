"""Test plan engine that runs the Antigravity CLI (agy) on the Pro plan login."""
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from automation.domain.constants import DEFAULT_AGY_MODEL
from automation.interfaces.test_plan_engine_interface import ITestPlanEngine
from automation.services.agy_binary import find_agy_binary

logger = logging.getLogger(__name__)

# agy answers a trivial prompt in one to two minutes; a feature diff at high effort takes longer.
AGY_PRINT_TIMEOUT = "8m0s"
AGY_PROCESS_TIMEOUT_SECONDS = 9 * 60

# Written inside the throwaway worktree, where agy reads them. A diff can exceed Linux's
# 128 KiB limit on a single argument, so it cannot be passed in the prompt.
INPUT_DIR_NAME = ".qa-plan-input"

AGY_TASK_PROMPT = """{system_prompt}

This directory is a checkout of the app at the pull request's head.
- The pull request's full git diff is in {input_dir}/diff.patch. Read all of it.
{context_line}- Read the app's source here when a diff alone leaves a route, a visible label or an option text
  uncertain, and copy what the source actually renders.
- Only read files. Do not create, edit or delete files, and do not run the app or install anything.

Reply with the test plan as JSON matching the schema, and nothing else."""


class AgyTestPlanEngine(ITestPlanEngine):
    """Writes the plan with agy in a throwaway git worktree of the checkout.

    agy runs with permissions auto-approved so it can read the app's source, so it never
    runs in the checkout under test: anything it writes lands in the worktree, which is
    removed afterwards.
    """

    def __init__(
        self,
        repo_dir: str = ".",
        model: str = DEFAULT_AGY_MODEL,
        effort: str = "high",
        binary_finder: Callable[[], Optional[str]] = find_agy_binary,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self._repo_dir = repo_dir
        self._model = model
        self._effort = effort
        self._binary_finder = binary_finder
        self._run = run

    @property
    def name(self) -> str:
        return "agy"

    @property
    def cache_identity(self) -> str:
        return f"agy:{self._model}:{self._effort}"

    def is_available(self) -> bool:
        return self._binary_finder() is not None

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return self._run(
            ["git", "-C", self._repo_dir, *args], capture_output=True, text=True, timeout=60
        )

    @staticmethod
    def _parse_output(stdout: str) -> dict:
        """Pull the plan out of agy's `--output-format json` envelope.

        agy can print status lines (such as a timeout notice) before the envelope, so the
        last line that parses as a JSON object is taken.
        """
        envelope = None
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                envelope = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if not isinstance(envelope, dict):
            raise RuntimeError("agy printed no JSON result.")

        if envelope.get("status") != "SUCCESS":
            raise RuntimeError(f"agy finished with status {envelope.get('status')!r}.")

        plan = envelope.get("structured_output")
        if not isinstance(plan, dict):
            # A run cut off by the print timeout reports SUCCESS with an empty response.
            response = (envelope.get("response") or "").strip()
            if not response:
                raise RuntimeError("agy returned an empty response, likely cut off by its print timeout.")
            try:
                plan = json.loads(response)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"agy's response was not JSON: {e}") from e
        if not isinstance(plan, dict):
            raise RuntimeError("agy's response was not a JSON object.")
        return plan

    def generate_plan_json(self, system_prompt: str, diff: str, component_context: str, schema: dict) -> dict:
        binary = self._binary_finder()
        if binary is None:
            raise RuntimeError("agy is not installed.")

        tmp_root = Path(tempfile.mkdtemp(prefix="qa-plan-agy-"))
        worktree = tmp_root / "app"
        added = self._git("worktree", "add", "--detach", str(worktree), "HEAD")
        if added.returncode != 0:
            shutil.rmtree(tmp_root, ignore_errors=True)
            raise RuntimeError(f"Could not create a worktree for agy: {added.stderr.strip()}")

        try:
            input_dir = worktree / INPUT_DIR_NAME
            input_dir.mkdir()
            (input_dir / "diff.patch").write_text(diff, encoding="utf-8")
            schema_path = input_dir / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            context_line = ""
            if component_context.strip():
                (input_dir / "context.md").write_text(component_context, encoding="utf-8")
                context_line = (
                    f"- More context, including the routes the app declares, is in {INPUT_DIR_NAME}/context.md.\n"
                )

            prompt = AGY_TASK_PROMPT.format(
                system_prompt=system_prompt.strip(), input_dir=INPUT_DIR_NAME, context_line=context_line
            )
            cmd = [
                binary, "--print", prompt,
                "--dangerously-skip-permissions",
                "--disable-slash-commands",
                "--add-dir", ".",
                "--model", self._model,
                "--effort", self._effort,
                "--output-format", "json",
                "--json-schema", str(schema_path),
                "--print-timeout", AGY_PRINT_TIMEOUT,
            ]
            logger.info(f"Asking agy ({self._model}, --effort {self._effort}) for the test plan...")
            try:
                result = self._run(
                    cmd, cwd=str(worktree), capture_output=True, text=True, timeout=AGY_PROCESS_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"agy did not finish within {AGY_PROCESS_TIMEOUT_SECONDS}s.") from e
            except OSError as e:
                raise RuntimeError(f"agy could not be started: {e}") from e

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-500:]
                raise RuntimeError(f"agy exited with code {result.returncode}: {detail}")

            return self._parse_output(result.stdout)
        finally:
            self._git("worktree", "remove", "--force", str(worktree))
            shutil.rmtree(tmp_root, ignore_errors=True)
