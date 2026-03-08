"""
We Work Remotely — RSS feed scraper, profile-aware keyword filtering.
"""
import hashlib
import feedparser
import httpx
from datetime import datetime

FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}


async def fetch_jobs(target_keywords: list[str], exclude_keywords: list[str], profile_id: str) -> list[dict]:
    results = []

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        for feed_url in FEEDS:
            try:
                resp = await client.get(feed_url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)

                for entry in feed.entries:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    text = (title + " " + summary).lower()

                    if any(k in text for k in exclude_keywords):
                        continue
                    if not any(k in text for k in target_keywords):
                        continue

                    job_id = hashlib.md5(entry.get("link", title).encode()).hexdigest()
                    parts = title.split("|") if "|" in title else title.split("–")
                    company = parts[0].strip() if len(parts) > 1 else "Unknown"
                    role = parts[-1].strip() if len(parts) > 1 else title

                    results.append({
                        "id": f"wwr_{job_id}",
                        "profile_id": profile_id,
                        "source": "WeWorkRemotely",
                        "title": role,
                        "company": company,
                        "url": entry.get("link", ""),
                        "location": "Remote",
                        "salary": "Not specified",
                        "is_remote": True,
                        "requires_english": True,
                        "skills": [],
                        "raw_description": summary,
                        "found_at": datetime.utcnow().isoformat(),
                    })
            except Exception as e:
                print(f"[WWR:{profile_id}] Error: {e}")

    return results
