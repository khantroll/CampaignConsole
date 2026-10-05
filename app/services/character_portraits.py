"""Safe local storage helpers for PlayerCharacterNote portraits."""

from pathlib import Path
import secrets
from typing import Optional

from fastapi import UploadFile

PORTRAIT_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "character_portraits"
PORTRAIT_URL_PREFIX = "/static/uploads/character_portraits/"
MAX_PORTRAIT_BYTES = 5 * 1024 * 1024

_IMAGE_SIGNATURES = (
    ("png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ("jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ("webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
)


def _detected_extension(data: bytes) -> Optional[str]:
    for extension, predicate in _IMAGE_SIGNATURES:
        if predicate(data):
            return extension
    return None


def _path_for_url(portrait_path: Optional[str]) -> Optional[Path]:
    if not portrait_path or not portrait_path.startswith(PORTRAIT_URL_PREFIX):
        return None
    filename = portrait_path[len(PORTRAIT_URL_PREFIX):]
    if not filename or "/" in filename or "\\" in filename:
        return None
    return PORTRAIT_DIR / filename


def delete_portrait_file(portrait_path: Optional[str]) -> None:
    target = _path_for_url(portrait_path)
    if not target:
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


async def save_portrait_upload(upload: UploadFile, previous_path: Optional[str] = None) -> str:
    data = await upload.read(MAX_PORTRAIT_BYTES + 1)
    if not data:
        raise ValueError("Choose an image file to upload.")
    if len(data) > MAX_PORTRAIT_BYTES:
        raise ValueError("Portrait must be 5 MB or smaller.")

    extension = _detected_extension(data)
    if not extension:
        raise ValueError("Portrait must be a PNG, JPEG, or WebP image.")

    PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_urlsafe(18)}.{extension}"
    target = PORTRAIT_DIR / filename
    target.write_bytes(data)

    delete_portrait_file(previous_path)
    return f"{PORTRAIT_URL_PREFIX}{filename}"
