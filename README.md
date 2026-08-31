<img width="927" height="473" alt="Screenshot 2026-08-13 at 10 16 41 AM" src="https://github.com/user-attachments/assets/60612c2a-a52f-4347-82ef-ce19f354986a" />

# AutoPR Slack AI — Autonomous AI Developer

[![npm version](https://img.shields.io/npm/v/autopr-slack.svg?color=cb3837&logo=npm)](https://www.npmjs.com/package/autopr-slack)
[![PyPI version](https://img.shields.io/pypi/v/github-automation-ai.svg?color=3775a9&logo=pypi)](https://pypi.org/project/github-automation-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

AutoPR Slack AI is a **zero-clone, serverless autonomous AI developer pipeline**. It turns natural language task requests from Slack or Telegram into tested, production-grade GitHub Pull Requests in seconds.

No manual cloning, no local Python environment setup, and zero runner compute costs on your central repository. Everything executes directly inside your target repository's GitHub Actions runner using the Google Antigravity Engine (`agy`) and Graphify AST indexing.

---

<img width="1152" height="720" alt="slack_bot" src="https://github.com/user-attachments/assets/1f5b6b1e-834c-4be0-9083-0610f640b3b9" />

---

## ⚡ 1-Command Quickstart (Zero-Clone Setup)

You don't need to clone this repository. Open your terminal inside any GitHub repository (or any empty folder) and run:

```bash
npx autopr-slack
```

*(or `npx autopr-slack init`)*

The interactive wizard configures your entire autonomous developer pipeline in **5 guided steps**:

```text
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ⚡ AutoPR Slack AI — Autonomous AI Developer               ║
║   Zero-Clone Edge & GitHub Actions Setup Wizard               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝

[1/5] Diagnostics & Target Repository Resolution
  ✔ Node.js Runtime: v22.x
  ✔ Git CLI & GitHub CLI (gh) authenticated
  ✔ Target Repository: your-org/your-repo

[2/5] Cloudflare Worker Fast-Path Deployment
  ✔ Deploys serverless edge webhook via Wrangler (zero idle server costs)
  ✔ Output endpoint: https://autopr-your-repo.subdomain.workers.dev

[3/5] 1-Click Slack App Manifest Generation
  ✔ Generates slack-app-manifest.json with pre-configured /code slash commands,
    event subscriptions, and bot scopes

[4/5] GitHub Repository Secrets Provisioning
  ✔ Automatically provisions PAT_TOKEN, SLACK_BOT_TOKEN, and AGY_AUTH_CONFIG
    directly to your GitHub repository via gh CLI

[5/5] GitHub Actions Workflow Injection
  ✔ Injects .github/workflows/autopr.yml using ultra-fast uvx execution
  ✔ Auto-pushes workflow to your remote GitHub repository
```

---

## 📖 End-to-End Setup Instructions (Start to Finish)

### Step 1: Run the Setup Wizard

Inside your terminal, execute:

```bash
npx autopr-slack
```

The wizard will prompt you for:
- **GitHub Workflow Target Repository**: `owner/repo` (auto-detected if inside a git repo).
- **Cloudflare Worker Name**: Custom name or default `autopr-<repo>`.
- **GitHub Personal Access Token (PAT)**: Classic token with `repo` and `workflow` scopes.
- **Gemini API Key / Antigravity Config**: For intent classification and headless engine reasoning.

---

### Step 2: Create the Slack App (1-Click Manifest)

The wizard creates a file named `slack-app-manifest.json` in your project folder.

1. Go to [**api.slack.com/apps**](https://api.slack.com/apps) and click **Create New App**.
2. Select **From an app manifest**.
3. Choose your Slack workspace.
4. Open `slack-app-manifest.json`, copy its entire content, and paste it into Slack.
5. Click **Create**, then click **Install to Workspace**.
6. Copy your **Bot User OAuth Token** (`xoxb-...`) and **Signing Secret** back into the terminal wizard (or run `npx autopr-slack secrets`).

---

### Step 3: Invite Bot to Your Slack Channel

In your Slack workspace:
1. Open the channel where you want the bot to operate (e.g. `#dev-team` or `#eng-prs`).
2. Type `/invite @AutoPR AI` (or mention `@AutoPR AI` and click **Add to Channel**).

---

### Step 4: Issue Commands & Watch PRs Open Automatically!

Type a slash command directly in Slack:

```slack
/code Add Redis caching to the get_user_profile endpoint
```

Or target any repository dynamically:

```slack
/code org/api-gateway Fix race condition in authentication token refresh
```

#### What happens next:
1. **Sub-second Edge Acknowledgement**: Cloudflare Worker validates the request in `<50ms` and replies in your Slack thread with a progress indicator.
2. **Intent & Repository Resolution**: Gemini extracts repository targets, branches, and task constraints.
3. **Graphify AST Indexing**: Actions runner constructs a lightweight AST knowledge graph of the target repository, reducing token overhead by up to 50%.
4. **Antigravity AI Engine (`agy`)**: Generates precision code diffs, runs test suites (`pytest`, `npm test`, etc.), and verifies fixes with zero regressions.
5. **Verified PR Created**: Pushes a new feature branch, opens a GitHub Pull Request, and posts the PR link and AI summary directly back into your Slack thread!

---

## 🛠️ CLI Subcommands & Tooling

In addition to the master wizard, you can run individual modules on demand:

| Command | Description |
| :--- | :--- |
| `npx autopr-slack init` | Runs the full 5-step interactive setup wizard. |
| `npx autopr-slack workflow` | Injects the GitHub Actions workflow into current repository. |
| `npx autopr-slack deploy-worker` | Builds and deploys the Cloudflare Worker serverless edge webhook. |
| `npx autopr-slack manifest` | Generates a 1-click Slack App Manifest JSON file. |
| `npx autopr-slack secrets` | Configures GitHub Actions and Cloudflare secrets via `gh` CLI. |
| `npx autopr-slack check` | Runs system diagnostics and preflight credential checks. |

---

## 🐍 Python Engine via PyPI (`uvx`)

The core execution engine is also published on PyPI as [`github-automation-ai`](https://pypi.org/project/github-automation-ai/):

```bash
# Run the automation engine on-demand anywhere without installing:
uvx --from github-automation-ai autopr

# Or test preflight target resolution locally:
uvx --from github-automation-ai python -m automation.preflight --prompt "org/repo Fix auth token refresh"
```

---

## 🏛️ System Architecture

```text
+---------------------+
| Slack / Telegram    |
| (Slash Command)     |
+----------+----------+
           | Webhook HTTP POST
           v
+---------------------+
| Cloudflare Worker   |  <-- Sub-50ms Fast-Path & Gemini Intent Parsing
+----------+----------+
           | Repository Dispatch API Event
           v
+---------------------+
| GitHub Actions VM   |  <-- Executes on YOUR Repository Runner
| (Autonomous Engine) |
|                     |
| ├── 1. Restore Antigravity Session (AGY_AUTH_CONFIG)
| ├── 2. Preflight Target Resolution (automation/preflight.py)
| ├── 3. Graphify AST Knowledge Graph Indexing (Cuts tokens by 50%)
| ├── 4. Google Antigravity Execution (agy run -y "$PROMPT")
| ├── 5. Automated Unit Testing & Lint Validation
| └── 6. GitHub Pull Request Creation (gh pr create)
+----------+----------+
           | Execution Result Callback
           v
+---------------------+
| Slack Thread Reply  |  <-- Posts PR URL & AI Summary back to thread
+---------------------+
```

---

## 🔐 Environment & Security Configuration

All sensitive keys remain strictly inside your private GitHub Repository Secrets and Cloudflare Worker environment:

| Secret Name | Purpose |
| :--- | :--- |
| `PAT_TOKEN` | GitHub Personal Access Token (Classic) with `repo`, `workflow`, and `write:packages` scopes. |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) for posting threaded replies. |
| `SLACK_SIGNING_SECRET` | Slack Signing Secret for cryptographic webhook signature verification. |
| `AGY_AUTH_CONFIG` | Base64-encoded session configuration file (`~/.gemini/config`) for Google Antigravity CLI. |
| `GEMINI_API_KEY` | Optional Gemini API Key used for fast edge intent classification and repository resolution. |

---

## 🤝 Contributing

1. Fork the repository and create a feature branch (`git checkout -b feat/your-feature`).
2. Follow Clean Architecture and PEP 8 conventions.
3. Run tests with `uv run pytest`.
4. Open a Pull Request detailing the changes and verification steps.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
