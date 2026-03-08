"""
Orchestrator — runs the full pipeline per profile on a schedule.
"""
import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime

from telegram.constants import ParseMode

from src.scrapers import remoteok_scraper, weworkremotely_scraper, linkedin_scraper, computrabajo_scraper, elempleo_scraper, indeed_scraper
from src.evaluator.job_evaluator import evaluate_job
from src.cv_adapter.cv_adapter import adapt_cv
from src.database.db import (
    job_exists, save_job, update_job_status, get_top_jobs_today,
    get_jobs_needing_followup, mark_reminder_sent, get_low_match_jobs_this_week,
)
from src.bot.telegram_bot import send_job_notification

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "profile"


_ENGLISH_MARKERS = [
    " the ", " and ", " you ", " will ", " your ", " with ", " for ", " are ", " this ",
    " that ", " have ", " from ", " our ", " team ", " work ", " role ", " about ",
    "you will", "we are", "we're looking", "you'll be", "requirements:", "responsibilities:",
    "what you'll do", "who you are", "about the role", "about us",
]
_SPANISH_MARKERS = [
    " el ", " la ", " los ", " las ", " una ", " con ", " para ", " por ", " que ", " del ",
    " se ", " en ", " es ", " su ", " sus ", " nos ", " más ",
    "buscamos", "requisitos", "responsabilidades", "ofrecemos", "sobre nosotros",
]


def _is_english_text(text: str) -> bool:
    """Heuristic: returns True if the text is predominantly English (not Spanish)."""
    t = text.lower()
    en_hits = sum(1 for m in _ENGLISH_MARKERS if m in t)
    es_hits = sum(1 for m in _SPANISH_MARKERS if m in t)
    # Consider English if English markers are clearly dominant
    return en_hits >= 6 and en_hits > es_hits * 2


def _keyword_prefilter(job: dict, config: dict) -> bool:
    """
    Fast keyword check before spending API tokens.
    Returns True if the job passes the pre-filter and should be evaluated by AI.
    """
    queries = config.get("search_queries", {})
    # Collect all relevant keywords from the profile's search config
    keywords = set()
    for kw in queries.get("linkedin", []):
        keywords.update(kw.lower().split())
    for tag in queries.get("remoteok_tags", []):
        keywords.update(tag.lower().split("-"))
    for kw in queries.get("wwr_keywords", []):
        keywords.update(kw.lower().split())

    exclude = [w.lower() for w in queries.get("wwr_exclude", [])]

    text = f"{job.get('title', '')} {job.get('raw_description', '')}".lower()

    # Hard exclude
    if any(ex in text for ex in exclude):
        return False

    # Must match at least 1 keyword in title, or 2 in full text
    title = job.get("title", "").lower()
    title_hits = sum(1 for kw in keywords if kw in title)
    if title_hits >= 1:
        return True
    text_hits = sum(1 for kw in keywords if kw in text)
    return text_hits >= 2


def load_profiles() -> list[dict]:
    profiles = []
    for config_path in sorted(PROFILES_DIR.glob("*/config.json")):
        config = json.loads(config_path.read_text())
        profile_path = config_path.parent / "profile.json"
        profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
        profiles.append({**config, "profile_data": profile})
    return profiles


