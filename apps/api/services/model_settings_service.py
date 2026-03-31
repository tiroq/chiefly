from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import Settings
from db.repositories.app_setting_repo import AppSettingRepository

_SETTINGS_KEY = "model_settings"

_DEFAULTS: dict[str, str | bool] = {
    "provider": "",
    "model": "",
    "api_key": "",
    "base_url": "",
    "fast_model": "",
    "quality_model": "",
    "fallback_model": "",
    "auto_mode": False,
}

SUPPORTED_PROVIDERS = ("openai", "ollama", "github_models")


def get_auth_status(db_settings: dict[str, str | bool], env_settings: Settings) -> dict[str, str]:
    db_key = str(db_settings.get("api_key", ""))
    env_key = env_settings.llm_api_key

    if db_key:
        return {"source": "database", "configured": "true", "masked_key": f"••••{db_key[-4:]}"}
    if env_key:
        return {"source": "environment", "configured": "true", "masked_key": f"••••{env_key[-4:]}"}
    return {"source": "none", "configured": "false", "masked_key": ""}


@dataclass(frozen=True)
class EffectiveLLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    fast_model: str
    quality_model: str
    fallback_model: str
    auto_mode: bool


async def get_model_settings(session: AsyncSession) -> dict[str, str | bool]:
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


async def _get_raw_stored_keys(session: AsyncSession) -> set[str]:
    """Return the set of keys explicitly stored in DB JSON blob."""
    repo = AppSettingRepository(session)
    raw = await repo.get(_SETTINGS_KEY, "")
    if not raw:
        return set()
    try:
        stored = json.loads(raw)
        return set(stored.keys()) & set(_DEFAULTS.keys())
    except (json.JSONDecodeError, TypeError):
        return set()


async def save_model_settings(session: AsyncSession, settings: dict[str, str | bool]) -> None:
    repo = AppSettingRepository(session)
    await repo.set(_SETTINGS_KEY, json.dumps(settings))
    await session.flush()


async def reset_model_settings(session: AsyncSession) -> None:
    repo = AppSettingRepository(session)
    await repo.set(_SETTINGS_KEY, "")
    await session.flush()


async def get_effective_llm_config(
    session: AsyncSession,
    env_settings: Settings,
) -> EffectiveLLMConfig:
    db = await get_model_settings(session)
    stored_keys = await _get_raw_stored_keys(session)

    if "auto_mode" in stored_keys:
        auto_mode = bool(db["auto_mode"])
    else:
        auto_mode = env_settings.llm_auto_mode

    return EffectiveLLMConfig(
        provider=str(db["provider"]) or env_settings.llm_provider,
        model=str(db["model"]) or env_settings.llm_model,
        api_key=str(db["api_key"]) or env_settings.llm_api_key,
        base_url=str(db["base_url"]) or env_settings.llm_base_url,
        fast_model=str(db["fast_model"]) or env_settings.llm_fast_model,
        quality_model=str(db["quality_model"]) or env_settings.llm_quality_model,
        fallback_model=str(db["fallback_model"]) or env_settings.llm_fallback_model,
        auto_mode=auto_mode,
    )
