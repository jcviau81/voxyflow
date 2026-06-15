"""AI-powered workspace features: meeting notes, brief, health, standup,
and smart prioritization.

Two routers so the package ``__init__`` can reproduce the original
registration order — in the original module the wiki routes registered
between the standup endpoints and the prioritize endpoint.

NOTE: the ``from app.services.claude_service import ClaudeService`` imports
are deliberately lazy (inside each handler) to avoid startup import cycles.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import (
    get_db, Workspace, Card, CardRelation,
    new_uuid, utcnow,
)
from app.services.agent_personas import AgentType, get_persona
from app.services.jobs_store import load_jobs, save_jobs
from app.services.ws_broadcast import ws_broadcast

from app.routes.workspaces.insights import _compute_health, _compute_priority_score
from app.routes.workspaces.schemas import (
    BriefResponse,
    HealthResponse,
    MeetingCardPreview,
    MeetingConfirmRequest,
    MeetingConfirmResponse,
    MeetingNotesRequest,
    MeetingNotesResponse,
    PrioritizeResponse,
    PriorizedCard,
    StandupResponse,
    StandupScheduleRequest,
    StandupScheduleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
prioritize_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# AI Meeting Notes Extractor
# ---------------------------------------------------------------------------

@router.post("/{workspace_id}/meeting-notes", response_model=MeetingNotesResponse)
async def extract_meeting_notes(
    workspace_id: str,
    body: MeetingNotesRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract action items from meeting notes using the Fast AI model.
    Returns a preview of cards — user confirms before creation.
    """
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    if not body.notes or not body.notes.strip():
        raise HTTPException(400, "Meeting notes cannot be empty.")

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    data = await svc.generate_meeting_notes(body.notes)

    cards = []
    for item in data.get("cards", []):
        cards.append(
            MeetingCardPreview(
                title=str(item.get("title", "Untitled action"))[:200],
                description=str(item.get("description", ""))[:1000],
                priority=max(0, min(3, int(item.get("priority", 1)))),
                agent_type=str(item.get("agent_type", "general")),
            )
        )

    return MeetingNotesResponse(
        cards=cards,
        summary=str(data.get("summary", ""))[:500],
    )


