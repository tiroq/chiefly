from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReviewStates(StatesGroup):
    awaiting_title_edit = State()
    awaiting_disambiguation = State()
    draft_preview = State()


class SettingsStates(StatesGroup):
    viewing = State()
    changing_batch_size = State()
