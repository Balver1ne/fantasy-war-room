import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from warroom.config import Settings
from warroom.db import repo
from warroom.events.broker import Event, EventBroker
from warroom.platforms.base import PlatformAdapter
from warroom.platforms.models import DraftInfo, PickInfo
from warroom.sync import snake

draft_log = logging.getLogger("warroom.draft")
log = logging.getLogger(__name__)

RECENT_PICKS = 10


class DraftSession:
    """Live sync loop for one draft (DESIGN.md §3).

    Sleeper's pick list is the source of truth: seeding, restart recovery, and
    anomaly handling are all the same wholesale-replace path.
    """

    def __init__(
        self,
        draft_id: str,
        adapter: PlatformAdapter,
        broker: EventBroker,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        my_slot: int | None = None,
        my_roster_id: int | None = None,
        my_user_id: str | None = None,
    ) -> None:
        self.draft_id = draft_id
        self._adapter = adapter
        self._broker = broker
        self._session_factory = session_factory
        self._settings = settings
        self.my_slot = my_slot
        self.my_roster_id = my_roster_id
        self.my_user_id = my_user_id

        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._seq = 0
        self._draft: DraftInfo | None = None
        self._cfg: snake.DraftOrderConfig | None = None
        self._applied: dict[int, str] = {}  # pick_no -> platform_player_id
        self._recent: list[dict[str, Any]] = []
        self.stale = False
        self._failures = 0
        self._last_success: datetime | None = None

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        await self._seed(initial=True)
        self._task = asyncio.create_task(self._run(), name=f"draft-session-{self.draft_id}")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---- state -----------------------------------------------------------

    @property
    def last_pick_no(self) -> int:
        return max(self._applied, default=0)

    @property
    def status(self) -> str:
        return self._draft.status if self._draft else "unknown"

    def snapshot(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "status": self.status,
            "running": self.running,
            "pick_count": self.last_pick_no,
            "stale": self.stale,
            "last_success": self._last_success.isoformat() if self._last_success else None,
            "my_slot": self.my_slot,
            "my_roster_id": self.my_roster_id,
            "last_picks": self._recent[-RECENT_PICKS:],
            "on_clock": self._on_clock_payload(),
        }

    # ---- events ----------------------------------------------------------

    def _emit(self, type_: str, data: dict[str, Any]) -> None:
        self._seq += 1
        self._broker.publish(
            Event(seq=self._seq, type=type_, draft_id=self.draft_id, data=data)
        )

    def emit_snapshot(self) -> None:
        """Synthetic resync for a newly connected SSE subscriber."""
        self._emit("resync", self.snapshot())

    # ---- sync core -------------------------------------------------------

    async def _seed(self, initial: bool = False) -> None:
        """Full resync from the platform — also the restart/anomaly recovery path."""
        draft = await self._adapter.get_draft(self.draft_id)
        self._draft = draft
        self._resolve_identity(draft)
        traded = await self._adapter.get_traded_picks(self.draft_id)
        self._cfg = snake.DraftOrderConfig(
            team_count=draft.team_count,
            rounds=draft.rounds,
            draft_type="linear" if draft.draft_type == "linear" else "snake",
            reversal_round=draft.reversal_round,
            slot_to_roster=draft.slot_to_roster,
            traded={
                (t.round, t.original_roster_id): t.current_owner_roster_id for t in traded
            },
        )
        picks = await self._adapter.get_picks(self.draft_id)
        with self._session_factory() as session:
            repo.upsert_draft(session, draft)
            repo.replace_picks(session, self.draft_id, picks)
            session.commit()
            self._recent = [
                self._pick_payload(p, session) for p in picks[-RECENT_PICKS:]
            ]
        self._applied = {p.pick_no: p.platform_player_id for p in picks}
        self._last_success = datetime.now(UTC)
        self._emit("resync", self.snapshot())
        draft_log.info(
            "RESYNC draft %s: %d picks, status=%s%s",
            self.draft_id,
            len(picks),
            draft.status,
            " (session start)" if initial else "",
        )
        self._log_on_clock()

    def _resolve_identity(self, draft: DraftInfo) -> None:
        if self.my_user_id and draft.draft_order and self.my_slot is None:
            self.my_slot = draft.draft_order.get(self.my_user_id)
        if self.my_slot is not None and self.my_roster_id is None:
            self.my_roster_id = draft.slot_to_roster.get(self.my_slot)

    async def _poll_once(self) -> list[PickInfo]:
        """One poll iteration: fetch, diff by pick_no, apply. Returns new picks."""
        picks = await self._adapter.get_picks(self.draft_id)
        fetched = {p.pick_no: p.platform_player_id for p in picks}
        overlap_changed = any(
            fetched.get(no) != pid for no, pid in self._applied.items()
        )
        if len(picks) < len(self._applied) or overlap_changed:
            draft_log.warning(
                "Pick list anomaly on draft %s (undo or platform hiccup) — full resync",
                self.draft_id,
            )
            await self._seed()
            return []

        new_picks = sorted(
            (p for p in picks if p.pick_no not in self._applied),
            key=lambda p: p.pick_no,
        )
        if new_picks:
            with self._session_factory() as session:
                repo.append_picks(session, self.draft_id, new_picks)
                session.commit()
                for pick in new_picks:
                    payload = self._pick_payload(pick, session)
                    self._applied[pick.pick_no] = pick.platform_player_id
                    self._recent.append(payload)
                    self._emit("pick", payload)
                    self._log_pick(payload)
            self._recent = self._recent[-RECENT_PICKS:]
            self._emit("on_clock", self._on_clock_payload() or {})
            self._log_on_clock()
        self._last_success = datetime.now(UTC)
        return new_picks

    async def _refresh_meta(self) -> None:
        """60s cadence: traded picks + draft status (catches pause/complete/order fill)."""
        draft = await self._adapter.get_draft(self.draft_id)
        old_status = self.status
        self._draft = draft
        self._resolve_identity(draft)
        traded = await self._adapter.get_traded_picks(self.draft_id)
        if self._cfg is not None:
            self._cfg = snake.DraftOrderConfig(
                team_count=draft.team_count or self._cfg.team_count,
                rounds=draft.rounds or self._cfg.rounds,
                draft_type="linear" if draft.draft_type == "linear" else "snake",
                reversal_round=draft.reversal_round,
                slot_to_roster=draft.slot_to_roster or self._cfg.slot_to_roster,
                traded={
                    (t.round, t.original_roster_id): t.current_owner_roster_id
                    for t in traded
                },
            )
        with self._session_factory() as session:
            repo.upsert_draft(session, draft)
            session.commit()
        if draft.status != old_status:
            self._emit("status", {"from": old_status, "to": draft.status})
            draft_log.info("STATUS draft %s: %s → %s", self.draft_id, old_status, draft.status)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_meta = loop.time() + self._adapter.traded_picks_interval
        try:
            while not self._stopping.is_set():
                delay = self._adapter.poll_interval
                prev_success = self._last_success
                try:
                    await self._poll_once()
                    if self.stale:
                        downtime = (
                            datetime.now(UTC) - prev_success
                        ).total_seconds() if prev_success else 0.0
                        self.stale = False
                        self._failures = 0
                        self._emit("recovered", {"downtime_seconds": round(downtime, 1)})
                        draft_log.info("RECOVERED after %.1fs — resyncing", downtime)
                        await self._seed()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._failures += 1
                    delay = min(
                        self._adapter.poll_interval * 2 ** (self._failures - 1),
                        self._settings.max_backoff,
                    )
                    if not self.stale:
                        self.stale = True
                        self._emit(
                            "stale",
                            {
                                "consecutive_failures": self._failures,
                                "last_success": self._last_success.isoformat()
                                if self._last_success
                                else None,
                            },
                        )
                    draft_log.warning(
                        "STALE: poll failed x%d (%s) — backing off %.1fs",
                        self._failures,
                        exc,
                        delay,
                    )

                if not self.stale and loop.time() >= next_meta:
                    try:
                        await self._refresh_meta()
                    except Exception as exc:
                        log.warning("Meta refresh failed for %s: %s", self.draft_id, exc)
                    next_meta = loop.time() + self._adapter.traded_picks_interval

                all_picks_made = (
                    self._cfg is not None
                    and self._cfg.total_picks > 0
                    and self.last_pick_no >= self._cfg.total_picks
                )
                if self.status == "complete" or all_picks_made:
                    draft_log.info(
                        "COMPLETE draft %s after %d picks", self.draft_id, self.last_pick_no
                    )
                    if self.status != "complete":
                        # _refresh_meta emits the transition when Sleeper reports it;
                        # this covers the all-picks-made case ahead of that.
                        self._emit("status", {"from": self.status, "to": "complete"})
                    break

                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=delay)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    # ---- payloads / logging ----------------------------------------------

    def _pick_payload(self, pick: PickInfo, session: Session) -> dict[str, Any]:
        player = repo.get_players_by_ids(session, [pick.platform_player_id]).get(
            pick.platform_player_id
        )
        label = (
            snake.format_pick(pick.pick_no, self._cfg)
            if self._cfg and self._cfg.team_count
            else f"{pick.round}.{pick.draft_slot:02d}"
        )
        return {
            "pick_no": pick.pick_no,
            "round": pick.round,
            "draft_slot": pick.draft_slot,
            "label": label,
            "player": {
                "id": pick.platform_player_id,
                "name": player.name if player else pick.metadata.get("first_name", "?"),
                "position": player.position if player else pick.metadata.get("position"),
                "team": player.team if player else pick.metadata.get("team"),
            },
            "roster_id": pick.roster_id,
            "picked_by": pick.picked_by,
        }

    def _on_clock_payload(self) -> dict[str, Any] | None:
        if not self._cfg or not self._cfg.team_count:
            return None
        next_no = self.last_pick_no + 1
        if next_no > self._cfg.total_picks:
            return None
        round_no, slot = snake.slot_for_pick(next_no, self._cfg)
        until = snake.picks_until(
            self.last_pick_no,
            self._cfg,
            roster_id=self.my_roster_id,
            slot=self.my_slot if self.my_roster_id is None else None,
        )
        return {
            "next_pick_no": next_no,
            "label": snake.format_pick(next_no, self._cfg),
            "round": round_no,
            "slot": slot,
            "roster_id": snake.owner_of_pick(next_no, self._cfg),
            "picks_until_me": until,
            "alert": until is not None and until <= 2,
        }

    def _log_pick(self, payload: dict[str, Any]) -> None:
        player = payload["player"]
        draft_log.info(
            "PICK %3d %s  %s (%s, %s) → slot %s",
            payload["pick_no"],
            payload["label"],
            player["name"],
            player["position"] or "?",
            player["team"] or "FA",
            payload["draft_slot"],
        )

    def _log_on_clock(self) -> None:
        oc = self._on_clock_payload()
        if oc is None:
            return
        until = oc["picks_until_me"]
        if until == 0:
            draft_log.info(
                ">>> YOU ARE ON THE CLOCK — pick %s (%s) <<<", oc["next_pick_no"], oc["label"]
            )
        elif until is not None and until <= 2:
            draft_log.info("ALERT: you pick in %d (pick %s)", until, oc["next_pick_no"])
        elif until is not None:
            draft_log.info("Next: pick %s (%s), slot %s — you pick in %d",
                           oc["next_pick_no"], oc["label"], oc["slot"], until)


