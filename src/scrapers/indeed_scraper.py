"""
Indeed Colombia scraper — portal global con fuerte presencia en Colombia/LATAM.
Usa co.indeed.com con filtro de trabajo remoto.
"""
import hashlib
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://co.indeed.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://co.indeed.com/",
}


def _job_id(url: str) -> str:
    return "indeed_" + hashlib.md5(url.encode()).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        desc = soup.find("div", id="jobDescriptionText") or soup.find("div", class_=re.compile(r"jobDescription|job-description", re.I))
        return _clean(desc.get_text(" ")) if desc else ""
    except Exception:
        return ""


async def fetch_jobs(keywords: list[str], exclude_keywords: list[str], profile_id: str,
                     location: str = "Colombia", remote_only: bool = True, max_per_keyword: int = 5) -> list[dict]:
    results = []
    seen_ids = set()
    exclude_set = {k.lower() for k in exclude_keywords}

    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for keyword in keywords:
            try:
                params = {"q": keyword, "l": location, "sort": "date"}
                if remote_only:
                    params["remotejobs"] = "1"

                resp = await client.get(f"{BASE_URL}/jobs", params=params)
                if resp.status_code != 200:
                    logger.warning(f"[Indeed] '{keyword}': HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("div", class_=re.compile(r"job_seen_beacon|jobsearch-SerpJobCard|result ", re.I))
                if not cards:
                    cards = soup.find_all("li", class_=re.compile(r"job_seen_beacon", re.I))

                logger.info(f"[Indeed] '{keyword}': {len(cards)} cards found")

                for card in cards[:max_per_keyword]:
                    try:
                        title_tag = card.find("a", class_=re.compile(r"jcs-JobTitle|jobtitle", re.I)) or card.find("h2")
                        if not title_tag:
                            continue
                        title = _clean(title_tag.get_text())

                        href = title_tag.get("href", "")
                        if not href and title_tag.find("a"):
                            href = title_tag.find("a").get("href", "")
                        if not href:
                            continue
                        job_url = href if href.startswith("http") else BASE_URL + href

                        job_id = _job_id(job_url)
                        if job_id in seen_ids:
                            continue

                        title_lower = title.lower()
                        if any(ex in title_lower for ex in exclude_set):
                            continue

                        seen_ids.add(job_id)

                        company_tag = card.find(class_=re.compile(r"companyName|company", re.I))
                        company = _clean(company_tag.get_text()) if company_tag else "No especificada"

                        loc_tag = card.find(class_=re.compile(r"companyLocation|location", re.I))
                        location_text = _clean(loc_tag.get_text()) if loc_tag else location

                        sal_tag = card.find(class_=re.compile(r"salary-snippet|salaryText", re.I))
                        salary = _clean(sal_tag.get_text()) if sal_tag else "No especificado"

                        card_text = card.get_text().lower()
                        is_remote = any(w in card_text for w in ["remoto", "remote", "teletrabajo", "home office"])

                        description = await _fetch_description(client, job_url)

                        results.append({
                            "id": job_id,
                            "profile_id": profile_id,
                            "source": "Indeed",
                            "title": title,
                            "company": company,
                            "url": job_url,
                            "location": location_text,
                            "salary": salary,
                            "is_remote": is_remote,
                            "requires_english": False,
                            "skills": [],
                            "raw_description": description,
                            "found_at": datetime.utcnow().isoformat(),
                        })

                    except Exception as e:
                        logger.warning(f"[Indeed] Card parse error: {e}")

            except Exception as e:
                logger.error(f"[Indeed] Error fetching '{keyword}': {e}")

    logger.info(f"[Indeed] Total: {len(results)} jobs for profile={profile_id}")
    return results
