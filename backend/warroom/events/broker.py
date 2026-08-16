import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

QUEUE_SIZE = 200


class Event(BaseModel):
    seq: int
    type: str  # resync | pick | on_clock | stale | recovered | status
    draft_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class EventBroker:
    """Per-draft fan-out. No replay buffer: every new subscriber immediately receives
    a synthetic `resync` snapshot from the session, so reconnects self-heal the same
    way an app restart does."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {}

    def publish(self, event: Event) -> None:
        dead: list[asyncio.Queue[Event]] = []
        for queue in self._subscribers.get(event.draft_id, ()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop it rather than stall the draft feed.
                dead.append(queue)
        for queue in dead:
            log.warning("Dropping slow SSE subscriber for draft %s", event.draft_id)
            self._subscribers[event.draft_id].discard(queue)

    @asynccontextmanager
    async def subscribe(self, draft_id: str) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.setdefault(draft_id, set()).add(queue)
        try:
            yield queue
        finally:
            subs = self._subscribers.get(draft_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(draft_id, None)

    def subscriber_count(self, draft_id: str) -> int:
        return len(self._subscribers.get(draft_id, ()))
