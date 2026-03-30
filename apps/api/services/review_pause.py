from __future__ import annotations

_review_paused = False


def is_review_paused() -> bool:
    return _review_paused


def toggle_review_pause() -> bool:
    global _review_paused
    _review_paused = not _review_paused
    return _review_paused


def set_review_paused(paused: bool) -> None:
    global _review_paused
    _review_paused = paused
