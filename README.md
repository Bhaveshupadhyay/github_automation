# ⚡ AutoPR Slack AI — Serverless Autonomous AI Developer

An enterprise, serverless AI developer pipeline triggered directly from **Slack** or **Telegram** via **Cloudflare Workers**, executing **Google Antigravity Engine (`agy`)** inside **GitHub Actions** with zero API costs using your Google Pro session authentication.

---

## 🎬 Product Launch Video

<video src="product_demo/brag.mp4" controls width="100%" poster="product_demo/brag.jpg"></video>

> 📹 **Launch Video File:** [`product_demo/brag.mp4`](product_demo/brag.mp4)  
> 🖼️ **Poster Thumbnail:** [`product_demo/brag.jpg`](product_demo/brag.jpg)

---

## 🌟 Interactive Landing Page & Sandbox

This repository includes a dark-mode landing page and real-time interactive Slackbot simulator (`index.html`, `style.css`, `app.js`).

### Features:
- 💬 **Live Slack Slash Command Simulator**: Test prompts (`/code Add Redis caching`) and view simulated PR diffs in real-time.
- ⚡ **Architecture Flowchart**: Step-by-step visual of Slack → Cloudflare Worker → GitHub Actions (`agy`) → PR Created.
- 📋 **Quick Deployment Tabs**: Copy-paste deployment snippets for Cloudflare Wrangler, Slack Slash Commands, and GitHub Secrets.

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

Send a slash command in Slack or Telegram:

```text
/code bhaveshupadhyay/app Add Redis caching to get_user_profile
```

Antigravity Engine (`agy`) will execute on GitHub Actions, modify target code in-place, and open a Pull Request ready for review!
