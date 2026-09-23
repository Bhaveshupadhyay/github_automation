"""Structural tests for the assembled QA workflows.

The guardrails in Phase 6 — concurrency, job timeouts, fork safety, ordering, and the
`if: always()` reporting path — are properties of the YAML, so they are asserted against
the parsed YAML rather than reviewed by eye. Each test names the failure it excludes.
"""
import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
TEMPLATE_DIR = REPO_ROOT / "contracts" / "templates" / "workflows"

REUSABLE_WORKFLOWS = ["qa-web-preview.yml", "qa-mobile-preview.yml"]
CALLER_TEMPLATES = ["qa-web-preview.caller.yml", "qa-mobile-preview.caller.yml"]
R2_SECRETS = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    """Return the `on:` block. PyYAML reads the bare key `on` as the boolean True."""
    return document.get("on", document.get(True, {}))


def _preview_job(document: dict) -> dict:
    return document["jobs"]["qa-preview"]


def _step_index(job: dict, fragment: str) -> int:
    """Index of the first step whose name contains `fragment`."""
    for index, step in enumerate(job["steps"]):
        if fragment.lower() in str(step.get("name", "")).lower():
            return index
    raise AssertionError(f"No step named like {fragment!r}. Steps: {[s.get('name') for s in job['steps']]}")


class TestWorkflowsParse(unittest.TestCase):
    """Every workflow file must be valid YAML with the expected top-level shape."""

    def test_all_workflows_parse(self) -> None:
        for name in REUSABLE_WORKFLOWS + [p.name for p in WORKFLOW_DIR.glob("*.yml")]:
            with self.subTest(workflow=name):
                document = _load(WORKFLOW_DIR / name)
                self.assertIn("jobs", document)
                self.assertTrue(_triggers(document), "Workflow declares no trigger.")

    def test_caller_templates_parse(self) -> None:
        for name in CALLER_TEMPLATES:
            with self.subTest(template=name):
                document = _load(TEMPLATE_DIR / name)
                self.assertIn("jobs", document)


class TestReusableContract(unittest.TestCase):
    """The QA workflows are called by consumer repositories, never self-triggered."""

    def test_only_workflow_call_is_declared(self) -> None:
        """A `pull_request` trigger here would run the pipeline against this tooling
        repository, which has no application to preview."""
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                triggers = _triggers(_load(WORKFLOW_DIR / name))
                self.assertEqual(list(triggers.keys()), ["workflow_call"])

    def test_sops_age_key_is_the_only_required_secret(self) -> None:
        """Directive: a caller needs exactly one secret to run the pipeline."""
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                secrets = _triggers(_load(WORKFLOW_DIR / name))["workflow_call"]["secrets"]
                required = [key for key, spec in secrets.items() if spec.get("required")]
                self.assertEqual(required, ["SOPS_AGE_KEY"])

    def test_storage_credentials_are_accepted_as_optional_secrets(self) -> None:
        """R2 credentials may come from GitHub secrets instead of .env.qa.enc."""
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                secrets = _triggers(_load(WORKFLOW_DIR / name))["workflow_call"]["secrets"]
                for key in R2_SECRETS:
                    self.assertIn(key, secrets)
                    self.assertFalse(secrets[key].get("required"))

    def test_storage_credentials_reach_only_the_publish_step(self) -> None:
        """Written to GITHUB_ENV, credentials reach every later step, including the pull
        request's own test plan and build hooks. Only the publisher needs them."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                publish = _step_index(job, "Publish the QA comment")
                for index, step in enumerate(job["steps"]):
                    run = str(step.get("run", ""))
                    self.assertFalse("R2_" in run and "GITHUB_ENV" in run, step.get("name"))
                    if index != publish:
                        self.assertNotIn("secrets.R2_", str(step.get("env", "")), step.get("name"))
                step_env = job["steps"][publish]["env"]
                for key in R2_SECRETS:
                    self.assertEqual(step_env[key], f"${{{{ secrets.{key} }}}}")

    def test_decryption_exports_nothing_to_the_job(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                decrypt = job["steps"][_step_index(job, "Decrypt the QA environment")]
                self.assertNotIn("GITHUB_ENV", decrypt["run"])

    def test_the_tooling_checkout_defaults_to_this_workflows_own_commit(self) -> None:
        """A caller pinned to a branch must get that branch's CLIs. Defaulting to `main`
        would run new steps against whatever `main` holds — during a branch pilot, CLIs
        that do not yet exist."""
        for name in REUSABLE_WORKFLOWS:
            document = _load(WORKFLOW_DIR / name)
            with self.subTest(workflow=name):
                self.assertEqual(
                    _triggers(document)["workflow_call"]["inputs"]["tooling-ref"]["default"], ""
                )
                job = _preview_job(document)
                checkout = job["steps"][_step_index(job, "Checkout QA tooling")]
                self.assertIn("github.job_workflow_sha", checkout["with"]["ref"])

    def test_backend_repository_is_an_input_not_a_constant(self) -> None:
        """A hardcoded repository would couple the pipeline to one product."""
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                inputs = _triggers(_load(WORKFLOW_DIR / name))["workflow_call"]["inputs"]
                self.assertTrue(inputs["backend-repo"]["required"])


class TestConcurrencyGuardrails(unittest.TestCase):
    """A second push must cancel the run still testing the previous commit."""

    def test_concurrency_is_keyed_on_the_pull_request_and_cancels(self) -> None:
        for name in REUSABLE_WORKFLOWS + CALLER_TEMPLATES:
            directory = WORKFLOW_DIR if name in REUSABLE_WORKFLOWS else TEMPLATE_DIR
            with self.subTest(workflow=name):
                concurrency = _load(directory / name)["concurrency"]
                self.assertTrue(concurrency["cancel-in-progress"])
                self.assertIn("pull_request.number", concurrency["group"])

    def test_caller_and_called_groups_do_not_collide_across_pipelines(self) -> None:
        """Web and mobile runs on one pull request must not cancel each other."""
        web = _load(WORKFLOW_DIR / "qa-web-preview.yml")["concurrency"]["group"]
        mobile = _load(WORKFLOW_DIR / "qa-mobile-preview.yml")["concurrency"]["group"]
        self.assertNotEqual(web, mobile)


class TestDefensiveGuardrails(unittest.TestCase):
    """Job timeouts, and reporting that survives a failing test step."""

    def test_every_job_declares_a_timeout(self) -> None:
        """Without one a hung service holds a runner for six hours."""
        for name in REUSABLE_WORKFLOWS:
            document = _load(WORKFLOW_DIR / name)
            for job_name, job in document["jobs"].items():
                with self.subTest(workflow=name, job=job_name):
                    self.assertIn("timeout-minutes", job)

    def test_media_publish_and_teardown_run_after_a_failed_test_step(self) -> None:
        """The recording of a failure is the most valuable artifact a red run produces,
        so it must survive the step that failed."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            for fragment in ("Compress the recording", "Publish the QA comment", "Stop the", "Report the test outcome"):
                with self.subTest(workflow=name, step=fragment):
                    step = job["steps"][_step_index(job, fragment)]
                    self.assertIn("always()", str(step.get("if", "")))

    def test_the_test_step_does_not_abort_the_job(self) -> None:
        """`continue-on-error` is what lets the publishing steps run; the job's verdict
        is then re-asserted by the final step."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                test_step = job["steps"][_step_index(job, "Execute the")]
                self.assertTrue(test_step.get("continue-on-error"))
                report = job["steps"][_step_index(job, "Report the test outcome")]
                self.assertIn("steps.tests.outcome", report["run"])

    def test_a_failed_run_still_fails_the_job(self) -> None:
        """Publishing a red comment from a green job would hide the failure from
        branch protection."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                report = job["steps"][_step_index(job, "Report the test outcome")]
                self.assertIn("exit 1", report["run"])


