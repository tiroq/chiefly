from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

from apps.api.config import get_settings
from apps.api.logging import get_logger

logger = get_logger(__name__)

AUTH_DATE_MAX_AGE_SECONDS = 3600


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, str]:
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash in init data")

    auth_date_str = parsed.get("auth_date", "")
    if not auth_date_str:
        raise HTTPException(status_code=401, detail="Missing auth_date")

    try:
        auth_date = int(auth_date_str)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid auth_date") from exc

    if time.time() - auth_date > AUTH_DATE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Init data expired")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        logger.warning("miniapp_auth_invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    return parsed


async def verify_miniapp_auth(request: Request) -> dict[str, str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("tma "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    init_data = auth_header[4:]
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")

    return _validate_init_data(init_data, settings.telegram_bot_token)
