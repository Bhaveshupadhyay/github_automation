"""Structural tests for the assembled QA workflows.

The guardrails — concurrency, job timeouts, fork safety, secret isolation, ordering, and
the `if: always()` reporting path — are properties of the YAML, so they are asserted
against the parsed YAML rather than reviewed by eye. Each test names the failure it
excludes.

The pipeline runs centrally in this repository: a dispatch names a pull request in a
registered repository, and three jobs resolve it, run its code, and publish the result.
"""
import json
import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
REGISTRY_PATH = REPO_ROOT / "contracts" / "qa-targets.json"

QA_WORKFLOWS = {"qa-web-preview.yml": "web", "qa-mobile-preview.yml": "mobile"}
R2_SECRETS = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    """Return the `on:` block. PyYAML reads the bare key `on` as the boolean True."""
    return document.get("on", document.get(True, {}))


def _job(document: dict, name: str) -> dict:
    return document["jobs"][name]


def _step_index(job: dict, fragment: str) -> int:
    """Index of the first step whose name contains `fragment`."""
    for index, step in enumerate(job["steps"]):
        if fragment.lower() in str(step.get("name", "")).lower():
            return index
    raise AssertionError(f"No step named like {fragment!r}. Steps: {[s.get('name') for s in job['steps']]}")


def _step(job: dict, fragment: str) -> dict:
    return job["steps"][_step_index(job, fragment)]


def _plan_job(document: dict) -> dict:
    """The job that writes the test plan: `plan` where agy runs, else the preview itself."""
    return document["jobs"].get("plan") or _job(document, "qa-preview")


def _workflows():
    for name, platform in QA_WORKFLOWS.items():
        yield name, platform, _load(WORKFLOW_DIR / name)


class TestWorkflowsParse(unittest.TestCase):
    """Every workflow file must be valid YAML with the expected top-level shape."""

    def test_all_workflows_parse(self) -> None:
        for path in WORKFLOW_DIR.glob("*.yml"):
            with self.subTest(workflow=path.name):
                document = _load(path)
                self.assertIn("jobs", document)
                self.assertTrue(_triggers(document), "Workflow declares no trigger.")


