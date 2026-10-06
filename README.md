# Reborn Bot

A Discord bot for running a **Madden Mobile** league system: score tracking, power rankings, ladder matchups, defensive stats, siege tracking and stats, NFL-style member seasons, tournaments, and archived past seasons — all as slash commands, fully localized in five languages.

Built for the Reborn league system.

> **Branch note.** This is `reborn_main`, the branch the Reborn bot deploys from. It shares a repository with Neuroverse's `main` but is **no longer identical to it**: the gamemode module, its command, its database tables, the default database filename and all user-facing branding were renamed from Neuro* to Reborn*. Reborn also runs its own Discord server, bot application, token and host. A `main` → `reborn_main` merge is therefore a curated operation, not a fast-forward — see [CLAUDE.md](CLAUDE.md) → "The Reborn fork: what actually differs" for the full delta and the merge rules.

The bot is built as a multi-league system and still is — Reborn simply has one league in it: **`RX` — CHRISTiansReborn** (formerly `NX` / NeuroChristians, renamed on the way out of Neuroverse). The league list is read from the database's `teams` table at startup, never hardcoded, so adding a second league is a row, not a code change.

---

## Highlights

- **Score tracking** — per-player, per-day scoring with proper handling of excused absences, forfeited drives, and genuine 0-point games as distinct states.
- **Defensive tracking** — `/dscore` logs points allowed per drive, turnovers forced (fumble/interception/safety) and the offensive OVR faced; `/dstats` and `/dscores` read it back as a league table and a per-player history.
- **Rendered image output** — `/rank`, `/scores`, `/stats`, and `/show_ladder` produce PNG tables via Pillow (with bundled fonts, so rendering doesn't depend on host OS font packages). `/show_ladder` ships 25 visual styles: `classic`, `neon`, `clean`, `scoreboard`, `tactical`, `varsity`, `arcade`, `street`, `carnival`, `gridiron`, `blueprint`, `newsprint`, `terminal`, `gators`, `ledboard`, `dossier`, `gameboy`, `cyberdeck`, `starfield`, `hazard`, `bubble`, `sketch`, `prestige`, `paper`, and `heatmap`. Each ladder row shows our player's offensive OVR, the opponent's defensive OVR, and the difference between them in a middle column.
- **Configurable rankings** — power rank and ladder rank are weighted formulas over dozens of stat factors, tunable per league through `/weights` and inspectable via `/factors`. Every average has a *fumble-adjusted* counterpart (fumbles excluded from the denominator rather than counted as a scored drive).
- **Ladder builder with screenshot extraction** — `/ladder` can read a League vs League screenshot through Claude Haiku vision to pull the opponent roster, league name, division, and rank. Names that can't be matched exactly are handed back to an admin for manual matching rather than silently dropped, and suspicious OVR changes (relative to that player's own previous value) are held for review before they're applied.
- **Siege mode** — full match lifecycle: opponent nodes with mods, per-player scoring against nodes, live status embeds, corrections, and per-mod splits.
- **RebornSeason** — an NFL-shaped season for individual members: signups, a conference/division draw, an 18-matchup schedule generated for any field size, screenshot-read results, NFL tiebreakers, and a self-seeding 16-team playoff.
- **Multi-season archives** — `/legacy` runs the same lookups against a previous season's database file, opened read-only at the SQLite level.
- **Five languages** — every user-facing string goes through `i18n.t()`: English, Spanish, French, Portuguese, German.

---

## Commands

Run `/manual` in Discord for the full, localized, paginated reference. Summary:

### Scoring & stats
| Command | Description |
| --- | --- |
| `/score` | Record a player's score for a day |
| `/dscore` | Record a defensive score — one opponent faced all 3 drives |
| `/dscore_multiple` | Record a defensive score drive-by-drive (different opponents) |
| `/dstats` | A league's defensive totals and averages (image) |
| `/dscores` | A player's defensive history over a date range |
| `/avg` | A player's average (plain and fumble-adjusted), by window or division |
| `/streak` | Current consecutive-game streaks (24+ scoring, and no-dropped-drive) |
| `/history` | A player's score history over a date range |
| `/player` | Full stats card for one player |
| `/rank` | Power ranking table for a league (image) |
| `/stats` | League-wide averages (image) |
| `/scores` | Score grid for a league across a date range (image) |
| `/ovr` | Update a player's team overall |

### Matchups & ladder
| Command | Description |
| --- | --- |
| `/ladder` | Build today's ladder interactively — from a screenshot or manually |
| `/show_ladder` | Render a league's ladder matchups as an image |
| `/matchup` | Edit matchup info and player scores for a given day |
| `/opp` | Show a player's opponent in today's ladder |
| `/status` | Today's matchup status for a league |

### Siege
`/siege` · `/node` · `/siegescore` · `/siegestatus` · `/updatesiege` ·
`/siegefinal` · `/siegesplits` · `/siegehistory`

### RebornSeason
An NFL-shaped season played by individual members rather than by leagues: up to
32 sign up, get drawn into two conferences and their divisions, and play 18
matchups each — division rivals twice, a full division in-conference, a full
division cross-conference, and the rest filled in. Results are read from the
Head to Head Arena "Game Stats" screenshot, or typed in by hand when nobody
remembered to take one. When the last one is in, a 16-team playoff seeds
itself and each round generates the next until a champion is crowned.

