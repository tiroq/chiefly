from __future__ import annotations

from dataclasses import dataclass, field

from db.models.task_item import TaskItem
from db.models.task_revision import TaskRevision
from db.models.system_event import SystemEvent
from db.models.project import Project
from db.models.project_alias import ProjectAlias
from db.models.project_prompt_version import ProjectPromptVersion


@dataclass
class TaskListResult:
    items: list[TaskItem] = field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 25
    total_pages: int = 1


@dataclass
class TaskDetailResult:
    task: TaskItem | None = None
    revisions: list[TaskRevision] = field(default_factory=list)


@dataclass
class EventListResult:
    """Result container for paginated event list."""

    items: list[SystemEvent] = field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50
    total_pages: int = 1


@dataclass
class DashboardStats:
    total_tasks: int = 0
    tasks_by_status: dict[str, int] = field(default_factory=dict)
    tasks_today: int = 0
    active_projects: int = 0
    recent_events: list[SystemEvent] = field(default_factory=list)
    error_count_24h: int = 0
    tasks_by_kind: dict[str, int] = field(default_factory=dict)


@dataclass
class ProjectWithStats:
    project: Project | None = None
    task_count: int = 0
    alias_count: int = 0
    active_prompt_version: ProjectPromptVersion | None = None


@dataclass
class ProjectListResult:
    items: list[ProjectWithStats] = field(default_factory=list)
    total: int = 0


@dataclass
class ProjectDetailResult:
    project: Project | None = None
    task_count: int = 0
    aliases: list[ProjectAlias] = field(default_factory=list)
