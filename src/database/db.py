import aiosqlite
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT NOT NULL,
                profile_id TEXT NOT NULL DEFAULT 'jeferson',
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                url TEXT NOT NULL,
                location TEXT,
                salary TEXT,
                is_remote INTEGER DEFAULT 0,
                requires_english INTEGER DEFAULT 0,
                skills TEXT,
                raw_description TEXT,
                match_score INTEGER,
                match_summary TEXT,
                cv_adapted TEXT,
                status TEXT DEFAULT 'pending',
                found_at TEXT NOT NULL,
                notified_at TEXT,
                applied_at TEXT,
                PRIMARY KEY (id, profile_id)
            )
        """)
        # Migrations
        for migration in [
            "ALTER TABLE jobs ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'jeferson'",
            "ALTER TABLE jobs ADD COLUMN approved_at TEXT",
            "ALTER TABLE jobs ADD COLUMN reminder_sent INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN skills_missing TEXT",
        ]:
            try:
                await db.execute(migration)
            except Exception:
                pass
        await db.commit()


async def job_exists(job_id: str, profile_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM jobs WHERE id = ? AND profile_id = ?", (job_id, profile_id)
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_job(job: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO jobs
            (id, profile_id, source, title, company, url, location, salary, is_remote,
             requires_english, skills, raw_description, match_score,
             match_summary, cv_adapted, status, found_at, skills_missing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job["id"],
            job.get("profile_id", "jeferson"),
            job["source"],
            job["title"],
            job["company"],
            job["url"],
            job.get("location", ""),
            job.get("salary", "Not specified"),
            1 if job.get("is_remote") else 0,
            1 if job.get("requires_english") else 0,
            json.dumps(job.get("skills", [])),
            job.get("raw_description", ""),
            job.get("match_score", 0),
            job.get("match_summary", ""),
            job.get("cv_adapted", ""),
            job.get("status", "pending"),
            datetime.utcnow().isoformat(),
            json.dumps(job.get("skills_missing", [])),
        ))
        await db.commit()


async def update_job_status(job_id: str, profile_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        if status == "applied":
            await db.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE id = ? AND profile_id = ?",
                (status, now, job_id, profile_id),
            )
        elif status == "approved":
            await db.execute(
                "UPDATE jobs SET status = ?, approved_at = ?, notified_at = ? WHERE id = ? AND profile_id = ?",
                (status, now, now, job_id, profile_id),
            )
        else:
            await db.execute(
                "UPDATE jobs SET status = ?, notified_at = ? WHERE id = ? AND profile_id = ?",
                (status, now, job_id, profile_id),
            )
        await db.commit()


async def get_jobs_needing_followup(profile_id: str, days: int = 5) -> list[dict]:
    """Approved jobs older than `days` days with no follow-up reminder sent yet."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM jobs
               WHERE profile_id = ? AND status = 'approved'
               AND approved_at <= ? AND (reminder_sent IS NULL OR reminder_sent = 0)""",
            (profile_id, cutoff)
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["skills"] = json.loads(d["skills"] or "[]")
                result.append(d)
            return result


async def mark_reminder_sent(job_id: str, profile_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET reminder_sent = 1 WHERE id = ? AND profile_id = ?",
            (job_id, profile_id)
        )
        await db.commit()


async def get_low_match_jobs_this_week(profile_id: str) -> list[dict]:
    """Jobs with low match from the past 7 days for skills gap analysis."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT skills_missing, match_score FROM jobs
               WHERE profile_id = ? AND found_at >= ?
               AND status IN ('low_match', 'rejected', 'pending')
               AND skills_missing IS NOT NULL AND skills_missing != ''""",
            (profile_id, cutoff)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_job(job_id: str, profile_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE id = ? AND profile_id = ?", (job_id, profile_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                d = dict(row)
                d["skills"] = json.loads(d["skills"] or "[]")
                return d
    return None


async def get_approved_jobs(profile_id: str, limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE status = 'approved' AND profile_id = ? ORDER BY applied_at DESC LIMIT ?",
            (profile_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["skills"] = json.loads(d["skills"] or "[]")
                result.append(d)
            return result


async def get_top_jobs_today(profile_id: str, limit: int = 5) -> list[dict]:
    today = datetime.utcnow().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM jobs
               WHERE profile_id = ? AND status != 'low_match' AND found_at >= ?
               ORDER BY match_score DESC LIMIT ?""",
            (profile_id, today, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["skills"] = json.loads(d["skills"] or "[]")
                result.append(d)
            return result


async def get_pending_jobs(profile_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND profile_id = ? ORDER BY match_score DESC",
            (profile_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["skills"] = json.loads(d["skills"] or "[]")
                result.append(d)
            return result
