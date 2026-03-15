"""
Telegram webhook route for receiving updates from Telegram Bot API.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from apps.api.logging import get_logger

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = get_logger(__name__)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    """
    Receive Telegram webhook updates.
    The bot dispatcher handles these updates.
    """
    try:
        body = await request.json()
        dp = request.app.state.dispatcher
        bot = request.app.state.bot
        from aiogram.types import Update

        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error("telegram_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
