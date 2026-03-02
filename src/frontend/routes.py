# src/frontend/routes.py
# FastAPI routes mounted on NiceGUI's internal FastAPI app.

from __future__ import annotations

from fastapi import Request
from nicegui import app

from src.core.config import settings

# ---------------------------------------------------------------------------
# Shared in-memory transcript state
# Resets on server restart; shared across all browser tabs in the same process.
# ---------------------------------------------------------------------------

_transcript: list[dict[str, str]] = []

_ROOM = "newsletter"
_AGENT_NAME = "newsletter"


@app.get("/token")
async def get_token() -> dict:
    """Return a LiveKit JWT and dispatch the agent to the room."""
    from livekit import api  # noqa: PLC0415
    from livekit.api import AccessToken, VideoGrants  # noqa: PLC0415

    try:
        token = (
            AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
            .with_grants(VideoGrants(room_join=True, room=_ROOM))
            .with_identity("user")
            .to_jwt()
        )
    except Exception as exc:
        from fastapi.responses import JSONResponse  # noqa: PLC0415

        return JSONResponse({"error": str(exc)}, status_code=503)

    # Dispatch the agent to the room so it joins when the user connects.
    # If the agent worker isn't running the dispatch is silently skipped.
    lk = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=_AGENT_NAME, room=_ROOM)
        )
    except Exception:
        pass  # agent worker not running — user can still join the empty room
    finally:
        await lk.aclose()

    return {"token": token, "url": str(settings.livekit_url)}


@app.post("/transcript")
async def post_transcript(request: Request) -> dict:
    """Receive a final transcript segment from the JS audio widget.

    Expected body: {"role": "user" | "assistant", "text": "..."}
    """
    data = await request.json()
    text = str(data.get("text", "")).strip()
    if text:
        _transcript.append({"role": str(data.get("role", "user")), "text": text})
    return {"ok": True}
