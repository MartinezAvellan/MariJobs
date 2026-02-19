import os

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet:
        return _fernet
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        return None
    _fernet = Fernet(key.encode())
    return _fernet


def encrypt_value(plain: str) -> str:
    f = _get_fernet()
    if not f or not plain:
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_value(token: str) -> str:
    f = _get_fernet()
    if not f or not token:
        return token
    try:
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return token
