"""Smoke test: fire a canned Web Push notification through notify_user().

Usage (from backend/ with the venv active):
    python -m scripts.push_smoke

Respects ``push.enabled`` in app_settings — if push is off, this is a no-op.
Use POST /api/push/test to bypass the gate.
"""
import asyncio
import logging

from app.services.push_service import notify_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def main() -> None:
    await notify_user(
        event="smoke_test",
        title="Voxyflow smoke test",
        body="If you see this, Web Push is wired up correctly.",
        url="/",
        tag="voxyflow-smoke",
    )


if __name__ == "__main__":
    asyncio.run(main())
