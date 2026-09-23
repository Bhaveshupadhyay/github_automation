# QA CI Pipeline (Phase 6)

The assembled pipeline. Phases 1–5 produced independent CLIs; this phase wires them into
two reusable GitHub Actions workflows and adds the guardrails that make them safe to run
on every pull request.

## Shape

Both workflows are **reusable** (`on: workflow_call`) and live in this repository. A
consumer repository copies a short caller from `contracts/templates/workflows/`:

| File | Purpose |
| :--- | :--- |
| `.github/workflows/qa-web-preview.yml` | Frontend PRs: Playwright journeys against the paired backend |
| `.github/workflows/qa-mobile-preview.yml` | Mobile PRs: Maestro flows on an Android emulator |
| `contracts/templates/workflows/*.caller.yml` | Copied into the app repository; declares when to run and which backend to pair |

They are deliberately not triggered by `pull_request` here. This repository has no
application to preview, so a direct trigger would run the pipeline against the tooling.

```yaml
jobs:
  qa:
    uses: bhaveshupadhyay/github_automation/.github/workflows/qa-web-preview.yml@main
    with:
      backend-repo: your-org/your-backend
    secrets:
      SOPS_AGE_KEY: ${{ secrets.SOPS_AGE_KEY }}
```

## Step sequence

1. Checkout the frontend **at the PR head commit**, with full history.
2. Checkout this tooling repository and install the `qa-*` CLIs.
3. Install SOPS and age.
4. Key-drift check on the frontend.
5. Resolve the backend branch (explicit declaration → matching remote head → default).
6. Checkout the backend at the resolved branch.
7. Key-drift check on the backend.
8. Decrypt `.env.qa.enc`; export and mask only the storage keys.
9. Start the database, backend and frontend; wait for both health probes.
10. Generate the test plan from the diff, reusing the cached plan when the diff is unchanged.
11. Execute the journeys, recording video.
12. Compress the recording and build the preview GIF.
13. Publish the single in-place PR comment; upload artifacts if storage degraded.
14. Stop the services and shred the decrypted environment.
15. Re-assert the test verdict as the job's verdict.

Steps 4 and 8 come before step 9 on purpose. Drift and decryption failures are cheap to
diagnose at the point they occur; the same failures surfacing after startup look like
unrelated failing assertions minutes later.

## Guardrails

**Concurrency.** Both the caller and the called workflow declare
`cancel-in-progress: true`, keyed on the pull request number. Both are needed: a caller
that keeps running holds its called workflow alive. Web and mobile use distinct group
names, so a repository running both does not have one cancel the other.

Cancellation is a capacity control, not a correctness guarantee — a run already past the
cancellation point still finishes. The single-comment invariant is restored by the
publisher itself (Directive 5.A.4), not by this setting.

**Job timeouts.** 15 minutes for web, 25 for mobile, both overridable through the
`timeout-minutes` input. Mobile is higher because emulator boot and the Gradle build
dominate the run; Appendix A.5 records why mobile is an independent milestone.

**Fork safety.** A fork PR receives a read-only token and no secrets, so the preview job
is skipped by `if: ${{ !github.event.pull_request.head.repo.fork }}` and a separate job
writes an explanatory notice. That job attempts a PR comment and tolerates failure —
a fork's token cannot post one — so the job summary is the reliable surface. Nothing
about a fork PR turns the pipeline red.

**Reporting survives failure.** The execution step carries `continue-on-error: true`, and
media processing, publishing and teardown carry `if: always()`. The final step re-reads
`steps.tests.outcome` and fails the job, so a red run still publishes the recording of its
failure and still fails branch protection.

**Commit identity.** Checkout pins `github.event.pull_request.head.sha` and publishing
passes the same value. `GITHUB_SHA` is never used: on a `pull_request` event it is the
synthetic merge commit of `refs/pull/N/merge`, which appears in no commit list and is
recreated whenever the base branch moves (Directive 5.A.2).

**Untrusted text.** The PR body reaches the branch resolver through a file, never
interpolated into a script. Decrypted values are passed through `::add-mask::` before
export, and the plaintext env file is written under `RUNNER_TEMP` — outside the workspace,
where no upload or commit step can reach it — and removed during teardown.

