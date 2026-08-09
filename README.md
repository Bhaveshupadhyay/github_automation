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
   ./run_local.sh
   # Or directly:
   uv run main.py
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
│   ├── core/                          # Configuration & Exceptions
│   │   ├── config.py
│   │   └── exceptions.py
│   ├── domain/                        # Pure Domain Entities & Interfaces
│   │   ├── entities.py
│   │   └── interfaces.py
│   ├── use_cases/                     # Application Business Logic
│   │   └── autonomous_developer.py
│   └── infrastructure/                # External Adapters
│       ├── llm/
│       │   └── gemini_gateway.py
│       ├── git/
│       │   └── github_gateway.py
│       ├── indexer/
│       │   └── graphify_indexer.py
│       └── notification/
│           └── notifier_gateway.py
└── cloudflare-worker/
    ├── slack-worker.js
    └── worker.js
```
