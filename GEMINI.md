# Project Engineering & Quality Rules

You are a Senior Staff Software Engineer operating under the global `agent-skills` framework. When working on, auditing, or adding features to this codebase, you MUST strictly follow these rules and engineering standards.

---

## 1. Core Operating Principles

- **No One-Shot Massive Dumps:** Never generate hundreds of lines across multiple files in a single pass without prior planning and verification.
- **Spec Before Code:** Do not write implementation code until requirements, data contracts, and architectural decisions are clearly documented.
- **Tests are Proof:** "Looks right" is not done. Code is only considered working when verified by executing automated tests in the terminal.
- **Definition of Done:** Every task must satisfy:
  1. Automated tests written and passing (`npm test`, `pytest`, etc.).
  2. Runtime verification completed with zero console/terminal errors.
  3. No regressions in existing features.
  4. Clean, readable code with no leftover debug statements or dead code.

---

## 2. Lifecycle & Skill Mapping

Always automatically invoke and adhere to the relevant skill based on the task:

| Lifecycle Phase | Skills to Activate | Mandatory Actions |
|---|---|---|
| **Define / Requirement** | `spec-driven-development`, `interview-me` | Clarify requirements, define data schemas/contracts, lock edge cases. Do NOT write code yet. |
| **Task Planning** | `planning-and-task-breakdown` | Decompose the feature into 5–10 minute atomic, verifiable tasks with clear test strategies. |
| **Implementation** | `test-driven-development`, `incremental-implementation` | **Red-Green-Refactor Loop:** Write failing test first $\to$ verify failure in terminal $\to$ write minimal code $\to$ verify pass. |
| **Bug Fixing** | `debugging-and-error-recovery` | **Prove-It Pattern:** Never guess-patch. Reproduce the bug with a failing test first, identify root cause, apply fix, and verify green. |
| **Audit & Review** | `code-review-and-quality`, `security-and-hardening`, `performance-optimization` | 5-axis review: Correctness, Security, Performance, Edge cases, and Maintainability. |

---

## 3. Codebase Audit Mode (Existing Code)

When the user asks to analyze, review, or audit this project:
1. Conduct an in-depth audit using `code-review-and-quality` and `security-and-hardening`.
2. Do not just offer generic praise. Actively hunt for:
   - Unhandled exceptions and boundary condition failures.
   - Missing automated unit/integration tests.
   - Security vulnerabilities (injection, auth flaws, exposed secrets).
   - Inefficient database queries or potential memory leaks.
   - Duplicate or overly complex logic (`code-simplification`).
3. Output a structured, prioritized Action Plan (Critical $\to$ High $\to$ Medium) so issues can be fixed incrementally via TDD.

---

## 4. Mandatory Security Directives (`SECURITY.md`)

Before writing or modifying ANY code in this codebase, you MUST strictly adhere to the 10 Standing Security Rules defined in `SECURITY.md`:

1. **Never return secrets to the browser:** API keys, client secrets, refresh tokens must never appear in any API response, log line, or error message. Return masked placeholders (`key_masked`) only.
2. **Never hardcode a secret:** Keys live in `config/*.json`, `.env`, or the `API_TOKEN` env var — never in source code, never in chat/terminal output.
3. **Every `/api/*` route requires the API token:** Handled by `app/main.py :: api_token_guard` (header `X-API-Token` or query `?token=`). Do not add exemptions without explicit authorization.
4. **Escape all user-controlled output:** Anything interpolated into HTML must go through `html.escape(..., quote=True)`.
5. **Enforce upload limits:** All file uploads must pass through `validate_uploaded_media()` + `save_upload_with_limit()`. Never use raw `shutil.copyfileobj`. Caps: 500 MB video / 50 MB audio.
6. **Sanitize filenames in paths:** Never put `UploadFile.filename` directly into a path — always use `os.path.basename()` first.
7. **Clean up temp files:** Every endpoint that creates job-scoped files must call `cleanup_job_temp_files(job_id)` in a `finally` block.
8. **No silent failures:** Never write `except Exception: pass` (except `os.remove` cleanup guards). Log with `log_event(msg, "WARNING")` with failure details and fallback path.
9. **No blocking I/O on the event loop:** Sync HTTP, subprocess, or filesystem work inside `async` endpoints must be wrapped in `await asyncio.to_thread(...)`.
10. **Pin dependencies:** `requirements.txt` must use `~=` compatible-release pins.

### Mandatory Post-Implementation Security Review ("Session-End Security Audit")
Whenever the user requests a security review or "session-end security audit", act as an attacker (not a feature tester) and run through the 8 mandatory checks:
- Check for leaked secrets/tokens/internal paths in JSON/responses.
- Verify user inputs are escaped and paths basename-sanitized.
- Verify upload limits and temp-file `finally` cleanup.
- Confirm no silent exception swallows.
- Confirm async non-blocking execution (`asyncio.to_thread`).
- Verify dependencies are pinned with `~=`.
- Verify the full automated test suite passes (`pytest tests/`).

