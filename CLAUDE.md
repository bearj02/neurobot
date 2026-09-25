# CLAUDE.md — Neuroverse Discord Bot

This file exists so a future session (with none of this conversation's context)
can pick this project up quickly. Update it as new important context is learned —
don't let it go stale.

## What this is

A Discord bot (`TittyBot#0428`) for a multi-league Madden Mobile league system.
Leagues as of Sept 2026: NP (NeuroPerverse), ND (NeuroDiverse),
NA (NeuroAdverse), NR (NeuroReverse), NC (NeuroChaos), NT (NeuroTraverse),
NX (NeuroChristians). NI (NeuroInverse) existed earlier and has been deleted.
**Don't treat that list as fixed — and don't hardcode it anywhere.** The
`teams` table is the source of truth; see "League list comes from the teams
table" below.

**Stack:** discord.py 2.7+, SQLite via `aiosqlite`, hosted on bot-hosting.net
(Pterodactyl panel). Fully localized in 5 languages (en, es, fr, pt, de).

**Files:**
- `optimized_bot.py` — main bot, most slash commands
- `db.py` — all database access, schema migrations
- `i18n.py` — all user-facing strings, all 5 languages, manual page text
- `siege.py` — the Siege game mode
- `ladder_flow.py` — the `/ladder` builder flow (screenshot extraction or manual)
- `neuroseason.py` — the NeuroSeason gamemode (scheduling, standings, playoffs)
- `agent.py` — Claude Haiku vision extraction for `/ladder` and `/seasonmatch` screenshots
- `sheet_image.py` — PIL-based PNG table rendering (`/rank`, `/scores`, `/show_ladder`)
- `tournament.py`, `status.py`, `newday.py` — smaller, mostly-stable feature areas
- `tests.py` — full discord.py stub + 530+ tests, no real Discord/network needed
- `db_schema.sql`, `logger_config.py` — supporting files, rarely touched

## Critical: how deployment actually works (NO shell access)

**As of Sept 2026, this project migrated from manual file-manager uploads
to a GitHub-connected workflow** (see the "GitHub deployment workflow"
section below for the full mechanism) — but the fundamental constraint
that shaped this project from the start hasn't changed: **the user still
has no real SSH/shell access.** The panel does have something labeled
"terminal," but it was directly tested and confirmed to just echo input
back rather than execute anything — not a real shell, don't treat it as
one if it's ever mentioned again. This still shapes everything below:

- All schema and data migrations MUST run automatically from code
  (`db.py`'s `_migrate_schema()`, called on every startup). There is no other
  way to apply a DB change. Every migration must be idempotent (safe to rerun
  forever) since it runs on literally every restart.
- **The database runs in WAL mode.** Replacing `neuroverse.db` on the server
  while the bot is still running causes a real race condition — the live
  process is still writing to the file at the same time the replacement
  happens. This produces exactly the failure mode hit repeatedly early on:
  corruption (`disk image is malformed`) and/or silent partial reverts where
  only the most-recently-written data survives. **Confirmed root cause, not
  a guess.** Correct sequence: **fully stop the bot → delete any leftover
  `.db-wal`/`.db-shm` → upload the new `.db` → start the bot.** This risk is
  specifically about manually replacing the database file (e.g. restoring
  from a backup) — it's unrelated to the GitHub deploy workflow below, since
  `neuroverse.db` is `.gitignore`d and never touched by a code sync at all.
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

## GitHub deployment workflow (replaces manual file-manager uploads)

The project is on bot-hosting.net's **new panel** (a separate system from
their older Pterodactyl-based legacy panel — confirmed this project was
already on the new panel, not mid-migration between the two). The new
panel's file manager includes a GitHub sync feature, and this project's
live server is now connected to a real GitHub repo.

**How a deploy actually happens, confirmed by direct, live testing (not
assumed from the panel's own docs, which were ambiguous on this point):**
1. Commit and push a change to the repo's default branch (`main`, after
   the initial `migration` branch was merged in).
2. Restart the bot from the panel.
3. That restart **both** pulls the latest commit from GitHub **and**
   starts the process — "auto-pull at restart" is a real, confirmed-working
   setting for this server, not just a theoretical option. There is no
   separate "click Sync" step needed for a routine update; the panel's
   manual Sync button is only for reconnecting/resetting the link itself
   (e.g. the very first connection, or if the link ever breaks).
4. This didn't add a step that wasn't already there — the bot always
   needed a restart to pick up any code change, GitHub or not, since
   editing a file on disk never affects an already-running process. What
   changed is that the restart now also handles getting the latest code,
   replacing manual file-manager uploads entirely.

**Sync strategy is Merge, never "Replace all files."** Replace would wipe
`neuroverse.db` and anything else present on the server but not tracked in
the repo (since those aren't in Git at all, Replace has no way to know
they should survive). Merge only touches files that exist in the repo,
leaving everything else — the database, its `-wal`/`-shm` siblings, the
`gifs*` folders, `.pyc` cache — completely alone. This was verified
directly: the first sync onto the already-running server was a
confirmed no-op with the bot coming up clean afterward, exactly as
expected for a repo that mirrored the live state at the time.

**What's tracked in Git vs. what stays server-only:** `.gitignore`
excludes `*.gif` (the `gifs*` folders — large, static, and not something
that benefits from version history), `*.db`/`*.db-shm`/`*.db-wal` (runtime
data, never source code — daily backups are the right tool for DB safety,
not Git), and the usual `__pycache__/`/`*.pyc`. Everything else — every
`.py` file, `CLAUDE.md`, `requirements.txt`, the `fonts/` directory — is
tracked and is what actually gets deployed on a restart.

**Two now-deleted files were confirmed to be dead MySQL-era leftovers
before this migration** (`db_schema.sql`, `neuroverse_mm26.sql`) — see the
"MySQL-era leftovers cleaned up" section below for the full story; they
were never part of what got imported into the new repo.

**No `.env` file exists on this server at all** — bot-hosting.net's new
panel holds environment variables (including the Discord bot token) on
their own separate dashboard tab, not as a file on disk. This is a cleaner
separation than a typical `.env`-based setup and means there was never a
risk of the token ending up in a `git add .` by accident — but it's still
worth a visual check of anywhere a bot client or API key gets constructed
before trusting that no token is hardcoded as a literal fallback
somewhere in the source instead.

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
fallback** — tactical/varsity/street/arcade all use
Black Ops One/Graduate/Bungee Inline/Press Start 2P for names too,
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

## /show_ladder: four newer styles, and the ones that were removed

**`championship` (Nabla) was deleted outright** — the user's call, the 3D
extruded variable font simply looked wrong at these sizes. It's gone from
the renderer, the dispatcher, `LADDER_STYLE_CHOICES` and every test style
list. Nabla itself is still in `fonts/` and `_FONT_NABLA_PATH` still
exists, but nothing uses it; don't reintroduce it for a new style without
asking first.

**Four styles added (Sept 2026):**
- `gridiron` — football field: green turf, a white yard line under every
  row, hash marks, slot number as a field number on both sidelines. The
  only style whose layout comes from the sport rather than a generic
  poster treatment. Black Ops One (shared with tactical).
- `blueprint` — technical schematic: blueprint blue, fine grid, corner
  registration marks, dimension leaders around the diff readout.
  Monospace, which is most of what makes it read as a drawing.
- `newsprint` — broadsheet sports page, and **the only light-background
  style** (every other one is dark, so it's the one that looks genuinely
  different in Discord's light theme). Graduate masthead (shared with
  varsity, but black-ink-on-paper reads nothing like varsity's navy/gold),
  halftone dots, hairline column rule. Names deliberately stay in the
  condensed bold: Graduate has no true lowercase, and real IGNs carry case
  distinctions worth keeping (`thebigbreesy` vs `TheBigBreesy`).
- `terminal` — CRT green phosphor, scanline overlay, prompt-led rows.
  Press Start 2P for the header banner only; **rows stay monospace on
  purpose** — a terminal whose columns don't line up stops looking like a
  terminal, and that font is far too wide per character for 16 rows.

**Second font batch (Sept 2026), user-supplied:** Anton, Bebas Neue,
Orbitron (static weights + variable), Share Tech Mono, VT323 — requested
specifically so the styles that had no display face could get one. Current
assignment:

| Style | Face | Notes |
| --- | --- | --- |
| `neon` | Orbitron | Black weight for the title, Bold elsewhere. Slashed zero is a design feature of the face, not a bug |
| `scoreboard` | Anton | Heavy condensed broadcast caps |
| `blueprint` | Share Tech Mono | Genuinely monospaced (verified) |
| `terminal` | VT323 | Genuinely monospaced; **every size in that style is ~1.36x** the monospace-family equivalent, because VT323's glyphs fill only ~0.73 of the em box (measured, not guessed) |
| `newsprint` | Graduate masthead | Shared with varsity; names stay condensed bold to keep IGN case |
| `gridiron` | Black Ops One | **Shares tactical's face by explicit preference** — don't "fix" this; the two look nothing alike otherwise. An earlier version used Bebas Neue, which being caps-only also flattened IGN case |
| `tactical` / `varsity` / `street` / `arcade` | Black Ops One / Graduate / Bungee Inline / Press Start 2P | First batch, unchanged |
| `clean` | none (condensed bold) | Identity is layout/colour, not type |
| `carnival` | Honk (title/labels only) | See the Honk-legibility note above |

**Bebas Neue is bundled but unused** now that gridiron reverted — it's
available for a future style, and a test keeps it loadable.

`_FONT_SHARE_TECH` and `_FONT_VT323` fall back to the **monospace** family,
not the condensed bold every other display font falls back to: both styles
depend on fixed-width columns lining up, so a missing bundled file has to
degrade to another monospace face rather than a proportional one. There's
a test for this; it checks the intent (every path in the chain names a Mono
face) as well as measuring whichever candidates exist locally, since most
are Linux system paths absent on a dev machine.

**Getting more fonts is still a manual step.** Fetching them is a known
dead end (see the font-loading section above: GitHub raw blocks automated
access, CDN routes need JS, and Google Fonts' CSS endpoint only serves
woff2, which PIL/FreeType cannot read at all). The working route is the
user downloading .ttf files from fonts.google.com into `fonts/` — which is
now a git commit plus a restart, not a file-manager upload. When a batch
arrives, check each one before wiring it up: that it loads at the sizes
actually used, that its cap height matches what the existing sizes were
tuned for (VT323 did not), whether it has real lowercase (Bebas Neue and
Graduate do not), and whether it's truly monospaced if a style depends on
that.

## /show_ladder: 25 styles, and the themed engine behind the newest 12

**There are exactly 25 ladder styles, which is exactly Discord's hard cap
of 25 choices per command parameter.** `LADDER_STYLE_CHOICES` has an
`assert` on it for this reason. A 26th style **cannot** be added as a
static choice — it would need an autocomplete callback instead (same
mechanism `/legacy`'s league field uses). Tests enforce both directions of
the picker/renderer contract: every offered style must render something
different from `classic` (a style that falls through looks like the picker
being ignored), and every implemented style must appear in the picker (the
four newest sat unreachable for a while precisely because they didn't).

**The 12 newest styles share one renderer, `_render_ladder_themed`,** driven
by a theme dict in `_LADDER_THEMES` — palette, fonts, badge shape, header
variant, row treatment, plus optional `bg_art` and `row_tint` hooks. The
nine older bespoke renderers were left exactly as they are; only new styles
go through the engine. Adding a style is a theme entry plus a picker choice,
and the shared row logic (centred names, the diff column, badge geometry)
can't drift per style. The full key list is documented in a comment above
the engine.

The 12: `gators` (blue/orange — see below), `ledboard` (LED dot-matrix,
Bitcount), `dossier` (typewritten scouting file, Special Elite),
`gameboy` (green LCD, DotGothic16), `cyberdeck` (circuit uplink, Audiowide),
`starfield` (deep space, Nova Square), `hazard` (industrial caution,
Wallpoet), `bubble` (pastel rounded, Keania One), `sketch` (pencil on paper,
Syne Mono), `prestige` (black/gold, Graduate), `paper` (quiet serif ledger,
Newsreader), `heatmap` (rows tinted by the diff, Anton).

**`gators` exists to satisfy an explicit request for a blue-and-orange
style** (Florida's colours). It uses the real pair — `#0021A5` blue,
`#FA4616` orange — and a test asserts the palette actually is blue and
orange rather than trusting the style's name. The first attempt used a
darker navy that read as generic; if this ever looks washed out, check it's
still on the true blue.

**Third font batch, user-supplied:** Audiowide, Bitcount Grid Double,
DotGothic16, Keania One, Newsreader, Nova Square, Special Elite, Syne Mono,
Wallpoet. Notes worth keeping:
- **Keania One's `8` is all but indistinguishable from its `S`** — real
  rosters render as `GCraneSCowboys`, `FunkyT19S`, `+S`. Confirmed on a
  rendered digit sheet, not assumed. It's title/label-only in `bubble`,
  exactly like Honk in `carnival`; names/stats/slot numbers/diff all use the
  condensed bold. A test enforces this. **Check any new display face this
  way before wiring it to names** — it's the second time this exact defect
  has appeared.
- Bitcount Grid Double and Syne Mono are genuinely monospaced; Newsreader
  ships a true italic (used for newsprint's kicker) and five optical sizes
  (the 24pt cut is the one wired up).
- Wallpoet measures 0.80x the baseline cap height and is very wide, hence
  `hazard`'s larger sizes and taller header.
- `newsprint` moved off the Graduate stand-in onto **Newsreader** now that a
  real newspaper serif is available; its names still stay condensed bold, as
  a serif at 24px on a tinted row is a real legibility step down.

## Faux-bolding, and which faces can take it

Several of these faces ship a **Regular weight only**, and PIL has no
synthetic bold. Where one reads too light, the options are a bigger size or
a 1px `stroke_width` outline in the glyph's own colour (supported by
`_draw_centered_name`, `_draw_diff` and `_draw_slot_badge` via a `stroke`
argument, and by the themed engine via `name_stroke`/`num_stroke`/
`title_stroke`).

**Stroke only works on a light, open face. It wrecks tight or heavy ones** —
all three of these were tried and reverted after looking at the render:
- Anton (`heatmap`): counters closed up, "Ruffis" read as "Buffis",
  "Rob926" as "Bob926".
- DotGothic16 (`gameboy`): pixel shapes filled in, "scotty" read as
  "ecotty", slot 16 as 18.
- VT323 (`terminal`): 'm' and 'W' filled in, "Packman425" read as
  "Packnan425".

Share Tech Mono (`blueprint`) is the one that takes it cleanly, and is the
only place `stroke=1` survives. Everywhere else the fix was size: blueprint
and terminal are both a size up (terminal now ~1.55x the monospace-family
equivalent), heatmap went 42/25 → 46/27. A test pins this so a future
"make it bolder" doesn't reintroduce the smudging.

**`gameboy` was inverted to the real DMG panel** — dark ink on the pale
yellow-green LCD (`9bbc0f` / `8bac0f` / `306230` / `0f380f`), not light text
on dark green. The first version was light-on-dark and both muddy and hard
to read; inverting it also freed up enough contrast to colour the two diff
signs differently, which the dark version couldn't do at all (both signs
had to share one colour there).

## Decals: laurels, helmets, and the value of testing a shape in isolation

`prestige` has gold laurel branches flanking the title
(`_draw_laurel_branch` / `_draw_leaf`), and `varsity` has blank football
helmet decals either side of its title (`_helmet_layer` / `_paste_helmet`).
Both were requested specifically, and both are the sort of thing a later
palette tweak can silently drop, so there's a test asserting each renderer
still references its decal helper.

**The laurels took two attempts as well, and the second failure is the
instructive one: mirroring.** Generating the facing branch by negating
coordinates produces a *180-degree rotation*, not a horizontal mirror — the
pair ends up pointing the same way round instead of opening toward each
other like a wreath. Both decals therefore draw one orientation onto an RGBA
layer and use `transpose(FLIP_LEFT_RIGHT)` for the other side
(`_laurel_layer`/`_paste_laurel`, `_helmet_layer`/`_paste_helmet`). The
laurels also gained a bezier stem, alternating tapering leaves, a tip curl
and berries after "more flourishy" feedback, and the pair sits wider apart —
with `title_pad` on the theme reserving room so a long matchup title can't
run under them.

**The helmet took two attempts, and the useful lesson is how it was
caught.** The first version drew outline arcs straight onto the image and
read as "a circle with an eye" — the shape was wrong, not the placement.
Rendering the silhouette *alone* on a plain background at three sizes made
that obvious immediately, where it was nearly invisible inside a full
ladder render. The working version is a filled silhouette on its own RGBA
layer (shell, jaw, ear hole, a pieslice bite for the face opening, two
facemask bars and a chin bar), pasted in — which also means the mirrored
copy is a `FLIP_LEFT_RIGHT` rather than a second set of hand-mirrored
coordinates. Laurels needed a second pass too, for position: at radius 62
centred on y=58 they ran off the top edge and tangled with the frame's
corner ticks.

**A pixel assertion has to be computed against the shapes, not eyeballed.**
The helmet test checks a point that's transparent only because of the
face-opening cut. The first point chosen (100, 100) turned out to be
outside the shell ellipse entirely, so it was transparent either way and
the test passed even with the cut removed — confirmed by actually deleting
the cut and watching the test still pass. The replacement (88, 55) was
derived from the ellipse maths and verified to fail without the cut.

**`bubble` keeps Keania One for names and numbers despite the ambiguity.**
Its '8' is nearly identical to its 'S' (so `GCrane8Cowboys` renders as
`GCraneSCowboys`), which is the same defect that keeps Honk out of
carnival's rows — but here it was raised explicitly and the look was
preferred over the legibility. There's a test pinning that decision; don't
revert it on legibility grounds without asking.

**`gators` took three passes; the two rejected ones are worth knowing.**
Bebas Neue read as "a spreadsheet with team colours" (now Audiowide, which
also keeps lowercase so IGN casing survives). The replacement then used 1x
chevron polygons behind the title, which came out **blocky** — and put white
type on orange, which was **hard to read**. Current version: all diagonal art
supersampled (see `_ART_SUPERSAMPLE`), a two-tone blue wedge behind the title
instead of chevrons, orange kept to a swept top band and a thin base rule
well clear of the text, the home band flipped to light-with-navy-type, and
navy numerals on the orange badges. If a future tweak puts white back on that
orange, that's the same contrast problem returning.

**PIL antialiases neither polygons nor lines.** Any art that is mostly
diagonals — laurels, chevrons, swept bands, the heatmap wedges — must be
drawn at `_ART_SUPERSAMPLE` (4x) and downscaled with LANCZOS, or the edges
stair-step. This is the actual cause of "blocky", not the shapes themselves.

`heatmap` got the same angling treatment (slanted badges plus a diagonal
header field) alongside its size bump.

**`newsprint` is set in Newsreader throughout** — masthead, column heads,
names, slot numbers, with the true italic on the kicker and stat text. An
earlier pass changed only the masthead and left the body in the generic
condensed bold, which still read as unstyled; if it ever looks "default"
again, check the *body* font, not the title.

**Background art that scatters elements (`starfield`, `cyberdeck`,
`dossier`, `bubble`) uses a seeded `random.Random`**, so the same ladder
renders byte-identically every time. There's a test for it; an unseeded
version would shimmer between otherwise identical calls.

## Ladder rows: offensive OVR, and the middle difference column

**`matchup_ladder.our_total_ovr` is NOT our team's overall despite the
name — it holds the *opponent's* team overall.** `ladder_flow.py`'s
opponent CSV flow writes `opp['total_ovr']` into that column, and
`classic` labels it "Opp TOT" correctly. Nothing should ever use it for
our side; our player's numbers come from `players` (`off_ovr` via
`get_ladder_snapshot`'s join, `total_ovr` for team overall).

**`_ladder_row_fields`'s `our_stat` used to be
`r.get('ladder_rank') or r.get('our_off_ovr')`** — and `ladder_rank` is
non-None for any league with ladder weights configured, which in practice
is all of them (the `pwr_rank_weights` table ships global `ladder`-category
rows). So what the poster styles actually showed next to our players was a
weighted rank score, not an OVR. It's `off_ovr` unconditionally now.
`classic` still has its own separate Ladder Rank column, so that number
didn't disappear anywhere it was labelled.

**New middle column: `off_ovr - opp_def_ovr`**, pre-formatted with a sign
in `_ladder_row_fields` as `diff`/`diff_val`, drawn by the shared
`_draw_diff()` (green-ish positive / red-ish negative in each style's own
palette). It draws **nothing** when either OVR is missing rather than a 0,
which would read as an even matchup. `_DIFF_GUTTER` (46px either side of
the midline) is the space every style reserves for it; the styles that had
a full-height centre divider now split that rule above and below the
number. `clean` had no end-of-row slot badges to fall back on, so its
centre circle became a pill holding the slot number and the diff together.

## Ladder player names are centred in their column

Explicit request, applied to every style including `classic`. All of the
geometry lives in one helper, `_draw_centered_name()` — each style passes
only its column bounds, colours, and a `fitter` lambda, which keeps each
style's font constant inside that style's own source where the
font-choice tests can still see it (`test_carnival_style_player_names_use_
reliable_font_not_honk` and friends scan for exact call shapes like
`_fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD` — keep that shape when
touching a renderer).

Two things that are easy to get wrong here:
- **The fit budget has to be measured from the centre outward, not from
  the column width.** A centred name grows in *both* directions, so it
  has to fit between the centre and whichever edge is nearer, after
  subtracting the stat's width and gap on the side the stat sits on.
  Otherwise a long name slides under the slot badge on one side while
  crossing the centre divider on the other.
- **`_fit_text` returns its floor size even when the text still doesn't
  fit**, so `_draw_centered_name` truncates (via `_truncate_to_width`,
  suffix `..` rather than `…` — the bundled pixel/display fonts only
  cover basic Latin and would render a missing-glyph box). It returns
  `(font, text_as_drawn)`, and the drawn text is what a caller measuring
  the result must use.

`_render_table` grew a `'C'` alignment (see `_cell_text_x`) for classic's
two name columns; its numeric columns stay right-aligned so digits still
line up. `/rank`, `/scores` and `/stats` pass the same aligns they always
did and are unaffected.

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

## League list comes from the teams table, not a hardcoded dict

`LEAGUE_NAMES` used to be a hardcoded `{team_id: display name}` dict,
**duplicated verbatim in four modules** (`optimized_bot.py`,
`sheet_image.py`, `siege.py`, `ladder_flow.py` — the latter three can't
import `optimized_bot` without a circular import, so each kept its own
copy). All four still listed NI/NeuroInverse well after that league was
deleted from the `teams` table, which is exactly the drift this arrangement
invites.

All four now call **`db.load_league_names_sync()`** at import instead. It
reads `SELECT id, name FROM teams` with the **stdlib `sqlite3` driver,
synchronously, read-only** (`file:...?mode=ro`). The sync/stdlib part is not
laziness — it's forced: `@app_commands.choices(league=LEAGUE_CHOICES)` is
evaluated *while `optimized_bot`'s module body is still executing*, long
before `db.init()` or any event loop exists, so an `await` is impossible
there. A missing db file or missing `teams` table returns `{}` with a log
line rather than raising, so a fresh install (or a test run in a directory
with no db) can still import the bot. `db.list_teams(conn=None)` is the
async counterpart for normal runtime use, and takes an archive `conn`.

Consequences worth knowing:
- A league added/renamed/deleted in `teams` is picked up **on the next
  restart**, with no code change. Deleting a league's row is now genuinely
  sufficient to retire it.
- `/league`'s runtime add/rename path goes through
  `_sync_league_name(lid, name)`, which writes the new name into *all four*
  modules' maps. Updating only `optimized_bot`'s (the old behavior) left
  `/rank` image titles and siege labels showing the stale name until the
  next restart.
- Slash-command *choices* still can't be updated at runtime — they're fixed
  when the command is registered with Discord — so a league added via
  `/league` appears in `LEAGUE_CHOICES` for future registrations but needs a
  `/sync` to show up in the picker. That predates this change.
- A test (`test_no_module_hardcodes_the_league_list`) scans all four
  modules' source and fails if a league-name literal reappears, so the
  hardcoded list can't quietly come back.

## /legacy league options are per-season, from the archive's own teams table

Leagues change year over year, so the **live** league list is the wrong list
for an archived season: a 2026 archive can contain a league since deleted
(NI) and lack one created afterward. `/legacy`'s league field therefore
can't use `@app_commands.choices` at all — static choices are fixed at
registration time and **cannot depend on another argument's value**.

`archive_league_autocomplete()` reads the already-entered year via
`interaction.namespace.year` (same mechanism as `league_player_autocomplete`)
and lists that archive's own `teams` rows. It falls back to the live list
when year isn't filled in yet / isn't a valid year / has no archive, so the
field is never mysteriously empty mid-typing. **`year` was moved to be the
first parameter** on all four league-taking `/legacy` subcommands (`rank`,
`stats`, `scores`, `show_ladder`) so Discord prompts for it before league —
the autocomplete has nothing to scope by otherwise.

Because an autocomplete only *suggests* values and never restricts what
Discord accepts, each of those commands re-validates via
**`_resolve_archive_league()`**, which returns that season's display name for
the league or sends `common.invalid_league` and bails. This also replaced
every `LEAGUE_NAMES[league]` in the `/legacy` commands — for an
archive-only league that's a **`KeyError`, not a miss**, which is a real
crash reproduced by
`test_legacy_rank_serves_a_league_that_no_longer_exists`. `send_rank_image`,
`send_stats_image`, and `_build_ladder_image` grew an optional
`league_name=` for this, so archive output is titled with the season's own
name rather than today's.

## Windows note for running the suite

`tests.py`'s `test_every_command_marked_admin_in_manual_actually_requires_admin`
reads `optimized_bot.py` as text to `ast.parse` it. It had no `encoding=`
argument, so on Windows it decoded as cp1252 and died on the emoji in the
bot's user-facing strings (`UnicodeDecodeError: 0x8f`) — a pre-existing
failure invisible on the Linux host. Now passes `encoding="utf-8"`. If a
future test opens a source file, pass the encoding explicitly.

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


## NeuroSeason — the NFL-shaped season gamemode (`neuroseason.py`)

A season played by **individual members**, not by leagues — up to 32 people
from any league sign up, get drawn into two conferences and their divisions,
and play 18 matchups each. Results come in from a screenshot of the game's
own Head to Head Arena "Game Stats" screen. When the last regular-season
match is reported, a playoff field seeds itself and each round generates the
next until a champion is recorded.

**Four decisions the user made explicitly when this was built — don't
silently revisit them:**
- **Sub-32 fields auto-scale the layout.** Always two conferences; divisions
  per conference is "as many as fit at 3+ members each, capped at 4", which
  lands exactly on the NFL's 2x4x4 at 32. Not a lookup table of special
  cases, and not ghost teams padding the field to 32.
- **Everyone plays exactly 18, at every field size.** Small fields reach 18
  by repeating opponents, not by playing a shorter season.
- **Signups are slash-command self-serve** (`/neuroseason join season:N
  player:<ign>`), open to anyone — no Discord-account linking, no button UI,
  and deliberately nothing stopping someone signing another member up.
- **The playoff field is 16.** Below 16 members that literally can't be
  drawn, so it falls to the largest power of two that fits (12 members → 8,
  7 → 4). It is never padded with byes or ghosts.

### The four new tables — and why they're created differently to every other one

`neuro_seasons`, `neuro_season_members`, `neuro_season_matches`,
`neuro_season_stats`. **No other table in this database is created from
code** — the rest were made by hand on the server long ago, and `db.py` only
ever `ALTER`s them. There is no shell access to do that with anymore, so
these four live in **`db.NEUROSEASON_SCHEMA`** (a single SQL string near the
bottom of `db.py`), executed as `CREATE TABLE IF NOT EXISTS` by
`_migrate_neuroseason_schema()` from `_migrate_schema()` on every startup.
`tests.py`'s `setup_db()` builds its copy from **that same constant** rather
than pasting the DDL into the test `SCHEMA` block — a schema change can't
pass tests while breaking production.

Worth knowing about the columns:
- `neuro_season_members.team_id` is the league the player belonged to **at
  signup**, same historical-attribution principle as `game_scores.team_id`.
  A mid-season transfer doesn't move them out of the season or rewrite what
  they've already played.
- `get_neuro_season_members()` has **no status filter at all**. A season
  roster is frozen at signup, so a member who goes inactive still owns their
  matchups and their stats. Relatedly, `neuroseason._resolve_player()` falls
  back to an unfiltered `players` lookup when `db.get_player()` (which
  excludes `status='I'`) comes back empty — without that, a member going
  inactive in week 9 would silently make their own remaining nine matchups
  impossible to report. There's a test.
- `match_num` is unique per season and **playoff rounds continue the regular
  season's numbering** rather than restarting it, because that number is
  what a player types into `/seasonmatch`.
- `record_neuro_season_result()` **replaces** a previously-reported result
  instead of adding a second one, using the same explicit check-then-act
  pattern as `update_player_score`/`log_siege_score` (SELECT for the
  existing row, UPDATE it by its own id, INSERT only if absent). This is the
  third time this exact duplicate-row class of bug has been designed around
  in this codebase; there's a test that reverts it and confirms totals
  inflate.

### Schedule generation (`build_schedule`)

Runs in four steps: division rivals twice (6 at a 4-member division), one
other division in-conference in full (4), one division cross-conference in
full (4), then a fill stage to reach 18 — same-conference-unplayed first
down to the last two games, then cross-conference-unplayed, then anything at
all. At 32 members that produces exactly the requested 6/4/4/2/2, verified
per-member by a test rather than just in aggregate.

**The fill stage always pairs the two neediest members.** That ordering is
load-bearing, not cosmetic: it's what keeps the remaining-degree sequence
realisable (the Havel-Hakimi argument, which holds for multigraphs whenever
the degree sum is even), so the unrestricted final pass can never strand
someone needing games with nobody left to play them. A "prefer a fresh
opponent" ordering looks nicer and can strand.

**The calendar is ~20 weeks for an 18-game season, and that is correct.**
Division pairs meet twice and can't do so in the same week, which pushes the
minimum week count above the game count regardless of how well the packing
works (Vizing, for multigraphs). Each member therefore gets about two byes.
If someone reports "why are there 20 weeks", that's the answer — it isn't
the packer being sloppy. Week assignment fills one week at a time, taking
the most-booked members' games first, best of several **seeded** attempts
(`_season_rng(season_id)`), so a season always regenerates identically
rather than shimmering — same principle as the seeded background art in
`sheet_image.py`.

### Standings, tiebreakers and seeding

`compute_standings` tracks overall, division and conference records
separately (all three are tiebreakers) plus points for/against. Only
`status='complete'` matches count — an unplayed matchup is not a loss.

`rank_rows` applies the four requested tiebreakers in order: head-to-head,
division record, conference record, points for, with `player_id` last so the
order is stable rather than arbitrary. Head-to-head is computed **relative
to the tied group** (for two, literally their record against each other).
This is a deliberate simplification of the full NFL rulebook, which then
drops to common games, strength of victory and eventually a coin toss — the
four asked for are applied exactly, and the rest isn't implemented.

`compute_seeds` seeds **every division winner above every wild card**, even
a wild card with a better record — the NFL rule, and the reason seeding
isn't just "sort the conference by record". The test for this had to be
rewritten once: the first fixture happened to have the division winners also
leading on record, so it passed identically against a plain record sort.
It now asserts the discriminating order *and* asserts the fixture still
discriminates.

`build_playoff_round` **re-seeds every round** (best remaining vs worst
remaining), NFL-style, rather than following a fixed bracket path. Rounds
are created one at a time as the previous one finishes, so
`_current_playoff_round` finds the furthest round present.

### /seasonmatch and the confirmation step

The screenshot shows **NFL team logos, never player names** — the bot cannot
work out whose column is whose. That is the entire reason the command takes
`left_player` and `right_player`: they describe the *picture*, not the
fixture, and the match row decides which of them is the home side
(`SeasonMatchConfirmView._sides()`). A test puts the away player in the left
column specifically to pin this.

**Nothing is written until a human confirms.** Vision misreads are a real,
already-observed failure mode on this project (see the `/ladder` OVR sanity
check), and a wrong season result is harder to notice than a wrong OVR
because it silently moves the standings and the playoff seeding. The review
embed shows every extracted stat; "Fix the score" opens a modal (from a
button — a modal can never be opened from another modal's submission).
Only the two scores are editable: they decide the match, the standings and
every tiebreaker, and a modal caps at five components anyway.

A **playoff match can't be saved as a tie** — there's no way to send two
players into the next round, and inventing a tiebreak there would be the bot
deciding a playoff game.

`agent.extract_season_match_from_screenshot()` is a second, separate
extractor in `agent.py` (the ladder one is untouched). Its prompt explicitly
forbids reordering the columns by score or winner, and an unreadable stat
must come back `null`, never `0` — a real 0 is meaningful on that screen (0
turnovers is a clean game), so a 0 standing in for "couldn't read it" would
put a fabricated stat into the season record. **Not yet tested against a
real screenshot** — no network access in this sandbox — so it's worth a live
`/seasonmatch` run after any prompt change, same caveat as the ladder
extractor.

### Stage advancement

`advance_season(season_id)` is called after every saved result and is safe
to call at any time — it only acts when the current stage or round has zero
pending matches, so an early call is a no-op. `/neuroseason advance` is an
admin fallback for the case where a result corrected after the fact left a
stage stuck. Every seed is cleared before being re-set when the playoffs
open, so a member who missed the field can't keep a seed from an earlier
call.

### Testing notes specific to this feature

- The new tests use a **hand-written `_FakeInteraction`**, not `MagicMock` —
  its `followup` has `send()` and nothing else, so code that mistakes a
  followup for a response object fails the way it would in production. This
  is the lesson from the `/ladder` manual-match crash that a `MagicMock`
  hid completely.
- `tests.py`'s aiohttp stub gained `ClientSession`: `agent.py` annotates with
  it at import time, so the module couldn't be imported by the suite at all
  before (it never had been).
- Every new test was mutation-checked — the code it covers was broken on
  purpose and the test confirmed to fail — rather than only confirmed to
  pass. That's what caught the non-discriminating seeding fixture above.
