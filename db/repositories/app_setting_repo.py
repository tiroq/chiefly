from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.app_setting import AppSetting


class AppSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str, default: str = "") -> str:
        result = await self._session.execute(select(AppSetting.value).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        return row if row is not None else default

    async def set(self, key: str, value: str) -> None:
        result = await self._session.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = AppSetting(key=key, value=value)
            self._session.add(setting)
        else:
            setting.value = value
        await self._session.flush()