## Caching

| Cache | Key | Effect |
| :--- | :--- | :--- |
| uv / Python deps | `tooling/uv.lock` | Tooling install |
| npm | `frontend/package-lock.json` | Frontend install |
| Playwright browsers | `~/.cache/ms-playwright`, keyed on `uv.lock` | Skips a ~150MB Chromium download |
| Test plans | PR number + head SHA, with prefix restore-keys | A re-run of an unchanged diff makes no model call |
| Gradle | `gradle/actions/setup-gradle` | Mobile build |

The plan cache's `restore-keys` matter: without them every push is a cold cache, and the
plan is regenerated even when the diff content already has an entry.

## Secrets

`SOPS_AGE_KEY` is the only required secret and the only application secret in GitHub
Actions. Everything else is decrypted from the `.env.qa.enc` committed beside the code.

| Secret | Required | Absent behaviour |
| :--- | :--- | :--- |
| `SOPS_AGE_KEY` | Yes | Fails fast at the decryption step with an explicit message |
| `GEMINI_API_KEY` | No | Test generation falls back to the baseline smoke suite |
| `BACKEND_TOKEN` | No | Falls back to the workflow token; needed when the backend is private |
| `SLACK_BOT_TOKEN` | No | Slack notification skipped entirely |

## Running the pieces locally

Each stage is an ordinary CLI, so a failing run can be reproduced step by step:

```bash
qa-branch-resolve --source-branch feat/x --backend-repo-url https://github.com/org/api.git --json
qa-lifecycle --backend-dir ./backend --frontend-dir ./frontend --check-only
qa-test-gen --base-branch origin/main --output plan.json
qa-run --plan plan.json --base-url http://localhost:3000 --video-dir raw --result-json run.json
qa-media --input raw/video.webm --output-dir processed --result-json media.json
qa-publish --repo org/app --pr 42 --test-result run.json --media-result media.json --dry-run
```

`qa-run` is the bridge Phase 5 assumed: it validates the model-authored plan, executes it,
writes the `TestRunResult` that `qa-publish` consumes, and names the one recording worth
processing — the failing journey's when there is one, since that is what a reviewer opens
on a red run.

Its exit codes are distinguished because they call for different responses:

| Code | Meaning |
| :--- | :--- |
| `0` | Every journey passed |
| `1` | A journey failed — the application, not the pipeline |
| `2` | Nothing executed: runner unavailable, empty plan, engine crash |
| `3` | Usage error: missing or malformed plan, Maestro without an app ID |

A result JSON is written on all of them, so the publishing stage can always explain the
run rather than silently omitting a section.

## Verifying the guardrails

`tests/test_qa_workflow_assembly.py` asserts these properties against the parsed YAML
rather than leaving them to review: trigger shape, concurrency and cancellation, per-job
timeouts, the fork condition, step ordering, head-SHA usage, masking, and the caches. Each
test names the failure it excludes, so it can fail for the right reason.

For the YAML itself:

```bash
actionlint -ignore 'property "job_workflow_sha" is not defined' \
  .github/workflows/qa-web-preview.yml .github/workflows/qa-mobile-preview.yml
```

The ignore is a false positive: `github.job_workflow_sha` is documented by GitHub but
missing from actionlint 1.7.7's context table. It is not relied upon blindly — the tooling
install step verifies `qa-run` exists and fails with an actionable message if the checkout
resolved to a commit that predates it.

## Piloting before merge

Component tests pass on both sides of a missing bridge, so the pipeline must run once end
to end against a real pull request before these workflows are merged. Point a caller at
the feature branch:

```yaml
uses: bhaveshupadhyay/github_automation/.github/workflows/qa-web-preview.yml@feat/qa-automation-phase-6
```

The tooling checkout follows that same commit automatically, so no second ref needs
pinning. Run it on one real frontend PR carrying the `qa-preview` label — that single run
exercises SOPS decryption, branch resolution, health probes, plan generation, Playwright,
storage and the comment publisher together, and is itself the first of the Phase 7.1
pilot runs.