class TestCentralTriggers(unittest.TestCase):
    """The pipeline runs here, for pull requests opened elsewhere."""

    def test_triggered_only_by_dispatch(self) -> None:
        """`workflow_call` would run the pipeline inside the caller's repository, with
        its secrets; `pull_request` would run it against this repository, which has no
        application to preview."""
        for name, platform, document in _workflows():
            with self.subTest(workflow=name):
                triggers = _triggers(document)
                self.assertEqual(sorted(triggers.keys()), ["repository_dispatch", "workflow_dispatch"])
                self.assertEqual(triggers["repository_dispatch"]["types"], [f"qa_{platform}_preview"])

    def test_manual_rerun_names_the_pull_request(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                inputs = _triggers(document)["workflow_dispatch"]["inputs"]
                self.assertTrue(inputs["repository"]["required"])
                self.assertTrue(inputs["pr_number"]["required"])

    def test_every_registered_platform_has_a_dispatch_target(self) -> None:
        """The Worker dispatches `qa_<platform>_preview`; a platform with no workflow
        listening would drop its pull requests silently."""
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        listened = {
            _triggers(document)["repository_dispatch"]["types"][0] for _, _, document in _workflows()
        }
        for repository, target in registry["targets"].items():
            with self.subTest(repository=repository):
                self.assertIn(f"qa_{target['platform']}_preview", listened)

    def test_dispatch_values_reach_scripts_only_through_the_environment(self) -> None:
        """Interpolated into `run:`, a crafted repository name would execute."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                for job_name, job in document["jobs"].items():
                    for step in job["steps"]:
                        run = str(step.get("run", ""))
                        self.assertNotIn("client_payload", run, f"{job_name}: {step.get('name')}")
                        self.assertNotRegex(run, r"\$\{\{\s*inputs\.", f"{job_name}: {step.get('name')}")
                resolve = _step(_job(document, "resolve"), "Resolve the pull request")
                self.assertIn("=~", resolve["run"], "Dispatch values must be validated before use.")


class TestJobStructure(unittest.TestCase):
    """resolve → qa-preview → publish, with the skip decision made once."""

    def test_the_preview_runs_only_for_a_resolved_pull_request(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                job = _job(document, "qa-preview")
                self.assertIn(job["needs"], ("resolve", ["resolve", "plan"]))
                self.assertIn("needs.resolve.outputs.skip == 'false'", job["if"])

    def test_publishing_runs_after_a_failed_preview_but_not_a_cancelled_one(self) -> None:
        """The recording of a failure is the most valuable thing a red run produces. A run
        cancelled by a newer request must stay silent: its "stopped early" notice would
        contradict the run that superseded it, and `always()` would still post it."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                job = _job(document, "publish")
                self.assertEqual(sorted(job["needs"]), ["qa-preview", "resolve"])
                self.assertIn("!cancelled()", job["if"])
                self.assertNotIn("always()", job["if"])
                self.assertIn("needs.resolve.outputs.skip == 'false'", job["if"])

    def test_a_failed_resolve_is_answered(self) -> None:
        """A failure before the skip decision leaves both later jobs skipped."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                notice = _step(_job(document, "resolve"), "could not start")
                self.assertEqual(notice["if"], "failure()")
                self.assertIn("chat.postMessage", notice["run"])

    def test_a_skipped_pull_request_is_explained(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                explain = _step(_job(document, "resolve"), "Explain why no preview")
                self.assertIn("skip == 'true'", explain["if"])
                self.assertIn("GITHUB_STEP_SUMMARY", explain["run"])

    def test_results_are_handed_from_the_preview_to_the_publisher(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                handoff = _step(_job(document, "qa-preview"), "Hand the results")
                self.assertIn("always()", handoff["if"])
                collect = _step(_job(document, "publish"), "Collect the test results")
                self.assertEqual(handoff["with"]["name"], collect["with"]["name"])


class TestSlackRoundTrip(unittest.TestCase):
    """QA is requested in a Slack thread, so every outcome is answered in that thread."""

    def test_results_reply_in_the_requesting_thread(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                env = _step(_job(document, "publish"), "Publish the QA comment")["env"]
                self.assertIn("client_payload.slack_thread_ts", env["SLACK_THREAD"])
                # The request's channel wins; the registry's is the fallback for manual re-runs.
                self.assertTrue(env["SLACK_CHANNEL"].startswith("${{ github.event.client_payload.slack_channel ||"))

    def test_a_run_that_never_reached_the_tests_still_reports(self) -> None:
        """Without it, a startup failure leaves the requester waiting in silence."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                publish = _job(document, "publish")
                early = _step(publish, "stopped early")
                self.assertIn("hashFiles('qa-results/run.json') == ''", early["if"])
                self.assertLess(_step_index(publish, "stopped early"), _step_index(publish, "Publish the QA comment"))

    def test_a_skipped_request_is_answered(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                explain = _step(_job(document, "resolve"), "Explain why no preview")
                self.assertIn("chat.postMessage", explain["run"])


class TestBackendChoice(unittest.TestCase):
    """The requester chooses the backend: a backend PR, a repository's main, or the dev APIs."""

    def test_the_choice_is_validated_and_passed_to_the_resolver(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                self.assertIn("client_payload.backend", document["env"]["BACKEND_CHOICE"])
                self.assertIn("backend", _triggers(document)["workflow_dispatch"]["inputs"])
                run = _step(_job(document, "resolve"), "Resolve the pull request")["run"]
                self.assertIn('--backend "$BACKEND_CHOICE"', run)
                self.assertIn('[[ "$BACKEND_CHOICE" =~', run)

    def test_the_branch_resolver_runs_only_when_nothing_was_chosen(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                resolver = _step(_job(document, "resolve"), "Resolve the backend branch")
                self.assertIn("backend_mode == 'auto'", resolver["if"])
                # A chosen PR or branch wins over the resolver's branch.
                self.assertIn("steps.pr.outputs.backend_ref ||", _job(document, "resolve")["outputs"]["backend_branch"])

    def test_dev_mode_never_clones_or_decrypts_a_backend(self) -> None:
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            for fragment in ("Checkout backend", "Check backend secret drift", "Decrypt the QA environment"):
                with self.subTest(workflow=name, step=fragment):
                    self.assertIn("backend_mode != 'dev'", _step(job, fragment)["if"])

    def test_web_dev_mode_starts_only_the_frontend_against_the_dev_apis(self) -> None:
        job = _job(_load(WORKFLOW_DIR / "qa-web-preview.yml"), "qa-preview")
        start = _step(job, "await health")
        self.assertIn("--no-backend --api-base-url \"$DEV_API_URL\"", start["run"])


class TestSecretIsolation(unittest.TestCase):
    """The pull request's code must never share a runner with credentials that can
    write to it: a malicious step could read them from a later step's process."""

    def test_storage_credentials_reach_only_the_publish_step(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                for job_name, job in document["jobs"].items():
                    for step in job["steps"]:
                        run = str(step.get("run", ""))
                        self.assertFalse("R2_" in run and "GITHUB_ENV" in run, step.get("name"))
                        if not (job_name == "publish" and step.get("name") == "Publish the QA comment"):
                            self.assertNotIn("secrets.R2_", str(step.get("env", "")), step.get("name"))
                publish = _step(_job(document, "publish"), "Publish the QA comment")
                for key in R2_SECRETS:
                    self.assertEqual(publish["env"][key], f"${{{{ secrets.{key} }}}}")

    def test_the_preview_job_never_references_the_write_token(self) -> None:
        """GitHub sends every secret a job references to its runner, where the PR's code
        has sudo and can read the runner's memory. Not persisting a checkout credential
        is not enough; the preview job must not reference the PAT at all."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                job = _job(document, "qa-preview")
                self.assertNotIn("PAT_TOKEN", str(job))
                for step in job["steps"]:
                    if "actions/checkout" in str(step.get("uses", "")) and "token" in step.get("with", {}):
                        self.assertEqual(step["with"]["token"], "${{ secrets.QA_READ_TOKEN || github.token }}")

    def test_no_checkout_leaves_a_token_on_disk(self) -> None:
        """actions/checkout writes its token into .git/config unless told not to, where
        the pull request's own code could read it."""
        for name, _, document in _workflows():
            for job_name, job in document["jobs"].items():
                for step in job["steps"]:
                    if "actions/checkout" not in str(step.get("uses", "")):
                        continue
                    with self.subTest(workflow=name, job=job_name, step=step.get("name")):
                        self.assertIs(step["with"]["persist-credentials"], False)

    def test_decryption_exports_nothing_to_the_job(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                decrypt = _step(_job(document, "qa-preview"), "Decrypt the QA environment")
                self.assertNotIn("GITHUB_ENV", decrypt["run"])

    def test_the_run_token_cannot_write(self) -> None:
        """This run's own token is scoped to github_automation; commenting on the
        repository under test uses the PAT in the publish job only."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                self.assertEqual(document["permissions"], {"contents": "read"})


class TestConcurrencyGuardrails(unittest.TestCase):
    """A second push must cancel the run still testing the previous commit."""

    def test_concurrency_is_keyed_on_the_pull_request_and_cancels(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                concurrency = document["concurrency"]
                self.assertTrue(concurrency["cancel-in-progress"])
                # Keyed on repository and number: this repository serves many, and PR #7
                # in one must not cancel PR #7 in another.
                self.assertIn("client_payload.repository", concurrency["group"])
                self.assertIn("client_payload.pr_number", concurrency["group"])
                self.assertIn("inputs.pr_number", concurrency["group"])

    def test_web_and_mobile_groups_do_not_collide(self) -> None:
        web = _load(WORKFLOW_DIR / "qa-web-preview.yml")["concurrency"]["group"]
        mobile = _load(WORKFLOW_DIR / "qa-mobile-preview.yml")["concurrency"]["group"]
        self.assertNotEqual(web, mobile)


class TestDefensiveGuardrails(unittest.TestCase):
    """Job timeouts, and reporting that survives a failing test step."""

    def test_every_job_declares_a_timeout(self) -> None:
        """Without one a hung service holds a runner for six hours."""
        for name, _, document in _workflows():
            for job_name, job in document["jobs"].items():
                with self.subTest(workflow=name, job=job_name):
                    self.assertIn("timeout-minutes", job)

    def test_media_and_teardown_run_after_a_failed_test_step(self) -> None:
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            for fragment in ("Compress the recording", "Hand the results", "Stop the", "Report the test outcome"):
                with self.subTest(workflow=name, step=fragment):
                    self.assertIn("always()", str(_step(job, fragment).get("if", "")))

    def test_the_test_step_does_not_abort_the_job(self) -> None:
        """`continue-on-error` lets the media steps run; the job's verdict is then
        re-asserted by the final step."""
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            with self.subTest(workflow=name):
                self.assertTrue(_step(job, "Execute the").get("continue-on-error"))
                report = _step(job, "Report the test outcome")
                self.assertIn("steps.tests.outcome", report["run"])
                # Publishing a red comment from a green run would hide the failure.
                self.assertIn("exit 1", report["run"])


class TestForkSafety(unittest.TestCase):
    """Fork code must never run with this repository's secrets."""

    def test_the_pull_request_is_resolved_through_the_fork_check(self) -> None:
        """qa-pr-context refuses forks and closed PRs even on a manual dispatch; the
        workflow must go through it rather than trusting the payload."""
        for name, platform, document in _workflows():
            with self.subTest(workflow=name):
                run = _step(_job(document, "resolve"), "Resolve the pull request")["run"]
                self.assertIn("qa-pr-context", run)
                self.assertIn(f"--platform {platform}", run)


class TestStepOrdering(unittest.TestCase):
    """The sequence exists so failures surface at their cheapest point."""

    def test_drift_detection_precedes_decryption_and_startup(self) -> None:
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            with self.subTest(workflow=name):
                drift = _step_index(job, "backend secret drift")
                decrypt = _step_index(job, "Decrypt the QA environment")
                startup = _step_index(job, "await health")
                tests = _step_index(job, "Execute the")
                self.assertLess(drift, decrypt)
                self.assertLess(decrypt, startup)
                self.assertLess(startup, tests)

    def test_the_backend_branch_is_resolved_before_it_is_checked_out(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                resolve = _job(document, "resolve")
                self.assertIn("backend_branch", resolve["outputs"])
                _step_index(resolve, "Resolve the backend branch")
                checkout = _step(_job(document, "qa-preview"), "Checkout backend")
                self.assertEqual(checkout["with"]["ref"], "${{ needs.resolve.outputs.backend_branch }}")

    def test_the_plan_is_generated_before_the_tests_execute(self) -> None:
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            with self.subTest(workflow=name):
                if "plan" in document["jobs"]:
                    self.assertIn("plan", job["needs"])
                    self.assertLess(_step_index(job, "Collect the test plan"), _step_index(job, "Execute the"))
                else:
                    self.assertLess(_step_index(job, "Generate the test plan"), _step_index(job, "Execute the"))


class TestCommitIdentity(unittest.TestCase):
    """Directive 5.A.2: results are reported against the PR head, never this repository's commit."""

    def test_publishing_uses_the_resolved_head_sha(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                publish = _step(_job(document, "publish"), "Publish the QA comment")
                self.assertEqual(publish["env"]["HEAD_SHA"], "${{ needs.resolve.outputs.head_sha }}")
                self.assertEqual(publish["env"]["TARGET_REPO"], "${{ needs.resolve.outputs.repository }}")

    def test_no_step_substitutes_this_repositorys_commit(self) -> None:
        for name in QA_WORKFLOWS:
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertNotIn("${{ github.sha }}", text)
                self.assertNotIn("$GITHUB_SHA", text)

    def test_checkout_pins_the_head_commit(self) -> None:
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            with self.subTest(workflow=name):
                checkout = job["steps"][0]
                self.assertIn("actions/checkout", checkout["uses"])
                self.assertEqual(checkout["with"]["repository"], "${{ needs.resolve.outputs.repository }}")
                self.assertEqual(checkout["with"]["ref"], "${{ needs.resolve.outputs.head_sha }}")
                # The diff against the base branch needs full history.
                self.assertEqual(checkout["with"]["fetch-depth"], 0)


class TestUntrustedTextHandling(unittest.TestCase):
    """Appendix B.3: human- and model-authored text reaches a shell in these workflows."""

    def test_the_pull_request_body_travels_as_a_file(self) -> None:
        """Interpolated into `run:`, a PR body containing backticks or $( ) executes."""
        pattern = re.compile(r"pull_request\.(body|title)")
        for name, _, document in _workflows():
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertIsNone(pattern.search(text))
                resolve = _job(document, "resolve")
                self.assertIn("--body-file", _step(resolve, "Resolve the pull request")["run"])
                self.assertIn("--pr-body-file", _step(resolve, "Resolve the backend branch")["run"])

    def test_the_media_step_reads_the_runners_selection_and_never_globs(self) -> None:
        """Globbing the recording directory returns whichever file the filesystem lists
        first, which on a multi-journey run publishes a passing journey's video while the
        comment reports a failure."""
        for name, _, document in _workflows():
            job = _job(document, "qa-preview")
            with self.subTest(workflow=name):
                tests = _step(job, "Execute the")
                invocation = str(tests.get("run", "")) + str(tests.get("with", {}).get("script", ""))
                self.assertIn("--selected-video-out", invocation)
                media = _step(job, "Compress the recording")
                self.assertIn("selected-video.txt", media["run"])
                self.assertNotIn("find ", media["run"])

    def test_the_decrypted_file_is_removed_on_every_exit_path(self) -> None:
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                teardown = _step(_job(document, "qa-preview"), "Stop the")
                self.assertIn("rm -f", teardown["run"])
                self.assertIn("always()", str(teardown["if"]))


class TestCaching(unittest.TestCase):
    """Warm runs must not re-download what a previous run already resolved."""

    def test_web_pipeline_caches_dependencies_browsers_and_plans(self) -> None:
        job = _job(_load(WORKFLOW_DIR / "qa-web-preview.yml"), "qa-preview")
        joined = " ".join(
            str(step.get("with", {}).get("path", "")) + str(step.get("with", {}).get("cache", ""))
            for step in job["steps"]
        )
        self.assertIn("ms-playwright", joined)
        self.assertIn("npm", joined)
        plan_cache = _step(_job(_load(WORKFLOW_DIR / "qa-web-preview.yml"), "plan"), "Restore the test plan cache")
        self.assertIn("test-plans", plan_cache["with"]["path"])

    def test_the_plan_cache_is_scoped_to_the_repository(self) -> None:
        """This cache is shared by every repository served. Unscoped, PR #7 in one
        repository would restore the plan of PR #7 in another."""
        for name, _, document in _workflows():
            with self.subTest(workflow=name):
                cache = _step(_plan_job(document), "Restore the test plan cache")
                self.assertIn("needs.resolve.outputs.repository", cache["with"]["key"])
                self.assertIn("restore-keys", cache["with"])
                for line in cache["with"]["restore-keys"].strip().splitlines():
                    self.assertIn("needs.resolve.outputs.repository", line)



class TestAgyPlanJob(unittest.TestCase):
    """The agy login belongs to a personal account: it stays off the runner that runs PR code."""

    def test_the_agy_login_and_api_key_are_held_only_by_the_plan_job(self) -> None:
        document = _load(WORKFLOW_DIR / "qa-web-preview.yml")
        preview = str(_job(document, "qa-preview"))
        for secret in ("AGY_SESSION_DATA", "AGY_AUTH_CONFIG", "GEMINI_API_KEY"):
            self.assertNotIn(f"secrets.{secret}", preview, secret)
            self.assertIn(f"secrets.{secret}", str(_job(document, "plan")), secret)

    def test_the_plan_job_never_runs_the_pull_requests_code(self) -> None:
        plan = _job(_load(WORKFLOW_DIR / "qa-web-preview.yml"), "plan")
        runs = " ".join(str(step.get("run", "")) for step in plan["steps"])
        for command in ("npm ", "npx ", "yarn ", "pnpm ", "prepare", "lifecycle"):
            self.assertNotIn(command, runs)

    def test_the_login_is_removed_even_when_generation_fails(self) -> None:
        plan = _job(_load(WORKFLOW_DIR / "qa-web-preview.yml"), "plan")
        removal = _step(plan, "Remove the agy login")
        self.assertIn("always()", str(removal["if"]))
        self.assertLess(_step_index(plan, "Generate the test plan"), _step_index(plan, "Remove the agy login"))


if __name__ == "__main__":
    unittest.main()
