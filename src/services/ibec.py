import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from src.core.utils import setup_logging

logger = setup_logging()

LISTING_URL = "https://ibecbarcelona.eu/careers-at-ibec/jobs/jobs-scientific-and-technical-job-opportunities/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_PAGES = 5


def _parse_deadline(text: str) -> datetime | None:
    text = text.strip()
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", text)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _is_deadline_valid(deadline_str: str) -> bool:
    if not deadline_str:
        return True
    dt = _parse_deadline(deadline_str)
    if not dt:
        return True
    return dt.date() >= datetime.now(timezone.utc).date()


def _extract_deadline(text: str) -> str:
    text = text.replace("\xa0", " ")
    match = re.search(r"[Dd]eadline[;:]?\s*(.+)", text)
    if match:
        return match.group(1).strip()
    return ""


def _parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("div.entry-content")
    if not content:
        return []

    jobs = []
    containers = content.select("div.post-content-area")

    for container in containers:
        title_el = container.select_one("h2.post-title a[href]")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        url = title_el.get("href", "")
        if not title or not url:
            continue
        if not url.startswith("http"):
            url = f"https://ibecbarcelona.eu{url}"

        deadline = ""
        ref_el = container.select_one("div.hover-excerpt")
        if ref_el:
            ref_text = ref_el.get_text(strip=True)
            deadline = _extract_deadline(ref_text)

        date_el = container.select_one("div.post-meta")
        date_posted = date_el.get_text(strip=True) if date_el else ""

        jobs.append({
            "site": "ibec",
            "title": title,
            "url": url,
            "company": "IBEC Barcelona",
            "location": "Barcelona, Spain",
            "description": "",
            "date_posted": date_posted,
            "deadline": deadline,
        })

    return jobs


def _fetch_detail(url: str, headers: dict) -> str:
    try:
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        content = soup.select_one("div.entry-content")
        if content:
            return content.get_text(separator="\n", strip=True)[:3000]
    except Exception as e:
        logger.error(f"IBEC detail fetch error for {url}: {e}")
    return ""


def _matches_term(job: dict, term: str) -> bool:
    term_lower = term.lower()
    return (
        term_lower in job.get("title", "").lower()
        or term_lower in job.get("description", "").lower()
    )


def search_ibec(term: str, max_results: int = 20, delay: int = 2) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    all_jobs = []

    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(delay)
        url = LISTING_URL if page == 1 else f"{LISTING_URL}?paged9={page}"
        try:
            resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
            if resp.status_code != 200:
                break
            page_jobs = _parse_listing_page(resp.text)
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)
        except Exception as e:
            logger.error(f"IBEC listing error page {page}: {e}")
            break

    valid_jobs = [j for j in all_jobs if _is_deadline_valid(j.get("deadline", ""))]
    logger.info(f"IBEC: {len(valid_jobs)} with valid deadline (from {len(all_jobs)} total)")

    matched = []
    for job in valid_jobs:
        time.sleep(delay)
        job["description"] = _fetch_detail(job["url"], headers)
        if _matches_term(job, term):
            job["search_term"] = term
            matched.append(job)
            if len(matched) >= max_results:
                break

    logger.info(f"IBEC: {len(matched)} results matching '{term}'")
    return matched
