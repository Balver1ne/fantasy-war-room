# War Room

A locally run fantasy football draft companion. Connects to a live Sleeper draft, tracks
every pick in near real time, and (from Phase 3) recommends the best available pick using
multi-source rankings, league-adjusted value, and your personal preferences.

Full specification: [docs/DESIGN.md](docs/DESIGN.md)

## Run

```bash
python -m venv .venv
source .venv/Scripts/activate      # git bash on Windows; .venv\Scripts\activate in cmd
pip install -e ".[dev]"
python -m warroom                  # serves http://127.0.0.1:8734
```

Configuration via environment variables with the `WARROOM_` prefix (or a `.env` file):
`WARROOM_PORT` (default 8734), `WARROOM_SEASON` (default 2026), `WARROOM_DB_PATH`
(default `data/warroom.db`), `WARROOM_LOG_LEVEL`.

Tests: `pytest`

## Following a draft (Phase 1)

1. Start the server: `python -m warroom`. First start syncs the ~12k-player Sleeper
   universe into `data/warroom.db` (a few seconds).
2. Open `http://127.0.0.1:8734/debug` — paste a Sleeper draft id (or use curl below),
   enter your draft slot, click **Start session**.
   ```bash
   curl -X POST http://127.0.0.1:8734/api/drafts/<draft_id>/session \
        -H "content-type: application/json" -d '{"my_slot": 4}'
   curl -N http://127.0.0.1:8734/api/drafts/<draft_id>/events   # raw SSE stream
   ```
   The draft id is in the Sleeper URL: `sleeper.com/draft/nfl/<draft_id>`. A full URL
   pasted as the id also works.
3. Picks appear in the server terminal and on the SSE stream within one 2-second poll.
   `STALE` / `RECOVERED` lines flag connectivity problems — never trust a stale board.
4. Restart-safe: kill the server mid-draft, start it again, re-POST the session — it
   resyncs the full pick list from Sleeper within one poll.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo + Sleeper plumbing (live pick polling, SSE, resume-safe state) | complete — tag `2026.1` |
| 2 | Ingestion + player matching | — |
| 3 | Recommendation engine | — |
| 4 | Draft Room UI | — |
| 5 | Multi-league + polish | — |

### Phase 1 acceptance run — PASSED 2026-07-05

Verified live against a Sleeper mock draft: picks streamed within 2–3 s, snake round-turns
matched Sleeper exactly, all players resolved (no unmatched), on-the-clock/alert logic and
clean draft-complete detection all fired correctly, and resume-safety held (server restart
+ draft pause/restart both re-synced without loss). Re-run steps if regressions are
suspected: `pytest`; `.venv\Scripts\python.exe -m warroom`; start a mock, open `/debug`,
watch picks; Ctrl-C + restart mid-draft to confirm RESYNC.

## Draft day checklist

1. Refresh player universe: `curl -X POST "http://127.0.0.1:8734/api/players/sync?force=true"`
2. Import latest rankings (Phase 2+)
3. Confirm league scoring preset (Phase 5)
4. Run one mock draft end-to-end
