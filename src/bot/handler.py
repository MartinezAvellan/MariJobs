import asyncio
import os
import tempfile

import httpx

from src.core.config import MariJobsConfig
from src.services.cv_parser import extract_cv_text
from src.services.jobspy import run_search
from src.services.euraxess import search_euraxess
from src.services.ibec import search_ibec
from src.store.mongo import (
    get_user, save_user,
    save_jobs_batch, get_cached_review, save_review, save_search,
    create_queue, get_queue, advance_queue, mark_queue_completed,
    delete_queue, has_active_queue,
    set_search_phase, set_searching, check_is_searching, extend_queue,
    save_vote, save_feedback,
    find_jobs_by_terms, get_job_by_id,
    save_interview, get_interview_summary, has_user_interview,
    get_vote_summary, get_voted_job_ids,
    save_application, get_application, delete_application,
    get_voted_jobs_with_details, count_user_votes,
)
from src.services.openrouter import review_job
from src.bot.summary import build_single_job_card, build_vote_keyboard
from src.bot.telegram import (
    get_token,
    send_message,
    send_inline_keyboard,
    answer_callback,
    edit_message_text,
    edit_message_reply_markup,
    download_file,
    request_contact,
    remove_keyboard,
)
from src.core.utils import setup_logging, set_user_context, clear_user_context

logger = setup_logging()

STATES = {}

APPLICATION_STAGES = ["applied", "screening", "interview", "offer", "closed"]
STAGE_LABELS = {
    "applied": "\U0001f4e8 Applied",
    "screening": "\U0001f50d Screening",
    "interview": "\U0001f4ac Interview",
    "offer": "\U0001f4b0 Offer",
    "closed": "\u2705 Closed",
}
HISTORY_PAGE_SIZE = 5

MSG_GREETING = (
    "<b>MariJobs Bot</b>\n\n"
    "I search for jobs across 4 sources (LinkedIn, Indeed, Glassdoor,\n"
    "Google) and use AI to validate\n"
    "relevance based on your CV.\n\n"
    "<b>How it works:</b>\n"
    "1. Share your contact (phone)\n"
    "2. Send your CV (PDF)\n"
    "3. Enter search terms (e.g.: microfluidics, postdoc)\n"
    "4. Choose countries and search\n"
    "5. Rate each job individually (\U0001f44d/\U0001f44e)\n\n"
    "<b>Commands:</b>\n"
    "/start - Start (uses saved profile if it exists)\n"
    "/new - Create profile from scratch\n"
    "/terms - Change search terms only\n"
    "/cv - Resend CV\n"
    "/apikey - Change OpenRouter API key\n"
    "/model - Change AI model\n"
    "/interview - Log interview experience\n"
    "/history - View voted jobs and track applications\n"
    "/back - Go back to previous step\n"
    "/status - View your current profile\n"
    "/skip - Discard pending jobs"
)

MSG_ASK_PHONE = (
    "<b>Step 1 - Share your contact</b>\n\n"
    "Tap the <b>Share contact</b> button that appears\n"
    "in place of the keyboard (you may need to tap the keyboard icon).\n\n"
    "Or send your number manually (e.g.: <code>+351912345678</code>)."
)

MSG_ASK_API_KEY = (
    "<b>OpenRouter Key</b>\n\n"
    "To use AI in job analysis, send your\n"
    "<a href=\"https://openrouter.ai/keys\">OpenRouter</a> API key.\n\n"
    "It will be saved securely for future searches.\n\n"
    "Or tap <b>Skip</b> to see jobs without AI analysis\n"
    "(the job description will be shown instead)."
)

MSG_ASK_MODEL = (
    "<b>AI Model</b>\n\n"
    "Current model: <code>{model}</code>\n\n"
    "Send the model name to change\n"
    "(e.g.: <code>z-ai/glm-4.5-air:free</code>)\n"
    "or tap the button to use the current one."
)

MSG_ASK_CV = (
    "<b>Step 2 - Send your CV</b>\n\n"
    "Send a <b>PDF</b> file with your CV.\n"
    "It will be saved so you don't need to send it again."
)

MSG_ASK_TERMS = (
    "<b>Step 3 - Search terms</b>\n\n"
    "Send the terms separated by <b>comma</b>.\n"
    "Example: <i>microfluidics, postdoc, R&amp;D engineer</i>\n\n"
    "/back to resend the CV"
)

MSG_PICK_COUNTRIES = (
    "<b>Step 4 - Countries</b>\n"
    "Terms: <b>{terms}</b>\n\n"
    "Tap countries to check/uncheck.\n"
    "Enable <b>Remote</b> to search only remote jobs.\n"
    "Then tap <b>Search</b>."
)

MSG_PROFILE_FOUND = (
    "<b>Profile found!</b>\n\n"
    "CV: \u2705 saved\n"
    "Terms: <b>{terms}</b>\n\n"
    "Choose an option:"
)

MSG_EDIT_API_KEY = (
    "<b>Change API Key</b>\n\n"
    "Current status: {status}\n\n"
    "Send the new "
    "<a href=\"https://openrouter.ai/keys\">OpenRouter</a> API key\n"
    "or choose an option below."
)

MSG_EDIT_MODEL = (
    "<b>Change AI model</b>\n\n"
    "Current model: <code>{model}</code>\n\n"
    "Send the new model name\n"
    "(e.g.: <code>z-ai/glm-4.5-air:free</code>)\n"
    "or choose an option below."
)

MSG_ASK_SALARY = (
    "<b>Interview - Salary</b>\n\n"
    "What was the offered salary/salary range?\n"
    "(e.g.: <code>45000-55000</code> or <code>3500/month</code>)\n\n"
    "Send <b>skip</b> to omit."
)

MSG_ASK_CURRENCY = (
    "<b>Interview - Currency</b>\n\n"
    "Which currency? (e.g.: BRL, EUR, USD, GBP)"
)

MSG_ASK_STAGES = (
    "<b>Interview - Stages</b>\n\n"
    "Describe the process stages.\n"
    "(e.g.: <code>1 HR call, 1 technical, 1 final with manager</code>)"
)

