<img width="927" height="473" alt="Screenshot 2026-08-13 at 10 16 41 AM" src="https://github.com/user-attachments/assets/60612c2a-a52f-4347-82ef-ce19f354986a" />

# AutoPR Slack AI — Autonomous AI Developer

[![npm version](https://img.shields.io/npm/v/autopr-slack.svg?color=cb3837&logo=npm)](https://www.npmjs.com/package/autopr-slack)
[![PyPI version](https://img.shields.io/pypi/v/github-automation-ai.svg?color=3775a9&logo=pypi)](https://pypi.org/project/github-automation-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

AutoPR Slack AI is a **zero-clone, serverless autonomous AI developer pipeline**. It turns natural language task requests from Slack into tested, production-grade GitHub Pull Requests in seconds.

---

<img width="1152" height="720" alt="slack_bot" src="https://github.com/user-attachments/assets/1f5b6b1e-834c-4be0-9083-0610f640b3b9" />

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

The bot will open a pull request in your GitHub repository within minutes.

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
| `GEMINI_API_KEY` | Gemini API Key for intent classification. |

---

## License

[MIT](LICENSE)
