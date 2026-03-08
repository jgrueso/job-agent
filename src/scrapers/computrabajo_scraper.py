"""
Computrabajo scraper — principal portal de empleo Colombia/LATAM.
Busca por keywords en computrabajo.com.co.
"""
import hashlib
import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://co.computrabajo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _job_id(url: str) -> str:
    return "computrabajo_" + hashlib.md5(url.encode()).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


async def _fetch_description(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        desc = soup.find("div", {"id": "offer_description"}) or soup.find("div", class_=re.compile(r"description|offerDesc", re.I))
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
                url = f"{BASE_URL}/trabajo-de-{search_slug}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"[Computrabajo] {keyword}: HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("article", class_=re.compile(r"box_offer|offerBlock", re.I))
                if not cards:
                    # fallback: try generic offer links
                    cards = soup.find_all("div", class_=re.compile(r"box_offer", re.I))

                logger.info(f"[Computrabajo] '{keyword}': {len(cards)} cards found")

                for card in cards[:max_per_keyword]:
                    try:
                        # Title + link
                        title_tag = card.find("a", class_=re.compile(r"js-o-link|title", re.I)) or card.find("h2")
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

                        # Exclude check
                        title_lower = title.lower()
                        if any(ex in title_lower for ex in exclude_set):
                            continue

                        seen_ids.add(job_id)

                        # Company
                        company_tag = card.find("a", class_=re.compile(r"company|empresa", re.I)) or card.find("span", class_=re.compile(r"company", re.I))
                        company = _clean(company_tag.get_text()) if company_tag else "No especificada"

                        # Location
                        loc_tag = card.find("span", class_=re.compile(r"location|ciudad|ubic", re.I))
                        location = _clean(loc_tag.get_text()) if loc_tag else "Colombia"

                        # Salary
                        sal_tag = card.find("span", class_=re.compile(r"salary|salario", re.I))
                        salary = _clean(sal_tag.get_text()) if sal_tag else "No especificado"

                        # Remote detection
                        card_text = card.get_text().lower()
                        is_remote = any(w in card_text for w in ["remoto", "remote", "teletrabajo", "trabajo en casa", "home office"])

                        # Description (fetch detail page)
                        description = await _fetch_description(client, job_url)

                        results.append({
                            "id": job_id,
                            "profile_id": profile_id,
                            "source": "Computrabajo",
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
                        logger.warning(f"[Computrabajo] Card parse error: {e}")

            except Exception as e:
                logger.error(f"[Computrabajo] Error fetching '{keyword}': {e}")

    logger.info(f"[Computrabajo] Total: {len(results)} jobs for profile={profile_id}")
    return results