MSG_ASK_RATING = (
    "<b>Interview - Rating</b>\n\n"
    "How do you rate the process? (1-5)\n"
    "1 = Terrible, 5 = Excellent"
)

MSG_ASK_EXPERIENCE = (
    "<b>Interview - Experience</b>\n\n"
    "Describe how the experience was.\n"
    "(free text, tips for other candidates)"
)

MSG_HISTORY_EMPTY = "No voted jobs yet. Search and vote on jobs first!"

MSG_HISTORY_HEADER = "<b>\U0001f4cb Your voted jobs</b> (page {page}/{total_pages})\n"


def _build_history_item(item: dict, index: int) -> str:
    vote_icon = "\U0001f44d" if item["vote"] == "up" else "\U0001f44e"
    title = item.get("title", "N/A")
    company = item.get("company", "N/A")
    stage = item.get("stage", "")
    result = item.get("result", "")
    stage_text = ""
    if stage:
        label = STAGE_LABELS.get(stage, stage)
        if stage == "closed" and result:
            label += f" ({result})"
        stage_text = f" | {label}"
    url = item.get("url", "")
    link = f' | <a href="{url}">Link</a>' if url else ""
    return f"{index}. {vote_icon} <b>{title}</b>\n   {company}{stage_text}{link}"


def _build_history_keyboard(items: list[dict], page: int, total_pages: int) -> list[list[dict]]:
    buttons = []
    for item in items:
        job_id = item["job_id"]
        stage = item.get("stage", "")
        if stage:
            label = STAGE_LABELS.get(stage, stage)
            btn_text = f"\u270f\ufe0f {label}"
        else:
            btn_text = "\U0001f4cc Track"
        buttons.append([{"text": btn_text, "callback_data": f"appstage:{job_id}"}])
    nav = []
    if page > 1:
        nav.append({"text": "\u25c0\ufe0f Previous", "callback_data": f"histpage:{page - 1}"})
    if page < total_pages:
        nav.append({"text": "Next \u25b6\ufe0f", "callback_data": f"histpage:{page + 1}"})
    if nav:
        buttons.append(nav)
    buttons.append([{"text": "\u274c Close", "callback_data": "close_history"}])
    return buttons


async def _show_history(token: str, chat_id: str, page: int = 1) -> None:
    total = count_user_votes(chat_id)
    if total == 0:
        await send_message(token, chat_id, MSG_HISTORY_EMPTY)
        return
    total_pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    skip = (page - 1) * HISTORY_PAGE_SIZE
    items = get_voted_jobs_with_details(chat_id, skip=skip, limit=HISTORY_PAGE_SIZE)
    if not items:
        await send_message(token, chat_id, MSG_HISTORY_EMPTY)
        return
    text = MSG_HISTORY_HEADER.format(page=page, total_pages=total_pages) + "\n"
    for i, item in enumerate(items, start=skip + 1):
        text += _build_history_item(item, i) + "\n\n"
    keyboard = _build_history_keyboard(items, page, total_pages)
    await send_inline_keyboard(token, chat_id, text, keyboard)


async def _show_stage_picker(token: str, chat_id: str, job_id: str) -> None:
    app = get_application(chat_id, job_id)
    current_stage = app.get("stage", "") if app else ""
    current_result = app.get("result", "") if app else ""
    job = get_job_by_id(job_id)
    title = job.get("title", "N/A") if job else "N/A"
    text = f"<b>Track application</b>\n{title}\n\nSelect current stage:"
    buttons = []
    for stage in APPLICATION_STAGES:
        if stage == "closed":
            check_approved = "\u2705 " if (current_stage == "closed" and current_result == "approved") else ""
            check_rejected = "\u2705 " if (current_stage == "closed" and current_result == "rejected") else ""
            buttons.append([
                {"text": f"{check_approved}\u2705 Approved", "callback_data": f"setapp:{job_id}:closed:approved"},
                {"text": f"{check_rejected}\u274c Rejected", "callback_data": f"setapp:{job_id}:closed:rejected"},
            ])
        else:
            check = "\u2705 " if current_stage == stage else ""
            label = STAGE_LABELS[stage]
            buttons.append([{"text": f"{check}{label}", "callback_data": f"setapp:{job_id}:{stage}:"}])
    if current_stage:
        buttons.append([{"text": "\U0001f5d1 Remove tracking", "callback_data": f"rmapp:{job_id}"}])
    buttons.append([{"text": "\u25c0\ufe0f Back to history", "callback_data": "histpage:1"}])
    await send_inline_keyboard(token, chat_id, text, buttons)


def _get_state(chat_id: str) -> dict:
    if chat_id not in STATES:
        STATES[chat_id] = {
            "phase": "idle",
            "cv_text": "",
            "terms": [],
            "countries": set(),
            "current_job_id": "",
            "user_name": "",
            "phone": "",
            "api_key": "",
            "model": "",
            "remote_only": False,
            "interview_step": "",
            "interview_data": {},
            "_return_phase": "",
        }
        user = get_user(chat_id)
        if user:
            s = STATES[chat_id]
            s["cv_text"] = user.get("cv_text", "")
            s["phone"] = user.get("phone", "")
            s["api_key"] = user.get("api_key", "")
            s["model"] = user.get("model", "")
            s["terms"] = user.get("terms", [])
            s["user_name"] = user.get("user_name", "")
    return STATES[chat_id]


def _normalize_phone(phone: str) -> str:
    return phone.replace(" ", "").replace("-", "")


def _is_whitelisted(phone: str, config: MariJobsConfig) -> bool:
    normalized = _normalize_phone(phone)
    return normalized in [_normalize_phone(p) for p in config.openrouter.whitelisted_phones]


def _get_api_key(state: dict, config: MariJobsConfig) -> str:
    if _is_whitelisted(state.get("phone", ""), config):
        return os.environ.get(config.openrouter.api_key_env, "")
    return state.get("api_key", "")


