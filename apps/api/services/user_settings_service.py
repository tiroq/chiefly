from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.app_setting_repo import AppSettingRepository

_SETTINGS_KEY = "user_settings"

_DEFAULTS: dict[str, bool | int] = {
    "auto_next": True,
    "batch_size": 1,
    "paused": False,
    "sync_summary": True,
    "daily_brief": True,
    "show_confidence": True,
    "show_raw_input": True,
    "draft_suggestions": True,
    "ambiguity_prompts": True,
    "show_steps_auto": False,
    "changes_only": False,
}

BOOL_SETTINGS = {
    "auto_next",
    "paused",
    "sync_summary",
    "daily_brief",
    "show_confidence",
    "show_raw_input",
    "draft_suggestions",
    "ambiguity_prompts",
    "show_steps_auto",
    "changes_only",
}

INT_SETTINGS = {"batch_size"}
BATCH_SIZE_OPTIONS = [1, 5, 10]


async def get_user_settings(session: AsyncSession) -> dict[str, bool | int]:
    repo = AppSettingRepository(session)
    raw = await repo.get(_SETTINGS_KEY, "")
    if not raw:
        return dict(_DEFAULTS)
    try:
        stored = json.loads(raw)
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in stored.items() if k in _DEFAULTS})
        return merged
    except (json.JSONDecodeError, TypeError):
        return dict(_DEFAULTS)


async def save_user_settings(session: AsyncSession, settings: dict[str, bool | int]) -> None:
    repo = AppSettingRepository(session)
    await repo.set(_SETTINGS_KEY, json.dumps(settings))
    await session.flush()


async def toggle_bool_setting(session: AsyncSession, key: str) -> dict[str, bool | int]:
    settings = await get_user_settings(session)
    if key in BOOL_SETTINGS:
        settings[key] = not settings[key]
    await save_user_settings(session, settings)
    return settings


async def cycle_batch_size(session: AsyncSession) -> dict[str, bool | int]:
    settings = await get_user_settings(session)
    current = settings.get("batch_size", 1)
    try:
        idx = BATCH_SIZE_OPTIONS.index(current)
        settings["batch_size"] = BATCH_SIZE_OPTIONS[(idx + 1) % len(BATCH_SIZE_OPTIONS)]
    except ValueError:
        settings["batch_size"] = BATCH_SIZE_OPTIONS[0]
    await save_user_settings(session, settings)
    return settings
