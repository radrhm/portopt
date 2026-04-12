# PortOpt — Best Practices Reference

This document lists every best-practice rule to follow for this project going forward.
Organised by layer. Each rule states **what** to do, **why**, and **when it applies**.

---

## 1. Git & Version Control

| # | Rule | Why |
|---|------|-----|
| 1 | Add `.gitignore` **before** the first commit | Binary/generated files (`.db`, `__pycache__`, `.env`) are hard to purge from history once committed |
| 2 | Never commit secrets or local config (`.env`, credentials) | Leaked keys cannot be un-leaked |
| 3 | Verify `git config user.email` matches your GitHub account before pushing | Vercel blocks deployments from unrecognised committers |
| 4 | Use feature branches; merge to `main` via PR | Protects main from broken pushes; gives a review checkpoint |
| 5 | Prefer a new commit over force-push to trigger Vercel builds | Vercel's webhook may ignore a force-push even if history changed |
| 6 | Use concise, imperative commit messages (`Fix`, `Add`, `Remove`) | GitHub squashes long bodies into subject-only views |

---

## 2. Dependency Management

| # | Rule | Why |
|---|------|-----|
| 7 | Pin **all** deps (including transitive) in `requirements.txt` for Vercel | Vercel Python 3.12 doesn't auto-install transitive deps at runtime |
| 8 | Use upper-bound pins for fast-moving libs (`cvxpy<2`, `numpy<2`) | Major version breaks are common; upper bounds prevent surprise failures |
| 9 | Add a `.python-version` file (`3.12`) | Documents the exact runtime; tools like pyenv respect it |
| 10 | Use a virtual environment locally (`python -m venv .venv`) | Prevents version conflicts with system packages |

---

## 3. Flask Application Structure

| # | Rule | Why |
|---|------|-----|
| 11 | Split the app into `services/` (business logic) and `routes/` (Flask Blueprints) | A 850-line `app.py` is unreadable and untestable |
| 12 | Register Blueprints in `app.py`; keep `app.py` under ~30 lines | The entry point should just wire things up, not contain logic |
| 13 | Never use `warnings.filterwarnings("ignore")` globally | Masks real bugs; scope it to the specific module/category that needs it |
| 14 | Use `logging` instead of `print()` / `traceback.print_exc()` | Serverless logs need structured output; print goes to stdout with no level |
| 15 | Add a `/health` endpoint that returns `{"status": "ok"}` | Required by load balancers, uptime monitors, and Vercel warm-pings |

---

## 4. Input Validation & Error Handling

| # | Rule | Why |
|---|------|-----|
| 16 | Call `request.get_json(silent=True)` and check for `None` before accessing keys | Bare `request.json["key"]` throws `TypeError` or `KeyError` on malformed input |
| 17 | Validate all required fields at the top of each route; return **400** for bad input | Routes that accept whatever they get silently fail or crash |
| 18 | Return correct HTTP status codes: 400 for bad input, 500 for server errors, 404 for not found | A 200 response with `{"error": "..."}` confuses monitoring tools and CDNs |
| 19 | Catch **specific** exceptions (`ValueError`, `KeyError`) not bare `except Exception` | Bare except hides bugs; you can't distinguish expected failures from crashes |
| 20 | Log the full traceback server-side; return only a safe error message to the client | Stack traces in API responses leak internal structure |

---

## 5. Database (SQLite / db.py)

| # | Rule | Why |
|---|------|-----|
| 21 | Never use `PRAGMA journal_mode=WAL` in serverless | WAL requires `-shm`/`-wal` shared-memory files that don't exist in Vercel/Lambda containers |
| 22 | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` | `utcnow()` is deprecated in Python 3.12 and will be removed in 3.14 |
| 23 | Wrap `init_db()` in a try/except; don't let import-time side-effects crash the module | An `init_db()` failure at import kills the entire Lambda cold start with a cryptic error |
| 24 | **SQLite in `/tmp` is ephemeral on Vercel** — saved data is lost on every cold start | Vercel's container filesystem is wiped between cold starts; use a real DB for persistence |
| 25 | For production persistence on serverless: use Supabase (PostgreSQL) or move to Railway/Render | These provide either a managed DB or a persistent disk without changing the Flask code much |

---

## 6. Frontend (HTML/CSS/JS)

| # | Rule | Why |
|---|------|-----|
| 26 | Split a 2000-line `index.html` into `static/css/app.css` and `static/js/app.js` | One file is unmaintainable; split enables browser caching and better diffs |
| 27 | Add a `<link rel="icon">` (favicon) | Browsers make a request for `/favicon.ico` on every load; 404 is a log noise source |
| 28 | Add Subresource Integrity (SRI) hashes to CDN `<script>` tags | Without SRI, a compromised CDN can inject arbitrary JS into your page |
| 29 | Use `showError(msg)` helper instead of `alert()` for user-facing errors | `alert()` blocks the thread, is not styleable, and is terrible UX |
| 30 | Wrap all `localStorage` calls in try/catch | Private/incognito mode and storage quota exceeded throw synchronously |
| 31 | Define a localStorage schema version key (`portopt_v3`) and migrate on load | Without versioning, adding a field to the stored object will silently break old data |
| 32 | Use event listeners instead of inline `onclick=` handlers | Inline handlers make it impossible to apply Content Security Policy headers |
| 33 | Namespace all global JS (`window.PortOpt = {}`) or use ES modules | Every `let x = ...` in a `<script>` tag is a global; name collisions cause subtle bugs |

---

## 7. Platform & Architecture

| # | Rule | Why |
|---|------|-----|
| 34 | Set `maxDuration: 30` in `vercel.json` for CPU-heavy endpoints | Default is 10 s; portfolio optimization can take 15–25 s on cold start |
| 35 | Vercel serverless is **not** the right platform for heavy computation + persistent state | Cold starts add ~5 s; 30 s timeout; ephemeral filesystem. Use Railway/Render for this app |
| 36 | Separate dev and prod environments | Never test against the live production database/URL |
| 37 | Add a `README.md` with setup instructions | New contributors (and future-you) should be able to run the project in under 5 minutes |

---

## Quick Checklist for New Routes

```
[ ] request.get_json(silent=True) and null check → 400
[ ] Validate required fields (type, range, presence) → 400
[ ] Catch specific exceptions; log traceback; return 500
[ ] Return correct HTTP status code (not always 200)
[ ] No bare `data["key"]` — use data.get("key") with a default
```

## Quick Checklist Before Every Deploy

```
[ ] .gitignore updated (no .db, .env, __pycache__)
[ ] requirements.txt includes all transitive deps
[ ] No print() or traceback.print_exc() left in routes
[ ] No warnings.filterwarnings("ignore") at global scope
[ ] /health returns 200
[ ] Tested locally with python app.py
```
