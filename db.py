"""
db.py — SQLite database helpers using aiosqlite.

The database file lives at DB_PATH (default: neuroverse.db).
No host, no credentials, no network — just a file in the bot directory.
"""

import os
import asyncio
import datetime
import aiosqlite
from logger_config import global_logger as logger

DB_PATH = os.getenv("DB_PATH", "neuroverse.db")
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)) or ".", "backups")
BACKUP_RETENTION_DAYS = 14
_db: aiosqlite.Connection | None = None


async def init():
    """Open the SQLite connection. Safe to call multiple times — no-ops if already connected."""
    global _db
    if _db is not None:
        return
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _migrate_schema()
    logger.info(f"SQLite connected → {DB_PATH}")


async def _migrate_schema():
    """
    Lightweight, idempotent migrations that run on every startup. Safe to
    call repeatedly — each ALTER TABLE is wrapped individually so an already-
    applied migration (duplicate column) is silently skipped rather than
    blocking the ones after it.
    """
    migrations = [
        ("game_scores", "fumbles", "ALTER TABLE game_scores ADD COLUMN fumbles INTEGER DEFAULT 0"),
        ("defense_scores", "drive1_outcome", "ALTER TABLE defense_scores ADD COLUMN drive1_outcome TEXT"),
        ("defense_scores", "drive2_outcome", "ALTER TABLE defense_scores ADD COLUMN drive2_outcome TEXT"),
        ("defense_scores", "drive3_outcome", "ALTER TABLE defense_scores ADD COLUMN drive3_outcome TEXT"),
        ("defense_scores", "drive1_ovr", "ALTER TABLE defense_scores ADD COLUMN drive1_ovr INTEGER"),
        ("defense_scores", "drive2_ovr", "ALTER TABLE defense_scores ADD COLUMN drive2_ovr INTEGER"),
        ("defense_scores", "drive3_ovr", "ALTER TABLE defense_scores ADD COLUMN drive3_ovr INTEGER"),
        ("defense_scores", "drive1_turnover_down", "ALTER TABLE defense_scores ADD COLUMN drive1_turnover_down TEXT"),
        ("defense_scores", "drive2_turnover_down", "ALTER TABLE defense_scores ADD COLUMN drive2_turnover_down TEXT"),
        ("defense_scores", "drive3_turnover_down", "ALTER TABLE defense_scores ADD COLUMN drive3_turnover_down TEXT"),
        ("defense_scores", "drive1_turnover_distance", "ALTER TABLE defense_scores ADD COLUMN drive1_turnover_distance TEXT"),
        ("defense_scores", "drive2_turnover_distance", "ALTER TABLE defense_scores ADD COLUMN drive2_turnover_distance TEXT"),
        ("defense_scores", "drive3_turnover_distance", "ALTER TABLE defense_scores ADD COLUMN drive3_turnover_distance TEXT"),
        ("defense_scores", "drive1_turnover_play", "ALTER TABLE defense_scores ADD COLUMN drive1_turnover_play TEXT"),
        ("defense_scores", "drive2_turnover_play", "ALTER TABLE defense_scores ADD COLUMN drive2_turnover_play TEXT"),
        ("defense_scores", "drive3_turnover_play", "ALTER TABLE defense_scores ADD COLUMN drive3_turnover_play TEXT"),
        ("defense_scores", "drive1_turnover_forced_by", "ALTER TABLE defense_scores ADD COLUMN drive1_turnover_forced_by TEXT"),
        ("defense_scores", "drive2_turnover_forced_by", "ALTER TABLE defense_scores ADD COLUMN drive2_turnover_forced_by TEXT"),
        ("defense_scores", "drive3_turnover_forced_by", "ALTER TABLE defense_scores ADD COLUMN drive3_turnover_forced_by TEXT"),
    ]
    for table, column, sql in migrations:
        try:
            await _db.execute(sql)
            await _db.commit()
            logger.info(f"Migration applied: {table}.{column}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                pass  # already applied on a previous startup — nothing to do
            else:
                logger.error(f"Migration failed for {table}.{column}: {e}")

    # players.fourth_downs / players.fourth_down_convs are dead columns —
    # leftovers from mirroring the original Excel import schema, never read
    # from or written to anywhere in the codebase. The real, working 4th-down
    # tracking lives entirely in game_scores (one row per player per game,
    # which is the correct shape for a per-game stat). Dropping them here.
    drops = [
        ("players", "fourth_downs", "ALTER TABLE players DROP COLUMN fourth_downs"),
        ("players", "fourth_down_convs", "ALTER TABLE players DROP COLUMN fourth_down_convs"),
    ]
    for table, column, sql in drops:
        try:
            await _db.execute(sql)
            await _db.commit()
            logger.info(f"Migration applied: dropped {table}.{column}")
        except Exception as e:
            if "no such column" in str(e).lower():
                pass  # already dropped on a previous startup — nothing to do
            else:
                logger.error(f"Migration failed dropping {table}.{column}: {e}")

    # Data migration (not a schema change): every player's real_ign should be
    # set to something — players registered before this was enforced, or
    # registered without providing one, can end up with real_ign NULL. Back
    # those in with the player's current nickname. Safe to run every startup:
    # only touches rows that are still NULL, so it's a no-op once caught up.
    try:
        cur = await _db.execute("UPDATE players SET real_ign = ign WHERE real_ign IS NULL")
        await _db.commit()
        if cur.rowcount:
            logger.info(f"Migration: backfilled real_ign for {cur.rowcount} player(s) with no real_ign set")
    except Exception as e:
        logger.error(f"Migration failed for players.real_ign backfill: {e}")

    # An excused entry (is_excused=1) should store score as NULL — there is
    # no real score for that entry at all, unlike a missed/forfeited drive
    # (is_forfeit=1), which is genuinely 0. Earlier versions of /score and
    # the matchup bulk-editor both stored 0 for excused entries too; fix any
    # already sitting in the database to match the corrected behavior. Safe
    # to run every startup — only touches rows that still have the old
    # score=0 value, so it's a no-op once caught up.
    try:
        cur = await _db.execute("UPDATE game_scores SET score = NULL WHERE is_excused = 1 AND score = 0")
        await _db.commit()
        if cur.rowcount:
            logger.info(f"Migration: cleared score to NULL for {cur.rowcount} excused game_scores row(s)")
    except Exception as e:
        logger.error(f"Migration failed for game_scores excused-score cleanup: {e}")

    # game_scores' uniqueness was (player_id, game_date, event_type) — meaning
    # a correction via /score, which never specifies event_type (always None),
    # could silently fail to match an existing row that already has a non-NULL
    # event_type (e.g. anything touched by an event_type backfill) and insert
    # a brand new duplicate row instead of updating it. A player should only
    # ever have one score per day, full stop — event_type is just descriptive
    # metadata about that one score, not a second axis of identity. Fixing
    # this requires merging any duplicates already created by the bug before
    # the corrected (player_id, game_date)-only unique index can be created.
    try:
        dupes = await fetchall(
            """
            SELECT player_id, game_date, COUNT(*) c FROM game_scores
            GROUP BY player_id, game_date HAVING c > 1
            """
        )
        for dupe in dupes:
            rows = await fetchall(
                "SELECT * FROM game_scores WHERE player_id=? AND game_date=? ORDER BY id",
                (dupe['player_id'], dupe['game_date'])
            )
            newest = rows[-1]
            older = rows[:-1]
            # Trust the newest row's own score/is_forfeit/is_excused/event_type
            # (that's the actual correction that was intended), but don't lose
            # any of the other detail fields if the newest row left them blank
            # while an older one had them set.
            merged = dict(newest)
            for field in ('event_type', 'def_ovr_faced'):
                if merged.get(field) is None:
                    for old in reversed(older):
                        if old.get(field) is not None:
                            merged[field] = old[field]
                            break
            for field in ('fourth_downs', 'fourth_down_convs', 'fumbles'):
                if not merged.get(field):
                    for old in reversed(older):
                        if old.get(field):
                            merged[field] = old[field]
                            break
            await _db.execute(
                """
                UPDATE game_scores SET score=?, is_forfeit=?, is_excused=?, event_type=?,
                    def_ovr_faced=?, fourth_downs=?, fourth_down_convs=?, fumbles=?
                WHERE id=?
                """,
                (merged['score'], merged['is_forfeit'], merged['is_excused'], merged['event_type'],
                 merged['def_ovr_faced'], merged['fourth_downs'], merged['fourth_down_convs'],
                 merged['fumbles'], newest['id'])
            )
            for old in older:
                await _db.execute("DELETE FROM game_scores WHERE id=?", (old['id'],))
            await _db.commit()
        if dupes:
            logger.info(f"Migration: merged {len(dupes)} duplicate game_scores group(s) "
                        f"caused by the event_type uniqueness bug")
    except Exception as e:
        logger.error(f"Migration failed merging duplicate game_scores rows: {e}")

    try:
        await _db.execute("DROP INDEX IF EXISTS uq_player_date")
        await _db.execute("CREATE UNIQUE INDEX uq_player_date ON game_scores(player_id, game_date)")
        await _db.commit()
        logger.info("Migration applied: uq_player_date now (player_id, game_date) only")
    except Exception as e:
        logger.error(f"Migration failed rebuilding uq_player_date index: {e}")

    # /siegescore used to be purely additive — logging a second score for the
    # same player against the same node just inserted another row, summing
    # into the node's total rather than replacing the earlier entry. Now that
    # a re-score replaces instead, merge any duplicates that behavior already
    # created (keeping the newest entry's own drives/points — trusting it as
    # the corrected value, same reasoning as the game_scores duplicate merge
    # above) before the unique index can be safely added.
    try:
        dupes = await fetchall(
            """
            SELECT node_id, player_id, COUNT(*) c FROM siege_scores
            GROUP BY node_id, player_id HAVING c > 1
            """
        )
        for dupe in dupes:
            rows = await fetchall(
                "SELECT * FROM siege_scores WHERE node_id=? AND player_id=? ORDER BY id",
                (dupe['node_id'], dupe['player_id'])
            )
            newest = rows[-1]
            for old in rows[:-1]:
                await _db.execute("DELETE FROM siege_scores WHERE id=?", (old['id'],))
            await _db.commit()
        if dupes:
            logger.info(f"Migration: merged {len(dupes)} duplicate siege_scores group(s) "
                        f"caused by the old additive /siegescore behavior")
    except Exception as e:
        logger.error(f"Migration failed merging duplicate siege_scores rows: {e}")

    try:
        await _db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_siege_node_player ON siege_scores(node_id, player_id)")
        await _db.commit()
        logger.info("Migration applied: uq_siege_node_player enforced")
    except Exception as e:
        logger.error(f"Migration failed creating uq_siege_node_player index: {e}")


async def backup_database():
    """
    Create a timestamped copy of the live database in a local backups/
    folder (next to the main db file), then prune anything older than
    BACKUP_RETENTION_DAYS. Safe to call at any time, including while the
    database is actively being read from and written to — this opens a
    second, independent connection and uses SQLite's own online backup API
    (sqlite3.Connection.backup) rather than a raw file copy, which matters
    because the database runs in WAL mode: a plain file copy can miss data
    that's still sitting in the WAL file and not yet checkpointed into the
    main file, silently producing an inconsistent snapshot. SQLite supports
    multiple concurrent connections to the same file for exactly this kind
    of case, so this doesn't interfere with the bot's own connection.

    This exists specifically as a local safety net against the database
    file itself being accidentally overwritten (e.g. an older backup or
    the wrong file getting uploaded over the live one during a deploy) —
    a scenario that has no other recovery path on hosts without shell
    access. Called on every startup and once daily; see optimized_bot.py.
    """
    import sqlite3

    def _do_backup(source_path: str, dest_path: str):
        source = sqlite3.connect(source_path)
        dest = sqlite3.connect(dest_path)
        try:
            source.backup(dest)
        finally:
            source.close()
            dest.close()

    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"neuroverse_{timestamp}.db")

        await asyncio.to_thread(_do_backup, DB_PATH, backup_path)

        logger.info(f"Database backup created: {backup_path}")
        _prune_old_backups()
    except Exception as e:
        logger.error(f"Database backup failed: {e}", exc_info=True)


