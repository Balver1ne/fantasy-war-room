import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from warroom.api.deps import get_broker, get_session_manager
from warroom.events.broker import EventBroker
from warroom.sync.draft_session import SessionManager

router = APIRouter(prefix="/api", tags=["stream"])

PING_SECONDS = 15


@router.get("/drafts/{draft_id}/events")
async def draft_events(
    draft_id: str,
    request: Request,
    broker: Annotated[EventBroker, Depends(get_broker)],
    sessions: Annotated[SessionManager, Depends(get_session_manager)],
) -> EventSourceResponse:
    async def generate() -> AsyncIterator[dict[str, Any]]:
        async with broker.subscribe(draft_id) as queue:
            # Snapshot greeting instead of a replay buffer: a reconnecting client
            # self-heals exactly like an app restart does (resync from truth).
            session = sessions.get(draft_id)
            snapshot = (
                session.snapshot()
                if session is not None
                else {"draft_id": draft_id, "status": "no_session", "running": False}
            )
            yield {"event": "resync", "id": "0", "data": json.dumps(snapshot)}
            while True:
                event = await queue.get()
                yield {
                    "event": event.type,
                    "id": str(event.seq),
                    "data": json.dumps({"ts": event.ts.isoformat(), **event.data}),
                }

    return EventSourceResponse(generate(), ping=PING_SECONDS)
