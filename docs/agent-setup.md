# Agent Setup Guide

This guide is for coding agents (e.g. Google Antigravity, GitHub Copilot Workspace, Cursor, Devin) to set up AutoPR Slack AI non-interactively without human input or TTY prompts.

---

## How the Wizard Works Internally

The `npx autopr-slack` wizard is interactive by default. When invoked by a coding agent, all steps must be driven via environment variables, CLI flags, or direct subcommand invocations to bypass TTY prompts.

---

## Prerequisites

The following tools must be installed and authenticated in the agent's environment before proceeding.

### GitHub CLI

```bash
brew install gh   # or: apt-get install gh
gh auth login --with-token <<< "$GITHUB_TOKEN"
```

### Wrangler CLI (Cloudflare Workers)

The Cloudflare Worker deployment step requires Wrangler authenticated with a Cloudflare API token. Do **not** use `wrangler login` (requires browser). Use the token directly:

```bash
npm install -g wrangler
export CLOUDFLARE_API_TOKEN="your-cloudflare-api-token"
export CLOUDFLARE_ACCOUNT_ID="your-cloudflare-account-id"
```

Wrangler reads these environment variables automatically — no interactive login needed.

### Google Antigravity CLI

The Antigravity CLI must be installed and its OAuth credentials present on disk. The wizard reads them automatically from `~/.gemini/oauth_creds.json` and uploads them as `AGY_AUTH_CONFIG` to GitHub Secrets.

```bash
npm install -g @google/antigravity
agy auth login   # completes browser OAuth flow once
```

After login, the session is persisted at:

```
~/.gemini/oauth_creds.json                              → uploaded as AGY_AUTH_CONFIG
~/.gemini/antigravity-cli/antigravity-oauth-token       → uploaded as AGY_SESSION_DATA
```

Both are base64-encoded before being written to GitHub Secrets. The GitHub Actions workflow decodes them at runtime:

```bash
echo "$AGY_AUTH_CONFIG" | tr -d '\r\n ' | base64 -d > ~/.gemini/oauth_creds.json
echo "$AGY_SESSION_DATA" | tr -d '\r\n ' | base64 -d > ~/.gemini/antigravity-cli/antigravity-oauth-token
```

To encode and set these manually without running the wizard:

```bash
# Encode
AGY_AUTH_CONFIG=$(base64 -i ~/.gemini/oauth_creds.json | tr -d '\n')
AGY_SESSION_DATA=$(base64 -i ~/.gemini/antigravity-cli/antigravity-oauth-token | tr -d '\n')

# Upload directly via gh CLI
gh secret set AGY_AUTH_CONFIG --body "$AGY_AUTH_CONFIG" --repo owner/repo
gh secret set AGY_SESSION_DATA --body "$AGY_SESSION_DATA" --repo owner/repo
```

---

## Non-Interactive Setup (Subcommand by Subcommand)

Instead of running the interactive wizard, invoke each module independently:

### Step 1: Install the GitHub Actions Workflow

```bash
npx autopr-slack workflow
```

This writes `.github/workflows/autopr.yml` to the current repository and pushes it to the remote via `gh` CLI.

### Step 2: Deploy the Cloudflare Worker

Requires `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set in environment.

```bash
npx autopr-slack deploy-worker
```

This runs `wrangler deploy` and outputs the Worker URL (e.g. `https://autopr-your-repo.subdomain.workers.dev`).

### Step 3: Generate the Slack App Manifest

```bash
npx autopr-slack manifest
```

Writes `slack-app-manifest.json` to the current directory. The Slack App must then be created via the Slack API or manually at [api.slack.com/apps](https://api.slack.com/apps).

> Note: Slack App creation cannot be fully automated — it requires a browser-based OAuth installation step. This is a Slack platform constraint, not a limitation of this project. After creating the app, the `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` can be passed in the next step.

### Step 4: Provision GitHub Secrets

```bash
npx autopr-slack secrets
```

Or set all secrets directly via `gh` CLI to avoid any remaining prompts:

```bash
gh secret set PAT_TOKEN             --body "$PAT_TOKEN"              --repo owner/repo
gh secret set SLACK_BOT_TOKEN       --body "$SLACK_BOT_TOKEN"        --repo owner/repo
gh secret set SLACK_SIGNING_SECRET  --body "$SLACK_SIGNING_SECRET"   --repo owner/repo
gh secret set AGY_AUTH_CONFIG       --body "$AGY_AUTH_CONFIG"        --repo owner/repo
gh secret set AGY_SESSION_DATA      --body "$AGY_SESSION_DATA"       --repo owner/repo
gh secret set GEMINI_API_KEY        --body "$GEMINI_API_KEY"         --repo owner/repo
```

### Step 5: Verify Setup

```bash
npx autopr-slack check
```

---

## Full Environment Variable Reference

### Local Setup (not uploaded to GitHub)

These are only needed on the machine or agent environment running the setup commands. They are consumed by Wrangler during the one-time `deploy-worker` step and never stored in GitHub Secrets.

| Variable | Description |
| :--- | :--- |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token with `Workers:Edit` permission. Used by Wrangler to deploy the edge worker. |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID (found in the dashboard sidebar). |

### GitHub Actions Secrets (uploaded via `gh secret set`)

These are provisioned into the target GitHub repository and used by the Actions workflow at runtime.

| Secret | Required | Description |
| :--- | :---: | :--- |
| `PAT_TOKEN` | Yes | GitHub Classic PAT with `repo` and `workflow` scopes. |
| `SLACK_BOT_TOKEN` | Yes | Slack Bot User OAuth Token (`xoxb-...`). |
| `SLACK_SIGNING_SECRET` | Yes | Slack Signing Secret for webhook verification. |
| `AGY_AUTH_CONFIG` | Yes | Base64-encoded contents of `~/.gemini/oauth_creds.json`. |
| `AGY_SESSION_DATA` | Yes | Base64-encoded contents of `~/.gemini/antigravity-cli/antigravity-oauth-token`. |
| `GEMINI_API_KEY` | Optional | Gemini API Key for fast intent classification at the edge. |

---

## Notes for Agent Implementors

- The wizard uses `execFileSync("gh", [...args])` with argument arrays, not shell string interpolation. There is no shell injection surface — arguments are passed directly.
- Worker name is sanitized to `^[a-z0-9-]+$`. Pass a lowercase alphanumeric name when invoking `deploy-worker`.
- The `workflow` subcommand detects whether `gh` is authenticated and pushes directly to the remote. If `gh` is not available, it writes the file locally and expects a subsequent `git push`.
- Both `AGY_AUTH_CONFIG` and `AGY_SESSION_DATA` are decoded on the GitHub Actions runner at job start. The runner is ephemeral and the decoded files exist only for the duration of the job.
