"""
Google Calendar service stub.
Placeholder for future calendar integration.
"""

from __future__ import annotations


class GoogleCalendarService:
    def __init__(self, credentials_file: str) -> None:
        self._credentials_file = credentials_file

    def list_upcoming_events(self, calendar_id: str = "primary", max_results: int = 10) -> list[dict]:
        raise NotImplementedError("Google Calendar integration not yet implemented")
