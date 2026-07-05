import httpx
import pytest
import respx
from warroom.platforms.sleeper.client import SleeperClient

BASE = "http://sleeper.test/v1"


async def no_sleep(_delay: float) -> None:
    pass


def make_client() -> SleeperClient:
    client = SleeperClient(BASE)
    client._sleep = no_sleep
    return client


@respx.mock
async def test_retry_on_500_then_success():
    route = respx.get(f"{BASE}/league/123").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"league_id": "123"})]
    )
    client = make_client()
    assert await client.get_league("123") == {"league_id": "123"}
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_retry_on_429_then_success():
    route = respx.get(f"{BASE}/user/paul").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"user_id": "1"})]
    )
    client = make_client()
    assert await client.get_user("paul") == {"user_id": "1"}
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_gives_up_after_retries_exhausted():
    route = respx.get(f"{BASE}/league/123").mock(return_value=httpx.Response(500))
    client = make_client()
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_league("123")
    assert route.call_count == 4  # initial + 3 retries
    await client.aclose()


@respx.mock
async def test_404_is_not_retried():
    route = respx.get(f"{BASE}/league/nope").mock(return_value=httpx.Response(404))
    client = make_client()
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_league("nope")
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_picks_endpoint_never_retries():
    """The poll loop owns backoff/stale policy — client retries would mask staleness."""
    route = respx.get(f"{BASE}/draft/D1/picks").mock(return_value=httpx.Response(500))
    client = make_client()
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_draft_picks("D1")
    assert route.call_count == 1
    await client.aclose()
