# AGENTS.md

## Run

```bash
uv run main.py          # starts uvicorn on http://localhost:8000
```

Requires Python >=3.13. Package manager is `uv` (not pip).

## Architecture

- **Entry**: `main.py` → `src/app.py` (FastAPI app)
- **Web**: FastAPI + Jinja2 templates + htmx (partial HTML responses, no SPA)
- **Data scraping**: Playwright launches a real Chrome browser (`channel='chrome'`) using a persistent user profile (`USER_DATA_DIR`, default `./browser_profile`) to send authenticated requests to Ozon seller API. The first login is performed manually through the `/settings` page → "Log in to Ozon" button, which opens a non-headless Chrome window at `seller.ozon.ru`. The session (cookies + localStorage) is persisted to disk and reused across restarts.
- **DB**: SQLite (`PriceMonitor.sqlite`) via SQLAlchemy async + aiosqlite. Custom migration system reads `.sql` files from `migrations/` on startup.
- **Scheduler**: APScheduler (`ScedulerService` — typo is intentional, don't rename it) runs cron jobs to collect prices per company_id.

## Key files

| Path | Purpose |
|------|---------|
| `config.json` | Runtime config (LOG_LEVEL, HEADLESS_BROWSER, BROWSER_STARTUP_SLEEP_SECONDS, SUSPEND_AFTER_BROWSER_STARTUP, USER_DATA_DIR, WB_WALLET_REFRESH_MINUTES, WB_WALLET_LEVEL) |
| `src/config.py` | Loads `config.json` at import time |
| `src/browser_request_sender.py` | Playwright persistent browser context (login flow + request sender); saves Chrome profile to `USER_DATA_DIR` |
| `src/api/ozon_api.py` | Ozon API endpoints wrapper |
| `src/service/ozon_service.py` | Business logic: fetch prices, compute changes, generate Excel reports |
| `src/service/scheduler_service.py` | Cron-based scheduled price collection |
| `src/persistence/` | Database access (ozon_price, parameters, task) |
| `src/models/` | SQLAlchemy models |
| `src/dto/` | Pydantic response models |
| `templates/` | Jinja2 + htmx HTML templates |

## Migrations

SQL files in `migrations/` are auto-applied on app startup (tracked in `migrations` table). No external migration tool needed. Numbered `NNN_*.sql`.

## Testing

No test suite exists in this project.

## Build

`cx_Freeze` config is in `pyproject.toml` under `[tool.cxfreeze]`. Builds a standalone executable from `main.py`.

## Gotchas

- `config.json` must exist at CWD — the app reads it at import time and silently defaults if missing.
- Playwright requires a Chrome browser installed; `HEADLESS_BROWSER: false` in config shows the browser window for debugging.
- First-time setup: on `/settings` click "Log in to Ozon" → a Chrome window opens at `seller.ozon.ru`, log in manually, then close the window. The session is persisted to `USER_DATA_DIR` and reused on subsequent starts. If the Ozon session expires, repeat this step.
- `USER_DATA_DIR` is locked exclusively by Chromium — only one process can hold it at a time. The `/login` endpoint closes the running sender before launching the login window.
- `src/service/scheduler_service.py` class is `ScedulerService` (misspelled) — matches usage in `src/app.py`.