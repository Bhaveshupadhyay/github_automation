<img width="927" height="473" alt="Screenshot 2026-08-13 at 10 16 41 AM" src="https://github.com/user-attachments/assets/60612c2a-a52f-4347-82ef-ce19f354986a" />

# AutoPR Slack AI — Autonomous AI Developer

[![npm version](https://img.shields.io/npm/v/autopr-slack.svg?color=cb3837&logo=npm)](https://www.npmjs.com/package/autopr-slack)
[![PyPI version](https://img.shields.io/pypi/v/github-automation-ai.svg?color=3775a9&logo=pypi)](https://pypi.org/project/github-automation-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

AutoPR Slack AI is a **zero-clone, serverless autonomous AI developer pipeline**. It turns natural language task requests from Slack into tested, production-grade GitHub Pull Requests in seconds, and QA-tests those pull requests on request: it runs the app, drives it through generated test journeys, and posts the recording back to the PR and the Slack thread.

---

<img width="1152" height="720" alt="slack_bot" src="https://github.com/user-attachments/assets/1f5b6b1e-834c-4be0-9083-0610f640b3b9" />

---

## Prerequisites

Before running the setup wizard, you need the following tools installed and authenticated:

**1. GitHub CLI**

```bash
brew install gh
gh auth login
```

**2. Wrangler CLI (Cloudflare)**

Required to deploy the edge webhook worker.

```bash
npm install -g wrangler
wrangler login
```

**3. Google Antigravity CLI**

Required for the autonomous AI execution engine. Install and authenticate it locally:

```bash
npm install -g @google/antigravity
agy auth login
```

The wizard automatically reads your local Antigravity session (`~/.gemini/config`) and uploads it as the `AGY_AUTH_CONFIG` secret to your GitHub repository. No manual base64 encoding required.

---

## Installation

```bash
npx autopr-slack
```

The setup wizard will guide you through the following:

1. **Target Repository** — Select the GitHub repository to connect (`owner/repo`).
2. **Workflow Setup** — Installs the GitHub Actions workflow into your repository.
3. **Cloudflare Worker** — Deploys the edge webhook that routes Slack commands.
4. **Slack App** — Generates `slack-app-manifest.json` for 1-click Slack app creation.
5. **Secrets** — Provisions all required GitHub and Cloudflare secrets automatically.

---

## Slack App Setup

After running the wizard:

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App > From an app manifest**.
2. Paste the contents of `slack-app-manifest.json` and click **Create**.
3. Click **Install to Workspace** and copy your **Bot Token** (`xoxb-...`) and **Signing Secret**.
4. Enter these values back into the wizard when prompted.

Then invite the bot to your Slack channel:

```
/invite @AutoPR AI
```

---

## Usage

Type a command in Slack:

```
/code Fix the authentication bug in the login endpoint
```

Or tag the bot in any thread:

```
@AutoPR AI target repo: owner/frontend  add an admin panel to view, add, update and delete posts
```

The bot will open a pull request in your GitHub repository within minutes.

---

## QA Testing

Ask the bot to test a pull request, and it runs the PR's code, generates test journeys from the diff, runs them while recording, and reports back.

**What to write in Slack.** Tag the bot and ask it to test, not to change code:

| Where | Message |
| :--- | :--- |
| In the thread where the bot opened the PR | `@AutoPR AI run QA on this PR` |
| Anywhere, naming the PR | `@AutoPR AI QA test owner/frontend#12` |
| With a backend PR, so it starts at once | `@AutoPR AI test owner/frontend#12 against owner/backend#8` |

Without a named backend PR, the bot asks which backend to test against. Reply with a backend PR (`owner/backend#8`), `main`, or `dev` (the deployed dev API, no backend started). The reply doesn't need a tag.

**What you get back:**

1. The `qa-web-preview` (Playwright) or `qa-mobile-preview` (Maestro on an Android emulator) workflow runs in the automation repository's Actions tab.
2. It checks out the PR's head commit, starts the database, backend and frontend, and waits for their health checks.
3. It generates test journeys from the diff, runs them, and records video.
4. It posts one comment on the PR with the result, the video and a preview GIF, and replies in the Slack thread. A failing run still posts the recording of its failure.

**Tips:**

- Don't put words like "add", "fix" or "change" in a QA request. The bot may read it as a coding task and open a new PR instead.
- A PR from a fork, a closed PR, or a PR on an unregistered repository is refused.
- A second request for the same PR cancels the run still testing it.

**Registering a repository.** QA runs centrally in the automation repository. The repository under test needs no workflow and no secret. Add it to `contracts/qa-targets.json`:

```json
{
  "targets": {
    "owner/frontend": {
      "platform": "web",
      "backend_repo": "owner/backend",
      "backend_default_branch": "main",
      "frontend_url": "http://localhost:5173",
      "dev_api_url": "https://api-dev.example.com"
    }
  }
}
```

Both repositories need a `qa-contract.json` describing the app, and the backend needs its SOPS-encrypted `.env.qa.enc` and `.sops.yaml`. See [QA CI Pipeline](docs/qa-ci-pipeline.md) for every field, the guardrails and manual re-runs.

---

## CLI Reference

| Command | Description |
| :--- | :--- |
| `npx autopr-slack` | Run the full setup wizard. |
| `npx autopr-slack workflow` | Inject the GitHub Actions workflow. |
| `npx autopr-slack deploy-worker` | Deploy the Cloudflare Worker. |
| `npx autopr-slack manifest` | Generate the Slack App manifest file. |
| `npx autopr-slack secrets` | Provision GitHub repository secrets. |
| `npx autopr-slack check` | Run preflight diagnostics. |

---

## Python Engine

The core engine is also available via PyPI:

```bash
uvx --from github-automation-ai autopr
```

---

## Required Secrets

| Secret | Purpose |
| :--- | :--- |
| `PAT_TOKEN` | GitHub Personal Access Token with `repo` and `workflow` scopes. |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`). |
| `SLACK_SIGNING_SECRET` | Slack Signing Secret for webhook verification. |
| `AGY_AUTH_CONFIG` | Base64-encoded Antigravity CLI session config. |
| `AGY_SESSION_DATA` | Base64-encoded Antigravity CLI OAuth token (`~/.gemini/antigravity-cli/antigravity-oauth-token`). |
| `GEMINI_API_KEY` | Gemini API Key for intent classification, PR metadata and QA test generation. |

QA testing adds these, all in the automation repository:

| Secret | Purpose |
| :--- | :--- |
| `SOPS_AGE_KEY` | Decrypts the backend's `.env.qa.enc`. Required for QA. |
| `QA_READ_TOKEN` | Read-only token to clone private repositories under test. Public ones don't need it. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` | Cloudflare R2 storage for QA videos and GIFs. Without them, media falls back to workflow artifacts. |

---

## License

[MIT](LICENSE)

---

## Docs

- [Agent Setup Guide](docs/agent-setup.md) — Non-interactive setup for coding agents (Antigravity, Copilot Workspace, Devin, Cursor, etc.)
- [QA CI Pipeline](docs/qa-ci-pipeline.md) — How QA runs are requested, isolated and published, and how to register a repository.
- [QA Publishing](docs/qa-publishing.md) — The PR comment, media storage and Slack reply.
