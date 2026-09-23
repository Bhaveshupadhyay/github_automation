# QA CI Pipeline

The assembled pipeline. Phases 1–5 produced independent CLIs; Phase 6 wired them into two
GitHub Actions workflows with the guardrails that make them safe to run. Both workflows
run **centrally, in this repository**, for pull requests opened in other repositories, and
**only when a user asks the Slack bot for QA testing**. Asking the bot to write code opens
a pull request; it never tests one.

## Shape

The repositories under test hold no workflow file and no secret. Everything — the
pipeline, its secrets, its runs and its logs — lives here.

```
@bot target repo: owner/frontend  add an admin panel…   → the bot opens a frontend PR
@bot run QA on this                                      (in that thread)
  → Worker classifies the request as QA_TESTING and finds the frontend PR
  → bot: "which backend should it run against?"
      owner/backend#8 (or its link)   → the backend PR's branch, run in the runner
      main  (or `main owner/repo`)    → that backend's main branch, run in the runner
      dev                             → the deployed dev APIs; no backend is started
  → repository_dispatch `qa_<platform>_preview` on github_automation
  → resolve → qa-preview → publish, all in github_automation's Actions
  → frontend PR branch cloned at its head commit, pointed at the chosen backend
  → tests generated from the diff, run and recorded
  → one comment on the pull request, media in R2, reply in the Slack thread
```

The frontend PR is the one named in the message, else the latest registered PR linked in
the thread. A request that names a backend PR too (`@bot test owner/web#5 against
owner/api#8`) starts at once. Answering "no backend PR" gets the `main` and `dev` options;
an unrecognised answer gets the question again. The answer may be tagged or not, but a
QA request itself only counts when the bot is tagged, and a QA reply never resumes the
coding run.

| File | Purpose |
| :--- | :--- |
| `contracts/qa-targets.json` | Which repositories can be QA-tested, their platform, paired backend and settings |
| `.github/workflows/qa-web-preview.yml` | Web PRs: Playwright journeys against the paired backend |
| `.github/workflows/qa-mobile-preview.yml` | Mobile PRs: Maestro flows on an Android emulator |
| `cloudflare-worker/src/services/qaRequestService.js` | Finds the PR a Slack QA request means and dispatches the pipeline |
| `automation/qa_pr_context_cli.py` | `qa-pr-context`: reads the PR fresh from the API and pairs it with its target |

Each workflow also has a `workflow_dispatch` trigger, for re-running a pull request by hand
after updating its backend branch or fixing a broken test (Phase 7.3):

```bash
gh workflow run qa-web-preview.yml -f repository=owner/frontend -f pr_number=42 -f backend=owner/backend#8
```

## Registering a repository

Add it to `contracts/qa-targets.json`:

```json
{
  "targets": {
    "owner/frontend": {
      "platform": "web",
      "backend_repo": "owner/backend",
      "backend_default_branch": "main",
      "frontend_url": "http://localhost:5173"
    }
  }
}
```

| Field | Default | Meaning |
| :--- | :--- | :--- |
| `platform` | — | `web` or `mobile`: which pipeline runs |
| `backend_repo` | — | Backend paired with this repository |
| `backend_default_branch` | `main` | Used when the PR declares no backend branch and no head matches |
| `alternate_backend_repos` | `[]` | Other backends a requester may choose. Any other repository is refused, since a backend runs beside the QA secrets |
| `dev_api_url` | none | Deployed dev API base URL for the `dev` answer. Unset, `dev` is refused with a reason |
| `slack_channel` | none | Slack channel for a manual re-run's result. A Slack request replies in its own thread |
| `db_strategy` | `auto` | `auto`, `cloud_dev` or `ephemeral_container` |
| `startup_timeout_seconds` | `420` | Budget for install, migrations and health probes |
| `frontend_url`, `node_version` | `http://localhost:3000`, `20` | Web only |
| `api_base_url`, `android_api_level`, `java_version` | `http://10.0.2.2:8000`, `34`, `17` | Mobile only |

Unknown fields are rejected, so a typo fails loudly instead of falling back to a default.
Nothing is installed in the registered repository: no workflow, no secret, no webhook.

The backend repository still needs its `.env.qa.enc` and `.sops.yaml`, and both
repositories need a `qa-contract.json`: those describe the application, not the pipeline.

## Jobs

**`resolve`** reads the pull request from the API — the dispatch payload carries only a
repository, a number and the backend choice — and refuses it when it is unregistered,
closed, or from a fork. A backend PR gets the same open/fork check and is checked out at
its head commit. With no choice (a manual re-run without `backend`), the backend branch is
resolved from the PR (explicit declaration → matching remote head → default).

**`qa-preview`** runs the pull request's code:

1. Checkout the PR head commit with full history, and this repository's tooling.
2. Install SOPS and age; key-drift check on the frontend.
3. Checkout the backend at the chosen PR or branch; key-drift check on the backend.
4. Check that `.env.qa.enc` decrypts, failing fast on a bad key. Nothing is exported.
5. Start the database, backend and frontend, with the frontend's `apiBaseUrlEnvVar`
   pointed at the backend; wait for both health probes. With `dev`, steps 3–4 are skipped
   and only the frontend starts, pointed at `dev_api_url`.
6. Generate the test plan from the diff, reusing the cached plan when unchanged.
7. Execute the journeys, recording video; compress it and build the preview GIF.
8. Hand the results to `publish` as an artifact; stop the services; re-assert the verdict.

