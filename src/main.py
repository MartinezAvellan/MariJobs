import asyncio
from pathlib import Path

from dotenv import load_dotenv

from src.core.config import load_config, MariJobsConfig
from src.store.mongo import init_mongo, cleanup_old_jobs
from src.bot.handler import poll_updates
from src.bot.telegram import get_token, set_my_commands
from src.core.utils import setup_logging

logger = setup_logging()


def _resolve_config_path() -> str:
    project_root = Path(__file__).resolve().parent.parent
    return str(project_root / "config" / "marijobs.yml")


async def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")
    config = load_config(_resolve_config_path())
    init_mongo(config.mongo)
    logger.info("MariJobs started (MongoDB connected)")

    token = get_token(config.telegram.bot_token_env)
    if token:
        try:
            await set_my_commands(token, [
                {"command": "start", "description": "Start (uses saved profile if exists)"},
                {"command": "new", "description": "Create profile from scratch"},
                {"command": "terms", "description": "Change search terms only"},
                {"command": "cv", "description": "Re-upload CV"},
                {"command": "apikey", "description": "Change OpenRouter API key"},
                {"command": "model", "description": "Change AI model"},
                {"command": "history", "description": "View voted jobs and track applications"},
                {"command": "interview", "description": "Log interview experience"},
                {"command": "status", "description": "View current profile"},
                {"command": "skip", "description": "Discard pending jobs"},
                {"command": "back", "description": "Go back to previous step"},
            ])
            logger.info("Bot commands registered")
        except Exception as exc:
            logger.warning("Failed to register bot commands: %s", exc)

    asyncio.create_task(_cleanup_loop(config))
    await poll_updates(config)


async def _cleanup_loop(config: MariJobsConfig) -> None:
    interval = config.app.cleanup_interval_hours * 3600
    max_age = config.app.job_max_age_days
    logger.info("Cleanup cron started (every %dh, max age %d days)", config.app.cleanup_interval_hours, max_age)
    while True:
        try:
            deleted = cleanup_old_jobs(max_age)
            logger.info("Cleanup: %d old jobs removed", deleted)
        except Exception as exc:
            logger.error("Cleanup error: %s", exc)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MariJobs stopped")
