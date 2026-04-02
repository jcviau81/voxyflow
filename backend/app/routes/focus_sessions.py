"""Focus session tracking and analytics endpoints."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, FocusSession, Card, Project, new_uuid

router = APIRouter(tags=["focus-sessions"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class FocusSessionCreate(BaseModel):
    card_id: str | None = None
    project_id: str | None = None
    duration_minutes: int
    completed: bool
    started_at: str  # ISO datetime string
    ended_at: str    # ISO datetime string


class FocusSessionResponse(BaseModel):
    id: str
    card_id: str | None
    project_id: str | None
    duration_minutes: int
    completed: bool
    started_at: str
    ended_at: str


class CardFocusStat(BaseModel):
    card_id: str
    title: str
    sessions: int
    minutes: int


class DayFocusStat(BaseModel):
    date: str
    sessions: int
    minutes: int


class FocusAnalyticsResponse(BaseModel):
    total_sessions: int
    total_minutes: int
    completed_sessions: int
    avg_session_minutes: float
    by_card: list[CardFocusStat]
    by_day: list[DayFocusStat]


# ---------------------------------------------------------------------------
# POST /api/focus-sessions — log a session
# ---------------------------------------------------------------------------

@router.post("/focus-sessions", response_model=FocusSessionResponse, status_code=201)
async def create_focus_session(
    body: FocusSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Log a completed or interrupted Pomodoro focus session."""
    if body.duration_minutes < 0:
        raise HTTPException(400, "duration_minutes must be >= 0.")

    # Validate FK references if provided
    if body.card_id:
        card = await db.get(Card, body.card_id)
        if not card:
            raise HTTPException(404, f"Card {body.card_id!r} not found")

    if body.project_id:
        project = await db.get(Project, body.project_id)
        if not project:
            raise HTTPException(404, f"Project {body.project_id!r} not found")

    try:
        started_at = datetime.fromisoformat(body.started_at.replace("Z", "+00:00"))
        ended_at = datetime.fromisoformat(body.ended_at.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(400, f"Invalid datetime format: {e}")

    session = FocusSession(
        id=new_uuid(),
        card_id=body.card_id,
        project_id=body.project_id,
        duration_minutes=body.duration_minutes,
        completed=body.completed,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return FocusSessionResponse(
        id=session.id,
        card_id=session.card_id,
        project_id=session.project_id,
        duration_minutes=session.duration_minutes,
        completed=session.completed,
        started_at=session.started_at.isoformat(),
        ended_at=session.ended_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/focus — analytics
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/focus", response_model=FocusAnalyticsResponse)
async def get_project_focus_analytics(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return focus session analytics for a project (all time for totals, last 7 days for by_day)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found.")

    # Fetch all sessions for this project
    stmt = select(FocusSession).where(FocusSession.project_id == project_id)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    total_sessions = len(sessions)
    total_minutes = sum(s.duration_minutes for s in sessions)
    completed_sessions = sum(1 for s in sessions if s.completed)
    avg_session_minutes = round(total_minutes / total_sessions, 1) if total_sessions > 0 else 0.0

    # --- by_card: aggregate per card ---
    card_stats: dict[str, dict] = {}
    for s in sessions:
        if s.card_id:
            if s.card_id not in card_stats:
                card_stats[s.card_id] = {"sessions": 0, "minutes": 0, "title": "Unknown"}
            card_stats[s.card_id]["sessions"] += 1
            card_stats[s.card_id]["minutes"] += s.duration_minutes

    # Fetch card titles
    if card_stats:
        card_ids = list(card_stats.keys())
        card_stmt = select(Card).where(Card.id.in_(card_ids))
        card_result = await db.execute(card_stmt)
        for card in card_result.scalars().all():
            if card.id in card_stats:
                card_stats[card.id]["title"] = card.title

    by_card = [
        CardFocusStat(
            card_id=card_id,
            title=data["title"],
            sessions=data["sessions"],
            minutes=data["minutes"],
        )
        for card_id, data in sorted(card_stats.items(), key=lambda x: x[1]["minutes"], reverse=True)
    ]

    # --- by_day: last 7 days ---
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_day: list[DayFocusStat] = []

    for i in range(6, -1, -1):  # 6 days ago → today
        day_start = today - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        day_sessions = [
            s for s in sessions
            if day_start <= _ensure_tz(s.ended_at) < day_end
        ]
        by_day.append(DayFocusStat(
            date=day_start.strftime("%Y-%m-%d"),
            sessions=len(day_sessions),
            minutes=sum(s.duration_minutes for s in day_sessions),
        ))

    return FocusAnalyticsResponse(
        total_sessions=total_sessions,
        total_minutes=total_minutes,
        completed_sessions=completed_sessions,
        avg_session_minutes=avg_session_minutes,
        by_card=by_card,
        by_day=by_day,
    )


def _ensure_tz(dt: datetime) -> datetime:
    """Make datetime timezone-aware (UTC) if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
