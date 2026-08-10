# ⚡ GitHub Automation (`github_automation`)

Project Location: `/Users/bhaveshupadhyay/IdeaProjects/github_automation`

An autonomous serverless AI agent system powered by **Google Gemini 2.0 Flash**, **Graphify AST Indexing**, **GitHub Actions**, and **Slack / Telegram Webhooks**.

---

## 🛠️ Tooling & Stack

- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (`>=3.12`)
- **Architecture**: Clean Architecture (`src/core`, `src/domain`, `src/use_cases`, `src/infrastructure`)
- **AI Engine**: Google Gemini 2.0 Flash (Tool Calling & Function Calling)
- **Index Engine**: Graphify AST Knowledge Graph
- **CI/CD**: GitHub Actions (`uv run main.py`)
- **Webhooks**: Cloudflare Workers (`cloudflare-worker/slack-worker.js` & `worker.js`)

---

## 💻 Local Quickstart with `uv`

1. Navigate to project directory:
   ```bash
   cd /Users/bhaveshupadhyay/IdeaProjects/github_automation
   ```
2. Copy environment template and populate keys:
   ```bash
   cp .env.example .env
   ```
3. Sync dependencies:
   ```bash
   uv sync
   ```
4. Run locally:
   ```bash
   ./run_local.sh "Add dark mode toggle"
   # Or directly:
   uv run main.py "Add dark mode toggle"
   ```

---

## 🏗️ Clean Architecture Layout

```text
/Users/bhaveshupadhyay/IdeaProjects/github_automation/
├── pyproject.toml                     # uv project configuration
├── uv.lock                            # Lockfile
├── main.py                            # Entry Point & DI Composition Root
├── run_local.sh                       # Local Runner
├── src/
│   ├── core/                          # Configuration, Logger & DI Container
│   │   ├── config.py                  # Pydantic Settings
│   │   ├── logger.py                  # Structured Logging
│   │   ├── dependencies.py            # DI Container Factories
│   │   └── exceptions.py              # Domain Exceptions
│   ├── domain/                        # Pure Domain Entities & Interfaces
│   │   ├── entities.py                # Pydantic Value Objects
│   │   └── interfaces.py              # Abstract Gateways
│   ├── use_cases/                     # Application Business Logic
│   │   └── autonomous_developer.py    # AutonomousDeveloperUseCase
│   └── infrastructure/                # External Adapters
│       ├── llm/
│       │   └── gemini_gateway.py      # Gemini API + Tool Calling Adapter
│       ├── git/
│       │   └── github_gateway.py      # Git CLI & GitHub REST API Adapter
│       ├── indexer/
│       │   └── graphify_indexer.py    # Graphify AST Indexer Adapter
│       └── notification/
│           └── notifier_gateway.py    # Slack & Telegram Composite Notifier
└── cloudflare-worker/                 # Serverless Webhook Bridges
    ├── slack-worker.js
    └── worker.js
```