| Command | Description |
| --- | --- |
| `/rebornseason create` | **Admin.** Open signups for a new season |
| `/rebornseason join` / `leave` | Sign up, or withdraw before kickoff |
| `/rebornseason start` | **Admin.** Draw the divisions and build the schedule |
| `/rebornseason list` | Every season and its status |
| `/rebornseason standings` | Standings by division — overall, division and conference records; filter by conference or division |
| `/rebornseason schedule` | The slate, filterable by player or week |
| `/rebornseason bracket` | The playoff bracket |
| `/rebornseason advance` | **Admin.** Fallback if a corrected result left a stage stuck |
| `/seasonmatch` | Log a played matchup — from a result screenshot, or entered by hand |
| `/seasonstats` | A player's stats for one season, or their whole career |

Fewer than 32 signups doesn't change any of that: the layout scales (two
conferences always, as many divisions as fit at three-plus members each, capped
at four) and everyone still plays exactly 18. Below 16 members a 16-team
bracket can't be drawn, so the playoff field drops to the largest clean power
of two instead of being padded with byes.

### Roster management
| Command | Description |
| --- | --- |
| `/register` | Register a new player |
| `/transfer` | Move a player to a different league |
| `/inactive` / `/reactivate` | Change a player's roster status |
| `/nick` / `/rename` | Change a player's bot nickname |
| `/ign` | Update a player's real in-game name |
| `/openspots` | Open roster spots per league (18-player cap) |

### League config & admin
`/league` · `/weights` · `/factors` · `/newday` · `/sync` · `/test` · `/nukeguildcmds` · `/reloadgifs` · `/addgif`

### Tournaments
`/tournament_start` · `/tournament_result` · `/tournament_bracket` · `/tournament_list`

### Past seasons
`/legacy rank|stats|player|history|scores|show_ladder year:YYYY` — identical arguments to the live commands, plus a season year.

Admin-gated commands require one of the roles `Administrator`, `League Owner`, or `Madden Admin`.

---

## Running it

**Requirements:** Python 3.11+ (uses `zoneinfo`), plus `requirements.txt`.

```bash
pip install -r requirements.txt
```

**Environment** (a `.env` file in the project root works):

| Variable | Required | Purpose | Reborn value |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | yes | Bot token | Reborn's own bot application — not a second copy of Neuroverse's |
| `DB_PATH` | no | SQLite path override | leave unset — defaults to `reborn.db` |
| `DEV` | for scheduled tasks | Enables the daily new-day and daily backup loops when set to `production` | `production` |
| `ANTHROPIC_API_KEY` | for `/ladder` and `/seasonmatch` screenshots | Claude vision extraction | set (both commands have manual fallbacks without it) |

On bot-hosting.net these live on the panel's environment tab, not in a `.env` file.

**If the database can't be found, nothing errors.** The bot creates an empty one, migrates it cleanly, and starts with no leagues, no players and no history. The only symptom is a `No leagues loaded from the teams table` line in the log and empty league pickers in Discord — so if you see that, check the filename on the server before looking anywhere else.

```bash
python optimized_bot.py
```

The schema is created and migrated automatically on every startup — there is no separate migration step or schema file to apply. Archived seasons are expected as `reborn_<year>.db` next to the live database; that prefix is a literal in `db._archive_path()` and doesn't follow `DB_PATH`, so name archives that way regardless of what the live file is called. Bundled fonts live in `fonts/` and must sit alongside `sheet_image.py`.

**GIFs are not in the repo.** `.gitignore` excludes `*.gif`, so a server deployed purely from Git has no `gifs*` folders. Score GIFs degrade gracefully (no GIF is sent), but the `Kobe!`, `Brunson!` and `bingbong` chat triggers log an `IndexError` instead of doing nothing, and `/addgif` fails until the target folder exists. Create the folders on the server and upload GIFs through `/addgif` if they're wanted.

### Backups

`db.backup_database()` runs on startup and once daily, using SQLite's online backup API. Backups land in `backups/` and are pruned after 14 days.

### Replacing the database file

The database runs in WAL mode. **Stop the bot, delete any leftover `.db-wal` / `.db-shm`, then upload/replace the `.db`, then start again.** Swapping the file under a running process races with the live writer and can corrupt it or silently lose recent transactions.

This applies to the very first upload of `reborn.db` too — upload it with the bot stopped, set `DB_PATH=reborn.db`, then start. The database is `.gitignore`d, so a GitHub sync never touches it; keep the sync strategy on **Merge**, since "Replace all files" would delete it along with everything else on the server that isn't tracked in the repo.

---

## Project layout

| File | Role |
| --- | --- |
| `optimized_bot.py` | Bot entrypoint and most slash commands |
| `db.py` | All database access, schema migrations, stat computation |
| `i18n.py` | Every user-facing string, all five languages |
| `siege.py` | Siege game mode |
| `ladder_flow.py` | The `/ladder` interactive builder |
| `rebornseason.py` | The RebornSeason gamemode: scheduling, standings, playoffs |
| `agent.py` | Claude vision extraction for ladder and season-match screenshots |
| `sheet_image.py` | Pillow-based PNG table and poster rendering |
| `tournament.py`, `status.py`, `newday.py` | Smaller feature areas |
| `tests.py` | Test suite (530+ tests) with a full discord.py stub |

## Tests

```bash
python tests.py
```

No Discord connection, network access, or API key needed — `tests.py` includes a complete discord.py stub and an in-process SQLite fixture. `/test` also runs the suite from inside Discord and posts the results.

Contributors: see [CLAUDE.md](CLAUDE.md) for the accumulated architectural notes, database invariants, and platform gotchas — most of them cost real debugging time to find and are easy to reintroduce.
