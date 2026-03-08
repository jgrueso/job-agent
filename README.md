# Job Agent

An AI-powered job search agent that runs autonomously, evaluates job offers against your profile, adapts your CV for each application, and delivers curated results through Telegram.

## What it does

1. **Scrapes** job boards on a schedule (LinkedIn, RemoteOK, WeWorkRemotely, Computrabajo, Elempleo, Indeed Colombia)
2. **Evaluates** each offer with Claude AI — scores 0-100 match, extracts skills gap, salary, remote status
3. **Adapts your CV** for every qualifying offer using ATS-optimized formatting
4. **Notifies via Telegram** with a card showing score, skills match, and recommendation
5. **Telegram Web App (TWA)** — a mini web UI inside Telegram with job cards, detail view, approve/reject/later buttons, and CV download
6. **On approval**: auto-generates cover letter + interview question prep
7. **Follow-up reminders**: alerts you 5 days after approving a job if you haven't followed up
8. **Weekly skill gap report**: shows which skills are blocking you most across all evaluated jobs

## Architecture

```
main.py                         # Entry point — runs PTB bot + FastAPI concurrently
src/
  bot/telegram_bot.py           # Telegram bot handlers, inline keyboards
  scheduler/scheduler.py        # Pipeline orchestrator + scheduled jobs
  scrapers/
    linkedin_scraper.py
    remoteok_scraper.py
    weworkremotely_scraper.py
    computrabajo_scraper.py     # LATAM — Colombia
    elempleo_scraper.py         # LATAM — Colombia
    indeed_scraper.py           # LATAM — Colombia
  evaluator/job_evaluator.py    # AI job-profile matching (Claude Haiku)
  cv_adapter/
    cv_adapter.py               # ATS-optimized CV tailoring (Claude Sonnet)
    cv_renderer.py              # Plain text → PDF (ReportLab)
    cover_letter.py             # Auto cover letter generation
    interview_prep.py           # Interview question generation
  llm_client.py                 # Anthropic → Groq fallback chain
  database/db.py                # aiosqlite persistence
  webapp/
    api.py                      # FastAPI backend for the TWA
    static/index.html           # Telegram Web App UI (single-page)
  profile/
    {name}/config.json          # Per-user configuration
    {name}/profile.json         # Candidate CV / skills data
```

## Multi-profile support

Each user has their own folder under `src/profile/{id}/`:

- **config.json** — search queries, markets, salary range, language, min score, telegram_chat_id
- **profile.json** — full CV data used for AI evaluation and CV adaptation

The agent routes notifications and actions by `telegram_chat_id`, supporting unlimited users.

## LLM strategy

| Task | Model | Cost |
|------|-------|------|
| Job evaluation | Claude Haiku 4.5 | ~$0.001/job |
| CV adaptation | Claude Sonnet 4.6 | ~$0.01/job |
| Fallback (all) | Groq llama-3.3-70b (free) | $0 |
| Fallback 2 | Groq llama-3.1-8b (free) | $0 |

The client tries Anthropic first, falls back to Groq automatically on credit errors or rate limits.

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/job-agent.git
cd job-agent
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required keys:
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `GROQ_API_KEY` — from [console.groq.com](https://console.groq.com) (free)
- `TELEGRAM_BOT_TOKEN` — create a bot with [@BotFather](https://t.me/BotFather)

### 3. Create your profile

```bash
mkdir -p src/profile/yourname
```

**`src/profile/yourname/config.json`**:
```json
{
  "id": "yourname",
  "name": "Your Name",
  "telegram_chat_id": 123456789,
  "min_match_score": 65,
  "primary_language": "English",
  "salary_currency": "USD",
  "salary_min": 4000,
  "modality": ["remote"],
  "markets": ["USA", "Europe"],
  "search_queries": {
    "linkedin": ["Senior React Developer", "Frontend Engineer"],
    "remoteok_tags": ["react", "frontend", "typescript"],
    "wwr_keywords": ["frontend", "react", "typescript"],
    "wwr_exclude": ["ios", "android", "mobile"]
  }
}
```

**`src/profile/yourname/profile.json`**: your full CV in JSON format (experience, skills, education, etc.)

To get your `telegram_chat_id`: start the bot and send `/myid`.

### 4. Start the public tunnel (required for TWA)

```bash
cloudflared tunnel --url http://localhost:8080
# Copy the https://xxx.trycloudflare.com URL to WEBAPP_URL in .env
```

### 5. Run

```bash
python main.py
```

The bot starts, initializes the DB, schedules the pipeline, and launches the web server on port 8080.

## Telegram commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome + command list |
| `/pending` | Show pending job offers |
| `/lastcv` | Download CV for last approved job |
| `/status` | Check agent is running |
| `/myid` | Get your chat ID |

## Telegram Web App

Each job notification includes a **"Ver en App"** button that opens a mini web UI inside Telegram with:

- Job cards with match score badge, skills tags, salary, remote indicator
- Detail view: skills match/gap breakdown, match summary, salary
- Approve / Reject / Later buttons
- CV download as PDF
- Tabs: Pendientes / Aprobadas

## Scheduled events

| Job | Schedule | Description |
|-----|----------|-------------|
| Pipeline | Every 6h (configurable) | Scrape → evaluate → notify |
| Daily summary | 23:00 UTC | Top 5 matches of the day |
| Follow-up reminders | 14:00 UTC daily | Ping approved jobs older than 5 days |
| Skill gap report | Mondays 13:00 UTC | Most common missing skills this week |

## LATAM support

For profiles with `"markets": ["Colombia", "LATAM"]`, the agent additionally scrapes:
- Computrabajo Colombia (`co.computrabajo.com`)
- Elempleo (`elempleo.com`)
- Indeed Colombia (`co.indeed.com`)

Set `"primary_language": "Spanish"` in config.json to get evaluations, CV, cover letters, and interview prep in Spanish. English-required jobs receive a 15-point score penalty.

## Cost estimate

Under normal usage (2 profiles, 6h interval, ~8 jobs/cycle):
- Anthropic: ~$0.05–0.15/day
- Groq: $0 (free tier, 100k tokens/day)
- Infrastructure: runs locally or on any $5/mo VPS

## License

MIT
