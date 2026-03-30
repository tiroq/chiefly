from __future__ import annotations

from aiogram import Dispatcher

from apps.api.telegram.callbacks import callback_router
from apps.api.telegram.commands import command_router
from apps.api.telegram.messages import message_router


def register_all_routers(dp: Dispatcher) -> None:
    dp.include_router(command_router)
    dp.include_router(callback_router)
    dp.include_router(message_router)
