from pathlib import Path

import yaml
from pydantic import BaseModel


class AppConfig(BaseModel):
    timezone: str = "Europe/Lisbon"
    max_new_jobs_in_message: int = 50
    db_cache_hours: int = 48
    scrape_delay: int = 2
    job_max_age_days: int = 30
    cleanup_interval_hours: int = 24


class MongoConfig(BaseModel):
    uri_env: str = "MONGO_URI"
    database: str = "marijobs"


class CountryOption(BaseModel):
    label: str
    value: str


class JobSpyConfig(BaseModel):
    terms: list[str] = []
    location: str = ""
    remote_only: bool = False
    results_per_term: int = 30
    sites: list[str] = ["linkedin", "indeed", "glassdoor", "google"]
    country_options: list[CountryOption] = []


class ActiveConfig(BaseModel):
    inactive_after_misses: int = 3


class TelegramConfig(BaseModel):
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"


class OpenRouterConfig(BaseModel):
    enabled: bool = True
    api_key_env: str = "OPENROUTER_API_KEY"
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4.1-mini"
    max_chars_per_job: int = 800
    prompt_style: str = "short"
    min_relevance_score: int = 3
    whitelisted_phones: list[str] = []


class MariJobsConfig(BaseModel):
    app: AppConfig = AppConfig()
    mongo: MongoConfig = MongoConfig()
    jobspy: JobSpyConfig = JobSpyConfig()
    active: ActiveConfig = ActiveConfig()
    telegram: TelegramConfig = TelegramConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()


def load_config(path: str = "config/marijobs.yml") -> MariJobsConfig:
    with open(Path(path).resolve()) as f:
        data = yaml.safe_load(f)
    return MariJobsConfig(**data)
