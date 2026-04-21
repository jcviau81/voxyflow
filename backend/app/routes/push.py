"""Web Push subscription + VAPID key routes.

The public key endpoint is intentionally unauthenticated — the frontend needs
it before it can call ``PushManager.subscribe()``, which happens before the
user has interacted with any authed UI.

Subscribe / unsubscribe / test require the bootstrap bearer token (same model
as ``settings.py``).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import PushSubscription, get_db, new_uuid, utcnow
from app.services.auth_service import verify_auth
from app.services.push_service import get_vapid_keys, send_test_push

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    userAgent: str | None = None


class UnsubscribeRequest(BaseModel):
    endpoint: str


class SubscriptionResponse(BaseModel):
    id: str
    endpoint: str
    user_agent: str | None
    created_at: str
    last_used_at: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key (base64url). Public — no auth required."""
    try:
        _private, public = await get_vapid_keys()
    except Exception as e:
        logger.exception("Failed to load/generate VAPID keys")
        raise HTTPException(500, f"Could not load VAPID keys: {e}")
    return {"public_key": public}


@router.post("/subscribe", dependencies=[Depends(verify_auth)])
async def subscribe(body: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    """Upsert a push subscription by endpoint."""
    if not body.endpoint:
        raise HTTPException(400, "endpoint is required")

    stmt = select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is not None:
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_agent = body.userAgent
        await db.commit()
        return {"id": existing.id, "created": False}

    sub = PushSubscription(
        id=new_uuid(),
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.userAgent,
        created_at=utcnow(),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    logger.info("push: new subscription %s (%s)", sub.id, (body.userAgent or "")[:40])
    return {"id": sub.id, "created": True}


@router.post("/unsubscribe", dependencies=[Depends(verify_auth)])
async def unsubscribe(body: UnsubscribeRequest, db: AsyncSession = Depends(get_db)):
    """Remove a push subscription by endpoint. Idempotent."""
    if not body.endpoint:
        raise HTTPException(400, "endpoint is required")

    stmt = select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        return {"deleted": False}

    await db.delete(existing)
    await db.commit()
    return {"deleted": True}


@router.get("/subscriptions")
async def list_subscriptions(db: AsyncSession = Depends(get_db)):
    """Debug: list all saved subscriptions (endpoint truncated in response)."""
    rows = (await db.execute(select(PushSubscription))).scalars().all()
    return {
        "subscriptions": [
            SubscriptionResponse(
                id=r.id,
                endpoint=r.endpoint,
                user_agent=r.user_agent,
                created_at=r.created_at.isoformat() if r.created_at else "",
                last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            ).dict()
            for r in rows
        ]
    }


@router.post("/test", dependencies=[Depends(verify_auth)])
async def test_push():
    """Send a canned test notification to every saved subscription."""
    result = await send_test_push()
    return result