class SessionManager:
    def __init__(
        self,
        adapter: PlatformAdapter,
        broker: EventBroker,
        session_factory: sessionmaker[Session],
        settings: Settings,
    ) -> None:
        self._adapter = adapter
        self._broker = broker
        self._session_factory = session_factory
        self._settings = settings
        self._sessions: dict[str, DraftSession] = {}

    def get(self, draft_id: str) -> DraftSession | None:
        return self._sessions.get(draft_id)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.running)

    async def start_session(
        self,
        draft_id: str,
        *,
        my_slot: int | None = None,
        my_roster_id: int | None = None,
        my_user_id: str | None = None,
    ) -> DraftSession:
        existing = self._sessions.get(draft_id)
        if existing is not None and existing.running:
            return existing
        session = DraftSession(
            draft_id,
            self._adapter,
            self._broker,
            self._session_factory,
            self._settings,
            my_slot=my_slot,
            my_roster_id=my_roster_id,
            my_user_id=my_user_id,
        )
        await session.start()
        self._sessions[draft_id] = session
        return session

    async def stop_session(self, draft_id: str) -> bool:
        session = self._sessions.pop(draft_id, None)
        if session is None:
            return False
        await session.stop()
        return True

    async def stop_all(self) -> None:
        for draft_id in list(self._sessions):
            await self.stop_session(draft_id)