def _prune_old_backups():
    """Delete backup files older than BACKUP_RETENTION_DAYS."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=BACKUP_RETENTION_DAYS)
    try:
        for name in os.listdir(BACKUP_DIR):
            path = os.path.join(BACKUP_DIR, name)
            if not name.startswith("neuroverse_") or not name.endswith(".db"):
                continue
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                os.remove(path)
                logger.info(f"Pruned old backup: {name}")
    except Exception as e:
        logger.error(f"Backup pruning failed: {e}", exc_info=True)


async def close():
    global _db
    if _db:
        await _db.close()
        _db = None
        logger.info("SQLite connection closed")


def _check():
    if _db is None:
        raise RuntimeError("Database not initialised — call db.init() first.")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

async def execute(sql: str, args=()):
    _check()
    async with _db.execute(sql, args) as cur:
        await _db.commit()
        return cur.rowcount


async def execute_insert(sql: str, args=()) -> int:
    """Like execute(), but returns the newly-inserted row's id (cur.lastrowid)."""
    _check()
    async with _db.execute(sql, args) as cur:
        await _db.commit()
        return cur.lastrowid


async def fetchone(sql: str, args=(), conn=None) -> dict | None:
    """conn: optional override, e.g. an archived season's connection from
    get_archive_conn(). Defaults to the live database."""
    c = conn or _db
    if c is None:
        _check()
    async with c.execute(sql, args) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def fetchall(sql: str, args=(), conn=None) -> list[dict]:
    """conn: optional override, e.g. an archived season's connection from
    get_archive_conn(). Defaults to the live database."""
    c = conn or _db
    if c is None:
        _check()
    async with c.execute(sql, args) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Archived-season connections (read-only, for /legacy commands)
# ---------------------------------------------------------------------------

_archive_connections: dict[int, aiosqlite.Connection] = {}

def _archive_path(year: int) -> str:
    base_dir = os.path.dirname(os.path.abspath(DB_PATH)) or "."
    return os.path.join(base_dir, f"neuroverse_{year}.db")


async def get_archive_conn(year: int) -> aiosqlite.Connection | None:
    """
    Open (or reuse a cached) read-only connection to an archived season's
    database, e.g. neuroverse_2026.db sitting alongside the live db. Returns
    None if no archive exists for that year — callers should treat this as
    "that season isn't available," not an error.
    Opened with mode=ro (SQLite's own read-only URI mode) since /legacy
    commands must never be able to write to a past season's data, even by
    accident — there's no legitimate reason a fetch-style command would need to.
    """
    if year in _archive_connections:
        return _archive_connections[year]

    path = _archive_path(year)
    if not os.path.isfile(path):
        return None

    conn = await aiosqlite.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = aiosqlite.Row
    _archive_connections[year] = conn
    logger.info(f"Opened archive connection for season {year}: {path}")
    return conn


async def close_archive_connections():
    """Close all cached archive connections — called on bot shutdown."""
    for year, conn in list(_archive_connections.items()):
        await conn.close()
    _archive_connections.clear()


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

async def get_player(ign: str, conn=None) -> dict | None:
    """
    Look up a player by nickname (ign). conn: optional archive connection
    (see get_archive_conn) — when querying an archive, status is not
    filtered on, since a closed season's roster isn't meaningfully
    "active"/"inactive" the way the live roster is.
    """
    if conn is not None:
        return await fetchone("SELECT * FROM players WHERE ign = ? LIMIT 1", (ign,), conn=conn)
    return await fetchone(
        "SELECT * FROM players WHERE ign = ? AND status != 'I' LIMIT 1",
        (ign,)
    )


async def get_player_by_real_ign(real_ign: str) -> dict | None:
    """
    Look up a player by their real in-game name (used by the AI agent).
    Matches real_ign column exactly first; falls back to ign if real_ign is NULL.
    """
    row = await fetchone(
        "SELECT * FROM players WHERE real_ign=? LIMIT 1", (real_ign,)
    )
    if row:
        return row
    # Fall back: player whose ign matches and has no real_ign set
    return await fetchone(
        "SELECT * FROM players WHERE ign=? AND real_ign IS NULL LIMIT 1", (real_ign,)
    )


async def update_player_score(ign: str, game_date, score: float | None,
                               event_type: str | None = None,
                               is_forfeit: bool = False,
                               is_excused: bool = False,
                               def_ovr_faced: int | None = None,
                               team_id_override: str | None = None,
                               fourth_downs: int | None = None,
                               fourth_down_convs: int | None = None,
                               fumbles: int | None = None):
    """
    Insert or update a player score.
    score:            None for an excused entry — there is no real score to
                      store at all, not a 0. A missed (forfeited) drive is
                      still stored as 0, since that's a real, meaningful value
                      (the player was expected to play and didn't); excused
                      means the entry shouldn't exist as a score at all.
    team_id_override: store the score against a different team than the player's
                      current team (used when recording a score for a past matchup
                      where the player may have since transferred).
    def_ovr_faced:    the opponent defensive OVR the player faced that game.
    fumbles:          directly logged fumble count for this entry — not derived
                      from the score value, since a fumble can happen on any real
                      played drive regardless of the final score.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")
    team_id = team_id_override or player['team_id']

    # A player has exactly one score per day, full stop. Check for that
    # existing row explicitly (by player_id + game_date only — never
    # event_type, or anything else that could cause this check and the
    # actual write to silently disagree about which row is "the" row for
    # this player today) before deciding whether to update it or insert a
    # new one, rather than letting an UPDATE's WHERE clause double as both
    # the existence check and the write target.
    existing = await fetchone(
        "SELECT id FROM game_scores WHERE player_id=? AND game_date=?",
        (player['id'], str(game_date))
    )

    if existing:
        await execute(
            """
            UPDATE game_scores SET score=?, event_type=COALESCE(?, event_type), is_forfeit=?, is_excused=?,
                def_ovr_faced=?, fourth_downs=?, fourth_down_convs=?, fumbles=?
            WHERE id=?
            """,
            (score, event_type, int(is_forfeit), int(is_excused), def_ovr_faced,
             fourth_downs, fourth_down_convs, fumbles, existing['id'])
        )
    else:
        await execute(
            "INSERT INTO game_scores "
            "(player_id, team_id, game_date, event_type, score, is_forfeit, is_excused, "
            "def_ovr_faced, fourth_downs, fourth_down_convs, fumbles) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (player['id'], team_id, str(game_date),
             event_type, score, int(is_forfeit), int(is_excused), def_ovr_faced,
             fourth_downs, fourth_down_convs, fumbles)
        )


async def update_player_ovr(ign: str, off_ovr: int, def_ovr: int, total_ovr: int):
    rows = await execute(
        "UPDATE players SET off_ovr=?, def_ovr=?, total_ovr=? WHERE ign=? AND status != 'I'",
        (off_ovr, def_ovr, total_ovr, ign)
    )
    if rows == 0:
        raise ValueError(f"Player '{ign}' not found.")


async def get_player_avg(ign: str, atype: str = "Yearly") -> float | None:
    """Compute a player's average live from game_scores."""
    # A genuine 0-point game is a real, countable entry — only is_forfeit/
    # is_excused should exclude an entry, never the score value itself.
    filt = "is_forfeit = 0 AND is_excused = 0"
    player = await fetchone(
        "SELECT id FROM players WHERE ign=? AND status != 'I' LIMIT 1", (ign,)
    )
    if not player:
        return None
    pid = player['id']

    event_map = {'HOF': 'HOF', 'E1': 'E1', 'E2': 'E2', 'E3': 'E3', 'Gold-': 'Gold-'}
    n_map     = {'3': 3, '7': 7, '14': 14, '30': 30}

    if atype == 'Yearly':
        row = await fetchone(
            f"SELECT ROUND(AVG(score),4) AS v FROM game_scores WHERE player_id=? AND {filt}",
            (pid,)
        )
        return row['v'] if row else None
    elif atype in n_map:
        n = n_map[atype]
        row = await fetchone(
            f"SELECT ROUND(AVG(score),4) AS v FROM "
            f"(SELECT score FROM game_scores WHERE player_id=? AND {filt} "
            f"ORDER BY game_date DESC LIMIT {n})",
            (pid,)
        )
        return row['v'] if row else None
    elif atype in event_map:
        # event_type/tier lives on the matchup_day row for that
        # (team_id, game_date), not reliably on the game_scores entry
        # itself — see get_player_stats' event_avg for the full reasoning.
        row = await fetchone(
            f"SELECT ROUND(AVG(gs.score),4) AS v FROM game_scores gs "
            f"JOIN matchup_day md ON md.team_id = gs.team_id AND md.game_date = gs.game_date "
            f"WHERE gs.player_id=? AND gs.is_forfeit=0 AND gs.is_excused=0 AND md.event_type=?",
            (pid, event_map[atype])
        )
        return row['v'] if row else None
    else:
        raise ValueError(f"Average type '{atype}' not supported. Valid: Yearly, HOF, E1, E2, E3, Gold-, 3, 7, 14, 30")


