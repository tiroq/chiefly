"""
Telegram webhook route for receiving updates from Telegram Bot API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from apps.api.logging import get_logger

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = get_logger(__name__)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    """
    Receive Telegram webhook updates.
    The bot dispatcher handles these updates.
    """
    dp = getattr(request.app.state, "dispatcher", None)
    bot = getattr(request.app.state, "bot", None)
    if dp is None or bot is None:
        logger.warning("telegram_webhook_called_but_bot_not_configured")
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": "Bot not configured"},
        )

    try:
        body = await request.json()
        from aiogram.types import Update

        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error("telegram_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
