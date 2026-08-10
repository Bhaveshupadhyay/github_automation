# Antigravity (`agy`) Global Operating Rules

## Core Directives

### 1. Mandatory Graphify AST Knowledge Graph Query
- **Graphify Awareness**: The repository has a `graphify-out/` AST knowledge graph.
- **Before Modifying Code**: Always query or inspect `graphify-out/` or AST index to map function callers, callees, nodes, and dependency edges before refactoring or adding logic.

### 2. Clarification Check Rule
- **Missing Parameters**: If the user prompt is ambiguous or missing critical required information (e.g., "Change app name" without specifying the new name), output:
  `CLARIFICATION_NEEDED: <Your clear question to the user>`
  Do NOT attempt to guess missing parameters or invent placeholder code.

### 3. Meaningful Git Branching & Commit Conventions
- **Branch & Commit Suggestions**: At the end of your response after completing file edits, output:
  `SUGGESTED_BRANCH: feat/<short-kebab-case-description>`
  `SUGGESTED_COMMIT: <conventional-commit-type>(<scope>): <meaningful description>`
  Example:
  `SUGGESTED_BRANCH: feat/add-redis-caching-get-trending-posts`
  `SUGGESTED_COMMIT: feat(posts): add Redis caching decorator to get_trending_posts`

### 4. Pull Request & Clean Diff Rules
- **DO NOT Auto-Merge**: Always open a Pull Request for human code review.
- **Clean Diffs Only**: Only commit source code changes requested by the user. NEVER commit or stage `.agents/`, `skills.md`, or instruction files into the PR diff.

### 5. Code Modifications & Quality Standards
- **In-Place File Updates**: Modify existing source code files in-place using exact line diffs. Never invent mangled filenames (like `app_api_v1_post`).
- **Complete Production Code**: Never leave TODO comments, placeholder stubs, or truncated code snippets.
- **Preserve Existing Architecture**: Strictly follow existing project conventions, models, dependencies, and formatting.
