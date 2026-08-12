# Architecture & Component Reference Manual

This document provides a deep structural breakdown of every module, service, interface, and domain model in the `github_automation` project.

---

## 📂 File Directory & Layer Mapping

```text
github_automation/
├── .github/workflows/
│   └── ai-autonomous-developer.yml      # Master GitHub Actions CI/CD runner workflow
├── automation/
│   ├── domain/
│   │   ├── constants.py                  # Default models (gemini-3.6-flash, gemini-3.1-flash-lite) & SpecialTags
│   │   └── models.py                     # Pydantic models (TaskIntent, WorkflowEnvironment, GitPRDetails)
│   ├── interfaces/
│   │   ├── intent_router_interface.py    # IIntentRouterService abstract interface
│   │   ├── metadata_service_interface.py # IMetadataService abstract interface
│   │   ├── code_development_interface.py # ICodeDevelopmentService abstract interface
│   │   └── summarizer_interface.py       # ISummarizerService abstract interface
│   ├── services/
│   │   ├── gemini_intent_router_service.py # Structured intent classification (SDK + 0.8s REST fallback)
│   │   ├── gemini_metadata_service.py      # Git branch, commit title & PR description generator
│   │   ├── gemini_summarizer_service.py    # 1-sentence clean clarification text summarizer
│   │   ├── code_development_service.py     # Graphify AST + agy CLI engine pipeline runner
│   │   ├── deployment_service.py           # Operational DevOps deployment handler
│   │   ├── notification_service.py         # Rich Slack message posting via Slack Webhook/API
│   │   ├── slack_history_service.py        # Slack conversations.replies thread history retriever
│   │   ├── git_pr_service.py               # Git branch management (-B) and gh pr create/update
│   │   └── cleanup_service.py              # Injected .agents, rules, graphify cleanup
│   ├── utils/
│   │   └── credentials.py                # Centralized API key detection & model normalization
│   ├── dependency.py                     # Dependency Injection Container singleton
│   ├── preflight.py                      # Pre-flight runner step for target repository resolution
│   └── main.py                           # 10-line Master AI Orchestrator Entrypoint
```

---

## 🧩 Dependency Injection Container (`automation/dependency.py`)

All services are decoupled via abstract interfaces and managed through the `Container` singleton:

```python
from automation.dependency import container

# Resolving registered services:
intent_router = container.get_intent_router_service()
code_dev_service = container.get_code_development_service()
summarizer = container.get_summarizer_service()
cleanup = container.get_cleanup_service()
```

---

## 🔑 Credential & Model Utilities (`automation/utils/credentials.py`)

- **`get_gemini_api_key()`**: Checks `AGY_API_KEY`, `GEMINI_API_KEY`, `ANTIGRAVITY_API_KEY`, and falls back to `~/.gemini/oauth_creds.json`.
- **`normalize_gemini_model(model_name)`**: Normalizes model requests to `gemini-3.1-flash-lite` for Python SDK and REST API invocations.

---

## 🎯 Target Repository Extraction (`extract_target_repo`)

Located in [`automation/domain/models.py`](file:///Users/bhaveshupadhyay/IdeaProjects/github_automation/automation/domain/models.py):

1. Strips full URLs (`https://...` or `github.com/...`) from prompt string.
2. Uses boundary-aware regex `r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b"` to extract bare `owner/repo` candidates (e.g. `bhaveshupadhyay/culture_box`).
3. Ignores header sentinel phrases starting with `original`.
4. If no valid candidate is found, returns `""` (no default fallback repository).
