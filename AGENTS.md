# 🧬 DJANGO GUARDIAN HARNESS & AI BOOTSTRAP DIRECTIVES

This document sets the initialization rules and boot directives for any Artificial Intelligence or Automated Agent operating in this repository. Its instructions take **absolute precedence** over any general workflow.

---

## 🚨 1. FIRST-TURN COMMAND RULE (Golden Initialization Rule)

- **Mandatory First-Turn Action:** Upon starting a session, on your **FIRST turn**, you MUST immediately execute the `read_file` tool command to load and analyze the skill specification in `.gemini/skills/django-warden/SKILL.md`.
- **Available Commands:** Always inspect the root `Justfile` to discover available project tasks and shortcuts. They are designed for token efficiency and their usage is strictly preferred (e.g., `just test`, `just check`, `just migrate`, `just run_simulation`).
- **No Premature Actions:** You are strictly PROHIBITED from proposing strategies, generating code, answering complex questions, or applying any modifications before reading `SKILL.md` in full.
- **🛡️ Mandatory Skill Validation (Django Warden / Guardian):**
  - Verify that the `django-warden` skill is installed and active in this session (activate on demand via `activate_skill` if available).
  - **🔌 Mandatory MCP Server Validation:**
    - Verify that MCP tools provided by `django-ai-boost` (e.g., `list_apps`, `get_model_schema`) and `codebase-memory-mcp` are available in the assistant environment.

---

## 🛡️ 2. CODE QUALITY CONTRACT & SLA COMPLIANCE

When working in this repository, align all code authoring and refactoring behaviors to the following standards of excellence:

- **100% Code Coverage SLA:** Every logical branch or feature added or modified in the application must include corresponding unit tests to maintain high test coverage.
- **McCabe Cyclomatic Complexity < 10:** No standard business function or view may exceed a cyclomatic complexity of 10. Dense functions must be decomposed.
- **Event & Handler Delegation:** Dense webhooks and dispatchers must be refactored using private handler delegation patterns, keeping the primary event router cyclomatic complexity strictly below 4.
- **No Hardcoded Prompts:** AI system prompts must reside isolated in dedicated `.prompt` or Markdown files and never be hardcoded into Python source files.
- **No-Storytelling Rule (Clean Comments):** Prolix or narrative comments regarding specs or business logic are strictly prohibited. Block comments (`#`) must not exceed **3 lines**, individual comment lines must not exceed **120 characters**, and redundant or obsolete comments are rejected by the Harness.
- **Migration Index Idempotency:** Any database migration operation creating indexes or constraints must include existence checks (e.g., `IF NOT EXISTS`) to prevent failures during sequential runs across dev and production.

---

## ⚡ 3. INTEGRATION WITH DJANGO-AI-BOOST (MCP Server)

This project leverages `django-ai-boost` as an MCP server to optimize context usage and code analysis:

- **Dynamic Context Configuration:** The agent must automatically keep local MCP server settings updated with the correct Django settings module (`gpurent.settings`).
- **Active Code Validation:** The assistant should leverage validation tools like `run_check` provided by `django-ai-boost` to verify architectural compliance in real time.

---

## 🧠 4. COGNITIVE ORCHESTRATION & AGENTIC WORKFLOW

Adopt a proactive and rigorous posture before marking any task as complete:

### 🎯 Plan-Before-Code Trigger
- **Planning Threshold:** Any task involving more than 3 physical steps, modifications to database models (`models.py`), or complex external integrations requires presenting a concise action plan for review prior to modifying files.

### 🛑 Strategic Course Correction (The 3-Error Rule)
- **Loop Prevention:** If an attempt to fix code or tests fails 3 consecutive times:
  1. **Stop immediately.**
  2. Provide a concise summary of current assumptions.
  3. Identify potential incorrect assumptions and propose an alternative architectural approach rather than applying repetitive hotfixes.

### 🧪 Rigorous Verification & Self-Correction
- **Autonomous Failure Resolution:** If tests fail, proactively inspect error logs, review affected files, and apply necessary corrections.
- **Code Idiomaticity:** Always verify: *"Is this the most Pythonic, maintainable, and Django-idiomatic way to solve this problem?"*
- **Database Query Hygiene:** Enforce zero N+1 queries (use `select_related`/`prefetch_related`), use serializers rather than raw dict parsing, and guard signals against recursive infinite loops.
