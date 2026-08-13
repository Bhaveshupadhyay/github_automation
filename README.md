# AutoPR Slack AI — Serverless Autonomous AI Developer

AutoPR Slack AI is an enterprise-grade serverless autonomous AI developer pipeline. It accepts developer task requests directly from Slack or Telegram, resolves target repositories using Gemini intent classification and preflight context resolution, and executes the Google Antigravity Engine (`agy`) within GitHub Actions to generate, test, and open verified Pull Requests automatically.

---

## Product Demo

<video src="product_demo/brag.mp4" controls width="100%" poster="product_demo/brag.jpg"></video>

> **Demo Video File:** [`product_demo/brag.mp4`](product_demo/brag.mp4)  
> **Poster Thumbnail:** [`product_demo/brag.jpg`](product_demo/brag.jpg)

---

## Key Features

- **Serverless Edge Webhook Handling**: Cloudflare Workers intercept incoming Slack slash commands and Telegram webhooks with sub-second response times.
- **AI Intent & Repository Resolution**: Integrates Gemini models to parse unstructured prompt text, determine target GitHub repositories, and resolve default branches.
- **Headless Antigravity Engine Execution**: Runs the Google Antigravity (`agy`) CLI inside ephemeral GitHub Actions runner VMs with session authentication.
- **Automated Pull Request Lifecycle**: Automatically creates target feature branches, applies precision code modifications, runs verification, and submits GitHub Pull Requests.
- **Threaded Status Feedback**: Updates Slack and Telegram discussion threads in real-time with execution status, PR links, and AI summarization.
- **Interactive Sandbox & Web UI**: Includes a local web interface (`index.html`, `style.css`, `app.js`) for simulating slash commands, inspecting architecture flows, and testing deployment configurations.

---

## System Architecture

```text
+---------------------+
| Slack / Telegram    |
| (Slash Command)     |
+----------+----------+
           | Webhook HTTP POST
           v
+---------------------+
| Cloudflare Worker   |  <-- Fast-path validation & Gemini intent parsing
+----------+----------+
           | Repository Dispatch API Event
           v
+---------------------+
| GitHub Actions VM   |
| (Runner Engine)     |
|                     |
| ├── 1. Environment & Auth Restoration (AGY_AUTH_CONFIG)
| ├── 2. Preflight Target Resolution (automation/preflight.py)
| ├── 3. Antigravity CLI Execution (agy run -y "$PROMPT")
| ├── 4. Automated Verification & Git Commit
| └── 5. Pull Request Submission (gh pr create)
+----------+----------+
           | Execution Result Callback
           v
+---------------------+
| Slack Thread Reply  |  <-- Posts PR URL & AI summary back to thread
+---------------------+
```

---

## Project Structure

```text
github_automation/
├── .github/
│   └── workflows/
│       ├── ai-autonomous-developer.yml   # Primary GitHub Actions execution workflow
│       ├── deploy-pages.yml             # GitHub Pages deployment workflow
│       └── test-workflow.yml            # Integration test workflow
├── automation/
│   ├── core/                            # Core engine configurations & logging
│   ├── domain/                          # Business entities and value objects
│   ├── interfaces/                      # API clients and GitHub/Slack adapters
│   ├── services/                        # Intent routing, preflight resolution, summarization
│   ├── preflight.py                     # Repository & target branch preflight script
│   └── main.py                          # Automation entrypoint
├── cloudflare-worker/
│   ├── worker.js                        # Worker entrypoint for dispatching events
│   ├── slack-worker.js                  # Slack webhook & challenge handler
│   └── wrangler.toml                    # Cloudflare Worker configuration manifest
├── product_demo/
│   ├── brag.mp4                         # Demonstration video
│   └── brag.jpg                         # Video poster frame
├── runner.py                            # Standalone Python engine execution orchestrator
├── pyproject.toml                       # Python project configuration (uv / hatchling)
├── index.html                           # Sandbox Web UI structure
├── style.css                            # Sandbox Web UI styling
└── app.js                               # Sandbox Web UI interactive logic
```

---

## Prerequisites

- **Python**: Version 3.12 or higher.
- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`.
- **Node.js**: Version 18 or higher (for Cloudflare Wrangler CLI).
- **GitHub CLI**: `gh` CLI installed and authenticated with repository permissions.
- **Antigravity CLI**: `agy` executable installed on the worker environment or GitHub Actions runner.

---

## Configuration & Environment Secrets

### 1. GitHub Repository Secrets

Configure the following secrets under **Settings > Secrets and variables > Actions** in your GitHub repository:

| Secret Name | Description |
| :--- | :--- |
| `AGY_AUTH_CONFIG` | Base64-encoded session configuration file (`~/.gemini/config`) for Google Antigravity CLI authentication. |
| `PAT_TOKEN` | GitHub Personal Access Token (Classic) with `repo`, `workflow`, and `write:packages` scopes. |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) for sending thread updates and status messages. |
| `GEMINI_API_KEY` | Optional API key for Gemini models used during preflight intent resolution. |

### 2. Cloudflare Worker Secrets

Set worker secrets using `wrangler secret put`:

```bash
cd cloudflare-worker
npx wrangler secret put GITHUB_PAT
npx wrangler secret put SLACK_BOT_TOKEN
npx wrangler secret put GEMINI_API_KEY
```

---

## Deployment & Setup

### Deploying the Cloudflare Worker

1. Navigate to the worker directory:
   ```bash
   cd cloudflare-worker
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Deploy to your Cloudflare account:
   ```bash
   npx wrangler deploy
   ```
4. Copy the output Worker HTTP endpoint URL and configure it as your Request URL in the Slack App settings under **Slash Commands** (e.g. `/code` or `/autopr`).

---

## Local Development & Testing

### Running Python Tests

Execute test suites using `uv`:

```bash
uv run pytest
```

### Testing Preflight Target Resolution Locally

Run the preflight resolution module locally to verify repository intent parsing:

```bash
uv run python -m automation.preflight --prompt "bhaveshupadhyay/app Add Redis caching to user service"
```

### Running the Cloudflare Worker Locally

Start local Wrangler environment:

```bash
cd cloudflare-worker
npx wrangler dev
```

---

## Contributing Guidelines

We welcome contributions to AutoPR Slack AI. Please follow these guidelines when submitting pull requests or opening issues:

### Branching Strategy

- `main`: Production-ready branch. All changes enter via Pull Requests.
- Feature branches: Use prefix `feat/` (e.g., `feat/add-telegram-adapter`).
- Bug fix branches: Use prefix `fix/` (e.g., `fix/intent-router-fallback`).
- Documentation: Use prefix `docs/` (e.g., `docs/update-architecture-spec`).
- Refactoring: Use prefix `refactor/` (e.g., `refactor/clean-architecture`).

### Pull Request Process

1. Fork the repository and create a new feature branch from `main`.
2. Ensure code follows clean architecture patterns, PEP 8 standards, and includes proper type hints.
3. Write or update unit tests for any new or modified functionality.
4. Run `uv run pytest` to ensure all tests pass.
5. Submit a Pull Request detailing the problem solved, changes made, and verification steps taken.
6. Obtain approval from at least one repository maintainer before merging.

---

## License & Security

This project is distributed under the MIT License. For security vulnerabilities or concerns, please open an issue or contact the maintainers directly.
