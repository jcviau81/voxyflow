"""Pure scoring/analysis helpers for workspace health and card prioritization.

No FastAPI imports — deterministic, unit-testable business logic called by
``ai_features.py``.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.routes.workspaces.schemas import HealthIssue

if TYPE_CHECKING:  # pragma: no cover
    from app.database import Card, Workspace


def _compute_health(workspace: "Workspace", cards: list["Card"]) -> dict:
    """Rule-based health analysis. Returns raw data dict (no AI summary yet)."""
    now = datetime.now(timezone.utc)
    issues: list[dict] = []
    strengths: list[str] = []
    recommendations: list[str] = []

    total = len(cards)
    backlog_cards = [c for c in cards if c.status == "backlog"]
    todo_cards = [c for c in cards if c.status == "todo"]
    inprog_cards = [c for c in cards if c.status == "in-progress"]
    done_cards = [c for c in cards if c.status == "done"]

    # ── Issue: no cards in-progress ──────────────────────────────────────────
    if total > 0 and len(inprog_cards) == 0:
        issues.append({"severity": "warning", "message": "No cards are currently in progress."})
        recommendations.append("Move at least one card to 'in-progress' to keep momentum going.")
    elif len(inprog_cards) > 0:
        strengths.append(f"{len(inprog_cards)} card(s) actively in progress — work is moving forward.")

    # ── Issue: stale todo cards (no activity > 7 days) ──────────────────────
    stale_count = 0
    seven_days_ago = now.timestamp() - 7 * 86400
    for c in todo_cards:
        updated = c.updated_at
        if updated:
            # Make timezone-aware for comparison
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated.timestamp() < seven_days_ago:
                stale_count += 1
    if stale_count > 0:
        issues.append({
            "severity": "warning",
            "message": f"{stale_count} todo card(s) have had no activity in over 7 days.",
        })
        recommendations.append("Review and prioritize stale todo cards or archive ones no longer relevant.")

    # ── Issue: high ratio of backlog cards ───────────────────────────────────
    if total > 0:
        backlog_ratio = len(backlog_cards) / total
        if backlog_ratio > 0.4:
            issues.append({
                "severity": "info",
                "message": f"{len(backlog_cards)} of {total} cards ({round(backlog_ratio*100)}%) are in the backlog.",
            })
            recommendations.append("Groom your backlog: promote cards to 'todo' or archive low-priority ones.")

    # ── Issue: cards with no description ────────────────────────────────────
    no_desc = [c for c in cards if not (c.description or "").strip()]
    if no_desc:
        issues.append({
            "severity": "info",
            "message": f"{len(no_desc)} card(s) have no description.",
        })
        recommendations.append("Add descriptions to cards so agents and teammates have the context they need.")

    # ── Issue: cards with no assignee ──────────────────────────────────────
    no_assignee = [c for c in cards if not c.assignee and not c.agent_type and not c.agent_assigned]
    if total > 0 and len(no_assignee) > total * 0.5:
        issues.append({
            "severity": "info",
            "message": f"{len(no_assignee)} card(s) have no assignee or agent.",
        })
        recommendations.append("Assign cards to agents or team members to ensure clear ownership.")

    # ── Strength: checklist usage + completion ──────────────────────────────
    all_checklist = []
    for c in cards:
        if hasattr(c, "checklist_items") and c.checklist_items:
            all_checklist.extend(c.checklist_items)
    if all_checklist:
        completed_items = [i for i in all_checklist if i.completed]
        completion_rate = len(completed_items) / len(all_checklist)
        if completion_rate >= 0.5:
            strengths.append(
                f"Checklist items are {round(completion_rate*100)}% complete — good tracking discipline."
            )
        elif completion_rate < 0.2 and len(all_checklist) > 3:
            issues.append({
                "severity": "info",
                "message": f"Checklist completion is low ({round(completion_rate*100)}% of {len(all_checklist)} items done).",
            })

    # ── Issue: blocked cards (cards with is_blocked_by relations) ──────────
    blocked_cards = []
    for c in cards:
        if hasattr(c, "relations_as_target") and c.relations_as_target:
            for rel in c.relations_as_target:
                if rel.relation_type == "is_blocked_by":
                    source = rel.source_card
                    if source and source.status not in ("done",):
                        blocked_cards.append(c)
                        break
    if blocked_cards:
        issues.append({
            "severity": "warning",
            "message": f"{len(blocked_cards)} card(s) are blocked by unresolved dependencies.",
        })
        recommendations.append("Resolve blocked card dependencies to unblock your team.")

    # ── Strength: done cards signal progress ────────────────────────────────
    if done_cards:
        strengths.append(f"{len(done_cards)} card(s) completed — real progress delivered.")

    # ── Score algorithm ─────────────────────────────────────────────────────
    score = 100
    severity_deductions = {"critical": -15, "warning": -5, "info": -2}
    for issue in issues:
        score += severity_deductions.get(issue["severity"], 0)
    score += len(strengths) * 5
    score = max(0, min(100, score))

    # ── Grade ───────────────────────────────────────────────────────────────
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "strengths": strengths,
        "issues": [HealthIssue(**i) for i in issues],
        "recommendations": recommendations,
        # Context for AI summary
        "_meta": {
            "total": total,
            "todo": len(todo_cards),
            "inprog": len(inprog_cards),
            "done": len(done_cards),
            "backlog": len(backlog_cards),
            "workspace_title": workspace.title,
        },
    }


def _compute_priority_score(card: "Card", all_cards: list["Card"]) -> float:
    """
    Deterministic rule-based scoring (0-100).
    Weights:
      - priority field:      0-25 pts
      - votes:               0-20 pts  (capped at 10 votes = max)
      - unblocks others:     0-20 pts
      - age (days):          0-10 pts  (capped at 30 days)
      - checklist progress:  0-15 pts  (partially done = highest)
      - status:              0-10 pts
    Total max = 100
    """
    score = 0.0
    now = datetime.now(timezone.utc)

    # 1. Priority field (critical=4, high=3, medium=2, low=1, none=0)
    # Map DB values: 3=critical, 2=high, 1=medium, 0=low
    priority_map = {3: 25.0, 2: 18.75, 1: 12.5, 0: 6.25}
    score += priority_map.get(card.priority or 0, 6.25)

    # 2. Votes (more votes = higher) — capped at 10 votes for max score
    votes = card.votes or 0
    score += min(votes / 10.0, 1.0) * 20.0

    # 3. Dependencies: cards that unblock others → higher priority
    # Count how many OTHER cards depend on this card
    dependents_count = 0
    for other in all_cards:
        if other.id == card.id:
            continue
        if hasattr(other, "dependencies"):
            for dep in (other.dependencies or []):
                if dep.id == card.id:
                    dependents_count += 1
    score += min(dependents_count / 3.0, 1.0) * 20.0

    # 4. Age (older = slightly higher) — capped at 30 days
    created_at = card.created_at
    if created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created_at).total_seconds() / 86400
        score += min(age_days / 30.0, 1.0) * 10.0

    # 5. Checklist completion (partially done = highest: started but not finished)
    checklist = list(card.checklist_items) if hasattr(card, "checklist_items") else []
    if checklist:
        total_items = len(checklist)
        done_items = sum(1 for i in checklist if i.completed)
        completion_ratio = done_items / total_items
        # Partially done (0.1-0.9) = max points; fully done or not started = 0
        if 0.0 < completion_ratio < 1.0:
            # Peak at 50% completion
            partial_score = 1.0 - abs(completion_ratio - 0.5) * 2  # 0.5 → 1.0, 0 or 1 → 0
            score += partial_score * 15.0
        # fully done = 0 extra (already done is done)
    # No checklist = neutral (0 pts for this factor)

    # 6. Status (in-progress > todo > backlog; done cards get 0 = should not appear)
    status_map = {"in-progress": 10.0, "todo": 6.0, "backlog": 2.0, "done": 0.0}
    score += status_map.get(card.status or "todo", 2.0)

    return round(min(score, 100.0), 2)