async def get_player_avg_with_fumble_adj(ign: str, atype: str = "Yearly") -> dict | None:
    """
    Same lookup as get_player_avg (identical scope, identical query
    structure per atype — deliberately not narrower/wider), but also
    returns the fumble-adjusted variant (see _fumble_adjusted_avg) computed
    from that exact same range's totals. Kept as a separate function rather
    than changing get_player_avg's own return type, since several existing
    callers (including tests) expect a plain float back from that one —
    this is purely additive, for /avg specifically to show both numbers
    side by side.
    Returns None if the player isn't found or has no scores in range,
    matching get_player_avg's own None cases.
    """
    filt = "is_forfeit = 0 AND is_excused = 0"
    player = await fetchone(
        "SELECT id FROM players WHERE ign=? AND status != 'I' LIMIT 1", (ign,)
    )
    if not player:
        return None
    pid = player['id']

    event_map = {'HOF': 'HOF', 'E1': 'E1', 'E2': 'E2', 'E3': 'E3', 'Gold-': 'Gold-'}
    n_map     = {'3': 3, '7': 7, '14': 14, '30': 30}

    if atype == 'Yearly':
        row = await fetchone(
            f"SELECT ROUND(AVG(score),4) AS v, COALESCE(SUM(score),0) AS sum_v, "
            f"COUNT(*) AS games_v, COALESCE(SUM(fumbles),0) AS fumbles_v "
            f"FROM game_scores WHERE player_id=? AND {filt}",
            (pid,)
        )
    elif atype in n_map:
        n = n_map[atype]
        row = await fetchone(
            f"SELECT ROUND(AVG(score),4) AS v, COALESCE(SUM(score),0) AS sum_v, "
            f"COUNT(*) AS games_v, COALESCE(SUM(fumbles),0) AS fumbles_v FROM "
            f"(SELECT score, fumbles FROM game_scores WHERE player_id=? AND {filt} "
            f"ORDER BY game_date DESC LIMIT {n})",
            (pid,)
        )
    elif atype in event_map:
        row = await fetchone(
            f"SELECT ROUND(AVG(gs.score),4) AS v, COALESCE(SUM(gs.score),0) AS sum_v, "
            f"COUNT(*) AS games_v, COALESCE(SUM(gs.fumbles),0) AS fumbles_v FROM game_scores gs "
            f"JOIN matchup_day md ON md.team_id = gs.team_id AND md.game_date = gs.game_date "
            f"WHERE gs.player_id=? AND gs.is_forfeit=0 AND gs.is_excused=0 AND md.event_type=?",
            (pid, event_map[atype])
        )
    else:
        raise ValueError(f"Average type '{atype}' not supported. Valid: Yearly, HOF, E1, E2, E3, Gold-, 3, 7, 14, 30")

    if not row or row['v'] is None:
        return None
    return {
        'avg': row['v'],
        'fumble_adjusted_avg': _fumble_adjusted_avg(row['sum_v'], row['games_v'], row['fumbles_v']),
    }


async def get_players_remaining(team_id: str, game_date) -> list[str]:
    rows = await fetchall(
        """
        SELECT p.ign FROM players p
        LEFT JOIN game_scores gs ON gs.player_id = p.id AND gs.game_date = ?
        WHERE p.team_id = ? AND p.status = 'A' AND gs.id IS NULL
        ORDER BY p.ign
        """,
        (str(game_date), team_id)
    )
    return [r['ign'] for r in rows]


# ---------------------------------------------------------------------------
# Status / matchup helpers
# ---------------------------------------------------------------------------

async def get_matchup_status(team_id: str, game_date) -> dict:
    our = await fetchone(
        """
        SELECT COALESCE(SUM(gs.score), 0) AS us_score, COUNT(gs.id) AS us_drives
        FROM game_scores gs JOIN players p ON p.id = gs.player_id
        WHERE gs.team_id = ? AND gs.game_date = ? AND p.status != 'I'
        """,
        (team_id, str(game_date))
    )
    opp = await fetchone(
        """SELECT opp_ign, opp_score, opp_drives, our_defaults, opp_defaults
           FROM matchup_day WHERE team_id=? AND game_date=?""",
        (team_id, str(game_date))
    )
    remaining = await get_players_remaining(team_id, game_date)

    # Real roster size — a league's active (rostered) player count isn't a
    # fixed 16 or 18, it's whatever's actually on the roster right now, so
    # callers must use this instead of assuming a fixed number. Note this is
    # the 18-cap membership concept (status='A'), not the separate 16-cap
    # "playing this specific matchup" concept (see siege.py's header
    # docstring / ladder_flow.py for that distinction) — this count can
    # exceed 16 for a league with a fuller roster than fits in one matchup.
    roster_row    = await fetchone(
        "SELECT COUNT(*) AS c FROM players WHERE team_id=? AND status='A'",
        (team_id,)
    )
    active_roster = roster_row['c'] if roster_row else 0

    us_score      = our['us_score']       if our else 0
    us_drives     = our['us_drives']      if our else 0
    them_score    = opp['opp_score']      if opp else 0
    their_drives  = opp['opp_drives']     if opp else 0
    opp_ign       = opp['opp_ign']        if opp else "?"
    our_defaults  = opp['our_defaults']   if opp else 0
    opp_defaults  = opp['opp_defaults']   if opp else 0

    diff    = us_score - them_score
    outlook = "AHEAD" if diff > 0 else ("BEHIND" if diff < 0 else "TIED")

    return {
        'opp_ign': opp_ign, 'us_score': us_score, 'us_drives': us_drives,
        'them_score': them_score, 'their_drives': their_drives,
        'outlook': outlook, 'players_remaining': remaining,
        'our_defaults': our_defaults, 'opp_defaults': opp_defaults,
        'active_roster': active_roster,
    }


async def update_opp_score(team_id: str, game_date, score: int, drives: int):
    await execute(
        """
        INSERT INTO matchup_day (team_id, game_date, opp_score, opp_drives)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(team_id, game_date) DO UPDATE SET opp_score=excluded.opp_score, opp_drives=excluded.opp_drives
        """,
        (team_id, str(game_date), score, drives)
    )


async def new_day(team_id: str, game_date):
    await execute(
        "INSERT OR IGNORE INTO matchup_day (team_id, game_date, opp_score, opp_drives) VALUES (?,?,0,0)",
        (team_id, str(game_date))
    )


# ---------------------------------------------------------------------------
# Rank / ladder helpers
# ---------------------------------------------------------------------------

async def get_rank_table(team_id: str, conn=None) -> list[dict]:
    """Active roster sorted by pwr_rank, all stats computed live."""
    return await get_team_stats(team_id, conn=conn)


async def get_ladder(team_id: str, conn=None) -> list[dict]:
    return await fetchall(
        """
        SELECT lm.slot, lm.our_ign, lm.our_total_ovr, lm.opp_def_ovr, lm.opp_ign,
               lm.tier, lm.tier_score,
               p.off_ovr AS our_off_ovr, p.total_ovr AS our_total_ovr_live
        FROM ladder_matchups lm
        LEFT JOIN players p ON p.ign = lm.our_ign
        WHERE lm.team_id=? ORDER BY lm.slot
        """,
        (team_id,), conn=conn
    )


# ---------------------------------------------------------------------------
# Tournament helpers
# ---------------------------------------------------------------------------

async def create_tournament(tid: str, name: str, total_rounds: int,
                             player_count: int, game_date):
    await execute(
        "INSERT INTO tournaments(id,name,status,current_round,total_rounds,player_count,created) "
        "VALUES (?,?,'active',1,?,?,?)",
        (tid, name, total_rounds, player_count, str(game_date))
    )


async def get_tournament(tid: str) -> dict | None:
    return await fetchone("SELECT * FROM tournaments WHERE id=?", (tid,))


async def list_tournaments() -> list[dict]:
    return await fetchall("SELECT * FROM tournaments ORDER BY created DESC")


async def complete_tournament(tid: str, champion: str):
    await execute("UPDATE tournaments SET status='complete', champion=? WHERE id=?", (champion, tid))


async def advance_tournament_round(tid: str, new_round: int):
    await execute("UPDATE tournaments SET current_round=? WHERE id=?", (new_round, tid))


async def insert_matches(tid: str, matches: list[dict]):
    _check()
    await _db.executemany(
        "INSERT INTO tournament_matches(tournament_id,round,match_num,p1,p2,winner) VALUES (?,?,?,?,?,?)",
        [(tid, m['round'], m['match'], m['p1'], m['p2'], m.get('winner', '')) for m in matches]
    )
    await _db.commit()


async def get_matches(tid: str) -> list[dict]:
    return await fetchall(
        "SELECT round, match_num AS `match`, p1, p2, winner FROM tournament_matches "
        "WHERE tournament_id=? ORDER BY round, match_num",
        (tid,)
    )


async def record_match_result(tid: str, round_num: int, match_num: int, winner: str):
    rows = await execute(
        "UPDATE tournament_matches SET winner=? WHERE tournament_id=? AND round=? AND match_num=?",
        (winner, tid, round_num, match_num)
    )
    if rows == 0:
        raise ValueError(f"Match **{match_num}** not found in round {round_num} of tournament **{tid}**.")


# ---------------------------------------------------------------------------
# Matchup helpers
# ---------------------------------------------------------------------------

async def set_matchup_info(team_id: str, game_date, opp_ign: str | None = None,
                            event_type: str | None = None, notes: str | None = None,
                            our_rank: int | None = None):
    """
    Upsert just the matchup_day row's opponent/division/notes/our_rank —
    no ladder-snapshot side effect. Any field left as None preserves whatever
    is already stored rather than overwriting it, since callers (e.g. a
    screenshot extraction) may only have some of this info available.
    Used directly by anything that's already separately responsible for the
    ladder data itself (see save_ladder_to_db) to avoid double-writing it;
    set_matchup wraps this for callers that need both done together.
    """
    await execute(
        """
        INSERT INTO matchup_day (team_id, game_date, opp_ign, event_type, notes, our_rank,
                                  opp_score, our_score)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(team_id, game_date) DO UPDATE SET
            opp_ign=COALESCE(excluded.opp_ign, matchup_day.opp_ign),
            event_type=COALESCE(excluded.event_type, matchup_day.event_type),
            notes=COALESCE(excluded.notes, matchup_day.notes),
            our_rank=COALESCE(excluded.our_rank, matchup_day.our_rank)
        """,
        (team_id, str(game_date), opp_ign, event_type, notes, our_rank)
    )


