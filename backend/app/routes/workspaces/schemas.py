"""Pydantic schemas shared by the workspace route submodules."""

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateResponse(BaseModel):
    id: str
    name: str
    emoji: str
    description: str
    color: str
    cards: list[dict[str, Any]]


class CreateFromTemplateRequest(BaseModel):
    title: str
    description: str = ""
    emoji: str | None = None
    color: str | None = None


class CreateFromTemplateResponse(BaseModel):
    workspace_id: str
    workspace_title: str
    cards_imported: int
    template_emoji: str
    template_color: str


# ---------------------------------------------------------------------------
# Export/Import schemas
# ---------------------------------------------------------------------------

class ChecklistItemExport(BaseModel):
    text: str
    completed: bool
    position: int


class TimeEntryExport(BaseModel):
    duration_minutes: int
    note: str | None = None
    logged_at: str


class RelationExport(BaseModel):
    target_card_id: str   # original card ID — used for cross-referencing on import
    relation_type: str


class CardExport(BaseModel):
    id: str  # original card ID — used to resolve relations/dependencies on import
    title: str
    description: str
    status: str
    priority: int
    position: int = 0
    color: str | None = None
    agent_type: str | None = None
    agent_context: str | None = None
    assignee: str | None = None
    watchers: str = ""
    files: list[str] = []
    tags: list[str] = []
    dependency_ids: list[str] = []
    checklist_items: list[ChecklistItemExport] = []
    time_entries: list[TimeEntryExport] = []
    relations: list[RelationExport] = []


class WorkspaceExport(BaseModel):
    title: str
    description: str
    status: str
    context: str
    github_repo: str | None = None
    github_url: str | None = None
    github_branch: str | None = None
    github_language: str | None = None
    local_path: str | None = None


class WikiPageExport(BaseModel):
    title: str
    content: str


class ExportPayload(BaseModel):
    version: str
    exported_at: str
    workspace: WorkspaceExport
    cards: list[CardExport]
    # TODO: wiki pages are intentionally excluded from export v1.0 to keep
    # the payload size manageable and avoid orphaned page references across
    # workspace boundaries.  Bump version to "2.0" and add `wiki` field when
    # wiki export/import is implemented.
    # wiki: list[WikiPageExport] = []


class ImportResponse(BaseModel):
    workspace_id: str
    workspace_title: str
    cards_imported: int


# ---------------------------------------------------------------------------
# Autonomy — per-workspace heartbeat
# ---------------------------------------------------------------------------

class AutonomyUpsertBody(BaseModel):
    enabled: bool = True
    schedule: str | None = None  # e.g. "every_5min", "every_15min", cron expr
    directive: str | None = None  # content written below the "---" divider


# ---------------------------------------------------------------------------
# AI Meeting Notes Extractor
# ---------------------------------------------------------------------------

class MeetingNotesRequest(BaseModel):
    notes: str
    workspace_id: str | None = None  # optional, for context (unused in extraction but accepted)


class MeetingCardPreview(BaseModel):
    title: str
    description: str
    priority: int
    agent_type: str


class MeetingNotesResponse(BaseModel):
    cards: list[MeetingCardPreview]
    summary: str


class MeetingConfirmRequest(BaseModel):
    cards: list[MeetingCardPreview]


class MeetingConfirmResponse(BaseModel):
    created: int
    card_ids: list[str]


# ---------------------------------------------------------------------------
# AI Workspace Brief Generator
# ---------------------------------------------------------------------------

class BriefResponse(BaseModel):
    brief: str
    generated_at: str


# ---------------------------------------------------------------------------
# Workspace Health Check
# ---------------------------------------------------------------------------

class HealthIssue(BaseModel):
    severity: str  # "critical" | "warning" | "info"
    message: str


class HealthResponse(BaseModel):
    score: int
    grade: str  # "A" | "B" | "C" | "D" | "F"
    summary: str
    strengths: list[str]
    issues: list[HealthIssue]
    recommendations: list[str]
    generated_at: str


# ---------------------------------------------------------------------------
# Daily Standup
# ---------------------------------------------------------------------------

class StandupResponse(BaseModel):
    summary: str
    generated_at: str


class StandupScheduleRequest(BaseModel):
    enabled: bool = True
    hour: int = Field(default=9, ge=0, le=23)    # 09:00 local time
    minute: int = Field(default=0, ge=0, le=59)


class StandupScheduleResponse(BaseModel):
    job_id: str
    workspace_id: str
    schedule: str
    enabled: bool


# ---------------------------------------------------------------------------
# Workspace Wiki
# ---------------------------------------------------------------------------

class WikiPageSummary(BaseModel):
    id: str
    title: str
    updated_at: str


class WikiPageDetail(BaseModel):
    id: str
    workspace_id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class WikiPageCreate(BaseModel):
    title: str = "Untitled Page"
    content: str = ""


class WikiPageUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


# ---------------------------------------------------------------------------
# Smart Card Prioritization
# ---------------------------------------------------------------------------

class PriorizedCard(BaseModel):
    card_id: str
    title: str
    score: float
    reasoning: str


class PrioritizeResponse(BaseModel):
    ordered_cards: list[PriorizedCard]
    summary: str