def _build_country_keyboard(config: MariJobsConfig, selected: set, remote_only: bool = False) -> list[list[dict]]:
    buttons = []
    row = []
    for opt in config.jobspy.country_options:
        check = "\u2705 " if opt.value in selected else ""
        row.append({
            "text": f"{check}{opt.label}",
            "callback_data": f"toggle:{opt.value}",
        })
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    remote_check = "\u2705 " if remote_only else ""
    buttons.append([{"text": f"{remote_check}Remote", "callback_data": "toggle_remote"}])
    buttons.append([
        {"text": "\u25c0\ufe0f Back", "callback_data": "back"},
        {"text": "\U0001f50d Search", "callback_data": "search"},
    ])
    return buttons


def _build_profile_keyboard() -> list[list[dict]]:
    return [
        [{"text": "\U0001f50d Search with this profile", "callback_data": "use_profile"}],
        [{"text": "\u270f\ufe0f Change terms", "callback_data": "change_terms"}],
        [{"text": "\U0001f195 New profile from scratch", "callback_data": "new_profile"}],
    ]


async def _resume_after_edit(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    ret = state.get("_return_phase", "")
    state["_return_phase"] = ""

    if ret in ("viewing_job", "waiting_feedback") and has_active_queue(chat_id):
        await send_message(token, chat_id, "Resuming pending jobs...")
        await _show_next_job(token, chat_id, config)
    elif ret == "has_profile":
        state["phase"] = "has_profile"
        terms_str = ", ".join(state["terms"]) if state["terms"] else "—"
        await send_inline_keyboard(
            token, chat_id,
            MSG_PROFILE_FOUND.format(terms=terms_str),
            _build_profile_keyboard(),
        )
    else:
        state["phase"] = "idle"
        await send_message(token, chat_id, "Use /start to continue.")


async def _edit_api_key(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    if _is_whitelisted(state.get("phone", ""), config):
        await send_message(
            token, chat_id,
            "Your number uses the shared key. It's not possible to change the API key.",
        )
        return

    state["_return_phase"] = state["phase"]
    state["phase"] = "editing_api_key"
    current_key = state.get("api_key", "")
    if current_key:
        masked = current_key[:4] + "..." + current_key[-4:] if len(current_key) > 8 else "****"
        status = f"<code>{masked}</code>"
    else:
        status = "no API key (AI disabled)"
    text = MSG_EDIT_API_KEY.format(status=status)
    keyboard = []
    if current_key:
        keyboard.append([{"text": "\U0001f5d1 Remove API key (no AI)", "callback_data": "remove_api_key"}])
    keyboard.append([{"text": "\u274c Cancel", "callback_data": "cancel_edit"}])
    await send_inline_keyboard(token, chat_id, text, keyboard)


async def _edit_model(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    api_key = _get_api_key(state, config)
    if not api_key:
        await send_message(token, chat_id, "Activate AI first with /apikey.")
        return

    state["_return_phase"] = state["phase"]
    state["phase"] = "editing_model"
    current = state.get("model") or config.openrouter.model
    default = config.openrouter.model
    text = MSG_EDIT_MODEL.format(model=current)
    keyboard = [
        [{"text": f"\u2705 Keep {current}", "callback_data": "keep_model"}],
    ]
    if current != default:
        keyboard.append([{"text": f"\U0001f504 Reset to {default}", "callback_data": "reset_model"}])
    keyboard.append([{"text": "\u274c Cancel", "callback_data": "cancel_edit"}])
    await send_inline_keyboard(token, chat_id, text, keyboard)


async def _send_greeting(token: str, chat_id: str) -> None:
    await send_message(token, chat_id, MSG_GREETING)


async def _handle_start(token: str, chat_id: str, config: MariJobsConfig, user_name: str) -> None:
    state = _get_state(chat_id)
    state["user_name"] = user_name

    user = get_user(chat_id)
    if user and user.get("cv_text") and user.get("terms"):
        state["cv_text"] = user["cv_text"]
        state["terms"] = user["terms"]
        state["phone"] = user.get("phone", "")
        state["api_key"] = user.get("api_key", "")
        state["model"] = user.get("model", "")

        if has_active_queue(chat_id):
            await send_message(
                token, chat_id,
                "You have pending jobs. Continuing from where you left off...",
            )
            await _show_next_job(token, chat_id, config)
            return

        state["phase"] = "has_profile"
        terms_str = ", ".join(user["terms"])
        await send_inline_keyboard(
            token, chat_id,
            MSG_PROFILE_FOUND.format(terms=terms_str),
            _build_profile_keyboard(),
        )
    else:
        if user and user.get("phone"):
            state["phone"] = user["phone"]
            state["api_key"] = user.get("api_key", "")
            state["model"] = user.get("model", "")
            await _ask_cv(token, chat_id)
        else:
            await _ask_phone(token, chat_id)


async def _ask_phone(token: str, chat_id: str) -> None:
    state = _get_state(chat_id)
    state["phase"] = "waiting_phone"
    await request_contact(token, chat_id, MSG_ASK_PHONE)


async def _ask_api_key(token: str, chat_id: str) -> None:
    state = _get_state(chat_id)
    state["phase"] = "waiting_api_key"
    keyboard = [[{"text": "\u23ed Skip (no AI)", "callback_data": "skip_api_key"}]]
    await send_inline_keyboard(token, chat_id, MSG_ASK_API_KEY, keyboard)


async def _ask_model(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    state["phase"] = "waiting_model"
    current = state.get("model") or config.openrouter.model
    text = MSG_ASK_MODEL.format(model=current)
    keyboard = [[{"text": f"\u2705 Use {current}", "callback_data": "use_default_model"}]]
    await send_inline_keyboard(token, chat_id, text, keyboard)


async def _ask_cv(token: str, chat_id: str) -> None:
    state = _get_state(chat_id)
    state["phase"] = "waiting_cv"
    await send_message(token, chat_id, MSG_ASK_CV)


async def _ask_terms(token: str, chat_id: str) -> None:
    state = _get_state(chat_id)
    state["phase"] = "waiting_terms"
    state["terms"] = []
    state["countries"] = set()
    await send_message(token, chat_id, MSG_ASK_TERMS)


async def _show_country_picker(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    state["phase"] = "picking_countries"
    state["countries"] = set()
    state["remote_only"] = False
    terms_str = ", ".join(state["terms"])
    text = MSG_PICK_COUNTRIES.format(terms=terms_str)
    keyboard = _build_country_keyboard(config, state["countries"], state["remote_only"])
    await send_inline_keyboard(token, chat_id, text, keyboard)


async def _go_back(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    phase = state["phase"]

    if phase in ("editing_api_key", "editing_model"):
        ret = state.get("_return_phase", "idle")
        state["phase"] = ret
        state["_return_phase"] = ""
        await send_message(token, chat_id, "Edit cancelled.")
        return
    if phase == "waiting_cv":
        if not _is_whitelisted(state.get("phone", ""), config):
            await _ask_model(token, chat_id, config)
        else:
            await _ask_phone(token, chat_id)
    elif phase == "waiting_model":
        await _ask_api_key(token, chat_id)
    elif phase == "waiting_terms":
        await _ask_cv(token, chat_id)
    elif phase == "picking_countries":
        await _ask_terms(token, chat_id)
    elif phase == "waiting_api_key":
        await _ask_phone(token, chat_id)
    else:
        await send_message(token, chat_id, "You're already at the beginning. Use /start.")


async def _send_status(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    user = get_user(chat_id)

    has_cv = "\u2705" if (user and user.get("cv_text")) else "\u274c"
    terms_str = ", ".join(user["terms"]) if (user and user.get("terms")) else "\u2014"
    phone = user.get("phone", "\u2014") if user else "\u2014"
    whitelisted = "\u2705" if (phone != "\u2014" and _is_whitelisted(phone, config)) else ""
    has_key = "\u2705" if (user and user.get("api_key")) or whitelisted else "\u274c"
    queue_info = ""
    if has_active_queue(chat_id):
        q = get_queue(chat_id)
        if q:
            remaining = len(q.get("job_ids", [])) - q.get("current_index", 0)
            queue_info = f"\nPending jobs: {remaining}"

    model_str = user.get("model", "") if user else ""
    if not model_str:
        model_str = f"{config.openrouter.model} (default)"

    text = (
        f"<b>Your profile</b>\n\n"
        f"Phone: {phone} {whitelisted}\n"
        f"CV: {has_cv}\n"
        f"Terms: {terms_str}\n"
        f"API Key: {has_key}\n"
        f"Model: <code>{model_str}</code>\n"
        f"Status: {state['phase']}"
        f"{queue_info}"
    )
    await send_message(token, chat_id, text)


def _search_jobspy(config: MariJobsConfig, terms: list[str], countries: list[str], remote_only: bool = False) -> list[dict]:
    return run_search(config, terms, countries, delay=config.app.scrape_delay, remote_only=remote_only)


def _search_euraxess_source(config: MariJobsConfig, terms: list[str], countries: list[str]) -> list[dict]:
    all_jobs = []
    delay = config.app.scrape_delay
    for term in terms:
        for country in countries:
            jobs = search_euraxess(term, country=country, max_results=config.jobspy.results_per_term, delay=delay)
            all_jobs.extend(jobs)
    return all_jobs


def _search_ibec_source(config: MariJobsConfig, terms: list[str]) -> list[dict]:
    all_jobs = []
    delay = config.app.scrape_delay
    for term in terms:
        jobs = search_ibec(term, max_results=20, delay=delay)
        all_jobs.extend(jobs)
    return all_jobs


async def _run_next_phase(token: str, chat_id: str, config: MariJobsConfig) -> bool:
    state = _get_state(chat_id)
    if not _is_whitelisted(state.get("phone", ""), config):
        return False

    queue = get_queue(chat_id)
    if not queue:
        return False

    phase = queue.get("search_phase", 3)
    terms = queue.get("terms", [])
    countries = queue.get("countries", [])
    loop = asyncio.get_running_loop()

    if phase == 1:
        set_searching(chat_id, True)
        await send_message(token, chat_id, "\U0001f50d Searching Euraxess...")
        raw = await loop.run_in_executor(
            None, lambda: _search_euraxess_source(config, terms, countries),
        )
        logger.info(f"Euraxess phase: {len(raw)} results")
        new_ids = save_jobs_batch(raw, chat_id=chat_id)
        voted = get_voted_job_ids(chat_id)
        added = extend_queue(chat_id, [i for i in new_ids if i and i not in voted])
        set_search_phase(chat_id, 2)
        set_searching(chat_id, False)
        if added:
            await send_message(token, chat_id, f"<b>+{added}</b> jobs from Euraxess.")
            return True
        return await _run_next_phase(token, chat_id, config)

    if phase == 2:
        set_searching(chat_id, True)
        await send_message(token, chat_id, "\U0001f50d Searching IBEC...")
        raw = await loop.run_in_executor(
            None, lambda: _search_ibec_source(config, terms),
        )
        logger.info(f"IBEC phase: {len(raw)} results")
        new_ids = save_jobs_batch(raw, chat_id=chat_id)
        voted = get_voted_job_ids(chat_id)
        added = extend_queue(chat_id, [i for i in new_ids if i and i not in voted])
        set_search_phase(chat_id, 3)
        set_searching(chat_id, False)
        if added:
            await send_message(token, chat_id, f"<b>+{added}</b> jobs from IBEC.")
            return True
        return False

    return False


async def _show_next_job(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    queue = get_queue(chat_id)

    if not queue:
        state["phase"] = "idle"
        return

    api_key = _get_api_key(state, config)
    cv_text = state["cv_text"]
    total = len(queue.get("job_ids", []))
    skipped = 0

    while queue["current_index"] < total:
        idx = queue["current_index"]
        job_id = queue["job_ids"][idx]

        job = get_job_by_id(job_id)
        if not job:
            advance_queue(chat_id)
            queue = get_queue(chat_id)
            total = len(queue.get("job_ids", []))
            continue

        if api_key and config.openrouter.enabled:
            cached = get_cached_review(chat_id, job_id)
            if cached and cached.get("score"):
                job["review_score"] = cached["score"]
                job["review_verdict"] = cached["verdict"]
                job["review_reason"] = cached["reason"]
                job["recruiter_message"] = cached.get("recruiter_message", "")
            else:
                await send_message(token, chat_id, "\u23f3 Analyzing job with AI...")
                user_model = state.get("model", "")
                result = await review_job(config.openrouter, cv_text, job, api_key=api_key, model=user_model)
                job["review_score"] = result["score"]
                job["review_verdict"] = result["verdict"]
                job["review_reason"] = result["reason"]
                job["recruiter_message"] = result["recruiter_message"]
                save_review(chat_id, job_id, result["score"], result["verdict"], result["reason"],
                            result["recruiter_message"])

            min_score = config.openrouter.min_relevance_score
            if job.get("review_score", 0) < min_score:
                skipped += 1
                url = job.get("url", "")
                link = f'\n<a href="{url}">View anyway</a>' if url else ""
                await send_message(
                    token, chat_id,
                    f"\u274c Discarded — not relevant to your profile.{link}",
                )
                advance_queue(chat_id)
                queue = get_queue(chat_id)
                total = len(queue.get("job_ids", []))
                continue

        state["current_job_id"] = job_id
        state["phase"] = "viewing_job"
        vote_summary = get_vote_summary(job_id)
        interview_summary = get_interview_summary(job_id)
        text = build_single_job_card(job, idx + 1, total, vote_summary=vote_summary, interview_summary=interview_summary)
        keyboard = build_vote_keyboard(job_id)
        await send_inline_keyboard(token, chat_id, text, keyboard)
        return

    has_more = await _run_next_phase(token, chat_id, config)
    if has_more:
        await _show_next_job(token, chat_id, config)
        return

    mark_queue_completed(chat_id)
    state["phase"] = "queue_empty"
    state["current_job_id"] = ""
    msg = "<b>All jobs have been evaluated!</b>"
    if skipped:
        msg += f"\n({skipped} jobs discarded due to low relevance)"
    msg += "\n\nYou can start a new search."
    await send_inline_keyboard(
        token, chat_id, msg,
        [[{"text": "\U0001f504 New search", "callback_data": "new_search"}]],
    )


async def _run_and_reply(token: str, chat_id: str, config: MariJobsConfig) -> None:
    state = _get_state(chat_id)
    terms = state["terms"]
    countries = sorted(state["countries"])
    remote_only = state.get("remote_only", False)

    if check_is_searching(chat_id):
        await send_message(token, chat_id, "Search already in progress. Please wait...")
        return

    terms_str = ", ".join(terms)
    countries_str = ", ".join(countries)

    whitelisted = _is_whitelisted(state.get("phone", ""), config)
    cached_jobs = find_jobs_by_terms(chat_id, terms, max_age_hours=config.app.db_cache_hours)

    phase_label = "Phase 1/3" if whitelisted else "Sources"
    await send_message(
        token, chat_id,
        f"\U0001f50d Searching <b>{terms_str}</b> in <b>{countries_str}</b>...\n"
        f"{phase_label}: JobSpy (LinkedIn, Indeed, Glassdoor, Google)",
    )

    create_queue(chat_id, [], terms, countries, search_phase=0)
    set_searching(chat_id, True)

    loop = asyncio.get_running_loop()
    try:
        raw_jobs = await loop.run_in_executor(
            None, lambda: _search_jobspy(config, terms, countries, remote_only=remote_only),
        )
        logger.info(f"JobSpy phase: {len(raw_jobs)} results")
    except Exception as e:
        logger.error(f"JobSpy search error: {e}")
        raw_jobs = []

    raw_ids = save_jobs_batch(raw_jobs, chat_id=chat_id)
    save_search(chat_id, terms, countries, len(raw_jobs))

    voted = get_voted_job_ids(chat_id)
    all_job_ids = []
    seen_ids = set()

    for job in cached_jobs:
        jid = str(job["_id"])
        if jid not in seen_ids and jid not in voted:
            all_job_ids.append(jid)
            seen_ids.add(jid)

    for jid in raw_ids:
        if jid and jid not in seen_ids and jid not in voted:
            all_job_ids.append(jid)
            seen_ids.add(jid)

    delete_queue(chat_id)
    create_queue(chat_id, all_job_ids, terms, countries, search_phase=1)

    if not all_job_ids:
        if whitelisted:
            await send_message(token, chat_id, "No jobs on JobSpy. Searching next sources...")
            has_more = await _run_next_phase(token, chat_id, config)
            if has_more:
                await _show_next_job(token, chat_id, config)
                return
        mark_queue_completed(chat_id)
        state["phase"] = "queue_empty"
        await send_inline_keyboard(
            token, chat_id,
            "<b>No jobs found.</b>\n\nYou can start a new search.",
            [[{"text": "\U0001f504 New search", "callback_data": "new_search"}]],
        )
        return

    extra = ""
    if whitelisted:
        extra = "\n(Euraxess and IBEC will be searched when these run out)"
    await send_message(
        token, chat_id,
        f"<b>{len(all_job_ids)}</b> jobs from JobSpy. Showing one at a time...{extra}",
    )

    await _show_next_job(token, chat_id, config)


async def poll_updates(config: MariJobsConfig) -> None:
    token = get_token(config.telegram.bot_token_env)
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set, bot disabled")
        return

    base_url = f"https://api.telegram.org/bot{token}"
    offset = 0

    logger.info("Telegram bot polling started")

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            try:
                resp = await client.get(
                    f"{base_url}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"getUpdates error: {data}")
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    await _process_update(config, token, update)

            except httpx.TimeoutException:
                continue
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                await asyncio.sleep(5)


async def _process_update(config: MariJobsConfig, token: str, update: dict) -> None:
    if "message" in update:
        msg = update["message"]
        chat_id = str(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()
        user = msg.get("from", {})
        user_name = user.get("first_name", "")
        state = _get_state(chat_id)
        set_user_context(chat_id, state.get("user_name", "") or user_name)

        if text == "/start":
            await _send_greeting(token, chat_id)
            await _handle_start(token, chat_id, config, user_name)
            return

        if text == "/new":
            if has_active_queue(chat_id):
                delete_queue(chat_id)
            await _send_greeting(token, chat_id)
            await _ask_phone(token, chat_id)
            return

        if text == "/back":
            await _go_back(token, chat_id, config)
            return

        if text == "/status":
            await _send_status(token, chat_id, config)
            return

        if text == "/history":
            await _show_history(token, chat_id)
            return

        if text == "/terms":
            db_user = get_user(chat_id)
            if db_user and db_user.get("cv_text"):
                state["cv_text"] = db_user["cv_text"]
                state["phone"] = db_user.get("phone", "")
                state["api_key"] = db_user.get("api_key", "")
                state["model"] = db_user.get("model", "")
                state["user_name"] = user_name
                if has_active_queue(chat_id):
                    delete_queue(chat_id)
                await _ask_terms(token, chat_id)
            else:
                await send_message(token, chat_id, "No CV saved. Use /start first.")
            return

        if text == "/cv":
            await _ask_cv(token, chat_id)
            return

        if text == "/apikey":
            await _edit_api_key(token, chat_id, config)
            return

        if text == "/model":
            await _edit_model(token, chat_id, config)
            return

        if text == "/interview":
            job_id = state.get("current_job_id", "")
            if not job_id:
                await send_message(token, chat_id, "No job selected. Evaluate a job first.")
                return
            if has_user_interview(chat_id, job_id):
                await send_message(token, chat_id, "You have already registered an interview for this job.")
                return
            state["_return_phase"] = state["phase"]
            state["phase"] = "logging_interview"
            state["interview_step"] = "salary"
            state["interview_data"] = {"job_id": job_id}
            await send_message(token, chat_id, MSG_ASK_SALARY)
            return

        if text == "/skip":
            if has_active_queue(chat_id):
                delete_queue(chat_id)
                state["phase"] = "idle"
                await send_message(token, chat_id, "Job queue discarded. Use /start for a new search.")
            else:
                await send_message(token, chat_id, "No active queue.")
            return

        contact = msg.get("contact")
        if contact and state["phase"] == "waiting_phone":
            phone = _normalize_phone(contact.get("phone_number", ""))
            if not phone.startswith("+"):
                phone = f"+{phone}"
            state["phone"] = phone
            state["user_name"] = user_name
            save_user(chat_id, phone=phone, user_name=user_name)
            await remove_keyboard(token, chat_id, f"\u2705 Contact received: {phone}")
            logger.info(f"Phone received: {phone}")

            if _is_whitelisted(phone, config):
                await send_message(token, chat_id, "\u2705 Number recognized! AI enabled automatically.")
                await _ask_cv(token, chat_id)
            else:
                await _ask_api_key(token, chat_id)
            return

        if state["phase"] == "waiting_phone":
            if text and (text.startswith("+") or text.replace(" ", "").replace("-", "").isdigit()):
                phone = _normalize_phone(text)
                if not phone.startswith("+"):
                    phone = f"+{phone}"
                if len(phone) < 8:
                    await send_message(token, chat_id, "Invalid number. Send with country code (e.g.: <code>+351912345678</code>).")
                    return
                state["phone"] = phone
                state["user_name"] = user_name
                save_user(chat_id, phone=phone, user_name=user_name)
                await remove_keyboard(token, chat_id, f"\u2705 Contact received: {phone}")
                logger.info(f"Phone received (manual): {phone}")
                if _is_whitelisted(phone, config):
                    await send_message(token, chat_id, "\u2705 Number recognized! AI enabled automatically.")
                    await _ask_cv(token, chat_id)
                else:
                    await _ask_api_key(token, chat_id)
            else:
                await send_message(
                    token, chat_id,
                    "Tap the <b>Share contact</b> button (in place of the keyboard)\n"
                    "or send the number manually (e.g.: <code>+351912345678</code>).",
                )

        elif state["phase"] == "waiting_api_key":
            if text:
                state["api_key"] = text.strip()
                save_user(chat_id, api_key=text.strip())
                await send_message(token, chat_id, "\u2705 API key saved!")
                await _ask_model(token, chat_id, config)
            else:
                await send_message(token, chat_id, "Send your OpenRouter API key.")

        elif state["phase"] == "waiting_model":
            if text:
                state["model"] = text.strip()
                save_user(chat_id, model=text.strip())
                await send_message(token, chat_id, f"\u2705 Model saved: <code>{text.strip()}</code>")
                await _ask_cv(token, chat_id)
            else:
                await send_message(token, chat_id, "Send the model name or use the button.")

        elif state["phase"] == "waiting_cv":
            doc = msg.get("document")
            if doc:
                file_name = doc.get("file_name", "")
                mime = doc.get("mime_type", "")
                if not (file_name.lower().endswith(".pdf") or mime == "application/pdf"):
                    await send_message(token, chat_id, "Send only <b>PDF</b> files.")
                    return
                file_id = doc["file_id"]
                with tempfile.NamedTemporaryFile(suffix=f"_{file_name}", delete=False) as tmp:
                    tmp_path = tmp.name

                ok = await download_file(token, file_id, tmp_path)
                if ok:
                    cv_text = extract_cv_text(tmp_path)
                    if cv_text:
                        state["cv_text"] = cv_text
                        save_user(chat_id, cv_text=cv_text, user_name=user_name)
                        logger.info(f"CV saved: {len(cv_text)} chars")
                        await send_message(token, chat_id, "\u2705 CV received and saved!")
                        await _ask_terms(token, chat_id)
                    else:
                        await send_message(token, chat_id, "Couldn't read the PDF. File corrupted or empty?")
                else:
                    await send_message(token, chat_id, "Error downloading the file. Try again.")
            else:
                await send_message(token, chat_id, "Send your CV as a <b>PDF</b> file.")

        elif state["phase"] == "waiting_terms":
            if text:
                terms = [t.strip() for t in text.split(",") if t.strip()]
                if not terms:
                    await send_message(token, chat_id, "Send at least one search term.")
                    return
                state["terms"] = terms
                save_user(chat_id, terms=terms)
                await send_message(token, chat_id, f"\u2705 Terms saved: <b>{', '.join(terms)}</b>")
                await _show_country_picker(token, chat_id, config)
            else:
                await send_message(token, chat_id, "Send search terms separated by comma.")

        elif state["phase"] == "editing_api_key":
            if text:
                state["api_key"] = text.strip()
                save_user(chat_id, api_key=text.strip())
                await send_message(token, chat_id, "\u2705 API key saved!")
                if not state.get("model"):
                    await _edit_model(token, chat_id, config)
                else:
                    await _resume_after_edit(token, chat_id, config)
            else:
                await send_message(token, chat_id, "Send the new OpenRouter API key.")

        elif state["phase"] == "editing_model":
            if text:
                state["model"] = text.strip()
                save_user(chat_id, model=text.strip())
                await send_message(token, chat_id, f"\u2705 Model saved: <code>{text.strip()}</code>")
                await _resume_after_edit(token, chat_id, config)
            else:
                await send_message(token, chat_id, "Send the model name or use the buttons.")

        elif state["phase"] == "waiting_feedback":
            if text:
                job_id = state.get("current_job_id", "")
                save_feedback(chat_id, job_id, text)
                await send_message(token, chat_id, "\u2705 Feedback saved! Showing next job...")
                await _show_next_job(token, chat_id, config)
            else:
                await send_message(token, chat_id, "Write your feedback or tap Continue.")

        elif state["phase"] == "logging_interview":
            step = state.get("interview_step", "")
            idata = state.get("interview_data", {})

            if step == "salary":
                idata["salary"] = text if text.lower() != "skip" else ""
                if idata["salary"]:
                    state["interview_step"] = "currency"
                    await send_message(token, chat_id, MSG_ASK_CURRENCY)
                else:
                    idata["currency"] = ""
                    state["interview_step"] = "stages"
                    await send_message(token, chat_id, MSG_ASK_STAGES)

            elif step == "currency":
                idata["currency"] = text.upper().strip()[:3] if text else "EUR"
                state["interview_step"] = "stages"
                await send_message(token, chat_id, MSG_ASK_STAGES)

            elif step == "stages":
                idata["stages"] = text or ""
                state["interview_step"] = "rating"
                await send_inline_keyboard(
                    token, chat_id, MSG_ASK_RATING,
                    [[
                        {"text": "1", "callback_data": "interview_rating:1"},
                        {"text": "2", "callback_data": "interview_rating:2"},
                        {"text": "3", "callback_data": "interview_rating:3"},
                        {"text": "4", "callback_data": "interview_rating:4"},
                        {"text": "5", "callback_data": "interview_rating:5"},
                    ]],
                )

            elif step == "experience":
                idata["experience"] = text or ""
                save_interview(
                    chat_id, idata["job_id"],
                    idata.get("salary", ""), idata.get("currency", ""),
                    idata.get("stages", ""), idata.get("rating", 3),
                    idata.get("experience", ""),
                )
                state["interview_step"] = ""
                state["interview_data"] = {}
                ret = state.get("_return_phase", "")
                state["_return_phase"] = ""
                await send_message(token, chat_id, "\u2705 Interview registered! Thank you for helping other candidates.")
                if ret in ("viewing_job", "waiting_feedback") and has_active_queue(chat_id):
                    await _show_next_job(token, chat_id, config)
                else:
                    state["phase"] = ret or "idle"
                    await send_message(token, chat_id, "Use /start to continue.")

            else:
                await send_message(token, chat_id, "Error in interview flow. Use /start.")
                state["phase"] = "idle"

        elif state["phase"] == "idle":
            await _send_greeting(token, chat_id)

        else:
            await send_message(token, chat_id, "Use /start to begin or /back to go back.")

    elif "callback_query" in update:
        cb = update["callback_query"]
        callback_id = cb["id"]
        chat_id = str(cb["message"]["chat"]["id"])
        message_id = cb["message"]["message_id"]
        data = cb.get("data", "")
        state = _get_state(chat_id)
        cb_user = cb.get("from", {})
        if not state.get("user_name") and cb_user.get("first_name"):
            state["user_name"] = cb_user["first_name"]
        set_user_context(chat_id, state.get("user_name", ""))

        if data == "use_profile":
            await answer_callback(token, callback_id)
            if has_active_queue(chat_id):
                await send_message(token, chat_id, "Continuing pending jobs...")
                await _show_next_job(token, chat_id, config)
            else:
                await _show_country_picker(token, chat_id, config)

        elif data == "change_terms":
            await answer_callback(token, callback_id)
            if has_active_queue(chat_id):
                delete_queue(chat_id)
            await _ask_terms(token, chat_id)

        elif data == "new_profile":
            await answer_callback(token, callback_id)
            if has_active_queue(chat_id):
                delete_queue(chat_id)
            await _ask_phone(token, chat_id)

        elif data.startswith("toggle:"):
            country = data.split(":", 1)[1]
            if country in state["countries"]:
                state["countries"].discard(country)
            else:
                state["countries"].add(country)
            keyboard = _build_country_keyboard(config, state["countries"], state.get("remote_only", False))
            await edit_message_reply_markup(token, chat_id, message_id, keyboard)
            await answer_callback(token, callback_id)

        elif data == "toggle_remote":
            state["remote_only"] = not state.get("remote_only", False)
            keyboard = _build_country_keyboard(config, state["countries"], state["remote_only"])
            await edit_message_reply_markup(token, chat_id, message_id, keyboard)
            await answer_callback(token, callback_id)

        elif data == "back":
            await answer_callback(token, callback_id)
            await _ask_terms(token, chat_id)

        elif data == "search":
            if not state["countries"]:
                await answer_callback(token, callback_id, "Select at least one country!")
                return
            if check_is_searching(chat_id):
                await answer_callback(token, callback_id, "Search in progress!")
                return
            if has_active_queue(chat_id):
                await answer_callback(token, callback_id, "You still have jobs to evaluate!")
                await send_message(
                    token, chat_id,
                    "You still have pending jobs. Evaluate all before starting a new search.\n"
                    "Use /skip to discard the queue.",
                )
                await _show_next_job(token, chat_id, config)
                return
            await answer_callback(token, callback_id, "Starting search...")
            state["phase"] = "searching"
            await _run_and_reply(token, chat_id, config)

        elif data.startswith("vote:"):
            parts = data.split(":")
            vote_type = parts[1]
            vote_job_id = parts[2] if len(parts) > 2 else state.get("current_job_id", "")
            await answer_callback(token, callback_id)

            if vote_type in ("up", "down"):
                if vote_job_id:
                    save_vote(chat_id, vote_job_id, vote_type)
                    state["current_job_id"] = vote_job_id
                advance_queue(chat_id)
                state["phase"] = "waiting_feedback"
                feedback_buttons = [
                    [{"text": "\u25b6\ufe0f Continue", "callback_data": "continue_queue"}],
                ]
                if vote_type == "up" and vote_job_id:
                    feedback_buttons.append(
                        [{"text": "\U0001f4dd Log interview", "callback_data": f"start_interview:{vote_job_id}"}],
                    )
                    feedback_buttons.append(
                        [{"text": "\U0001f4cc Track application", "callback_data": f"appstage:{vote_job_id}"}],
                    )
                await send_inline_keyboard(
                    token, chat_id,
                    "Want to adjust something in the search? Write your suggestion\n"
                    "or tap <b>Continue</b> for the next job.",
                    feedback_buttons,
                )

            elif vote_type == "skip":
                advance_queue(chat_id)
                await _show_next_job(token, chat_id, config)

        elif data == "continue_queue":
            await answer_callback(token, callback_id)
            await _show_next_job(token, chat_id, config)

        elif data == "skip_api_key":
            await answer_callback(token, callback_id)
            state["api_key"] = ""
            state["model"] = ""
            await send_message(token, chat_id, "\u2705 AI disabled. Jobs will be shown with description.")
            await _ask_cv(token, chat_id)

        elif data == "use_default_model":
            await answer_callback(token, callback_id)
            current = state.get("model") or config.openrouter.model
            state["model"] = current
            save_user(chat_id, model=current)
            await send_message(token, chat_id, f"\u2705 Model: <code>{current}</code>")
            await _ask_cv(token, chat_id)

        elif data == "remove_api_key":
            await answer_callback(token, callback_id)
            state["api_key"] = ""
            state["model"] = ""
            save_user(chat_id, api_key="", model="")
            await send_message(token, chat_id, "\u2705 API key removed. AI disabled.")
            await _resume_after_edit(token, chat_id, config)

        elif data == "keep_model":
            await answer_callback(token, callback_id)
            await send_message(token, chat_id, "\u2705 Model kept.")
            await _resume_after_edit(token, chat_id, config)

        elif data == "reset_model":
            await answer_callback(token, callback_id)
            default = config.openrouter.model
            state["model"] = default
            save_user(chat_id, model=default)
            await send_message(token, chat_id, f"\u2705 Model reset to: <code>{default}</code>")
            await _resume_after_edit(token, chat_id, config)

        elif data == "cancel_edit":
            await answer_callback(token, callback_id)
            ret = state.get("_return_phase", "idle")
            state["phase"] = ret
            state["_return_phase"] = ""
            await send_message(token, chat_id, "Edit cancelled.")

        elif data == "new_search":
            await answer_callback(token, callback_id)
            delete_queue(chat_id)
            await _show_country_picker(token, chat_id, config)

        elif data.startswith("start_interview"):
            await answer_callback(token, callback_id)
            parts = data.split(":")
            job_id = parts[1] if len(parts) > 1 else state.get("current_job_id", "")
            if not job_id:
                await send_message(token, chat_id, "Error: job not found.")
                return
            if has_user_interview(chat_id, job_id):
                await send_message(token, chat_id, "You have already registered an interview for this job.")
                await _show_next_job(token, chat_id, config)
                return
            state["_return_phase"] = state["phase"]
            state["phase"] = "logging_interview"
            state["interview_step"] = "salary"
            state["interview_data"] = {"job_id": job_id}
            await send_message(token, chat_id, MSG_ASK_SALARY)

        elif data.startswith("interview_rating:"):
            rating = int(data.split(":")[1])
            await answer_callback(token, callback_id)
            idata = state.get("interview_data", {})
            idata["rating"] = rating
            state["interview_step"] = "experience"
            await send_message(token, chat_id, MSG_ASK_EXPERIENCE)

        elif data.startswith("histpage:"):
            page = int(data.split(":")[1])
            await answer_callback(token, callback_id)
            await _show_history(token, chat_id, page=page)

        elif data.startswith("appstage:"):
            job_id = data.split(":")[1]
            await answer_callback(token, callback_id)
            await _show_stage_picker(token, chat_id, job_id)

        elif data.startswith("setapp:"):
            parts = data.split(":")
            job_id = parts[1]
            stage = parts[2]
            result = parts[3] if len(parts) > 3 else ""
            save_application(chat_id, job_id, stage, result)
            await answer_callback(token, callback_id, f"Saved: {STAGE_LABELS.get(stage, stage)}")
            await _show_stage_picker(token, chat_id, job_id)

        elif data.startswith("rmapp:"):
            job_id = data.split(":")[1]
            delete_application(chat_id, job_id)
            await answer_callback(token, callback_id, "Tracking removed")
            await _show_history(token, chat_id, page=1)

        elif data == "close_history":
            await answer_callback(token, callback_id)
            await send_message(token, chat_id, "History closed.")

        elif data == "noop":
            await answer_callback(token, callback_id)