class TestForkSafety(unittest.TestCase):
    """A fork PR gets no secrets, so it must be skipped visibly, not failed cryptically."""

    def test_the_preview_job_is_skipped_for_forks(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                condition = _preview_job(_load(WORKFLOW_DIR / name))["if"]
                self.assertIn("head.repo.fork", condition)
                self.assertIn("!", condition)

    def test_a_fork_receives_an_explanatory_notice(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            with self.subTest(workflow=name):
                notice = _load(WORKFLOW_DIR / name)["jobs"]["fork-notice"]
                self.assertIn("head.repo.fork", notice["if"])
                body = notice["steps"][0]["run"]
                self.assertIn("GITHUB_STEP_SUMMARY", body)
                # The comment attempt must not fail the job: a fork's token is read-only.
                self.assertIn("||", body)


class TestStepOrdering(unittest.TestCase):
    """The plan's sequence exists so failures surface at their cheapest point."""

    def test_drift_detection_precedes_decryption_and_startup(self) -> None:
        """Key drift must halt the run before services start, or the symptom appears
        minutes later as an unrelated failing assertion."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                drift = _step_index(job, "backend secret drift")
                decrypt = _step_index(job, "Decrypt the QA environment")
                startup = _step_index(job, "await health")
                tests = _step_index(job, "Execute the")
                self.assertLess(drift, decrypt)
                self.assertLess(decrypt, startup)
                self.assertLess(startup, tests)

    def test_the_backend_branch_is_resolved_before_it_is_checked_out(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                self.assertLess(
                    _step_index(job, "Resolve the backend branch"),
                    _step_index(job, "Checkout backend"),
                )

    def test_the_plan_is_generated_before_the_tests_execute(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                self.assertLess(
                    _step_index(job, "Generate the test plan"),
                    _step_index(job, "Execute the"),
                )


class TestCommitIdentity(unittest.TestCase):
    """Directive 5.A.2: GITHUB_SHA is the synthetic merge commit on pull_request events."""

    def test_publishing_uses_the_pull_request_head_sha(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                publish = job["steps"][_step_index(job, "Publish the QA comment")]
                self.assertEqual(
                    publish["env"]["HEAD_SHA"], "${{ github.event.pull_request.head.sha }}"
                )

    def test_no_step_substitutes_the_merge_commit(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertNotIn("${{ github.sha }}", text)
                # GITHUB_SHA may be named in prose explaining why it is not used, but
                # never expanded in a command.
                self.assertNotIn("$GITHUB_SHA", text)

    def test_checkout_pins_the_head_commit_not_the_merge_ref(self) -> None:
        """Checking out the default ref would test `refs/pull/N/merge`, a commit the
        author never wrote."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                checkout = job["steps"][0]
                self.assertIn("actions/checkout", checkout["uses"])
                self.assertEqual(checkout["with"]["ref"], "${{ github.event.pull_request.head.sha }}")
                # The diff against the base branch needs full history.
                self.assertEqual(checkout["with"]["fetch-depth"], 0)


class TestUntrustedTextHandling(unittest.TestCase):
    """Appendix B.3: human- and model-authored text reaches a shell in these workflows."""

    def test_the_pull_request_body_never_reaches_a_script_inline(self) -> None:
        """Interpolated into `run:`, a PR body containing backticks or $( ) executes."""
        pattern = re.compile(r"\$\{\{\s*github\.event\.pull_request\.(body|title)\s*\}\}")
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                for step in job["steps"]:
                    self.assertIsNone(
                        pattern.search(str(step.get("run", ""))),
                        f"Step {step.get('name')!r} interpolates PR text into its script.",
                    )
                resolve = job["steps"][_step_index(job, "Resolve the backend branch")]
                self.assertEqual(resolve["env"]["PR_BODY"], "${{ github.event.pull_request.body }}")
                # Passed as a file, so the resolver reads it rather than the shell re-parsing it.
                self.assertIn("--pr-body-file", resolve["run"])

    def test_the_media_step_reads_the_runners_selection_and_never_globs(self) -> None:
        """Globbing the recording directory returns whichever file the filesystem lists
        first, which on a multi-journey run publishes a passing journey's video while the
        comment reports a failure."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                tests = job["steps"][_step_index(job, "Execute the")]
                invocation = str(tests.get("run", "")) + str(tests.get("with", {}).get("script", ""))
                self.assertIn("--selected-video-out", invocation)
                media = job["steps"][_step_index(job, "Compress the recording")]
                self.assertIn("selected-video.txt", media["run"])
                self.assertNotIn("find ", media["run"])

    def test_publish_step_masks_and_removes_decrypted_values(self) -> None:
        """An unmasked value appears in plain text in the run log, and a decrypted file
        in the workspace could be uploaded with the artifacts."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                publish = job["steps"][_step_index(job, "Publish the QA comment")]["run"]
                self.assertIn("::add-mask::", publish)
                self.assertIn('mktemp "$RUNNER_TEMP/', publish)
                self.assertIn('rm -f "$QA_ENV"', publish)
                self.assertNotIn("GITHUB_ENV", publish)

    def test_the_decrypted_file_is_removed_on_every_exit_path(self) -> None:
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                teardown = job["steps"][_step_index(job, "Stop the")]
                self.assertIn("rm -f", teardown["run"])
                self.assertIn("always()", str(teardown["if"]))


class TestCaching(unittest.TestCase):
    """Warm runs must not re-download what a previous run already resolved."""

    def test_web_pipeline_caches_dependencies_browsers_and_plans(self) -> None:
        job = _preview_job(_load(WORKFLOW_DIR / "qa-web-preview.yml"))
        cached = [
            str(step.get("with", {}).get("path", "")) + str(step.get("with", {}).get("cache", ""))
            for step in job["steps"]
        ]
        joined = " ".join(cached)
        self.assertIn("ms-playwright", joined)
        self.assertIn("test-plans", joined)
        self.assertIn("npm", joined)

    def test_the_plan_cache_falls_back_to_an_earlier_run_on_the_same_pr(self) -> None:
        """Without restore-keys every push is a cold cache and a fresh model call."""
        for name in REUSABLE_WORKFLOWS:
            job = _preview_job(_load(WORKFLOW_DIR / name))
            with self.subTest(workflow=name):
                cache = job["steps"][_step_index(job, "Restore the test plan cache")]
                self.assertIn("restore-keys", cache["with"])


class TestCallerTemplates(unittest.TestCase):
    """The templates a consumer repository copies must call the workflows shipped here."""

    def test_each_template_calls_its_reusable_workflow(self) -> None:
        for template, workflow in zip(CALLER_TEMPLATES, REUSABLE_WORKFLOWS):
            with self.subTest(template=template):
                job = _load(TEMPLATE_DIR / template)["jobs"]["qa"]
                self.assertIn(f".github/workflows/{workflow}@", job["uses"])
                self.assertIn("SOPS_AGE_KEY", job["secrets"])
                for key in R2_SECRETS:
                    self.assertIn(key, job["secrets"])
                self.assertIn("backend-repo", job["with"])

    def test_templates_trigger_on_the_pull_request_events_that_change_code(self) -> None:
        for template in CALLER_TEMPLATES:
            with self.subTest(template=template):
                types = _triggers(_load(TEMPLATE_DIR / template))["pull_request"]["types"]
                self.assertIn("synchronize", types)
                self.assertIn("opened", types)


if __name__ == "__main__":
    unittest.main()
