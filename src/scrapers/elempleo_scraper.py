"""
Elempleo scraper — segundo portal de empleo más grande de Colombia.
"""
import hashlib
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.elempleo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _job_id(url: str) -> str:
    return "elempleo_" + hashlib.md5(url.encode()).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        desc = soup.find(class_="js-description")
        return _clean(desc.get_text(" ")) if desc else ""
    except Exception:
        return ""


async def fetch_jobs(keywords: list[str], exclude_keywords: list[str], profile_id: str, max_per_keyword: int = 5) -> list[dict]:
    results = []
    seen_ids = set()
    exclude_set = {k.lower() for k in exclude_keywords}

    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for keyword in keywords:
            try:
                search_slug = keyword.lower().replace(" ", "-")
                url = f"{BASE_URL}/co/ofertas-empleo/{search_slug}/"
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"[Elempleo] '{keyword}': HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("div", class_="result-item")
                logger.info(f"[Elempleo] '{keyword}': {len(cards)} cards found")

                for card in cards[:max_per_keyword]:
                    try:
                        title_tag = card.find("a", class_="js-offer-title")
                        if not title_tag:
                            continue
                        title = _clean(title_tag.get_text())
                        href = title_tag.get("href", "")
                        if not href:
                            continue
                        job_url = href if href.startswith("http") else BASE_URL + href

                        job_id = _job_id(job_url)
                        if job_id in seen_ids:
                            continue

                        if any(ex in title.lower() for ex in exclude_set):
                            continue

                        seen_ids.add(job_id)

                        company_tag = card.find("span", class_="info-company-name")
                        company = _clean(company_tag.get_text()) if company_tag else "No especificada"

                        city_tag = card.find("span", class_="info-city")
                        location = _clean(city_tag.get_text()) if city_tag else "Colombia"

                        sal_tag = card.find("span", class_="info-salary")
                        salary = _clean(sal_tag.get_text()) if sal_tag else "No especificado"

                        card_text = card.get_text().lower()
                        is_remote = any(w in card_text for w in ["remoto", "remote", "teletrabajo", "home office", "trabajo en casa"])

                        description = await _fetch_description(client, job_url)

                        results.append({
                            "id": job_id,
                            "profile_id": profile_id,
                            "source": "Elempleo",
                            "title": title,
                            "company": company,
                            "url": job_url,
                            "location": location,
                            "salary": salary,
                            "is_remote": is_remote,
                            "requires_english": False,
                            "skills": [],
                            "raw_description": description,
                            "found_at": datetime.utcnow().isoformat(),
                        })

                    except Exception as e:
                        logger.warning(f"[Elempleo] Card parse error: {e}")

            except Exception as e:
                logger.error(f"[Elempleo] Error fetching '{keyword}': {e}")

    logger.info(f"[Elempleo] Total: {len(results)} jobs for profile={profile_id}")
    return results
