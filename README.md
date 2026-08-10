# 🚀 Serverless Antigravity AI Autonomous Developer Setup

An enterprise, serverless AI developer pipeline triggered from **Slack** or **Telegram** via **Cloudflare Workers**, executing **Google Antigravity Engine (`agy`)** inside **GitHub Actions** with zero API costs using your Google Pro Account.

---

## 🏗️ Architecture Overview

```text
[ Slack / Telegram ] 
       │
       ▼ (Webhook Request)
[ Cloudflare Worker ] 
       │
       ▼ (Dispatches GitHub Repository Event)
[ GitHub Actions Runner VM ]
       │
       ├── 1. Restores Google Pro Auth Credentials (AGY_AUTH_CONFIG)
       ├── 2. Installs & Launches Antigravity CLI (agy run -y "$PROMPT")
       ├── 3. Executes Multi-Agent Reasoning, AST Graphing & Precision Diffs
       └── 4. Pushes Branch & Opens GitHub Pull Request (gh pr create)
```

---

## 🔑 Required Secrets Setup

### 1. GitHub Repository Secrets (`github_automation`)

| Secret Name | Description |
| :--- | :--- |
| `AGY_AUTH_CONFIG` | Base64-encoded `~/.gemini/config` containing Google Pro OAuth session |
| `PAT_TOKEN` | GitHub Personal Access Token (Classic) with `repo` and `workflow` scopes |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) |

---

### 2. Cloudflare Worker Secrets (`wrangler secret put`)

| Secret Name | Description |
| :--- | :--- |
| `GITHUB_PAT` | GitHub Personal Access Token (`ghp_...`) for `repository_dispatch` |
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token (`xoxb-...`) for thread messaging |

---

## 💬 Usage

Send a command in Slack or Telegram:

```text
/code bhaveshupadhyay/hiphomboombox_backend Add caching to get_trending_posts
```

Antigravity Engine (`agy`) will execute on GitHub Actions, modify target code in-place, and open a Pull Request ready for human review!
