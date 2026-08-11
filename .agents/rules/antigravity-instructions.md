# Antigravity (`agy`) Global Operating Rules

## Core Directives

### 1. Mandatory Graphify AST Knowledge Graph Query
- **Graphify Awareness**: The repository has a `graphify-out/` AST knowledge graph.
- **Before Modifying Code**: Always query or inspect `graphify-out/` or AST index to map function callers, callees, nodes, and dependency edges before refactoring or adding logic.

### 2. Mandatory Clarification Check Rule
- **Missing Parameters**: If the user prompt is ambiguous, incomplete, or missing critical parameters (e.g., "change Redis to" without specifying what to replace it with, or "change app name" without specifying the new name), you MUST start your response with:
  `CLARIFICATION_NEEDED: <Your clear question to the user>`
  Do NOT attempt to guess missing parameters or output conversational suggestions without this exact prefix tag.

### 3. Pure Engineering Focus & Structured Execution Summary
- **Code Execution Only**: Focus 100% on software engineering, file editing, and test implementation. Do NOT execute `git` or `gh` CLI commands.
- **Execution Summary Tag**: At the end of your response after editing all target files, output a clear summary tag:
  `AGY_EXECUTION_SUMMARY:`
  followed by structured bullet points detailing:
  - Key files modified or created.
  - Architectural & logic updates implemented.
  - Test coverage added or verified.

### 4. Code Modifications & Quality Standards
- **In-Place File Updates**: Modify existing source code files in-place using exact line diffs. Never invent mangled filenames.
- **Complete Production Code**: Never leave TODO comments, placeholder stubs, or truncated code snippets.
- **Preserve Existing Architecture**: Strictly follow existing project conventions, models, dependencies, and formatting.
