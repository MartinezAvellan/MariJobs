import time

from jobspy import scrape_jobs

from src.core.config import MariJobsConfig
from src.core.utils import setup_logging

logger = setup_logging()

COLUMN_MAP = {
    "job_url": "url",
    "job_url_direct": "url_direct",
    "date_posted": "date_posted",
}


def normalize_job(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        mapped_key = COLUMN_MAP.get(key, key)
        if hasattr(value, "isoformat"):
            normalized[mapped_key] = value.isoformat()
        elif str(value) == "nan" or value is None:
            normalized[mapped_key] = ""
        else:
            normalized[mapped_key] = str(value)
    return normalized


def run_search(
    config: MariJobsConfig,
    terms: list[str],
    countries: list[str],
    delay: int = 2,
    remote_only: bool = False,
) -> list[dict]:
    all_jobs = []
    for term in terms:
        for country in countries:
            logger.info(f"Searching for: '{term}' in {country}")
            for site in config.jobspy.sites:
                time.sleep(delay)
                try:
                    location = config.jobspy.location or country
                    df = scrape_jobs(
                        site_name=[site],
                        search_term=term,
                        location=location,
                        results_wanted=config.jobspy.results_per_term,
                        country_indeed=country,
                        is_remote=remote_only or config.jobspy.remote_only,
                    )
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            job = normalize_job(row.to_dict())
                            job["search_term"] = term
                            job["search_country"] = country
                            all_jobs.append(job)
                        logger.info(f"Found {len(df)} results for '{term}' on {site} ({country})")
                    else:
                        logger.info(f"No results for '{term}' on {site} ({country})")
                except Exception as e:
                    logger.error(f"Error searching '{term}' on {site} ({country}): {e}")
    return all_jobs
