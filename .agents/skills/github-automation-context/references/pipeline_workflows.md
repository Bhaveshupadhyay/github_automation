# Pipeline Workflows & Execution Runbook

This document details the step-by-step runtime flow of the GitHub Actions workflow, Python orchestrator, and Slack thread interaction patterns.

---

## ⚡ Step-by-Step Runtime Execution Flow

### 1. Workflow Trigger
GitHub Actions receives a `repository_dispatch` event (`types: [ai_developer_task]`) or manual `workflow_dispatch` trigger.

### 2. Pre-Flight Target Resolution (`python -m automation.preflight`)
- Step `Run Python Pre-Flight Target Resolution` runs on the runner VM before cloning the workspace.
- **2-Stage Preflight Lookup**:
  - **Stage A**: Preflight inspects `USER_PROMPT`. If `USER_PROMPT` contains `"Previous Coding Request"`, it queries Slack API with `limit=1` (`SlackHistoryService.fetch_first_message_text()`) to inspect Turn 1 (the original root user prompt).
  - **Stage B**: Preflight extracts candidate `owner/repo` (e.g. `bhaveshupadhyay/culture_box`) and validates it via GitHub API (`https://api.github.com/repos/<candidate>`).
  - **Stage C**: If valid, exports `target_repo=<candidate>` to `$GITHUB_OUTPUT`.
  - **Stage D**: If no repo is specified on a Slack thread, preflight ignores default webhook payloads and outputs `target_repo=""`.

### 3. Workspace Cloning
- If `target_repo` is non-empty, GitHub Actions clones `https://github.com/<target_repo>.git` into `workspace_target`.
- If `target_repo` is empty `""`, GitHub Actions creates an empty directory `workspace_target` and proceeds.

### 4. Intent Classification (`GeminiIntentRouterService`)
- Runs `GeminiIntentRouterService.classify_intent()`.
- If `target_repo` is empty `""`, returns `CLARIFICATION_NEEDED` asking:
  > ❓ **Clarification Needed**: Which target repository (owner/repo) would you like me to work on? (e.g., `bhaveshupadhyay/culture_box`)
- Posts clarification to Slack thread and exits.

### 5. Code Development Execution (`CodeDevelopmentService`)
If intent is `CODE_DEVELOPMENT`:
- Cleans workspace via `WorkspaceCleanupService`.
- Fetches full Slack thread conversation history formatted as `### User (Human):` vs `### Assistant (AI):`.
- Updates & queries Graphify AST knowledge graph (`graphify update .` and `graphify query`).
- Injects workspace rules from `../.agents/rules` into `.agents/rules`.
- Executes native `agy` CLI engine:
  `agy --print "$full_prompt" --dangerously-skip-permissions --add-dir . --model gemini-3.6-flash --effort high --print-timeout 15m0s`
- Cleans up injected temporary files.

### 6. Code Change & Clarification Check
- If `agy` produced no file modifications on disk (`git status --porcelain` is empty):
  - Uses `ISummarizerService` (`GeminiLLMSummarizerService`) to distill `agy`'s output into a clean **1-sentence clarification question**.
  - Posts question to Slack thread and exits.

### 7. Metadata Generation & Git Release (`GitPRService`)
- Generates semantic branch name (e.g. `refactor/update-app-name-culture-box`), commit message, PR title, and PR body using `GeminiLLMMetadataService`.
- Configures git user as `github-actions[bot]`.
- Runs `git checkout -B <branch_name>` to preserve all local modifications.
- Commits and pushes branch to `https://github.com/<target_repo>.git`.
- Creates or updates Pull Request via `gh pr create` / `gh pr list`.

### 8. Slack Notification (`NotificationService`)
- Posts rich Markdown Slack message containing PR URL and summary of changes to the Slack thread.