@router.post("/{workspace_id}/meeting-notes/confirm", response_model=MeetingConfirmResponse, status_code=201)
async def confirm_meeting_notes(
    workspace_id: str,
    body: MeetingConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create cards from confirmed meeting notes extraction.
    """
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    card_ids = []
    for i, card_data in enumerate(body.cards):
        agent_assigned = None
        try:
            persona = get_persona(AgentType(card_data.agent_type))
            agent_assigned = f"{persona.emoji} {persona.name}"
        except (ValueError, KeyError):
            pass

        card = Card(
            id=new_uuid(),
            workspace_id=workspace_id,
            title=card_data.title,
            description=card_data.description,
            status="todo",
            priority=card_data.priority,
            agent_type=card_data.agent_type,
            agent_assigned=agent_assigned,
        )
        db.add(card)
        card_ids.append(card.id)

    workspace.updated_at = utcnow()
    await db.commit()

    # Notify connected clients so the new cards appear without a manual refetch.
    if card_ids:
        ws_broadcast.emit_sync("cards:changed", {"workspaceId": workspace_id, "cardId": None})

    return MeetingConfirmResponse(created=len(card_ids), card_ids=card_ids)


# ---------------------------------------------------------------------------
# AI Workspace Brief Generator
# ---------------------------------------------------------------------------

@router.post("/{workspace_id}/brief", response_model=BriefResponse)
async def generate_brief(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a comprehensive AI workspace brief / PRD using the Deep (Opus) model."""
    # Fetch workspace + cards
    stmt = (
        select(Workspace)
        .options(selectinload(Workspace.cards))
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    cards = workspace.cards

    # Group cards by status
    def card_lines(filtered_cards) -> str:
        if not filtered_cards:
            return "  (none)"
        lines = []
        for c in filtered_cards:
            agent = f" [{c.agent_type}]" if c.agent_type else ""
            priority_map = {0: "low", 1: "medium", 2: "high", 3: "critical"}
            prio = priority_map.get(c.priority or 0, "low")
            desc = f" — {c.description[:120]}" if c.description else ""
            lines.append(f"  - {c.title}{agent} (priority: {prio}){desc}")
        return "\n".join(lines)

    backlog_cards = [c for c in cards if c.status == "backlog"]
    todo_cards    = [c for c in cards if c.status == "todo"]
    inprog_cards  = [c for c in cards if c.status == "in-progress"]
    done_cards    = [c for c in cards if c.status == "done"]

    tech_stack = ""
    if workspace.github_language:
        tech_stack += f"Primary language: {workspace.github_language}. "
    if workspace.github_repo:
        tech_stack += f"Repo: {workspace.github_repo}. "
    if workspace.local_path:
        tech_stack += f"Local path: {workspace.local_path}. "
    if not tech_stack:
        tech_stack = "Not specified — infer from context."

    prompt = (
        f"Generate a professional workspace brief for: **{workspace.title}**\n\n"
        f"Description: {workspace.description or 'No description provided.'}\n\n"
        f"Tech stack: {tech_stack}\n\n"
        f"Cards/Features by status:\n\n"
        f"📦 BACKLOG:\n{card_lines(backlog_cards)}\n\n"
        f"📋 TODO:\n{card_lines(todo_cards)}\n\n"
        f"🔨 IN PROGRESS:\n{card_lines(inprog_cards)}\n\n"
        f"✅ DONE:\n{card_lines(done_cards)}\n\n"
        f"Total cards: {len(cards)} | Done: {len(done_cards)} | "
        f"In Progress: {len(inprog_cards)} | Todo: {len(todo_cards)} | "
        f"Backlog: {len(backlog_cards)}\n\n"
        f"Generate a comprehensive workspace brief with the following sections:\n"
        f"1. Executive Summary (2-3 paragraphs)\n"
        f"2. Problem Statement\n"
        f"3. Goals & Success Metrics\n"
        f"4. Features List (organized from the cards above)\n"
        f"5. Technical Architecture (inferred from tech stack and card context)\n"
        f"6. Timeline Estimate (based on card count and complexity)\n"
        f"7. Risk Assessment\n\n"
        f"Format as clean, professional markdown. Be specific and actionable."
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    brief = await svc.generate_brief(prompt)

    return BriefResponse(
        brief=brief,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Workspace Health Check
# ---------------------------------------------------------------------------

@router.post("/{workspace_id}/health", response_model=HealthResponse)
async def workspace_health_check(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Analyse workspace health and return a score, grade, strengths, issues, and recommendations."""
    from sqlalchemy.orm import selectinload as slo

    stmt = (
        select(Workspace)
        .options(
            slo(Workspace.cards).selectinload(Card.checklist_items),
            slo(Workspace.cards).selectinload(Card.relations_as_target).selectinload(CardRelation.source_card),
        )
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    cards = list(workspace.cards)

    health = _compute_health(workspace, cards)

    # Build AI summary prompt
    meta = health.pop("_meta")
    strengths_text = "\n".join(f"- {s}" for s in health["strengths"]) or "None"
    issues_text = "\n".join(
        f"- [{i.severity.upper()}] {i.message}" for i in health["issues"]
    ) or "None"
    recs_text = "\n".join(f"- {r}" for r in health["recommendations"]) or "None"

    summary_prompt = (
        f"Workspace: {meta['workspace_title']}\n"
        f"Health score: {health['score']}/100 (Grade {health['grade']})\n"
        f"Cards: {meta['total']} total — {meta['inprog']} in-progress, {meta['todo']} todo, "
        f"{meta['done']} done, {meta['backlog']} backlog\n\n"
        f"Strengths:\n{strengths_text}\n\n"
        f"Issues:\n{issues_text}\n\n"
        f"Recommendations:\n{recs_text}\n\n"
        f"Write a concise 2-3 sentence health summary for this workspace."
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    summary = await svc.generate_health_summary(summary_prompt)

    return HealthResponse(
        score=health["score"],
        grade=health["grade"],
        summary=summary,
        strengths=health["strengths"],
        issues=health["issues"],
        recommendations=health["recommendations"],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Daily Standup
# ---------------------------------------------------------------------------

@router.post("/{workspace_id}/standup", response_model=StandupResponse)
async def generate_standup(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a daily standup summary for a workspace using the fast AI model."""
    # Fetch workspace + cards
    stmt = (
        select(Workspace)
        .options(selectinload(Workspace.cards))
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    cards = workspace.cards

    # Categorize cards
    in_progress = [c for c in cards if c.status == "in-progress"]
    done_cards = [c for c in cards if c.status == "done"]
    blocked = [c for c in cards if c.priority == 3]  # critical priority = potential blocker
    todo = [c for c in cards if c.status == "todo"]

    def card_line(c: Card) -> str:
        agent = f" [{c.agent_type}]" if c.agent_type else ""
        return f"- {c.title}{agent}"

    in_progress_text = "\n".join(card_line(c) for c in in_progress) or "None"
    done_text = "\n".join(card_line(c) for c in done_cards) or "None"
    blocked_text = "\n".join(card_line(c) for c in blocked) or "None"
    todo_text = "\n".join(card_line(c) for c in todo[:5]) or "None"  # top 5 upcoming

    prompt = (
        f"Generate a concise daily standup for workspace: **{workspace.title}**\n\n"
        f"Workspace description: {workspace.description or 'N/A'}\n\n"
        f"Cards IN PROGRESS:\n{in_progress_text}\n\n"
        f"Cards DONE:\n{done_text}\n\n"
        f"BLOCKED / Critical priority:\n{blocked_text}\n\n"
        f"Next TODO (upcoming):\n{todo_text}\n\n"
        f"Total cards: {len(cards)} | Done: {len(done_cards)} | In Progress: {len(in_progress)} | Todo: {len(todo)}"
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    summary = await svc.generate_standup(prompt)

    return StandupResponse(
        summary=summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{workspace_id}/standup/schedule", response_model=StandupScheduleResponse | None)
async def get_standup_schedule(workspace_id: str):
    """Get the current standup schedule for a workspace, or null if not configured."""
    jobs = await asyncio.to_thread(load_jobs)
    for job in jobs:
        if (
            job.get("type") == "standup"
            and job.get("payload", {}).get("workspace_id") == workspace_id
        ):
            return StandupScheduleResponse(
                job_id=job["id"],
                workspace_id=workspace_id,
                schedule=job["schedule"],
                enabled=job.get("enabled", True),
            )
    return None


@router.post("/{workspace_id}/standup/schedule", response_model=StandupScheduleResponse, status_code=201)
async def set_standup_schedule(
    workspace_id: str,
    body: StandupScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create or update the daily standup schedule for a workspace."""
    # Verify workspace exists
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    schedule = f"0 {body.minute} {body.hour} * * *"  # cron: daily at HH:MM

    jobs = await asyncio.to_thread(load_jobs)

    # Remove existing standup job for this workspace if any
    jobs = [
        j for j in jobs
        if not (j.get("type") == "standup" and j.get("payload", {}).get("workspace_id") == workspace_id)
    ]

    job_id = str(uuid.uuid4())
    new_job = {
        "id": job_id,
        "name": f"Daily Standup — {workspace.title}",
        "type": "standup",
        "schedule": schedule,
        "enabled": body.enabled,
        "payload": {
            "workspace_id": workspace_id,
            "workspace_name": workspace.title,
            "hour": body.hour,
            "minute": body.minute,
        },
    }
    jobs.append(new_job)
    await asyncio.to_thread(save_jobs, jobs)

    # Sync the live APScheduler — otherwise the new schedule only takes effect
    # after a backend restart (and a replaced job's old trigger keeps firing).
    # Guarded: a missing scheduler API degrades to jobs.json-only persistence.
    try:
        from app.services import scheduler_service as _sched
        _sched.unregister_standup_job(workspace_id)
        if body.enabled:
            _sched.register_standup_job(workspace_id, new_job)
    except Exception as e:
        logger.warning(
            "Standup scheduler sync failed for workspace %s (job persisted to jobs.json): %s",
            workspace_id, e,
        )

    return StandupScheduleResponse(
        job_id=job_id,
        workspace_id=workspace_id,
        schedule=schedule,
        enabled=body.enabled,
    )


# ---------------------------------------------------------------------------
# Smart Card Prioritization
# ---------------------------------------------------------------------------

@prioritize_router.post("/{workspace_id}/prioritize", response_model=PrioritizeResponse)
async def smart_prioritize(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """
    Analyze all non-done cards and return a suggested work order.
    Score is deterministic (rule-based). AI generates brief reasoning for top 3.
    """
    from sqlalchemy.orm import selectinload as slo
    from app.services.claude_service import ClaudeService

    stmt = (
        select(Workspace)
        .options(
            slo(Workspace.cards).selectinload(Card.checklist_items),
            slo(Workspace.cards).selectinload(Card.dependencies),
        )
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    all_cards = list(workspace.cards)

    # Score only non-done cards (done cards have nothing left to prioritize)
    active_cards = [c for c in all_cards if c.status != "done"]

    if not active_cards:
        return PrioritizeResponse(
            ordered_cards=[],
            summary="All cards are done — nothing left to prioritize! 🎉",
        )

    # Compute scores
    scored = [(card, _compute_priority_score(card, all_cards)) for card in active_cards]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Build top-3 AI reasoning prompt
    top3 = scored[:3]
    priority_label = {3: "critical", 2: "high", 1: "medium", 0: "low"}
    status_label = {"in-progress": "in progress", "todo": "todo", "backlog": "backlog"}

    top3_lines = []
    for rank, (card, score) in enumerate(top3, 1):
        votes = card.votes or 0
        checklist = list(card.checklist_items) if hasattr(card, "checklist_items") else []
        checklist_info = ""
        if checklist:
            done = sum(1 for i in checklist if i.completed)
            checklist_info = f", {done}/{len(checklist)} checklist items done"
        line = (
            f"#{rank}: \"{card.title}\" — score {score}/100, "
            f"priority={priority_label.get(card.priority or 0, 'low')}, "
            f"status={status_label.get(card.status, card.status)}, "
            f"votes={votes}{checklist_info}"
        )
        top3_lines.append(line)

    reasoning_prompt = (
        f"Workspace: {workspace.title}\n\n"
        f"Top 3 prioritized cards:\n" + "\n".join(top3_lines) + "\n\n"
        f"For each of the top 3 cards, write ONE short sentence (max 20 words) explaining WHY it should be done first. "
        f"Be specific: mention priority, blocking others, partial progress, or votes. "
        f"Respond ONLY with valid JSON: "
        f'[{{"card_rank": 1, "reasoning": "..."}}, {{"card_rank": 2, "reasoning": "..."}}, {{"card_rank": 3, "reasoning": "..."}}]'
    )

    svc = ClaudeService()
    reasoning_map: dict[int, str] = {}

    try:
        raw = await svc.generate_priority_reasoning(reasoning_prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        for item in parsed:
            reasoning_map[item["card_rank"]] = str(item["reasoning"])[:200]
    except Exception as e:
        logger.warning(f"[Prioritize] AI reasoning failed, using fallback: {e}")
        # Fallback: deterministic reasoning
        for rank, (card, score) in enumerate(top3, 1):
            reasoning_map[rank] = f"Score {score}/100 based on priority, votes, and dependencies."

    # Build response
    ordered = []
    for rank, (card, score) in enumerate(scored, 1):
        reasoning = reasoning_map.get(rank, "")
        ordered.append(PriorizedCard(
            card_id=card.id,
            title=card.title,
            score=score,
            reasoning=reasoning,
        ))

    # Summary
    total = len(scored)
    in_prog = sum(1 for c, _ in scored if c.status == "in-progress")
    top_title = scored[0][0].title if scored else ""
    summary = (
        f"{total} card{'s' if total != 1 else ''} analyzed. "
        f"{in_prog} in progress. "
        f"Top priority: \"{top_title}\"."
    )

    return PrioritizeResponse(ordered_cards=ordered, summary=summary)