async def run_pipeline_for_profile(app, config: dict):
    profile_id = config["id"]
    name = config["name"]
    chat_id = config.get("telegram_chat_id")
    min_score = config.get("min_match_score", 65)
    queries = config.get("search_queries", {})

    if not chat_id:
        logger.warning(f"[{name}] No telegram_chat_id configured — skipping notifications")

    logger.info(f"[{name}] Pipeline starting...")

    is_latam_profile = "Colombia" in config.get("markets", []) or "LATAM" in config.get("markets", [])
    all_jobs = []

    # RemoteOK
    try:
        jobs = await remoteok_scraper.fetch_jobs(
            target_tags=queries.get("remoteok_tags", []),
            exclude_tags=["designer", "graphic", "ios", "android", "flutter"],
            profile_id=profile_id,
        )
        logger.info(f"[{name}] RemoteOK: {len(jobs)} candidate jobs")
        all_jobs.extend(jobs)
    except Exception as e:
        logger.error(f"[{name}] RemoteOK error: {e}")

    # WeWorkRemotely
    try:
        jobs = await weworkremotely_scraper.fetch_jobs(
            target_keywords=queries.get("wwr_keywords", []),
            exclude_keywords=queries.get("wwr_exclude", []),
            profile_id=profile_id,
        )
        logger.info(f"[{name}] WWR: {len(jobs)} candidate jobs")
        all_jobs.extend(jobs)
    except Exception as e:
        logger.error(f"[{name}] WWR error: {e}")

    # LinkedIn — use geo filter for LATAM/Colombia profiles
    linkedin_geo_id = "100446943" if is_latam_profile else None
    try:
        jobs = await linkedin_scraper.fetch_jobs(
            search_queries=queries.get("linkedin", []),
            profile_id=profile_id,
            geo_id=linkedin_geo_id,
        )
        logger.info(f"[{name}] LinkedIn: {len(jobs)} candidate jobs")
        all_jobs.extend(jobs)
    except Exception as e:
        logger.error(f"[{name}] LinkedIn error: {e}")

    # Portales Colombia/LATAM (Computrabajo, Elempleo, Indeed)
    if is_latam_profile:
        latam_keywords = queries.get("computrabajo_keywords") or queries.get("wwr_keywords", [])
        latam_exclude = queries.get("wwr_exclude", [])

        try:
            jobs = await computrabajo_scraper.fetch_jobs(
                keywords=latam_keywords, exclude_keywords=latam_exclude, profile_id=profile_id,
            )
            logger.info(f"[{name}] Computrabajo: {len(jobs)} candidate jobs")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"[{name}] Computrabajo error: {e}")

        try:
            jobs = await elempleo_scraper.fetch_jobs(
                keywords=latam_keywords, exclude_keywords=latam_exclude, profile_id=profile_id,
            )
            logger.info(f"[{name}] Elempleo: {len(jobs)} candidate jobs")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"[{name}] Elempleo error: {e}")

        try:
            jobs = await indeed_scraper.fetch_jobs(
                keywords=latam_keywords, exclude_keywords=latam_exclude, profile_id=profile_id,
                location="Colombia", remote_only=config.get("modality", []) == ["remote"],
            )
            logger.info(f"[{name}] Indeed: {len(jobs)} candidate jobs")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"[{name}] Indeed error: {e}")

    logger.info(f"[{name}] Total raw: {len(all_jobs)}")

    # Filter duplicates
    new_jobs = [j for j in all_jobs if not await job_exists(j["id"], profile_id)]
    logger.info(f"[{name}] New jobs after dedup: {len(new_jobs)}")

    # Keyword pre-filter (free, no API calls)
    prefiltered = [j for j in new_jobs if _keyword_prefilter(j, config)]
    skipped = len(new_jobs) - len(prefiltered)
    logger.info(f"[{name}] After keyword pre-filter: {len(prefiltered)} (skipped {skipped})")
    new_jobs = prefiltered

    if not new_jobs:
        logger.info(f"[{name}] No new jobs.")
        return

    primary_language = config.get("primary_language", "English")

    # Cap at 8 jobs per pipeline run to respect Groq daily token limits
    if len(new_jobs) > 8:
        logger.info(f"[{name}] Capping to 15 jobs (round-robin by source)")
        # Round-robin sampling: take 3 from each source to avoid LinkedIn monopolizing LATAM runs
        from collections import defaultdict
        by_source: dict[str, list] = defaultdict(list)
        for j in new_jobs:
            by_source[j.get("source", "Other")].append(j)
        # Sort within each source by insertion order (already sorted by recency from scrapers)
        sampled: list[dict] = []
        max_per_source = 4 if is_latam_profile else 8
        for source_jobs in by_source.values():
            sampled.extend(source_jobs[:max_per_source])
        # Final sort by LATAM-aware priority
        if is_latam_profile:
            priority = {"Computrabajo": 0, "Elempleo": 1, "Indeed": 2, "LinkedIn": 3, "WeWorkRemotely": 4, "RemoteOK": 5}
        else:
            priority = {"LinkedIn": 0, "WeWorkRemotely": 1, "RemoteOK": 2, "Computrabajo": 3, "Elempleo": 4, "Indeed": 5}
        new_jobs = sorted(sampled, key=lambda j: priority.get(j.get("source", ""), 9))[:15]

    # Evaluate + adapt
    for job in new_jobs:
        try:
            logger.info(f"[{name}] Evaluating: {job['title']} @ {job['company']}")
            evaluated = await evaluate_job(job, config["profile_data"], primary_language=primary_language)

            # Auto-detect English-only job description for Spanish profiles (pre-AI heuristic)
            if primary_language == "Spanish" and not evaluated.get("requires_english"):
                desc_text = job.get("raw_description", "")
                if desc_text and _is_english_text(desc_text):
                    evaluated["requires_english"] = True
                    logger.info(f"[{name}] Auto-detected English-only job description")

            # Extra penalty: if profile prefers Spanish and job requires English, reduce score further
            if primary_language == "Spanish" and evaluated.get("requires_english"):
                penalty = 20
                evaluated["match_score"] = max(0, evaluated["match_score"] - penalty)
                logger.info(f"[{name}] Language penalty -{penalty} (requires English) → {evaluated['match_score']}%")

            # Modality filter: skip on-site jobs for remote-only profiles
            modality = config.get("modality", [])
            if modality == ["remote"] and not evaluated.get("is_remote", True):
                logger.info(f"[{name}] Skip presencial — {job['title']} @ {job['company']}")
                await save_job({**evaluated, "status": "low_match"})
                continue

            if evaluated["match_score"] < min_score:
                logger.info(f"[{name}] Skip {evaluated['match_score']}% — {job['title']} @ {job['company']}")
                await save_job({**evaluated, "status": "low_match"})
                continue

            logger.info(f"[{name}] Match {evaluated['match_score']}% — adapting CV ({primary_language})...")
            cv_adapted = await adapt_cv(evaluated, config["profile_data"], primary_language=primary_language)
            evaluated["cv_adapted"] = cv_adapted

            await save_job(evaluated)

            if chat_id:
                await send_job_notification(app, evaluated, chat_id)
                await update_job_status(evaluated["id"], profile_id, "notified")

            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"[{name}] Error processing {job.get('title')}: {e}")

    logger.info(f"[{name}] Pipeline done.")


