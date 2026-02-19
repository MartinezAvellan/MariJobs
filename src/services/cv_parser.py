import logging
from pathlib import Path

from pypdf import PdfReader

from src.core.utils import setup_logging

logging.getLogger("pypdf").setLevel(logging.ERROR)
logger = setup_logging()


def extract_cv_text(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip()
        else:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception as e:
        logger.error(f"CV parse error for {file_path}: {e}")
        return ""
