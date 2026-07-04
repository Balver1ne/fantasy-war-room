# Draft Companion — App Design Document

**Purpose:** This document is the build specification for a locally run fantasy football draft companion application. It will be provided to Claude Code as the primary instruction set. Follow it section by section; where the doc says "Phase," treat phases as sequential milestones with working software at the end of each.

---

## 1. Product Overview

A local application that connects to a live Sleeper draft, tracks every pick in near real time, and recommends the best available pick based on:

1. Pre-ingested research: rankings and projections from multiple sources (FantasyPros, ESPN, 4for4, Fantasy Headliners subscriber exports, and arbitrary CSVs)
2. The user's personal preferences and overrides (targets, avoids, tier adjustments)
3. League-specific context pulled automatically from Sleeper (scoring settings, roster slots, number of teams, draft type)
4. Live draft state: who's gone, what my roster looks like, positional runs, and the probability a player survives back to my next pick

The app must support **multiple leagues**, all on Sleeper. All drafts are **snake format** (confirmed — no auction support needed). The dynasty league's rookie draft for this year is already complete; dynasty *draft* modes are out of scope for this version (planned for the 2027 edition). The dynasty league still appears in league management for in-season tracking.

### Non-goals (v1)
- No auction draft support (all leagues are snake)
- No dynasty startup/rookie draft modes (rookie draft already completed; revisit in the 2027 version)
- No keeper handling (confirmed: no keeper rules affect these drafts)
- No writing back to Sleeper (the public API is read-only anyway — picks are made manually in the Sleeper app/site)
- No in-season lineup optimization (that's a later module; design the data layer so it can be added)
- No scraping of paywalled sites. Subscription content (4for4, Fantasy Headliners) enters the system via the user's own exported files, PDFs, or pasted text. Do not build authenticated scrapers.

---

## 2. Architecture

### Stack
- **Backend:** Python 3.11+, FastAPI, uvicorn
- **Frontend:** React + Vite single-page app, served by the backend in production mode (single `localhost` URL to open)
- **Storage:** SQLite (single file, zero setup), accessed via SQLAlchemy
- **HTTP client:** `httpx` with retry/backoff
- **Packaging:** one `make run` / `python -m warroom` entry point that starts the server and opens the browser. No Docker required, but structure the repo so containerizing later is trivial. (Naming standard: Section 10.2.)

### High-level components
```
┌─────────────────────────────────────────────────┐
│                  React UI (localhost)           │
│  Draft Board · Best Available · Tiers · Roster  │
└──────────────▲──────────────────────────────────┘
               │ REST + Server-Sent Events (SSE)
┌──────────────┴──────────────────────────────────┐
│                FastAPI backend                  │
│  ┌───────────┐ ┌────────────┐ ┌──────────────┐  │
│  │ Sleeper   │ │ Ingestion  │ │ Recommendation│ │
│  │ Sync      │ │ Pipeline   │ │ Engine        │ │
│  └─────┬─────┘ └─────┬──────┘ └──────┬───────┘  │
│        └─────────────┴───────────────┘          │
│                   SQLite                        │
└─────────────────────────────────────────────────┘
```

- Backend pushes live draft events to the UI over **SSE** (simpler than websockets for one-directional updates; the UI never needs to push realtime data back).
- All state lives in SQLite so a crash mid-draft loses nothing — restart the app and it resyncs from Sleeper's pick list, which is the source of truth.

---

## 3. Sleeper Integration

### Platform adapter abstraction (required from day one)
The user may expand to other platforms (ESPN, Yahoo, etc.) in future seasons. All platform-specific code must sit behind a `PlatformAdapter` interface in `warroom/platforms/`; the recommendation engine, data model, and UI consume only the adapter's normalized outputs and must contain **zero Sleeper-specific logic**. v1 implements exactly one adapter: Sleeper.

Interface (minimum):
- `resolve_user(identifier) → User`
- `list_leagues(user, season) → [League]` (normalized: scoring preset, roster slots, team count, league_type)
- `list_drafts(league) → [Draft]` (normalized: type, status, order, settings)
- `get_picks(draft) → [Pick]` (normalized: pick_no, platform_player_id, roster)
- `get_players() → [Player]` (normalized universe; adapter owns caching policy)
- `poll_interval` and rate-limit config per adapter

Normalization rule: internal canonical player identity is the app's own `player_id`; each adapter maintains a `platform_player_id ↔ player_id` mapping (for Sleeper this is near-1:1; for a future ESPN adapter it reuses the same matching machinery from Section 4). The `leagues` table carries a `platform` column.

### Sleeper adapter (v1)
Base URL: `https://api.sleeper.app/v1` — public, read-only, no auth. Rate guidance: stay well under 1000 requests/minute. Verify endpoint shapes against https://docs.sleeper.com/ during implementation.

### Endpoints used
| Purpose | Endpoint | Cadence |
|---|---|---|
| Resolve user | `GET /user/<username>` | On setup |
| List leagues | `GET /user/<user_id>/leagues/nfl/<season>` | On setup / refresh |
| League settings | `GET /league/<league_id>` | On league add + daily |
| League users/rosters | `GET /league/<league_id>/users`, `/rosters` | On league add + daily |
| Drafts for league | `GET /league/<league_id>/drafts` | Pre-draft |
| Draft metadata | `GET /draft/<draft_id>` | On draft open (contains draft order, roster slot settings, pick timer, type: snake/auction/linear) |
| **Live picks** | `GET /draft/<draft_id>/picks` | **Poll every 2s while draft status is active** |
| Traded picks | `GET /draft/<draft_id>/traded_picks` | On draft open + every 60s |
| Player universe | `GET /players/nfl` | **Once per day, cached** — response is ~5MB; never call per-lookup |
| Trending adds | `GET /players/nfl/trending/add` | Optional, hourly |

### Live draft sync loop
1. On "Start Draft Session," fetch draft metadata and full pick list; seed local state.
2. Poll `/picks` every 2 seconds. Diff by `pick_no` against local state.
3. For each new pick: mark player drafted, attribute to roster, recompute recommendations, push SSE event to UI.
4. Detect "on the clock" status from pick count + draft order + snake logic (handle traded picks and third-round reversal if the draft settings indicate it).
5. If polling fails (network blip), back off exponentially to 10s max and surface a visible "STALE DATA" banner in the UI. Never silently show stale state during a draft.
6. When my pick is ≤ 2 away, flash a prominent alert state in the UI.

### Player ID mapping — this is the hard, boring, critical part
Sleeper player IDs (e.g., `"4034"`, `"CAR"` for DEFs) must map to names in ranking CSVs from other sites. Build a `player_map` table with:
- Canonical key: Sleeper `player_id`
- Match fields: full name (normalized: lowercase, strip punctuation/suffixes like Jr./III), team, position
- Matching strategy: exact normalized name+position → name+team → fuzzy match (rapidfuzz, threshold ~90) → **unmatched queue surfaced in UI for manual resolution**
- Persist manual resolutions so they never have to be repeated
- Known landmines: multiple players with identical names, team abbreviation differences between sites (JAX/JAC, WAS/WSH), rookies missing from stale sources, D/ST naming conventions varying wildly per site

Do not ship the ingestion pipeline without the manual-resolution UI. Silent mismatches mean the app recommends a player who was drafted 3 rounds ago, and the tool is worse than useless.

---

## 4. Ingestion Pipeline

### Sources (v1)
| Source | Mechanism | Notes |
|---|---|---|
| FantasyPros | CSV export (user downloads cheat sheet / ECR export) | Also supports scoring-format variants (STD/HALF/PPR) |
| ESPN | CSV or pasted rankings | Public rankings pages; a paste-parser is acceptable |
| 4for4 | Subscriber CSV export | User exports from their account |
| Fantasy Headliners | Subscriber content: **PDF documents**, pasted text/notes, or CSV | Rankings, prose notes, and **structured flags** (see below) |
| Generic CSV | Column-mapping wizard | Any source with player, position, and a rank or projection column |
| Generic PDF | PDF extraction pipeline (see below) | Text-based PDFs only; scanned/image PDFs are out of scope for v1 |
| ADP | FantasyPros ADP export or Sleeper-format ADP CSV | Drives survival probability (Section 5) |

### PDF ingestion
Subscriber documentation (Fantasy Headliners especially) arrives as PDF. The wizard must handle it:
1. **Extraction:** use `pdfplumber` to pull tables and text. Tables → candidate rows for the column-mapping wizard; prose → candidate per-player notes (detect player names in text via the player map and offer to attach paragraphs as notes).
2. **Mandatory preview step:** show the extracted table/text side-by-side with the raw page render before anything is committed. PDF table extraction is inherently flaky — the user confirms or corrects the parse before it touches the board. Never silently ingest a PDF.
3. **Layout presets:** once a Fantasy Headliners PDF layout has been mapped once, save the extraction preset (table regions, column meanings, flag columns) so subsequent documents in the same layout import near-zero-click.
4. **Fallback:** if a PDF parses badly, the user can copy-paste its content into the text/paste parser instead. Do not sink days into perfecting extraction for one stubborn layout.

### Fantasy Headliners flags (tiebreaker data)
FH provides per-player qualitative flags — e.g., red zone targets, RB confidence score, and similar signal markers. These are first-class data, not notes:
- Stored in a dedicated `player_flags` table (Section 7): flag name, value (boolean or numeric score), source, imported_at.
- Flag schema is **user-extensible**: the import wizard lets the user declare a new flag type on the fly when mapping a column ("this column is a flag called `rb_confidence`, numeric").
- Flags are consumed by the recommendation engine's **tiebreaker layer** (Section 5.4) and rendered as compact badges on player cards in the Draft Room.
- Flags do NOT feed the composite score directly by default (they'd get diluted); their job is breaking ties between comparably valued players. A settings toggle can optionally give a flag a small score weight if the user wants it.

### Import flow
1. User drops a file (CSV or PDF) or pastes text into the Import screen and tags it with: source name, **scoring format (required — Standard / Half-PPR / Full PPR; no untagged imports)**, date, league-type applicability (redraft / dynasty).
2. Column-mapping wizard with saved presets per source (second import from FantasyPros should be zero-click).
3. Rows matched to Sleeper player IDs via the player map; unmatched rows go to the resolution queue.
4. Stored as an immutable `ranking_set`. Re-importing a source creates a new versioned set; the engine always uses the most recent set per source unless pinned.

### User preference layer (highest priority input)
A `preferences` store editable in the UI:
- **My Guys:** players to bump (configurable boost, expressed in tiers or rank positions)
- **Do Not Draft:** hard exclusions (never recommended, rendered struck-through on the board)
- **Tier overrides:** move a player to a specific tier
- **Exposure notes:** free-text notes per player, displayed on their card during the draft
- **Strategy toggles per league:** e.g., "Zero RB," "early-round TE premium," "punt QB until round 8," "prioritize rookies (dynasty)" — implemented as weighting profiles the engine consumes (Section 5)

---

## 5. Recommendation Engine

This is the core value. Build it as a pure, unit-testable module: `(draft_state, ranking_data, preferences, league_settings) → ranked recommendations with reasons`.

### 5.1 Consensus value
- Normalize each ranking set to a 0–100 value scale within position and overall (rank → percentile → value curve; don't average raw ranks, which compresses top-end gaps).
- Weighted blend across sources; source weights configurable in settings (default equal). Fantasy Headliners and user overrides sit on top of the blend, not inside it.
- Compute **tiers** per position via gap detection in the blended value curve (a drop exceeding a configurable threshold starts a new tier). Tiers are the primary mental model in the UI.

### 5.2 League-adjusted value (VBD)
- Pull scoring settings and roster slots from Sleeper league config.
- Compute replacement level per position from league size × starter slots (including FLEX/SUPERFLEX allocation — Superflex must materially elevate QB value automatically).
- Value Over Replacement = blended projected value − replacement baseline. This is the base score.

### 5.3 Live adjustments (recomputed on every pick)
- **Roster need multiplier:** diminishing returns per slot filled; hard caps (don't recommend a 4th QB in a 1-QB league); flex-aware.
- **Positional scarcity / tier cliff:** if I'm at the last player of a tier at a position and the next tier is a big drop, boost urgency.
- **Run detection:** if ≥3 of the last 5 picks are one position, flag it and raise urgency for that position.
- **Survival probability:** using ADP with a variance model (assume ADP is roughly normal with position-dependent σ), estimate P(player available at my next pick). The headline recommendation logic: prefer the player *least likely* to survive among players of comparable value. Show "% chance he's back" on every card.
### 5.4 Tiebreaker layer (Fantasy Headliners flags)
When two or more candidates' composite scores fall within a configurable epsilon (default 2%), they are considered **tied on value** and FH flags break the tie:
- Each flag type has a user-assignable tiebreak priority (e.g., `red_zone_targets` > `rb_confidence`). Boolean flags: has-it beats doesn't. Numeric flags: higher wins.
- The reason string must state it explicitly: "Tied on value with J. Example — edge: FH red-zone-target flag."
- If no flags differentiate, fall back to survival probability (take the one less likely to come back).

### 5.5 Output contract
Top N (default 8) recommendations, each with:
- Composite score and tier
- Flag badges (compact icons/chips for any FH flags on the player)
- **Plain-English reasons** (max 3 bullets): e.g., "Last tier-2 RB; next RB tier is a 14% value drop," "12% chance he survives to your pick 3.08," "Your note: 'target — new OC, elite target share.'"
- Positional need summary strip (what my roster still requires vs. rounds remaining)

The reasons are non-negotiable. A number with no explanation gets ignored at pick 6 of a 90-second clock.

---

## 6. UI Requirements

Single-page app, optimized for a laptop screen sitting next to the Sleeper draft room. Dark theme default. Everything reachable in ≤1 click during a live draft.

### Visual direction
Reference aesthetic: modern dark finance-dashboard style (think Google Finance dark mode) — near-black background, thin rounded panel borders, generous whitespace, muted grays for secondary text, restrained accent colors (green/red for good/bad signals, one blue accent for interactive elements), small sparkline-style micro-charts where trend data exists (e.g., a player's rank movement across ranking-set versions). Clean, quiet, data-forward. No gradients-everywhere dashboard clutter.

### Screens
1. **Draft Room (primary):**
   - Left: Best Available list (recommendation-ordered), with position filter chips, tier bands as horizontal separators, drafted players removed live
   - Center: recommendation cards (top 3 large, with reasons), pick clock context ("You pick in 4 — ~7 min")
   - Right: My Roster (slot-by-slot, empty slots prominent) + positional needs bar
   - Top strip: last 10 picks ticker with position-colored chips (run detection visible at a glance)
   - **Queue:** user can pin players to a personal queue; queued players get survival-probability warnings ("Queued: T. Example — 18% chance he makes it back. Take him or lose him.")
2. **Prep / Big Board:** full blended board, editable pre-draft (drag tier boundaries, toggle My Guys / DND, attach notes)
3. **Import:** file drop, column mapping, unmatched-player resolution queue
4. **Leagues:** connected leagues list, settings snapshot, draft picker (handles multiple drafts per league — dynasty leagues have several). Per-league settings are deliberately **basic**: team count, roster slots, and a single scoring preset picker — **Standard / Half-PPR / Full PPR** — nothing more granular. Defaults auto-populate from the Sleeper league config on connect; the picker is a manual override, not a scoring editor. The selected preset determines which ranking sets (by scoring-format tag) the engine uses for that league. Primary format across the user's leagues: **Half-PPR**.
5. **Settings (global):** source weights, strategy profiles, flag tiebreak priorities, poll interval, tier-gap threshold

### Behavior
- Mock-draft compatible: point the app at any Sleeper mock draft ID for dry runs. **This is the acceptance test for the whole system.**
- Resume-safe: restart mid-draft → full resync from Sleeper within one poll cycle.
- All recommendation math must complete in <200ms per pick on a normal laptop; precompute what you can.

---

## 7. Data Model (SQLite, core tables)

- `leagues` (league_id, **platform** default 'sleeper', name, settings JSON, scoring JSON, league_type: redraft|dynasty)
- `drafts` (draft_id, league_id, type, status, settings JSON, draft_order JSON)
- `players` (sleeper_id PK, name, name_normalized, position, team, age, status, metadata JSON) — refreshed daily from `/players/nfl`
- `player_aliases` (alias_normalized, sleeper_id, source) — manual + learned matches
- `ranking_sets` (id, source, scoring_format, league_type, imported_at, active)
- `rankings` (ranking_set_id, sleeper_id, rank, projection, tier, position_rank, notes)
- `player_flags` (sleeper_id, flag_name, value_bool nullable, value_num nullable, source, ranking_set_id, imported_at) — FH flags and any user-defined flag types
- `flag_types` (flag_name PK, value_kind: bool|numeric, tiebreak_priority, optional_score_weight default 0)
- `import_presets` (source, layout fingerprint, column/flag mappings JSON, pdf_extraction_config JSON nullable)
- `preferences` (league_id nullable, sleeper_id, type: my_guy|dnd|tier_override|note, value)
- `draft_picks` (draft_id, pick_no, sleeper_id, roster_slot, picked_by, ts) — mirror of Sleeper truth
- `queue` (draft_id, sleeper_id, order)
- `strategy_profiles` (id, name, weights JSON)

---

## 8. Build Phases

**Phase 1 — Repo + Sleeper plumbing (foundation):**
**First action: create and initialize the GitHub repo per Section 10.1.** Then: player universe sync, league/draft fetch, live pick polling with diff + SSE, resume-safe state. Deliverable: a terminal/log view proving picks appear within 2–3s of being made in a Sleeper mock draft.

**Phase 2 — Ingestion + player matching:**
CSV importers, column-mapping wizard, normalization, fuzzy matching, manual resolution queue, versioned ranking sets, **PDF extraction pipeline with preview**, **flag ingestion with user-defined flag types**. Deliverable: import FantasyPros CSV + one Fantasy Headliners PDF with flags, 100% of players resolved, flags visible in the database.

**Phase 3 — Recommendation engine:**
Consensus blend, tiers, VBD from league settings, live adjustments, survival probability, **flag tiebreaker layer**, reasons generator. Fully unit-tested against fixture drafts (record a real mock draft's pick sequence as a test fixture).

**Phase 4 — Draft Room UI:**
Full React interface per Section 6, including flag badges on player cards. Deliverable: complete a live Sleeper mock draft end-to-end using only the app for decisions.

**Phase 5 — Multi-league + polish:**
Strategy profiles, multi-league management (including the dynasty league's in-season visibility), settings, import preset refinement. (Dynasty draft modes and age-curve valuation: deferred to the 2027 version.)

Each phase ends with working, demonstrable software. Do not start Phase 4 UI polish while Phase 2 matching is unreliable — matching quality is the app.

---

## 9. Testing & Acceptance

- Unit tests: matching logic (name-collision fixtures), snake order math (incl. traded picks, 3rd-round reversal), VBD under Standard/Half-PPR/Full-PPR presets, survival probability sanity checks, tiebreaker layer (flag priority ordering, epsilon boundary cases)
- Integration test: replay a recorded mock draft pick-by-pick; assert recommendations never include drafted players and recompute in <200ms
- PDF ingestion test: fixture PDFs (one clean table, one messy layout) run through extraction + preview; assert flags land in `player_flags` correctly
- **Acceptance:** two full Sleeper mock drafts (both **Half-PPR**, matching the real leagues) completed using the app, zero unmatched players, zero stale-state incidents

---

## 10. Repository & Version Control

### 10.1 Repo creation (first task, before any code)
**Starting condition:** the user has already created a local folder named **`fantasy-war-room`** containing this design document, and Claude Code is launched from inside it. That folder IS the repository and the working location for the entire effort — do not create a separate directory, do not clone into a subfolder, do not relocate the work.

Claude Code's first actions in Phase 1, executed from the folder root:
1. Move/confirm this design document at `docs/DESIGN.md` (if the user dropped it at the root, move it into `docs/`).
2. `git init` in the folder root, then create the `.gitignore` (see 10.3) **before** any other files, so nothing sensitive is ever staged.
3. Scaffold the directory layout in 10.4 and a `CLAUDE.md` at the root (project rules: follow `docs/DESIGN.md`, naming standard 10.2, one phase at a time, never commit `data/` or subscriber content, all platform code behind the PlatformAdapter interface).
4. Create the private GitHub remote from the existing folder: `gh repo create fantasy-war-room --private --source=. --remote=origin --push` (or guide the user through manual creation + `git remote add` if `gh` auth isn't set up — do not proceed unauthenticated and silently skip this).
5. Initial commit: `phase-0: repo scaffold + design doc`. Confirm the remote push succeeded before writing feature code.

### 10.2 Naming standard (nomenclature — use consistently everywhere)
| Thing | Name | Rule |
|---|---|---|
| GitHub repo & local folder | `fantasy-war-room` | kebab-case; the user's local folder of this name is the repo root and sole working location; **platform-agnostic** — no vendor name, no year. Sleeper is the first supported platform, not the identity of the app. Seasons are tags |
| Python package | `warroom` | single word, lowercase; entry point is `python -m warroom` |
| Platform adapters | `warroom/platforms/<vendor>/` | e.g., `warroom/platforms/sleeper/`; each implements the `PlatformAdapter` interface (Section 3) |
| Frontend app | `warroom-ui` | lives at `/frontend` |
| App display name | **War Room** | what the UI header says |
| SQLite file | `warroom.db` | gitignored |
| Env var prefix | `WARROOM_` | e.g., `WARROOM_PORT`, `WARROOM_POLL_INTERVAL` |
| Season versioning | git tags `2026.x`, releases per phase | 2027 edition = new major tag series in the same repo, not a new repo |

(This supersedes the `draftcompanion` placeholder used earlier in this document — `warroom` is the canonical package name.)

### 10.3 .gitignore requirements
Must exclude: the SQLite database (`*.db`), everything under `data/` (imported CSVs/PDFs), any Fantasy Headliners or 4for4 subscriber files, `.env`, `node_modules/`, Python caches/venvs. Subscriber content is paid IP — it never gets committed, even to a private repo. Commit code and structure, not data. Test fixtures must be synthetic or sanitized.

### 10.4 Repo layout (scaffolded inside the user's existing `fantasy-war-room` folder)
- `CLAUDE.md` — project rules for Claude Code sessions (root level)
- `/backend` — FastAPI app (`warroom` package)
- `/frontend` — React/Vite (`warroom-ui`)
- `/docs` — `DESIGN.md` (this document, provided by the user) + `LEAGUE_VARIABLES.md` (per-league specifics the user maintains for future reference: league IDs, scoring preset, team count, draft slot, notes)
- `/tests` — unit + integration tests
- `/fixtures` — recorded mock drafts, synthetic sample CSVs, sanitized sample PDFs
- `/data` — local-only runtime data (gitignored, created on first run)

### 10.5 Workflow
- Conventional, phase-tagged commits (e.g., `phase-1: pick polling + SSE`); feature branches per phase merged to `main` when the phase's deliverable passes.
- Tag a release at the end of each phase (`2026.1` through `2026.5`) so any phase can be rolled back to cleanly.
- README must include one-command run instructions and a "draft day checklist" (refresh player universe, import latest rankings, confirm league scoring preset, run one mock).

---

## 11. Resolved Decisions (from design review)

1. **Draft format:** snake only, all leagues. No auction module.
2. **Keepers:** none that affect drafts. No keeper handling.
3. **Dynasty:** rookie draft for this season already complete. This version provides league tracking only; dynasty draft support ships in the 2027 edition.
4. **Scoring:** simple preset model (Standard / Half-PPR / Full PPR) + team count + roster slots. Primary format is Half-PPR. Per-league specifics get set in-app and recorded in `docs/LEAGUE_VARIABLES.md`.
5. **Timeline:** primary draft is the first weekend of September 2026. Target: Phases 1–4 complete and one full mock draft passed by **mid-August**, leaving two-plus weeks for real mock reps and ranking refreshes.