**`publish`** runs on a fresh runner, downloads the results, uploads the media to R2,
edits the single PR comment in place and replies in the Slack thread that asked. It runs
even when `qa-preview` failed, so a red run still publishes the recording of its failure,
but not when the run was cancelled by a newer request. A run that stopped before any test
ran, a skipped request, and a `resolve` that failed outright are also answered in the
thread.

## Guardrails

**Secret isolation.** The pull request's code runs only in `qa-preview`. GitHub sends
every secret a job references to that job's runner, where the PR's code has sudo, so
`qa-preview` does not reference the PAT or the R2 credentials at all: they exist only in
`resolve` and `publish`, which run none of the PR's code. `qa-preview` clones with a
read-only token — `QA_READ_TOKEN` when set, else the run's own token, which can read
public repositories — and every checkout sets `persist-credentials: false`. A backend
the requester names must be `backend_repo` or listed in `alternate_backend_repos`.

**Fork safety.** Fork code would run with this repository's secrets, so forks never run.
`qa-pr-context` refuses them against the API, so neither a Slack request nor a manual
dispatch can bypass the check.

**Untrusted input.** Dispatch values reach scripts only through the environment and are
validated before use. The PR body travels as a file, never interpolated into a script.

**Concurrency.** Keyed on repository and PR number, with `cancel-in-progress: true`, so a
second request for the same PR cancels the run still testing it, and PR #7 in one repository never
cancels PR #7 in another. Cancellation is a capacity control, not a correctness guarantee;
the publisher restores the single-comment invariant itself (Directive 5.A.4).

**Job timeouts.** 5 minutes for `resolve`, 15 for web and 25 for mobile `qa-preview`
(emulator boot and the Gradle build dominate; Appendix A.5), 10 for `publish`.

**Commit identity.** Checkout pins the head SHA that `resolve` read, and publishing
reports the same value. This repository's own commit is never used (Directive 5.A.2).

## Caching

Caches belong to this repository and are shared by every repository it serves, so the
test-plan keys carry the repository name.

| Cache | Key | Effect |
| :--- | :--- | :--- |
| uv / Python deps | `tooling/uv.lock` | Tooling install |
| npm | `frontend/package-lock.json` | Frontend install |
| Playwright browsers | `~/.cache/ms-playwright`, keyed on `uv.lock` | Skips a ~150MB Chromium download |
| Test plans | repository + PR number + head SHA, with prefix restore-keys | A re-run of an unchanged diff makes no model call |
| Gradle | `gradle/actions/setup-gradle` | Mobile build |

## Secrets

All in **this repository's** Actions secrets.

| Secret | Required | Used by | Absent behaviour |
| :--- | :--- | :--- | :--- |
| `PAT_TOKEN` | Yes | `resolve`, `publish` | Cannot read the PR or comment on it. Needs read access to the repositories under test and write access to their pull requests |
| `QA_READ_TOKEN` | Private repos only | `qa-preview` clones | Read-only (`contents: read`) token for cloning private repositories under test. Public ones clone with the run's own token |
| `SOPS_AGE_KEY` | Yes | `qa-preview` | Fails fast at the decryption step |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` | No | `publish` | Media falls back to workflow artifacts |
| `GEMINI_API_KEY` | No | `resolve`, `qa-preview` | Test generation falls back to the baseline smoke suite |
| `SLACK_BOT_TOKEN` | No | `publish` | Slack notification skipped |

The Worker needs only what it already has: `GITHUB_PAT` (now also used to read the
registry) and the Slack and Gemini credentials.

Comments are posted as the PAT's account, which the publisher resolves through `/user` to
recognise its own previous comment.

## Running the pieces locally

Each stage is an ordinary CLI, so a failing run can be reproduced step by step:

```bash
qa-pr-context --repository owner/frontend --pr 42 --platform web
qa-branch-resolve --source-branch feat/x --backend-repo-url https://github.com/org/api.git --json
qa-lifecycle --backend-dir ./backend --frontend-dir ./frontend --check-only
qa-test-gen --base-branch origin/main --output plan.json
qa-run --plan plan.json --base-url http://localhost:3000 --video-dir raw --result-json run.json
qa-media --input raw/video.webm --output-dir processed --result-json media.json
qa-publish --repo org/app --pr 42 --test-result run.json --media-result media.json --dry-run
```

`qa-run`'s exit codes are distinguished because they call for different responses:

| Code | Meaning |
| :--- | :--- |
| `0` | Every journey passed |
| `1` | A journey failed — the application, not the pipeline |
| `2` | Nothing executed: runner unavailable, empty plan, engine crash |
| `3` | Usage error: missing or malformed plan, Maestro without an app ID |

## Verifying the guardrails

`tests/test_qa_workflow_assembly.py` asserts these properties against the parsed YAML:
trigger shape, job structure, secret isolation, credential persistence, concurrency,
timeouts, the fork check, step ordering, head-SHA usage, the Slack round trip and the
caches. The Worker's QA routing is covered by `npm run test:worker`.

## Piloting

GitHub runs `repository_dispatch` and `workflow_dispatch` workflows from the **default
branch**, so Slack-requested runs use whatever `main` holds. The first end-to-end run
therefore happens after merge and a Worker deploy: tag the bot in a thread where it opened
a pull request on a registered repository, ask it to run QA, and check the run in this
repository's Actions tab. That run exercises intent routing, dispatch, SOPS decryption,
branch resolution, health probes, plan generation, Playwright, storage, the comment
publisher and the Slack reply together, and is the first of the Phase 7.1 pilot runs.
