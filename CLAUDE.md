# CLAUDE.md — Neuroverse Discord Bot

This file exists so a future session (with none of this conversation's context)
can pick this project up quickly. Update it as new important context is learned —
don't let it go stale.

## What this is

A Discord bot (`TittyBot#0428`) for an 8-team Madden Mobile league system.
Teams/leagues: NP (NeuroPerverse), ND (NeuroDiverse), NI (NeuroInverse),
NA (NeuroAdverse), NR (NeuroReverse), NC (NeuroChaos), NT (NeuroTraverse),
NX (NeuroChristians).

**Stack:** discord.py 2.7+, SQLite via `aiosqlite`, hosted on bot-hosting.net
(Pterodactyl panel). Fully localized in 5 languages (en, es, fr, pt, de).

**Files:**
- `optimized_bot.py` — main bot, most slash commands
- `db.py` — all database access, schema migrations
- `i18n.py` — all user-facing strings, all 5 languages, manual page text
- `siege.py` — the Siege game mode
- `ladder_flow.py` — the `/ladder` builder flow (screenshot extraction or manual)
- `agent.py` — Claude Haiku vision extraction for `/ladder` screenshots
- `sheet_image.py` — PIL-based PNG table rendering (`/rank`, `/scores`, `/show_ladder`)
- `tournament.py`, `status.py`, `newday.py` — smaller, mostly-stable feature areas
- `tests.py` — full discord.py stub + ~290 tests, no real Discord/network needed
- `db_schema.sql`, `logger_config.py` — supporting files, rarely touched

## Critical: how deployment actually works (NO shell access)

The user has **no SSH/shell access** to the host — only Pterodactyl's File
Manager (upload/download files) and a restart button. This shapes everything:

- All schema and data migrations MUST run automatically from code
  (`db.py`'s `_migrate_schema()`, called on every startup). There is no other
  way to apply a DB change. Every migration must be idempotent (safe to rerun
  forever) since it runs on literally every restart.
- **The database runs in WAL mode.** Uploading a new `neuroverse.db` while the
  bot is still running causes a real race condition — the live process is
  still writing to the file at the same time the upload replaces it. This
  produces exactly the failure mode we hit repeatedly early on: corruption
  (`disk image is malformed`) and/or silent partial reverts where only the
  most-recently-written data survives. **Confirmed root cause, not a guess.**
  Correct sequence: **fully stop the bot → delete any leftover
  `.db-wal`/`.db-shm` → upload the new `.db` → start the bot.**
- When diagnosing "the file I delivered doesn't match what's live," always
  ask for a fresh export **including `.db-wal` and `.db-shm`**, not just the
  bare `.db` — a plain file can be missing transactions still sitting in the
  WAL. Merge with `PRAGMA wal_checkpoint(FULL)` before trusting it.
- An automatic backup system exists specifically because of a real incident
  where live data (a matchup + a player registration) was permanently lost to
  an accidental overwrite with no backup available. `db.backup_database()`
  runs on every startup and once daily, using SQLite's own online backup API
  (not a raw file copy — WAL mode means a raw copy can miss unflushed data).
  Backups land in a local `backups/` folder, pruned after 14 days.

## Database gotchas (each one cost real time to find — don't relearn these)

- **A game's division/tier (E1/E2/E3/HOF/Gold-) lives on `matchup_day.event_type`
  for that (team_id, game_date) — NOT reliably on the individual
  `game_scores.event_type` for that score.** `/score` has no tier parameter
  at all; the tier for a given day comes from whatever matchup was recorded
  via `/ladder` or `/matchup`, which writes to `matchup_day`, not
  `game_scores`. `game_scores.event_type` still exists as a column and
  still gets read/written by the historical-backfill/correction-preserving
  logic in `update_player_score`, but nothing computing a division average
  should filter or select on it directly — it's just not reliably populated
  for real day-to-day scoring. This caused `/stats`' per-division averages
  (and `/avg`'s HOF/E1/E2/E3/Gold- option, and `/history`'s per-row "Evt"
  column) to silently show nothing for leagues that had, in reality, played
  those divisions plenty of times. Fixed everywhere by joining
  `game_scores` to `matchup_day` on `(team_id, game_date)` instead of
  filtering `game_scores.event_type` directly — see `get_player_stats`'s
  `event_avg()`, `get_player_avg()`, and `/history`'s query in
  `optimized_bot.py`. `get_matchup_summary()` (currently dead code, no
  live command calls it) had the same issue and was fixed for consistency
  even though nothing currently exercises it.

**`game_scores`** (one row per player per day):
- Uniqueness is a **separate named index** `uq_player_date`, not an inline
  table constraint — it used to be `(player_id, game_date, event_type)`,
  which was a real, live bug: `/score` never passes `event_type` (always
  `None`), so once a row had a real `event_type` (e.g. from a backfill), a
  plain correction couldn't match it via `UPDATE ... WHERE event_type=?` and
  silently inserted a **duplicate row** instead, inflating team totals. Fixed:
  index is now `(player_id, game_date)` only, and every upsert function
  explicitly `SELECT`s for an existing row first, then updates *that row by
  its own id* or inserts — never relies on an UPDATE's WHERE clause to also
  serve as the existence check.
- Each row's `team_id` reflects whichever team the player was actually on
  **at the time** — not their current team. A transferred player's old scores
  must stay attributed to their old team. Any query filtering `p.team_id`
  (the player's *current* team, via a join) instead of `gs.team_id` (the
  row's own historical team) will silently drop that player's history the
  moment they transfer. **Always filter on `gs.team_id` for historical
  queries, never `p.team_id`.** This exact bug hit `/scores` and
  `/matchup`'s running total independently — check any new query the same way.
  It also hit `get_player_stats()` itself in the opposite direction: every
  `game_scores` query inside it filtered only on `player_id`, with no
  `team_id` filter at all, so a transferred player's *entire history from
  every league they've ever played for* fed into their current team's stats
  — e.g. a league that has never played a HOF match could still show a HOF
  average for a player who played HOF while on a different team before
  transferring in. Fixed by adding `AND team_id=?` to every `game_scores`
  query in `get_player_stats()`, scoping it to what the player did while
  representing that specific team_id. This affects `/rank`, `/player`,
  `/stats`, and every `/legacy` equivalent, since they all share this one function.
- `score` is `NULL` for an excused entry (`is_excused=1`) — not `0`. A missed/
  forfeited drive (`is_forfeit=1`) genuinely *is* `0`. Don't conflate them.
- A genuine 0-point game is a **real, countable entry**. Never use
  `score > 0` as a stand-in for "is this a real row" — only `is_forfeit`/
  `is_excused` should exclude a row from stats. (This was a real bug affecting
  games-played count, points total, and every rolling average.)
- `fumbles` is directly logged per-entry, never derived from the score value.

**`players`**:
- `ign` = bot nickname (what most commands key on). `real_ign` = actual
  in-game name. Different purposes, different commands: `/nick` changes
  `ign` only, `/ign` changes `real_ign` only. **`real_ign` is not unique** —
  multiple players can legitimately share one, so anything that looks a
  player up for renaming must key on a unique player id (via autocomplete),
  never on `real_ign` text alone.
- Every player's `real_ign` should be non-NULL (auto-backfilled from `ign`
  if missing, via migration, and defaulted at registration time).
- `fourth_downs`/`fourth_down_convs` columns here are **dead** — real per-game
  tracking lives in `game_scores`. Migration drops these columns.

**`defense_scores`** (`/dscore`, per-drive defense tracking):
- Drive outcomes (`"0"`-`"8"` or `F`/`I`/`S`) are slash-command params on
  `/dscore` itself, not modal fields — known upfront, before any modal opens.
- Each drive tracks its own OVR faced; turnover drives additionally track
  down/distance/play/forced-by. `avg_off_ovr_faced` is **computed** (average
  of whichever per-drive OVRs were actually entered, nulls excluded) — never
  directly input.
- Same "select first, then update by id or insert" upsert pattern as above.

**`matchup_day` vs `matchup_ladder` vs `ladder_matchups`** — three different
things, easy to confuse:
- `ladder_matchups`: the **live, current** working ladder, no date column —
  fully overwritten every time a new ladder is built.
- `matchup_ladder`: the **permanent, per-date archive** (unique on
  `team_id, game_date, slot`).
- `matchup_day`: one row per team per day — opponent name, division
  (`event_type`), `our_rank`, final score/outcome.
- `set_matchup()` upserts `matchup_day` **and** snapshots `ladder_matchups` →
  `matchup_ladder`. `set_matchup_info()` is the narrower version —
  `matchup_day` only, no snapshot. `ladder_flow.py`'s `save_ladder_to_db` uses
  `set_matchup_info` specifically, since it already writes ladder slot data
  directly; calling the full `set_matchup` there would trigger a redundant,
  potentially conflicting snapshot.
- Upserts to `matchup_day` use `COALESCE(new, existing)` per field — a field
  left `None` preserves whatever's already there rather than wiping it, since
  callers (e.g. a partial screenshot extraction) may only have some of it.

## Discord platform facts (confirmed via direct research, not assumption)

- **`/siegescore` used to be purely additive** — `log_siege_score()` did a
  plain `INSERT` every time, so re-scoring the same player against the same
  node created a second row and `get_siege_node_totals()`'s `SUM(points)`
  added both together. Changed to replace: an existing `(node_id, player_id)`
  row is now found and updated in place (drives/points/created_at all
  overwritten) rather than a new row inserted, using the same explicit
  check-then-act pattern as `update_player_score`/`update_player_dscore`
  (`SELECT` for an existing row first, `UPDATE ... WHERE id=?` if found,
  `INSERT` otherwise — never rely on a WHERE clause alone to double as the
  existence check). Enforced with a real `uq_siege_node_player` unique index,
  not just application logic. Different players scoring the same node still
  both count toward its total as separate rows — this only collapses repeat
  entries from the *same* player against the *same* node. A migration merges
  any duplicates the old additive behavior already created in production
  (keeping the newest entry, same reasoning as the `game_scores` duplicate
  merge described above) before the unique index is added.

- **Autocomplete callbacks that search across ALL players globally (like
  `player_autocomplete`: no `team_id` filter, no `ORDER BY`, hard
  `LIMIT 25`) can silently omit a specific player** once the total active
  pool crosses ~25 for a given prefix — with no sort order, which 25 survive
  the cutoff isn't even predictable. This bit `/siegescore` specifically: it
  already has its own `league` parameter, so there's no reason for its
  `player` field to search all ~140+ active players across every league
  instead of just that league's own ~15-25. Fixed with a new
  `league_player_autocomplete()` that reads the already-selected `league`
  value via `interaction.namespace.league` and filters by
  `team_id=? AND status='A'` — the same scoping `get_team_stats()` uses for
  the ladder roster. A transferred player is now always findable in their
  *current* league's own (much smaller) list, immediately. Any other command
  that has its own `league`/`team_id` parameter *and* a separate `player`
  field should use this same scoped autocomplete, not the global one —
  the global one is fine for commands like `/score`/`/player`/`/history`
  that only take `player` (no league to scope by) and expect the admin to
  type a specific, already-known name.

- **A modal can never be opened in direct response to another modal's
  submission** — only from a slash command interaction or a component
  (button/select) interaction. This is a hard Discord API restriction, not a
  discord.py quirk. Any multi-step "modal, then another modal" flow must
  actually go: modal submit → bot sends a message with a **button** →
  clicking that button (a valid component interaction) opens the next modal.
  Learned this the hard way after building a direct modal-chain that failed
  with a generic "something went wrong" every time — see `/dscore`'s
  turnover-detail flow (`DscoreContinueView`) for the correct pattern.
- `discord.ui.Label` (replacing the deprecated `TextInput.label`) has a
  **45-character limit** on its `text`. Check translated text in all 5
  languages against this whenever adding a field, not just English (German
  usually runs longest).
- A modal has a **hard max of 5 top-level components**.
- There's no way to customize a modal's own Submit button label — it's fixed
  by Discord's client, not something the bot controls. Any "click to
  continue" UX has to be the bot's own separate button shown *after*
  submission, never the modal's built-in submit button.
- Migration pattern used everywhere in this codebase for
  `TextInput.label` → `discord.ui.Label`: construct each field fresh inside
  `__init__` with the correct, already-translated label text from the start
  — never mutate a label after construction (that mutability was never
  confirmed for the new component). Keep a direct instance attribute for each
  `TextInput` (e.g. `self.score_val = TextInput(...)`) so `on_submit` keeps
  reading `.value` directly; don't route through `label.component.value`.

## i18n conventions

- 5 languages, always: `en`, `es`, `fr`, `pt`, `de`. Every user-facing string
  goes through `i18n.t(key, lang, **kwargs)`.
- `i18n.resolve_lang(interaction)` gets the caller's language.
- Always check new Label/title/button text against Discord's character
  limits in *all 5* languages before shipping, not just English.

## Testing conventions (`tests.py`)

- Full discord.py stub, zero real network/Discord dependency.
- `@tree.command`-wrapped functions can't be called directly (the decorator
  mangles them) — test the underlying Modal/View classes and helper
  functions directly instead.
- **`View`, `Button`, `Select`, and `Modal` are all literally the same stub
  class (`_BaseUI`)** — `isinstance(child, Button)` and
  `isinstance(child, Select)` are therefore always both true for any child,
  useless for telling them apart. To find a specific child in `view.children`
  in a test, check for a distinguishing constructor kwarg instead — e.g.
  `getattr(c, 'options', None) is not None` for a select,
  `"Confirm" in (getattr(c, 'label', None) or "")` for a specific button.
  Also: an attribute that was never passed as a kwarg doesn't exist on the
  stub at all (accessing it raises `AttributeError`, it does not return
  `None`) — always use `getattr(c, 'attr', None)` when checking an arbitrary
  child from a mixed list, never `c.attr` directly.
- `_label_text_for(modal, field)` helper: finds a field's visible label by
  searching `modal.children` for the `Label` wrapping it (fields no longer
  carry `.label` directly post-migration).
- The stub's fake DB cursor must mirror real aiosqlite's actual dual nature —
  a call like `_db.execute(...)` needs to support *both* direct `await` and
  `async with`. Getting this wrong once let a migration bug through the test
  suite silently (the test technically "passed" without truly exercising the
  code). If a migration test feels too easy, double-check the stub isn't
  swallowing an exception.
- **Always run the full suite after every change**, not just new tests —
  unrelated regressions have been caught this way multiple times.
- **Watch which test class a new test lands in.** `unittest.TestCase`
  subclasses (e.g. `TestScoresGrid`) are sync-only — an `async def test_...`
  method placed there either errors loudly (missing event loop) or, worse,
  silently "passes" without ever actually running its body. Async tests
  belong in an `IsolatedAsyncioTestCase` subclass (`TestDB`, `TestLadderFlow`,
  `TestSiege`, etc.) — pick whichever is topically closest to what's being tested.

## Ladder screenshot extraction: manual player-name matching

`/ladder`'s screenshot extraction matches each detected "our team" player to
a known league member by **exact** `real_ign` string match
(`db.get_player_by_real_ign`). Vision extraction is imperfect — a name can
be misread (mixed-up characters, a garbled special character), and when that
happens the match fails even though the player is genuinely in the league.
This used to just silently drop that player's OVR update and show a text
warning listing the unmatched name(s), with no way to recover other than
manually running `/ovr` afterward.

Fixed with `LadderPlayerMatchView` (in `optimized_bot.py`, right before the
`/ladder` command): when one or more "our" players can't be exact-matched,
the admin is shown a select menu per unmatched name (populated with the
league's active roster, minus whoever's already been auto-matched, plus a
"skip — not actually in this league" option) and a Confirm/Skip All button
pair. Confirming applies the OVR update to whichever player was manually
chosen — via `_apply_extracted_ovr()`, the same update-and-notify logic the
automatic exact-match path uses, so a manual match behaves identically to an
automatic one, not a second, divergent code path. Then the flow continues
into `start_ladder_flow()` exactly as it would have without any mismatches.

Capped at 4 unmatched names *per screen* (`LadderPlayerMatchView.MAX_ENTRIES`) —
Discord allows at most 5 action rows per view and each select needs its own
row, leaving one row for the two buttons. Any names beyond 4 are **not**
dropped: confirming or skipping a batch chains straight into a follow-up
view of the same kind for the remaining names (`batch_num`/`total_entries`
track progress across batches), and only once nothing remains does the flow
actually continue into `start_ladder_flow()`. An earlier version of this
capped at 4 and just warned about anything past that with a "try `/ovr`
manually" message — that was a real bug, not an acceptable limitation, since
it silently abandoned exactly the players this feature exists to help with.
Caught via direct user report after a 6-name day; fixed by chaining instead
of dropping, and there's a test that reverts the chaining and confirms it
fails the same way the original bug did, not just that the new code works.

**A second, more serious bug in this same feature, also caught by direct
user report (with a screenshot showing the exact failure):** once every
batch was resolved, the handoff to `start_ladder_flow()` used a hand-built
fake stand-in object instead of the real interaction, to satisfy
`start_ladder_flow`'s `interaction.response.is_done()` check. That fake
object's `response` attribute was set to the `followup` webhook itself —
which has no `is_done()` method — so this crashed with an `AttributeError`
every single time, right after the OVR-update notification (sent via the
*real* interaction's followup, earlier in the same function) had already
gone out. That's exactly why the OVR-update message would appear but the
ladder builder never followed it. Separately, `_on_confirm` also deferred
the interaction *after* doing per-entry DB work instead of before, risking
the 3-second acknowledgment window expiring on a slow batch (Discord's own
"didn't respond in time" on the button itself). Fixed both: defer
immediately as the first line, and pass the real interaction straight into
`start_ladder_flow` (once deferred, `is_done()` on it correctly returns
`True` on its own — no proxy object needed at all).

**Testing lesson from this one:** the original tests for this feature all
passed against the broken code, because they used `MagicMock()` for
`interaction.followup` — a `MagicMock` auto-creates *any* attribute you
access, including a fake `is_done()` that returns a truthy mock, so it never
reproduced the real `AttributeError` a genuine `discord.Webhook` object
would raise. Catching this needed a hand-written stub that only defines the
methods the real object actually has, so accessing something missing
genuinely raises — an all-permissive Mock hides exactly this class of bug.

Deliberately did **not** add fuzzy/approximate matching as a first line of
defense here — a wrong automatic match (two similarly-named players getting
swapped) would be worse than the current "ask a human" fallback, and the
explicit ask was for a manual-match capability, not a smarter automatic one.

## Known historical data facts (context for future data questions)

- NP's `event_type`: confirmed `E2` for 2026-07-13 through 07-19, `E1` for
  07-20 through 07-26 (per-team, per-week; divisions are not shared
  league-wide). Other teams have older, more scattered `event_type` gaps that
  were *not* addressed — that would need separate, team-specific research.
- The original Excel reconciliation (start of this project) only ever
  extracted individual player scores + `event_type` from the spreadsheet's
  per-date grid. It missed matchup-level columns sitting in the exact same
  grid (Opponent Name, Division, Opponent/Our Rank, Outcome) — discovered
  and backfilled much later (~1,200 `matchup_day` rows across the whole
  league, from data that had been sitting there the entire time).
- A real production incident: NP's 7/22 matchup + a player (PB619) were
  genuinely lost to an accidental file overwrite on the hosting side with no
  backup available (not a bot bug) — recovered via user-provided game
  screenshots. This is the direct reason the automatic backup system exists.

## MySQL-era leftovers cleaned up (Sept 2026)

This project's real lineage is Google Sheets (gspread) → a brief MySQL
attempt → the current, actual architecture: SQLite via `db.py`. Two files
were confirmed to be dead weight from the MySQL step and were deleted from
the live server (not archived — genuinely dropped): `db_schema.sql`
(MySQL-syntax `CREATE TABLE` statements, `ENGINE=InnoDB` etc.) and
`neuroverse_mm26.sql` (a one-time MySQL data dump dated 2026-07-02, whose
own header said so directly). Confirmed dead via direct evidence, not
assumption: `db.py` imports `aiosqlite`, not any MySQL client; grepping
every live file for `.sql`/`mysql`/`pymysql`/`db_schema` turned up nothing
except a stale comment; and the dump's own `players` schema stored stats
like `hof_avg`/`pwr_rank` as static columns on each row — completely
incompatible with the current architecture, where `get_player_stats()`
computes every one of those live from `game_scores` instead. The dump was
also missing the NX league entirely, confirming it predates NX being added.

`tournament.py`'s header docstring said "backed by MySQL" and pointed at
`db_schema.sql` by name — also stale, not actually true. The file itself
does `import db` and calls `db.list_tournaments()`/`db.create_tournament()`/
etc., going through the exact same SQLite layer as everything else; it
never touched MySQL directly, the file just never got its own comment
updated when the underlying storage was migrated out from under it.
Corrected to describe the real architecture and point at `db.py`'s own
CRUD functions as the source of truth, since there's no separate schema
file anymore — the live schema lives in the `.db` file itself.

Two other files from the same MySQL-transition era are still around but
harmless: `utils.py`'s docstring ("no gspread dependency in the MySQL
version") and its `safe_db_call` helper, which doesn't appear to be
called from `db.py` or `optimized_bot.py` — possibly used from `agent.py`/
`status.py`, neither of which has been reviewed in depth yet. Worth
checking before assuming it's fully dead the way the two `.sql` files were.

## Anthropic-specific

- `/ladder`'s screenshot extraction calls Claude Haiku
  (`claude-haiku-4-5-20251001`) directly via the Anthropic API in `agent.py` —
  vision extraction of opponent roster + league name + division + our rank
  from League vs League screenshots. **Not yet tested against a real
  screenshot** — this sandbox has no network access to call the live API.
  Worth a real `/ladder` run after any prompt change to confirm accuracy.

## Multi-season archive system (/legacy) and /stats

Added at the 2026→2027 season transition. Two pieces:

- **`/stats league:X include_inactive:bool`** — league-wide averages as an
  image (one row per stat category, not per-player — that's `/rank`).
  `include_inactive` (default False) folds in players who are now inactive
  *or have since transferred to a different league*, as long as they have a
  historical `game_scores` row with `team_id` = this league. Backing
  function: `db.get_league_stats()`.

- **`/legacy <rank|player|stats|history|scores|show_ladder> year:YYYY`** —
  read-only lookups against an archived past season's database
  (`neuroverse_{year}.db`, expected to sit alongside the live `neuroverse.db`
  on the server). Each subcommand takes exactly the same arguments as its
  live counterpart, plus `year`. `/legacy opp` was deliberately never built —
  `/opp` has no existing date argument (it's always "today"), so "same
  arguments + year" doesn't map onto it cleanly, and the live command
  falls back to the undated `ladder_matchups` table in a way that isn't
  meaningful for a closed season anyway.

**How it works, if this needs extending:**
- `db.get_archive_conn(year)` opens (and caches) a connection to the archive
  file in SQLite's own **read-only URI mode** (`file:...?mode=ro`) — not just
  "the code happens to never write," but genuinely enforced at the SQLite
  level. Returns `None` if that year's archive doesn't exist; callers show a
  "no archive for that year" message, not an error.
- Every DB function a `/legacy` command might need takes an **optional
  `conn=None` parameter**, threaded all the way down to the low-level
  `fetchone`/`fetchall` (which default to the live `_db` when `conn` is
  `None`). This was done as explicit parameter-passing, not a global
  connection swap — swapping a module-level `_db` pointer would be a genuine
  concurrency hazard in a multi-user bot (two people running a live and a
  legacy command at the same time could each end up hitting the wrong
  database if the event loop interleaves them mid-await).
- Each live command's actual logic (building the rank image, the player
  embed, the history embed, the scores grid, the ladder image) was refactored
  into a shared helper function accepting `conn`/`season_label`, so the live
  command and its `/legacy` counterpart call the exact same code — not a
  parallel copy that could drift out of sync.
- `status`/`active` filtering nuances differ by function, on purpose:
  `get_player()` and `get_player_fourth_down_rate()` drop the
  `status != 'I'` filter entirely when `conn` is provided, since looking
  someone up *by name* in an archive should work regardless of their final
  status. `get_team_stats()` (which drives `/rank` and `/legacy rank`) keeps
  the `status='A'` filter even in archive mode, since that reflects who was
  actually active in that season's own frozen snapshot — i.e. what `/rank`
  genuinely showed back then, not a reinterpretation.
- Archive connections are closed on bot shutdown alongside the main DB
  (`db.close_archive_connections()`).

**Test-stub gotchas hit while building this** (fixed, but worth knowing since
they could resurface): the fake `aiosqlite.connect()` in `tests.py` originally
only accepted a single positional path argument — extended to accept and
honor `uri=True`, otherwise a test claiming to verify read-only enforcement
would silently not verify anything. Separately, `_FakeDBConn.row_factory` was
a dead class attribute that didn't propagate to the wrapped real `sqlite3`
connection — fixed into a real property, otherwise rows fetched through any
non-main connection (like an archive one) came back as bare tuples instead of
dict-like rows. Also: `app_commands.Group` didn't exist in the stub at all
until this feature needed it — added as an identity-decorator stub
(`@group.command(...)` returns the function unchanged), which conveniently
means `/legacy` subcommands stay directly testable, unlike plain
`@tree.command`-decorated functions.

## /dscore simplified, full flow moved to /dscore_multiple

In this game's ecosystem, the common case is a single opponent facing a
player for all 3 drives, not a different opponent per drive — the
original `/dscore` (modal per drive, individually collecting each
drive's OVR plus turnover down/distance/play/forced-by detail) was more
than the common case actually needs.

**Split into two commands, same `defense_scores` schema for both:**
- **`/dscore`** — new, simplified. No modal at all. Takes `player`,
  `drive1`/`drive2`/`drive3` (unchanged, same 0-8/F/I/S values), and a new
  inline `ovr` argument — the single opponent's OVR, applied to all 3
  drives at once. Backed by a new `db.update_player_dscore_single_opponent()`,
  which sets `avg_off_ovr_faced` **and** all three `drive{1,2,3}_ovr`
  columns to that same value in one call — not just the average, since
  `drive{N}_ovr` are real columns other things could read per-drive, and
  leaving them null while only setting the average would be an
  inconsistent partial write. Never touches the turnover
  down/distance/play/forced-by columns — those stay unset, since nothing
  collects that detail in this simplified path (no modal, no inline
  argument for it either).
- **`/dscore_multiple`** — the original flow, completely unchanged
  (down to the exact modal classes, `_dscore_build_drive_modal`,
  `db.update_player_dscore`/`update_dscore_drive_detail`/
  `finalize_dscore_avg_ovr`), just renamed from `/dscore`. For the less
  common case where more than one opponent actually faced the player
  across the 3 drives, so each drive genuinely needs its own OVR.

Drive-string parsing/validation (`0`-`8`/`F`/`I`/`S`, points-allowed
total) is shared between both via a new `_parse_dscore_drives()` helper
in `optimized_bot.py`, so the two commands can never quietly drift apart
on this point. It raises `ValueError` carrying the 1-based drive number
(as a string) that failed, not a full message — each command's own
i18n-labeled error text is built from that number, since only the caller
knows which label (`dscore.modal.label_drive1` etc.) goes with which slot.

`get_player_dscore_stats()` (the career defensive rollup) reads
`avg_off_ovr_faced` — confirmed this needs no changes at all, since the
simplified path sets that column to exactly the same kind of value the
full modal flow always did, just computed differently upstream (given
directly, rather than averaged from 3 separately-entered values that
happen to be equal).

## Fumble-adjusted averages: fumbles treated as null drives

`_fumble_adjusted_avg(total_points, games, fumbles)` in `db.py` implements
a second, parallel average for every existing average calculation: instead
of treating a fumble as a real drive that happened to score low, it's
excluded from the denominator entirely, as if that drive never occurred.
Every game is exactly 3 drives:
```
total_drives           = games * 3
fumble_adjusted_drives = total_drives - fumbles
fumble_adjusted_ppd    = total_points / fumble_adjusted_drives
fumble_adjusted_avg    = fumble_adjusted_ppd * 3
```
**Counterintuitive but correct: this number comes out *higher* than the
plain average whenever there are fumbles**, not lower — a fumble is
typically a low/zero-scoring event, and removing it from the denominator
means the same points get divided across fewer drives. It's "protecting"
the average from being dragged down by the fumble, which is the whole
point of treating it as null rather than as a real, scored drive. A test
in `tests.py` originally asserted the opposite (lower, not higher) and
had to be corrected — worth remembering if this ever looks "backwards" at
a glance.

With zero fumbles, `fumble_adjusted_drives` equals `total_drives` exactly,
so this collapses to precisely `total_points / games` — identical to the
plain average. The two numbers only diverge once fumbles > 0.

**Applied to `get_player_stats`** (backs `/rank`, `/player`, `/stats`):
every one of the 10 existing averages (`avg_yearly`, `avg_30day`,
`avg_14day`, `avg_7day`, `avg_3day`, `hof_avg`, `e1_avg`, `e2_avg`,
`e3_avg`, `gold_avg`) now has a `_fumble_adj` counterpart in the returned
dict, computed from the exact same query/window as its plain sibling (not
a second pass) — `last_n()` and `event_avg()` both compute `SUM(score)`,
`COUNT(*)`, and `SUM(fumbles)` alongside the plain `AVG(score)` in one query.

**Applied to `/avg` via a new function, not a change to the existing
one** — `get_player_avg_with_fumble_adj(ign, atype)` mirrors
`get_player_avg`'s exact query structure/scope and returns
`{'avg':, 'fumble_adjusted_avg':}`. `get_player_avg` itself was
deliberately left unchanged (several existing tests depend on its plain
float return) — this is purely additive. `/avg`'s `AvgTypeSelect` now
shows both numbers together.

**Surfaced in `/player`'s card** as a new "Yearly Avg (Fumble-Adj.)"
field next to the existing yearly average — the single most-viewed of the
ten, added without doubling every field on an already-dense 17-field
card. The other nine fumble-adjusted values exist in `get_player_stats`'s
return dict and are available to any future command that wants them, just
not yet wired into a specific display beyond this one field and `/avg`.

**Also selectable as independent pwr_rank/ladder_rank factors** — 11 new
labels in `ALL_STAT_KEYS` (`optimized_bot.py`): the 7 pwr_rank-side
averages (`yearly_avg_fumble_adj`, `30day_avg_fumble_adj`,
`hof_avg_fumble_adj`, `e1_avg_fumble_adj`, `e2_avg_fumble_adj`,
`e3_avg_fumble_adj`, `gold_avg_fumble_adj`) and the 4 ladder-side ones
(`3day_avg_fumble_adj`, `7day_avg_fumble_adj`, `14day_avg_fumble_adj`,
`30day_ladder_fumble_adj`). Each is wired as its own term in the actual
`pwr_rank`/`ladder_rank` formula in `db.py`, alongside (not replacing) its
plain counterpart — an admin who wants fumbles-as-null-drives to
influence rank sets a weight on the new label via `/weights`; with no row
for it in `pwr_rank_weights` (the default, unchanged case), it
contributes exactly 0, so no existing league's rank shifts just because
this feature exists. Verified by actually setting a weight and confirming
the computed rank changes, then reverting the formula term and confirming
the test genuinely fails without it — not just asserting a plausible
number.

**Testing note:** `get_player_avg` (the pre-existing, unchanged function)
doesn't scope by `team_id` at all — unlike the now-fixed `get_player_stats`,
it computes a player's career-wide average regardless of which team they
were on for each game. This predates this feature, wasn't part of what was
asked here, and was deliberately left alone rather than silently changing
`/avg`'s existing behavior as a side effect of this work — flagged here in
case it's ever raised as a separate issue later.

**All 10 averages, not just yearly, shown on `/player`'s card** — each
average field's value now combines its plain and fumble-adjusted number
into one string ("20.54 (FA: 21.65)") via a new `_fmt_avg_with_fumble_adj()`
helper, rather than a separate field per average. This is what makes
showing all 10 (not just the 6 that used to be on this card — 30-day,
14-day, E3, and Gold- are new additions here specifically so their
fumble-adjusted values have somewhere to go) fit within Discord's
25-fields-per-embed limit: 10 separate plain fields plus 10 separate
fumble-adjusted fields would have been 20 fields on their own, before
counting everything else already on the card.

## 4th down conversion % replaces dead nominal-count weight options

`fourth_downs`/`fourth_down_convs` were selectable in `/weights` since
`ALL_STAT_KEYS` was first built, but were **never actually wired into**
the `pwr_rank`/`ladder_rank` formula at all — a genuinely dead pair of
options, same as several other pre-existing `ALL_STAT_KEYS` entries
(`kobes`, `points`, `games`, `three_td`, `three_td_pct`, `two_pt_pct`,
`fumbles` — none of these are referenced in the formula either; this
predates any of this session's work and wasn't touched). Raw nominal
counts also wouldn't have been a meaningful weight factor even if wired
in, since they scale with how many games a player's played rather than
their actual efficiency.

Replaced both with a single `fourth_down_conv_pct` label — conversions/
attempts, stored as a decimal (0-1, matching `three_td_pct`/`two_pt_pct`'s
own convention, not 0-100) — computed **inside** `get_player_stats` with
its own team_id-scoped query, not by reusing `get_player_fourth_down_rate`
(which is deliberately career-wide/unscoped for its own by-name-lookup
purpose; reusing it here would reintroduce the exact cross-team bleeding
this function is careful to avoid everywhere else). Wired into both
`pwr_rank` and `ladder_rank` as a genuinely functional, independently-
weighted factor this time — confirmed by setting a real weight and
seeing the computed rank actually change, then confirming a broken
team_id scope is caught by a dedicated test before considering this done.
`/player`'s existing 4th-down field (attempts/conversions/rate, via
`get_player_fourth_down_rate`) was deliberately left as-is — this change
was scoped to the `/weights` factor specifically, not to that display.

## /streak — consecutive-game hot streaks

New command, `player` as the only input (autocomplete via the same
`player_autocomplete` as `/score`/`/player`, no league/team param needed).
`db.get_player_streaks()` computes two metrics, each counting consecutive
games backward from the most recent:
- `kobe_streak` — consecutive games scoring **24+** (not exactly 24 — see
  the real-data bug note below; deliberately NOT the same condition as
  the existing `kobes` stat, which does count score==24 exactly).
- `no_drop_streak` — consecutive games scoring 18+. Per this game's
  scoring tiers (see `_two_pt_pct`), 18-19 is the lowest score
  representing all 3 drives completed; anything below means at least one
  drive was dropped.

**Real bug caught by testing against an actual production database**
(the user stopped the server and provided a copy specifically for this):
the first implementation used `score == 24` exactly, mirroring the
existing `kobes` stat — but the actual request said "24+", and every
synthetic test fixture up to that point happened to only ever use exactly
24, so this was invisible. Querying the real database directly showed
scores of 26, 28, 30 (even 40) genuinely occur, affecting roughly 5% of
real players — one active player's streak was incorrectly breaking on a
30-point game, a *better* result than a Kobe, because it wasn't exactly
24. Fixed to `score >= 24`; re-verified the exact real player/date this
was caught on before and after the fix, and added a permanent test
(`test_get_player_streaks_kobe_streak_counts_scores_above_24_too`)
reproducing it directly. Worth remembering generally: synthetic test data
only covers cases someone thought to write, real data covers cases that
actually happen — this is exactly the kind of off-by-a-condition bug that
a hand-written fixture is unlikely to ever stumble into by accident.

**Missed vs. excused handled differently on purpose:** a missed drive
(`is_forfeit`) counts as a real score of 0, failing both conditions and
breaking both streaks outright. An excused absence (`is_excused`) is
**skipped entirely** rather than breaking either streak — consistent
with how excused entries are excluded from every other average/count in
this codebase (treated as if that day never happened at all, not as a bad
game). Scoped to the player's current `team_id`, same historical-scoping
principle as `get_player_stats` — a transferred player's streak on a
previous team can't carry into or extend their current team's streak.
Confirmed all three of these (excused-skip, missed-break, team-scoping)
are real by breaking each one in the code and confirming the corresponding
test fails without it.

## /openspots — open roster spots per league

New command, no arguments at all. `db.get_open_spots()` computes, for
every league, `18 - COUNT(active players)`. Queries the `teams` table
directly for both `team_id` and display name, rather than a hardcoded
league list or depending on `optimized_bot.py`'s `LEAGUE_NAMES` constant
(a backwards dependency — `db.py` is the lower-level module) — this means
a league added to the `teams` table later is automatically picked up with
no code change here.

**The 18 here is a distinct concept from the "16" used for siege
matchups** (`siege.py` — a siege match pits 16 active players against 16
opposing players). This is the overall league membership cap the command
is asking about, not the siege participant count — the two numbers
describe genuinely different things in this game's ecosystem, not one
being a typo for the other. `get_team_stats`'s own docstring already
notes active rosters "aren't always exactly 16" for the siege context;
the same caveat applies here for 18.

Sorted by most open spots first (descending), not alphabetically by
league — the more immediately actionable order for a "where does a new
player fit" question. Only `status='A'` players count against a league's
active total; an inactive (`status='I'`) player doesn't reduce that
league's open spots, confirmed by a dedicated test (added a player with
`status='I'` and verified the count is unaffected). A league with zero
active players still appears in the output at the full 18 open, rather
than being silently absent.

## Terminology: "active/rostered" (18-cap) vs. "playing/rested" (16-cap)

Two genuinely distinct concepts that both got called "active" at different
points in this codebase's history, which is confusing on its own even
before the newer `/activate`/`/inactive`/`/reactivate` commands (a third,
related-but-different meaning — see those commands' own docs) entered the
mix:

- **Active / rostered** (`players.status = 'A'`): is this player currently
  a member of the league's roster at all. Hard cap of **18** per league.
  `/openspots` (18 minus this count), `/player`'s status field, and
  `get_team_stats`/`get_player_stats`'s scoping all use this meaning.
- **Playing / rested**: of a league's active roster, which players are
  actually participating in one specific ladder, matchup, or siege
  instance. Hard cap of **16** — see `ladder_flow.py`'s `MATCHUP_SIZE` and
  `siege.py`'s header docstring. A player not selected for a given
  instance is "rested" for it, not inactive — resting for one ladder has
  no bearing on their roster membership or their status in the next one.

There's no dedicated `players` column for "playing" — `/ladder`'s builder
tracks it as `LadderState.selected` (exactly 16 of `LadderState.players`,
the active pool for that league); `/matchup`'s score-entry grid shows the
full active roster and treats a blank/missing `game_scores` row for that
date as "didn't play this one," not stored as an explicit flag anywhere.

Several comments and docstrings across `db.py`, `siege.py`, and
`ladder_flow.py` previously said things like "a siege match pits our
league's 16 active players" — technically describing the playing concept
but using the active/rostered word for it, which is exactly backwards from
how an admin reading it would parse "active" elsewhere in this same
codebase. Corrected wherever found; if a future comment says "16 active
players" again, that's this same conflation recurring, not a new fact
about the game. **User-facing text (i18n labels like `player.status_active`,
`{active}/18 active`) intentionally keeps "active" for the roster-
membership meaning** — this terminology cleanup was scoped to internal
comments/docstrings, not to renaming what players actually see in Discord.

## Siege embed field length: Discord's 1024-char-per-field limit

`build_status_embed()` — shared by `/siegestatus`, `/siegefinal`, and
`/updatesiege` (the latter two via `_send_correction_view`) — built its
"Open Nodes" field by joining one line per open node into a single string
with no length check. Discord hard-caps a single embed field's `value` at
1024 characters and rejects the **entire message** with an `HTTPException`
if any field exceeds it — not a partial send, not a truncation, the whole
command just fails. Once a long-running siege accumulates enough open
nodes, this made all three commands fail on literally every single call,
every time, until someone cleared enough nodes to get back under the limit.
Same underlying risk existed in the "Player Totals" field (already split
into a 2-column layout, but that's a cosmetic halving, not a length
safeguard — this league has at least one 66-player roster, easily enough
to still exceed 1024 chars per half).

Fixed with `_chunk_lines_to_fit(lines, max_chars=1024, max_chunks=5)` in
`siege.py`: splits a list of lines into as many 1024-char-safe chunks as
needed, each becoming its own embed field (labeled "(cont.)" past the
first). Capped at 5 chunks so an extreme case (dozens of open nodes) can't
separately blow past Discord's other limit of 25 fields per embed — the
last allowed chunk gets a "...and N more" note instead, counting actual
dropped *lines*, not dropped chunks, so the number shown is meaningful.

**Right-sized to the actual game rule, not left at the generic default** —
a siege match pits 16 players against 16 opponents, one node per opponent,
so there is a hard, real ceiling of 16 open nodes at once (`MAX_SIEGE_NODES`
in `siege.py`). The open-nodes field specifically uses
`_OPEN_NODES_MAX_CHUNKS = 3` rather than the generic `_chunk_lines_to_fit`
default of 5 — confirmed directly that even the worst realistic case (all
16 nodes, each with a deliberately long opponent name) only ever needs 2
chunks, so 3 leaves real margin without being sized for a 30- or 200-node
scenario that can never actually occur. The generic default of 5 is kept
for the "Player Totals" field, which genuinely isn't bounded this way — it
scales with roster size (this league has a 66-player roster), not a fixed
game rule.

Caught via a real production screenshot showing the exact error
(`embeds.0.fields.1.value: Must be 1024 or fewer in length`) on both
`/siegestatus` and `/siegefinal`. Verified the fix directly — reverted to
the original single-field join and confirmed the test fails with the field
at 2215 characters (matching the reported failure), then confirmed it
passes clean restored. Also verified an extreme 200-node case correctly
caps at 5 fields with an accurate overflow count rather than trying to
build 20+ fields and hitting the fields-per-embed limit instead.

**Test-writing lesson from this one:** the stub's `discord.Embed` doesn't
maintain a real `.fields` list — `add_field()` is a plain mock, so
`embed.fields` is always empty regardless of what was called. The
established (and correct) way to inspect what an embed actually received
is `embed.add_field.call_args_list`, pulling `.kwargs.get("name"/"value")`
per call — confirmed this directly after an initial verification pass
silently checked nothing (`embed.fields` was trivially `[]`, so an
assertion on it never failed no matter what).

## /ladder OVR sanity check — catching vision misreads before they hit the ladder

Reported failure mode: the AI vision extraction in `/ladder` sometimes
misreads a leading digit (specifically: 3 misread as 8), turning e.g. a
real OVR of 3200 into an extracted 8200. This silently applied to the
player's record and skewed ladder rankings, requiring a manual correction
after the fact once someone noticed.

**Deliberately relative, never an absolute/hardcoded range** —
`_is_ovr_change_suspicious(old_val, new_val, threshold=0.30)` in
`optimized_bot.py` compares a change to *that specific player's own
previous value*, not any fixed number range. This matters concretely: OVR
is currently ~3000-4000 league-wide but increases unpredictably over a
season, so a hardcoded absolute cutoff (e.g. "flag anything over 6000")
would work today and quietly stop working — or start false-flagging
everyone — a few months from now. A relative check keeps working
correctly at whatever range the league drifts to, since it was directly
tested at multiple different ranges, not just the one true "right now."
30% was chosen to let a real, large legitimate jump (a much stronger
build) through untouched, while still easily catching a misread this size
(+156% for the reported 3200→8200 case). Flags large decreases too, not
just increases — the reverse misread (8 read as 3) is exactly as possible.

**Implementation**: `_check_ovr_changes(row, extracted)` is a pure
comparison (no DB writes) splitting a candidate update into `normal`
(safe, applied immediately via `_commit_ovr_updates`) and `suspicious`
(held for review). `OvrSanityCheckView` is a new review step — same
batched/chaining/5-action-row-cap design as `LadderPlayerMatchView` (see
that class's docstring for the Discord-limit reasoning) — shown after all
name-matching is resolved (including for players matched through the
*manual* name-match flow, not just the automatic exact-match path) and
before `start_ladder_flow` is ever called. Each flagged change gets a
select with "use extracted value" vs "keep current value"; leaving it
unreviewed and hitting Confirm defaults to reject (the safer of the two —
never silently accepts something nobody actually looked at).

`_apply_extracted_ovr` (the original, single-function version) is kept
around unchanged for direct callers like `/ovr` that want the old
always-apply behavior — a human deliberately typing a value in doesn't
need a machine second-guessing them the way an AI vision extraction does.
Only the `/ladder` screenshot flow uses the check/commit split.

## Global slash-command error handler: rate limit vs. expired interaction

Two real production errors surfaced together: `/player` hit a transient
Discord-side issue sending its result (`429`, error code `40062` "Service
resource is being rate limited"), and `/matchup` hit an already-expired
interaction on its very first response attempt (`404`, error code `10062`
"Unknown interaction"). The single global handler (`@tree.error` →
`on_app_command_error`) treated both identically: one blind retry attempt
wrapped in a bare `except: pass`.

For an expired interaction, that retry was **guaranteed to fail with the
exact same error** — once an interaction's token is invalid, no amount of
retrying makes it valid again, so the attempt just wasted a call and the
bare `except` swallowed the second failure too, leaving no trace of what
happened and no response to the user either way. For a rate limit, a
single *immediate* retry is unlikely to help either, since the underlying
condition (Discord's service being overloaded) hasn't had time to clear.

Fixed by distinguishing the two: unwrap `CommandInvokeError.original`
(confirmed directly against discord.py's own source — both the
`ext.commands` and `app_commands` versions expose the underlying exception
via `.original`) to see what actually happened. `discord.NotFound` with
`.code == 10062` logs clearly and returns immediately — no retry attempt
at all, since none can succeed. `discord.HTTPException` with
`.status == 429` gets one retry after a 2-second `asyncio.sleep`, since
that class of error can genuinely clear within a second or two. Every
other error keeps the original single-attempt behavior unchanged.

**Extracted into `_handle_app_command_error()`, a plain function, rather
than testing `on_app_command_error` directly** — `@tree.error` is used
as a bare decorator (no parentheses), so under this codebase's stub
(`tree` is a `MagicMock`), `on_app_command_error = tree.error(...)`
becomes another `MagicMock`, not the original function — confirmed
directly (`type(on_app_command_error)` prints `_BotStub`). Same
underlying reason `@tree.command`-decorated functions can't be called
directly either; `on_app_command_error` itself is now a one-line
delegation to the actual, testable logic.

**Test-stub gotcha found while building this:** `discord.HTTPException`
and `discord.NotFound` didn't exist as real classes in the stub at all —
`discord.errors.HTTPException` was aliased to plain `Exception`, with no
`.status`/`.code` attributes and no `discord.NotFound` at all. Added
proper stub classes exposing both attributes, plus a stub
`app_commands.CommandInvokeError` exposing `.original`, matching the real
discord.py API exactly (verified against the actual source before
building on top of it, not assumed).

## /score crash: modal default value exceeding its own max_length

`ScoreModal`'s score field has `max_length=4` (reasonable — scores are
short: a number, "M", or "E"). `/score`'s `points` parameter gets passed
through as that field's default via `prefill_score`, with no length check
at all. Discord rejects modal creation outright — `HTTPException: 400 Bad
Request, Invalid Form Body, data.components.0.component.value: Must be 4
or fewer in length` — if a default value exceeds the field's own
`max_length`. This surfaced as a full unhandled crash with zero response
to the user (not even an error message) whenever someone typed more than
4 characters into `points`.

Fixed at two layers: `score_slash` now validates `points` length before
ever constructing the modal, showing a friendly `score.err.points_too_long`
message instead of letting Discord reject it. `ScoreModal.__init__` also
now truncates `prefill_score` to `self.score_val.max_length` defensively,
so this can't happen regardless of what any current or future call site
passes in — belt-and-suspenders, not either/or.

**Test-stub gotcha found while fixing this:** the stub's `_TextInput` class
only stored `.value`/`.default` from constructor kwargs, silently dropping
`max_length` and `required` entirely — so code that legitimately checks
`self.some_field.max_length` (exactly what the fix needed to do) crashed in
tests with `AttributeError`, not because the production code was wrong, but
because the stub didn't model a real attribute the actual `discord.ui.TextInput`
exposes. Fixed by storing both. Worth checking for the same gap if a future
fix ever needs another `TextInput` constructor kwarg the stub doesn't track yet.



**Player names now use each style's own display font, not a generic
fallback** — tactical/varsity/street/championship/arcade all use
Black Ops One/Graduate/Bungee Inline/Nabla/Press Start 2P for names too,
matching the title, per an explicit request that a style's whole table
feel consistent rather than just the header being themed. Confirmed each
font stays legible at the sizes names actually render at before making
this change (all tested down through realistic small sizes) — Press Start
2P stays fully legible down to 10px despite being very wide per character
(unlike Honk/Nabla, it isn't a variable font with a breakdown point), so
it was safe to use directly with `_fit_text`.

**`carnival` (Honk) is a deliberate exception** — names there still use
`_POSTER_FONT_BOLD`, not Honk. Confirmed directly (not assumed) that Honk's
digit glyphs are genuinely hard to distinguish from letters in mixed
alphanumeric names: "JX8", "Dukie06", "GKH1987" all became borderline
illegible even at a safe size, and tuning the shadow axis down to 0 didn't
fix it — this is a base glyph-design limitation, not a size or
axis-setting problem. Real rosters in this league commonly have exactly
this kind of name, so Honk stays reserved for the title/labels (known,
controlled text) and rank badges/names use the reliable font. Tests check
this from source directly (`_render_ladder_carnival` must reference
`_POSTER_FONT_BOLD` for names, must not reference `_fit_variable_text` for
them) so a future edit that reintroduces Honk here fails a test rather
than shipping unreadable names silently.

**Three additional /show_ladder styles use real display fonts the user
sourced and uploaded directly** (a zip of Black Ops One, Bungee Inline,
Graduate, Honk, Nabla, Press Start 2P — only 3 of the 6 were used):
`tactical` (Black Ops One — military/esports stencil look, olive/amber),
`varsity` (Graduate — collegiate athletics slab-serif, navy/gold; note this
font has no true lowercase glyphs, renders as caps regardless of input
case, which fits the aesthetic), and `arcade` (Press Start 2P — 8-bit pixel
font, magenta/cyan neon; very wide per character, so titles/labels lean on
`_fit_text` more aggressively than other styles and keep display-font text
short, using `_POSTER_FONT_BOLD` instead for the actual player
names/stats). Bungee Inline/Honk/Nabla weren't used for this round but are
still sitting in the uploaded zip if a future style wants them.

These fonts have no standard OS package the way DejaVu does, so their
fallback chains are just `[bundled_path] + _POSTER_FONT_BOLD` (Condensed
Bold) — no fake system-wide path guessed, since one doesn't realistically
exist for these. A missing bundled file degrades to "looks like a
different style" rather than illegible, same principle as everywhere else
in this file.

**Worth knowing for next time a "make it look more X" request comes in:**
genuinely fetching a specific named display font (e.g. Anton, Bebas Neue)
from the web didn't work — GitHub's raw content host disallows automated
fetches, and CDN mirrors either need JS execution to resolve a real
download link or hit the fetch tool's restriction against building a URL
from a path merely seen in prior content rather than one actually returned
as a link. The reliable path is asking the user to download from
fonts.google.com directly and upload the .ttf here, which is exactly how
this batch arrived.

## Font loading: bundled fonts, not system-dependent

**Poster styles use DejaVu Sans Condensed (bold/regular/oblique), not the
regular-width DejaVu Sans** — chosen for a sportier, more athletic/blocky
look than the standard width, while staying in the same reliable DejaVu
family (all fallback chains still end in the regular-width DejaVu Sans,
which is confirmed working, then PIL's default as an absolute last resort).
Genuine display/condensed fonts built specifically for a sports-broadcast
look (Anton, Bebas Neue, etc.) aren't available in this sandbox and
couldn't be fetched — GitHub's raw content host disallows automated
access, and other CDN routes either require JS execution to resolve a
download link or hit the fetch tool's restriction against constructing a
URL from a path found in prior content rather than a URL it directly
returned. DejaVu Sans Condensed Bold was the best available option without
introducing a new, unverified font dependency.

`sheet_image.py` renders every image (`/rank`, `/scores`, `/stats`,
`/show_ladder`) via Pillow, which needs real `.ttf` files on disk — it
doesn't fall back gracefully the way a browser does. Two real bugs came out
of this:

1. **`ImageFont.load_default()` (PIL's fallback for a missing font file)
   ignores whatever size was requested** on most PIL versions — it always
   renders at a fixed ~10px. `_load_font()` used to catch a missing-font
   exception and call this with no signal at all, so a missing font file
   didn't error, it just silently produced barely-legible text.
2. **The `/show_ladder` poster styles (neon/clean/scoreboard) introduced a
   dependency on the "Liberation" font package**, separate from the "DejaVu"
   family every other rendered image in this codebase has reliably used.
   This sandbox happens to have both installed, so it was invisible in
   every render done here — but the actual production server apparently
   doesn't have Liberation, so every bold element in those three styles
   (titles, names, rank numbers — nearly everything except italic stat
   text) silently collapsed to that same fixed ~10px font. Confirmed via a
   user screenshot showing correct layout/shapes but tiny text, then
   confirmed the file's actual pixel dimensions exactly matched what the
   code should have produced — proving the bug was in font rendering, not
   image sizing or Discord's display scaling (an earlier, wrong theory).

**Fixed by bundling fonts directly with the bot's own files** rather than
depending on the host OS having any particular font package installed at
all — this hosting setup has no shell access to install one anyway. Font
constants (`FONT_PATH`, `FONT_BOLD`, `FONT_ITALIC`, `_POSTER_FONT_*`) are
now lists of candidate paths: a bundled copy in a `fonts/` folder next to
`sheet_image.py` first, then the old system path as a secondary fallback.
`_load_font()` tries each in order, and only if literally every candidate
fails does it reach `load_default()` — which now also logs a loud server
error (so a missing font is a visible ops issue, not a silent rendering
bug) and asks for `size=` explicitly on PIL versions that support it.

**To deploy:** upload the bundled `.ttf` files into a `fonts/` folder in the
same directory as `sheet_image.py` on the server (same File Manager process
as any other file — no shell needed). Verified this actually works by
simulating a server with zero matching system fonts at all (pointing every
system fallback path at something nonexistent) and confirming all three
poster styles still render with correctly-sized text using only the
bundled copies.

**Testing lesson:** every previous test for the poster styles passed
against the broken code, because this sandbox has both font packages
installed — none of them actually verified text was a specific size, only
that rendering didn't crash. The tests that actually catch this class of
bug simulate a missing font file directly (pointing a font constant at a
nonexistent path) and assert on the resulting font's actual `.size`, not
just that a PNG came out the other end.

**Follow-up from actual production logs:** after deploying the bundled
fonts, one specific file — `DejaVuSans-Oblique.ttf` (and only that one; its
regular/bold siblings loaded fine) — still failed to load on the real
server, confirmed via repeated `_load_font` error-log lines during a single
`/show_ladder` run. The delivered file was verified byte-identical to the
source and loads fine in every test environment, so the exact cause on that
specific server remains unconfirmed (a partial/incomplete upload of just
that one file is the most likely explanation, but not verifiable
remotely). Rather than depend on chasing that down, `FONT_ITALIC` and
`_POSTER_FONT_ITALIC`'s candidate-path lists now also fall back to the
same family's *regular* (non-italic) weight before ever reaching PIL's
generic default — so one specific font file being unavailable degrades to
"correct size, not italic" rather than the ~10px collapse. Confirmed via a
test that simulates this exact scenario (oblique unavailable at both
candidate paths, regular weight available) and asserts the resulting font
size, not just that rendering succeeds.

## Workflow conventions for future sessions

- Deliver DB fixes as an actual repaired `.db` file when the user provides an
  export; deliver code fixes as the changed `.py` files. Always run the full
  test suite before presenting anything.
- When something "isn't taking effect" after a fix was delivered, don't
  assume the fix is wrong — check the deploy sequence first (WAL race
  condition above is the most common real cause found this session).
- If uncertain about a live Discord/Python API behavior instead of an
  in-repo pattern, search for it directly rather than relying on training
  data — this project's Discord library version has changed meaningfully
  during this conversation (Components V2 modal system, `discord.ui.Label`)
  and stale assumptions have caused real bugs before.

   <!-- github sync test, 2026-09-17 -->