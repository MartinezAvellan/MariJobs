import os

import httpx

from src.core.config import OpenRouterConfig
from src.core.utils import setup_logging

logger = setup_logging()

REVIEW_PROMPT = """You are a technical recruiter. Given the candidate's CV and a job, assess the relevance.

Candidate's CV:
{cv}

Job:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Answer EXACTLY in this format (no markdown):
Score: X/5
Verdict: RELEVANT or NOT RELEVANT
Reason: explanation in 1 sentence
Message: a short 2-3 sentence message the candidate could send to the recruiter for this role"""


async def review_job(config: OpenRouterConfig, cv_text: str, job: dict, api_key: str = "", model: str = "") -> dict:
    key = api_key or os.environ.get(config.api_key_env, "")
    if not key:
        return {"score": 0, "verdict": "NO API KEY", "reason": "", "recruiter_message": ""}

    desc = (job.get("description") or "")[:config.max_chars_per_job]
    prompt = REVIEW_PROMPT.format(
        cv=cv_text[:3000],
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        description=desc,
    )

    use_model = model or config.model

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": use_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                },
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                return _parse_review(text)
            else:
                logger.error(f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"OpenRouter review error: {e}")

    return {"score": 0, "verdict": "ERROR", "reason": "", "recruiter_message": ""}


def _parse_review(text: str) -> dict:
    score = 0
    verdict = ""
    reason = ""
    recruiter_message = ""

    for line in text.strip().splitlines():
        line = line.strip()
        if line.lower().startswith("score:"):
            try:
                score = int(line.split(":")[1].strip().split("/")[0])
            except (ValueError, IndexError):
                pass
        elif line.lower().startswith("verdict:"):
            verdict = line.split(":", 1)[1].strip()
        elif line.lower().startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
        elif line.lower().startswith("message:"):
            recruiter_message = line.split(":", 1)[1].strip()

    return {"score": score, "verdict": verdict, "reason": reason, "recruiter_message": recruiter_message}
