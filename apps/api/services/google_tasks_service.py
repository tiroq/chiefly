"""
Google Tasks service abstraction.

Encapsulates Google Tasks API client details and provides a clean interface
for the rest of the application.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from apps.api.logging import get_logger
from core.domain.exceptions import GoogleTasksError

logger = get_logger(__name__)


@dataclass
class GoogleTask:
    id: str
    title: str
    notes: str | None
    status: str
    tasklist_id: str
    due: str | None = None
    updated: str | None = None
    raw_payload: dict | None = None


class GoogleTasksService:
    def __init__(self, credentials_file: str) -> None:
        self._credentials_file = credentials_file
        self._service = None

    def _get_service(self):
        if self._service is None:
            import json

            from googleapiclient.discovery import build

            if not os.path.exists(self._credentials_file):
                raise GoogleTasksError(f"Credentials file not found: {self._credentials_file}")

            with open(self._credentials_file) as f:
                cred_data = json.load(f)

            if cred_data.get("type") == "service_account":
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_file,
                    scopes=["https://www.googleapis.com/auth/tasks"],
                )
            else:
                # OAuth2 user token (produced by auth_tasks.py)
                from google.auth.transport.requests import Request
                from google.oauth2.credentials import Credentials

                credentials = Credentials.from_authorized_user_file(
                    self._credentials_file,
                    scopes=["https://www.googleapis.com/auth/tasks"],
                )
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                    # Persist refreshed token
                    with open(self._credentials_file, "w") as f:
                        f.write(credentials.to_json())

            self._service = build("tasks", "v1", credentials=credentials)
        return self._service

    def list_tasklists(self) -> list[dict]:
        try:
            items = []
            page_token = None
            while True:
                kwargs: dict = dict(maxResults=100)
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._get_service().tasklists().list(**kwargs).execute()
                items.extend(result.get("items", []))
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return items
        except Exception as e:
            raise GoogleTasksError(f"Failed to list tasklists: {e}") from e

    def list_tasks(self, tasklist_id: str) -> list[GoogleTask]:
        try:
            tasks = []
            page_token = None
            while True:
                kwargs: dict = dict(
                    tasklist=tasklist_id,
                    showCompleted=False,
                    showHidden=False,
                    maxResults=100,
                )
                if page_token:
                    kwargs["pageToken"] = page_token
                result = self._get_service().tasks().list(**kwargs).execute()
                for item in result.get("items", []):
                    if item.get("status") == "completed":
                        continue
                    tasks.append(
                        GoogleTask(
                            id=item["id"],
                            title=item.get("title", "").strip(),
                            notes=item.get("notes"),
                            status=item.get("status", "needsAction"),
                            tasklist_id=tasklist_id,
                            due=item.get("due"),
                            updated=item.get("updated"),
                            raw_payload=item,
                        )
                    )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return tasks
        except GoogleTasksError:
            raise
        except Exception as e:
            raise GoogleTasksError(f"Failed to list tasks for {tasklist_id}: {e}") from e

    def get_task(self, tasklist_id: str, task_id: str) -> GoogleTask | None:
        try:
            item = self._get_service().tasks().get(tasklist=tasklist_id, task=task_id).execute()
            return GoogleTask(
                id=item["id"],
                title=item.get("title", "").strip(),
                notes=item.get("notes"),
                status=item.get("status", "needsAction"),
                tasklist_id=tasklist_id,
                due=item.get("due"),
                updated=item.get("updated"),
                raw_payload=item,
            )
        except Exception as e:
            logger.warning("get_task failed", task_id=task_id, error=str(e))
            return None

    def patch_task(
        self,
        tasklist_id: str,
        task_id: str,
        title: str | None = None,
        notes: str | None = None,
        due: str | None = None,
    ) -> GoogleTask:
        body: dict = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        try:
            item = (
                self._get_service()
                .tasks()
                .patch(tasklist=tasklist_id, task=task_id, body=body)
                .execute()
            )
            return GoogleTask(
                id=item["id"],
                title=item.get("title", "").strip(),
                notes=item.get("notes"),
                status=item.get("status", "needsAction"),
                tasklist_id=tasklist_id,
                due=item.get("due"),
                updated=item.get("updated"),
            )
        except Exception as e:
            raise GoogleTasksError(f"Failed to patch task {task_id}: {e}") from e

    def move_task(
        self, source_tasklist_id: str, task_id: str, destination_tasklist_id: str
    ) -> GoogleTask:
        """
        Move a task from one tasklist to another by inserting a copy and
        deleting the original.
        """
        try:
            original = self.get_task(source_tasklist_id, task_id)
            if original is None:
                raise GoogleTasksError(f"Task {task_id} not found in {source_tasklist_id}")

            new_task_body: dict = {"title": original.title}
            if original.notes:
                new_task_body["notes"] = original.notes
            if original.due:
                new_task_body["due"] = original.due

            created = (
                self._get_service()
                .tasks()
                .insert(tasklist=destination_tasklist_id, body=new_task_body)
                .execute()
            )

            # Delete from source
            self._get_service().tasks().delete(tasklist=source_tasklist_id, task=task_id).execute()

            return GoogleTask(
                id=created["id"],
                title=created.get("title", "").strip(),
                notes=created.get("notes"),
                status=created.get("status", "needsAction"),
                tasklist_id=destination_tasklist_id,
                due=created.get("due"),
                updated=created.get("updated"),
            )
        except GoogleTasksError:
            raise
        except Exception as e:
            raise GoogleTasksError(
                f"Failed to move task {task_id} to {destination_tasklist_id}: {e}"
            ) from e

    def complete_task(self, tasklist_id: str, task_id: str) -> None:
        try:
            self._get_service().tasks().patch(
                tasklist=tasklist_id, task=task_id, body={"status": "completed"}
            ).execute()
        except Exception as e:
            raise GoogleTasksError(f"Failed to complete task {task_id}: {e}") from e
