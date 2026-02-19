import os

import httpx


def get_token(bot_token_env: str) -> str:
    return os.environ.get(bot_token_env, "")


def get_chat_id(chat_id_env: str) -> str:
    return os.environ.get(chat_id_env, "")


async def send_message(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = _split_message(text, 4096)
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })


async def send_inline_keyboard(
    token: str, chat_id: str, text: str, buttons: list[list[dict]],
) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })


async def answer_callback(token: str, callback_id: str, text: str = "") -> None:
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={
            "callback_query_id": callback_id,
            "text": text,
        })


async def edit_message_text(
    token: str, chat_id: str, message_id: int, text: str,
    buttons: list[list[dict]] | None = None,
) -> None:
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons is not None:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json=payload)


async def edit_message_reply_markup(
    token: str, chat_id: str, message_id: int, buttons: list[list[dict]],
) -> None:
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": buttons},
        })


async def request_contact(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "keyboard": [[{"text": "Share Contact", "request_contact": True}]],
                "one_time_keyboard": True,
                "resize_keyboard": True,
            },
        })


async def remove_keyboard(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"remove_keyboard": True},
        })


async def set_my_commands(token: str, commands: list[dict]) -> None:
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={"commands": commands})


async def download_file(token: str, file_id: str, dest_path: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
            )
            data = resp.json()
            if not data.get("ok"):
                return False
            file_path = data["result"]["file_path"]
            file_resp = await client.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}",
            )
            if file_resp.status_code == 200:
                from pathlib import Path
                Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
                Path(dest_path).write_bytes(file_resp.content)
                return True
    except Exception:
        pass
    return False


def _split_message(text: str, max_length: int = 4096) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
