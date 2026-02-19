import logging

_user_context: dict[str, str] = {}

_setup_done = False


def set_user_context(chat_id: str, name: str = "") -> None:
    _user_context["chat_id"] = chat_id
    _user_context["name"] = name


def clear_user_context() -> None:
    _user_context.pop("chat_id", None)
    _user_context.pop("name", None)


class _ContextFormatter(logging.Formatter):
    def format(self, record):
        cid = _user_context.get("chat_id", "")
        name = _user_context.get("name", "")
        if cid:
            tag = f"[{name}|{cid}]" if name else f"[{cid}]"
            record.msg = f"{tag} {record.msg}"
        return super().format(record)


def setup_logging() -> logging.Logger:
    global _setup_done
    if not _setup_done:
        handler = logging.StreamHandler()
        handler.setFormatter(_ContextFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        _setup_done = True
    return logging.getLogger("marijobs")
