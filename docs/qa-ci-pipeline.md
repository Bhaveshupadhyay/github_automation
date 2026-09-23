# QA CI Pipeline

The assembled pipeline. Phases 1–5 produced independent CLIs; Phase 6 wired them into two
GitHub Actions workflows with the guardrails that make them safe to run on every pull
request. Both workflows run **centrally, in this repository**, for pull requests opened in
other repositories.

## Shape

The repositories under test hold no workflow file and no secret. Everything — the
pipeline, its secrets, its runs and its logs — lives here.

```
PR opened / pushed / labelled in a registered repository
  → GitHub webhook → Cloudflare Worker (verifies the signature, filters forks and labels)
  → repository_dispatch `qa_<platform>_preview` on github_automation
  → resolve → qa-preview → publish, all in github_automation's Actions
  → one comment on the pull request, media in R2
```

| File | Purpose |
| :--- | :--- |
| `contracts/qa-targets.json` | Which repositories are served, their platform, backend, label gate and settings |
| `.github/workflows/qa-web-preview.yml` | Web PRs: Playwright journeys against the paired backend |
| `.github/workflows/qa-mobile-preview.yml` | Mobile PRs: Maestro flows on an Android emulator |
| `cloudflare-worker/src/services/githubWebhookService.js` | Webhook signature check and dispatch decision |
| `automation/qa_pr_context_cli.py` | `qa-pr-context`: reads the PR fresh from the API and pairs it with its target |

Each workflow also has a `workflow_dispatch` trigger, for re-running a pull request by hand
after updating its backend branch or fixing a broken test (Phase 7.3):

```bash
gh workflow run qa-web-preview.yml -f repository=owner/frontend -f pr_number=42
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
      "require_label": "qa-preview",
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
| `require_label` | `qa-preview` | Label a PR needs to run. `null` runs every PR (general availability) |
| `slack_channel` | none | Slack channel for the result notification |
| `db_strategy` | `auto` | `auto`, `cloud_dev` or `ephemeral_container` |
| `startup_timeout_seconds` | `420` | Budget for install, migrations and health probes |
| `frontend_url`, `node_version` | `http://localhost:3000`, `20` | Web only |
| `api_base_url`, `android_api_level`, `java_version` | `http://10.0.2.2:8000`, `34`, `17` | Mobile only |

Unknown fields are rejected, so a typo fails loudly instead of falling back to a default.
Then, in the registered repository, add a webhook: **Settings → Webhooks → Add webhook**,
payload URL the Worker's URL, content type `application/json`, the secret stored in the
Worker as `GITHUB_WEBHOOK_SECRET`, and the **Pull requests** event only.

The backend repository still needs its `.env.qa.enc` and `.sops.yaml`, and both
repositories need a `qa-contract.json`: those describe the application, not the pipeline.

## Jobs

**`resolve`** reads the pull request from the API — the dispatch payload carries only a
repository and a number — and refuses it when it is unregistered, closed, or from a fork.
It then resolves the backend branch (explicit declaration → matching remote head → default).

**`qa-preview`** runs the pull request's code:

1. Checkout the PR head commit with full history, and this repository's tooling.
2. Install SOPS and age; key-drift check on the frontend.
3. Checkout the backend at the resolved branch; key-drift check on the backend.
4. Check that `.env.qa.enc` decrypts, failing fast on a bad key. Nothing is exported.
5. Start the database, backend and frontend; wait for both health probes.
6. Generate the test plan from the diff, reusing the cached plan when unchanged.
7. Execute the journeys, recording video; compress it and build the preview GIF.
8. Hand the results to `publish` as an artifact; stop the services; re-assert the verdict.

**`publish`** runs on a fresh runner, downloads the results, uploads the media to R2 and
edits the single PR comment in place. It runs even when `qa-preview` failed, so a red run
still publishes the recording of its failure.

## Guardrails

**Secret isolation.** The pull request's code runs only in `qa-preview`. The token that
can write to the pull request and the R2 credentials exist only in `publish`, on a
separate runner, so no step of the PR's code can read them from a neighbouring process or
a file. In `qa-preview` the PAT appears only as a checkout credential, and every checkout
sets `persist-credentials: false`, so no token is left in `.git/config`.

**Fork safety.** Fork code would run with this repository's secrets, so forks never run.
The Worker drops fork webhooks, and `qa-pr-context` refuses them again against the API, so
neither a forged payload nor a manual dispatch can bypass the check.

**Untrusted input.** Dispatch values reach scripts only through the environment and are
validated before use. The PR body travels as a file, never interpolated into a script.

**Concurrency.** Keyed on repository and PR number, with `cancel-in-progress: true`, so a
new push cancels the run still testing the old commit, and PR #7 in one repository never
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
| `PAT_TOKEN` | Yes | `resolve`, clones, `publish` | Cannot read the PR or comment on it. Needs read access to the repositories under test and write access to their pull requests |
| `SOPS_AGE_KEY` | Yes | `qa-preview` | Fails fast at the decryption step |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` | No | `publish` | Media falls back to workflow artifacts |
| `GEMINI_API_KEY` | No | `resolve`, `qa-preview` | Test generation falls back to the baseline smoke suite |
| `SLACK_BOT_TOKEN` | No | `publish` | Slack notification skipped |

The Worker needs `GITHUB_PAT` (to read the registry and send the dispatch) and
`GITHUB_WEBHOOK_SECRET`. Without the webhook secret every webhook is rejected.

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
timeouts, the fork check, step ordering, head-SHA usage and the caches. The Worker's
webhook handling is covered by `npm run test:worker`.

## Piloting

GitHub runs `repository_dispatch` and `workflow_dispatch` workflows from the **default
branch**, so webhook-triggered runs use whatever `main` holds. The first end-to-end run
therefore happens after merge: register the repository, add its webhook, label one real
pull request `qa-preview`, and check the run in this repository's Actions tab. That run
exercises the webhook, dispatch, SOPS decryption, branch resolution, health probes, plan
generation, Playwright, storage and the comment publisher together, and is the first of
the Phase 7.1 pilot runs.