async def set_matchup(team_id: str, game_date, opp_ign: str | None = None,
                      event_type: str | None = None, notes: str | None = None,
                      our_rank: int | None = None):
    """
    Record today's opponent, division, and our rank. Upserts matchup_day and
    snapshots the current ladder (ladder_matchups) into matchup_ladder. Any
    field left as None preserves whatever's already stored for this team+date.
    """
    await set_matchup_info(team_id, game_date, opp_ign, event_type, notes, our_rank)

    # Snapshot current ladder for this date
    ladder = await fetchall(
        "SELECT * FROM ladder_matchups WHERE team_id=? ORDER BY slot",
        (team_id,)
    )
    for row in ladder:
        await execute(
            """
            INSERT INTO matchup_ladder
                (team_id, game_date, slot, opp_ign, opp_def_ovr,
                 our_total_ovr, tier, tier_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, game_date, slot) DO UPDATE SET
                opp_ign=excluded.opp_ign,
                opp_def_ovr=excluded.opp_def_ovr,
                our_total_ovr=excluded.our_total_ovr,
                tier=excluded.tier,
                tier_score=excluded.tier_score
            """,
            (team_id, str(game_date), row['slot'], row['opp_ign'],
             row['opp_def_ovr'], row['our_total_ovr'], row['tier'], row['tier_score'])
        )


async def set_outcome(team_id: str, game_date,
                      our_score: int, opp_score: int, opp_drives: int):
    """
    Record the final score and derive WIN/LOSS/TIE.
    Also updates each ladder entry that matches the opponent with the result.
    """
    if our_score > opp_score:
        outcome = 'WIN'
    elif our_score < opp_score:
        outcome = 'LOSS'
    else:
        outcome = 'TIE'

    await execute(
        """
        UPDATE matchup_day
        SET our_score=?, opp_score=?, opp_drives=?, outcome=?
        WHERE team_id=? AND game_date=?
        """,
        (our_score, opp_score, opp_drives, outcome, team_id, str(game_date))
    )

    # Update the ladder snapshot with the result
    matchup = await fetchone(
        "SELECT opp_ign FROM matchup_day WHERE team_id=? AND game_date=?",
        (team_id, str(game_date))
    )
    if matchup:
        await execute(
            """
            UPDATE matchup_ladder SET result=?, our_pts=?, opp_pts=?
            WHERE team_id=? AND game_date=? AND opp_ign=?
            """,
            (outcome, our_score, opp_score, team_id, str(game_date), matchup['opp_ign'])
        )

    return outcome


async def get_matchup_summary(team_id: str, game_date) -> dict:
    """
    Return everything needed for a matchup summary embed:
      - matchup_day row (opponent, scores, outcome)
      - ladder snapshot for that date
      - all player scores that day (using team_id at time of scoring)
    """
    matchup = await fetchone(
        "SELECT * FROM matchup_day WHERE team_id=? AND game_date=?",
        (team_id, str(game_date))
    )

    ladder = await fetchall(
        "SELECT * FROM matchup_ladder WHERE team_id=? AND game_date=? ORDER BY slot",
        (team_id, str(game_date))
    )

    # Scores use game_scores.team_id so a transferred player's score
    # stays tied to the league they played for that day. event_type isn't
    # selected here — it's not reliably set per game_scores row, and the
    # matchup dict above already carries the correct, single event_type
    # for this team_id+game_date (every row here shares the same one).
    scores = await fetchall(
        """
        SELECT p.ign, gs.score, gs.is_forfeit,
               gs.team_id AS played_for,
               p.team_id  AS current_team
        FROM game_scores gs
        JOIN players p ON p.id = gs.player_id
        WHERE gs.team_id = ? AND gs.game_date = ?
        ORDER BY gs.score DESC
        """,
        (team_id, str(game_date))
    )

    return {
        'matchup': matchup,
        'ladder':  ladder,
        'scores':  scores,
    }


async def get_recent_matchups(team_id: str, limit: int = 10) -> list[dict]:
    """Return recent matchup_day rows for a team — used to populate the past-match dropdown."""
    return await fetchall(
        """
        SELECT game_date, opp_ign, event_type, outcome,
               our_score, opp_score
        FROM matchup_day
        WHERE team_id=?
        ORDER BY game_date DESC
        LIMIT ?
        """,
        (team_id, limit)
    )


async def upsert_ladder_slot(team_id: str, game_date, slot: int,
                              opp_ign: str, opp_def_ovr: int | None = None,
                              our_total_ovr: int | None = None,
                              our_ign: str | None = None,
                              tier: int | None = None):
    """Insert or update a single ladder slot for a given day."""
    await execute(
        """
        INSERT INTO matchup_ladder
            (team_id, game_date, slot, opp_ign, opp_def_ovr, our_total_ovr, our_ign, tier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(team_id, game_date, slot) DO UPDATE SET
            opp_ign=excluded.opp_ign,
            opp_def_ovr=excluded.opp_def_ovr,
            our_total_ovr=excluded.our_total_ovr,
            our_ign=excluded.our_ign,
            tier=excluded.tier
        """,
        (team_id, str(game_date), slot, opp_ign,
         opp_def_ovr, our_total_ovr, our_ign, tier)
    )


async def get_ladder_snapshot(team_id: str, game_date, conn=None) -> list[dict]:
    """Return the ladder snapshot for a team on a given date."""
    return await fetchall(
        """
        SELECT ml.slot, ml.our_ign, ml.opp_ign, ml.opp_def_ovr, ml.our_total_ovr,
               ml.tier, ml.tier_score, ml.result, ml.our_pts, ml.opp_pts,
               p.off_ovr AS our_off_ovr
        FROM matchup_ladder ml
        LEFT JOIN players p ON p.ign = ml.our_ign
        WHERE ml.team_id=? AND ml.game_date=?
        ORDER BY ml.slot
        """,
        (team_id, str(game_date)), conn=conn
    )