async def send_followup_reminders(app):
    """Remind users to follow up on approved jobs older than 5 days."""
    logger.info("[Followup] Checking for pending follow-ups...")
    profiles = load_profiles()
    for config in profiles:
        chat_id = config.get("telegram_chat_id")
        if not chat_id:
            continue
        try:
            jobs = await get_jobs_needing_followup(config["id"], days=5)
            for job in jobs:
                lang = config.get("primary_language", "English")
                if lang == "Spanish":
                    msg = (
                        f"⏰ *Recordatorio de seguimiento*\n\n"
                        f"Aprobaste *{job['title']}* @ {job['company']} hace 5 días.\n"
                        f"¿Ya aplicaste? Si no, es el momento ideal para hacer seguimiento.\n\n"
                        f"🔗 {job['url']}"
                    )
                else:
                    msg = (
                        f"⏰ *Follow-up Reminder*\n\n"
                        f"You approved *{job['title']}* @ {job['company']} 5 days ago.\n"
                        f"Have you applied? If not, now is a great time to follow up.\n\n"
                        f"🔗 {job['url']}"
                    )
                await app.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
                await mark_reminder_sent(job["id"], config["id"])
                logger.info(f"[Followup] Sent reminder to {config['name']} for {job['title']}")
        except Exception as e:
            logger.error(f"[Followup] Error for {config['name']}: {e}")


