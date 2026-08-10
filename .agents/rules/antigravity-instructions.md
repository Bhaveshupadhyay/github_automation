# Antigravity (`agy`) Global Operating Rules

## Core Directives

### 1. Clarification Check Rule
- **Missing Parameters**: If the user prompt is ambiguous or missing critical required information (e.g., "Change app name" without specifying the new name), output:
  `CLARIFICATION_NEEDED: <Your clear question to the user>`
  Do NOT attempt to guess missing parameters or invent placeholder code.

### 2. Pull Request & Branch Rules
- **DO NOT Auto-Merge**: Always create a feature branch (`ai-patch-<timestamp>`) and open a Pull Request for human code review.
- **Descriptive Titles**: Use clean git commit titles (e.g. `feat: add caching to get_trending_posts`).

### 3. Code Modifications & Quality Standards
- **In-Place File Updates**: Modify existing source code files in-place using exact line diffs. Never invent mangled filenames (like `app_api_v1_post`).
- **Complete Production Code**: Never leave TODO comments, placeholder stubs, or truncated code snippets.
- **Preserve Existing Architecture**: Strictly follow existing project conventions, models, dependencies, and formatting.

### 4. Graph & Skill Context Awareness
- **Skills First**: Check `.agents/skills/` and read relevant `SKILL.md` documents if present.
- **Graph Context**: Query `graphify-out/` or AST index to understand call trees, nodes, and edges before refactoring.
