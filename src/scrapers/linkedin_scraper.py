"""
LinkedIn Jobs scraper — uses the public guest API (no auth required).
Accepts search queries from profile config.
"""
import hashlib
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
import asyncio

LINKEDIN_BASE = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def _fetch_job_detail(client: httpx.AsyncClient, job_id: str) -> str:
    try:
        url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        resp = await client.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            desc = soup.find("div", {"class": "description__text"})
            if desc:
                return desc.get_text(separator="\n", strip=True)
    except Exception:
        pass
    return ""


async def fetch_jobs(search_queries: list[str], profile_id: str) -> list[dict]:
    results = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        for query in search_queries:
            params = {
                "start": 0,
                "count": 10,
                "sortBy": "DD",
                "keywords": query,
                "f_WT": "2",  # Remote
            }

            try:
                resp = await client.get(LINKEDIN_BASE, params=params)
                if resp.status_code != 200:
                    print(f"[LinkedIn:{profile_id}] Status {resp.status_code} for: {query}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.find_all("li")

                for card in cards:
                    link_tag = card.find("a", {"class": "base-card__full-link"}) or card.find("a", href=True)
                    if not link_tag:
                        continue

                    href = link_tag.get("href", "")
                    li_id = ""
                    if "/jobs/view/" in href:
                        li_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                    elif "currentJobId=" in href:
                        li_id = href.split("currentJobId=")[1].split("&")[0]

                    if not li_id or li_id in seen_ids:
                        continue
                    seen_ids.add(li_id)

                    title_tag = card.find("h3", {"class": "base-search-card__title"})
                    company_tag = card.find("h4", {"class": "base-search-card__subtitle"})
                    location_tag = card.find("span", {"class": "job-search-card__location"})
                    salary_tag = card.find("span", {"class": "job-search-card__salary-info"})

                    title = title_tag.get_text(strip=True) if title_tag else ""
                    company = company_tag.get_text(strip=True) if company_tag else ""
                    location = location_tag.get_text(strip=True) if location_tag else "Remote"
                    salary = salary_tag.get_text(strip=True) if salary_tag else "Not specified"

                    await asyncio.sleep(1.5)
                    description = await _fetch_job_detail(client, li_id)

                    job_hash = hashlib.md5(li_id.encode()).hexdigest()
                    results.append({
                        "id": f"linkedin_{job_hash}",
                        "profile_id": profile_id,
                        "source": "LinkedIn",
                        "title": title,
                        "company": company,
                        "url": f"https://www.linkedin.com/jobs/view/{li_id}/",
                        "location": location,
                        "salary": salary,
                        "is_remote": True,
                        "requires_english": "english" in query.lower() or "remote" in location.lower(),
                        "skills": [],
                        "raw_description": description,
                        "found_at": datetime.utcnow().isoformat(),
                    })

                await asyncio.sleep(3)

            except Exception as e:
                print(f"[LinkedIn:{profile_id}] Error for '{query}': {e}")

    return results
