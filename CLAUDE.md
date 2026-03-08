# Job Agent — AI Context

## Project overview

Autonomous job search agent: scrapes job boards → AI evaluation → adapted CV → Telegram notification + Web App UI.

## Stack

- **Python 3.12+**
- **python-telegram-bot v22** (PTB) — async bot with inline keyboards, callback handlers, PTB JobQueue for scheduling
- **FastAPI + uvicorn** — TWA backend, runs concurrently with PTB in the same asyncio event loop
- **aiosqlite** — async SQLite for job persistence
- **Anthropic Claude** (Haiku for eval, Sonnet for CV) with **Groq** as free fallback
- **BeautifulSoup4 + httpx** — scraping
- **ReportLab** — PDF generation

## Running the project

```bash
python3.14 main.py
```

Uses `python3.14` on this machine (system pip3.14). No virtualenv — packages installed globally.

The bot and FastAPI WebApp start together. FastAPI runs on port 8080.

For the Telegram WebApp to work, a public HTTPS URL is needed:
```bash
cloudflared tunnel --url http://localhost:8080
# Set WEBAPP_URL in .env
```

## Key files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — asyncio event loop, PTB + uvicorn together |
| `src/llm_client.py` | Central LLM client — Anthropic → Groq(70b) → Groq(8b) fallback |
| `src/bot/telegram_bot.py` | All bot handlers + `build_job_message()` with TWA button |
| `src/scheduler/scheduler.py` | Pipeline orchestrator + scheduled daily/weekly jobs |
| `src/evaluator/job_evaluator.py` | AI job scoring — returns 0-100 match + skills analysis |
| `src/cv_adapter/cv_adapter.py` | ATS-optimized CV tailoring |
| `src/cv_adapter/cv_renderer.py` | Plain text → PDF with ReportLab |
| `src/cv_adapter/cover_letter.py` | Cover letter generation on approval |
| `src/cv_adapter/interview_prep.py` | Interview question generation on approval |
| `src/database/db.py` | All DB operations — schema is auto-migrated on startup |
| `src/webapp/api.py` | FastAPI backend — Telegram initData auth, job CRUD, CV download |
| `src/webapp/static/index.html` | Telegram Web App — single HTML file, no build step |
| `src/profile/{id}/config.json` | Per-user config (search queries, language, salary, chat_id) |
| `src/profile/{id}/profile.json` | Candidate CV data for AI evaluation |

## Multi-profile architecture

- Each user has `src/profile/{id}/config.json` + `profile.json`
- Routing by `telegram_chat_id` in config — loaded fresh on each request (no caching)
- `primary_language: "Spanish"` → Spanish prompts, Spanish CV, 15pt penalty for English-required jobs
- `markets: ["Colombia", "LATAM"]` → activates Computrabajo + Elempleo + Indeed Colombia scrapers

## LLM client

```python
# src/llm_client.py
await llm_chat(system, user, max_tokens=1500, mode="eval")
# mode="eval" → Claude Haiku  (cheap, fast)
# mode="cv"   → Claude Sonnet (better writing quality)
# Auto-falls back to Groq on Anthropic credit/rate errors
```

## Database schema

Table: `jobs`
- `id`, `profile_id`, `title`, `company`, `url`, `source`
- `match_score`, `match_summary`, `match_level`, `recommendation`
- `salary_info`, `is_remote`, `requires_english`, `english_level`
- `skills_match` (JSON), `skills_missing` (JSON)
- `strengths` (JSON), `concerns` (JSON), `ats_keywords` (JSON)
- `cv_adapted`, `raw_description`, `status`
- `created_at`, `approved_at`, `reminder_sent`

Status flow: `pending` → `notified` → `approved` / `rejected` / `pending` (later)
Also: `low_match` for jobs below `min_match_score`

## Pipeline flow

```
Scrapers (parallel) → dedup check → keyword pre-filter (free) → cap 8/run
→ AI evaluate (Haiku) → language penalty if needed → skip if < min_score
→ adapt CV (Sonnet) → save to DB → send Telegram notification
```

Source priority (when capping): LinkedIn > Computrabajo > Elempleo > Indeed > WWR > RemoteOK

## TWA auth

Every API request sends `X-Init-Data` header with Telegram's `initData` string.
`_verify_telegram_init_data()` in `api.py` validates the HMAC-SHA256 signature using `TELEGRAM_BOT_TOKEN`.
Never trust requests without valid initData.

## Scheduled jobs (UTC)

- Pipeline: every 6h (env: `SEARCH_INTERVAL_HOURS`)
- Daily summary: 23:00 (env: `DAILY_SUMMARY_HOUR_UTC`)
- Follow-up reminders: 14:00 daily (approved jobs > 5 days old)
- Skill gap report: Mondays 13:00

## Common tasks

**Add a new scraper:**
1. Create `src/scrapers/newsite_scraper.py` with `async def fetch_jobs(...) -> list[dict]`
2. Each job dict needs: `id`, `title`, `company`, `url`, `source`, `profile_id`, `raw_description`
3. Import and call in `scheduler.py` inside `run_pipeline_for_profile()`

**Add a new profile:**
1. `mkdir src/profile/newuser`
2. Create `config.json` (see README for schema)
3. Create `profile.json` with CV data
4. Restart the bot

**Update DB schema:**
- Add migration in `init_db()` in `src/database/db.py` using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- Schema is always migrated on startup — no manual migration needed

## Environment variables

See `.env.example` for all variables. Key ones:
- `ANTHROPIC_API_KEY` — required
- `GROQ_API_KEY` — required (free fallback)
- `TELEGRAM_BOT_TOKEN` — required
- `WEBAPP_URL` — public HTTPS URL for TWA (cloudflared tunnel)
- `WEBAPP_PORT` — default 8080
- `SEARCH_INTERVAL_HOURS` — default 6
- `DAILY_SUMMARY_HOUR_UTC` — default 23

## Profiles on this machine

- **jeferson** — English, USD, Frontend/React, global remote
- **lina** — Spanish, COP, Scrum Master/Agile, LATAM/Colombia
