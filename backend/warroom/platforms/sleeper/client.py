import asyncio
import logging
import random
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SleeperClient:
    """Raw wrappers over the public read-only Sleeper API (base: /v1, no auth).

    Steady-state usage while drafting is ~31 requests/minute — far under Sleeper's
    1000/min guidance — so a 429 here means something is wrong and is logged loudly.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
        self._sleep = asyncio.sleep  # injectable so retry tests don't wall-clock wait

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, retries: int = 3) -> Any:
        delay = 0.5
        attempt = 0
        while True:
            try:
                resp = await self._client.get(path)
                if resp.status_code == 429:
                    log.warning("Sleeper rate limit (429) on %s — backing off %.1fs", path, delay)
                    raise httpx.HTTPStatusError("429", request=resp.request, response=resp)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = status is None or status >= 500 or status == 429
                if not retryable or attempt >= retries:
                    raise
                attempt += 1
                await self._sleep(delay + random.uniform(0, delay / 4))
                delay *= 2

    async def get_user(self, username_or_id: str) -> dict:
        return await self._get(f"/user/{username_or_id}")

    async def get_user_leagues(self, user_id: str, season: str, sport: str = "nfl") -> list[dict]:
        return await self._get(f"/user/{user_id}/leagues/{sport}/{season}")

    async def get_league(self, league_id: str) -> dict:
        return await self._get(f"/league/{league_id}")

    async def get_league_users(self, league_id: str) -> list[dict]:
        return await self._get(f"/league/{league_id}/users")

    async def get_league_rosters(self, league_id: str) -> list[dict]:
        return await self._get(f"/league/{league_id}/rosters")

    async def get_league_drafts(self, league_id: str) -> list[dict]:
        return await self._get(f"/league/{league_id}/drafts")

    async def get_draft(self, draft_id: str) -> dict:
        return await self._get(f"/draft/{draft_id}")

    async def get_draft_picks(self, draft_id: str) -> list[dict]:
        # retries=0: the poll loop owns backoff and the stale/recovered contract;
        # client-level retries here would mask staleness from the user.
        return await self._get(f"/draft/{draft_id}/picks", retries=0)

    async def get_traded_picks(self, draft_id: str) -> list[dict]:
        return await self._get(f"/draft/{draft_id}/traded_picks")

    async def get_players(self) -> dict[str, dict]:
        # ~5 MB payload — only PlayerSyncService may call this (once/day cache policy).
        return await self._get("/players/nfl")
