# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (Python 3.12)
pip install -r requirements.txt
playwright install chromium --with-deps

# Run full pipeline (scrape → Sheets → Notion)
python main.py

# Override complex IDs at runtime
python main.py --complex-ids 8928 102378

# Pipeline stage flags (combinable)
python main.py --scrape-only      # skip Sheets & Notion writes
python main.py --notion-only      # skip scrape and Sheets
python main.py --sheets-only      # skip scrape and Notion (requires existing data)

# Smoke-test individual modules
python -c "from models import Listing; print('models OK')"
python -c "import asyncio; from scraper import run_scraper; r = asyncio.run(run_scraper(['8928'])); print(len(r['8928']), 'listings')"
```

## Architecture

**Data flow:** `scraper.py` → `sheets_handler.py` → `notion_handler.py`, orchestrated by `main.py`.

### Pipeline stages (`main.py`)
1. **Scrape** — `run_scraper()` returns `dict[complex_id → list[Listing]]`
2. **Sheets write** — `write_listings(all_listings)` writes to today's tab (YYYY-MM-DD)
3. **Delta compute** — reads yesterday's Sheets tab, computes `ComplexSummary` per complex × trade type
4. **Notion write** — `write_summaries(summaries)` upserts rows by (complex_id, date, trade_type)

### Scraper design (`scraper.py`)
Uses Playwright + playwright-stealth to run a Chromium browser. API calls are made via `page.evaluate(fetch(...))` — not direct HTTP — so Naver session cookies set by `warm_up_session()` are automatically included. Retries up to 3× on 429/network errors with exponential backoff.

- **API endpoint:** `https://new.land.naver.com/api/articles/complex/{id}?tradeType=A1|B1|B2&page=N`
- **Trade types:** `A1` = 매매 (sale), `B1` = 전세 (lease), `B2` = 월세 (monthly rent)
- **Price parsing:** Korean 억/만원 strings → int 만원. B2 prices use `"deposit/monthly"` slash format.

### Google Sheets (`sheets_handler.py`)
- One spreadsheet, one tab per date (YYYY-MM-DD)
- On re-run, existing data rows are cleared before re-writing (header preserved)
- Reads yesterday's tab for delta computation
- Credential precedence: `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` (raw JSON, used in CI) → `GOOGLE_SERVICE_ACCOUNT_JSON` (file path, used locally)

### Notion (`notion_handler.py`)
- One database with one row per (complex_id × trade_type × date)
- Upsert: queries by those three fields, updates if found, creates if not
- Rate-limited to 350ms between API calls

### First-run resource creation
Both handlers auto-create missing resources on first run and log the generated IDs:
- `sheets_handler`: creates spreadsheet, logs `GOOGLE_SPREADSHEET_ID`
- `notion_handler`: creates database under `NOTION_PARENT_PAGE_ID`, logs `NOTION_DATABASE_ID`

Copy logged IDs into `.env` and GitHub Secrets before subsequent runs.

## Environment Variables

| Variable | Purpose |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Local: path to service account JSON file |
| `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` | CI: raw JSON string (takes precedence over above) |
| `GOOGLE_SHARE_EMAIL` | Email to share the created spreadsheet with |
| `GOOGLE_SPREADSHEET_ID` | Blank on first run; set after creation |
| `NOTION_TOKEN` | Notion integration token |
| `NOTION_PARENT_PAGE_ID` | Page where the DB is created |
| `NOTION_DATABASE_ID` | Blank on first run; set after creation |
| `COMPLEX_IDS` | Comma-separated Naver complex IDs (default: `8928,102378,111515`) |
| `TRADE_TYPES` | Comma-separated trade types (default: `A1,B1,B2`) |
| `MAX_LISTINGS_PER_COMPLEX` | Per-complex cap (default: `200`) |
| `SLEEP_MIN` / `SLEEP_MAX` | Random delay range in seconds between requests |
| `HEADLESS` | `true` for headless Chromium (always true in CI) |
| `PROXY_URL` | Optional HTTP/SOCKS proxy, e.g. `http://user:pass@host:port` (needed outside Korea) |

## CI (GitHub Actions)
Runs daily at 02:00 KST (17:00 UTC) via `.github/workflows/daily_scrape.yml`. Also supports `workflow_dispatch` for manual triggers. Playwright browser binaries are cached keyed on `requirements.txt` hash.