async def get_player_fourth_down_rate(ign: str, conn=None) -> dict | None:
    """Return career 4th down attempts, conversions, and rate for a player.
    Returns None if the player has no 4th down data recorded."""
    status_filt = "" if conn is not None else "AND p.status != 'I'"
    row = await fetchone(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN gs.fourth_downs IS NOT NULL THEN gs.fourth_downs ELSE 0 END), 0)      AS attempts,
            COALESCE(SUM(CASE WHEN gs.fourth_down_convs IS NOT NULL THEN gs.fourth_down_convs ELSE 0 END), 0) AS conversions,
            COUNT(CASE WHEN gs.fourth_downs IS NOT NULL AND gs.fourth_downs > 0 THEN 1 END) AS games_with_data
        FROM game_scores gs
        JOIN players p ON p.id = gs.player_id
        WHERE p.ign = ? {status_filt}
        """,
        (ign,), conn=conn
    )
    if not row or not row['games_with_data'] or row['attempts'] == 0:
        return None
    attempts     = row['attempts']
    conversions  = row['conversions']
    conv_rate    = round(conversions / attempts * 100, 1) if attempts > 0 else None
    return {
        'attempts':    attempts,
        'conversions': conversions,
        'conv_rate':   conv_rate,
    }


async def get_player_streaks(ign: str, conn=None) -> dict | None:
    """
    Computes two "hot streak" metrics for a player, each counting
    consecutive games going backward from their most recent entry, scoped
    to their current team (matching get_player_stats' own historical-
    team-id scoping — a streak is about recent form on this team, not a
    career-wide mix across every team they've ever played for):
      - kobe_streak: consecutive games with score >= 24 ("24+", per the
        actual request — NOT the same condition as the existing 'kobes'
        stat elsewhere, which counts score==24 exactly. Scores above 24 do
        occur in real data (confirmed against a real production database:
        30, 28, 26 all appear, affecting ~5% of players), so score==24
        alone would incorrectly break a streak on an even-better game.
      - no_drop_streak: consecutive games with score >= 18 (no drive
        dropped — per the scoring tiers used elsewhere in this codebase,
        e.g. _two_pt_pct: 18-19 is the lowest score representing all 3
        drives completed; anything below means at least one drive was
        dropped/didn't happen).
    A missed drive (is_forfeit) is treated as a real score of 0, which
    fails both conditions and breaks both streaks outright. An excused
    absence (is_excused) is skipped entirely rather than breaking either
    streak — consistent with how excused entries are excluded from every
    other average/count in this codebase (treated as if that day never
    happened at all, not as a bad game that ends the streak).
    Returns None if the player isn't found.
    """
    status_filt = "" if conn is not None else "AND status != 'I'"
    player = await fetchone(
        f"SELECT id, team_id FROM players WHERE ign=? {status_filt} LIMIT 1", (ign,), conn=conn
    )
    if not player:
        return None

    rows = await fetchall(
        "SELECT score, is_forfeit, is_excused FROM game_scores "
        "WHERE player_id=? AND team_id=? ORDER BY game_date DESC",
        (player['id'], player['team_id']), conn=conn
    )

    kobe_streak = 0
    kobe_active = True
    no_drop_streak = 0
    no_drop_active = True

    for r in rows:
        if not kobe_active and not no_drop_active:
            break
        if r['is_excused']:
            continue  # excused day never happened — skip, don't break either streak
        score = 0 if r['is_forfeit'] else r['score']
        if kobe_active:
            if score is not None and score >= 24:
                kobe_streak += 1
            else:
                kobe_active = False
        if no_drop_active:
            if score is not None and score >= 18:
                no_drop_streak += 1
            else:
                no_drop_active = False

    return {'kobe_streak': kobe_streak, 'no_drop_streak': no_drop_streak}


# ---------------------------------------------------------------------------
# Defensive score helpers — points allowed + avg opponent OFF OVR faced
# ---------------------------------------------------------------------------

async def update_player_dscore(ign: str, game_date, points_allowed: int,
                                avg_off_ovr_faced: float | None = None,
                                drive1_outcome: str | None = None,
                                drive2_outcome: str | None = None,
                                drive3_outcome: str | None = None):
    """
    Insert or update a player's defensive log for a given day.
    drive{1,2,3}_outcome: '0'-'8' (points allowed on that specific drive) or
    'F'/'I'/'S' for a fumble/interception/safety turnover. None if not entered.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")

    existing = await fetchone(
        "SELECT id FROM defense_scores WHERE player_id=? AND game_date=?",
        (player['id'], str(game_date))
    )

    if existing:
        await execute(
            """
            UPDATE defense_scores
            SET points_allowed=?, avg_off_ovr_faced=?,
                drive1_outcome=?, drive2_outcome=?, drive3_outcome=?
            WHERE id=?
            """,
            (points_allowed, avg_off_ovr_faced, drive1_outcome, drive2_outcome, drive3_outcome,
             existing['id'])
        )
    else:
        await execute(
            """
            INSERT INTO defense_scores
                (player_id, team_id, game_date, points_allowed, avg_off_ovr_faced,
                 drive1_outcome, drive2_outcome, drive3_outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (player['id'], player['team_id'], str(game_date),
             points_allowed, avg_off_ovr_faced, drive1_outcome, drive2_outcome, drive3_outcome)
        )


async def update_player_dscore_single_opponent(ign: str, game_date, points_allowed: int, ovr: int,
                                                 drive1_outcome: str | None = None,
                                                 drive2_outcome: str | None = None,
                                                 drive3_outcome: str | None = None):
    """
    Simplified defensive-log entry for /dscore's common case: the same
    single opponent faced the player for all 3 drives, so there's only
    one OVR to record, not three, and no modal is needed to collect it
    drive by drive. Sets avg_off_ovr_faced AND all three drive{1,2,3}_ovr
    columns to this same value — same schema, same downstream stats
    (get_player_dscore_stats etc. read those columns the same way either
    path wrote them), just a faster path than /dscore_multiple's full
    per-drive modal flow for what is, per the actual game's ecosystem,
    the common case.
    Unlike /dscore_multiple's flow, this never populates the turnover
    down/distance/play/forced_by columns — those stay None/unset, since
    there's no modal (or inline argument) collecting that detail here.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")

    existing = await fetchone(
        "SELECT id FROM defense_scores WHERE player_id=? AND game_date=?",
        (player['id'], str(game_date))
    )

    if existing:
        await execute(
            """
            UPDATE defense_scores
            SET points_allowed=?, avg_off_ovr_faced=?,
                drive1_outcome=?, drive2_outcome=?, drive3_outcome=?,
                drive1_ovr=?, drive2_ovr=?, drive3_ovr=?
            WHERE id=?
            """,
            (points_allowed, ovr, drive1_outcome, drive2_outcome, drive3_outcome,
             ovr, ovr, ovr, existing['id'])
        )
    else:
        await execute(
            """
            INSERT INTO defense_scores
                (player_id, team_id, game_date, points_allowed, avg_off_ovr_faced,
                 drive1_outcome, drive2_outcome, drive3_outcome,
                 drive1_ovr, drive2_ovr, drive3_ovr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (player['id'], player['team_id'], str(game_date),
             points_allowed, ovr, drive1_outcome, drive2_outcome, drive3_outcome,
             ovr, ovr, ovr)
        )


async def update_dscore_drive_detail(ign: str, game_date, drive_num: int, ovr: int | None,
                                      down: str | None = None, distance: str | None = None,
                                      play: str | None = None, forced_by: str | None = None):
    """
    Save one drive's detail, after the initial row has already been created via
    update_player_dscore (which records points_allowed and all 3 outcomes up
    front, since those are now known from the /dscore command itself). Called
    once per drive, in order, from that drive's modal.
    ovr: the opposing player's offensive OVR faced on this specific drive —
    tracked for every drive, turnover or not.
    down/distance/play/forced_by: only meaningful for a turnover drive: plain,
    optional text, left None for a normal (non-turnover) drive.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")
    cols = {
        1: ("drive1_ovr", "drive1_turnover_down", "drive1_turnover_distance", "drive1_turnover_play", "drive1_turnover_forced_by"),
        2: ("drive2_ovr", "drive2_turnover_down", "drive2_turnover_distance", "drive2_turnover_play", "drive2_turnover_forced_by"),
        3: ("drive3_ovr", "drive3_turnover_down", "drive3_turnover_distance", "drive3_turnover_play", "drive3_turnover_forced_by"),
    }
    col_names = cols.get(drive_num)
    if not col_names:
        return
    ovr_col, down_col, distance_col, play_col, forced_by_col = col_names
    await execute(
        f"UPDATE defense_scores SET {ovr_col}=?, {down_col}=?, {distance_col}=?, {play_col}=?, {forced_by_col}=? "
        f"WHERE player_id=? AND game_date=?",
        (ovr, down, distance, play, forced_by, player['id'], str(game_date))
    )


async def finalize_dscore_avg_ovr(ign: str, game_date):
    """
    Once all 3 drives have their OVR recorded, compute avg_off_ovr_faced as
    the average of whichever drive1_ovr/drive2_ovr/drive3_ovr values were
    actually entered (NULLs excluded, not treated as 0). Called once, after
    the last drive's modal is submitted.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")
    row = await fetchone(
        "SELECT drive1_ovr, drive2_ovr, drive3_ovr FROM defense_scores WHERE player_id=? AND game_date=?",
        (player['id'], str(game_date))
    )
    if row is None:
        return
    values = [v for v in (row['drive1_ovr'], row['drive2_ovr'], row['drive3_ovr']) if v is not None]
    avg = round(sum(values) / len(values), 1) if values else None
    await execute(
        "UPDATE defense_scores SET avg_off_ovr_faced=? WHERE player_id=? AND game_date=?",
        (avg, player['id'], str(game_date))
    )
    return avg


async def get_player_dscore(ign: str, game_date) -> dict | None:
    """Return a player's defensive log for a specific day, if any."""
    player = await get_player(ign)
    if player is None:
        return None
    return await fetchone(
        "SELECT * FROM defense_scores WHERE player_id=? AND game_date=?",
        (player['id'], str(game_date))
    )


async def get_player_dscore_stats(ign: str, conn=None) -> dict | None:
    """Career defensive summary for a player — used anywhere a def. rollup is needed."""
    player = await get_player(ign, conn=conn)
    if player is None:
        return None
    row = await fetchone(
        """
        SELECT COUNT(*) AS games,
               COALESCE(SUM(points_allowed), 0) AS total_allowed,
               ROUND(AVG(points_allowed), 2) AS avg_allowed,
               ROUND(AVG(avg_off_ovr_faced), 2) AS avg_off_ovr_faced
        FROM defense_scores WHERE player_id=?
        """,
        (player['id'],), conn=conn
    )
    if not row or not row['games']:
        return None
    return row


# ---------------------------------------------------------------------------
# Power rank weight helpers
# ---------------------------------------------------------------------------

async def get_weights(category: str, team_id: str | None = None) -> list[dict]:
    """
    Return weights for a category ('pwr_rank' or 'ladder').
    If team_id is given, returns team-specific overrides merged with globals
    (team-specific rows take precedence over NULL team_id rows).
    """
    rows = await fetchall(
        """
        SELECT id, label, display_label, weight, category, team_id
        FROM pwr_rank_weights
        WHERE category = ?
          AND (team_id IS NULL OR team_id = ?)
        ORDER BY id
        """,
        (category, team_id or '')
    )
    # If a team_id override exists for a label, use it over the global
    seen: dict = {}
    for r in rows:
        key = r['label']
        if key not in seen or r['team_id'] is not None:
            seen[key] = r
    return list(seen.values())


async def set_weight(label: str, weight: float,
                     team_id: str | None = None) -> bool:
    """Update an existing weight by label. Returns True if found."""
    rows = await execute(
        """
        UPDATE pwr_rank_weights SET weight=?
        WHERE label=? AND (team_id IS NULL OR team_id=?)
        """,
        (weight, label, team_id or '')
    )
    return rows > 0


async def add_weight(label: str, display_label: str, weight: float,
                     category: str, team_id: str | None = None):
    """Insert a new weight factor."""
    await execute(
        """
        INSERT INTO pwr_rank_weights (label, display_label, weight, category, team_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (label, display_label, weight, category, team_id)
    )


async def delete_weight(label: str, team_id: str | None = None):
    """Delete a weight by label."""
    await execute(
        "DELETE FROM pwr_rank_weights WHERE label=? AND (team_id IS NULL OR team_id=?)",
        (label, team_id or '')
    )


# ---------------------------------------------------------------------------
# Player recalculation — triggered on every !score and !ovr
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Live stat calculation functions — nothing stored, always computed from game_scores
# ---------------------------------------------------------------------------

def _two_pt_pct(scores: list[float]) -> float | None:
    """
    2PT conversion % derived from drive scores.
    24       = 3/3 made
    22-23    = 2/3
    20-21    = 1/3
    18-19    = 0/3
    16       = 2/2
    14-15    = 1/2
    12-13    = 0/2
    8-9      = 1/1
    6-7      = 0/1
    """
    made = attempted = 0
    for s in scores:
        if s >= 24:
            made += 3; attempted += 3
        elif s >= 22:
            made += 2; attempted += 3
        elif s >= 20:
            made += 1; attempted += 3
        elif s >= 18:
            attempted += 3
        elif s == 16:
            made += 2; attempted += 2
        elif s >= 14:
            made += 1; attempted += 2
        elif s >= 12:
            attempted += 2
        elif s >= 8:
            made += 1; attempted += 1
        elif s >= 6:
            attempted += 1
    return round(made / attempted, 4) if attempted else None


def _fumble_adjusted_avg(total_points: float, games: int, fumbles: int) -> float | None:
    """
    Fumble-adjusted average: treats each fumble as a null drive (as if it
    never happened at all) rather than a real drive that just happened to
    score low, then re-derives what the per-game average would have been
    with those drives removed entirely. Every game is exactly 3 drives:
        total_drives           = games * 3
        fumble_adjusted_drives = total_drives - fumbles
        fumble_adjusted_ppd    = total_points / fumble_adjusted_drives
        fumble_adjusted_avg    = fumble_adjusted_ppd * 3
    This must be computed over the exact same range/filter as whatever
    "plain" average it's paired with (same date window, same event_type,
    etc.) — total_points, games, and fumbles all need to come from that
    identical query, not mixed from different ranges.

    Returns None if there's no data at all (0 games), or in the degenerate
    case where fumbles >= total_drives (every drive counted as a fumble, or
    more, which shouldn't be possible in valid data but is handled
    defensively rather than raising or returning something misleading like
    a negative average).

    Sanity check worth knowing: with zero fumbles, fumble_adjusted_drives
    equals total_drives exactly, so this collapses to total_points/games —
    identical to the plain average. The two numbers should only ever
    diverge once fumbles > 0.
    """
    if not games:
        return None
    total_drives = games * 3
    fumble_adjusted_drives = total_drives - fumbles
    if fumble_adjusted_drives <= 0:
        return None
    fumble_adjusted_ppd = total_points / fumble_adjusted_drives
    return round(fumble_adjusted_ppd * 3, 4)


async def get_player_stats(pid: int, team_id: str, conn=None) -> dict:
    """
    Compute all derived stats live from game_scores for a single player,
    scoped to what they did while representing team_id specifically — not
    their entire career across every league they've ever played for. A
    transferred player's history from a previous league must never bleed
    into their new league's stats (e.g. a HOF average showing up for a
    league that's never actually played a HOF match, because the player
    played HOF while on a different team before transferring).
    Returns a dict suitable for display in rank tables, player cards, etc.
    Never reads from stored derived columns.
    conn: optional archive connection (see get_archive_conn) for /legacy commands.
    """
    # A genuine 0-point game is a real, countable entry — only is_forfeit/
    # is_excused should exclude an entry, never the score value itself.
    filt = "is_forfeit = 0 AND is_excused = 0"

    # Yearly average
    row = await fetchone(
        f"SELECT ROUND(AVG(score),4) AS v, COALESCE(SUM(score),0) AS sum_v, "
        f"COUNT(*) AS games_v, COALESCE(SUM(fumbles),0) AS fumbles_v "
        f"FROM game_scores WHERE player_id=? AND team_id=? AND {filt}",
        (pid, team_id), conn=conn
    )
    avg_yearly = row['v'] if row else None
    avg_yearly_fumble_adj = _fumble_adjusted_avg(row['sum_v'], row['games_v'], row['fumbles_v']) if row else None

    # Last-N-game averages — also computes the fumble-adjusted variant from
    # the same window's totals in one query, rather than a second pass.
    async def last_n(n):
        r = await fetchone(
            f"SELECT ROUND(AVG(score),4) AS v, COALESCE(SUM(score),0) AS sum_v, "
            f"COUNT(*) AS games_v, COALESCE(SUM(fumbles),0) AS fumbles_v FROM "
            f"(SELECT score, fumbles FROM game_scores WHERE player_id=? AND team_id=? AND {filt} "
            f"ORDER BY game_date DESC LIMIT {n})", (pid, team_id), conn=conn
        )
        if not r:
            return None, None
        return r['v'], _fumble_adjusted_avg(r['sum_v'], r['games_v'], r['fumbles_v'])

    avg_3day,  avg_3day_fumble_adj  = await last_n(3)
    avg_7day,  avg_7day_fumble_adj  = await last_n(7)
    avg_14day, avg_14day_fumble_adj = await last_n(14)
    avg_30day, avg_30day_fumble_adj = await last_n(30)

    # Event averages — event_type/tier lives on the matchup_day row for
    # that (team_id, game_date), not reliably on the individual game_scores
    # entry itself (a score is logged via /score with no tier param at all;
    # the tier comes from whatever matchup was set for that day via /ladder
    # or /matchup). Joining against matchup_day is the correct source of
    # truth here, not game_scores.event_type directly. Also computes the
    # fumble-adjusted variant from this same event's totals.
    async def event_avg(evt):
        r = await fetchone(
            f"SELECT ROUND(AVG(gs.score),4) AS v, COALESCE(SUM(gs.score),0) AS sum_v, "
            f"COUNT(*) AS games_v, COALESCE(SUM(gs.fumbles),0) AS fumbles_v FROM game_scores gs "
            f"JOIN matchup_day md ON md.team_id = gs.team_id AND md.game_date = gs.game_date "
            f"WHERE gs.player_id=? AND gs.team_id=? AND gs.is_forfeit=0 AND gs.is_excused=0 AND md.event_type=?",
            (pid, team_id, evt), conn=conn
        )
        if not r:
            return None, None
        return r['v'], _fumble_adjusted_avg(r['sum_v'], r['games_v'], r['fumbles_v'])

    hof_avg,  hof_avg_fumble_adj  = await event_avg('HOF')
    e1_avg,   e1_avg_fumble_adj   = await event_avg('E1')
    e2_avg,   e2_avg_fumble_adj   = await event_avg('E2')
    e3_avg,   e3_avg_fumble_adj   = await event_avg('E3')
    gold_avg, gold_avg_fumble_adj = await event_avg('Gold-')

    # Game counts
    row = await fetchone(
        f"SELECT COUNT(*) AS v FROM game_scores WHERE player_id=? AND team_id=? AND {filt}",
        (pid, team_id), conn=conn
    )
    games = row['v'] if row else 0

    # Points (total)
    row = await fetchone(
        f"SELECT COALESCE(SUM(score),0) AS v FROM game_scores WHERE player_id=? AND team_id=? AND {filt}",
        (pid, team_id), conn=conn
    )
    points = int(row['v']) if row else 0

    # Kobes (score = 24)
    row = await fetchone(
        f"SELECT COUNT(*) AS v FROM game_scores WHERE player_id=? AND team_id=? AND {filt} AND score=24",
        (pid, team_id), conn=conn
    )
    kobes = row['v'] if row else 0

    # 3+ TDs (score > 17)
    row = await fetchone(
        f"SELECT COUNT(*) AS v FROM game_scores WHERE player_id=? AND team_id=? AND {filt} AND score > 17",
        (pid, team_id), conn=conn
    )
    three_td = row['v'] if row else 0

    three_td_pct = round(three_td / games, 4) if games else None

    # 2PT%
    all_scores = [r['score'] for r in await fetchall(
        f"SELECT score FROM game_scores WHERE player_id=? AND team_id=? AND {filt}", (pid, team_id), conn=conn
    )]
    two_pt_pct = _two_pt_pct(all_scores)

    # Fumbles — directly logged per entry (via /score's optional Fumbles field),
    # never inferred from the score value. A fumble can happen on any real
    # played drive regardless of the final score, so this only excludes
    # forfeited/excused entries (no real drive happened at all), not any
    # particular score value.
    row = await fetchone(
        "SELECT COALESCE(SUM(fumbles),0) AS v FROM game_scores "
        "WHERE player_id=? AND team_id=? AND is_forfeit=0 AND is_excused=0",
        (pid, team_id), conn=conn
    )
    fumbles = row['v'] if row else 0

    # Missed Drives — days a player didn't play at all (stored as is_forfeit,
    # always treated as a 0 and excluded from every average/count above)
    row = await fetchone(
        "SELECT COUNT(*) AS v FROM game_scores WHERE player_id=? AND team_id=? AND is_forfeit=1",
        (pid, team_id), conn=conn
    )
    missed_drives = row['v'] if row else 0

    # 4th down conversion percentage (conversions/attempts) — scoped to
    # this team_id like everything else in this function, deliberately
    # NOT reusing get_player_fourth_down_rate directly, since that
    # function is intentionally career-wide/unscoped for its own purpose
    # (a plain by-name lookup), which would reintroduce the exact
    # cross-team bleeding this function exists everywhere else to avoid.
    # Stored as a decimal (0-1), matching three_td_pct/two_pt_pct's own
    # convention, not as a 0-100 number.
    row = await fetchone(
        "SELECT COALESCE(SUM(fourth_downs),0) AS attempts, COALESCE(SUM(fourth_down_convs),0) AS conversions "
        "FROM game_scores WHERE player_id=? AND team_id=?",
        (pid, team_id), conn=conn
    )
    fourth_down_attempts    = row['attempts'] if row else 0
    fourth_down_conversions = row['conversions'] if row else 0
    fourth_down_conv_pct = (
        round(fourth_down_conversions / fourth_down_attempts, 4) if fourth_down_attempts > 0 else None
    )

    # pwr_rank and ladder_rank — weights read from the same source as the
    # rest of this call, so a /legacy lookup reflects whatever weights were
    # actually in effect when that season was live, not today's weights.
    w_rows  = await fetchall("SELECT label, weight FROM pwr_rank_weights WHERE category='pwr_rank'", conn=conn)
    lw_rows = await fetchall("SELECT label, weight FROM pwr_rank_weights WHERE category='ladder'", conn=conn)
    w  = {r['label']: r['weight'] for r in w_rows}
    lw = {r['label']: r['weight'] for r in lw_rows}

    max_row = await fetchone(
        "SELECT MAX(total_ovr) AS mx FROM players WHERE team_id=? AND status='A'", (team_id,), conn=conn
    )
    max_ovr  = float(max_row['mx'] or 1) if max_row else 1.0
    player   = await fetchone("SELECT total_ovr, off_ovr FROM players WHERE id=?", (pid,), conn=conn)
    total_ovr = float(player['total_ovr'] or 0)
    off_ovr   = float(player['off_ovr']   or 0)

    def s(v): return float(v) if v else 0.0

    pwr_rank = (
        s(avg_yearly)  * w.get('yearly_avg',    0) / 24
        + s(avg_30day) * w.get('30day_avg',     0) / 24
        + s(hof_avg)   * w.get('hof_avg',       0) / 24
        + s(e1_avg)    * w.get('e1_avg',        0) / 24
        + s(e2_avg)    * w.get('e2_avg',        0) / 24
        + s(e3_avg)    * w.get('e3_avg',        0) / 24
        + s(gold_avg)  * w.get('gold_avg',      0) / 24
        + (total_ovr / max_ovr) * w.get('team_total_ovr', 0)
        # Fumble-adjusted counterparts — each is a separate, independently
        # weighted factor, not a replacement for the plain average above.
        # An admin who wants fumbles-as-null-drives to influence pwr_rank
        # sets a weight on these; leaving them at the default 0 weight (no
        # row in pwr_rank_weights for that label) means they contribute
        # nothing, identical to today's behavior.
        + s(avg_yearly_fumble_adj) * w.get('yearly_avg_fumble_adj', 0) / 24
        + s(avg_30day_fumble_adj)  * w.get('30day_avg_fumble_adj',  0) / 24
        + s(hof_avg_fumble_adj)    * w.get('hof_avg_fumble_adj',    0) / 24
        + s(e1_avg_fumble_adj)     * w.get('e1_avg_fumble_adj',     0) / 24
        + s(e2_avg_fumble_adj)     * w.get('e2_avg_fumble_adj',     0) / 24
        + s(e3_avg_fumble_adj)     * w.get('e3_avg_fumble_adj',     0) / 24
        + s(gold_avg_fumble_adj)   * w.get('gold_avg_fumble_adj',   0) / 24
        # Already a 0-1 percentage, not a 0-24 score — no /24 normalization,
        # same treatment as total_ovr/max_ovr above.
        + s(fourth_down_conv_pct)  * w.get('fourth_down_conv_pct',  0)
    ) * 100

    ladder_rank = (
        s(avg_3day)    * lw.get('3day_avg',         0) / 24
        + s(avg_7day)  * lw.get('7day_avg',          0) / 24
        + s(avg_14day) * lw.get('14day_avg',         0) / 24
        + s(avg_30day) * lw.get('30day_ladder',      0) / 24
        + (total_ovr / max_ovr) * lw.get('total_ovr_ladder', 0)
        + (off_ovr  / max_ovr) * lw.get('off_ovr_ladder',   0)
        # Fumble-adjusted counterparts — same independent-factor reasoning as pwr_rank above.
        + s(avg_3day_fumble_adj)   * lw.get('3day_avg_fumble_adj',     0) / 24
        + s(avg_7day_fumble_adj)   * lw.get('7day_avg_fumble_adj',     0) / 24
        + s(avg_14day_fumble_adj)  * lw.get('14day_avg_fumble_adj',    0) / 24
        + s(avg_30day_fumble_adj)  * lw.get('30day_ladder_fumble_adj', 0) / 24
        + s(fourth_down_conv_pct)  * lw.get('fourth_down_conv_pct',    0)
    ) * 100

    return {
        'avg_yearly': avg_yearly, 'avg_30day': avg_30day,
        'avg_14day': avg_14day,   'avg_7day': avg_7day,   'avg_3day': avg_3day,
        'hof_avg': hof_avg,       'e1_avg': e1_avg,       'e2_avg': e2_avg,
        'e3_avg': e3_avg,         'gold_avg': gold_avg,
        'avg_yearly_fumble_adj': avg_yearly_fumble_adj, 'avg_30day_fumble_adj': avg_30day_fumble_adj,
        'avg_14day_fumble_adj': avg_14day_fumble_adj,   'avg_7day_fumble_adj': avg_7day_fumble_adj,
        'avg_3day_fumble_adj': avg_3day_fumble_adj,
        'hof_avg_fumble_adj': hof_avg_fumble_adj,   'e1_avg_fumble_adj': e1_avg_fumble_adj,
        'e2_avg_fumble_adj': e2_avg_fumble_adj,     'e3_avg_fumble_adj': e3_avg_fumble_adj,
        'gold_avg_fumble_adj': gold_avg_fumble_adj,
        'games': games,           'points': points,
        'kobes': kobes,           'three_td': three_td,   'three_td_pct': three_td_pct,
        'two_pt_pct': two_pt_pct, 'fumbles': fumbles,
        'missed_drives': missed_drives,
        'fourth_down_attempts': fourth_down_attempts, 'fourth_down_conversions': fourth_down_conversions,
        'fourth_down_conv_pct': fourth_down_conv_pct,
        'pwr_rank': round(pwr_rank, 4),
        'ladder_rank': round(ladder_rank, 4),
    }


async def get_team_stats(team_id: str, conn=None) -> list[dict]:
    """
    Compute live stats for all active players on a team, sorted by pwr_rank.
    Used by /rank, ladder builder sort, and anywhere a full team view is needed.
    conn: optional archive connection (see get_archive_conn) for /legacy commands
    — status='A' is still honored, reflecting who was active in that
    season's own frozen snapshot (i.e. what /rank actually showed back then).
    """
    players = await fetchall(
        "SELECT id, ign, team_id, status, off_ovr, def_ovr, total_ovr "
        "FROM players WHERE team_id=? AND status='A' ORDER BY ign",
        (team_id,), conn=conn
    )
    results = []
    for p in players:
        stats = await get_player_stats(p['id'], team_id, conn=conn)
        results.append({**dict(p), **stats})
    results.sort(key=lambda x: x['pwr_rank'], reverse=True)
    return results


async def get_open_spots(conn=None) -> list[dict]:
    """
    For every league, how many open roster spots remain: 18 minus the
    current count of active (status='A') players on that team — "active"
    here means currently a member of the league roster at all, the
    18-cap membership concept. This is a distinct concept from "playing":
    of a league's active roster, up to 16 are selected to actually play in
    a given ladder/matchup/siege instance (see siege.py's header docstring
    and ladder_flow.py) — the remaining active members for that instance
    are "rested", not inactive. /openspots is asking about the 18-cap
    membership count specifically, not the 16-cap playing count, and
    active rosters aren't always exactly at either number in practice
    (see get_team_stats' own note on this).
    Sorted by most open spots first (descending) — the most immediately
    actionable order for a "where does a new player fit" kind of question,
    not alphabetical by league.
    Queries the teams table directly for both team_id and display name,
    rather than a hardcoded list — automatically covers however many
    leagues actually exist, including one added after this was written,
    with no code change needed here.
    Returns a list of {'team_id', 'name', 'active_count', 'open_spots'} dicts.
    """
    teams = await fetchall("SELECT id, name FROM teams ORDER BY id", conn=conn)
    results = []
    for team in teams:
        row = await fetchone(
            "SELECT COUNT(*) AS c FROM players WHERE team_id=? AND status='A'",
            (team['id'],), conn=conn
        )
        active_count = row['c'] if row else 0
        results.append({
            'team_id': team['id'],
            'name': team['name'],
            'active_count': active_count,
            'open_spots': 18 - active_count,
        })
    results.sort(key=lambda x: x['open_spots'], reverse=True)
    return results


async def get_league_stats(team_id: str, include_inactive: bool = False, conn=None) -> dict | None:
    """
    Per-player stats for /stats, plus a league-wide average row.
    include_inactive: when False (default), only currently-active players on
    this team count. When True, also includes players who are now inactive
    or have since transferred to a different league, as long as they have at
    least one historical game_scores entry for this team_id — someone who
    played a full season for this league before leaving shouldn't vanish from
    its historical averages just because they're not on the roster anymore.
    Returns None if there's no qualifying player at all.
    """
    if include_inactive:
        rows = await fetchall(
            """
            SELECT id, ign FROM players WHERE team_id=?
            UNION
            SELECT p.id, p.ign FROM players p
            WHERE p.id IN (SELECT DISTINCT player_id FROM game_scores WHERE team_id=?)
            """,
            (team_id, team_id), conn=conn
        )
    else:
        rows = await fetchall(
            "SELECT id, ign FROM players WHERE team_id=? AND status='A'", (team_id,), conn=conn
        )

    if not rows:
        return None

    players = []
    for r in rows:
        stats = await get_player_stats(r['id'], team_id, conn=conn)
        players.append({'ign': r['ign'], **stats})
    players.sort(key=lambda p: p['pwr_rank'], reverse=True)

    def avg_of(field):
        values = [p[field] for p in players if p.get(field) is not None]
        return round(sum(values) / len(values), 4) if values else None

    def sum_of(field):
        return sum(p.get(field) or 0 for p in players)

    return {
        'players':       players,
        'player_count':  len(players),
        'avg_yearly':    avg_of('avg_yearly'),
        'avg_30day':     avg_of('avg_30day'),
        'avg_14day':     avg_of('avg_14day'),
        'avg_7day':      avg_of('avg_7day'),
        'avg_3day':      avg_of('avg_3day'),
        'hof_avg':       avg_of('hof_avg'),
        'e1_avg':        avg_of('e1_avg'),
        'e2_avg':        avg_of('e2_avg'),
        'e3_avg':        avg_of('e3_avg'),
        'gold_avg':      avg_of('gold_avg'),
        'games':         sum_of('games'),
        'points':        sum_of('points'),
        'kobes':         sum_of('kobes'),
        'three_td':      sum_of('three_td'),
        'three_td_pct':  avg_of('three_td_pct'),
        'two_pt_pct':    avg_of('two_pt_pct'),
        'fumbles':       sum_of('fumbles'),
        'missed_drives': sum_of('missed_drives'),
    }


# ---------------------------------------------------------------------------
# Siege helpers
# ---------------------------------------------------------------------------
# A siege match pits 16 of our league's players (selected to play this
# specific match, not necessarily every active/rostered league member — see
# siege.py's header docstring for the full playing-vs-active distinction)
# against an opposing league. Up to 10 opposing players carry a "mod"; the
# rest carry none ("No Mod"). Each opposing player is a "node" — hidden until
# an admin/player reports it visible via /node, at which point it becomes
# "open" and stays that way until our league's cumulative points against it
# meet or exceed its points_required, at which point it flips to "cleared".
#
# Only one siege match may be 'active' per team at a time (enforced by a
# partial unique index — see the schema). /siegefinal closes it out.

SIEGE_MODS = [
    "DEF OVR Boost", "OFF OVR Boost", "Long Pass Plays Only", "Run Plays Only",
    "Play Action Plays Only", "Short Pass Plays Only", "60 Second Drives",
    "Random Playcall", "Skip 1st Down", "20 Yard First Downs", "No Mod",
]


async def get_active_siege_match(team_id: str) -> dict | None:
    return await fetchone(
        "SELECT * FROM siege_matches WHERE team_id=? AND status='active'", (team_id,)
    )


async def get_siege_match(match_id: int) -> dict | None:
    return await fetchone("SELECT * FROM siege_matches WHERE id=?", (match_id,))


async def start_siege_match(team_id: str, opp_league: str, opp_rank: str | None = None,
                             our_rank: str | None = None, division: str | None = None) -> dict:
    """Open a new active siege match for a league. Raises if one is already active."""
    existing = await get_active_siege_match(team_id)
    if existing is not None:
        raise ValueError(
            f"There's already an active siege match for this league (vs **{existing['opp_league']}**). "
            f"Use `/siegefinal` to close it out first."
        )
    match_id = await execute_insert(
        """
        INSERT INTO siege_matches (team_id, opp_league, opp_rank, our_rank, division, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'active', datetime('now'))
        """,
        (team_id, opp_league, opp_rank, our_rank, division)
    )
    return await get_siege_match(match_id)


async def update_siege_match(match_id: int, **fields):
    """Admin correction of match-level fields (opp_league, opp_rank, our_rank, division, opp_total_points)."""
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await execute(f"UPDATE siege_matches SET {set_clause} WHERE id=?", (*fields.values(), match_id))


async def finalize_siege_match(match_id: int):
    await execute(
        "UPDATE siege_matches SET status='completed', completed_at=datetime('now') WHERE id=?",
        (match_id,)
    )


async def add_siege_node(match_id: int, mod: str, opponent_name: str, opponent_ovr: int | None,
                          points_required: int, points_reward: int) -> dict:
    """
    Each of the 10 named mods appears exactly once per match — reject a second
    node under the same named mod (almost always a mistyped mod on /node).
    "No Mod" is exempt: up to 6 un-modded opponents exist per match.
    """
    if mod != "No Mod":
        existing = await fetchone(
            "SELECT id FROM siege_nodes WHERE match_id=? AND mod=?", (match_id, mod)
        )
        if existing is not None:
            raise ValueError(
                f"**{mod}** has already been reported for this match — each named mod "
                f"appears once per match. Use `/updatesiege` if this needs correcting."
            )

    node_id = await execute_insert(
        """
        INSERT INTO siege_nodes
            (match_id, mod, opponent_name, opponent_ovr, points_required, points_reward, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', datetime('now'))
        """,
        (match_id, mod, opponent_name, opponent_ovr, points_required, points_reward)
    )
    return await get_siege_node(node_id)


async def get_siege_node(node_id: int) -> dict | None:
    return await fetchone("SELECT * FROM siege_nodes WHERE id=?", (node_id,))


async def get_siege_nodes(match_id: int, status: str | None = None) -> list[dict]:
    """All nodes for a match, optionally filtered to 'open' or 'cleared'."""
    if status:
        return await fetchall(
            "SELECT * FROM siege_nodes WHERE match_id=? AND status=? ORDER BY id",
            (match_id, status)
        )
    return await fetchall("SELECT * FROM siege_nodes WHERE match_id=? ORDER BY id", (match_id,))


async def get_siege_open_nodes_by_name(match_id: int, opponent_name: str) -> list[dict]:
    """
    All OPEN nodes with this exact name in a match. Named mods are unique per
    match, so a name collision can only happen among the up-to-6 "No Mod"
    nodes — this can legitimately return more than one row, which callers
    (e.g. /siegescore's manual-name fallback) must treat as ambiguous rather
    than guessing.
    """
    return await fetchall(
        "SELECT * FROM siege_nodes WHERE match_id=? AND opponent_name=? AND status='open'",
        (match_id, opponent_name)
    )


async def update_siege_node(node_id: int, **fields):
    """Admin correction of a node's info (opponent_name, opponent_ovr, points_required, points_reward, mod)."""
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    await execute(f"UPDATE siege_nodes SET {set_clause} WHERE id=?", (*fields.values(), node_id))


async def get_siege_node_totals(node_id: int) -> dict:
    """Cumulative points/drives logged against a node so far."""
    row = await fetchone(
        "SELECT COALESCE(SUM(points),0) AS points, COALESCE(SUM(drives),0) AS drives "
        "FROM siege_scores WHERE node_id=?",
        (node_id,)
    )
    return row or {'points': 0, 'drives': 0}


async def log_siege_score(node_id: int, ign: str, drives: int, points: int) -> dict:
    """
    Record a player's drives/points against an open node. If the player has
    already logged a score against this same node, that entry is replaced
    (not added to) — re-running /siegescore for the same player+node always
    reflects only their latest submission, matching how a plain correction
    is expected to work. If the league's cumulative points against the node
    now meet or exceed points_required, the node flips from open to cleared.
    """
    player = await get_player(ign)
    if player is None:
        raise ValueError(f"Player '{ign}' not found.")

    node = await get_siege_node(node_id)
    if node is None:
        raise ValueError("That node no longer exists.")
    if node['status'] != 'open':
        raise ValueError(f"**{node['opponent_name']}** has already been cleared.")

    existing = await fetchone(
        "SELECT id FROM siege_scores WHERE node_id=? AND player_id=?",
        (node_id, player['id'])
    )
    if existing:
        await execute(
            "UPDATE siege_scores SET drives=?, points=?, created_at=datetime('now') WHERE id=?",
            (drives, points, existing['id'])
        )
    else:
        await execute(
            "INSERT INTO siege_scores (node_id, player_id, drives, points, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (node_id, player['id'], drives, points)
        )

    totals  = await get_siege_node_totals(node_id)
    cleared = totals['points'] >= node['points_required']
    if cleared:
        await execute(
            "UPDATE siege_nodes SET status='cleared', cleared_at=datetime('now') WHERE id=?",
            (node_id,)
        )
    return {'cleared': cleared, 'totals': totals}


async def get_siege_score(score_id: int) -> dict | None:
    return await fetchone("SELECT * FROM siege_scores WHERE id=?", (score_id,))


async def get_siege_scores_for_node(node_id: int) -> list[dict]:
    return await fetchall(
        """
        SELECT ss.*, p.ign FROM siege_scores ss
        JOIN players p ON p.id = ss.player_id
        WHERE ss.node_id=? ORDER BY ss.created_at
        """,
        (node_id,)
    )


async def get_siege_scores_for_match(match_id: int, limit: int = 25) -> list[dict]:
    """
    Most recent score entries logged in a match, across all nodes — used by the
    admin correction UI (capped at 25 since that's Discord's max Select options;
    corrections are almost always for something logged recently anyway).
    """
    return await fetchall(
        """
        SELECT ss.*, p.ign, sn.opponent_name, sn.mod
        FROM siege_scores ss
        JOIN siege_nodes sn ON sn.id = ss.node_id
        JOIN players p ON p.id = ss.player_id
        WHERE sn.match_id=?
        ORDER BY ss.created_at DESC
        LIMIT ?
        """,
        (match_id, limit)
    )


async def get_siege_scores_for_player(match_id: int, ign: str) -> list[dict]:
    player = await get_player(ign)
    if player is None:
        return []
    return await fetchall(
        """
        SELECT ss.*, sn.opponent_name, sn.mod FROM siege_scores ss
        JOIN siege_nodes sn ON sn.id = ss.node_id
        WHERE sn.match_id=? AND ss.player_id=?
        ORDER BY ss.created_at
        """,
        (match_id, player['id'])
    )


async def recheck_siege_node_status(node_id: int):
    """
    Re-derive a node's open/cleared status from its current totals vs
    points_required. Shared by update_siege_score (after a drives/points
    correction) and the node-info correction UI (after a points_required edit).
    """
    node   = await get_siege_node(node_id)
    totals = await get_siege_node_totals(node_id)
    should_be_cleared = totals['points'] >= node['points_required']
    if should_be_cleared and node['status'] != 'cleared':
        await execute(
            "UPDATE siege_nodes SET status='cleared', cleared_at=datetime('now') WHERE id=?",
            (node_id,)
        )
    elif not should_be_cleared and node['status'] != 'open':
        await execute(
            "UPDATE siege_nodes SET status='open', cleared_at=NULL WHERE id=?",
            (node_id,)
        )


async def update_siege_score(score_id: int, **fields):
    """
    Admin correction of a logged score entry (drives, points). Re-evaluates the
    node's cleared/open status afterward, since the totals may have changed —
    including re-opening a node if a correction drops it back below required.
    """
    row = await get_siege_score(score_id)
    if row is None:
        raise ValueError("That score entry no longer exists.")
    if fields:
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await execute(f"UPDATE siege_scores SET {set_clause} WHERE id=?", (*fields.values(), score_id))

    await recheck_siege_node_status(row['node_id'])


async def get_siege_player_totals(match_id: int, ign: str) -> dict:
    """A player's cumulative points/drives in a given siege match, across all nodes."""
    player = await get_player(ign)
    if player is None:
        return {'points': 0, 'drives': 0}
    row = await fetchone(
        """
        SELECT COALESCE(SUM(ss.points),0) AS points, COALESCE(SUM(ss.drives),0) AS drives
        FROM siege_scores ss JOIN siege_nodes sn ON sn.id = ss.node_id
        WHERE sn.match_id=? AND ss.player_id=?
        """,
        (match_id, player['id'])
    )
    return row or {'points': 0, 'drives': 0}


async def get_siege_all_player_totals(match_id: int) -> list[dict]:
    """Every player who's logged a score in this match, with cumulative points/drives."""
    return await fetchall(
        """
        SELECT p.ign, COALESCE(SUM(ss.points),0) AS points, COALESCE(SUM(ss.drives),0) AS drives
        FROM siege_scores ss
        JOIN siege_nodes sn ON sn.id = ss.node_id
        JOIN players p ON p.id = ss.player_id
        WHERE sn.match_id=?
        GROUP BY p.id
        ORDER BY points DESC
        """,
        (match_id,)
    )


async def get_siege_match_summary(match_id: int) -> dict:
    """
    Aggregate numbers used by /siegestatus and the league score formula:
    league_score = open_node_points + cleared_required_total + cleared_reward_total + ppd_bonus
    where ppd_bonus = 30*ppd - 25 (left un-floored — can go negative).
    """
    match = await get_siege_match(match_id)
    nodes = await get_siege_nodes(match_id)

    open_nodes    = [dict(n) for n in nodes if n['status'] == 'open']
    cleared_nodes = [dict(n) for n in nodes if n['status'] == 'cleared']

    open_node_points = 0
    for n in open_nodes:
        totals = await get_siege_node_totals(n['id'])
        n['points_so_far'] = totals['points']
        n['drives_so_far'] = totals['drives']
        open_node_points  += totals['points']

    cleared_required_total = sum(n['points_required'] for n in cleared_nodes)
    cleared_reward_total   = sum(n['points_reward']   for n in cleared_nodes)

    totals_row = await fetchone(
        """
        SELECT COALESCE(SUM(ss.points),0) AS points, COALESCE(SUM(ss.drives),0) AS drives
        FROM siege_scores ss JOIN siege_nodes sn ON sn.id = ss.node_id
        WHERE sn.match_id=?
        """,
        (match_id,)
    )
    total_points = totals_row['points']
    total_drives = totals_row['drives']
    ppd          = (total_points / total_drives) if total_drives else 0
    # Un-floored per the design — can go negative — but rounded to a whole
    # point value since every other league total here is an integer.
    ppd_bonus    = round(30 * ppd - 25)

    league_score = open_node_points + cleared_required_total + cleared_reward_total + ppd_bonus

    # "3 highest point value nodes" = ranked by their clear reward (points_reward)
    top_open     = sorted(open_nodes, key=lambda n: n['points_reward'], reverse=True)[:3]
    top_open_ids = {n['id'] for n in top_open}

    return {
        'match': match,
        'open_nodes': open_nodes,
        'cleared_nodes': cleared_nodes,
        'top_open_ids': top_open_ids,
        'open_node_points': open_node_points,
        'cleared_required_total': cleared_required_total,
        'cleared_reward_total': cleared_reward_total,
        'total_points': total_points,
        'total_drives': total_drives,
        'ppd': round(ppd, 3),
        'ppd_bonus': ppd_bonus,
        'league_score': league_score,
    }


async def get_siege_splits(ign: str) -> list[dict]:
    """A player's cumulative points/drives broken down by mod, across every siege match they've played."""
    player = await get_player(ign)
    if player is None:
        return []
    return await fetchall(
        """
        SELECT sn.mod,
               COALESCE(SUM(ss.points),0) AS points,
               COALESCE(SUM(ss.drives),0) AS drives
        FROM siege_scores ss
        JOIN siege_nodes sn ON sn.id = ss.node_id
        WHERE ss.player_id=?
        GROUP BY sn.mod
        ORDER BY points DESC
        """,
        (player['id'],)
    )


async def get_siege_history(team_id: str, limit: int = 10) -> list[dict]:
    """Past completed siege matches for a league, most recent first."""
    return await fetchall(
        """
        SELECT * FROM siege_matches
        WHERE team_id=? AND status='completed'
        ORDER BY completed_at DESC
        LIMIT ?
        """,
        (team_id, limit)
    )
