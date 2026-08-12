---
name: github-automation-context
description: >-
  Provides comprehensive architectural context, domain rules, and pipeline runbooks for the
  github_automation system. Activate this skill at the start of any conversation turn or session
  when building, refactoring, or debugging the AI Autonomous Developer workflow, preflight target resolution,
  Gemini intent routing, agy CLI engine execution, Graphify AST integration, or Slack notification services.
---

# GitHub Automation Master Context & Architecture Skill

Welcome to the `github_automation` codebase context skill. This document serves as the authoritative single source of truth for the system's architecture, design patterns, file responsibilities, and operational runbooks.

---

## 🏛️ System Architectural Overview

`github_automation` is an enterprise-grade AI Autonomous Developer system that receives user requests (via Slack threads or GitHub Action dispatches), classifies task intent, dynamically extracts target repository context, builds a Graphify AST knowledge graph, invokes the native Google Antigravity CLI (`agy`) engine to perform precise code refactoring, and automatically creates semantic Pull Requests with Slack notifications.

```
                                  [ User Request via Slack / Dispatch ]
                                                    │
                                                    ▼
                                  [ GitHub Actions Runner Execution ]
                                                    │
                                                    ▼
                             [ Step 1: Pre-Flight Target Repo Resolution ]
                                (automation/preflight.py)
                                                    │
                                                    ├─► Extract from User Prompt (Regex + GitHub API Check)
                                                    ├─► Extract from Slack Thread Turn 1 (limit=1 API)
                                                    └─► Fallback to Manual Input Target (Ignore default payload on Slack)
                                                    │
                                                    ▼
                             [ Step 2: Clone Target Workspace Repository ]
                                                    │
                                                    ▼
                                 [ Step 3: Master AI Orchestrator ]
                                     (automation/main.py)
                                                    │
             ┌──────────────────────────────────────┼──────────────────────────────────────┐
             │                                      │                                      │
             ▼                                      ▼                                      ▼
[ TaskIntent: CLARIFICATION_NEEDED ]  [ TaskIntent: CODE_DEVELOPMENT ]       [ TaskIntent: DEPLOYMENT_DEVOPS ]
   - Post 1-sentence Slack Q             - Build Graphify AST Context            - Trigger DevOps Deployment
   - Exit pipeline                       - Enforce workspace boundary            - Notify Slack channel
                                         - Stream agy engine execution
                                         - Generate PR metadata (REST/SDK)
                                         - Create & push Git branch (-B)
                                         - Post Slack PR notification
```

---

## 📚 Deep Reference Manuals

For granular details on specific subsystems, inspect the following reference documents:

1. [**Codebase Architecture & Clean Design**](./references/architecture.md): Deep dive into Clean Architecture layers, SOLID principles, Pydantic models, Dependency Injection container, and model split targets.
2. [**Pipeline Execution & Flow Runbooks**](./references/pipeline_workflows.md): Detailed 9-step pipeline execution sequence, Slack thread role formatting (`User (Human)` vs `Assistant (AI)`), and Git PR release management.

---

## 🛠️ Dual-Model Architecture Targets

The system strictly segregates responsibilities across two Google Gemini model targets:

| Component | Target Model | Invocation Layer | Purpose & Constraints |
| :--- | :--- | :--- | :--- |
| **Native `agy` Coding Engine** | **`gemini-3.6-flash`** | `agy --print ... --model gemini-3.6-flash --effort high --add-dir . --print-timeout 15m0s` | High-speed codebase refactoring. **Must** pass `--effort high` when calling `gemini-3.6-flash`. |
| **Python SDK & REST Fallback** | **`gemini-3.1-flash-lite`** | `GeminiIntentRouterService`, `GeminiLLMMetadataService`, `GeminiLLMSummarizerService` | Ultra-fast (< 0.8s) structured JSON classification, PR metadata generation, and text summarization. Uses `X-goog-api-key` header. |

---

## 📌 Core Domain Rules & Operational Directives

When modifying or extending this repository, **ALWAYS** enforce the following rules:

1. **No Hardcoded Default Repositories**:
   - Never set a hardcoded fallback repository string (e.g. `hiphomboombox_backend`) in code or workflows.
   - If a prompt or Slack thread does not specify a target repository, set `target_repo = ""` so `GeminiIntentRouterService` immediately asks the user for clarification on Slack.

2. **Clean Architecture & Dependency Injection**:
   - Keep `automation/main.py` ultra-thin (< 10 lines) acting purely as the high-level orchestrator router.
   - All services must implement abstract interfaces in `automation/interfaces/`.
   - Register all services in `Container` (`automation/dependency.py`). Never instantiate services directly inside other services.

3. **Workspace Boundary Enforcement**:
   - `agy` CLI must be instructed to edit files **strictly inside the current working directory (`.`)**. Never allow creation of scratch directories in `~/.gemini/antigravity-cli/scratch/`.

4. **1-Sentence Concise Clarification**:
   - If `agy` outputs a conversational response without code modifications, use `ISummarizerService` (`GeminiLLMSummarizerService`) to distill the text down to a **single polite 1-sentence question**. Never dump file lists or log noise to Slack.

5. **Safe Branch Switching (`git checkout -B`)**:
   - When pushing branch modifications in `GitPRService`, use `git checkout -B <branch_name>` to safely switch branches without crashing when uncommitted local files are present on disk.

6. **Authentication & Gateway Keys**:
   - Always retrieve API keys via `automation.utils.credentials.get_gemini_api_key()`.
   - Include `headers={"X-goog-api-key": api_key}` in all direct HTTP REST API calls to support Enterprise/Gateway API keys starting with `AQ.Ab8RN6I-...`.

---

## 🧪 Local Testing & Verification Commands

```bash
# 1. Test Dependency Container resolution
uv run python -c "from automation.dependency import container; print('CONTAINER VERIFIED')"

# 2. Test Pre-Flight Target Resolution
USER_PROMPT="@AutoGit AI bhaveshupadhyay/culture_box can you change the app name?" \
PAYLOAD_TARGET="bhaveshupadhyay/hiphomboombox_backend" \
GH_TOKEN=$(gh auth token) \
uv run python -m automation.preflight

# 3. Test Full Automation Main Pipeline locally
uv run --project .. python -m automation.main
```
