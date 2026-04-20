"""Auth bootstrap route — serves the bearer token to the same-origin frontend.

``GET /api/auth/bootstrap`` returns the token as JSON. Cross-origin reads are
blocked by the CORS policy in ``main.py`` (``allow_origins`` is a small
allowlist, ``allow_credentials=True``), so a malicious page on another
Tailscale peer or LAN host cannot fetch the token from a user's browser.

This endpoint itself is unauthenticated — it has to be, because the frontend
needs to obtain the token before it can authenticate anything. The security
comes from CORS + network confinement (loopback/Tailscale bind), not from
gating this route.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.auth_service import get_auth_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/bootstrap")
async def bootstrap() -> dict[str, str]:
    """Return the current bearer token for the same-origin frontend."""
    return {"token": get_auth_token()}