async def send_weekly_skill_gaps(app):
    """Every Monday: analyze low-score jobs and report recurring skill gaps."""
    logger.info("[SkillGaps] Sending weekly skill gap analysis...")
    profiles = load_profiles()
    for config in profiles:
        chat_id = config.get("telegram_chat_id")
        if not chat_id:
            continue
        try:
            rows = await get_low_match_jobs_this_week(config["id"])
            if not rows:
                continue

            # Count gap frequency
            gap_count: dict[str, int] = {}
            for row in rows:
                try:
                    missing = json.loads(row.get("skills_missing") or "[]")
                    for skill in missing:
                        skill = skill.strip()
                        if skill:
                            gap_count[skill] = gap_count.get(skill, 0) + 1
                except Exception:
                    pass

            if not gap_count:
                continue

            top_gaps = sorted(gap_count.items(), key=lambda x: x[1], reverse=True)[:8]
            lang = config.get("primary_language", "English")

            if lang == "Spanish":
                lines = [f"📊 *Análisis semanal de brechas — {config['name']}*\n"]
                lines.append(f"En {len(rows)} ofertas evaluadas esta semana, las habilidades que más te faltaron:\n")
                for skill, count in top_gaps:
                    lines.append(f"• *{skill}* — apareció en {count} oferta(s)")
                lines.append("\n💡 Considera reforzar estas áreas para aumentar tu match score.")
            else:
                lines = [f"📊 *Weekly Skills Gap Report — {config['name']}*\n"]
                lines.append(f"Across {len(rows)} evaluated jobs this week, your most common gaps:\n")
                for skill, count in top_gaps:
                    lines.append(f"• *{skill}* — appeared in {count} job(s)")
                lines.append("\n💡 Consider strengthening these areas to boost your match score.")

            await app.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"[SkillGaps] Sent to {config['name']} ({len(top_gaps)} gaps)")
        except Exception as e:
            logger.error(f"[SkillGaps] Error for {config['name']}: {e}")


async def send_daily_summary_all(app):
    """Send each profile a ranked summary of today's top job matches."""
    logger.info("[DailySummary] Sending daily summaries...")
    profiles = load_profiles()
    for config in profiles:
        chat_id = config.get("telegram_chat_id")
        if not chat_id:
            continue
        try:
            jobs = await get_top_jobs_today(config["id"], limit=5)
            if not jobs:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text="📊 *Resumen del día*\n\nNo se encontraron nuevas ofertas hoy.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                continue

            today_str = datetime.utcnow().strftime("%d/%m/%Y")
            lines = [f"📊 *Top ofertas del día — {today_str}*\n"]
            for i, job in enumerate(jobs, 1):
                rec = job.get("recommendation", "Consider")
                rec_icon = {"Apply": "🚀", "Consider": "🤔", "Skip": "🛑"}.get(rec, "🤔")
                remote = "🌍" if job.get("is_remote") else "🏢"
                status_icon = "✅" if job.get("status") == "approved" else ("❌" if job.get("status") == "rejected" else "⏳")
                lines.append(
                    f"{i}\\. {rec_icon} *{job['title']}* @ {job['company']}\n"
                    f"   🎯 {job['match_score']}% | {remote} | {status_icon} | [Ver oferta]({job['url']})"
                )

            await app.bot.send_message(
                chat_id=chat_id,
                text="\n\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            logger.info(f"[DailySummary] Sent to {config['name']} ({len(jobs)} jobs)")
        except Exception as e:
            logger.error(f"[DailySummary] Error for {config['name']}: {e}")


async def run_pipeline(app):
    """Run pipeline for all configured profiles."""
    logger.info(f"[Pipeline] Starting at {datetime.utcnow().isoformat()}")
    profiles = load_profiles()
    logger.info(f"[Pipeline] Profiles found: {[p['name'] for p in profiles]}")

    for config in profiles:
        await run_pipeline_for_profile(app, config)
