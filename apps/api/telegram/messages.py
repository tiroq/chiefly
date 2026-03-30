from __future__ import annotations

import html as html_mod

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from apps.api.config import get_settings
from apps.api.logging import get_logger
from apps.api.services.telegram_service import TelegramService, _build_proposal_text
from apps.api.telegram.keyboards import proposal_keyboard
from apps.api.telegram.states import ReviewStates
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult
from db.repositories.review_session_repo import ReviewSessionRepository
from db.repositories.task_snapshot_repo import TaskSnapshotRepository
from db.session import get_session_factory

logger = get_logger(__name__)

message_router = Router(name="messages")


@message_router.message(ReviewStates.awaiting_title_edit, F.text)
async def handle_title_edit(message: Message, state: FSMContext):
    new_title = (message.text or "").strip()
    if not new_title:
        await message.answer("Title cannot be empty. Please send the new title:")
        return

    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await state.clear()
        return

    factory = get_session_factory()
    settings = get_settings()

    async with factory() as session:
        from core.utils.ids import parse_uuid

        session_repo = ReviewSessionRepository(session)
        stable_id = parse_uuid(task_id)
        review_session = await session_repo.get_active_by_stable_id(stable_id)

        if review_session is None:
            await message.answer("Review session expired.")
            await state.clear()
            return

        proposed = dict(review_session.proposed_changes or {})
        proposed["normalized_title"] = new_title[:500]
        review_session.proposed_changes = proposed
        review_session.status = "pending"
        await session_repo.save(review_session)
        await session.commit()

        kind = TaskKind(proposed.get("kind", "task"))
        confidence = ConfidenceBand(proposed.get("confidence", "medium"))

        classification = TaskClassificationResult(
            kind=kind,
            normalized_title=proposed.get("normalized_title", ""),
            confidence=confidence,
            next_action=proposed.get("next_action"),
            due_hint=proposed.get("due_hint"),
            substeps=proposed.get("substeps", []),
            ambiguities=proposed.get("ambiguities", []),
        )

        raw_text = ""
        if review_session.stable_id:
            snapshot_repo = TaskSnapshotRepository(session)
            snapshot = await snapshot_repo.get_latest_by_stable_id(review_session.stable_id)
            if snapshot and snapshot.payload:
                raw_text = snapshot.payload.get("title", "")
        if not raw_text:
            raw_text = classification.normalized_title

        text = _build_proposal_text(raw_text, classification, proposed.get("project_name"))
        short_id = (
            str(review_session.stable_id).replace("-", "")
            if review_session.stable_id
            else str(review_session.id).replace("-", "")
        )
        keyboard = proposal_keyboard(short_id)

        tg = TelegramService(settings.telegram_bot_token, settings.telegram_chat_id)
        try:
            if review_session.telegram_message_id:
                await tg.edit_message_text(
                    review_session.telegram_message_id, text, reply_markup=keyboard
                )
            safe_title = html_mod.escape(new_title)
            await message.answer(f"✅ Title updated to: <i>{safe_title}</i>")
        finally:
            await tg.aclose()

    await state.clear()
