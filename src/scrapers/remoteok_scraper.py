"""
RemoteOK scraper — public JSON API, profile-aware tag filtering.
"""
import hashlib
import httpx
from datetime import datetime

REMOTEOK_URL = "https://remoteok.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}


def _parse_salary(job: dict) -> str:
    low = job.get("salary_min")
    high = job.get("salary_max")
    currency = job.get("salary_currency", "USD")
    if low and high:
        return f"{currency} ${low:,} - ${high:,} / year"
    if low:
        return f"{currency} ${low:,}+ / year"
    return "Not specified"


async def fetch_jobs(target_tags: list[str], exclude_tags: list[str], profile_id: str) -> list[dict]:
    target_set = {t.lower() for t in target_tags}
    exclude_set = {t.lower() for t in exclude_tags}

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        resp = await client.get(REMOTEOK_URL)
        resp.raise_for_status()
        data = resp.json()

    raw_jobs = [j for j in data if isinstance(j, dict) and "position" in j]
    results = []

    for job in raw_jobs:
        tags = {t.lower() for t in (job.get("tags") or [])}
        title = (job.get("position") or "").lower()

        if tags & exclude_set:
            continue
        if not (tags & target_set or any(t in title for t in target_set)):
            continue

        job_id = hashlib.md5(job.get("url", str(job.get("id", ""))).encode()).hexdigest()
        results.append({
            "id": f"remoteok_{job_id}",
            "profile_id": profile_id,
            "source": "RemoteOK",
            "title": job.get("position", ""),
            "company": job.get("company", ""),
            "url": job.get("url", f"https://remoteok.com/l/{job.get('id', '')}"),
            "location": "Remote",
            "salary": _parse_salary(job),
            "is_remote": True,
            "requires_english": True,
            "skills": list(job.get("tags") or []),
            "raw_description": job.get("description", ""),
            "found_at": datetime.utcnow().isoformat(),
        })

    return results
