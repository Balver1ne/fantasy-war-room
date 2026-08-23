# War Room — project rules for Claude Code sessions

## Prime directive
`docs/DESIGN.md` is the authoritative build specification. Follow it section by section.
Work **one phase at a time** (Section 8) — do not start phase N+1 features while phase N's
deliverable is unproven. Matching quality is the app.

## Naming standard (DESIGN.md §10.2 — use everywhere)
- Python package: `warroom` (lives at `backend/warroom/`); entry point `python -m warroom`
- Platform adapters: `warroom/platforms/<vendor>/`, each implementing the `PlatformAdapter` interface
- Frontend app: `warroom-ui` at `/frontend` (Phase 4; requires Node, not needed before then)
- App display name: **War Room**
- SQLite file: `warroom.db` (at `data/warroom.db`, gitignored)
- Env var prefix: `WARROOM_` (e.g. `WARROOM_PORT`, `WARROOM_POLL_INTERVAL`)
- Season versioning: git tags `2026.x`, one release tag per phase

## Hard rules
- **Never commit** `data/`, `*.db`, `.env`, or any subscriber content (4for4, Fantasy
  Headliners). Subscriber content is paid IP — it never gets committed, even to a private
  repo. Test fixtures must be synthetic or sanitized.
- **All platform-specific code behind `PlatformAdapter`** (`warroom/platforms/base.py`).
  The engine, data model, and UI consume only normalized outputs — zero Sleeper-specific
  logic outside `warroom/platforms/sleeper/`.
- No authenticated scraping of paywalled sites. Subscriber content enters via user exports.
- Sleeper API is read-only, no auth; stay well under 1000 requests/minute.

## How to run / test
- Setup: `python -m venv .venv && source .venv/Scripts/activate && pip install -e ".[dev]"`
- Run: `python -m warroom` (serves on `http://127.0.0.1:8734`; `WARROOM_PORT` overrides)
- Test: `pytest` from repo root
- DB: `data/warroom.db`, created on first run. In Phase 1 it is a disposable mirror of
  Sleeper truth — schema changes are handled by deleting the file and resyncing (no alembic
  until Phase 2, when user-entered data appears).

## Environment quirks
- Windows 11, git bash shell. `make`, `gh`, and Node are **not installed** — use
  `python -m ...` invocations; git remote already exists (no `gh` needed).

## Git workflow (DESIGN.md §10.5)
- Feature branch per phase (e.g. `phase-1-sleeper-plumbing`), phase-prefixed commits
  (`phase-1: pick polling + SSE`), merge `--no-ff` to `main` when the phase deliverable
  passes, then tag (`2026.1` … `2026.5`).

## Current state
- Phase 1 COMPLETE, merged to `main`, tagged `2026.1`. Sleeper adapter behind
  PlatformAdapter, player universe sync (~12k players), draft session poll loop with
  diff/resync/backoff, SSE + `/debug` console, snake/traded-pick math, 72 passing tests.
  Live acceptance passed: picks streamed within 2–3 s, snake round-turns matched Sleeper,
  resume-safety confirmed (server restart + draft pause/restart both followed along).
- 3rd-round reversal: implemented and unit-tested, but the user's leagues do not use it,
  so it is not a verification concern. Do not spend effort re-confirming it live.
- TLS note: this machine's TLS path is intercepted (AV/proxy), so `create_app` calls
  `truststore.inject_into_ssl()` to use the Windows cert store. Don't remove it.
- Environment: the user runs commands in **Windows PowerShell**, not bash. Give
  PowerShell syntax (`Invoke-RestMethod`, `.venv\Scripts\python.exe`, `curl.exe` for real
  curl).
- Phase 2 (ingestion + matching) COMPLETE — merged to `main`, tagged `2026.2` (UAT
  passed). Matching engine (alias/exact/fuzzy, collisions to queue), CSV + PDF importers,
  column-mapping wizard, versioned ranking sets (deletable), user-defined flags,
  `/import` console. Verified vs the real 12k universe: FantasyPros 99.2%, TFH rankings
  100%, flags (sleeper/breakout/bust/value_pick) in `player_flags`. Next: Phase 3 —
  recommendation engine (DESIGN.md §5). Real research files live OUTSIDE the repo at
  `C:\Users\Paul\Documents\fantasy_football_research` (subscriber content, never committed;
  don't copy into the repo). PDF parsers are text-based (pdfplumber); handcuffs layout
  uses the paste fallback by design.
