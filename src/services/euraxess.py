import time

import httpx
from bs4 import BeautifulSoup

from src.core.utils import setup_logging

logger = setup_logging()

BASE_URL = "https://euraxess.ec.europa.eu"
SEARCH_URL = f"{BASE_URL}/jobs/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_PAGES = 3


def _parse_job(li: BeautifulSoup) -> dict | None:
    title_el = li.select_one("h3.ecl-content-block__title a")
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    url = f"{BASE_URL}{href}" if href.startswith("/") else href

    meta_items = li.select(".ecl-content-block__primary-meta-item")
    company = meta_items[0].get_text(strip=True) if meta_items else ""
    date_posted = ""
    if len(meta_items) > 1:
        date_posted = meta_items[1].get_text(strip=True).replace("Posted on: ", "")

    country_el = li.select_one(".ecl-label.ecl-label--highlight")
    country = country_el.get_text(strip=True) if country_el else ""

    desc_el = li.select_one(".ecl-content-block__description")
    description = desc_el.get_text(strip=True) if desc_el else ""

    location_el = li.select_one("div[class*='id-Work-Locations']")
    location = ""
    if location_el:
        divs = location_el.select("div")
        if divs:
            location = divs[-1].get_text(strip=True)

    deadline_el = li.select_one("div[class*='id-Application-Deadline'] time")
    deadline = deadline_el.get("datetime", "") if deadline_el else ""

    return {
        "site": "euraxess",
        "title": title,
        "url": url,
        "company": company,
        "location": location or country,
        "description": description,
        "date_posted": date_posted,
        "deadline": deadline,
    }


COUNTRY_MAP = {
    "portugal": "Portugal",
    "spain": "Spain",
    "france": "France",
    "germany": "Germany",
    "netherlands": "Netherlands",
    "uk": "United Kingdom",
    "ireland": "Ireland",
    "estonia": "Estonia",
    "latvia": "Latvia",
    "lithuania": "Lithuania",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "norway": "Norway",
    "usa": "United States",
}


def search_euraxess(term: str, country: str = "", max_results: int = 30, delay: int = 2) -> list[dict]:
    jobs = []
    headers = {"User-Agent": USER_AGENT}

    for page in range(MAX_PAGES):
        if page > 0:
            time.sleep(delay)
        params = {
            "f[0]": "offer_type:job_offer",
            "f[1]": f"keywords:{term}",
            "page": page,
        }
        euraxess_country = COUNTRY_MAP.get(country.lower(), "")
        if euraxess_country:
            params["f[2]"] = f"offer_country:{euraxess_country}"
        try:
            resp = httpx.get(SEARCH_URL, params=params, headers=headers, timeout=30, follow_redirects=True)
            if resp.status_code != 200:
                logger.error(f"Euraxess HTTP {resp.status_code} for '{term}' page {page}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select("ul[aria-label='Search results items'] > li")

            if not items:
                break

            for li in items:
                job = _parse_job(li)
                if job:
                    job["search_term"] = term
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        return jobs

        except Exception as e:
            logger.error(f"Euraxess scrape error for '{term}' page {page}: {e}")
            break

    logger.info(f"Euraxess: {len(jobs)} results for '{term}'")
    return jobs
