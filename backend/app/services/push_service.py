"""Web Push notifications — VAPID keys + fan-out to saved subscriptions.

Gated end-to-end behind ``push.enabled`` in app_settings (default OFF). Each
event type can be individually disabled via ``push.events.{event}`` (default ON
when key missing).

VAPID keypair:
  - Private key — raw base64url (32-byte EC scalar) — this is what
    ``pywebpush.Vapid.from_raw`` expects. Persisted via keyring when available,
    otherwise in ``~/.voxyflow/vapid_private_key`` (0600).
  - Public key — raw base64url — stored in app_settings under ``push.vapid_public_key``
    and returned by ``GET /api/push/vapid-public-key`` so the frontend can pass it
    to ``pushManager.subscribe()``.

``pywebpush.webpush`` is synchronous and makes an HTTP request per subscription
— always call it through ``asyncio.to_thread`` so we don't block the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import _get_secret
from app.database import PushSubscription, async_session, utcnow
from app.services.settings_loader import _load_settings_from_db

logger = logging.getLogger(__name__)

_SERVICE = "voxyflow"
_KEYRING_PRIVATE = "vapid_private_key"
_VAPID_FILE_FALLBACK = Path(
    os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow"))
) / "vapid_private_key"


# ---------------------------------------------------------------------------
# VAPID key management
# ---------------------------------------------------------------------------

async def _save_public_key_to_settings(public_b64url: str) -> None:
    """Persist the VAPID public key into the app_settings JSON blob under push.*."""
    from app.routes.settings import _save_settings_to_db  # local import: avoid cycle
    data = await _load_settings_from_db() or {}
    push = data.setdefault("push", {})
    push["vapid_public_key"] = public_b64url
    await _save_settings_to_db(data)


def _generate_keypair_sync() -> tuple[str, str]:
    """Generate a fresh VAPID keypair. Returns (private_raw_b64url, public_b64url).

    The private key is the raw 32-byte EC scalar, base64url-encoded — the format
    ``pywebpush.Vapid.from_raw`` expects. Do NOT use PEM here: pywebpush passes
    string private keys to ``Vapid.from_raw`` (which b64-decodes), so PEM input
    triggers an ASN.1 parsing error at send time.
    """
    import base64
    from py_vapid import Vapid  # pywebpush ships py_vapid
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    v = Vapid()
    v.generate_keys()

    # Private key → raw 32-byte scalar (big-endian), base64url-encoded.
    priv_numbers = v.private_key.private_numbers()  # type: ignore[attr-defined]
    priv_scalar = priv_numbers.private_value.to_bytes(32, byteorder="big")
    private_raw = base64.urlsafe_b64encode(priv_scalar).rstrip(b"=").decode("ascii")

    # Public key → raw uncompressed EC point, base64url-encoded (applicationServerKey).
    raw_pub = v.public_key.public_bytes(  # type: ignore[attr-defined]
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    public_b64url = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("ascii")
    return private_raw, public_b64url


def _read_private_from_file() -> str | None:
    try:
        if _VAPID_FILE_FALLBACK.exists():
            return _VAPID_FILE_FALLBACK.read_text(encoding="utf-8").strip() or None
    except Exception as e:
        logger.warning("push_service: could not read vapid file fallback: %s", e)
    return None


def _write_private_to_file(private_raw: str) -> None:
    try:
        _VAPID_FILE_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
        tmp = _VAPID_FILE_FALLBACK.with_suffix(".tmp")
        tmp.write_text(private_raw, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, _VAPID_FILE_FALLBACK)
    except Exception as e:
        logger.warning("push_service: could not write vapid file fallback: %s", e)


async def get_vapid_keys() -> tuple[str, str]:
    """Return (private_raw_b64url, public_b64url). Generate + persist on first use.

    Private-key persistence tries keyring first (if unlocked), then a 0600 file
    fallback under VOXYFLOW_DATA_DIR. If neither works we still return the
    freshly-generated key for the current process, but it won't survive a restart.
    """
    # 1. File first (fast; avoids a blocking keyring.get_password on locked collections)
    private_raw = _read_private_from_file()
    # 2. Env var
    if not private_raw:
        private_raw = os.environ.get("VAPID_PRIVATE_KEY", "") or ""
    # 3. Keyring last (can block for seconds when the collection is locked)
    if not private_raw:
        private_raw = _get_secret(_SERVICE, _KEYRING_PRIVATE, env_var=None)

    data = await _load_settings_from_db() or {}
    public_b64url = (data.get("push") or {}).get("vapid_public_key", "")

    if private_raw and public_b64url:
        return private_raw, public_b64url

    # Generate a new pair. Don't block the loop — key generation does a small
    # amount of EC math that's effectively instant, but to_thread keeps the
    # pattern consistent with other blocking crypto in this module.
    private_raw, public_b64url = await asyncio.to_thread(_generate_keypair_sync)

    # Persist to file (0600). File is authoritative here — keyring writes can
    # hang for seconds on a locked collection (KDE/Gnome headless setups).
    _write_private_to_file(private_raw)

    await _save_public_key_to_settings(public_b64url)
    logger.info("push_service: generated new VAPID keypair. Public key: %s", public_b64url)
    return private_raw, public_b64url


async def get_vapid_subject() -> str:
    """Subject claim embedded in every VAPID JWT. Overridable via app settings."""
    data = await _load_settings_from_db() or {}
    subj = (data.get("push") or {}).get("vapid_subject")
    if isinstance(subj, str) and subj.strip():
        return subj.strip()
    return "mailto:admin@localhost"


# ---------------------------------------------------------------------------
# Push dispatch
# ---------------------------------------------------------------------------

def _event_enabled(push_cfg: dict, event: str) -> bool:
    """Return True unless push.events.{event} is explicitly falsy."""
    events = push_cfg.get("events")
    if not isinstance(events, dict):
        return True
    if event not in events:
        return True
    return bool(events.get(event))


def _send_webpush_sync(
    subscription_info: dict,
    payload: str,
    vapid_private_key: str,
    vapid_claims: dict,
) -> None:
    """Blocking webpush call — always wrap in asyncio.to_thread."""
    from pywebpush import webpush
    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=dict(vapid_claims),  # pywebpush mutates this dict (adds `exp`)
    )


async def notify_user(
    event: str,
    title: str,
    body: str,
    url: str | None = None,
    icon: str | None = None,
    tag: str | None = None,
) -> None:
    """Fan-out a notification to every saved push subscription.

    Silently no-ops when ``push.enabled`` is falsy or when this event type is
    disabled. Stale subscriptions (HTTP 410 from the push service) are deleted.
    """
    data = await _load_settings_from_db() or {}
    push_cfg = data.get("push") or {}
    if not push_cfg.get("enabled"):
        return
    if not _event_enabled(push_cfg, event):
        return

    try:
        private_pem, _public = await get_vapid_keys()
    except Exception as e:
        logger.warning("push_service: could not load VAPID keys, skipping notify: %s", e)
        return
    subject = await get_vapid_subject()

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": icon,
        "tag": tag,
        "event": event,
    })

    async with async_session() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
        if not rows:
            return

        stale_ids: list[str] = []
        for sub in rows:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            try:
                await asyncio.to_thread(
                    _send_webpush_sync,
                    subscription_info,
                    payload,
                    private_pem,
                    {"sub": subject},
                )
                sub.last_used_at = utcnow()
            except Exception as e:
                # pywebpush raises WebPushException — import locally to keep the
                # module import-safe even when pywebpush isn't installed.
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code in (404, 410):
                    stale_ids.append(sub.id)
                    logger.info(
                        "push_service: removing stale subscription (HTTP %s): %s",
                        status_code, sub.endpoint[:60],
                    )
                else:
                    logger.warning(
                        "push_service: webpush failed for %s: %s",
                        sub.endpoint[:60], e,
                    )

        if stale_ids:
            for sid in stale_ids:
                stale = await session.get(PushSubscription, sid)
                if stale is not None:
                    await session.delete(stale)
        await session.commit()


async def send_test_push() -> dict[str, Any]:
    """Send a canned test notification to every subscriber.

    Bypasses ``push.enabled`` / per-event gating so the user can verify plumbing
    from the Settings UI even while push is disabled by default.
    """
    try:
        private_pem, _public = await get_vapid_keys()
    except Exception as e:
        return {"sent": 0, "failed": 0, "error": f"vapid key load failed: {e}"}
    subject = await get_vapid_subject()

    payload = json.dumps({
        "title": "Voxyflow test",
        "body": "Push notifications are working.",
        "url": "/",
        "event": "test",
        "tag": "voxyflow-test",
    })

    sent = 0
    failed = 0
    async with async_session() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
        stale_ids: list[str] = []
        for sub in rows:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            try:
                await asyncio.to_thread(
                    _send_webpush_sync,
                    subscription_info,
                    payload,
                    private_pem,
                    {"sub": subject},
                )
                sub.last_used_at = utcnow()
                sent += 1
            except Exception as e:
                failed += 1
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code in (404, 410):
                    stale_ids.append(sub.id)
                logger.warning("push_service: test push failed: %s", e)

        if stale_ids:
            for sid in stale_ids:
                stale = await session.get(PushSubscription, sid)
                if stale is not None:
                    await session.delete(stale)
        await session.commit()

    return {"sent": sent, "failed": failed, "total": sent + failed}


# ---------------------------------------------------------------------------
# Deep-link helper
# ---------------------------------------------------------------------------

def build_deep_link(project_id: str | None, card_id: str | None) -> str:
    """Build a frontend URL for a notification.

    Matches the routes declared in ``frontend-react/src/router.tsx``:
    only ``/project/:id`` exists — there is no dedicated ``/board/`` route,
    so we use the project page with a ``?card=`` query param so the UI can
    open the card detail panel on load.
    """
    if project_id and card_id:
        return f"/project/{project_id}?card={card_id}"
    if project_id:
        return f"/project/{project_id}"
    return "/"
