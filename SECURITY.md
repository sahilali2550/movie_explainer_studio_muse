# SECURITY.md — AutoExplainer AI

> Read this file BEFORE writing or modifying any code in this repo.
> It exists because AI-generated code shipped with real security holes.
> The checklist below is mandatory for every AI coding session (Antigravity,
> ChatGPT, or otherwise).

## 1. Standing rules (never violate)

1. **Never return secrets to the browser.** API keys, client secrets, refresh
   tokens must never appear in any API response, log line, or error message.
   Return masked placeholders (`key_masked`) only.
2. **Never hardcode a secret.** Keys live in `config/*.json`, `.env`, or the
   `API_TOKEN` env var — never in source, never in chat output.
3. **Every `/api/*` route requires the API token** (`app/main.py ::
   api_token_guard`, header `X-API-Token` or `?token=`). New endpoints are
   covered automatically. The only exemption is
   `/api/v1/youtube/oauth-callback` (browser redirect; protected by OAuth
   `state` instead). Do not add new exemptions without a written reason here.
4. **Escape all user-controlled output.** Anything interpolated into HTML
   must go through `html.escape(..., quote=True)`.
5. **Enforce upload limits.** All file uploads go through
   `validate_uploaded_media()` + `save_upload_with_limit()` in
   `backend/app/api/v1/explainer.py`. Never use raw `shutil.copyfileobj`
   for uploads. Current caps: 500 MB video / 50 MB audio.
6. **Sanitize filenames in paths.** Never put `UploadFile.filename` directly
   into a filesystem path — always `os.path.basename()` it first.
7. **Clean up temp files.** Every endpoint that creates job-scoped files must
   call `cleanup_job_temp_files(job_id)` in a `finally` block.
8. **No silent failures.** Never write `except Exception: pass` (except
   `os.remove` cleanup guards). Log with `log_event(msg, "WARNING")`
   including what failed and what the fallback is.
9. **No blocking I/O on the event loop.** Sync HTTP/file work inside `async`
   endpoints must be wrapped in `await asyncio.to_thread(...)`.
10. **Pin dependencies.** `requirements.txt` uses `~=` pins. New deps get a
    pin AND must actually be added (missing deps broke YouTube features).

## 2. Bugs already fixed (do not regress)

| # | Severity | Bug | Fix location |
|---|----------|-----|--------------|
| 1 | Critical | `GET /ai-config` returned full API keys in plaintext | `explainer.py :: get_ai_config` — `p_data.pop("key", None)` |
| 2 | Critical | Reflected XSS via `error` param in OAuth callback | `youtube_api.py :: oauth_callback` — `html.escape(error, quote=True)` |
| 3 | Critical | `MAX_VIDEO_BYTES`/`MAX_AUDIO_BYTES` defined but never enforced | `explainer.py :: validate_uploaded_media` + `save_upload_with_limit` |
| 4 | Critical | Path traversal: `local_file.filename` used raw in autopilot path | `explainer.py` — `os.path.basename(...)` |
| 5 | High | Temp files accumulated forever (only 3–4 of ~20 patterns cleaned) | `config.py :: cleanup_job_temp_files` + `finally` hooks + startup purge |
| 6 | High | YouTube OAuth had no `state` (CSRF) | `youtube_api.py` one-time state tokens, 10-min TTL |
| 7 | High | No API auth, `CORS allow_origins=["*"]` | `main.py :: api_token_guard`, auto-generated token injected into frontend |
| 8 | Medium | 6 swallowed exceptions hid real failures | Converted to `log_event(..., "WARNING")` |
| 9 | Medium | Unpinned `>=` deps; Google deps missing entirely | `requirements.txt` `~=` pins |
| 10 | Medium | Sync 9Router HTTP calls blocked the async event loop | `asyncio.to_thread(...)` wrappers |

## 3. How the auth model works

- On first run the server generates a random token, stored at
  `storage/.api_token` (mode `0600`). Override with the `API_TOKEN` env var.
- The dashboard served at `/` gets the token auto-injected into `index.html`
  (`window.__API_TOKEN__`); `frontend/js/app.js` attaches it to every
  `/api/*` fetch and to the bundle-zip download link.
- External clients (curl, scripts) must send `X-API-Token: <token>` or
  `?token=<token>`.
- Tests pin `API_TOKEN=test-token-local-only-do-not-use-in-prod` in
  `tests/conftest.py`, which auto-attaches the header to `TestClient`.

## 4. Mandatory checklist — run after EVERY AI session

Paste this to your AI assistant when a feature/fix is done:

```
SECURITY REVIEW — act as an attacker, not a feature tester:

1. Do any new/changed endpoints return secrets, tokens, or internal paths?
   Check every JSON response and error message.
2. Is any request parameter (query, form, filename, header) interpolated
   into HTML, shell commands, SQL, or filesystem paths without
   escaping/sanitizing?
3. Do new file uploads enforce validate_uploaded_media() +
   save_upload_with_limit()? Is the filename basename-sanitized?
4. Does the new endpoint clean its temp files via
   cleanup_job_temp_files(job_id) in a finally block?
5. Does any new except block swallow errors silently? Convert to
   log_event(..., "WARNING").
6. Is any new I/O (HTTP, subprocess, file) called directly inside an
   async endpoint? Wrap in asyncio.to_thread().
7. Are new dependencies added to requirements.txt with ~= pins?
8. Run the full pytest suite and report failures. Do not claim "done"
   until tests pass.

Then summarize: what changed, the security impact of each change,
and how you verified it.
```

## 5. Incident notes

- 2026-09-25: full security audit + fixes applied (see table above).
  Patch: `security-fixes.patch`. If AI tooling reintroduces any pattern
  from the table, treat it as a regression and fix immediately.
