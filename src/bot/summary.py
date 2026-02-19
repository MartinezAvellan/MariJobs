def build_single_job_card(job: dict, index: int, total: int,
                          vote_summary: dict | None = None,
                          interview_summary: dict | None = None) -> str:
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    location = job.get("location", "N/A")
    url = job.get("url", "")
    site = job.get("site", "")
    score = job.get("review_score", 0)
    verdict = job.get("review_verdict", "")
    reason = job.get("review_reason", "")
    description = job.get("description", "")

    stars = "\u2b50" * score if score else ""
    lines = [
        f"<b>Job {index}/{total}</b>\n",
        f"{stars} <b>{title}</b>",
        f"{company} | {location} | {site}",
    ]
    if verdict:
        lines.append(f"<i>{verdict}: {reason}</i>")
        recruiter_msg = job.get("recruiter_message", "")
        if recruiter_msg:
            lines.append(f"\n\u2709\ufe0f <b>Suggested message:</b>\n<i>{recruiter_msg}</i>")
    elif description:
        truncated = description[:500].strip()
        if len(description) > 500:
            truncated += "..."
        lines.append(f"\n{truncated}")
    if url:
        lines.append(f'\n<a href="{url}">View job</a>')
    if vote_summary and vote_summary.get("total", 0) > 0:
        up = vote_summary["up"]
        down = vote_summary["down"]
        lines.append(f"\n\U0001f465 {vote_summary['total']} review(s): \U0001f44d {up} | \U0001f44e {down}")
    if interview_summary and interview_summary.get("count", 0) > 0:
        avg = interview_summary["avg_rating"]
        count = interview_summary["count"]
        interview_stars = "\u2b50" * round(avg)
        lines.append(f"\n\U0001f4cb {count} interview(s) {interview_stars} ({avg}/5)")

    return "\n".join(lines)


def build_vote_keyboard(job_id: str = "") -> list[list[dict]]:
    suffix = f":{job_id}" if job_id else ""
    return [
        [
            {"text": "\U0001f44d Relevant", "callback_data": f"vote:up{suffix}"},
            {"text": "\U0001f44e Not relevant", "callback_data": f"vote:down{suffix}"},
        ],
        [
            {"text": "\u23ed Skip", "callback_data": f"vote:skip{suffix}"},
        ],
    ]
