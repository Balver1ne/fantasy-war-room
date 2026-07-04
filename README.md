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

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo + Sleeper plumbing (live pick polling, SSE, resume-safe state) | in progress |
| 2 | Ingestion + player matching | — |
| 3 | Recommendation engine | — |
| 4 | Draft Room UI | — |
| 5 | Multi-league + polish | — |

## Draft day checklist

(Filled in as phases complete.)

1. Refresh player universe: `curl -X POST http://127.0.0.1:8734/api/players/sync?force=true`
2. Import latest rankings (Phase 2+)
3. Confirm league scoring preset (Phase 5)
4. Run one mock draft end-to-end
