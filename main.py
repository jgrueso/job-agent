"""
Job Agent — Entry point.
Runs PTB bot and FastAPI (TWA backend) concurrently in the same asyncio event loop.
"""
import asyncio
import logging
import os
import signal
from datetime import time as dt_time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from telegram.ext import Application

from src.database.db import init_db
from src.bot.telegram_bot import build_app
from src.scheduler.scheduler import run_pipeline, send_daily_summary_all, send_followup_reminders, send_weekly_skill_gaps
from src.webapp.api import app as fastapi_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

LOCK_FILE = Path("/tmp/job-agent.lock")


async def post_init(app: Application) -> None:
    """Called after the bot starts — initialises DB and schedules the pipeline."""
    await init_db()
    logger.info("Database initialized.")

    interval_hours = int(os.getenv("SEARCH_INTERVAL_HOURS", "6"))

    # Run immediately on startup
    app.job_queue.run_once(
        lambda ctx: run_pipeline(ctx.application),
        when=5,
        name="pipeline_startup",
    )

    # Then repeat every N hours
    app.job_queue.run_repeating(
        lambda ctx: run_pipeline(ctx.application),
        interval=interval_hours * 3600,
        first=interval_hours * 3600,
        name="pipeline_scheduled",
    )

    logger.info(f"Pipeline scheduled — every {interval_hours} hours.")

    # Daily summary at configurable UTC hour (default 23:00 UTC = 6 PM Colombia)
    summary_hour = int(os.getenv("DAILY_SUMMARY_HOUR_UTC", "23"))
    app.job_queue.run_daily(
        lambda ctx: send_daily_summary_all(ctx.application),
        time=dt_time(hour=summary_hour, minute=0),
        name="daily_summary",
    )
    logger.info(f"Daily summary scheduled at {summary_hour:02d}:00 UTC.")

    # Follow-up reminders — daily at 14:00 UTC (9 AM Colombia)
    app.job_queue.run_daily(
        lambda ctx: send_followup_reminders(ctx.application),
        time=dt_time(hour=14, minute=0),
        name="followup_reminders",
    )

    # Weekly skill gap report — every Monday at 13:00 UTC (8 AM Colombia)
    app.job_queue.run_daily(
        lambda ctx: send_weekly_skill_gaps(ctx.application),
        time=dt_time(hour=13, minute=0),
        days=(0,),  # Monday only
        name="weekly_skill_gaps",
    )


def _check_single_instance():
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            os.kill(old_pid, signal.SIGKILL)
            logger.warning(f"Killed previous instance PID {old_pid}")
        except (ProcessLookupError, ValueError):
            pass
        LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))


async def run_all():
    _check_single_instance()

    ptb_app = build_app()
    ptb_app.post_init = post_init

    webapp_port = int(os.getenv("WEBAPP_PORT", "8080"))
    uvicorn_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=webapp_port,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    logger.info("Job Agent starting...")
    logger.info(f"WebApp (TWA) listening on port {webapp_port}")

    try:
        async with ptb_app:
            await ptb_app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            await ptb_app.start()
            await uvicorn_server.serve()
            await ptb_app.updater.stop()
            await ptb_app.stop()
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def main():
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
