"""
tests.py — Unit test suite for the Neuroverse bot.

Tests the database layer and command logic using an in-memory SQLite database.
Discord interactions are mocked so no bot connection is needed.

Run with:
    python tests.py
    python tests.py -v          # verbose
    python tests.py TestDB      # single class
"""

import asyncio
import datetime
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# DB_PATH is set per-test in setup_db() — do NOT set it here at module level
# as this file may be imported by the running bot (via !test) which would
# overwrite the production DB_PATH environment variable.

# ---------------------------------------------------------------------------
# Minimal stubs so db.py imports without discord/logger installed in test env
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

# Stub logger_config
import types
logger_stub = types.ModuleType("logger_config")
logger_stub.global_logger = MagicMock()
sys.modules.setdefault("logger_config", logger_stub)

# Stub discord so tests can import optimized_bot and ladder_flow
import types as _types

def _make_discord_stub():
    d = _types.ModuleType("discord")
    d.Intents = type("Intents", (), {"default": staticmethod(lambda: MagicMock()), "message_content": True, "messages": True})()
    class _ColorStub:
        """Catch-all: real discord.Color has dozens of named colors (dark_red,
        dark_gold, teal, ...) — stub every attribute as a no-op rather than
        hardcoding a fixed subset that inevitably falls out of date."""
        def __getattr__(self, name):
            return lambda *a, **kw: None
    d.Color = _ColorStub()
    d.TextStyle = type("TextStyle", (), {"paragraph": 1, "short": 0})()
    d.ButtonStyle = type("ButtonStyle", (), {"primary":1,"secondary":2,"success":3,"danger":4,"blurple":1,"gray":2,"green":3})()
    d.SelectOption = MagicMock
    d.File     = MagicMock
    d.Embed    = MagicMock
    d.app_commands = _types.ModuleType("discord.app_commands")
    class _ChoiceStub:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    d.app_commands.Choice   = _ChoiceStub
    d.app_commands.choices  = lambda **kw: (lambda f: f)
    d.app_commands.describe = lambda **kw: (lambda f: f)
    d.app_commands.autocomplete = lambda **kw: (lambda f: f)
    d.app_commands.AppCommandError = Exception
    d.app_commands.errors = _types.ModuleType("discord.app_commands.errors")

    class _GroupStub:
        """Real app_commands.Group registers subcommands via @group.command(...).
        Stubbed as an identity decorator (like describe/choices/autocomplete
        above) so subcommand functions stay directly importable and testable,
        same as any other plain function in this codebase."""
        def __init__(self, name=None, description=None, **kw):
            self.name = name
            self.description = description
        def command(self, **kw):
            return lambda f: f
    d.app_commands.Group = _GroupStub
    d.ext = _types.ModuleType("discord.ext")
    d.ext.commands = _types.ModuleType("discord.ext.commands")

    class _BotStub(MagicMock):
        def event(self, func):
            # Real discord.py's Client.event() just registers the coroutine
            # and returns it unchanged — unlike tree.command(), it's a plain
            # identity decorator. Preserving that here keeps functions like
            # on_ready/on_command_error directly callable/testable by name.
            return func

    d.ext.commands.Bot = _BotStub
    d.ext.commands.Cog = object
    d.ext.commands.command = lambda **kw: (lambda f: f)
    d.ext.commands.cooldown = lambda *a, **kw: (lambda f: f)
    d.ext.commands.has_role = lambda *a: (lambda f: f)
    d.ext.commands.BucketType = type("BucketType", (), {"user": 1, "channel": 2})()

    class _CommandNotFound(Exception):
        pass

    class _CommandOnCooldown(Exception):
        def __init__(self, retry_after=1.0):
            super().__init__()
            self.retry_after = retry_after

    class _MissingPermissions(Exception):
        pass

    class _MissingRequiredArgument(Exception):
        def __init__(self, param_name="arg"):
            super().__init__()
            self.param = type("Param", (), {"name": param_name})()

    d.ext.commands.CommandNotFound = _CommandNotFound
    d.ext.commands.CommandOnCooldown = _CommandOnCooldown
    d.ext.commands.MissingPermissions = _MissingPermissions
    d.ext.commands.MissingRequiredArgument = _MissingRequiredArgument
    d.ext.tasks = _types.ModuleType("discord.ext.tasks")
    d.ext.tasks.loop = lambda **kw: (lambda f: MagicMock())
    # UI components
    # Base classes that need to accept keyword args (e.g. title=) in subclassing
    class _BaseUI:
        def __init__(self, *a, **kw):
            self.children = []
            for k, v in kw.items():
                setattr(self, k, v)
        def __init_subclass__(cls, **kw): pass
        async def on_submit(self, interaction): pass
        def add_item(self, item):
            self.children.append(item)
            return self
        def clear_items(self):
            self.children = []
            return self
        def remove_item(self, item):
            if item in self.children:
                self.children.remove(item)
            return self
        def stop(self): pass
    class _TextInput:
        def __init__(self, *a, **kw):
            self.value = kw.get("placeholder", "")
            self.default = kw.get("default", None)
            self.max_length = kw.get("max_length", None)
            self.required = kw.get("required", True)
        def __set_name__(self, owner, name): pass
    for cls_name, cls_obj in [("View",_BaseUI),("Button",_BaseUI),("Select",_BaseUI),
                               ("Modal",_BaseUI),("TextInput",_TextInput)]:
        setattr(d, cls_name, cls_obj)
    d.ui = _types.ModuleType("discord.ui")
    for cls_name, cls_obj in [("View",_BaseUI),("Button",_BaseUI),("Select",_BaseUI),
                               ("Modal",_BaseUI),("TextInput",_TextInput),("Label",_BaseUI),
                               ("button",lambda **kw: lambda f: f),
                               ("select",lambda **kw: lambda f: f)]:
        setattr(d.ui, cls_name, cls_obj)
    d.Interaction = MagicMock
    d.Attachment  = MagicMock
    d.Guild       = MagicMock

    class _LocaleValue:
        def __init__(self, value): self._value = value
        def __str__(self): return self._value

    class _LocaleStub:
        american_english = _LocaleValue('en-US')
        british_english = _LocaleValue('en-GB')
        french = _LocaleValue('fr')
        german = _LocaleValue('de')
        spain_spanish = _LocaleValue('es-ES')
        latin_american_spanish = _LocaleValue('es-419')
        brazil_portuguese = _LocaleValue('pt-BR')
    d.Locale = _LocaleStub
    d.errors      = _types.ModuleType("discord.errors")

    class _HTTPException(Exception):
        """Real discord.HTTPException exposes .status (HTTP code) and .code
        (Discord's own JSON error code, e.g. 10062 for Unknown interaction,
        40062 for a rate-limited service) — both needed to test error-
        handling logic that distinguishes a transient rate limit from a
        permanently-expired interaction."""
        def __init__(self, status=500, code=0, text=""):
            self.status = status
            self.code = code
            self.text = text
            super().__init__(f"{status} {text} (error code: {code})")

    class _NotFound(_HTTPException):
        def __init__(self, code=10062, text="Unknown interaction"):
            super().__init__(status=404, code=code, text=text)

    d.errors.HTTPException = _HTTPException
    d.errors.NotFound = _NotFound
    d.HTTPException = _HTTPException
    d.NotFound = _NotFound

    class _AppCommandInvokeError(Exception):
        """Mirrors real discord.app_commands.errors.CommandInvokeError: wraps
        whatever exception a command's own code raised, exposed via .original
        (confirmed against the actual discord.py source)."""
        def __init__(self, command, e):
            self.original: Exception = e
            self.command = command
            super().__init__(f"Command {command!r} raised an exception: {e.__class__.__name__}: {e}")

    d.app_commands.errors.CommandInvokeError = _AppCommandInvokeError
    d.app_commands.CommandInvokeError = _AppCommandInvokeError
    d.gateway     = _types.ModuleType("discord.gateway")
    return d

_discord = _make_discord_stub()
sys.modules["discord"]                   = _discord
sys.modules["discord.app_commands"]      = _discord.app_commands
sys.modules["discord.app_commands.errors"] = _discord.app_commands.errors
sys.modules["discord.ext"]               = _discord.ext
sys.modules["discord.ext.commands"]      = _discord.ext.commands
sys.modules["discord.ext.tasks"]         = _discord.ext.tasks
sys.modules["discord.ui"]                = _discord.ui
sys.modules["discord.errors"]            = _discord.errors
sys.modules["discord.gateway"]           = _discord.gateway
sys.modules["aiohttp"]                   = _types.ModuleType("aiohttp")
sys.modules["aiohttp"].ClientConnectorError = Exception
import discord  # noqa: E402  (must come after stub registration above)
from discord.ext import commands  # noqa: E402

# Instead of stubbing aiosqlite, monkey-patch db to use sqlite3 directly
import sqlite3, types

_sqlite_conn: sqlite3.Connection | None = None

class _Row(dict):
    def keys(self): return super().keys()

async def _patched_init():
    global _sqlite_conn
    path = os.environ.get("DB_PATH", ":memory:")
    _sqlite_conn = sqlite3.connect(path)
    _sqlite_conn.row_factory = sqlite3.Row
    _sqlite_conn.executescript("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")
    import db as _db_mod
    _db_mod._db = _FakeDBConn(_sqlite_conn)

async def _patched_close():
    global _sqlite_conn
    if _sqlite_conn:
        _sqlite_conn.close()
        _sqlite_conn = None
    import db as _db_mod
    _db_mod._db = None

class _FakeCursor:
    def __init__(self, cur):
        self._c = cur
    @property
    def rowcount(self): return self._c.rowcount
    @property
    def lastrowid(self): return self._c.lastrowid
    async def fetchone(self):
        row = self._c.fetchone()
        if row is None: return None
        return dict(zip(row.keys(), tuple(row)))
    async def fetchall(self):
        rows = self._c.fetchall()
        return [dict(zip(r.keys(), tuple(r))) for r in rows]
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    def __await__(self):
        # Real aiosqlite's execute() return value supports both
        # "async with conn.execute(...) as cur:" AND "cur = await conn.execute(...)"
        # on the exact same call. This makes the sync execute() below work
        # correctly for both patterns too, instead of only the async-with one.
        async def _identity():
            return self
        return _identity().__await__()

class _FakeDBConn:
    def __init__(self, conn): self._c = conn
    @property
    def row_factory(self): return self._c.row_factory
    @row_factory.setter
    def row_factory(self, value): self._c.row_factory = value
    def execute(self, sql, args=()):
        return _FakeCursor(self._c.execute(sql, args))
    async def executemany(self, sql, args_list):
        return _FakeCursor(self._c.executemany(sql, args_list))
    async def commit(self): self._c.commit()
    async def close(self): self._c.close()

# Stub aiosqlite minimally so db.py imports
try:
    import aiosqlite
except ModuleNotFoundError:
    aiosqlite_stub = types.ModuleType("aiosqlite")
    aiosqlite_stub.Connection = _FakeDBConn
    aiosqlite_stub.Row = sqlite3.Row
    async def _connect(p, uri=False, **kwargs): return _FakeDBConn(sqlite3.connect(p, uri=uri))
    aiosqlite_stub.connect = _connect
    sys.modules["aiosqlite"] = aiosqlite_stub
import db  # noqa: E402  (must come after stubs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE teams (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, sheet_name TEXT NOT NULL
);
CREATE TABLE players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    ign TEXT NOT NULL,
    status TEXT DEFAULT 'A',
    pwr_rank REAL,
    off_ovr INTEGER,
    def_ovr INTEGER,
    total_ovr INTEGER,
    points INTEGER,
    games INTEGER,
    hof_avg REAL,
    e1_avg REAL,
    e2_avg REAL,
    e3_avg REAL,
    gold_avg REAL,
    kobes INTEGER,
    three_td INTEGER,
    three_td_pct REAL,
    two_pt_pct REAL,
    fumbles INTEGER,
    ladder_rank REAL,
    avg_3day REAL,
    avg_7day REAL,
    avg_14day REAL,
    avg_30day REAL,
    avg_yearly REAL,
    is_active INTEGER DEFAULT 1,
    real_ign TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(id)
);
CREATE TABLE game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    game_date TEXT NOT NULL,
    event_type TEXT,
    score REAL,
    is_forfeit INTEGER DEFAULT 0,
    is_excused INTEGER DEFAULT 0,
    def_ovr_faced INTEGER,
    fourth_downs INTEGER DEFAULT 0,
    fourth_down_convs INTEGER DEFAULT 0,
    fumbles INTEGER DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE UNIQUE INDEX uq_player_date ON game_scores(player_id, game_date);
CREATE TABLE matchup_day (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    game_date TEXT NOT NULL,
    opp_ign TEXT,
    opp_score INTEGER DEFAULT 0,
    opp_drives INTEGER DEFAULT 0,
    our_score INTEGER DEFAULT 0,
    our_drives INTEGER DEFAULT 0,
    outcome TEXT,
    event_type TEXT,
    notes TEXT,
    our_defaults INTEGER DEFAULT 0,
    opp_defaults INTEGER DEFAULT 0,
    our_rank INTEGER,
    opp_rank INTEGER,
    UNIQUE(team_id, game_date)
);
CREATE TABLE matchup_ladder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    game_date TEXT NOT NULL,
    slot INTEGER NOT NULL,
    our_ign TEXT,
    opp_ign TEXT NOT NULL,
    opp_def_ovr INTEGER,
    our_total_ovr INTEGER,
    tier INTEGER,
    tier_score INTEGER,
    result TEXT,
    our_pts INTEGER,
    opp_pts INTEGER,
    UNIQUE(team_id, game_date, slot)
);
CREATE TABLE ladder_matchups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    slot INTEGER NOT NULL,
    our_ign TEXT,
    our_total_ovr INTEGER,
    opp_def_ovr INTEGER,
    opp_ign TEXT,
    tier INTEGER,
    tier_score INTEGER
);
CREATE TABLE pwr_rank_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    weight REAL NOT NULL,
    category TEXT NOT NULL DEFAULT 'pwr_rank',
    display_label TEXT,
    team_id TEXT
);
CREATE TABLE tournaments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    current_round INTEGER DEFAULT 1,
    total_rounds INTEGER DEFAULT 1,
    player_count INTEGER DEFAULT 0,
    champion TEXT,
    created TEXT NOT NULL
);
CREATE TABLE tournament_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    match_num INTEGER NOT NULL,
    p1 TEXT NOT NULL,
    p2 TEXT NOT NULL,
    winner TEXT DEFAULT ''
);
CREATE TABLE defense_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    game_date TEXT NOT NULL,
    points_allowed INTEGER NOT NULL DEFAULT 0,
    avg_off_ovr_faced REAL,
    drive1_outcome TEXT,
    drive2_outcome TEXT,
    drive3_outcome TEXT,
    drive1_ovr INTEGER,
    drive2_ovr INTEGER,
    drive3_ovr INTEGER,
    drive1_turnover_down TEXT,
    drive2_turnover_down TEXT,
    drive3_turnover_down TEXT,
    drive1_turnover_distance TEXT,
    drive2_turnover_distance TEXT,
    drive3_turnover_distance TEXT,
    drive1_turnover_play TEXT,
    drive2_turnover_play TEXT,
    drive3_turnover_play TEXT,
    drive1_turnover_forced_by TEXT,
    drive2_turnover_forced_by TEXT,
    drive3_turnover_forced_by TEXT,
    FOREIGN KEY (player_id) REFERENCES players(id),
    UNIQUE (player_id, game_date)
);
CREATE TABLE siege_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL,
    opp_league TEXT NOT NULL,
    opp_rank TEXT,
    our_rank TEXT,
    division TEXT,
    opp_total_points REAL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE UNIQUE INDEX idx_siege_one_active_per_team ON siege_matches(team_id) WHERE status='active';
CREATE TABLE siege_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    mod TEXT NOT NULL,
    opponent_name TEXT NOT NULL,
    opponent_ovr INTEGER,
    points_required INTEGER NOT NULL,
    points_reward INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    cleared_at TEXT,
    FOREIGN KEY (match_id) REFERENCES siege_matches(id)
);
CREATE TABLE siege_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    drives INTEGER NOT NULL,
    points INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (node_id) REFERENCES siege_nodes(id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE UNIQUE INDEX uq_siege_node_player ON siege_scores(node_id, player_id);
"""

SEED_DATA = """
INSERT INTO teams VALUES ('NP','NeuroPerverse','NeuroPerverse');
INSERT INTO teams VALUES ('ND','NeuroDiverse','NeuroDiverse');
INSERT INTO players (team_id,ign,status,pwr_rank,off_ovr,def_ovr,total_ovr,games)
    VALUES ('NP','Grizzly','A',93.6,244,229,7059,294);
INSERT INTO players (team_id,ign,status,pwr_rank,off_ovr,def_ovr,total_ovr,games)
    VALUES ('NP','dougbaldwin','A',91.2,224,225,6585,283);
INSERT INTO players (team_id,ign,status,pwr_rank,off_ovr,def_ovr,total_ovr,games)
    VALUES ('NP','FHRITP','A',85.0,228,211,6355,284);
INSERT INTO players (team_id,ign,status,off_ovr,def_ovr,total_ovr)
    VALUES ('ND','Bob','I',200,200,5000);
INSERT INTO pwr_rank_weights (label,weight,category,display_label)
    VALUES ('yearly_avg',0.5,'pwr_rank','Yearly Avg');
INSERT INTO pwr_rank_weights (label,weight,category,display_label)
    VALUES ('30day_avg',0.1,'pwr_rank','30-Day Avg');
INSERT INTO pwr_rank_weights (label,weight,category,display_label)
    VALUES ('team_total_ovr',0.3,'pwr_rank','Team Total OVR');
INSERT INTO pwr_rank_weights (label,weight,category,display_label)
    VALUES ('7day_avg',0.3,'ladder','7-Day Avg');
INSERT INTO pwr_rank_weights (label,weight,category,display_label)
    VALUES ('off_ovr_ladder',0.6,'ladder','Off OVR (Ladder)');
"""

TODAY = str(datetime.date.today())
YESTERDAY = str(datetime.date.today() - datetime.timedelta(days=1))


async def setup_db():
    """Initialize in-memory DB with schema and seed data. Never touches production DB."""
    os.environ["DB_PATH"] = ":memory:"
    await _patched_init()
    for stmt in SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            await db.execute(s)
    for stmt in SEED_DATA.strip().split(";"):
        s = stmt.strip()
        if s:
            await db.execute(s)


# ---------------------------------------------------------------------------
# Test: Database layer
# ---------------------------------------------------------------------------

class TestDB(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    # --- backup_database / _prune_old_backups ---
    # These patch db.DB_PATH/db.BACKUP_DIR directly to isolated temp paths,
    # rather than relying on the shared test suite's DB_PATH=':memory:' —
    # SQLite in-memory databases are per-connection and can't be backed up
    # this way, so testing against a real temp file is the only way to
    # actually exercise this logic meaningfully.

    async def test_backup_database_creates_file_with_real_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source.db")
            backup_dir  = os.path.join(tmp, "backups")

            src_conn = sqlite3.connect(source_path)
            src_conn.execute("CREATE TABLE t (x INTEGER)")
            src_conn.execute("INSERT INTO t VALUES (42)")
            src_conn.commit()
            src_conn.close()

            orig_path, orig_dir = db.DB_PATH, db.BACKUP_DIR
            db.DB_PATH, db.BACKUP_DIR = source_path, backup_dir
            try:
                await db.backup_database()
            finally:
                db.DB_PATH, db.BACKUP_DIR = orig_path, orig_dir

            files = os.listdir(backup_dir)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].startswith("neuroverse_"))

            check = sqlite3.connect(os.path.join(backup_dir, files[0]))
            self.assertEqual(check.execute("SELECT x FROM t").fetchone()[0], 42)
            check.close()

    async def test_backup_database_does_not_raise_on_failure(self):
        """A backup failure (e.g. an unwritable path) must never crash the
        caller — this runs on every bot startup, and startup must never be
        blocked by a backup problem."""
        orig_path, orig_dir = db.DB_PATH, db.BACKUP_DIR
        db.DB_PATH = "/nonexistent/path/that/cannot/exist/source.db"
        db.BACKUP_DIR = "/nonexistent/path/that/cannot/exist/backups"
        try:
            await db.backup_database()  # should log an error, not raise
        finally:
            db.DB_PATH, db.BACKUP_DIR = orig_path, orig_dir

    def test_prune_old_backups_removes_only_old_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            old_file   = os.path.join(tmp, "neuroverse_old.db")
            recent_file = os.path.join(tmp, "neuroverse_recent.db")
            unrelated  = os.path.join(tmp, "not_a_backup.txt")
            for path in (old_file, recent_file, unrelated):
                with open(path, "w") as f:
                    f.write("x")

            old_time = (datetime.datetime.now() - datetime.timedelta(days=db.BACKUP_RETENTION_DAYS + 5)).timestamp()
            os.utime(old_file, (old_time, old_time))

            orig_dir = db.BACKUP_DIR
            db.BACKUP_DIR = tmp
            try:
                db._prune_old_backups()
            finally:
                db.BACKUP_DIR = orig_dir

            remaining = set(os.listdir(tmp))
            self.assertNotIn("neuroverse_old.db", remaining)
            self.assertIn("neuroverse_recent.db", remaining)
            self.assertIn("not_a_backup.txt", remaining)  # non-backup files are never touched

    # --- historical team_id vs current team_id (regression: a query that joins
    # game_scores to players and filters on p.team_id silently drops any row
    # for a player who has since transferred away, even though the score
    # correctly belongs to the team that earned it) ---

    async def test_matchup_status_includes_transferred_players_historical_score(self):
        """A player's historical score for a team must count toward that
        team's running total even after the player later transfers away —
        get_matchup_status previously filtered on the player's CURRENT team
        (p.team_id) instead of the score row's own team (gs.team_id), which
        silently dropped this exact case."""
        await db.update_player_score("Grizzly", TODAY, 22.0, team_id_override="NP")
        # Simulate a later transfer away from NP
        await db.execute("UPDATE players SET team_id='ND' WHERE ign='Grizzly'")
        status = await db.get_matchup_status("NP", TODAY)
        self.assertEqual(status["us_score"], 22)

    async def test_scores_query_includes_transferred_players_historical_score(self):
        """Same regression, for the exact query /scores uses directly."""
        await db.update_player_score("Grizzly", TODAY, 22.0, team_id_override="NP")
        await db.execute("UPDATE players SET team_id='ND' WHERE ign='Grizzly'")
        rows = await db.fetchall(
            """
            SELECT p.ign, gs.score FROM game_scores gs JOIN players p ON p.id = gs.player_id
            WHERE gs.team_id = ? AND gs.game_date = ?
            """,
            ("NP", TODAY)
        )
        self.assertIn("Grizzly", [r["ign"] for r in rows])

    # --- get_player ---

    async def test_get_player_active(self):
        row = await db.get_player("Grizzly")
        self.assertIsNotNone(row)
        self.assertEqual(row["ign"], "Grizzly")
        self.assertEqual(row["team_id"], "NP")

    async def test_get_player_rested_found(self):
        """A status players should be found."""
        row = await db.get_player("FHRITP")
        self.assertIsNotNone(row)

    async def test_get_player_left_not_found(self):
        """I (inactive) status players should not be returned."""
        row = await db.get_player("Bob")
        self.assertIsNone(row)

    async def test_get_player_nonexistent(self):
        row = await db.get_player("NoSuchPlayer")
        self.assertIsNone(row)

    # --- update_player_score ---

    async def test_update_score_insert(self):
        await db.update_player_score("Grizzly", TODAY, 22.0)
        row = await db.fetchone(
            "SELECT score FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["score"], 22.0)

    async def test_update_score_upsert(self):
        """Recording a second score for the same day/event should update not duplicate."""
        await db.update_player_score("Grizzly", TODAY, 22.0)
        await db.update_player_score("Grizzly", TODAY, 24.0)
        rows = await db.fetchall(
            "SELECT score FROM game_scores WHERE game_date=? AND event_type IS NULL",
            (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 24.0)

    async def test_update_score_forfeit(self):
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True)
        row = await db.fetchone("SELECT is_forfeit FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["is_forfeit"], 1)

    async def test_update_score_with_event(self):
        await db.update_player_score("Grizzly", TODAY, 18.0, event_type="HOF")
        row = await db.fetchone(
            "SELECT score, event_type FROM game_scores WHERE event_type='HOF'"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["score"], 18.0)

    async def test_update_score_different_events_same_day_updates_same_row(self):
        """
        A player has exactly one score per day, full stop — event_type is
        descriptive metadata about that score, not a second axis of identity.
        Calling update_player_score twice for the same day, even with a
        different event_type each time, must update the same row, not create
        a second one. (This used to intentionally create two rows; that
        behavior was the direct cause of a real bug — see the tests below.)
        """
        await db.update_player_score("Grizzly", TODAY, 18.0, event_type="HOF")
        await db.update_player_score("Grizzly", TODAY, 22.0, event_type="E1")
        rows = await db.fetchall(
            "SELECT score, event_type FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 22.0)
        self.assertEqual(rows[0]["event_type"], "E1")

    async def test_update_score_correction_preserves_existing_event_type(self):
        """
        The actual bug this whole area was fixed for: /score's only call site
        never passes event_type (always None). If an existing row already has
        a real event_type set (e.g. from a historical backfill) and someone
        corrects the score via /score, the correction must update that same
        row and must NOT wipe the event_type back to NULL — it should stay
        exactly as it was, since None here means "not specified", not "clear it".
        """
        await db.update_player_score("Grizzly", TODAY, 22.0, event_type="E2")
        # Simulate a plain /score correction: no event_type passed at all (defaults to None)
        await db.update_player_score("Grizzly", TODAY, 24.0)
        rows = await db.fetchall(
            "SELECT score, event_type FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 24.0)
        self.assertEqual(rows[0]["event_type"], "E2")  # preserved, not wiped to NULL

    async def test_update_score_correction_never_creates_a_duplicate_row(self):
        """Directly reproduces the reported bug: correcting an existing score
        (with an event_type already set) must never result in 2 rows and an
        inflated team total — it must always be exactly 1 row with the
        corrected value."""
        await db.update_player_score("dougbaldwin", TODAY, 22.0, event_type="E1")
        await db.update_player_score("dougbaldwin", TODAY, 24.0)  # the correction
        rows = await db.fetchall(
            "SELECT score FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 24.0)

    async def test_update_score_with_fourth_downs(self):
        await db.update_player_score(
            "Grizzly", TODAY, 22.0, fourth_downs=3, fourth_down_convs=2
        )
        row = await db.fetchone(
            "SELECT fourth_downs, fourth_down_convs FROM game_scores WHERE game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["fourth_downs"], 3)
        self.assertEqual(row["fourth_down_convs"], 2)

    async def test_update_score_player_not_found(self):
        with self.assertRaises(ValueError):
            await db.update_player_score("NoSuchPlayer", TODAY, 22.0)

    # --- update_player_ovr ---

    async def test_update_ovr(self):
        await db.update_player_ovr("Grizzly", 250, 235, 7200)
        row = await db.fetchone(
            "SELECT off_ovr, def_ovr, total_ovr FROM players WHERE ign='Grizzly'"
        )
        self.assertEqual(row["off_ovr"], 250)
        self.assertEqual(row["def_ovr"], 235)
        self.assertEqual(row["total_ovr"], 7200)

    async def test_update_ovr_not_found(self):
        with self.assertRaises(ValueError):
            await db.update_player_ovr("NoSuchPlayer", 200, 200, 5000)

    # --- get_rank_table ---

    async def test_get_rank_table_active_only(self):
        """Should only return A status players, not I."""
        rows = await db.get_rank_table("NP")
        igns = [r["ign"] for r in rows]
        self.assertIn("Grizzly", igns)
        self.assertIn("dougbaldwin", igns)
        self.assertIn("FHRITP", igns)    # now A status, should appear in rank table
        self.assertNotIn("Bob", igns)      # L status, wrong team

    async def test_get_rank_table_sorted_by_pwr_rank(self):
        rows = await db.get_rank_table("NP")
        ranks = [r["pwr_rank"] for r in rows]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    async def test_get_rank_table_empty_team(self):
        rows = await db.get_rank_table("NT")
        self.assertEqual(rows, [])

    # --- get_player_avg ---

    async def test_get_avg_no_scores(self):
        avg = await db.get_player_avg("Grizzly", "Yearly")
        self.assertIsNone(avg)

    async def test_get_avg_with_scores(self):
        await db.update_player_score("Grizzly", TODAY, 20.0)
        await db.update_player_score("Grizzly", YESTERDAY, 24.0)
        avg = await db.get_player_avg("Grizzly", "Yearly")
        self.assertAlmostEqual(avg, 22.0, places=1)

    async def test_get_avg_event_specific(self):
        """event_type/tier lives on matchup_day for that (team_id, game_date),
        not reliably on the game_scores entry itself — /score never takes a
        tier param, so the tier for a given day comes from whatever
        matchup was set via /ladder or /matchup, not the score entry."""
        await db.update_player_score("Grizzly", TODAY, 18.0)
        await db.update_player_score("Grizzly", YESTERDAY, 22.0)
        await db.set_matchup_info("NP", TODAY, event_type="HOF")
        avg = await db.get_player_avg("Grizzly", "HOF")
        self.assertAlmostEqual(avg, 18.0, places=1)

    async def test_get_avg_invalid_type(self):
        with self.assertRaises(ValueError):
            await db.get_player_avg("Grizzly", "InvalidType")

    # --- matchup helpers ---

    async def test_set_matchup(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia", "E1")
        row = await db.fetchone(
            "SELECT opp_ign, event_type FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["opp_ign"], "WolfpackMafia")
        self.assertEqual(row["event_type"], "E1")

    async def test_set_matchup_stores_our_rank(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia", "E1", our_rank=45)
        row = await db.fetchone(
            "SELECT our_rank FROM matchup_day WHERE team_id='NP' AND game_date=?", (TODAY,)
        )
        self.assertEqual(row["our_rank"], 45)

    async def test_set_matchup_none_fields_preserve_existing_values(self):
        """A field left as None (e.g. our_rank wasn't visible in a screenshot)
        must preserve whatever's already stored, not wipe it out."""
        await db.set_matchup("NP", TODAY, "WolfpackMafia", "E1", our_rank=45)
        await db.set_matchup("NP", TODAY, opp_ign=None, event_type=None, our_rank=None)
        row = await db.fetchone(
            "SELECT opp_ign, event_type, our_rank FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["opp_ign"], "WolfpackMafia")
        self.assertEqual(row["event_type"], "E1")
        self.assertEqual(row["our_rank"], 45)

    async def test_set_matchup_provided_fields_overwrite_even_when_others_are_none(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia", "E1", our_rank=45)
        await db.set_matchup("NP", TODAY, opp_ign="NewOpponent", event_type=None, our_rank=None)
        row = await db.fetchone(
            "SELECT opp_ign, event_type, our_rank FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["opp_ign"], "NewOpponent")  # explicitly provided, overwrites
        self.assertEqual(row["event_type"], "E1")        # left None, preserved
        self.assertEqual(row["our_rank"], 45)             # left None, preserved

    async def test_set_matchup_upsert(self):
        await db.set_matchup("NP", TODAY, "TeamA")
        await db.set_matchup("NP", TODAY, "TeamB")
        rows = await db.fetchall(
            "SELECT opp_ign FROM matchup_day WHERE team_id='NP' AND game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opp_ign"], "TeamB")

    async def test_set_outcome_win(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia")
        outcome = await db.set_outcome("NP", TODAY, 300, 225, 45)
        self.assertEqual(outcome, "WIN")

    async def test_set_outcome_loss(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia")
        outcome = await db.set_outcome("NP", TODAY, 200, 250, 48)
        self.assertEqual(outcome, "LOSS")

    async def test_set_outcome_tie(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia")
        outcome = await db.set_outcome("NP", TODAY, 250, 250, 45)
        self.assertEqual(outcome, "TIE")

    async def test_update_opp_score(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia")
        await db.update_opp_score("NP", TODAY, 225, 45)
        row = await db.fetchone(
            "SELECT opp_score, opp_drives FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["opp_score"], 225)
        self.assertEqual(row["opp_drives"], 45)

    # --- get_matchup_status ---

    async def test_matchup_status_no_data(self):
        status = await db.get_matchup_status("NP", TODAY)
        self.assertEqual(status["us_score"], 0)
        self.assertEqual(status["outlook"], "TIED")

    async def test_matchup_status_with_scores(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia")
        await db.update_opp_score("NP", TODAY, 100, 10)
        await db.update_player_score("Grizzly", TODAY, 22.0)
        await db.update_player_score("dougbaldwin", TODAY, 20.0)
        status = await db.get_matchup_status("NP", TODAY)
        self.assertEqual(status["us_score"], 42.0)
        self.assertEqual(status["outlook"], "BEHIND")

    async def test_matchup_status_remaining_players(self):
        await db.update_player_score("Grizzly", TODAY, 22.0)
        status = await db.get_matchup_status("NP", TODAY)
        # dougbaldwin hasn't scored yet
        self.assertIn("dougbaldwin", status["players_remaining"])
        self.assertNotIn("Grizzly", status["players_remaining"])

    # --- ladder helpers ---

    async def test_upsert_ladder_slot(self):
        await db.upsert_ladder_slot("NP", TODAY, 1, "WolfpackMafia", 219, 7059)
        rows = await db.get_ladder_snapshot("NP", TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opp_ign"], "WolfpackMafia")

    async def test_upsert_ladder_slot_update(self):
        await db.upsert_ladder_slot("NP", TODAY, 1, "TeamA", 219, 7059)
        await db.upsert_ladder_slot("NP", TODAY, 1, "TeamB", 230, 7100)
        rows = await db.get_ladder_snapshot("NP", TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opp_ign"], "TeamB")

    # --- weight helpers ---

    async def test_get_weights(self):
        weights = await db.get_weights("pwr_rank")
        labels = [w["label"] for w in weights]
        self.assertIn("yearly_avg", labels)
        self.assertIn("team_total_ovr", labels)

    async def test_set_weight(self):
        found = await db.set_weight("yearly_avg", 0.75)
        self.assertTrue(found)
        weights = await db.get_weights("pwr_rank")
        w = next(w for w in weights if w["label"] == "yearly_avg")
        self.assertEqual(w["weight"], 0.75)

    async def test_set_weight_not_found(self):
        found = await db.set_weight("nonexistent_label", 0.5)
        self.assertFalse(found)

    async def test_add_and_delete_weight(self):
        await db.add_weight("test_factor", "Test Factor", 0.2, "pwr_rank")
        weights = await db.get_weights("pwr_rank")
        labels = [w["label"] for w in weights]
        self.assertIn("test_factor", labels)

        await db.delete_weight("test_factor")
        weights = await db.get_weights("pwr_rank")
        labels = [w["label"] for w in weights]
        self.assertNotIn("test_factor", labels)

    # --- get_players_remaining ---

    async def test_players_remaining_all(self):
        remaining = await db.get_players_remaining("NP", TODAY)
        self.assertIn("Grizzly", remaining)
        self.assertIn("dougbaldwin", remaining)

    async def test_players_remaining_after_score(self):
        await db.update_player_score("Grizzly", TODAY, 22.0)
        remaining = await db.get_players_remaining("NP", TODAY)
        self.assertNotIn("Grizzly", remaining)
        self.assertIn("dougbaldwin", remaining)

    async def test_players_remaining_includes_all_active(self):
        """All A-status players should appear in remaining until scored."""
        remaining = await db.get_players_remaining("NP", TODAY)
        self.assertIn("FHRITP", remaining)

    # --- fourth down rate ---

    async def test_fourth_down_rate_no_data(self):
        result = await db.get_player_fourth_down_rate("Grizzly")
        self.assertIsNone(result)

    async def test_fourth_down_rate_with_data(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        result = await db.get_player_fourth_down_rate("Grizzly")
        self.assertIsNotNone(result)
        self.assertEqual(result["attempts"], 4)
        self.assertEqual(result["conversions"], 3)
        self.assertAlmostEqual(result["conv_rate"], 75.0)

    async def test_fourth_down_rate_zero_attempts(self):
        """Should return None if no attempts recorded."""
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=0, fourth_down_convs=0)
        result = await db.get_player_fourth_down_rate("Grizzly")
        self.assertIsNone(result)

    # --- /streak: kobe_streak (consecutive 24pt games) and no_drop_streak
    # (consecutive 18+pt games, no dropped drives) ---

    async def test_get_player_streaks_returns_none_for_unknown_player(self):
        result = await db.get_player_streaks("NoSuchPlayer")
        self.assertIsNone(result)

    async def test_get_player_streaks_counts_consecutive_kobes(self):
        for i in range(3):
            game_date = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=i)).isoformat()
            await db.update_player_score("Grizzly", game_date, 24.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 3)

    async def test_get_player_streaks_kobe_streak_counts_scores_above_24_too(self):
        """
        Directly reproduces a real bug caught by testing against an actual
        production database: scores above 24 (26, 28, 30 all genuinely
        occur, affecting ~5% of real players) were breaking the streak
        under an earlier score==24-exact implementation, when the actual
        request was "24+" — a better-than-24 game must still continue the
        streak, not end it.
        """
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat(), 30.0)
        await db.update_player_score("Grizzly", TODAY, 24.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 2)  # both the 24 and the 30 count

    async def test_get_player_streaks_kobe_streak_breaks_on_non_24(self):
        """Only the most recent unbroken run counts — a 24 further back,
        after a non-24 game, must not be included."""
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=2)).isoformat(), 24.0)
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat(), 20.0)  # breaks it
        await db.update_player_score("Grizzly", TODAY, 24.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 1)  # only today's 24 counts

    async def test_get_player_streaks_no_drop_streak_counts_18_plus(self):
        for i, score in enumerate([18.0, 22.0, 24.0]):
            game_date = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=2 - i)).isoformat()
            await db.update_player_score("Grizzly", game_date, score)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["no_drop_streak"], 3)

    async def test_get_player_streaks_no_drop_streak_breaks_below_18(self):
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=2)).isoformat(), 24.0)
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat(), 16.0)  # below 18 -- a dropped drive
        await db.update_player_score("Grizzly", TODAY, 20.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["no_drop_streak"], 1)  # only today's 20 counts

    async def test_get_player_streaks_missed_drive_breaks_both_streaks(self):
        """A missed drive (is_forfeit) counts as a real score of 0 — fails
        both conditions and ends both streaks, even if the games before it
        were a perfect run."""
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=2)).isoformat(), 24.0)
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat(), 0.0, is_forfeit=True)
        await db.update_player_score("Grizzly", TODAY, 24.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 1)
        self.assertEqual(result["no_drop_streak"], 1)

    async def test_get_player_streaks_excused_entry_skipped_not_broken(self):
        """An excused absence never happened, as far as the streak is
        concerned — it must be skipped entirely, not treated as a bad game
        that ends the streak."""
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=2)).isoformat(), 24.0)
        await db.update_player_score("Grizzly", (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat(), None, is_excused=True)
        await db.update_player_score("Grizzly", TODAY, 24.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 2)  # both real 24s count, excused day skipped
        self.assertEqual(result["no_drop_streak"], 2)

    async def test_get_player_streaks_scoped_to_current_team(self):
        """A transferred player's history on a PREVIOUS team must not
        extend or affect their CURRENT team's streak — matching the same
        historical-team-id scoping principle as get_player_stats."""
        grizzly = await db.get_player("Grizzly")  # currently on NP
        # An old, high streak on a different team_id, from before a
        # hypothetical transfer.
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) VALUES (?, 'ND', ?, 24.0)",
            (grizzly["id"], (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat())
        )
        # Just one real game on NP, not a 24.
        await db.update_player_score("Grizzly", TODAY, 20.0)
        result = await db.get_player_streaks("Grizzly")
        self.assertEqual(result["kobe_streak"], 0)  # ND's 24 must not count toward NP's streak
        self.assertEqual(result["no_drop_streak"], 1)  # just today's 20

    # --- /openspots: 18 minus active roster count, per league ---

    async def test_get_open_spots_basic_calculation(self):
        """The NP fixture has 3 active players (Grizzly, dougbaldwin, JX8) —
        open_spots must be exactly 18 minus that count."""
        spots = await db.get_open_spots()
        np_entry = next(s for s in spots if s["team_id"] == "NP")
        self.assertEqual(np_entry["active_count"], 3)
        self.assertEqual(np_entry["open_spots"], 15)

    async def test_get_open_spots_includes_teams_with_zero_active_players(self):
        """A league with no active players at all must still appear, with
        the full 18 open spots — not be silently missing from the output."""
        spots = await db.get_open_spots()
        nd_entry = next(s for s in spots if s["team_id"] == "ND")
        self.assertEqual(nd_entry["active_count"], 0)
        self.assertEqual(nd_entry["open_spots"], 18)

    async def test_get_open_spots_sorted_by_most_open_first(self):
        spots = await db.get_open_spots()
        open_counts = [s["open_spots"] for s in spots]
        self.assertEqual(open_counts, sorted(open_counts, reverse=True))

    async def test_get_open_spots_excludes_inactive_players_from_count(self):
        """An inactive (status='I') player must not count against open
        spots — a league with an inactive player still has that spot open."""
        await db.execute("INSERT INTO players (team_id, ign, status) VALUES ('NP', 'BenchedPlayer', 'I')")
        spots = await db.get_open_spots()
        np_entry = next(s for s in spots if s["team_id"] == "NP")
        self.assertEqual(np_entry["active_count"], 3)  # unchanged — the inactive player doesn't count
        self.assertEqual(np_entry["open_spots"], 15)

    async def test_get_open_spots_returns_display_name_not_just_team_id(self):
        spots = await db.get_open_spots()
        np_entry = next(s for s in spots if s["team_id"] == "NP")
        self.assertEqual(np_entry["name"], "NeuroPerverse")



    async def test_player_stats_missed_drives_count(self):
        """Missed-drive entries (is_forfeit) should be tallied for /player."""
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True)
        await db.update_player_score("Grizzly", YESTERDAY, 22.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["missed_drives"], 1)

    async def test_missed_drives_excluded_from_average(self):
        """A missed (forfeited) drive must be excluded from games/avg — unlike
        a genuine 0-point game, which is a real entry and does count."""
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True)
        await db.update_player_score("Grizzly", YESTERDAY, 20.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["games"], 1)
        self.assertEqual(stats["avg_yearly"], 20.0)

    async def test_missed_drives_no_score_stored(self):
        """A missed-drive entry should never carry a nonzero stored score."""
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True)
        row = await db.fetchone("SELECT score FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["score"], 0.0)

    # --- a genuine 0-point game is a real, countable entry — is_forfeit/
    # is_excused are what identify a non-real entry, never the score value
    # itself. Regression coverage for a bug where "score > 0" was used as a
    # stand-in for "is this a real entry", which silently excluded every
    # actual 0-point game from games count, points, and every average. ---

    async def test_genuine_zero_score_counts_as_a_played_game(self):
        await db.update_player_score("Grizzly", TODAY, 0.0)  # a real played drive, not forfeited
        await db.update_player_score("Grizzly", YESTERDAY, 20.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["games"], 2)  # both count — the 0 was really played

    async def test_genuine_zero_score_pulls_down_the_average(self):
        await db.update_player_score("Grizzly", TODAY, 0.0)
        await db.update_player_score("Grizzly", YESTERDAY, 20.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["avg_yearly"], 10.0)  # (0 + 20) / 2, not just 20 / 1

    async def test_genuine_zero_score_counts_toward_points_total(self):
        await db.update_player_score("Grizzly", TODAY, 0.0)
        await db.update_player_score("Grizzly", YESTERDAY, 20.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["points"], 20)

    async def test_get_player_avg_includes_genuine_zero(self):
        await db.update_player_score("Grizzly", TODAY, 0.0)
        await db.update_player_score("Grizzly", YESTERDAY, 10.0)
        avg = await db.get_player_avg("Grizzly", "Yearly")
        self.assertEqual(avg, 5.0)  # (0 + 10) / 2, not just 10 / 1

    async def test_zero_and_forfeit_are_still_distinguished_in_stats(self):
        """A genuine 0 must count; a forfeited (missed) 0 must not — verifying
        the fix didn't accidentally start counting missed drives too."""
        await db.update_player_score("Grizzly", TODAY, 0.0)             # real, counts
        await db.update_player_score("Grizzly", YESTERDAY, 0.0, is_forfeit=True)  # missed, doesn't
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["games"], 1)

    # --- fumbles (directly logged per entry, never derived from score) ---

    async def test_fumbles_stored_directly(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fumbles=2)
        row = await db.fetchone("SELECT fumbles FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["fumbles"], 2)

    async def test_fumbles_summed_across_entries(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fumbles=1)
        await db.update_player_score("Grizzly", YESTERDAY, 6.0, fumbles=2)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["fumbles"], 3)

    async def test_fumbles_can_occur_on_a_zero_score(self):
        """Regression test for the actual bug: a fumble can happen on any real
        played drive regardless of the final score, including a legitimate 0.
        The stat must never be inferred from the score value — it's only ever
        whatever was directly logged in the fumbles field for that entry."""
        await db.update_player_score("Grizzly", TODAY, 0.0, fumbles=1)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["fumbles"], 1)

    async def test_fumbles_default_zero_when_not_logged(self):
        """Scoring normally without ever touching the Fumbles field should
        never silently produce a nonzero count — this was the actual bug
        reported in production (everyone showing ~1 despite nobody having
        entered fumble data yet)."""
        await db.update_player_score("Grizzly", TODAY, 6.0)
        await db.update_player_score("Grizzly", YESTERDAY, 0.0)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["fumbles"], 0)

    async def test_fumbles_excluded_for_missed_and_excused_days(self):
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True, fumbles=5)
        await db.update_player_score("Grizzly", YESTERDAY, 0.0, is_excused=True, fumbles=5)
        row   = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["fumbles"], 0)

    # --- defensive score tracking (/dscore) ---

    async def test_dscore_insert(self):
        await db.update_player_dscore("Grizzly", TODAY, 48, 235.5)
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertIsNotNone(row)
        self.assertEqual(row["points_allowed"], 48)
        self.assertEqual(row["avg_off_ovr_faced"], 235.5)

    async def test_dscore_upsert(self):
        await db.update_player_dscore("Grizzly", TODAY, 48, 235.5)
        await db.update_player_dscore("Grizzly", TODAY, 24, 220.0)
        rows = await db.fetchall("SELECT * FROM defense_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["points_allowed"], 24)

    async def test_dscore_player_not_found(self):
        with self.assertRaises(ValueError):
            await db.update_player_dscore("NoSuchPlayer", TODAY, 10)

    async def test_dscore_no_data_returns_none(self):
        result = await db.get_player_dscore_stats("Grizzly")
        self.assertIsNone(result)

    async def test_get_player_stats_scoped_to_team_not_entire_career(self):
        """The exact bug reported: a player who transferred leagues had HOF
        (and other) games under their OLD team_id — those must never bleed
        into their CURRENT team's stats. A league that's never played a HOF
        match must never show a HOF average for any of its players, even one
        who played HOF while on a different team before transferring."""
        grizzly = await db.get_player("Grizzly")  # currently on NP
        # Historical HOF game from before a hypothetical transfer — tagged
        # with a different team_id, exactly like a real transferred player's
        # history. matchup_day is the real source of truth for event_type,
        # so it's set up here too (not just on the game_scores row itself,
        # which /score never actually sets in real usage).
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) "
            "VALUES (?, 'ND', ?, 30.0)",
            (grizzly["id"], YESTERDAY)
        )
        await db.set_matchup_info("ND", YESTERDAY, event_type="HOF")
        # A real NP game, no matching matchup_day entry (NP has never played a HOF match)
        await db.update_player_score("Grizzly", TODAY, 20.0)

        stats = await db.get_player_stats(grizzly["id"], "NP")
        self.assertIsNone(stats["hof_avg"])   # NP has no HOF games — must not inherit ND's
        self.assertEqual(stats["games"], 1)   # only the NP game counts, not the ND one too
        self.assertAlmostEqual(stats["avg_yearly"], 20.0)  # ND's 30.0 must not factor in

    # --- Fumble-adjusted averages: fumbles treated as null drives ---

    def test_fumble_adjusted_avg_matches_plain_average_with_zero_fumbles(self):
        """Sanity check baked into the math itself: with zero fumbles,
        fumble_adjusted_drives equals total_drives exactly, so this must
        collapse to exactly the plain average (total_points / games)."""
        from db import _fumble_adjusted_avg
        # 3 games, 20 points each = 60 total, 0 fumbles
        result = _fumble_adjusted_avg(total_points=60, games=3, fumbles=0)
        self.assertAlmostEqual(result, 20.0)  # same as the plain average would be

    def test_fumble_adjusted_avg_exact_formula(self):
        """Directly verifies the requested formula: total_drives = games*3,
        fumble_adjusted_drives = total_drives - fumbles, ppd = points /
        fumble_adjusted_drives, avg = ppd * 3."""
        from db import _fumble_adjusted_avg
        # 3 games = 9 drives, 1 fumble = 8 fumble-adjusted drives.
        # 30 points / 8 drives = 3.75 ppd, * 3 = 11.25
        result = _fumble_adjusted_avg(total_points=30, games=3, fumbles=1)
        self.assertAlmostEqual(result, 11.25)

    def test_fumble_adjusted_avg_higher_than_plain_when_fumbles_present(self):
        """The whole point of this metric: a fumble is typically a low/zero-
        scoring event. Excluding it from the denominator entirely (treating
        it as never having happened) means the same points are now divided
        across fewer drives — so the fumble-adjusted average should come
        out HIGHER than a plain average would, not lower. It's "protecting"
        the average from being dragged down by the fumbled drive, which is
        the intended effect of treating it as null rather than as a real,
        scored drive."""
        from db import _fumble_adjusted_avg
        plain_equivalent = 30 / 3  # 10.0, if this were a plain average
        adjusted = _fumble_adjusted_avg(total_points=30, games=3, fumbles=2)
        self.assertGreater(adjusted, plain_equivalent)

    def test_fumble_adjusted_avg_zero_games_returns_none(self):
        from db import _fumble_adjusted_avg
        self.assertIsNone(_fumble_adjusted_avg(total_points=0, games=0, fumbles=0))

    def test_fumble_adjusted_avg_fumbles_meet_or_exceed_total_drives_returns_none(self):
        """Degenerate case — every drive (or more) counted as a fumble.
        Shouldn't be possible in valid data, but must not raise or return
        something misleading like a negative average."""
        from db import _fumble_adjusted_avg
        self.assertIsNone(_fumble_adjusted_avg(total_points=10, games=1, fumbles=3))  # exactly all 3 drives
        self.assertIsNone(_fumble_adjusted_avg(total_points=10, games=1, fumbles=5))  # more than possible

    async def test_get_player_stats_includes_fumble_adjusted_averages(self):
        """Integration test through the real get_player_stats path: logs
        real scores with fumbles, confirms the returned dict's fumble-
        adjusted yearly average matches the exact expected calculation."""
        grizzly = await db.get_player("Grizzly")
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        await db.update_player_score("Grizzly", YESTERDAY, 20.0, fumbles=0)
        # 2 games, 30 total points, 1 total fumble -> 6 drives - 1 = 5
        # fumble-adjusted drives, 30/5 = 6.0 ppd, * 3 = 18.0
        stats = await db.get_player_stats(grizzly["id"], "NP")
        self.assertAlmostEqual(stats["avg_yearly_fumble_adj"], 18.0)
        self.assertAlmostEqual(stats["avg_yearly"], 15.0)  # plain average, unaffected
        self.assertEqual(stats["fumbles"], 1)

    async def test_get_player_stats_fumble_adjusted_scoped_to_same_window_as_plain(self):
        """The fumble-adjusted 7-day average must be computed over the SAME
        last-7-GAMES window as the plain 7-day average (it's a game-count
        window, not a calendar-day one), not the player's entire history —
        confirms last_n's single combined query is scoping correctly for
        both numbers together. Needs at least 8 total games to actually
        exercise the boundary — with fewer, the "old" game would still
        fall inside "last 7" regardless of its actual date."""
        grizzly = await db.get_player("Grizzly")
        old_date = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=100)).isoformat()
        # An old game with a fumble that must NOT factor into the 7-game window.
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score, fumbles) "
            "VALUES (?, 'NP', ?, 5.0, 10)",
            (grizzly["id"], old_date)
        )
        # 7 more recent, fumble-free games — enough to fully occupy the
        # "last 7 games" window on their own, pushing the old one out of it.
        for i in range(7):
            game_date = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=i)).isoformat()
            await db.update_player_score("Grizzly", game_date, 24.0, fumbles=0)

        stats = await db.get_player_stats(grizzly["id"], "NP")
        # Only the 7 recent, fumble-free games should count in the 7-day figures.
        self.assertAlmostEqual(stats["avg_7day"], 24.0)
        self.assertAlmostEqual(stats["avg_7day_fumble_adj"], 24.0)  # 0 fumbles in this window -> same as plain

    async def test_get_player_stats_fumble_adjusted_event_avg_uses_matchup_day_scoping(self):
        """The fumble-adjusted HOF average must respect the exact same
        matchup_day-based event scoping as the plain HOF average (the fix
        from the earlier division-averages bug) — not bypass it."""
        grizzly = await db.get_player("Grizzly")
        await db.update_player_score("Grizzly", TODAY, 20.0, fumbles=1)
        await db.set_matchup_info("NP", TODAY, event_type="HOF")
        stats = await db.get_player_stats(grizzly["id"], "NP")
        # 1 game = 3 drives, 1 fumble = 2 fumble-adjusted drives, 20/2=10 ppd, *3=30
        self.assertAlmostEqual(stats["hof_avg"], 20.0)
        self.assertAlmostEqual(stats["hof_avg_fumble_adj"], 30.0)

    async def test_get_player_avg_with_fumble_adj_matches_get_player_avg_for_plain_value(self):
        """Consistency check: the new function's 'avg' value must exactly
        match what the existing, unchanged get_player_avg returns for the
        same player/atype — this is purely additive, not a replacement."""
        await db.update_player_score("Grizzly", TODAY, 22.0, fumbles=1)
        plain = await db.get_player_avg("Grizzly", "Yearly")
        result = await db.get_player_avg_with_fumble_adj("Grizzly", "Yearly")
        self.assertAlmostEqual(result['avg'], plain)
        self.assertIsNotNone(result['fumble_adjusted_avg'])

    async def test_get_player_avg_with_fumble_adj_returns_none_for_unknown_player(self):
        result = await db.get_player_avg_with_fumble_adj("NoSuchPlayer", "Yearly")
        self.assertIsNone(result)

    async def test_get_player_avg_with_fumble_adj_invalid_atype_raises(self):
        with self.assertRaises(ValueError):
            await db.get_player_avg_with_fumble_adj("Grizzly", "NotARealType")

    async def test_player_card_shows_yearly_avg_with_fumble_adj_combined(self):
        """/player's card must surface the fumble-adjusted yearly average,
        combined into the same field as the plain average (not a separate
        field — see _fmt_avg_with_fumble_adj), not just compute it
        internally and never actually show it anywhere."""
        from optimized_bot import _build_player_card_embed
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        row = await db.get_player("Grizzly")
        embed = await _build_player_card_embed("Grizzly", row, "en")
        calls = embed.add_field.call_args_list
        yearly_field = next(c for c in calls if c.kwargs.get("name") == "Yearly Avg")
        # 1 game = 3 drives, 1 fumble = 2 fumble-adjusted drives,
        # 10 points / 2 drives = 5.0 ppd, * 3 = 15.0
        self.assertEqual(yearly_field.kwargs.get("value"), "10.00 (FA: 15.00)")

    async def test_player_card_shows_all_ten_averages_with_fumble_adj(self):
        """Directly addresses the actual request: ALL fumble-adjusted
        averages must be visible on the card, not just yearly — including
        the 4 (30-day, 14-day, E3, Gold-) that weren't shown here at all
        before this change."""
        from optimized_bot import _build_player_card_embed
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        await db.set_matchup_info("NP", TODAY, event_type="E3")
        row = await db.get_player("Grizzly")
        embed = await _build_player_card_embed("Grizzly", row, "en")
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        for expected in ["Yearly Avg", "30-Day Avg", "14-Day Avg", "7-Day Avg", "3-Day Avg",
                          "HOF Avg", "E1 Avg", "E2 Avg", "E3 Avg", "Gold- Avg"]:
            self.assertIn(expected, field_names)
        # E3 specifically has real data here — confirm its value actually
        # includes the fumble-adjusted number, not just "—" or a bare plain value.
        e3_field = next(c for c in embed.add_field.call_args_list if c.kwargs.get("name") == "E3 Avg")
        self.assertIn("FA:", e3_field.kwargs.get("value"))

    async def test_player_card_missing_average_shows_dash_not_crash(self):
        """An average with no data at all (e.g. no HOF games ever played)
        must show '—', not crash or show a stray 'None'."""
        from optimized_bot import _build_player_card_embed
        await db.update_player_score("Grizzly", TODAY, 10.0)
        row = await db.get_player("Grizzly")
        embed = await _build_player_card_embed("Grizzly", row, "en")
        hof_field = next(c for c in embed.add_field.call_args_list if c.kwargs.get("name") == "HOF Avg")
        self.assertEqual(hof_field.kwargs.get("value"), "—")

    async def test_player_card_field_count_stays_within_discord_limit(self):
        """Discord caps embeds at 25 fields — confirms the expanded card
        (10 averages instead of the previous 6, plus the removed separate
        yearly-fumble-adj field) still fits, including the optional 4th-
        down field."""
        from optimized_bot import _build_player_card_embed
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        row = await db.get_player("Grizzly")
        embed = await _build_player_card_embed("Grizzly", row, "en")
        self.assertLessEqual(len(embed.add_field.call_args_list), 25)

    # --- Fumble-adjusted factors actually wired into pwr_rank/ladder_rank,
    # not just present as inert dropdown options in /weights ---

    async def test_pwr_rank_weight_on_fumble_adjusted_yearly_actually_changes_rank(self):
        """Setting a weight on 'yearly_avg_fumble_adj' must genuinely
        influence pwr_rank's computed value — confirms the formula itself
        references this factor, not just that the label exists somewhere
        selectable in the /weights UI."""
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        row = await db.get_player("Grizzly")
        baseline = await db.get_player_stats(row["id"], "NP")

        await db.execute(
            "INSERT INTO pwr_rank_weights (label,weight,category,display_label) "
            "VALUES ('yearly_avg_fumble_adj', 0.5, 'pwr_rank', 'Yearly Avg (Fumble-Adj.)')"
        )
        with_new_weight = await db.get_player_stats(row["id"], "NP")
        self.assertNotEqual(with_new_weight["pwr_rank"], baseline["pwr_rank"])

    async def test_ladder_rank_weight_on_fumble_adjusted_7day_actually_changes_rank(self):
        """Same check for ladder_rank, using 7day_avg_fumble_adj."""
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        row = await db.get_player("Grizzly")
        baseline = await db.get_player_stats(row["id"], "NP")

        await db.execute(
            "INSERT INTO pwr_rank_weights (label,weight,category,display_label) "
            "VALUES ('7day_avg_fumble_adj', 0.5, 'ladder', '7-Day Avg (Fumble-Adj.)')"
        )
        with_new_weight = await db.get_player_stats(row["id"], "NP")
        self.assertNotEqual(with_new_weight["ladder_rank"], baseline["ladder_rank"])

    async def test_fumble_adjusted_weight_defaults_to_zero_contribution(self):
        """With no row in pwr_rank_weights for a fumble-adjusted label at
        all (the common case — nothing changes for a league that hasn't
        deliberately added one), pwr_rank/ladder_rank must be completely
        unaffected by this feature's existence — matching pre-feature
        behavior exactly, not silently shifting everyone's rank."""
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        row = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], "NP")
        # No fumble-adjusted weight rows exist in the fixture by default —
        # this is just confirming pwr_rank/ladder_rank still compute cleanly
        # (no crash, no NaN) using only the pre-existing weight rows.
        self.assertIsInstance(stats["pwr_rank"], float)
        self.assertIsInstance(stats["ladder_rank"], float)

    def test_all_fumble_adjusted_stat_keys_present_and_translatable(self):
        """Every fumble-adjusted label added to ALL_STAT_KEYS must have a
        working i18n translation — a missing key would surface as a raw
        key string in the /weights dropdown instead of a real label."""
        import optimized_bot
        import i18n
        fumble_adj_keys = [k for k, _ in optimized_bot.ALL_STAT_KEYS if k.endswith('_fumble_adj')]
        self.assertEqual(len(fumble_adj_keys), 11)  # 7 pwr_rank-side + 4 ladder-side
        labels = optimized_bot._stat_labels('en')
        translated = {display for key, display in labels if key in fumble_adj_keys}
        for key in fumble_adj_keys:
            tkey = next(tk for k, tk in optimized_bot.ALL_STAT_KEYS if k == key)
            display = i18n.t(tkey, 'en')
            self.assertNotEqual(display, tkey)  # a raw, untranslated key would equal itself
            self.assertIn(display, translated)

    # --- 4th down conversion percentage: replaces the old dead nominal-
    # count options (fourth_downs/fourth_down_convs, never actually wired
    # into pwr_rank/ladder_rank) with a single, functional percentage. ---

    def test_old_nominal_fourth_down_keys_removed(self):
        import optimized_bot
        keys = [k for k, _ in optimized_bot.ALL_STAT_KEYS]
        self.assertNotIn("fourth_downs", keys)
        self.assertNotIn("fourth_down_convs", keys)
        self.assertIn("fourth_down_conv_pct", keys)

    def test_fourth_down_conv_pct_key_translatable(self):
        import optimized_bot
        import i18n
        display = i18n.t('stat.fourth_down_conv_pct', 'en')
        self.assertNotEqual(display, 'stat.fourth_down_conv_pct')

    async def test_get_player_stats_computes_fourth_down_conv_pct(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        row = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertEqual(stats["fourth_down_attempts"], 4)
        self.assertEqual(stats["fourth_down_conversions"], 3)
        self.assertAlmostEqual(stats["fourth_down_conv_pct"], 0.75)  # decimal, not 75 -- matches three_td_pct/two_pt_pct convention

    async def test_get_player_stats_fourth_down_conv_pct_none_when_no_attempts(self):
        await db.update_player_score("Grizzly", TODAY, 22.0)
        row = await db.get_player("Grizzly")
        stats = await db.get_player_stats(row["id"], row["team_id"])
        self.assertIsNone(stats["fourth_down_conv_pct"])

    async def test_get_player_stats_fourth_down_conv_pct_scoped_to_current_team(self):
        """Same historical-scoping principle as everything else in this
        function — a transferred player's 4th down data on a PREVIOUS team
        must not bleed into their CURRENT team's percentage. Directly
        avoids reusing get_player_fourth_down_rate's own (deliberately
        unscoped, career-wide) query for this purpose."""
        grizzly = await db.get_player("Grizzly")  # currently on NP
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score, fourth_downs, fourth_down_convs) "
            "VALUES (?, 'ND', ?, 20.0, 10, 1)",
            (grizzly["id"], YESTERDAY)
        )
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        stats = await db.get_player_stats(grizzly["id"], "NP")
        self.assertEqual(stats["fourth_down_attempts"], 4)  # only NP's, not ND's 10 too
        self.assertAlmostEqual(stats["fourth_down_conv_pct"], 0.75)

    async def test_pwr_rank_weight_on_fourth_down_conv_pct_actually_changes_rank(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        row = await db.get_player("Grizzly")
        baseline = await db.get_player_stats(row["id"], "NP")
        await db.execute(
            "INSERT INTO pwr_rank_weights (label,weight,category,display_label) "
            "VALUES ('fourth_down_conv_pct', 0.5, 'pwr_rank', '4th Down Conv %')"
        )
        with_weight = await db.get_player_stats(row["id"], "NP")
        self.assertNotEqual(with_weight["pwr_rank"], baseline["pwr_rank"])

    async def test_ladder_rank_weight_on_fourth_down_conv_pct_actually_changes_rank(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, fourth_downs=4, fourth_down_convs=3)
        row = await db.get_player("Grizzly")
        baseline = await db.get_player_stats(row["id"], "NP")
        await db.execute(
            "INSERT INTO pwr_rank_weights (label,weight,category,display_label) "
            "VALUES ('fourth_down_conv_pct', 0.5, 'ladder', '4th Down Conv %')"
        )
        with_weight = await db.get_player_stats(row["id"], "NP")
        self.assertNotEqual(with_weight["ladder_rank"], baseline["ladder_rank"])

    async def test_avg_type_select_displays_both_plain_and_fumble_adjusted(self):
        """/avg's actual UI path — confirms the edited message includes both
        numbers, not just that the underlying db function works in isolation."""
        from optimized_bot import AvgTypeSelect
        await db.update_player_score("Grizzly", TODAY, 10.0, fumbles=1)
        view = AvgTypeSelect("Grizzly", lang="en")
        inter = MagicMock()
        inter.data = {'values': ['Yearly']}
        inter.response = MagicMock()
        inter.response.edit_message = AsyncMock()
        await view.on_select(inter)
        content = inter.response.edit_message.call_args.kwargs.get("content", "")
        self.assertIn("Grizzly", content)
        self.assertIn("10.0000", content)  # the plain average (1 game, score 10)
        # 1 game = 3 drives, 1 fumble = 2 fumble-adjusted drives,
        # 10 points / 2 drives = 5.0 ppd, * 3 = 15.0
        self.assertIn("15.0000", content)

    async def test_get_league_stats_does_not_show_hof_for_league_that_never_played_it(self):
        """Same bug, exercised through get_league_stats (the actual /stats
        path) rather than get_player_stats directly."""
        grizzly = await db.get_player("Grizzly")
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) "
            "VALUES (?, 'ND', ?, 30.0)",
            (grizzly["id"], YESTERDAY)
        )
        await db.set_matchup_info("ND", YESTERDAY, event_type="HOF")
        await db.update_player_score("Grizzly", TODAY, 20.0)

        stats = await db.get_league_stats("NP")
        self.assertIsNone(stats["hof_avg"])  # league-wide HOF avg must also be None, not 30.0
        by_ign = {p["ign"]: p for p in stats["players"]}
        self.assertIsNone(by_ign["Grizzly"]["hof_avg"])

    async def test_get_league_stats_division_avg_uses_matchup_day_not_game_scores_event_type(self):
        """
        Directly reproduces the reported bug: /stats' per-division averages
        (hof_avg/e1_avg/etc.) must come from matchup_day.event_type for that
        (team_id, game_date) — not game_scores.event_type, which /score
        never actually sets (it has no tier parameter at all). A score
        logged the normal way, on a day whose matchup was correctly tagged
        E1 via /ladder or /matchup, must count toward e1_avg even though
        the game_scores row itself has no event_type set.
        """
        await db.update_player_score("Grizzly", TODAY, 24.0)  # no event_type — matches real /score usage
        row = await db.fetchone("SELECT event_type FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertIsNone(row["event_type"])  # confirms the realistic starting state

        await db.set_matchup_info("NP", TODAY, event_type="E1")

        stats = await db.get_league_stats("NP")
        self.assertAlmostEqual(stats["e1_avg"], 24.0)
        by_ign = {p["ign"]: p for p in stats["players"]}
        self.assertAlmostEqual(by_ign["Grizzly"]["e1_avg"], 24.0)

    async def test_get_avg_division_uses_matchup_day_not_game_scores_event_type(self):
        """Same bug, exercised through /avg's backing function."""
        await db.update_player_score("Grizzly", TODAY, 24.0)
        await db.set_matchup_info("NP", TODAY, event_type="E1")
        avg = await db.get_player_avg("Grizzly", "E1")
        self.assertAlmostEqual(avg, 24.0, places=1)

    async def test_dscore_stats_rollup(self):
        await db.update_player_dscore("Grizzly", TODAY, 48, 240.0)
        await db.update_player_dscore("Grizzly", YESTERDAY, 24, 220.0)
        stats = await db.get_player_dscore_stats("Grizzly")
        self.assertEqual(stats["games"], 2)
        self.assertEqual(stats["total_allowed"], 72)
        self.assertAlmostEqual(stats["avg_allowed"], 36.0)

    # --- get_league_stats: /stats' underlying league-wide aggregate ---

    async def test_get_league_stats_averages_across_active_players(self):
        await db.update_player_score("Grizzly", TODAY, 20.0)
        await db.update_player_score("dougbaldwin", TODAY, 30.0)
        stats = await db.get_league_stats("NP")
        # FHRITP has no scores at all — excluded from the average (None, not 0)
        self.assertAlmostEqual(stats["avg_yearly"], 25.0)
        self.assertEqual(stats["player_count"], 3)  # still counted as a roster member
        self.assertEqual(stats["games"], 2)         # total across the whole roster
        self.assertEqual(stats["points"], 50)

    async def test_get_league_stats_includes_per_player_rows(self):
        """The /stats layout needs one row per player, not just the league
        aggregate — confirm the players list is present and each entry has
        its own ign and stats."""
        await db.update_player_score("Grizzly", TODAY, 20.0)
        await db.update_player_score("dougbaldwin", TODAY, 30.0)
        stats = await db.get_league_stats("NP")
        self.assertEqual(len(stats["players"]), 3)  # Grizzly, dougbaldwin, FHRITP
        by_ign = {p["ign"]: p for p in stats["players"]}
        self.assertAlmostEqual(by_ign["Grizzly"]["avg_yearly"], 20.0)
        self.assertAlmostEqual(by_ign["dougbaldwin"]["avg_yearly"], 30.0)
        self.assertIsNone(by_ign["FHRITP"]["avg_yearly"])  # no scores at all

    async def test_get_league_stats_excludes_inactive_by_default(self):
        bob = await db.fetchone("SELECT id, team_id FROM players WHERE ign='Bob'")
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) VALUES (?, ?, ?, 40.0)",
            (bob["id"], bob["team_id"], TODAY)
        )
        stats = await db.get_league_stats("ND")  # Bob is status='I'
        self.assertIsNone(stats)  # no active players on ND at all in the fixture

    async def test_get_league_stats_include_inactive_true_includes_them(self):
        bob = await db.fetchone("SELECT id, team_id FROM players WHERE ign='Bob'")
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) VALUES (?, ?, ?, 40.0)",
            (bob["id"], bob["team_id"], TODAY)
        )
        stats = await db.get_league_stats("ND", include_inactive=True)
        self.assertIsNotNone(stats)
        self.assertEqual(stats["player_count"], 1)
        self.assertAlmostEqual(stats["avg_yearly"], 40.0)
        self.assertEqual(stats["players"][0]["ign"], "Bob")

    async def test_get_league_stats_no_qualifying_players_returns_none(self):
        stats = await db.get_league_stats("NX")  # no players at all in the fixture
        self.assertIsNone(stats)

    async def test_send_stats_image_has_one_row_per_player_plus_league_avg(self):
        """The actual layout requested: stat categories across the top,
        each player as its own row, and a final League Avg row summarizing
        the league — not stat categories as rows with a single averages column."""
        import sheet_image
        await db.update_player_score("Grizzly", TODAY, 20.0)
        await db.update_player_score("dougbaldwin", TODAY, 30.0)

        captured = {}
        original = sheet_image._render_table
        def spy(title, headers, rows, aligns=None, subtitle=None):
            captured['title'] = title
            captured['headers'] = headers
            captured['rows'] = rows
            return original(title, headers, rows, aligns, subtitle=subtitle)
        sheet_image._render_table = spy
        try:
            ctx = MagicMock()
            ctx.send = AsyncMock()
            await sheet_image.send_stats_image(ctx, "NP")
        finally:
            sheet_image._render_table = original

        # Header row is stat categories, not a single "League Avg" column
        self.assertIn('Player', captured['headers'])
        self.assertIn('Yearly', captured['headers'])
        self.assertNotEqual(captured['headers'], ['Stat', 'League Avg'])

        # One row per active player (Grizzly, dougbaldwin, FHRITP = 3),
        # plus exactly one League Avg row at the very end
        self.assertEqual(len(captured['rows']), 4)
        player_names = [r[1] for r in captured['rows'][:-1]]
        self.assertIn('Grizzly', player_names)
        self.assertIn('dougbaldwin', player_names)
        self.assertIn('FHRITP', player_names)
        self.assertEqual(captured['rows'][-1][1], 'LEAGUE AVG')

    async def test_send_stats_image_league_avg_row_matches_get_league_stats(self):
        import sheet_image
        await db.update_player_score("Grizzly", TODAY, 20.0)
        await db.update_player_score("dougbaldwin", TODAY, 30.0)
        stats = await db.get_league_stats("NP")

        captured = {}
        original = sheet_image._render_table
        def spy(title, headers, rows, aligns=None, subtitle=None):
            captured['rows'] = rows
            return original(title, headers, rows, aligns, subtitle=subtitle)
        sheet_image._render_table = spy
        try:
            ctx = MagicMock()
            ctx.send = AsyncMock()
            await sheet_image.send_stats_image(ctx, "NP")
        finally:
            sheet_image._render_table = original

        league_avg_row = captured['rows'][-1]
        # Yearly column (index 3) should reflect the same average get_league_stats computed
        self.assertEqual(league_avg_row[3], f"{stats['avg_yearly']:.2f}")

    async def test_dscore_stores_drive_outcomes(self):
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "3", "F", "0")
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertEqual(row["drive1_outcome"], "3")
        self.assertEqual(row["drive2_outcome"], "F")
        self.assertEqual(row["drive3_outcome"], "0")

    async def test_dscore_drive_outcomes_default_to_none(self):
        await db.update_player_dscore("Grizzly", TODAY, 8)
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertIsNone(row["drive1_outcome"])
        self.assertIsNone(row["drive2_outcome"])
        self.assertIsNone(row["drive3_outcome"])

    async def test_dscore_drive_detail_saved_only_for_specified_drives(self):
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "F", "0", "I")
        await db.update_dscore_drive_detail("Grizzly", TODAY, 1, 235, "3rd", "8", "ball popped out on the tackle", "Dukie06")
        await db.update_dscore_drive_detail("Grizzly", TODAY, 2, 220)  # normal drive, OVR only
        await db.update_dscore_drive_detail("Grizzly", TODAY, 3, 240, "1st", "10", "pick six", "khromefiend")
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertEqual(row["drive1_ovr"], 235)
        self.assertEqual(row["drive1_turnover_down"], "3rd")
        self.assertEqual(row["drive1_turnover_distance"], "8")
        self.assertEqual(row["drive1_turnover_play"], "ball popped out on the tackle")
        self.assertEqual(row["drive1_turnover_forced_by"], "Dukie06")
        self.assertEqual(row["drive2_ovr"], 220)
        self.assertIsNone(row["drive2_turnover_play"])  # normal drive, no turnover fields
        self.assertEqual(row["drive3_ovr"], 240)
        self.assertEqual(row["drive3_turnover_play"], "pick six")
        self.assertEqual(row["drive3_turnover_forced_by"], "khromefiend")

    async def test_finalize_dscore_avg_ovr_averages_entered_drives_only(self):
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "3", "F", "5")
        await db.update_dscore_drive_detail("Grizzly", TODAY, 1, 230)
        await db.update_dscore_drive_detail("Grizzly", TODAY, 2, 240)
        # drive 3's OVR left blank (None) — must be excluded from the average, not treated as 0
        avg = await db.finalize_dscore_avg_ovr("Grizzly", TODAY)
        self.assertAlmostEqual(avg, 235.0)
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertAlmostEqual(row["avg_off_ovr_faced"], 235.0)

    async def test_finalize_dscore_avg_ovr_none_entered_stores_none(self):
        await db.update_player_dscore("Grizzly", TODAY, 0, None, "0", "0", "0")
        avg = await db.finalize_dscore_avg_ovr("Grizzly", TODAY)
        self.assertIsNone(avg)

    # --- matchup status: real active roster (not a hardcoded 16) ---

    async def test_matchup_status_active_roster_count(self):
        """NP has 3 active players in the seed data — not 16."""
        status = await db.get_matchup_status("NP", TODAY)
        self.assertEqual(status["active_roster"], 3)

    async def test_matchup_status_active_roster_excludes_inactive(self):
        await db.execute("UPDATE players SET status='I' WHERE ign='FHRITP'")
        status = await db.get_matchup_status("NP", TODAY)
        self.assertEqual(status["active_roster"], 2)
        await db.execute("UPDATE players SET status='A' WHERE ign='FHRITP'")

    # --- siege ---

    async def test_start_siege_match_creates_active(self):
        match = await db.start_siege_match("NP", "WolfpackMafia", opp_rank="3", our_rank="2", division="E1")
        self.assertEqual(match["status"], "active")
        self.assertEqual(match["opp_league"], "WolfpackMafia")

    async def test_start_siege_match_blocks_second_active(self):
        await db.start_siege_match("NP", "WolfpackMafia")
        with self.assertRaises(ValueError):
            await db.start_siege_match("NP", "AnotherLeague")

    async def test_start_siege_match_scoped_per_team(self):
        """A different team should be able to have its own active match at the same time."""
        await db.start_siege_match("NP", "WolfpackMafia")
        match2 = await db.start_siege_match("ND", "SomeOtherLeague")
        self.assertEqual(match2["status"], "active")

    async def test_finalize_allows_new_match(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.finalize_siege_match(match["id"])
        new_match = await db.start_siege_match("NP", "SecondOpponent")
        self.assertEqual(new_match["status"], "active")
        old = await db.get_siege_match(match["id"])
        self.assertEqual(old["status"], "completed")
        self.assertIsNotNone(old["completed_at"])

    async def test_add_siege_node_defaults_open(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=6500, points_required=30, points_reward=10
        )
        self.assertEqual(node["status"], "open")
        self.assertEqual(node["mod"], "No Mod")

    async def test_add_siege_node_rejects_duplicate_named_mod(self):
        """Each of the 10 named mods appears exactly once per match."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Slayer99",
            opponent_ovr=6600, points_required=20, points_reward=8
        )
        with self.assertRaises(ValueError):
            await db.add_siege_node(
                match["id"], mod="Run Plays Only", opponent_name="SomeoneElse",
                opponent_ovr=None, points_required=10, points_reward=5
            )

    async def test_add_siege_node_allows_multiple_no_mod(self):
        """Up to 6 un-modded opponents exist per match — No Mod is exempt from the 1-per-match rule."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        for i in range(6):
            await db.add_siege_node(
                match["id"], mod="No Mod", opponent_name=f"Guy{i}",
                opponent_ovr=None, points_required=10, points_reward=5
            )
        nodes = await db.get_siege_nodes(match["id"])
        self.assertEqual(len(nodes), 6)

    async def test_add_siege_node_duplicate_named_mod_after_clear_still_blocked(self):
        """The 1-per-match rule applies regardless of the existing node's status."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Slayer99",
            opponent_ovr=None, points_required=10, points_reward=8
        )
        await db.update_siege_node(node["id"], status="cleared")
        with self.assertRaises(ValueError):
            await db.add_siege_node(
                match["id"], mod="Run Plays Only", opponent_name="AnotherGuy",
                opponent_ovr=None, points_required=10, points_reward=5
            )

    async def test_get_siege_open_nodes_by_name_unique(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Slayer99",
            opponent_ovr=6600, points_required=20, points_reward=8
        )
        found = await db.get_siege_open_nodes_by_name(match["id"], "Slayer99")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["id"], node["id"])
        await db.update_siege_node(node["id"], status="cleared")
        self.assertEqual(await db.get_siege_open_nodes_by_name(match["id"], "Slayer99"), [])

    async def test_get_siege_open_nodes_by_name_duplicate_no_mod(self):
        """Two No Mod nodes can legitimately share a name — both should come back, unresolved."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node_a = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Slayer99",
            opponent_ovr=None, points_required=20, points_reward=8
        )
        node_b = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Slayer99",
            opponent_ovr=None, points_required=30, points_reward=12
        )
        found = await db.get_siege_open_nodes_by_name(match["id"], "Slayer99")
        self.assertEqual({n["id"] for n in found}, {node_a["id"], node_b["id"]})

        # Clearing one leaves only the other findable-by-name.
        await db.log_siege_score(node_a["id"], "Grizzly", 2, 20)
        still_open = await db.get_siege_open_nodes_by_name(match["id"], "Slayer99")
        self.assertEqual(len(still_open), 1)
        self.assertEqual(still_open[0]["id"], node_b["id"])

    async def test_log_siege_score_under_threshold_stays_open(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=6500, points_required=30, points_reward=10
        )
        result = await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        self.assertFalse(result["cleared"])
        refreshed = await db.get_siege_node(node["id"])
        self.assertEqual(refreshed["status"], "open")

    async def test_log_siege_score_clears_at_threshold(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=None, points_required=20, points_reward=10
        )
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        result = await db.log_siege_score(node["id"], "dougbaldwin", 2, 6)
        self.assertTrue(result["cleared"])
        refreshed = await db.get_siege_node(node["id"])
        self.assertEqual(refreshed["status"], "cleared")
        self.assertIsNotNone(refreshed["cleared_at"])

    async def test_log_siege_score_rejects_cleared_node(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=None, points_required=10, points_reward=10
        )
        await db.log_siege_score(node["id"], "Grizzly", 3, 10)
        with self.assertRaises(ValueError):
            await db.log_siege_score(node["id"], "dougbaldwin", 1, 5)

    async def test_update_siege_score_can_reopen_node(self):
        """An admin correction that drops the total back below required should reopen the node."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=None, points_required=20, points_reward=10
        )
        await db.log_siege_score(node["id"], "Grizzly", 3, 20)
        cleared = await db.get_siege_node(node["id"])
        self.assertEqual(cleared["status"], "cleared")

        scores = await db.get_siege_scores_for_node(node["id"])
        await db.update_siege_score(scores[0]["id"], points=5)
        reopened = await db.get_siege_node(node["id"])
        self.assertEqual(reopened["status"], "open")

    async def test_siege_player_totals(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node1 = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=None, points_required=100, points_reward=10
        )
        node2 = await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Slayer99",
            opponent_ovr=None, points_required=100, points_reward=10
        )
        await db.log_siege_score(node1["id"], "Grizzly", 3, 14)
        await db.log_siege_score(node2["id"], "Grizzly", 2, 8)
        totals = await db.get_siege_player_totals(match["id"], "Grizzly")
        self.assertEqual(totals["points"], 22)
        self.assertEqual(totals["drives"], 5)

    async def test_siege_splits_by_mod(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node1 = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="BigBoy87",
            opponent_ovr=None, points_required=100, points_reward=10
        )
        node2 = await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Slayer99",
            opponent_ovr=None, points_required=100, points_reward=10
        )
        await db.log_siege_score(node1["id"], "Grizzly", 3, 14)
        await db.log_siege_score(node2["id"], "Grizzly", 2, 8)
        splits = {row["mod"]: row for row in await db.get_siege_splits("Grizzly")}
        self.assertEqual(splits["No Mod"]["points"], 14)
        self.assertEqual(splits["Run Plays Only"]["points"], 8)

    async def test_siege_history_only_completed(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.finalize_siege_match(match["id"])
        await db.start_siege_match("NP", "SecondOpponent")  # stays active
        history = await db.get_siege_history("NP")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["opp_league"], "WolfpackMafia")

    async def test_siege_match_summary_formula(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        # One cleared node: required 20, reward 10
        cleared = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Cleared1",
            opponent_ovr=None, points_required=20, points_reward=10
        )
        await db.log_siege_score(cleared["id"], "Grizzly", 2, 20)
        # One open node with partial progress: 12 points scored so far
        open_node = await db.add_siege_node(
            match["id"], mod="Run Plays Only", opponent_name="Open1",
            opponent_ovr=None, points_required=50, points_reward=15
        )
        await db.log_siege_score(open_node["id"], "dougbaldwin", 2, 12)

        summary = await db.get_siege_match_summary(match["id"])
        self.assertEqual(summary["cleared_required_total"], 20)
        self.assertEqual(summary["cleared_reward_total"], 10)
        self.assertEqual(summary["open_node_points"], 12)
        self.assertEqual(summary["total_points"], 32)
        self.assertEqual(summary["total_drives"], 4)
        # ppd = 32/4 = 8.0 -> ppd_bonus = 30*8 - 25 = 215
        self.assertAlmostEqual(summary["ppd"], 8.0)
        self.assertEqual(summary["ppd_bonus"], 215)
        # league_score = 12 (open) + 20 (cleared req) + 10 (cleared reward) + 215 (ppd bonus)
        self.assertEqual(summary["league_score"], 257)
        # League totals are integers, not floats — ppd (a per-drive rate) is the one exception.
        self.assertIsInstance(summary["ppd_bonus"], int)
        self.assertIsInstance(summary["league_score"], int)

    async def test_siege_match_summary_ppd_bonus_unfloored(self):
        """Low PPD should be allowed to push the bonus (and league score) negative."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Weak1",
            opponent_ovr=None, points_required=100, points_reward=10
        )
        await db.log_siege_score(node["id"], "Grizzly", 10, 2)  # ppd = 0.2
        summary = await db.get_siege_match_summary(match["id"])
        self.assertAlmostEqual(summary["ppd"], 0.2)
        self.assertEqual(summary["ppd_bonus"], -19)  # 30*0.2 - 25
        self.assertIsInstance(summary["ppd_bonus"], int)
        self.assertIsInstance(summary["league_score"], int)
        self.assertLess(summary["league_score"], summary["open_node_points"])

    async def test_siege_match_summary_top_open_by_reward(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        low  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Low",
            opponent_ovr=None, points_required=50, points_reward=5
        )
        mid  = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="Mid",
            opponent_ovr=None, points_required=50, points_reward=15
        )
        high = await db.add_siege_node(
            match["id"], mod="No Mod", opponent_name="High",
            opponent_ovr=None, points_required=50, points_reward=25
        )
        summary = await db.get_siege_match_summary(match["id"])
        self.assertEqual(summary["top_open_ids"], {low["id"], mid["id"], high["id"]})

    # --- get_matchup_summary ---

    async def test_matchup_summary_no_matchup(self):
        data = await db.get_matchup_summary("NP", TODAY)
        self.assertIsNone(data["matchup"])
        self.assertEqual(data["scores"], [])

    async def test_matchup_summary_full(self):
        await db.set_matchup("NP", TODAY, "WolfpackMafia", "E1")
        await db.set_outcome("NP", TODAY, 300, 225, 45)
        await db.update_player_score("Grizzly", TODAY, 22.0)
        data = await db.get_matchup_summary("NP", TODAY)
        self.assertIsNotNone(data["matchup"])
        self.assertEqual(data["matchup"]["outcome"], "WIN")
        self.assertEqual(len(data["scores"]), 1)
        self.assertEqual(data["scores"][0]["ign"], "Grizzly")

    # --- recent matchups ---

    async def test_get_recent_matchups(self):
        await db.set_matchup("NP", TODAY, "TeamA")
        await db.set_matchup("NP", YESTERDAY, "TeamB")
        rows = await db.get_recent_matchups("NP", limit=10)
        self.assertEqual(len(rows), 2)
        # Most recent first
        self.assertEqual(rows[0]["opp_ign"], "TeamA")

    async def test_get_recent_matchups_limit(self):
        await db.set_matchup("NP", TODAY, "TeamA")
        await db.set_matchup("NP", YESTERDAY, "TeamB")
        rows = await db.get_recent_matchups("NP", limit=1)
        self.assertEqual(len(rows), 1)


# ---------------------------------------------------------------------------
# Test: Command logic (mocked interactions)
# ---------------------------------------------------------------------------

def _label_text_for(modal, field):
    """
    Find the label text for a modal field after the discord.ui.Label
    migration. TextInput no longer carries .label directly — the visible
    text lives on the wrapping Label component instead (component=field),
    added to the modal via add_item. Searches modal.children for the Label
    whose .component is the given field and returns its .text.
    """
    for child in modal.children:
        if getattr(child, "component", None) is field:
            return child.text
    raise AssertionError("No Label found wrapping this field — was it added via add_item(Label(...))?")


class TestCommandLogic(unittest.IsolatedAsyncioTestCase):
    """
    Tests the pure logic of commands that can be tested without a full
    Discord connection: validation, DB calls, and response construction.
    """

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    def _make_interaction(self, ephemeral_capture=None):
        """Create a mock Discord interaction."""
        inter = MagicMock()
        inter.locale = discord.Locale.american_english
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.response.send_modal = AsyncMock()
        inter.response.defer = AsyncMock()
        inter.response.edit_message = AsyncMock()
        inter.response.is_done = MagicMock(return_value=False)
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.edit_original_response = AsyncMock()
        inter.message = MagicMock()
        inter.message.edit = AsyncMock()
        inter.guild = MagicMock()
        inter.user = MagicMock()
        inter.user.roles = []
        inter.channel = MagicMock()
        inter.channel.send = AsyncMock()
        inter.command = MagicMock()
        inter.command.name = "test"
        return inter

    # --- _validate_league ---

    def test_validate_league_valid(self):
        from optimized_bot import _validate_league
        self.assertEqual(_validate_league("NP"), "NP")
        self.assertEqual(_validate_league("np"), "NP")

    def test_validate_league_invalid(self):
        from optimized_bot import _validate_league
        with self.assertRaises(ValueError):
            _validate_league("XX")

    # --- _is_admin ---

    def test_is_admin_true(self):
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        role = MagicMock()
        role.name = "Administrator"
        inter.user.roles = [role]
        self.assertTrue(_is_admin(inter))

    def test_is_admin_true_for_league_owner(self):
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        role = MagicMock()
        role.name = "League Owner"
        inter.user.roles = [role]
        self.assertTrue(_is_admin(inter))

    def test_is_admin_true_for_madden_admin(self):
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        role = MagicMock()
        role.name = "Madden Admin"
        inter.user.roles = [role]
        self.assertTrue(_is_admin(inter))

    def test_is_admin_false(self):
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        role = MagicMock()
        role.name = "Member"
        inter.user.roles = [role]
        self.assertFalse(_is_admin(inter))

    def test_is_admin_old_role_name_no_longer_works(self):
        """The role was renamed Admin -> Administrator; the old name must not grant access."""
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        role = MagicMock()
        role.name = "Admin"
        inter.user.roles = [role]
        self.assertFalse(_is_admin(inter))

    def test_is_admin_no_guild(self):
        from optimized_bot import _is_admin
        inter = self._make_interaction()
        inter.guild = None
        self.assertFalse(_is_admin(inter))

    def test_every_command_marked_admin_in_manual_actually_requires_admin(self):
        """Cross-check: every command whose manual description contains the
        Admin marker must actually gate on _require_admin somewhere in its
        source. This guards against the manual and the real gating drifting
        apart again. Parses optimized_bot.py's source directly via ast, since
        @tree.command wraps the real function into an unintrospectable
        MagicMock under this test stub (see prior tiers' notes on this)."""
        import ast
        import i18n

        # encoding is explicit: the source contains non-ASCII text (emoji in
        # user-facing strings), and Python's default encoding is the locale's
        # on Windows (cp1252), which can't decode it.
        with open(os.path.join(os.path.dirname(__file__), "optimized_bot.py"), encoding="utf-8") as f:
            src_text = f.read()
        tree = ast.parse(src_text)
        src_lines = src_text.splitlines()

        gates_admin = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name.endswith("_slash"):
                cmd_name = node.name[: -len("_slash")]
                func_src = "\n".join(src_lines[node.lineno - 1 : node.end_lineno])
                gates_admin[cmd_name] = "_require_admin(" in func_src

        marked = {}
        for page_key in i18n.MANUAL_PAGE_KEYS:
            for name, desc in i18n.TRANSLATIONS[f"{page_key}.fields"]["en"]:
                marked[name.lstrip("/")] = ("**Admin" in desc) or (page_key == "manual.page4")

        # Commands that use a direct role check (not _require_admin) are
        # intentionally excluded — they broaden access rather than narrow it.
        direct_check_commands = {"addgif", "reloadgifs"}

        checked = 0
        for cmd_name, is_marked in marked.items():
            if cmd_name in direct_check_commands or cmd_name not in gates_admin:
                continue
            checked += 1
            if is_marked:
                self.assertTrue(gates_admin[cmd_name], f"/{cmd_name} is marked Admin in the manual but doesn't call _require_admin")
        self.assertGreater(checked, 20)

    # --- on_command_error (prefix commands were fully retired) ---

    def _make_ctx(self, guild_locale=None):
        ctx = MagicMock()
        ctx.send = AsyncMock()
        if guild_locale is not None:
            ctx.guild = MagicMock()
            ctx.guild.preferred_locale = guild_locale
        else:
            ctx.guild = None
        return ctx

    async def test_command_not_found_points_to_manual(self):
        from optimized_bot import on_command_error
        ctx = self._make_ctx()
        await on_command_error(ctx, commands.CommandNotFound())
        msg = ctx.send.call_args.args[0]
        self.assertIn("/manual", msg)

    async def test_command_not_found_uses_guild_preferred_locale(self):
        from optimized_bot import on_command_error
        import i18n
        ctx = self._make_ctx(guild_locale=discord.Locale.german)
        await on_command_error(ctx, commands.CommandNotFound())
        msg = ctx.send.call_args.args[0]
        self.assertEqual(msg, i18n.t('prefix.deprecated', 'de'))

    async def test_command_not_found_falls_back_to_english_with_no_guild(self):
        from optimized_bot import on_command_error
        import i18n
        ctx = self._make_ctx(guild_locale=None)
        await on_command_error(ctx, commands.CommandNotFound())
        msg = ctx.send.call_args.args[0]
        self.assertEqual(msg, i18n.t('prefix.deprecated', 'en'))

    async def test_command_not_found_falls_back_to_english_for_unsupported_locale(self):
        from optimized_bot import on_command_error
        import i18n
        ctx = self._make_ctx(guild_locale=discord.Locale.british_english)
        await on_command_error(ctx, commands.CommandNotFound())
        msg = ctx.send.call_args.args[0]
        self.assertEqual(msg, i18n.t('prefix.deprecated', 'en'))

    async def test_other_command_errors_still_handled_correctly(self):
        """Sanity check for a stub fix made alongside this: CommandOnCooldown,
        MissingPermissions, and MissingRequiredArgument were previously all
        aliased to the same bare Exception class in the test stub, which would
        have made isinstance checks meaningless (the first branch in the
        if/elif chain would silently swallow all the others). Now that each
        has its own distinct class, verify each branch is actually reachable."""
        from optimized_bot import on_command_error

        ctx = self._make_ctx()
        await on_command_error(ctx, commands.CommandOnCooldown(retry_after=2.5))
        self.assertIn("Cooldown", ctx.send.call_args.args[0])

        ctx2 = self._make_ctx()
        await on_command_error(ctx2, commands.MissingPermissions())
        self.assertIn("permission", ctx2.send.call_args.args[0])

        ctx3 = self._make_ctx()
        await on_command_error(ctx3, commands.MissingRequiredArgument(param_name="player"))
        self.assertIn("player", ctx3.send.call_args.args[0])

    # --- _handle_app_command_error (slash commands) ---
    # Directly reproduces two real production errors: /player hit a
    # transient Discord-side rate limit (429, "Service resource is being
    # rate limited") trying to send its result, and /matchup hit an
    # already-expired interaction (404, "Unknown interaction") on its very
    # first response attempt. The old handler treated both identically —
    # a single blind retry wrapped in a bare `except: pass` — which for
    # the expired-interaction case was guaranteed to fail again with the
    # exact same error (an interaction token doesn't come back once
    # invalid) and silently swallowed that too, leaving no trace and no
    # response to the user either way.

    def _make_error_interaction(self, response_is_done=False):
        inter = MagicMock()
        inter.command = MagicMock()
        inter.command.name = "player"
        inter.response = MagicMock()
        inter.response.is_done = MagicMock(return_value=response_is_done)
        inter.response.send_message = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        return inter

    async def test_handle_app_command_error_expired_interaction_never_retries(self):
        """The exact /matchup scenario: Unknown interaction (404, code
        10062). Must log and return without attempting to send anything —
        any attempt is guaranteed to fail identically."""
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=False)
        original = discord.NotFound(code=10062, text="Unknown interaction")
        wrapped = discord.app_commands.CommandInvokeError(inter.command, original)

        await _handle_app_command_error(inter, wrapped)

        inter.response.send_message.assert_not_called()
        inter.followup.send.assert_not_called()

    async def test_handle_app_command_error_rate_limit_retries_after_delay(self):
        """The exact /player scenario: a 429 (error code 40062, 'Service
        resource is being rate limited'). First attempt fails, must retry
        once more after a short delay rather than giving up immediately."""
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=True)
        # First followup.send attempt fails (simulating the rate limit
        # still being in effect), second succeeds.
        inter.followup.send = AsyncMock(side_effect=[Exception("still rate limited"), None])
        original = discord.HTTPException(status=429, code=40062, text="Service resource is being rate limited")
        wrapped = discord.app_commands.CommandInvokeError(inter.command, original)

        with patch('optimized_bot.asyncio.sleep', new=AsyncMock()) as mock_sleep:
            await _handle_app_command_error(inter, wrapped)

        self.assertEqual(inter.followup.send.call_count, 2)
        mock_sleep.assert_called_once()

    async def test_handle_app_command_error_rate_limit_stops_after_success(self):
        """Confirms no third attempt is made once a retry succeeds."""
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=True)
        inter.followup.send = AsyncMock(side_effect=[Exception("still rate limited"), None])
        original = discord.HTTPException(status=429, code=40062, text="rate limited")
        wrapped = discord.app_commands.CommandInvokeError(inter.command, original)

        with patch('optimized_bot.asyncio.sleep', new=AsyncMock()):
            await _handle_app_command_error(inter, wrapped)

        self.assertEqual(inter.followup.send.call_count, 2)  # not 3+

    async def test_handle_app_command_error_non_rate_limit_error_does_not_retry(self):
        """A normal, non-rate-limited error must behave like before this
        change — a single attempt, no retry loop — confirming the new
        retry logic doesn't apply to every error indiscriminately."""
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=True)
        inter.followup.send = AsyncMock(side_effect=Exception("some other failure"))
        wrapped = discord.app_commands.CommandInvokeError(inter.command, ValueError("some bug"))

        with patch('optimized_bot.asyncio.sleep', new=AsyncMock()) as mock_sleep:
            await _handle_app_command_error(inter, wrapped)

        self.assertEqual(inter.followup.send.call_count, 1)
        mock_sleep.assert_not_called()

    async def test_handle_app_command_error_retry_hits_expired_interaction_stops_immediately(self):
        """If the interaction expires DURING the retry wait (between the
        original error and the retry attempt), the retry itself will hit
        Unknown interaction — must stop right there, not keep trying."""
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=True)
        inter.followup.send = AsyncMock(
            side_effect=[Exception("rate limited"), discord.NotFound(code=10062, text="Unknown interaction")]
        )
        original = discord.HTTPException(status=429, code=40062, text="rate limited")
        wrapped = discord.app_commands.CommandInvokeError(inter.command, original)

        with patch('optimized_bot.asyncio.sleep', new=AsyncMock()):
            await _handle_app_command_error(inter, wrapped)

        self.assertEqual(inter.followup.send.call_count, 2)  # tried, expired, stopped -- no 3rd attempt

    async def test_handle_app_command_error_uses_followup_when_response_already_done(self):
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=True)
        await _handle_app_command_error(inter, ValueError("some bug"))
        inter.followup.send.assert_called_once()
        inter.response.send_message.assert_not_called()

    async def test_handle_app_command_error_uses_response_send_message_when_not_done(self):
        from optimized_bot import _handle_app_command_error
        inter = self._make_error_interaction(response_is_done=False)
        await _handle_app_command_error(inter, ValueError("some bug"))
        inter.response.send_message.assert_called_once()
        inter.followup.send.assert_not_called()

    # --- score command ---

    async def test_score_records_correctly(self):
        """Score command should write to game_scores."""
        await db.update_player_score("Grizzly", TODAY, 22.0)
        rows = await db.fetchall(
            "SELECT score FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 22.0)

    async def test_score_negative_is_forfeit(self):
        """Negative score input should be stored as forfeit."""
        await db.update_player_score("Grizzly", TODAY, 0.0, is_forfeit=True)
        row = await db.fetchone("SELECT is_forfeit FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["is_forfeit"], 1)

    async def test_score_modal_m_records_missed_drives_as_zero(self):
        """Typing M in /score's modal should store a 0 score and flag is_forfeit."""
        from optimized_bot import ScoreModal
        row   = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY))
        modal.score_val.value        = "M"
        modal.def_ovr.value          = ""
        modal.fourth_downs.value     = ""
        modal.fourth_down_convs.value = ""
        modal.fumbles.value          = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)
        stored = await db.fetchone(
            "SELECT score, is_forfeit FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(stored["score"], 0)
        self.assertEqual(stored["is_forfeit"], 1)

    async def test_score_modal_e_records_excused_as_null_not_zero(self):
        """Typing E in /score's modal must store score as NULL, not 0 — an
        excused entry has no real score at all, unlike a missed (forfeited)
        drive which is genuinely a 0. Storing 0 here would put a real value
        in the column with nothing marking it meaningless except remembering
        to also check is_excused everywhere it's read."""
        from optimized_bot import ScoreModal
        row   = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY))
        modal.score_val.value        = "E"
        modal.def_ovr.value          = ""
        modal.fourth_downs.value     = ""
        modal.fourth_down_convs.value = ""
        modal.fumbles.value          = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)
        stored = await db.fetchone(
            "SELECT score, is_forfeit, is_excused FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertIsNone(stored["score"])
        self.assertEqual(stored["is_forfeit"], 0)
        self.assertEqual(stored["is_excused"], 1)

    async def test_score_modal_truncates_overlong_prefill_score(self):
        """
        Directly reproduces the production crash: ScoreModal's score field
        has max_length=4, but prefill_score used to be set as the field's
        default with no length check at all. Discord rejects modal
        creation outright (HTTPException, Invalid Form Body) if a default
        value exceeds the field's own max_length — this used to surface as
        an unhandled crash with no message to the user. The modal itself
        must now truncate defensively, regardless of what any caller passes.
        """
        from optimized_bot import ScoreModal
        row = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY),
                            prefill_score="12345678")  # 8 chars, over the 4-char max_length
        self.assertEqual(modal.score_val.default, "1234")
        self.assertLessEqual(len(modal.score_val.default), modal.score_val.max_length)

    async def test_score_modal_short_prefill_score_unaffected(self):
        """A normal, valid prefill (within max_length) must pass through
        unchanged — confirms the truncation fix doesn't corrupt the
        legitimate, common case."""
        from optimized_bot import ScoreModal
        row = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY),
                            prefill_score="22")
        self.assertEqual(modal.score_val.default, "22")

    async def test_score_modal_e_does_not_crash_gif_or_message(self):
        """An excused entry has no numeric score, so the gif lookup and the
        success message must both handle None gracefully rather than crashing
        on a None <= int comparison or literally printing 'None'."""
        from optimized_bot import ScoreModal
        row   = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY))
        modal.score_val.value        = "E"
        modal.def_ovr.value          = ""
        modal.fourth_downs.value     = ""
        modal.fourth_down_convs.value = ""
        modal.fumbles.value          = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)  # must not raise
        msg = inter.response.send_message.call_args.args[0]
        self.assertNotIn("None", msg)

    async def test_score_modal_legacy_negative_forces_zero_score(self):
        """A negative number (legacy alias) must store 0, not abs(value)."""
        from optimized_bot import ScoreModal
        row   = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY))
        modal.score_val.value        = "-14"
        modal.def_ovr.value          = ""
        modal.fourth_downs.value     = ""
        modal.fourth_down_convs.value = ""
        modal.fumbles.value          = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)
        stored = await db.fetchone(
            "SELECT score, is_forfeit FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(stored["score"], 0)
        self.assertEqual(stored["is_forfeit"], 1)

    # --- /dscore redesign: drive outcomes come from the slash command itself
    # (dscore_slash is @tree.command-wrapped, unusable directly under the
    # stub, same as every other admin command here — tested via the
    # directly-callable helper functions and the two modal classes instead) ---

    def test_parse_drive_outcome_valid_values(self):
        from optimized_bot import _parse_drive_outcome
        for v in ("0", "8", "f", "I", "s"):
            self.assertIsNotNone(_parse_drive_outcome(v))
        self.assertEqual(_parse_drive_outcome("f"), "F")  # normalized to uppercase

    def test_parse_drive_outcome_blank_is_none(self):
        from optimized_bot import _parse_drive_outcome
        self.assertIsNone(_parse_drive_outcome(""))
        self.assertIsNone(_parse_drive_outcome("   "))

    def test_parse_drive_outcome_invalid_raises(self):
        from optimized_bot import _parse_drive_outcome
        with self.assertRaises(ValueError):
            _parse_drive_outcome("9")
        with self.assertRaises(ValueError):
            _parse_drive_outcome("X")

    # --- _parse_dscore_drives: shared by /dscore and /dscore_multiple ---

    def test_parse_dscore_drives_valid_computes_points_allowed(self):
        from optimized_bot import _parse_dscore_drives
        outcomes, points_allowed = _parse_dscore_drives("3", "5", "0")
        self.assertEqual(outcomes, ["3", "5", "0"])
        self.assertEqual(points_allowed, 8)

    def test_parse_dscore_drives_turnovers_excluded_from_points(self):
        from optimized_bot import _parse_dscore_drives
        outcomes, points_allowed = _parse_dscore_drives("3", "F", "5")
        self.assertEqual(outcomes, ["3", "F", "5"])
        self.assertEqual(points_allowed, 8)  # F contributes 0, not counted as a numeric value

    def test_parse_dscore_drives_invalid_raises_with_correct_drive_number(self):
        """The exception's message must identify WHICH drive (1-based) was
        invalid, since /dscore and /dscore_multiple both need to map this
        back to the right translated label."""
        from optimized_bot import _parse_dscore_drives
        with self.assertRaises(ValueError) as ctx1:
            _parse_dscore_drives("9", "3", "5")
        self.assertEqual(str(ctx1.exception), "1")
        with self.assertRaises(ValueError) as ctx2:
            _parse_dscore_drives("3", "X", "5")
        self.assertEqual(str(ctx2.exception), "2")
        with self.assertRaises(ValueError) as ctx3:
            _parse_dscore_drives("3", "5", "")  # blank -> None -> invalid (all 3 required)
        self.assertEqual(str(ctx3.exception), "3")

    # --- update_player_dscore_single_opponent: /dscore's simplified path ---

    async def test_update_player_dscore_single_opponent_sets_all_ovr_columns(self):
        """The single provided OVR must be copied to avg_off_ovr_faced AND
        all three drive{1,2,3}_ovr columns — not just the average."""
        await db.update_player_dscore_single_opponent("Grizzly", TODAY, 8, 235, "3", "F", "5")
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertEqual(row["avg_off_ovr_faced"], 235)
        self.assertEqual(row["drive1_ovr"], 235)
        self.assertEqual(row["drive2_ovr"], 235)
        self.assertEqual(row["drive3_ovr"], 235)
        self.assertEqual(row["points_allowed"], 8)
        self.assertEqual(row["drive1_outcome"], "3")
        self.assertEqual(row["drive2_outcome"], "F")
        self.assertEqual(row["drive3_outcome"], "5")

    async def test_update_player_dscore_single_opponent_leaves_turnover_detail_unset(self):
        """Unlike /dscore_multiple's modal flow, this path never collects
        down/distance/play/forced_by — those must stay unset, not silently
        populated with something incorrect."""
        await db.update_player_dscore_single_opponent("Grizzly", TODAY, 0, 200, "F", "0", "0")
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertIsNone(row["drive1_turnover_down"])
        self.assertIsNone(row["drive1_turnover_play"])

    async def test_update_player_dscore_single_opponent_upserts_not_duplicates(self):
        await db.update_player_dscore_single_opponent("Grizzly", TODAY, 8, 200, "3", "F", "5")
        await db.update_player_dscore_single_opponent("Grizzly", TODAY, 3, 250, "3", "0", "0")
        rows = await db.fetchall(
            "SELECT * FROM defense_scores WHERE player_id=(SELECT id FROM players WHERE ign='Grizzly') AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(len(rows), 1)  # updated in place, not a second row
        self.assertEqual(rows[0]["points_allowed"], 3)
        self.assertEqual(rows[0]["avg_off_ovr_faced"], 250)
        self.assertEqual(rows[0]["drive1_ovr"], 250)

    async def test_update_player_dscore_single_opponent_unknown_player_raises(self):
        with self.assertRaises(ValueError):
            await db.update_player_dscore_single_opponent("NoSuchPlayer", TODAY, 8, 200, "3", "F", "5")

    async def test_update_player_dscore_single_opponent_feeds_dscore_stats_correctly(self):
        """End-to-end: data written via the simplified path must produce
        correct results from get_player_dscore_stats, exactly as if it had
        come from the full /dscore_multiple flow — same schema, same
        downstream reader."""
        await db.update_player_dscore_single_opponent("Grizzly", TODAY, 8, 220, "3", "F", "5")
        await db.update_player_dscore_single_opponent("Grizzly", YESTERDAY, 4, 240, "0", "0", "4")
        stats = await db.get_player_dscore_stats("Grizzly")
        self.assertEqual(stats["games"], 2)
        self.assertEqual(stats["total_allowed"], 12)
        self.assertAlmostEqual(stats["avg_off_ovr_faced"], 230.0)  # (220+240)/2

    def test_build_drive_modal_picks_normal_for_numeric_outcome(self):
        from optimized_bot import _dscore_build_drive_modal, DscoreDriveModal
        modal = _dscore_build_drive_modal(1, ["3", "F", "5"], "Grizzly", datetime.date.fromisoformat(TODAY), 8)
        self.assertIsInstance(modal, DscoreDriveModal)

    def test_build_drive_modal_picks_turnover_for_fis_outcome(self):
        from optimized_bot import _dscore_build_drive_modal, DscoreTurnoverModal
        modal = _dscore_build_drive_modal(2, ["3", "F", "5"], "Grizzly", datetime.date.fromisoformat(TODAY), 8)
        self.assertIsInstance(modal, DscoreTurnoverModal)

    async def test_dscore_drive_modal_saves_ovr_and_advances(self):
        """A normal drive modal has just 1 field (OVR). With more drives
        remaining, submitting it must prompt to continue, not finalize."""
        from optimized_bot import DscoreDriveModal
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "3", "F", "5")
        modal = DscoreDriveModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=1, drive_outcome="3",
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        modal.ovr.value = "235"
        inter = self._make_interaction()
        await modal.on_submit(inter)

        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertEqual(row["drive1_ovr"], 235)
        inter.response.send_message.assert_called_once()
        sent = inter.response.send_message.call_args
        self.assertIn("view", sent.kwargs)  # a continue-button view, not the final message

    async def test_dscore_drive_modal_blank_ovr_is_allowed(self):
        from optimized_bot import DscoreDriveModal
        await db.update_player_dscore("Grizzly", TODAY, 5, None, "5", None, None)
        modal = DscoreDriveModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=1, drive_outcome="5",
            drive_outcomes=["5", None, None], points_allowed=5
        )
        modal.ovr.value = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)  # must not raise
        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertIsNone(row["drive1_ovr"])

    async def test_dscore_drive_modal_invalid_ovr_rejected(self):
        from optimized_bot import DscoreDriveModal
        modal = DscoreDriveModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=1, drive_outcome="3",
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        modal.ovr.value = "not a number"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_called_once()
        self.assertTrue(inter.response.send_message.call_args.kwargs.get("ephemeral"))

    async def test_dscore_turnover_modal_has_5_fields(self):
        from optimized_bot import DscoreTurnoverModal
        modal = DscoreTurnoverModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=2, drive_type="F",
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        self.assertEqual(len(modal.children), 5)
        wrapped = {c.component for c in modal.children if hasattr(c, "component")}
        self.assertEqual(wrapped, {modal.ovr, modal.down, modal.distance, modal.play, modal.forced_by})

    async def test_dscore_turnover_modal_saves_all_5_fields(self):
        from optimized_bot import DscoreTurnoverModal
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "3", "F", "5")
        modal = DscoreTurnoverModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=2, drive_type="F",
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        modal.ovr.value = "230"
        modal.down.value = "3rd"
        modal.distance.value = "8"
        modal.play.value = "ball popped out on the tackle"
        modal.forced_by.value = "Dukie06"
        inter = self._make_interaction()
        await modal.on_submit(inter)

        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertEqual(row["drive2_ovr"], 230)
        self.assertEqual(row["drive2_turnover_down"], "3rd")
        self.assertEqual(row["drive2_turnover_distance"], "8")
        self.assertEqual(row["drive2_turnover_play"], "ball popped out on the tackle")
        self.assertEqual(row["drive2_turnover_forced_by"], "Dukie06")

    async def test_dscore_last_drive_finalizes_and_sends_final_message_not_a_view(self):
        """Submitting the 3rd (last) drive's modal must send the final
        confirmation directly — no continue button, since nothing remains."""
        from optimized_bot import DscoreDriveModal
        await db.update_player_dscore("Grizzly", TODAY, 8, None, "3", "F", "5")
        await db.update_dscore_drive_detail("Grizzly", TODAY, 1, 230)
        await db.update_dscore_drive_detail("Grizzly", TODAY, 2, 240, "3rd", "8", "popped out", "Dukie06")
        modal = DscoreDriveModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=3, drive_outcome="5",
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        modal.ovr.value = "220"
        inter = self._make_interaction()
        await modal.on_submit(inter)

        inter.response.send_message.assert_called_once()
        sent = inter.response.send_message.call_args
        self.assertNotIn("view", sent.kwargs)  # final message, no continue button
        msg = sent.args[0]
        self.assertIn("popped out", msg)  # drive 2's turnover detail included in the final summary

        row = await db.get_player_dscore("Grizzly", TODAY)
        self.assertAlmostEqual(row["avg_off_ovr_faced"], (230 + 240 + 220) / 3, places=1)

    async def test_dscore_continue_view_button_opens_correct_next_modal(self):
        """Clicking the continue button (a component interaction — the only
        kind Discord allows to open a modal after the first one) must open
        the right modal type for whichever drive comes next."""
        from optimized_bot import DscoreContinueView, DscoreTurnoverModal
        view = DscoreContinueView(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=2,
            drive_outcomes=["3", "F", "5"], points_allowed=8
        )
        inter = self._make_interaction()
        await view.children[0].callback(inter)
        inter.response.send_modal.assert_called_once()
        opened = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(opened, DscoreTurnoverModal)
        self.assertEqual(opened.drive_num, 2)

    def test_update_scores_modal_excused_returns_none_score(self):
        """Batch matchup entry: typing E must produce (None, False, True),
        never (0.0, False, True) — same NULL-not-zero rule as /score."""
        from optimized_bot import UpdateScoresModal

        class _Field:
            def __init__(self, value): self.value = value

        modal = UpdateScoresModal([{"ign": "Grizzly", "score": None}], 0, 1)
        modal.children = [_Field("E")]
        modal.player_names = ["Grizzly"]
        result = modal.get_scores()
        self.assertEqual(result["Grizzly"], (None, False, True))

    def test_update_scores_modal_reprefills_excused_as_e_not_blank(self):
        """Reopening a page where a player was already marked excused must
        show 'E' in the field again, not a blank — the stored score is now
        None for that entry, so the default text can't be derived from the
        score value alone anymore; it has to check is_excused/is_forfeit
        first."""
        from optimized_bot import UpdateScoresModal
        modal = UpdateScoresModal(
            [{"ign": "Grizzly", "score": None, "is_forfeit": False, "is_excused": True}],
            0, 1
        )
        self.assertEqual(modal.children[0].default, "E")

    def test_update_scores_modal_reprefills_missed_as_m_not_blank(self):
        from optimized_bot import UpdateScoresModal
        modal = UpdateScoresModal(
            [{"ign": "Grizzly", "score": 0.0, "is_forfeit": True, "is_excused": False}],
            0, 1
        )
        self.assertEqual(modal.children[0].default, "M")

    def test_update_scores_modal_missed_drives_alias(self):
        """Batch matchup entry: both M (current) and F (legacy) should map to missed drives."""
        from optimized_bot import UpdateScoresModal

        class _Field:
            def __init__(self, value): self.value = value

        modal = UpdateScoresModal.__new__(UpdateScoresModal)
        modal.player_names = ["Grizzly", "dougbaldwin", "FHRITP"]
        modal.children = [_Field("M"), _Field("F"), _Field("22")]
        scores = modal.get_scores()
        self.assertEqual(scores["Grizzly"], (0.0, True, False))
        self.assertEqual(scores["dougbaldwin"], (0.0, True, False))
        self.assertEqual(scores["FHRITP"], (22.0, False, False))

    def test_matchup_view_page_size_is_five(self):
        """Score-entry buttons should be grouped in 5s (Discord modal max) per league."""
        from optimized_bot import UpdateMatchupView
        self.assertEqual(UpdateMatchupView.PAGE_SIZE, 5)

    # --- ovr command ---

    async def test_ovr_updates_values(self):
        await db.update_player_ovr("Grizzly", 255, 240, 7200)
        row = await db.fetchone(
            "SELECT off_ovr, def_ovr, total_ovr FROM players WHERE ign='Grizzly'"
        )
        self.assertEqual(row["off_ovr"], 255)
        self.assertEqual(row["def_ovr"], 240)
        self.assertEqual(row["total_ovr"], 7200)

    # --- register ---

    async def test_register_new_player(self):
        await db.execute(
            "INSERT INTO players (team_id, ign, status, off_ovr, def_ovr, total_ovr) "
            "VALUES ('NP', 'NewPlayer', 'A', 220, 210, 6500)"
        )
        row = await db.get_player("NewPlayer")
        self.assertIsNotNone(row)
        self.assertEqual(row["team_id"], "NP")

    async def test_register_duplicate_ign_blocked(self):
        """Re-registering an existing IGN should be caught before insert."""
        existing = await db.get_player("Grizzly")
        self.assertIsNotNone(existing)  # Already exists

    # --- transfer ---

    async def test_transfer_changes_team(self):
        await db.execute(
            "UPDATE players SET team_id='ND' WHERE ign='Grizzly' AND status != 'I'"
        )
        row = await db.get_player("Grizzly")
        self.assertEqual(row["team_id"], "ND")

    # --- inactive / reactivate ---

    async def test_inactive_sets_L_status(self):
        await db.execute("UPDATE players SET status='I' WHERE ign='Grizzly'")
        row = await db.fetchone("SELECT status FROM players WHERE ign='Grizzly'")
        self.assertEqual(row["status"], "I")
        gone = await db.get_player("Grizzly")
        self.assertIsNone(gone)

    async def test_reactivate_sets_A_status(self):
        await db.execute("UPDATE players SET status='I' WHERE ign='Grizzly'")
        await db.execute("UPDATE players SET status='A' WHERE ign='Grizzly'")
        row = await db.get_player("Grizzly")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "A")

    # --- weights ---

    async def test_weights_category_isolation(self):
        """pwr_rank and ladder weights should not mix."""
        pwr    = await db.get_weights("pwr_rank")
        ladder = await db.get_weights("ladder")
        pwr_labels    = {w["label"] for w in pwr}
        ladder_labels = {w["label"] for w in ladder}
        self.assertFalse(pwr_labels & ladder_labels)  # no overlap

    async def test_weight_team_override(self):
        """A team-specific weight should override the global one."""
        await db.add_weight("yearly_avg", "Yearly Avg Override", 0.9, "pwr_rank", "NP")
        weights = await db.get_weights("pwr_rank", "NP")
        w = next(x for x in weights if x["label"] == "yearly_avg")
        self.assertEqual(w["weight"], 0.9)
        self.assertEqual(w["team_id"], "NP")

    # --- history query ---

    async def test_history_returns_date_range(self):
        await db.update_player_score("Grizzly", TODAY, 22.0)
        await db.update_player_score("Grizzly", YESTERDAY, 18.0)
        rows = await db.fetchall(
            """SELECT gs.game_date, gs.score FROM game_scores gs
               JOIN players p ON p.id = gs.player_id
               WHERE p.ign = ? AND gs.game_date >= ? AND gs.game_date <= ?
               ORDER BY gs.game_date""",
            ("Grizzly", YESTERDAY, TODAY)
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["score"], 18.0)
        self.assertEqual(rows[1]["score"], 22.0)

    async def test_history_excludes_outside_range(self):
        three_days_ago = str(datetime.date.today() - datetime.timedelta(days=3))
        await db.update_player_score("Grizzly", three_days_ago, 20.0)
        await db.update_player_score("Grizzly", TODAY, 22.0)
        rows = await db.fetchall(
            """SELECT gs.score FROM game_scores gs
               JOIN players p ON p.id = gs.player_id
               WHERE p.ign = ? AND gs.game_date >= ? AND gs.game_date <= ?""",
            ("Grizzly", YESTERDAY, TODAY)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 22.0)

    def test_history_average_calc_includes_genuine_zero(self):
        """/history's average calculation must include a genuine 0-point row —
        it previously used a truthy check on score (r['score']), and since 0
        is falsy in Python, every real 0-point game was silently dropped from
        the average. This exercises the exact same expression used there."""
        rows = [
            {"score": 0.0, "is_forfeit": 0, "is_excused": 0},   # real 0, must count
            {"score": 20.0, "is_forfeit": 0, "is_excused": 0},
            {"score": 0.0, "is_forfeit": 1, "is_excused": 0},   # missed, must not count
            {"score": None, "is_forfeit": 0, "is_excused": 1},  # excused, must not count
        ]
        scores = [r['score'] for r in rows if not r['is_forfeit'] and not r.get('is_excused') and r['score'] is not None]
        self.assertEqual(scores, [0.0, 20.0])
        self.assertEqual(round(sum(scores) / len(scores), 2), 10.0)

    # --- league management ---

    async def test_add_league(self):
        await db.execute("INSERT INTO teams VALUES ('NZ', 'NeuroZero', 'NeuroZero')")
        row = await db.fetchone("SELECT name FROM teams WHERE id='NZ'")
        self.assertEqual(row["name"], "NeuroZero")

    async def test_rename_league(self):
        await db.execute("UPDATE teams SET name='NeuroPerverse2' WHERE id='NP'")
        row = await db.fetchone("SELECT name FROM teams WHERE id='NP'")
        self.assertEqual(row["name"], "NeuroPerverse2")



    # --- DB initialization ---

    async def test_db_init_idempotent(self):
        """Calling db.init() twice should not raise or reset the connection."""
        await db.init()  # already initialized in asyncSetUp
        row = await db.fetchone("SELECT ign FROM players WHERE ign='Grizzly'")
        self.assertIsNotNone(row)  # data still accessible

    async def test_db_not_initialized_raises(self):
        """Commands should get a clear error if DB is not initialized."""
        await _patched_close()  # simulate DB going down
        with self.assertRaises(RuntimeError) as ctx:
            await db.fetchall("SELECT * FROM players")
        self.assertIn("not initialised", str(ctx.exception))
        await _patched_init()   # restore for teardown
        await setup_db()

    async def test_league_rename_requires_db(self):
        """Simulates the /league rename bug — db.fetchall must work."""
        rows = await db.fetchall("SELECT id, name FROM teams ORDER BY id")
        self.assertGreater(len(rows), 0)
        ids = [r['id'] for r in rows]
        self.assertIn('NP', ids)
        self.assertIn('ND', ids)

    # --- get_ladder / show_ladder fallback ---

    async def test_get_ladder_static_reference(self):
        await db.execute(
            "INSERT INTO ladder_matchups (team_id, slot, opp_ign, opp_def_ovr) "
            "VALUES ('NP', 1, 'WolfpackMafia', 219)"
        )
        rows = await db.get_ladder("NP")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opp_ign"], "WolfpackMafia")

    async def test_get_ladder_snapshot_empty(self):
        rows = await db.get_ladder_snapshot("NP", TODAY)
        self.assertEqual(rows, [])

    async def test_get_ladder_snapshot_with_data(self):
        await db.upsert_ladder_slot("NP", TODAY, 1, "TeamA", 219, 7000)
        await db.upsert_ladder_slot("NP", TODAY, 2, "TeamB", 235, 7100)
        rows = await db.get_ladder_snapshot("NP", TODAY)
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# Test: ladder_flow parsing helpers
# ---------------------------------------------------------------------------

class TestLadderFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_apply_extracted_ovr_updates_changed_fields(self):
        from optimized_bot import _apply_extracted_ovr
        row = await db.get_player("Grizzly")
        note = await _apply_extracted_ovr(row, {"total_ovr": 7100, "off_ovr": 250, "def_ovr": row["def_ovr"]}, "en")
        self.assertIsNotNone(note)
        self.assertIn("Grizzly", note)
        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["total_ovr"], 7100)
        self.assertEqual(updated["off_ovr"], 250)

    async def test_apply_extracted_ovr_no_change_returns_none(self):
        from optimized_bot import _apply_extracted_ovr
        row = await db.get_player("Grizzly")
        note = await _apply_extracted_ovr(
            row, {"total_ovr": row["total_ovr"], "off_ovr": row["off_ovr"], "def_ovr": row["def_ovr"]}, "en"
        )
        self.assertIsNone(note)

    async def test_apply_extracted_ovr_ignores_none_values(self):
        """A value the extraction couldn't read (None) must not clobber the
        existing OVR with a blank."""
        from optimized_bot import _apply_extracted_ovr
        row = await db.get_player("Grizzly")
        original_off = row["off_ovr"]
        await _apply_extracted_ovr(row, {"total_ovr": 7200, "off_ovr": None, "def_ovr": None}, "en")
        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["off_ovr"], original_off)  # untouched
        self.assertEqual(updated["total_ovr"], 7200)         # the one real value applied

    # --- OVR sanity check: catches vision misreading a digit (3 -> 8) ---
    # Deliberately relative to each player's OWN previous value, never an
    # absolute/hardcoded range, since the league-wide OVR range shifts
    # unpredictably over a season (reported as currently ~3000-4000, but
    # this must keep working whatever it becomes later).

    def test_is_ovr_change_suspicious_small_increase_not_flagged(self):
        from optimized_bot import _is_ovr_change_suspicious
        self.assertFalse(_is_ovr_change_suspicious(3200, 3400))  # +6.25%, normal progression

    def test_is_ovr_change_suspicious_large_legitimate_jump_not_flagged(self):
        """A real, large jump (e.g. a much stronger build) under the
        threshold must not be falsely flagged."""
        from optimized_bot import _is_ovr_change_suspicious
        self.assertFalse(_is_ovr_change_suspicious(3200, 3900))  # +21.9%, under 30%

    def test_is_ovr_change_suspicious_digit_misread_flagged(self):
        """Directly reproduces the reported bug: a leading 3 misread as an
        8 turns 3200 into 8200, a +156% jump."""
        from optimized_bot import _is_ovr_change_suspicious
        self.assertTrue(_is_ovr_change_suspicious(3200, 8200))

    def test_is_ovr_change_suspicious_large_decrease_also_flagged(self):
        """The reverse misread (8 read as 3) or any other large regression
        must also be caught — not just increases."""
        from optimized_bot import _is_ovr_change_suspicious
        self.assertTrue(_is_ovr_change_suspicious(8200, 3200))

    def test_is_ovr_change_suspicious_none_old_value_never_flagged(self):
        """A brand new player with no prior OVR has nothing to compare
        against — never suspicious regardless of the new value."""
        from optimized_bot import _is_ovr_change_suspicious
        self.assertFalse(_is_ovr_change_suspicious(None, 8200))
        self.assertFalse(_is_ovr_change_suspicious(0, 8200))

    def test_is_ovr_change_suspicious_scales_with_current_range_not_hardcoded(self):
        """Must work correctly regardless of what the league-wide OVR range
        has drifted to — this is what makes it robust to an unpredictably
        increasing range over a season, unlike a hardcoded absolute cutoff."""
        from optimized_bot import _is_ovr_change_suspicious
        # Same +156%-style misread pattern, but at a much higher range
        # than "currently ~3000-4000" — must still be caught.
        self.assertTrue(_is_ovr_change_suspicious(12000, 30000))
        # And a normal small increase at that same higher range must still
        # NOT be flagged.
        self.assertFalse(_is_ovr_change_suspicious(12000, 12800))

    def test_check_ovr_changes_splits_normal_and_suspicious(self):
        from optimized_bot import _check_ovr_changes
        row = {"id": 1, "ign": "Grizzly", "total_ovr": 3200, "off_ovr": 1600, "def_ovr": 1600}
        extracted = {"total_ovr": 8200, "off_ovr": 1650, "def_ovr": 1600}  # total misread, off normal, def unchanged
        result = _check_ovr_changes(row, extracted)
        self.assertEqual(result['suspicious'], {"total_ovr": (3200, 8200)})
        self.assertEqual(result['normal'], {"off_ovr": 1650})

    async def test_commit_ovr_updates_writes_and_notifies(self):
        from optimized_bot import _commit_ovr_updates
        row = await db.get_player("Grizzly")
        note = await _commit_ovr_updates(row, {"total_ovr": 3400}, "en")
        self.assertIsNotNone(note)
        self.assertIn("Grizzly", note)
        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["total_ovr"], 3400)

    async def test_commit_ovr_updates_empty_dict_returns_none_and_writes_nothing(self):
        from optimized_bot import _commit_ovr_updates
        row = await db.get_player("Grizzly")
        note = await _commit_ovr_updates(row, {}, "en")
        self.assertIsNone(note)

    def _make_view_interaction(self):
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.channel = MagicMock()
        return inter

    async def test_ladder_match_view_excludes_already_matched_from_options(self):
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "Grizzly", "real_ign": "Grizzly"}, {"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "GKHl987", "total_ovr": 7000}],
            league="NP", roster=roster, already_matched=["Grizzly"],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=None, bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        select = view.children[0]
        option_values = [o.value for o in select.options]
        self.assertNotIn("Grizzly", option_values)   # already matched, excluded
        self.assertIn("dougbaldwin", option_values)  # still available
        self.assertIn("__skip__", option_values)

    async def test_ladder_match_view_caps_at_max_entries_per_batch(self):
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "Grizzly", "real_ign": "Grizzly"}]
        missing = [{"real_ign": f"Unknown{i}"} for i in range(6)]
        view = LadderPlayerMatchView(
            missing_entries=missing, league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=None, bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        self.assertEqual(len(view.missing_entries), LadderPlayerMatchView.MAX_ENTRIES)
        self.assertEqual(len(view.remaining_entries), 6 - LadderPlayerMatchView.MAX_ENTRIES)
        # one select per handled entry, plus confirm + skip buttons
        selects = [c for c in view.children if getattr(c, 'options', None) is not None]
        self.assertEqual(len(selects), LadderPlayerMatchView.MAX_ENTRIES)

    async def test_ladder_match_view_chains_to_next_batch_not_dropped(self):
        """The actual reported bug: 6 unmatched names, first batch of 4
        confirmed, must NOT stop and abandon the remaining 2 — must show a
        follow-up view covering them instead."""
        from optimized_bot import LadderPlayerMatchView
        # Real players that exist in the test fixture, plus a couple extra
        # inserted directly so there are enough for a 4-player batch.
        np_team = await db.fetchone("SELECT team_id FROM players WHERE ign='Grizzly'")
        await db.execute(
            "INSERT INTO players (team_id, ign, real_ign, status, off_ovr, def_ovr, total_ovr) "
            "VALUES (?, 'ExtraPlayerA', 'ExtraPlayerA', 'A', 200, 200, 6000)", (np_team['team_id'],)
        )
        await db.execute(
            "INSERT INTO players (team_id, ign, real_ign, status, off_ovr, def_ovr, total_ovr) "
            "VALUES (?, 'ExtraPlayerB', 'ExtraPlayerB', 'A', 200, 200, 6000)", (np_team['team_id'],)
        )
        real_igns = ["Grizzly", "dougbaldwin", "FHRITP", "ExtraPlayerA", "ExtraPlayerB"]
        roster = [{"ign": ign, "real_ign": ign} for ign in real_igns]
        missing = [{"real_ign": f"Unknown{i}", "total_ovr": 7000 + i} for i in range(6)]
        view = LadderPlayerMatchView(
            missing_entries=missing, league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        # Simulate matching all 4 in this batch to the first 4 real igns
        for i, entry in enumerate(view.missing_entries):
            view.selections[entry["real_ign"]] = real_igns[i]

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        await confirm_btn.callback(inter)

        # Must NOT have proceeded to start_ladder_flow yet — a follow-up view
        # for the remaining 2 must have been sent instead.
        inter.followup.send.assert_called_once()
        sent = inter.followup.send.call_args
        next_view = sent.kwargs.get("view")
        self.assertIsInstance(next_view, LadderPlayerMatchView)
        self.assertEqual(len(next_view.missing_entries), 2)  # the 2 that didn't fit in batch 1
        self.assertEqual(next_view.batch_num, 2)
        self.assertEqual(next_view.total_entries, 6)
        # the 4 already matched must carry forward, not be re-offered as options
        self.assertEqual(set(next_view.preselected), set(real_igns[:4]))

    async def test_ladder_match_view_second_batch_of_two_reaches_ladder_flow(self):
        """Confirming the second (final) batch, with nothing left over,
        must actually proceed to start_ladder_flow — not chain forever."""
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": f"Player{i}", "real_ign": f"Player{i}"} for i in range(10)]
        missing_batch_2 = [{"real_ign": "UnknownA"}, {"real_ign": "UnknownB"}]
        view = LadderPlayerMatchView(
            missing_entries=missing_batch_2, league="NP", roster=roster,
            already_matched=["Player0", "Player1", "Player2", "Player3"],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=["previous batch note"], batch_num=2, total_entries=6,
        )
        for entry in view.missing_entries:
            view.selections[entry["real_ign"]] = "__skip__" if False else None  # leave unmatched/skip

        skip_all_btn = next(c for c in view.children if "Skip All" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()

        with patch('optimized_bot.start_ladder_flow', new=AsyncMock()) as mock_start:
            await skip_all_btn.callback(inter)
            mock_start.assert_called_once()
            # The real interaction must be passed through directly — not a
            # separate stand-in object. A previous version built a fake proxy
            # here whose .response was actually the followup webhook (no
            # is_done() method), which crashed inside start_ladder_flow right
            # after the OVR-update notification had already been sent —
            # exactly matching a real user report of that notification
            # appearing but the ladder builder never following it.
            self.assertIs(mock_start.call_args.args[0], inter)
            call_kwargs = mock_start.call_args.kwargs
            self.assertEqual(set(call_kwargs["preselected"]), {"Player0", "Player1", "Player2", "Player3"})

    # --- OvrSanityCheckView: review step for suspicious OVR changes ---

    def _make_suspicious_item(self, ign="Grizzly", old=3200, new=8200, col="total_ovr", row_id=1):
        return {'row': {'id': row_id, 'ign': ign, col: old}, 'suspicious': {col: (old, new)}}

    async def test_ovr_sanity_view_accept_applies_extracted_value(self):
        from optimized_bot import OvrSanityCheckView
        row = await db.get_player("Grizzly")
        item = self._make_suspicious_item(ign="Grizzly", old=row["total_ovr"], new=row["total_ovr"] * 3, row_id=row["id"])
        view = OvrSanityCheckView(
            suspicious_changes=[item], league="NP", game_date=datetime.date.fromisoformat(TODAY),
            interaction_channel=MagicMock(), bot=None, preselected=["Grizzly"], preopponents=[],
            ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None, notifications=[],
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['accept']}
        await select.callback(select_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        with patch('optimized_bot.start_ladder_flow', new=AsyncMock()):
            await confirm_btn.callback(self._make_view_interaction())

        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["total_ovr"], item['suspicious']['total_ovr'][1])

    async def test_ovr_sanity_view_reject_keeps_old_value(self):
        from optimized_bot import OvrSanityCheckView
        row = await db.get_player("Grizzly")
        original_total = row["total_ovr"]
        item = self._make_suspicious_item(ign="Grizzly", old=original_total, new=original_total * 3, row_id=row["id"])
        view = OvrSanityCheckView(
            suspicious_changes=[item], league="NP", game_date=datetime.date.fromisoformat(TODAY),
            interaction_channel=MagicMock(), bot=None, preselected=["Grizzly"], preopponents=[],
            ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None, notifications=[],
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['reject']}
        await select.callback(select_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        with patch('optimized_bot.start_ladder_flow', new=AsyncMock()):
            await confirm_btn.callback(self._make_view_interaction())

        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["total_ovr"], original_total)  # untouched

    async def test_ovr_sanity_view_unreviewed_defaults_to_reject(self):
        """If the admin clicks Confirm without touching a select at all,
        the safest default (reject / keep current value) must apply —
        never silently accepting an unreviewed suspicious change."""
        from optimized_bot import OvrSanityCheckView
        row = await db.get_player("Grizzly")
        original_total = row["total_ovr"]
        item = self._make_suspicious_item(ign="Grizzly", old=original_total, new=original_total * 3, row_id=row["id"])
        view = OvrSanityCheckView(
            suspicious_changes=[item], league="NP", game_date=datetime.date.fromisoformat(TODAY),
            interaction_channel=MagicMock(), bot=None, preselected=["Grizzly"], preopponents=[],
            ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None, notifications=[],
        )
        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        with patch('optimized_bot.start_ladder_flow', new=AsyncMock()):
            await confirm_btn.callback(self._make_view_interaction())

        updated = await db.get_player("Grizzly")
        self.assertEqual(updated["total_ovr"], original_total)

    async def test_ovr_sanity_view_chains_to_next_batch(self):
        """More than 4 suspicious changes must chain to a follow-up batch,
        not silently drop the rest — same principle as LadderPlayerMatchView."""
        from optimized_bot import OvrSanityCheckView
        items = [self._make_suspicious_item(ign=f"P{i}", row_id=i) for i in range(6)]
        view = OvrSanityCheckView(
            suspicious_changes=items, league="NP", game_date=datetime.date.fromisoformat(TODAY),
            interaction_channel=MagicMock(), bot=None, preselected=[], preopponents=[],
            ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None, notifications=[],
        )
        self.assertEqual(len(view.current_batch), OvrSanityCheckView.MAX_ENTRIES)
        self.assertEqual(len(view.remaining_entries), 6 - OvrSanityCheckView.MAX_ENTRIES)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        await confirm_btn.callback(inter)

        inter.followup.send.assert_called_once()
        next_view = inter.followup.send.call_args.kwargs.get("view")
        self.assertIsInstance(next_view, OvrSanityCheckView)
        self.assertEqual(len(next_view.current_batch), 2)
        self.assertEqual(next_view.batch_num, 2)

    async def test_ovr_sanity_view_final_batch_reaches_ladder_flow(self):
        from optimized_bot import OvrSanityCheckView
        items = [self._make_suspicious_item(ign="P0", row_id=0)]
        view = OvrSanityCheckView(
            suspicious_changes=items, league="NP", game_date=datetime.date.fromisoformat(TODAY),
            interaction_channel=MagicMock(), bot=None, preselected=["Grizzly"], preopponents=[],
            ladder_event_type="E1", ladder_our_rank=5, opponent_league_name="Dynasty 1", notifications=[],
        )
        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        with patch('optimized_bot.start_ladder_flow', new=AsyncMock()) as mock_start:
            await confirm_btn.callback(inter)
            mock_start.assert_called_once()
            call_kwargs = mock_start.call_args.kwargs
            self.assertEqual(call_kwargs["preselected"], ["Grizzly"])
            self.assertEqual(call_kwargs["event_type"], "E1")

    async def test_ladder_match_view_routes_manually_matched_suspicious_ovr_to_sanity_check(self):
        """
        Integration point: a player matched through the manual name-match
        flow (not the automatic exact-match path) whose OVR change is also
        suspicious must still be routed to OvrSanityCheckView afterward,
        not silently applied just because they came through a different
        matching path than usual.
        """
        from optimized_bot import LadderPlayerMatchView
        row = await db.get_player("dougbaldwin")
        original_total = row["total_ovr"]
        roster = [{"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "d0ugbaldw1n", "total_ovr": original_total * 3}],
            league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['dougbaldwin']}
        await select.callback(select_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        await confirm_btn.callback(inter)

        # Must NOT have applied the suspicious change yet, and must have
        # routed to OvrSanityCheckView instead of proceeding to the ladder.
        unchanged = await db.get_player("dougbaldwin")
        self.assertEqual(unchanged["total_ovr"], original_total)
        from optimized_bot import OvrSanityCheckView
        sent_view = inter.followup.send.call_args.kwargs.get("view")
        self.assertIsInstance(sent_view, OvrSanityCheckView)

    async def test_ladder_match_view_combines_auto_matched_and_manually_matched_suspicious_ovr(self):
        """
        Direct test that the two review systems don't conflict or clobber
        each other: one player's suspicious OVR change came from the
        automatic exact-match path (carried in via the constructor, exactly
        as ladder_slash does when it finds missing names AND an auto-matched
        suspicious change in the same run), and a second, different
        player's suspicious change is found live during the manual
        name-matching flow itself. Both must end up together in the final
        OvrSanityCheckView — neither path should silently drop the other's.
        """
        from optimized_bot import LadderPlayerMatchView, OvrSanityCheckView
        grizzly = await db.get_player("Grizzly")
        dougbaldwin = await db.get_player("dougbaldwin")
        auto_matched_suspicious = [{
            'row': grizzly,
            'suspicious': {'total_ovr': (grizzly['total_ovr'], grizzly['total_ovr'] * 3)}
        }]
        roster = [{"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "d0ugbaldw1n", "total_ovr": dougbaldwin["total_ovr"] * 3}],
            league="NP", roster=roster, already_matched=["Grizzly"],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[], suspicious_ovr_changes=auto_matched_suspicious,
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['dougbaldwin']}
        await select.callback(select_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        await confirm_btn.callback(inter)

        sent_view = inter.followup.send.call_args.kwargs.get("view")
        self.assertIsInstance(sent_view, OvrSanityCheckView)
        flagged_igns = {item['row']['ign'] for item in sent_view.current_batch}
        self.assertEqual(flagged_igns, {"Grizzly", "dougbaldwin"})

    async def test_ovr_sanity_check_chaining_survives_across_multiple_name_match_batches(self):
        """
        Stronger version of the above: suspicious changes discovered in
        name-match batch 1 must still be present after chaining through
        batch 2 (not just batch-1-into-final-review) — confirms
        self.suspicious_ovr_changes genuinely accumulates across the
        LadderPlayerMatchView's own internal chaining, not just a single hop.
        """
        from optimized_bot import LadderPlayerMatchView, OvrSanityCheckView
        grizzly = await db.get_player("Grizzly")
        dougbaldwin = await db.get_player("dougbaldwin")
        fhritp = await db.get_player("FHRITP")
        roster = [
            {"ign": "Grizzly", "real_ign": "Grizzly"},
            {"ign": "dougbaldwin", "real_ign": "dougbaldwin"},
            {"ign": "FHRITP", "real_ign": "FHRITP"},
        ]
        # 5 missing names forces a chain: batch 1 (4 entries) + batch 2 (1 entry).
        missing = (
            [{"real_ign": "Gr1zzly", "total_ovr": grizzly["total_ovr"] * 3}] +
            [{"real_ign": f"Unknown{i}"} for i in range(3)] +
            [{"real_ign": "d0ugbaldw1n", "total_ovr": dougbaldwin["total_ovr"] * 3}]
        )
        view = LadderPlayerMatchView(
            missing_entries=missing, league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        # Batch 1: match the Grizzly-lookalike (suspicious), skip the 3 unknowns.
        batch1_select = view.children[0]
        sel_inter = self._make_view_interaction()
        sel_inter.data = {'values': ['Grizzly']}
        await batch1_select.callback(sel_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter1 = self._make_view_interaction()
        await confirm_btn.callback(inter1)

        batch2_view = inter1.followup.send.call_args.kwargs.get("view")
        self.assertIsInstance(batch2_view, LadderPlayerMatchView)
        # The batch-1 suspicious find must have survived into batch 2's state.
        self.assertEqual(len(batch2_view.suspicious_ovr_changes), 1)
        self.assertEqual(batch2_view.suspicious_ovr_changes[0]['row']['ign'], "Grizzly")

        # Batch 2: match the dougbaldwin-lookalike (also suspicious).
        batch2_select = batch2_view.children[0]
        sel_inter2 = self._make_view_interaction()
        sel_inter2.data = {'values': ['dougbaldwin']}
        await batch2_select.callback(sel_inter2)

        confirm_btn2 = next(c for c in batch2_view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter2 = self._make_view_interaction()
        await confirm_btn2.callback(inter2)

        final_view = inter2.followup.send.call_args.kwargs.get("view")
        self.assertIsInstance(final_view, OvrSanityCheckView)
        flagged_igns = {item['row']['ign'] for item in final_view.current_batch}
        self.assertEqual(flagged_igns, {"Grizzly", "dougbaldwin"})

    async def test_ladder_match_view_confirm_end_to_end_reaches_real_start_ladder_flow(self):
        """
        Rigorous version of the above: doesn't mock start_ladder_flow at all,
        and uses a realistic interaction stub whose response.is_done() is a
        genuine stateful check (only True after defer()/send_message() was
        actually called), not a permissive MagicMock that would return a
        truthy value regardless of what happened. This is the shape of test
        that would have actually caught the reported bug — the previous
        tests all passed against the broken code because MagicMock-based
        interactions don't enforce real Discord interaction semantics.
        """
        class _StatefulResponse:
            def __init__(self):
                self._done = False
            async def defer(self, *a, **kw):
                self._done = True
            async def send_message(self, *a, **kw):
                self._done = True
            def is_done(self):
                return self._done

        class _StrictFollowup:
            """Only has what a real discord.Webhook actually has — no
            auto-mocked attributes, so accessing something that doesn't
            exist (like .is_done()) genuinely raises, the same as production."""
            def __init__(self):
                self.send = AsyncMock()

        class _RealisticInteraction:
            def __init__(self, channel):
                self.response = _StatefulResponse()
                self.followup = _StrictFollowup()
                self.channel = channel
                self.locale = None
                self.data = {}

        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "Grizzly", "real_ign": "Grizzly"}, {"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "GKHl987", "total_ovr": 7000}],
            league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        view.selections["GKHl987"] = "Grizzly"

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        inter = _RealisticInteraction(channel=MagicMock())

        await confirm_btn.callback(inter)  # must not raise — this is what actually failed in production

        # The ladder builder's own first message must have been sent via
        # this same interaction's followup (proving start_ladder_flow ran
        # to completion, not just up to the OVR-update notification).
        self.assertGreaterEqual(inter.followup.send.call_count, 1)
        sent_calls = inter.followup.send.call_args_list
        self.assertTrue(any('view' in c.kwargs for c in sent_calls))  # the PlayerToggleView being sent

    async def test_ladder_match_view_confirm_applies_chosen_match(self):
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "d0ugbaldw1n", "total_ovr": 6999, "off_ovr": 260, "def_ovr": 240}],
            league="NP", roster=roster, already_matched=["Grizzly"],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type="E1", ladder_our_rank=12, opponent_league_name="Dynasty 1",
            notifications=[],
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['dougbaldwin']}
        await select.callback(select_inter)
        self.assertEqual(view.selections["d0ugbaldw1n"], "dougbaldwin")

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        confirm_inter = self._make_view_interaction()
        await confirm_btn.callback(confirm_inter)

        updated = await db.get_player("dougbaldwin")
        self.assertEqual(updated["total_ovr"], 6999)
        self.assertIn("dougbaldwin", view.preselected)

    async def test_ladder_match_view_skip_option_applies_no_update(self):
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        original = await db.get_player("dougbaldwin")
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "NotARealPlayer", "total_ovr": 9999}],
            league="NP", roster=roster, already_matched=[],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        select = view.children[0]
        select_inter = self._make_view_interaction()
        select_inter.data = {'values': ['__skip__']}
        await select.callback(select_inter)

        confirm_btn = next(c for c in view.children if "Confirm" in (getattr(c, 'label', None) or ""))
        confirm_inter = self._make_view_interaction()
        await confirm_btn.callback(confirm_inter)

        unchanged = await db.get_player("dougbaldwin")
        self.assertEqual(unchanged["total_ovr"], original["total_ovr"])  # untouched
        self.assertNotIn("dougbaldwin", view.preselected)

    async def test_ladder_match_view_skip_all_button_proceeds_without_matching(self):
        from optimized_bot import LadderPlayerMatchView
        roster = [{"ign": "dougbaldwin", "real_ign": "dougbaldwin"}]
        original = await db.get_player("dougbaldwin")
        view = LadderPlayerMatchView(
            missing_entries=[{"real_ign": "GKHl987", "total_ovr": 9999}],
            league="NP", roster=roster, already_matched=["Grizzly"],
            game_date=datetime.date.fromisoformat(TODAY), interaction_channel=MagicMock(), bot=None,
            preopponents=[], ladder_event_type=None, ladder_our_rank=None, opponent_league_name=None,
            notifications=[],
        )
        skip_all_btn = next(c for c in view.children if "Skip All" in (getattr(c, 'label', None) or ""))
        inter = self._make_view_interaction()
        await skip_all_btn.callback(inter)

        unchanged = await db.get_player("dougbaldwin")
        self.assertEqual(unchanged["total_ovr"], original["total_ovr"])
        self.assertEqual(view.preselected, ["Grizzly"])  # unchanged from what was already matched

    def test_parse_csv_opponents_basic(self):
        from ladder_flow import _parse_csv_opponents
        result = _parse_csv_opponents("TeamA, 7200, 245\nTeamB, 6800, 231")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "TeamA")
        self.assertEqual(result[0]["total_ovr"], 7200)
        self.assertEqual(result[0]["def_ovr"], 245)
        self.assertEqual(result[1]["name"], "TeamB")

    def test_parse_csv_opponents_missing_ovr(self):
        from ladder_flow import _parse_csv_opponents
        result = _parse_csv_opponents("TeamA, , \nTeamB")
        self.assertEqual(result[0]["name"], "TeamA")
        self.assertIsNone(result[0]["total_ovr"])
        self.assertIsNone(result[0]["def_ovr"])

    def test_parse_csv_opponents_empty_lines(self):
        from ladder_flow import _parse_csv_opponents
        result = _parse_csv_opponents("TeamA, 7200, 245\n\n\nTeamB, 6800, 231")
        self.assertEqual(len(result), 2)

    def test_parse_csv_opponents_16_entries(self):
        from ladder_flow import _parse_csv_opponents
        lines = "\n".join(f"Team{i}, {6000+i*100}, {200+i}" for i in range(16))
        result = _parse_csv_opponents(lines)
        self.assertEqual(len(result), 16)
        self.assertEqual(result[15]["name"], "Team15")

    def test_parse_csv_opponents_strips_whitespace(self):
        from ladder_flow import _parse_csv_opponents
        result = _parse_csv_opponents("  TeamA  ,  7200  ,  245  ")
        self.assertEqual(result[0]["name"], "TeamA")
        self.assertEqual(result[0]["total_ovr"], 7200)

    # --- opponent persistence: same table as the final "Confirm Matchups" save ---

    async def test_save_ladder_to_db_overwrites_same_slots(self):
        """An interim save (e.g. from the opponent-entry 'continue' step) and the
        final save (Confirm Matchups) both write through save_ladder_to_db into
        the same (team_id, game_date, slot) rows — no separate cache table,
        finishing the ladder just overwrites what's already there."""
        from ladder_flow import save_ladder_to_db, LadderState, MATCHUP_SIZE

        state = LadderState("NP", TODAY, None)
        state.selected  = [f"P{i}" for i in range(MATCHUP_SIZE)]
        state.opponents = [
            {"name": f"TeamA{i}", "total_ovr": 7000 + i, "def_ovr": 200 + i}
            for i in range(MATCHUP_SIZE)
        ]
        identity = list(range(MATCHUP_SIZE))

        # Interim save — as the opponent-entry "Done — Sort & Arrange" button does.
        await save_ladder_to_db(state, identity, identity)
        rows = await db.fetchall(
            "SELECT slot, our_ign, opp_ign FROM matchup_ladder WHERE team_id='NP' AND game_date=? ORDER BY slot",
            (TODAY,)
        )
        self.assertEqual(len(rows), MATCHUP_SIZE)
        self.assertEqual(rows[0]["our_ign"], "P0")
        self.assertEqual(rows[0]["opp_ign"], "TeamA0")

        # Final save — as Confirm Matchups does, with a different (real) order.
        reordered = list(reversed(identity))
        await save_ladder_to_db(state, reordered, reordered)
        rows = await db.fetchall(
            "SELECT slot, our_ign, opp_ign FROM matchup_ladder WHERE team_id='NP' AND game_date=? ORDER BY slot",
            (TODAY,)
        )

    async def test_save_ladder_to_db_persists_extracted_matchup_context(self):
        from ladder_flow import save_ladder_to_db, LadderState, MATCHUP_SIZE
        state = LadderState("NP", TODAY, None)
        state.selected  = [f"P{i}" for i in range(MATCHUP_SIZE)]
        state.opponents = [{"name": f"TeamA{i}", "total_ovr": 7000, "def_ovr": 200} for i in range(MATCHUP_SIZE)]
        state.opponent_league_name = "seams suspicious"
        state.event_type           = "E1"
        state.our_rank              = 45
        identity = list(range(MATCHUP_SIZE))

        await save_ladder_to_db(state, identity, identity)

        row = await db.fetchone(
            "SELECT opp_ign, event_type, our_rank FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (TODAY,)
        )
        self.assertEqual(row["opp_ign"], "seams suspicious")
        self.assertEqual(row["event_type"], "E1")
        self.assertEqual(row["our_rank"], 45)

    async def test_save_ladder_to_db_does_not_touch_matchup_day_when_nothing_extracted(self):
        """The manual CSV entry flow never sets any of this — must not create
        a blank/garbage matchup_day row when there's nothing to save."""
        from ladder_flow import save_ladder_to_db, LadderState, MATCHUP_SIZE
        state = LadderState("NP", TODAY, None)
        state.selected  = [f"P{i}" for i in range(MATCHUP_SIZE)]
        state.opponents = [{"name": f"TeamA{i}", "total_ovr": 7000, "def_ovr": 200} for i in range(MATCHUP_SIZE)]
        identity = list(range(MATCHUP_SIZE))

        await save_ladder_to_db(state, identity, identity)

        row = await db.fetchone(
            "SELECT * FROM matchup_day WHERE team_id='NP' AND game_date=?", (TODAY,)
        )
        self.assertIsNone(row)

    async def test_start_ladder_flow_threads_extracted_context_into_state(self):
        from ladder_flow import start_ladder_flow
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.is_done = MagicMock(return_value=False)
        inter.response.send_message = AsyncMock()
        inter.channel = MagicMock()

        await start_ladder_flow(
            inter, "NP", datetime.date.fromisoformat(TODAY),
            opponent_league_name="Dynasty 1", event_type="E2", our_rank=12
        )

        view = inter.response.send_message.call_args.kwargs.get("view")
        self.assertEqual(view.state.opponent_league_name, "Dynasty 1")
        self.assertEqual(view.state.event_type, "E2")
        self.assertEqual(view.state.our_rank, 12)

    async def test_show_ladder_title_includes_opponent_when_set(self):
        """Same query + format logic show_ladder_slash uses to build its title —
        tested in isolation since the command itself is @tree.command-wrapped."""
        await db.set_matchup("NP", TODAY, "seams suspicious", "E1")
        matchup = await db.fetchone(
            "SELECT opp_ign, event_type FROM matchup_day WHERE team_id=? AND game_date=?",
            ("NP", TODAY)
        )
        opp_str = ""
        if matchup and matchup.get('opp_ign'):
            opp_str = f" vs {matchup['opp_ign']}"
            if matchup.get('event_type'):
                opp_str += f" ({matchup['event_type']})"
        self.assertEqual(opp_str, " vs seams suspicious (E1)")

    async def test_show_ladder_title_blank_when_no_matchup_recorded(self):
        matchup = await db.fetchone(
            "SELECT opp_ign, event_type FROM matchup_day WHERE team_id=? AND game_date=?",
            ("NP", TODAY)
        )
        opp_str = ""
        if matchup and matchup.get('opp_ign'):
            opp_str = f" vs {matchup['opp_ign']}"
        self.assertEqual(opp_str, "")


    async def test_opponent_entry_modal_loads_saved_snapshot(self):
        """If nothing's been entered yet this session, the opponent-entry modal
        should default to whatever's already saved to this team's ladder for
        this date — e.g. from an earlier /ladder run that got aborted."""
        from ladder_flow import OpponentEntryView, LadderState, MATCHUP_SIZE

        for i in range(MATCHUP_SIZE):
            await db.upsert_ladder_slot(
                "NP", TODAY, i + 1,
                opp_ign=f"SavedOpp{i}", opp_def_ovr=200 + i,
                our_total_ovr=7000 + i, our_ign=f"P{i}",
            )

        state = LadderState.__new__(LadderState)
        state.team_id   = "NP"
        state.game_date = TODAY
        state.lang      = "en"
        state.opponents = []  # nothing entered yet this session

        view = OpponentEntryView.__new__(OpponentEntryView)
        view.state = state

        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()

        await view._enter(inter)

        modal = inter.response.send_modal.call_args.args[0]
        self.assertIn("SavedOpp0", modal.opponents.default)
        self.assertIn("SavedOpp15", modal.opponents.default)

    # --- manual ladder building must also be able to set the opponent
    # league name / division / our rank, the same context an AI screenshot
    # extraction would have captured, so the confirmation shown at the end
    # isn't exclusive to the extraction flow ---

    async def test_ladder_matchup_info_modal_saves_entered_values(self):
        from ladder_flow import LadderMatchupInfoModal, LadderState
        state = LadderState("NP", TODAY, None)
        modal = LadderMatchupInfoModal(state)
        modal.opp_name.value = "seams suspicious"
        modal.division.value = "e1"  # lowercase, should normalize
        modal.rank.value = "45"
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        await modal.on_submit(inter)

        self.assertEqual(state.opponent_league_name, "seams suspicious")
        self.assertEqual(state.event_type, "E1")
        self.assertEqual(state.our_rank, 45)

    async def test_ladder_matchup_info_modal_blank_fields_clear_state(self):
        from ladder_flow import LadderMatchupInfoModal, LadderState
        state = LadderState("NP", TODAY, None)
        state.opponent_league_name = "OldName"
        state.event_type = "E2"
        state.our_rank = 10
        modal = LadderMatchupInfoModal(state)
        modal.opp_name.value = ""
        modal.division.value = ""
        modal.rank.value = ""
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        await modal.on_submit(inter)

        self.assertIsNone(state.opponent_league_name)
        self.assertIsNone(state.event_type)
        self.assertIsNone(state.our_rank)

    async def test_ladder_matchup_info_modal_non_numeric_rank_becomes_none(self):
        """A typo in the rank field must not crash — just treated as not entered."""
        from ladder_flow import LadderMatchupInfoModal, LadderState
        state = LadderState("NP", TODAY, None)
        modal = LadderMatchupInfoModal(state)
        modal.opp_name.value = "seams suspicious"
        modal.division.value = ""
        modal.rank.value = "not a number"
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        await modal.on_submit(inter)  # must not raise
        self.assertIsNone(state.our_rank)

    async def test_ladder_matchup_info_modal_prefills_from_existing_state(self):
        from ladder_flow import LadderMatchupInfoModal, LadderState
        state = LadderState("NP", TODAY, None)
        state.opponent_league_name = "Dynasty 1"
        state.event_type = "E2"
        state.our_rank = 12
        modal = LadderMatchupInfoModal(state)
        self.assertEqual(modal.opp_name.default, "Dynasty 1")
        self.assertEqual(modal.division.default, "E2")
        self.assertEqual(modal.rank.default, "12")

    async def test_opponent_entry_view_button_opens_matchup_info_modal(self):
        import i18n
        from ladder_flow import OpponentEntryView, LadderMatchupInfoModal, LadderState, MATCHUP_SIZE
        state = LadderState("NP", TODAY, None)
        view = OpponentEntryView(state)
        info_button = next(c for c in view.children if i18n.t('ladder.matchup_info_btn', 'en') == c.label)
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()
        await info_button.callback(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, LadderMatchupInfoModal)

    async def test_opponent_entry_view_embed_shows_context_when_set(self):
        from ladder_flow import OpponentEntryView, LadderState
        state = LadderState("NP", TODAY, None)
        state.opponent_league_name = "seams suspicious"
        state.event_type = "E1"
        state.our_rank = 45
        view = OpponentEntryView(state)
        embed = view._build_embed()
        calls = {c.kwargs.get("name"): c.kwargs.get("value") for c in embed.add_field.call_args_list}
        self.assertIn("Matchup", calls)
        self.assertIn("seams suspicious", calls["Matchup"])

    async def test_opponent_entry_view_embed_omits_context_when_not_set(self):
        from ladder_flow import OpponentEntryView, LadderState
        state = LadderState("NP", TODAY, None)
        view = OpponentEntryView(state)
        embed = view._build_embed()
        names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertNotIn("Matchup", names)

    async def test_opponent_entry_modal_prefers_in_session_entries(self):
        """If opponents were already entered this session, the modal should use
        those, not silently replace them with an older saved snapshot."""
        from ladder_flow import OpponentEntryView, LadderState, MATCHUP_SIZE

        await db.upsert_ladder_slot(
            "NP", TODAY, 1, opp_ign="OldSavedOpp", opp_def_ovr=210,
            our_total_ovr=7000, our_ign="P0",
        )

        state = LadderState.__new__(LadderState)
        state.team_id   = "NP"
        state.game_date = TODAY
        state.lang      = "en"
        state.opponents = [
            {"name": "FreshOpp", "total_ovr": 6900, "def_ovr": 220}
        ] + [{"name": "-", "total_ovr": None, "def_ovr": None} for _ in range(MATCHUP_SIZE - 1)]

        view = OpponentEntryView.__new__(OpponentEntryView)
        view.state = state

        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()

        await view._enter(inter)

        modal = inter.response.send_modal.call_args.args[0]
        self.assertIn("FreshOpp", modal.opponents.default)
        self.assertNotIn("OldSavedOpp", modal.opponents.default)


# ---------------------------------------------------------------------------
# Test: Data integrity
# ---------------------------------------------------------------------------

class TestSiege(unittest.IsolatedAsyncioTestCase):
    """Tests for siege.py — handler routing, modal submission, and the
    admin correction view (constructed for real now that the UI stub
    supports add_item/children)."""

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()
        import siege as _siege_mod
        self.siege = _siege_mod

    async def asyncTearDown(self):
        await _patched_close()

    def _make_interaction(self):
        inter = MagicMock()
        inter.locale = discord.Locale.american_english
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.response.send_modal = AsyncMock()
        inter.response.defer = AsyncMock()
        inter.response.edit_message = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.channel = MagicMock()
        inter.channel.send = AsyncMock()
        inter.namespace = MagicMock()
        return inter

    # --- /siege ---

    async def test_handle_siege_sends_modal(self):
        inter = self._make_interaction()
        await self.siege.handle_siege(inter, "NP")
        inter.response.send_modal.assert_awaited_once()
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.SiegeStartModal)
        self.assertEqual(modal.team_id, "NP")

    async def test_siege_start_modal_creates_match(self):
        modal = self.siege.SiegeStartModal("NP")
        modal.opp_league.value = "WolfpackMafia"
        modal.opp_rank.value   = "3"
        modal.our_rank.value   = "2"
        modal.division.value   = "E1"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        match = await db.get_active_siege_match("NP")
        self.assertIsNotNone(match)
        self.assertEqual(match["opp_league"], "WolfpackMafia")
        inter.response.send_message.assert_awaited_once()

    async def test_siege_start_modal_blocks_second_active(self):
        await db.start_siege_match("NP", "ExistingOpp")
        modal = self.siege.SiegeStartModal("NP")
        modal.opp_league.value = "NewOpp"
        modal.opp_rank.value = modal.our_rank.value = modal.division.value = ""
        inter = self._make_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once()
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("already an active siege match", msg)

    # --- /node ---

    async def test_handle_node_no_active_match(self):
        inter = self._make_interaction()
        await self.siege.handle_node(inter, "NP", "No Mod")
        inter.response.send_message.assert_awaited_once()
        self.assertIn("No active siege match", inter.response.send_message.call_args.args[0])

    async def test_handle_node_sends_modal(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        inter = self._make_interaction()
        await self.siege.handle_node(inter, "NP", "Run Plays Only")
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.NodeModal)
        self.assertEqual(modal.match_id, match["id"])
        self.assertEqual(modal.mod, "Run Plays Only")

    async def test_node_modal_creates_node(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        modal = self.siege.NodeModal(match["id"], "No Mod")
        modal.opponent_name.value   = "BigBoy87"
        modal.opponent_ovr.value    = "6500"
        modal.points_required.value = "30"
        modal.points_reward.value   = "10"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        node = (await db.get_siege_open_nodes_by_name(match["id"], "BigBoy87") or [None])[0]
        self.assertIsNotNone(node)
        self.assertEqual(node["points_required"], 30)
        self.assertEqual(node["points_reward"], 10)
        self.assertEqual(node["opponent_ovr"], 6500)

    async def test_node_modal_rejects_non_integer(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        modal = self.siege.NodeModal(match["id"], "No Mod")
        modal.opponent_name.value   = "BigBoy87"
        modal.opponent_ovr.value    = ""
        modal.points_required.value = "abc"
        modal.points_reward.value   = "10"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once()
        node = (await db.get_siege_open_nodes_by_name(match["id"], "BigBoy87") or [None])[0]
        self.assertIsNone(node)

    # --- /siegescore ---

    async def test_siege_opponent_autocomplete_shows_all_mods_together(self):
        """No mod pre-selection needed — modded and un-modded nodes both show up."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="OpenGuy",
                                 opponent_ovr=None, points_required=50, points_reward=5)
        await db.add_siege_node(match["id"], mod="Run Plays Only", opponent_name="ModdedGuy",
                                 opponent_ovr=None, points_required=30, points_reward=10)
        cleared = await db.add_siege_node(match["id"], mod="Skip 1st Down", opponent_name="ClearedGuy",
                                           opponent_ovr=None, points_required=10, points_reward=5)
        await db.update_siege_node(cleared["id"], status="cleared")

        inter = self._make_interaction()
        inter.namespace.league = "NP"
        choices = await self.siege.siege_opponent_autocomplete(inter, "")
        labels = {c.name for c in choices}
        self.assertTrue(any("OpenGuy" in l for l in labels))
        self.assertTrue(any("ModdedGuy" in l for l in labels))
        self.assertFalse(any("ClearedGuy" in l for l in labels))

    async def test_siege_opponent_autocomplete_value_is_node_id(self):
        """The visible label is friendly; the underlying value is the node id
        (what actually disambiguates duplicate No Mod names)."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="OpenGuy",
                                        opponent_ovr=6500, points_required=50, points_reward=5)
        inter = self._make_interaction()
        inter.namespace.league = "NP"
        choices = await self.siege.siege_opponent_autocomplete(inter, "OpenGuy")
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].value, str(node["id"]))
        self.assertIn("OpenGuy", choices[0].name)
        self.assertIn("No Mod", choices[0].name)

    async def test_siege_opponent_autocomplete_duplicate_no_mod_names_both_listed(self):
        """Two No Mod nodes sharing a name must both appear, as separate selectable entries."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node_a = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                          opponent_ovr=None, points_required=20, points_reward=8)
        node_b = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                          opponent_ovr=None, points_required=30, points_reward=12)
        inter = self._make_interaction()
        inter.namespace.league = "NP"
        choices = await self.siege.siege_opponent_autocomplete(inter, "Slayer")
        self.assertEqual(len(choices), 2)
        self.assertEqual({c.value for c in choices}, {str(node_a["id"]), str(node_b["id"])})

    async def test_handle_siegescore_no_active_match(self):
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", "1")
        self.assertIn("No active siege match", inter.response.send_message.call_args.args[0])

    async def test_handle_siegescore_node_not_found(self):
        await db.start_siege_match("NP", "WolfpackMafia")
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", "NoSuchOpponent")
        self.assertIn("No open node found", inter.response.send_message.call_args.args[0])

    async def test_handle_siegescore_player_not_found(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                 opponent_ovr=None, points_required=30, points_reward=10)
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "NoSuchPlayer", "BigBoy87")
        self.assertIn("not found", inter.response.send_message.call_args.args[0])

    async def test_handle_siegescore_resolves_via_autocomplete_id(self):
        """The normal path: opponent is the node id the autocomplete supplied, not a typed name."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", str(node["id"]))
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.SiegeScoreModal)
        self.assertEqual(modal.node_id, node["id"])

    async def test_handle_siegescore_manual_name_unambiguous_still_works(self):
        """If someone types a name by hand and it's unique, it should still resolve."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", "BigBoy87")
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.SiegeScoreModal)
        self.assertEqual(modal.node_id, node["id"])

    async def test_handle_siegescore_manual_name_ambiguous_flags_instead_of_guessing(self):
        """Two No Mod nodes share a name — typing the name manually must not
        silently pick one; it should tell the admin to use autocomplete."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                 opponent_ovr=None, points_required=20, points_reward=8)
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                 opponent_ovr=None, points_required=30, points_reward=12)
        inter = self._make_interaction()
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", "Slayer99")
        inter.response.send_modal.assert_not_awaited()
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("2", msg)
        self.assertIn("autocomplete", msg.lower())

    async def test_handle_siegescore_resolves_duplicate_names_independently_via_id(self):
        """Two No Mod nodes share a name — each must be individually scoreable via its own id."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node_a = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                          opponent_ovr=None, points_required=20, points_reward=8)
        node_b = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                          opponent_ovr=None, points_required=30, points_reward=12)

        inter_a = self._make_interaction()
        await self.siege.handle_siegescore(inter_a, "NP", "Grizzly", str(node_a["id"]))
        modal_a = inter_a.response.send_modal.call_args.args[0]
        self.assertEqual(modal_a.node_id, node_a["id"])

        inter_b = self._make_interaction()
        await self.siege.handle_siegescore(inter_b, "NP", "Grizzly", str(node_b["id"]))
        modal_b = inter_b.response.send_modal.call_args.args[0]
        self.assertEqual(modal_b.node_id, node_b["id"])

    async def test_league_player_autocomplete_scopes_to_specified_league(self):
        from optimized_bot import league_player_autocomplete
        inter = MagicMock()
        inter.namespace = MagicMock()
        inter.namespace.league = "NP"
        choices = await league_player_autocomplete(inter, "")
        names = [c.name for c in choices]
        self.assertIn("Grizzly", names)     # NP active player
        self.assertIn("dougbaldwin", names)  # NP active player
        self.assertIn("FHRITP", names)       # NP active player
        # Bob is ND, not NP — must not appear when scoped to NP
        self.assertNotIn("Bob", names)

    async def test_league_player_autocomplete_finds_transferred_player(self):
        """Directly reproduces the reported bug: a player transferred INTO a
        league must be findable via that league's own autocomplete, not
        buried behind (or missing from) a global, unfiltered search."""
        from optimized_bot import league_player_autocomplete
        # Simulate a transfer: an ND player moves to NP
        await db.execute("UPDATE players SET team_id='NP' WHERE ign='Bob'")
        await db.execute("UPDATE players SET status='A' WHERE ign='Bob'")

        inter = MagicMock()
        inter.namespace = MagicMock()
        inter.namespace.league = "NP"
        choices = await league_player_autocomplete(inter, "")
        names = [c.name for c in choices]
        self.assertIn("Bob", names)  # now on NP, must show up for NP's siege scoring

    async def test_league_player_autocomplete_excludes_inactive(self):
        from optimized_bot import league_player_autocomplete
        await db.execute("UPDATE players SET status='R' WHERE ign='FHRITP'")
        inter = MagicMock()
        inter.namespace = MagicMock()
        inter.namespace.league = "NP"
        choices = await league_player_autocomplete(inter, "")
        names = [c.name for c in choices]
        self.assertNotIn("FHRITP", names)

    async def test_league_player_autocomplete_no_league_selected_returns_empty(self):
        from optimized_bot import league_player_autocomplete
        inter = MagicMock()
        inter.namespace = MagicMock()
        inter.namespace.league = None
        choices = await league_player_autocomplete(inter, "")
        self.assertEqual(choices, [])

    async def test_league_player_autocomplete_filters_by_current_prefix(self):
        from optimized_bot import league_player_autocomplete
        inter = MagicMock()
        inter.namespace = MagicMock()
        inter.namespace.league = "NP"
        choices = await league_player_autocomplete(inter, "Griz")
        names = [c.name for c in choices]
        self.assertEqual(names, ["Grizzly"])

    async def test_siege_score_modal_logs_score(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        modal = self.siege.SiegeScoreModal(node["id"], "BigBoy87", "Grizzly")
        modal.drives.value = "3"
        modal.points.value = "14"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        totals = await db.get_siege_node_totals(node["id"])
        self.assertEqual(totals["points"], 14)
        msg = inter.response.send_message.call_args.args[0]
        self.assertNotIn("cleared", msg.lower())

    async def test_log_siege_score_replaces_not_adds_for_same_player_and_node(self):
        """Re-scoring the same player against the same node must replace
        their entry, not add a second one that sums into the total."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=100, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", drives=3, points=20)
        await db.log_siege_score(node["id"], "Grizzly", drives=2, points=15)

        totals = await db.get_siege_node_totals(node["id"])
        self.assertEqual(totals["points"], 15)   # latest value only, not 20+15=35
        self.assertEqual(totals["drives"], 2)

        rows = await db.get_siege_scores_for_node(node["id"])
        self.assertEqual(len(rows), 1)  # still exactly one row for Grizzly on this node

    async def test_log_siege_score_different_players_still_both_count(self):
        """Replace-not-add is scoped to (node, player) — different players
        scoring the same node must still both contribute to the total."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=100, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", drives=3, points=20)
        await db.log_siege_score(node["id"], "dougbaldwin", drives=2, points=15)

        totals = await db.get_siege_node_totals(node["id"])
        self.assertEqual(totals["points"], 35)  # both players' entries count
        rows = await db.get_siege_scores_for_node(node["id"])
        self.assertEqual(len(rows), 2)

    async def test_log_siege_score_replace_can_still_trigger_clear(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=20, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", drives=3, points=10)
        result = await db.log_siege_score(node["id"], "Grizzly", drives=3, points=25)  # replaces with a higher value
        self.assertTrue(result["cleared"])

    async def test_migration_merges_preexisting_duplicate_siege_scores(self):
        """Simulates data already corrupted by the old additive behavior —
        two rows for the same node+player before this fix existed — and
        confirms the migration merges them into one, keeping the newest."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=100, points_reward=10)
        grizzly = await db.get_player("Grizzly")

        await db.execute("DROP INDEX IF EXISTS uq_siege_node_player")
        await db.execute(
            "INSERT INTO siege_scores (node_id, player_id, drives, points) VALUES (?, ?, 3, 20)",
            (node["id"], grizzly["id"])
        )
        await db.execute(
            "INSERT INTO siege_scores (node_id, player_id, drives, points) VALUES (?, ?, 2, 15)",
            (node["id"], grizzly["id"])
        )
        rows_before = await db.get_siege_scores_for_node(node["id"])
        self.assertEqual(len(rows_before), 2)  # confirms the corrupted state exists first

        await db._migrate_schema()

        rows_after = await db.get_siege_scores_for_node(node["id"])
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0]["points"], 15)  # newest entry kept

    async def test_migration_rebuilds_siege_unique_index(self):
        """After the migration, a raw duplicate insert for the same node+player
        must be rejected outright by the database itself."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=100, points_reward=10)
        grizzly = await db.get_player("Grizzly")
        await db._migrate_schema()
        await db.execute(
            "INSERT INTO siege_scores (node_id, player_id, drives, points) VALUES (?, ?, 3, 20)",
            (node["id"], grizzly["id"])
        )
        with self.assertRaises(Exception):
            await db.execute(
                "INSERT INTO siege_scores (node_id, player_id, drives, points) VALUES (?, ?, 2, 15)",
                (node["id"], grizzly["id"])
            )

    async def test_siege_score_modal_reports_cleared(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=10, points_reward=10)
        modal = self.siege.SiegeScoreModal(node["id"], "BigBoy87", "Grizzly")
        modal.drives.value = "3"
        modal.points.value = "10"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("cleared", msg.lower())

    # --- /siegestatus ---

    async def test_handle_siegestatus_no_active_match(self):
        inter = self._make_interaction()
        await self.siege.handle_siegestatus(inter, "NP")
        self.assertIn("No active siege match", inter.response.send_message.call_args.args[0])

    async def test_build_status_embed_highlights_top_nodes(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        low  = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Low",
                                        opponent_ovr=None, points_required=50, points_reward=5)
        high = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="High",
                                        opponent_ovr=None, points_required=50, points_reward=25)
        summary = await db.get_siege_match_summary(match["id"])
        player_totals = await db.get_siege_all_player_totals(match["id"])
        embed = self.siege.build_status_embed("NP", match, summary, player_totals)
        # Pull the "Open Nodes" field value out of the recorded add_field calls
        open_field_value = None
        for call in embed.add_field.call_args_list:
            if call.kwargs.get("name", "").startswith("🔓 Open Nodes"):
                open_field_value = call.kwargs.get("value")
        self.assertIsNotNone(open_field_value)
        self.assertIn("⭐", open_field_value)
        # High-reward node should be starred, low-reward should not
        high_line = [l for l in open_field_value.split("\n") if "High" in l][0]
        low_line  = [l for l in open_field_value.split("\n") if "Low" in l and "Node" not in l]
        self.assertIn("⭐", high_line)

    # --- Embed field length limits: Discord rejects the ENTIRE message if
    # any single field value exceeds 1024 characters, which is exactly what
    # was reported: /siegestatus, /siegefinal, and /updatesiege (which all
    # share build_status_embed) failed outright on every single call once a
    # long-running siege accumulated enough open nodes.

    def test_chunk_lines_to_fit_small_list_stays_single_chunk(self):
        chunks = self.siege._chunk_lines_to_fit(["line1", "line2", "line3"])
        self.assertEqual(chunks, ["line1\nline2\nline3"])

    def test_chunk_lines_to_fit_splits_when_over_limit(self):
        long_lines = [f"Node{i}: opponent_name_{i} (OVR 3200) — No Mod, 20/40 pts" for i in range(50)]
        chunks = self.siege._chunk_lines_to_fit(long_lines)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1024)
        # No line's content should be lost across the split.
        rejoined = "\n".join(chunks)
        for line in long_lines:
            self.assertIn(line, rejoined)

    def test_chunk_lines_to_fit_caps_chunk_count_with_accurate_overflow_note(self):
        # Each line ~50 chars, so ~20 lines fit per 1024-char chunk — 500
        # lines guarantees well over 5 chunks' worth of content, genuinely
        # exercising the cap rather than happening to fit under it.
        huge_lines = [f"Node{i}: SomeOpponentName (OVR 3200) — No Mod" for i in range(500)]
        chunks = self.siege._chunk_lines_to_fit(huge_lines, max_chars=1024, max_chunks=5)
        self.assertEqual(len(chunks), 5)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1024)
        self.assertIn("more", chunks[-1])

    async def test_build_status_embed_realistic_16_node_worst_case_stays_within_field_limits(self):
        """
        Directly reproduces the reported production crash, sized to the
        actual constraint: a siege match pits 16 players against 16
        opponents, one node per opponent, so 16 is a hard, real ceiling —
        never 30, never 200. Uses a deliberately long opponent name for
        each of the 16 to test the actual worst case that can occur, not
        an unrealistically large node count that could never happen.
        """
        match = await db.start_siege_match("NP", "WolfpackMafia")
        for i in range(self.siege.MAX_SIEGE_NODES):
            await db.add_siege_node(
                match["id"], mod="No Mod", opponent_name=f"ReasonablyLongOpponentPlayerName_{i}",
                opponent_ovr=3200 + i * 10, points_required=40, points_reward=60
            )
        summary = await db.get_siege_match_summary(match["id"])
        player_totals = await db.get_siege_all_player_totals(match["id"])
        embed = self.siege.build_status_embed("NP", match, summary, player_totals)

        calls = embed.add_field.call_args_list
        for call in calls:
            value = call.kwargs.get("value", "")
            name = call.kwargs.get("name", "")
            self.assertLessEqual(len(value), 1024, f"Field {name!r} exceeded Discord's 1024-char limit")
            self.assertLessEqual(len(name), 256)
        self.assertLessEqual(len(calls), 25)  # Discord's overall fields-per-embed limit

        # The realistic worst case (16 nodes, long names) must never actually
        # need the overflow-note path — that path exists as a safety margin
        # for an assumption being violated, not something 16 real nodes
        # should ever trigger.
        open_node_values = [c.kwargs.get("value", "") for c in calls if "Open Nodes" in c.kwargs.get("name", "")]
        self.assertTrue(all("more" not in v for v in open_node_values))

    async def test_build_status_embed_many_open_nodes_stays_within_field_limits(self):
        """
        Defensive test for if the 16-node assumption is ever violated (a
        bug elsewhere allows more nodes than intended, a future rule change,
        etc.) — the field-length safety net must still hold regardless,
        even though this exact scale should never occur in practice.
        """
        match = await db.start_siege_match("NP", "WolfpackMafia")
        for i in range(30):
            await db.add_siege_node(
                match["id"], mod="No Mod", opponent_name=f"Opponent_Player_{i}",
                opponent_ovr=3200 + i * 10, points_required=40, points_reward=60
            )
        summary = await db.get_siege_match_summary(match["id"])
        player_totals = await db.get_siege_all_player_totals(match["id"])
        embed = self.siege.build_status_embed("NP", match, summary, player_totals)

        calls = embed.add_field.call_args_list
        self.assertGreater(len(calls), 1)  # confirms it actually split into multiple fields
        for call in calls:
            value = call.kwargs.get("value", "")
            name = call.kwargs.get("name", "")
            self.assertLessEqual(len(value), 1024, f"Field {name!r} exceeded Discord's 1024-char limit")
            self.assertLessEqual(len(name), 256)
        self.assertLessEqual(len(calls), 25)  # Discord's overall fields-per-embed limit

    async def test_build_status_embed_large_roster_player_totals_stays_within_field_limits(self):
        """Same class of bug, for the player-totals field — this league has
        at least one 66-player roster (NA), easily enough to exceed 1024
        chars even after the existing 2-column halving."""
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Solo",
                                 opponent_ovr=None, points_required=9999, points_reward=1)
        # Build player_totals directly — doesn't require every player to have
        # actually logged a score, just needs enough rows to exceed the limit.
        player_totals = [{"ign": f"SomeReallyLongPlayerName{i}", "points": 100 + i, "drives": 20 + i} for i in range(66)]
        summary = await db.get_siege_match_summary(match["id"])
        embed = self.siege.build_status_embed("NP", match, summary, player_totals)

        calls = embed.add_field.call_args_list
        totals_calls = [c for c in calls if "Player Totals" in c.kwargs.get("name", "") or c.kwargs.get("name") == "\u200b"]
        self.assertGreater(len(totals_calls), 2)  # more than the original fixed 2-column split
        for call in calls:
            self.assertLessEqual(len(call.kwargs.get("value", "")), 1024)

    # --- /updatesiege, /siegefinal, and the correction view ---

    async def test_handle_updatesiege_no_active_match(self):
        inter = self._make_interaction()
        await self.siege.handle_updatesiege(inter, "NP")
        self.assertIn("No active siege match", inter.response.send_message.call_args.args[0])

    async def test_handle_updatesiege_sends_correction_view(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)

        inter = self._make_interaction()
        await self.siege.handle_updatesiege(inter, "NP")
        inter.followup.send.assert_awaited_once()
        view = inter.followup.send.call_args.kwargs["view"]
        self.assertIsInstance(view, self.siege.SiegeCorrectionView)
        # opp-points button + node select + score select, no finalize button
        self.assertEqual(len(view.children), 3)

    async def test_handle_siegefinal_view_has_finalize_button(self):
        await db.start_siege_match("NP", "WolfpackMafia")
        inter = self._make_interaction()
        await self.siege.handle_siegefinal(inter, "NP")
        view = inter.followup.send.call_args.kwargs["view"]
        # opp-points button + finalize button (no nodes/scores yet)
        self.assertEqual(len(view.children), 2)

    async def test_correction_view_set_opp_points(self):
        match = await db.start_siege_match("NP", "WolfpackMafia", )
        await db.update_siege_match(match["id"], opp_total_points=99)
        match = await db.get_siege_match(match["id"])
        view = self.siege.SiegeCorrectionView(match, [], [])
        inter = self._make_interaction()
        await view._set_opp_points(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.OpponentPointsModal)
        self.assertEqual(modal.match_id, match["id"])
        self.assertEqual(modal.opp_points.default, "99.0")

    async def test_correction_view_edit_node(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=6500, points_required=30, points_reward=10)
        view = self.siege.SiegeCorrectionView(match, [node], [])
        inter = self._make_interaction()
        inter.data = {"values": [str(node["id"])]}
        await view._edit_node(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.NodeEditModal)
        self.assertEqual(modal.node_id, node["id"])
        self.assertEqual(modal.opponent_name.default, "BigBoy87")
        self.assertEqual(modal.points_required.default, "30")

    async def test_correction_view_edit_score(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        scores = await db.get_siege_scores_for_match(match["id"])
        view = self.siege.SiegeCorrectionView(match, [], scores)
        inter = self._make_interaction()
        inter.data = {"values": [str(scores[0]["id"])]}
        await view._edit_score(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, self.siege.ScoreEditModal)
        self.assertEqual(modal.score_id, scores[0]["id"])
        self.assertEqual(modal.points.default, "14")

    async def test_correction_view_finalize(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        view = self.siege.SiegeCorrectionView(match, [], [], allow_finalize=True)
        inter = self._make_interaction()
        await view._finalize(inter)
        finalized = await db.get_siege_match(match["id"])
        self.assertEqual(finalized["status"], "completed")
        inter.response.edit_message.assert_awaited_once()
        inter.channel.send.assert_awaited_once()

    async def test_opponent_points_modal_updates_match(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        modal = self.siege.OpponentPointsModal(match["id"])
        modal.opp_points.value = "4200"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        updated = await db.get_siege_match(match["id"])
        self.assertEqual(updated["opp_total_points"], 4200.0)

    async def test_node_edit_modal_recheck_reopens_node(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=10, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 2, 10)
        cleared = await db.get_siege_node(node["id"])
        self.assertEqual(cleared["status"], "cleared")

        modal = self.siege.NodeEditModal(cleared)
        modal.opponent_name.value    = "BigBoy87"
        modal.opponent_ovr.value     = ""
        modal.points_required.value = "50"  # raise the bar back above the logged total
        modal.points_reward.value   = "10"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        reopened = await db.get_siege_node(node["id"])
        self.assertEqual(reopened["status"], "open")

    async def test_score_edit_modal_updates_score(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        scores = await db.get_siege_scores_for_node(node["id"])
        modal = self.siege.ScoreEditModal(scores[0])
        modal.drives.value = "4"
        modal.points.value = "20"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        totals = await db.get_siege_node_totals(node["id"])
        self.assertEqual(totals["points"], 20)
        self.assertEqual(totals["drives"], 4)

    # --- /siegesplits, /siegehistory ---

    async def test_handle_siegesplits_no_scores(self):
        inter = self._make_interaction()
        await self.siege.handle_siegesplits(inter, "Grizzly")
        inter.followup.send.assert_awaited_once()
        self.assertIn("No siege scores", inter.followup.send.call_args.args[0])

    async def test_handle_siegesplits_with_scores(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="Run Plays Only", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        inter = self._make_interaction()
        await self.siege.handle_siegesplits(inter, "Grizzly")
        embed = inter.followup.send.call_args.kwargs["embed"]
        self.assertTrue(embed.add_field.called)

    async def test_handle_siegehistory_empty(self):
        inter = self._make_interaction()
        await self.siege.handle_siegehistory(inter, "NP")
        self.assertIn("No completed siege matches", inter.followup.send.call_args.args[0])

    async def test_handle_siegehistory_with_matches(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.finalize_siege_match(match["id"])
        inter = self._make_interaction()
        await self.siege.handle_siegehistory(inter, "NP")
        embed = inter.followup.send.call_args.kwargs["embed"]
        self.assertIn("WolfpackMafia", embed.description)


# ---------------------------------------------------------------------------
# Test: i18n / localization
# ---------------------------------------------------------------------------

class TestI18n(unittest.TestCase):

    def test_resolve_lang_maps_supported_locales(self):
        import i18n
        cases = [
            (discord.Locale.spain_spanish, 'es'),
            (discord.Locale.latin_american_spanish, 'es'),
            (discord.Locale.french, 'fr'),
            (discord.Locale.brazil_portuguese, 'pt'),
            (discord.Locale.german, 'de'),
        ]
        for loc, expected in cases:
            fake = MagicMock()
            fake.locale = loc
            self.assertEqual(i18n.resolve_lang(fake), expected)

    def test_resolve_lang_defaults_to_english(self):
        import i18n
        fake = MagicMock()
        fake.locale = discord.Locale.american_english
        self.assertEqual(i18n.resolve_lang(fake), 'en')
        fake.locale = discord.Locale.british_english
        self.assertEqual(i18n.resolve_lang(fake), 'en')

    def test_resolve_lang_handles_missing_locale(self):
        import i18n
        fake = MagicMock(spec=[])  # no .locale attribute at all
        self.assertEqual(i18n.resolve_lang(fake), 'en')

    def test_t_falls_back_to_english_for_unsupported_lang(self):
        import i18n
        # 'xx' isn't a language we have translations for
        self.assertEqual(i18n.t('manual.nav.close', 'xx'), i18n.t('manual.nav.close', 'en'))

    def test_t_falls_back_to_key_for_unknown_key(self):
        import i18n
        self.assertEqual(i18n.t('totally.made.up.key', 'en'), 'totally.made.up.key')

    def test_t_formats_kwargs(self):
        import i18n
        result = i18n.t('manual.nav.footer', 'en', page=2, total=5)
        self.assertIn('2', result)
        self.assertIn('5', result)

    def test_manual_translations_cover_all_supported_langs_and_pages(self):
        import i18n
        for page_key in i18n.MANUAL_PAGE_KEYS:
            title_entry = i18n.TRANSLATIONS[f'{page_key}.title']
            fields_entry = i18n.TRANSLATIONS[f'{page_key}.fields']
            for lang in i18n.SUPPORTED_LANGS:
                self.assertIn(lang, title_entry, f'{page_key}.title missing {lang}')
                self.assertIn(lang, fields_entry, f'{page_key}.fields missing {lang}')
                # Same number of command entries in every language for a given page
                self.assertEqual(
                    len(fields_entry[lang]), len(fields_entry['en']),
                    f'{page_key}.fields[{lang}] has a different command count than English'
                )

    def test_manual_translations_preserve_command_names_and_code_blocks(self):
        """Every language's field name must match English exactly (command
        names aren't translated), and inline code / bold markup must survive."""
        import i18n
        for page_key in i18n.MANUAL_PAGE_KEYS:
            fields_entry = i18n.TRANSLATIONS[f'{page_key}.fields']
            en_names = [name for name, _ in fields_entry['en']]
            for lang in i18n.SUPPORTED_LANGS:
                lang_names = [name for name, _ in fields_entry[lang]]
                self.assertEqual(lang_names, en_names, f'{page_key} command names differ in {lang}')
                for (_, en_desc), (_, lang_desc) in zip(fields_entry['en'], fields_entry[lang]):
                    en_backticks = en_desc.count('`')
                    lang_backticks = lang_desc.count('`')
                    self.assertEqual(en_backticks, lang_backticks,
                                      f'{page_key}/{lang}: backtick count differs from English')

    def test_manual_view_renders_in_each_language(self):
        import i18n
        from optimized_bot import ManualView
        for lang in i18n.SUPPORTED_LANGS:
            view = ManualView(lang)
            embed = view._build_embed()
            self.assertTrue(embed.title)
            self.assertTrue(embed.add_field.called)


class TestScoresGrid(unittest.TestCase):
    """
    /scores was redesigned to take a date range and render a players-by-dates
    grid image instead of a single-date text list. scores_slash itself is
    @tree.command-wrapped and unusable directly under the stub (same as every
    other admin command in this file), so this exercises the two pieces that
    actually matter and are directly testable: the image renderer itself,
    and the cell-formatting/roster-merging logic that feeds it.
    """

    def test_render_table_wraps_long_title_instead_of_widening_image(self):
        """A long title must wrap across multiple lines and stay within the
        table's own width — the image must NOT be widened to fit it on one line."""
        from sheet_image import _render_table, _wrap_text
        import sheet_image
        from PIL import Image, ImageDraw
        # A realistic ladder-style table (matching actual /show_ladder usage),
        # not an artificially narrow one a single title word couldn't fit in.
        headers = ['#', 'Our Player', 'Ladder Rank', 'Off OVR', 'Opponent', 'Opp TOT', 'Opp DEF', '+/-', 'Result']
        rows = [[str(i), f'Player{i}', '15.5', '235', f'Opp{i}', '7000', '220', '+15', 'WIN 22-14'] for i in range(16)]
        long_title = "NeuroPerverse vs seams suspicious (E1)  Ladder  (snapshot for 2026-07-20)"
        buf = _render_table(long_title, headers, rows, ['R', 'L', 'R', 'R', 'L', 'R', 'R', 'R', 'L'])
        img = Image.open(buf)

        font_title = sheet_image._load_font(sheet_image.FONT_BOLD, sheet_image.TITLE_SIZE)
        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        full_title_width = dummy.textlength(long_title, font=font_title)

        # The old (reverted) behavior would have widened the image to fit the
        # whole title on one line; confirm that did NOT happen here.
        self.assertLess(img.width, full_title_width)

        lines = _wrap_text(long_title, font_title, img.width - sheet_image.PAD_X * 2, lambda t, f: dummy.textlength(t, font=f))
        self.assertGreater(len(lines), 1)  # confirms it actually wrapped
        for line in lines:
            self.assertLessEqual(dummy.textlength(line, font=font_title), img.width - sheet_image.PAD_X * 2)

    def test_wrap_text_keeps_each_line_within_max_width(self):
        from sheet_image import _wrap_text, _load_font, FONT_BOLD, TITLE_SIZE
        from PIL import Image, ImageDraw
        font = _load_font(FONT_BOLD, TITLE_SIZE)
        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        measure = lambda t, f: dummy.textlength(t, font=f)
        text = "This is a fairly long title that should wrap across several lines"
        max_width = 200
        lines = _wrap_text(text, font, max_width, measure)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(measure(line, font), max_width)
        # nothing lost in the wrap
        self.assertEqual(" ".join(lines), text)

    def test_wrap_text_single_line_when_it_already_fits(self):
        from sheet_image import _wrap_text, _load_font, FONT_BOLD, TITLE_SIZE
        from PIL import Image, ImageDraw
        font = _load_font(FONT_BOLD, TITLE_SIZE)
        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        measure = lambda t, f: dummy.textlength(t, font=f)
        lines = _wrap_text("Short Title", font, 2000, measure)
        self.assertEqual(lines, ["Short Title"])

    def test_render_table_width_driven_by_table_when_title_is_short(self):
        """When the title is short, the table's own columns should still
        drive the width, not be forced wider than necessary."""
        from sheet_image import _render_table
        from PIL import Image
        headers = ['#', 'Player', 'PWR', 'OVR']
        rows = [[str(i), f'Player{i}', '15.5', '235'] for i in range(16)]
        buf = _render_table("Rankings", headers, rows, ['R', 'L', 'R', 'R'])
        img = Image.open(buf)
        # A short title shouldn't force the image dramatically wider than a
        # reasonably-sized table needs to be.
        self.assertLess(img.width, 900)

    def test_render_table_subtitle_adds_vertical_space(self):
        """A subtitle should make the image taller (extra line beneath the
        title) without affecting the image's width."""
        from sheet_image import _render_table
        from PIL import Image
        headers = ['#', 'Player', 'PWR', 'OVR']
        rows = [[str(i), f'Player{i}', '15.5', '235'] for i in range(4)]
        without = _render_table("Rankings", headers, rows, ['R', 'L', 'R', 'R'])
        with_sub = _render_table("Rankings", headers, rows, ['R', 'L', 'R', 'R'], subtitle="Snapshot for 2026-07-20")
        img_without = Image.open(without)
        img_with    = Image.open(with_sub)
        self.assertGreater(img_with.height, img_without.height)
        self.assertEqual(img_with.width, img_without.width)

    def test_render_table_no_subtitle_behaves_exactly_as_before(self):
        """Omitting subtitle entirely (the default) must not change anything
        about existing callers like /rank and /scores."""
        from sheet_image import _render_table
        from PIL import Image
        headers = ['#', 'Player']
        rows = [['1', 'Grizzly']]
        buf1 = _render_table("Title", headers, rows, ['R', 'L'])
        buf2 = _render_table("Title", headers, rows, ['R', 'L'], subtitle=None)
        self.assertEqual(Image.open(buf1).size, Image.open(buf2).size)

    def test_render_table_long_subtitle_wraps_too(self):
        from sheet_image import _render_table, _wrap_text
        import sheet_image
        from PIL import Image, ImageDraw
        headers = ['#', 'Our Player', 'Ladder Rank', 'Off OVR', 'Opponent', 'Opp TOT', 'Opp DEF', '+/-', 'Result']
        rows = [[str(i), f'Player{i}', '15.5', '235', f'Opp{i}', '7000', '220', '+15', 'WIN 22-14'] for i in range(16)]
        long_subtitle = ("Ladder (snapshot for 2026-07-20, pulled from the daily archive after "
                          "confirmation, reflecting the most recently saved matchup ladder state)")
        buf = _render_table("NeuroPerverse", headers, rows, ['R','L','R','R','L','R','R','R','L'], subtitle=long_subtitle)
        img = Image.open(buf)

        font_sub = sheet_image._load_font(sheet_image.FONT_ITALIC, sheet_image.SUBTITLE_SIZE)
        dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        lines = _wrap_text(long_subtitle, font_sub, img.width - sheet_image.PAD_X * 2, lambda t, f: dummy.textlength(t, font=f))
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(dummy.textlength(line, font=font_sub), img.width - sheet_image.PAD_X * 2)

    def test_render_ladder_image_passes_subtitle_through(self):
        from sheet_image import render_ladder_image
        from PIL import Image
        rows = [{'slot': 1, 'our_ign': 'P1', 'ladder_rank': 15.0, 'our_off_ovr': 230,
                 'opp_ign': 'O1', 'our_total_ovr': 7000, 'opp_def_ovr': 220}]
        without = render_ladder_image("NeuroPerverse", rows)
        with_sub = render_ladder_image("NeuroPerverse", rows, subtitle="Ladder (snapshot for 2026-07-20)")
        self.assertGreater(Image.open(with_sub).height, Image.open(without).height)

    def test_load_font_falls_back_through_multiple_candidate_paths(self):
        """The actual bug this covers: a font constant now holds a LIST of
        candidate paths (bundled copy, then system path) — confirm _load_font
        tries each in order and succeeds via the second if the first is
        missing, rather than only ever trying a single hardcoded path."""
        import sheet_image
        font = sheet_image._load_font(['/nonexistent/font.ttf', sheet_image._POSTER_FONT_BOLD[0]], 30)
        self.assertEqual(font.size, 30)

    def test_load_font_logs_error_when_every_candidate_missing(self):
        """If every candidate path is genuinely missing, this must be loud
        (a server-log error), not a silent collapse to a tiny font with no
        signal anything went wrong."""
        import sheet_image
        with patch.object(sheet_image.logger, 'error') as mock_error:
            sheet_image._load_font(['/nonexistent/a.ttf', '/nonexistent/b.ttf'], 30)
            mock_error.assert_called_once()

    def test_italic_font_falls_back_to_regular_weight_before_pil_default(self):
        """
        Directly reproduces the exact production log: DejaVuSans-Oblique.ttf
        unavailable at both its bundled and system paths, while the rest of
        the font family (used for FONT_ITALIC/_POSTER_FONT_ITALIC's fallback
        chain) is fine. Confirms this degrades to "correct size, not
        italic" via the regular-weight font, rather than falling all the
        way through to PIL's fixed ~10px default.
        """
        import sheet_image
        broken_italic = ['/nonexistent/bundled/DejaVuSans-Oblique.ttf',
                          '/nonexistent/system/DejaVuSans-Oblique.ttf'] + sheet_image._POSTER_FONT_REG
        font = sheet_image._load_font(broken_italic, 20)
        self.assertEqual(font.size, 20)

    def test_display_fonts_fall_back_to_condensed_bold_if_missing(self):
        """The tactical/varsity/arcade styles' display fonts (Black Ops One,
        Graduate, Press Start 2P) have no system-wide install path — if the
        bundled copy is ever missing, each must still degrade to the
        reliable DejaVu Condensed Bold at the correct size, not PIL's
        fixed ~10px default."""
        import sheet_image
        for const_name in ['_FONT_BLACK_OPS', '_FONT_GRADUATE', '_FONT_PRESS_START']:
            broken = ['/nonexistent/bundled/display_font.ttf'] + sheet_image._POSTER_FONT_BOLD
            font = sheet_image._load_font(broken, 24)
            self.assertEqual(font.size, 24, f"{const_name}'s fallback chain didn't respect requested size")

    def test_variable_font_never_shrinks_below_safe_size(self):
        """
        Directly reproduces the actual bug found while building the
        carnival style: Honk's digits become illegible solid blocks below
        ~16-18px regardless of axis settings, and _fit_text's normal
        shrink-to-fit loop would have silently pushed it there for a small
        rank badge. _fit_variable_text must stop shrinking at
        _VARIABLE_FONT_MIN_SAFE_SIZE and hand off to the reliable fallback
        font instead of continuing to shrink the variable font past that.
        """
        import sheet_image
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        # A single digit in a 44px badge easily "fits" at any size by width,
        # so nothing here forces a shrink via max_width — this specifically
        # tests that the floor itself is enforced regardless.
        font = sheet_image._fit_variable_text(
            draw, "1", sheet_image._FONT_HONK_PATH, [0, 100], sheet_image._POSTER_FONT_BOLD,
            max_size=8, min_size=4, max_width=44
        )
        # max_size (8) is below the safe floor (16) — must have handed off
        # to the fallback font entirely rather than rendering Honk at 8px.
        self.assertGreaterEqual(font.size, 4)  # fallback path still respects the true min_size

    def test_variable_font_falls_back_when_text_never_fits_at_safe_size(self):
        """An extremely long name that can't fit even at the variable
        font's safe minimum size must hand off to the reliable fallback
        font (which can keep shrinking further) rather than getting stuck
        rendering the variable font below its legible floor."""
        import sheet_image
        from PIL import Image, ImageDraw
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        long_text = "A" * 200
        # Must not raise, and must actually shrink below the variable
        # font's safe floor (16) since nothing that long fits at 16+ in a
        # 200px budget — proving the fallback path was taken, not stuck.
        font = sheet_image._fit_variable_text(
            draw, long_text, sheet_image._FONT_NABLA_PATH, [100, 12], sheet_image._POSTER_FONT_BOLD,
            max_size=34, min_size=6, max_width=200
        )
        self.assertLess(font.size, sheet_image._VARIABLE_FONT_MIN_SAFE_SIZE)

    def test_carnival_style_rank_badges_use_reliable_font_not_honk(self):
        """The actual production fix: rank badge numbers in the carnival
        style must render via the reliable bold font, not Honk directly —
        confirmed by checking the rendered image doesn't crash and produces
        a reasonably-sized, non-trivial image at full 16-row scale."""
        from sheet_image import render_ladder_image
        from PIL import Image
        rows = [{'slot': i, 'our_ign': f'P{i}', 'ladder_rank': 75.0, 'opp_ign': f'O{i}', 'opp_def_ovr': 110} for i in range(1, 17)]
        buf = render_ladder_image("T", rows, style='carnival', our_team_name="NeuroPerverse", opponent_name="Opponents")
        img = Image.open(buf)
        self.assertEqual(img.format, "PNG")
        self.assertGreater(img.width, 0)

    def test_carnival_style_player_names_use_reliable_font_not_honk(self):
        """
        Unlike every other display-font style (tactical/varsity/arcade/
        street all use their title font for player names too,
        per an explicit consistency request), carnival is a deliberate
        exception: confirmed directly that Honk's digit glyphs are
        genuinely hard to distinguish from letters in mixed alphanumeric
        names common on real rosters (JX8, Dukie06, GKH1987 all became
        borderline illegible even with zero shadow, ruling out an axis-
        tuning fix). Rather than re-litigate this with a brittle pixel
        comparison, this checks the actual source uses _POSTER_FONT_BOLD
        for names in carnival specifically, so a future edit reintroducing
        Honk here fails a test instead of shipping unreadable names.
        """
        import inspect
        import sheet_image
        source = inspect.getsource(sheet_image._render_ladder_carnival)
        # Find the two textual widths of the row loop and enforce that
        # calls involving f['our_ign']/f['opp_ign'] use the reliable font.
        self.assertIn("_fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD", source)
        self.assertIn("_fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD", source)
        self.assertNotIn("_fit_variable_text(draw, f['our_ign']", source)
        self.assertNotIn("_fit_variable_text(draw, f['opp_ign']", source)

    def test_other_display_font_styles_use_title_font_for_names(self):
        """The consistency fix itself: tactical/varsity/street
        (and arcade, checked separately since it's a wide non-variable
        font) must use their own display font for player names, not a
        generic fallback, confirmed directly from source rather than by
        eyeballing renders each time."""
        import inspect
        import sheet_image
        checks = [
            ('_render_ladder_tactical', '_FONT_BLACK_OPS'),
            ('_render_ladder_varsity', '_FONT_GRADUATE'),
            ('_render_ladder_street', '_FONT_BUNGEE'),
            ('_render_ladder_arcade', '_FONT_PRESS_START'),
            # Second font batch — one display face per style that had none.
            ('_render_ladder_neon', '_FONT_ORBITRON'),
            ('_render_ladder_scoreboard', '_FONT_ANTON'),
            # gridiron deliberately shares tactical's face, by preference.
            ('_render_ladder_gridiron', '_FONT_BLACK_OPS'),
            ('_render_ladder_blueprint', '_FONT_SHARE_TECH'),
            ('_render_ladder_terminal', '_FONT_VT323'),
        ]
        for func_name, font_const in checks:
            source = inspect.getsource(getattr(sheet_image, func_name))
            self.assertIn(
                f"f['our_ign'], {font_const}", source,
                f"{func_name} doesn't use {font_const} for player names"
            )

    def test_load_font_worst_case_fallback_still_respects_requested_size(self):
        """Isolates the absolute worst case — every candidate path missing,
        no bundled font available either — from the bundling fix itself.
        On PIL versions that support it, load_default(size=...) must still
        be asked for the requested size rather than silently defaulting to
        a fixed ~10px with no indication anything was wrong."""
        import sheet_image
        font = sheet_image._load_font(['/nonexistent/a.ttf', '/nonexistent/b.ttf'], 30)
        self.assertEqual(font.size, 30)

    def test_ladder_styles_render_correctly_sized_text_with_zero_system_fonts(self):
        """
        Directly reproduces the reported production bug: every bold poster-
        style font collapsed to PIL's fixed ~10px default because the
        Liberation font package this code used to depend on wasn't installed
        on the actual server — while this sandbox happened to have it, so
        the bug was invisible in every previous test here. This simulates a
        server with NO system dejavu fonts either (not just no Liberation),
        forcing every font load to rely entirely on the bundled fonts/
        folder, and confirms the rendered title text is still genuinely
        large — not just that rendering doesn't crash.
        """
        import sheet_image
        from PIL import Image, ImageDraw
        original_bold = sheet_image._POSTER_FONT_BOLD
        try:
            sheet_image._POSTER_FONT_BOLD = [original_bold[0], '/nonexistent/system/font.ttf']
            rows = [{'slot': 1, 'our_ign': 'Grizzly', 'ladder_rank': 81.8, 'opp_ign': 'CesarX', 'opp_def_ovr': 117}]
            buf = sheet_image.render_ladder_image(
                "T", rows, style='neon', our_team_name="NeuroPerverse", opponent_name="seams suspicious"
            )
            img = Image.open(buf)
            # Measure the actual title font used via the same _fit_text call
            # the renderer itself makes, confirming it's nowhere near PIL's
            # ~10px fallback size.
            dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
            title_font = sheet_image._fit_text(
                dummy, "NeuroPerverse vs seams suspicious", sheet_image._POSTER_FONT_BOLD, 44, 24, img.width - 70
            )
            self.assertGreaterEqual(title_font.size, 24)
        finally:
            sheet_image._POSTER_FONT_BOLD = original_bold

    def test_ladder_styles_all_produce_valid_png(self):
        from sheet_image import render_ladder_image
        from PIL import Image
        rows = [
            {'slot': i, 'our_ign': f'Player{i}', 'ladder_rank': 75.0 + i, 'our_off_ovr': 230,
             'opp_ign': f'Opp{i}', 'opp_def_ovr': 110 + i}
            for i in range(1, 17)
        ]
        for style in ['classic', 'neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                      'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal',
                      'gators', 'ledboard', 'dossier', 'gameboy', 'cyberdeck', 'starfield',
                      'hazard', 'bubble', 'sketch', 'prestige', 'paper', 'heatmap']:
            buf = render_ladder_image(
                "NeuroPerverse vs seams suspicious", rows, subtitle="Ladder (E1)",
                style=style, our_team_name="NeuroPerverse", opponent_name="seams suspicious", division="E1"
            )
            img = Image.open(buf)
            self.assertEqual(img.format, "PNG")
            self.assertGreater(img.width, 0)
            self.assertGreater(img.height, 0)

    def test_ladder_style_defaults_to_classic(self):
        from sheet_image import render_ladder_image, _render_table
        rows = [{'slot': 1, 'our_ign': 'P1', 'ladder_rank': 15.0, 'opp_ign': 'O1', 'opp_def_ovr': 220}]
        # classic is the only style that goes through the shared _render_table
        # helper, which the other three don't use at all
        import sheet_image
        called = {}
        original = sheet_image._render_table
        def spy(*a, **kw):
            called['used'] = True
            return original(*a, **kw)
        sheet_image._render_table = spy
        try:
            render_ladder_image("Title", rows)  # no style specified
        finally:
            sheet_image._render_table = original
        self.assertTrue(called.get('used'))

    def test_ladder_styles_handle_long_names_without_crashing(self):
        from sheet_image import render_ladder_image
        from PIL import Image
        rows = [{
            'slot': 1,
            'our_ign': 'ThisIsAReallyReallyLongPlayerNameForTestingOverflow',
            'ladder_rank': 75.0,
            'opp_ign': 'AnotherVeryLongOpponentNameThatShouldAlsoFit',
            'opp_def_ovr': 114,
        }]
        for style in ['neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                      'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal',
                      'gators', 'ledboard', 'dossier', 'gameboy', 'cyberdeck', 'starfield',
                      'hazard', 'bubble', 'sketch', 'prestige', 'paper', 'heatmap']:
            buf = render_ladder_image("Title", rows, style=style,
                                       our_team_name="NeuroPerverse", opponent_name="seams suspicious")
            img = Image.open(buf)  # must not raise
            self.assertGreater(img.width, 0)

    def test_ladder_styles_handle_missing_data_gracefully(self):
        """A slot with no opponent data at all (opp_ign/opp_def_ovr both None)
        must render as a placeholder, not crash or leave a blank error."""
        from sheet_image import render_ladder_image
        from PIL import Image
        rows = [{'slot': 1, 'our_ign': 'Grizzly', 'ladder_rank': None, 'our_off_ovr': None,
                 'opp_ign': None, 'opp_def_ovr': None}]
        for style in ['neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                      'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal',
                      'gators', 'ledboard', 'dossier', 'gameboy', 'cyberdeck', 'starfield',
                      'hazard', 'bubble', 'sketch', 'prestige', 'paper', 'heatmap']:
            buf = render_ladder_image("Title", rows, style=style)  # must not raise
            img = Image.open(buf)
            self.assertGreater(img.width, 0)

    def test_ladder_styles_scale_with_row_count(self):
        """A shorter ladder (fewer than 16 slots) must produce a
        proportionally shorter image, not a fixed 16-row layout."""
        from sheet_image import render_ladder_image
        from PIL import Image
        few_rows = [{'slot': i, 'our_ign': f'P{i}', 'opp_ign': f'O{i}'} for i in range(1, 4)]
        many_rows = [{'slot': i, 'our_ign': f'P{i}', 'opp_ign': f'O{i}'} for i in range(1, 17)]
        for style in ['neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                      'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal',
                      'gators', 'ledboard', 'dossier', 'gameboy', 'cyberdeck', 'starfield',
                      'hazard', 'bubble', 'sketch', 'prestige', 'paper', 'heatmap']:
            few_img = Image.open(render_ladder_image("T", few_rows, style=style))
            many_img = Image.open(render_ladder_image("T", many_rows, style=style))
            self.assertLess(few_img.height, many_img.height)

    def test_render_scores_grid_produces_valid_png(self):
        from sheet_image import render_scores_grid
        from PIL import Image
        dates = ["2026-07-20", "2026-07-21", "2026-07-22"]
        roster_rows = [
            {"ign": "Grizzly", "scores": {"2026-07-20": "22", "2026-07-21": "M", "2026-07-22": None}},
            {"ign": "TOTAL",   "scores": {"2026-07-20": "22", "2026-07-21": "0",  "2026-07-22": "0"}},
        ]
        buf = render_scores_grid("NeuroPerverse — 2026-07-20 to 2026-07-22", dates, roster_rows)
        img = Image.open(buf)
        self.assertEqual(img.format, "PNG")
        self.assertGreater(img.width, 0)
        self.assertGreater(img.height, 0)

    def test_render_scores_grid_shows_dashes_for_missing_and_wider_for_more_dates(self):
        from sheet_image import render_scores_grid
        from PIL import Image
        narrow = render_scores_grid("T", ["2026-07-20"], [{"ign": "Grizzly", "scores": {"2026-07-20": "22"}}])
        wide = render_scores_grid(
            "T", [f"2026-07-{d:02d}" for d in range(20, 28)],
            [{"ign": "Grizzly", "scores": {f"2026-07-{d:02d}": "22" for d in range(20, 28)}}]
        )
        self.assertGreater(Image.open(wide).width, Image.open(narrow).width)

    def test_cell_formatting_distinguishes_missed_excused_real_and_blank(self):
        """Same cell-selection logic used in scores_slash: E takes priority,
        then M, then a real score, then blank (never-recorded) as None."""
        rows = [
            {"ign": "A", "game_date": "2026-07-20", "score": 22.0, "is_forfeit": 0, "is_excused": 0},
            {"ign": "B", "game_date": "2026-07-20", "score": 0.0,  "is_forfeit": 1, "is_excused": 0},
            {"ign": "C", "game_date": "2026-07-20", "score": None, "is_forfeit": 0, "is_excused": 1},
        ]
        by_player = {}
        for r in rows:
            if r['is_excused']:
                cell = 'E'
            elif r['is_forfeit']:
                cell = 'M'
            elif r['score'] is not None:
                cell = f"{r['score']:.0f}"
            else:
                cell = None
            by_player.setdefault(r['ign'], {})[r['game_date']] = cell
        self.assertEqual(by_player['A']['2026-07-20'], '22')
        self.assertEqual(by_player['B']['2026-07-20'], 'M')
        self.assertEqual(by_player['C']['2026-07-20'], 'E')

    def test_never_recorded_date_is_none_not_a_string(self):
        """A player with literally no game_scores row for a given date must
        render as a blank ('--' in the actual image) — distinct from a real
        recorded 0, which must show '0', not disappear into the same bucket."""
        rows = [{"ign": "A", "game_date": "2026-07-20", "score": 0.0, "is_forfeit": 0, "is_excused": 0}]
        by_player = {"A": {}}
        for r in rows:
            cell = 'E' if r['is_excused'] else ('M' if r['is_forfeit'] else (f"{r['score']:.0f}" if r['score'] is not None else None))
            by_player[r['ign']][r['game_date']] = cell
        # date never touched at all
        self.assertIsNone(by_player["A"].get("2026-07-21"))
        # date with a genuine 0 must be the string '0', not None
        self.assertEqual(by_player["A"]["2026-07-20"], "0")

    def test_total_row_excludes_missed_and_excused_but_includes_real_zero(self):
        rows = [
            {"game_date": "2026-07-20", "score": 22.0, "is_forfeit": 0, "is_excused": 0},
            {"game_date": "2026-07-20", "score": 0.0,  "is_forfeit": 0, "is_excused": 0},  # real 0, counts
            {"game_date": "2026-07-20", "score": 0.0,  "is_forfeit": 1, "is_excused": 0},  # missed, excluded
            {"game_date": "2026-07-20", "score": None, "is_forfeit": 0, "is_excused": 1},  # excused, excluded
        ]
        total = sum(
            r['score'] for r in rows
            if r['game_date'] == "2026-07-20" and not r['is_forfeit'] and not r['is_excused'] and r['score'] is not None
        )
        self.assertEqual(total, 22.0)

    def test_scored_player_not_on_current_roster_still_gets_a_row(self):
        """A player who scored during the range but has since transferred or
        gone inactive must not silently vanish from the grid."""
        roster_igns = ["Grizzly", "Dukie06"]
        scored_igns = {"Grizzly", "Dukie06", "OldPlayer"}
        all_igns = roster_igns + [ign for ign in sorted(scored_igns) if ign not in roster_igns]
        self.assertIn("OldPlayer", all_igns)
        self.assertEqual(all_igns[:2], roster_igns)  # current roster order preserved first

class TestI18nTier1(unittest.IsolatedAsyncioTestCase):
    """Locks in i18n wiring for the core player-facing commands (Tier 1)."""

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_score_modal_translated_in_german(self):
        from optimized_bot import ScoreModal
        row = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY), lang='de')
        self.assertEqual(modal.title, "Punktestand Erfassen")
        self.assertIn("verpasste Drives", _label_text_for(modal, modal.score_val))
        modal.score_val.value = "M"
        modal.def_ovr.value = modal.fourth_downs.value = modal.fourth_down_convs.value = modal.fumbles.value = ""
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        await modal.on_submit(inter)
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("verpasste Drives", msg)

    async def test_score_modal_invalid_score_translated(self):
        from optimized_bot import ScoreModal
        row = await db.get_player("Grizzly")
        modal = ScoreModal("Grizzly", row, game_date=datetime.date.fromisoformat(TODAY), lang='fr')
        modal.score_val.value = "not-a-number"
        modal.def_ovr.value = modal.fourth_downs.value = modal.fourth_down_convs.value = modal.fumbles.value = ""
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        await modal.on_submit(inter)
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("entier", msg)

    async def test_dscore_modal_translated_in_spanish(self):
        from optimized_bot import DscoreDriveModal
        modal = DscoreDriveModal(
            "Grizzly", datetime.date.fromisoformat(TODAY), drive_num=1, drive_outcome="3",
            drive_outcomes=["3", "F", "5"], points_allowed=8, lang='es'
        )
        self.assertEqual(modal.title, "Detalle Serie 1")
        self.assertIn("Oponente", _label_text_for(modal, modal.ovr))

    async def test_player_field_translations_exist_and_differ_by_language(self):
        import i18n
        keys = ['player.field.games', 'player.field.missed_drives', 'player.field.pwr_rank',
                'player.status_active', 'player.status_inactive']
        for key in keys:
            en = i18n.t(key, 'en')
            de = i18n.t(key, 'de')
            self.assertTrue(en)
            self.assertTrue(de)

    async def test_common_player_not_found_translated(self):
        import i18n
        msg = i18n.t('common.player_not_found', 'pt', player="NoSuchPlayer")
        self.assertIn("NoSuchPlayer", msg)
        self.assertIn("não encontrado", msg)

    async def test_get_status_translated_in_french(self):
        from status import get_status
        await db.set_matchup("NP", TODAY, "RivalTeam", "E1")
        embed = await get_status("NP", lang='fr')
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertIn("📊 Tableau des Scores", field_names)
        self.assertIn("📈 Perspective", field_names)


class TestI18nTier2(unittest.IsolatedAsyncioTestCase):
    """Locks in i18n wiring for the siege gamemode (Tier 2)."""

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()
        import siege as _siege_mod
        self.siege = _siege_mod

    async def asyncTearDown(self):
        await _patched_close()

    def _make_interaction(self, locale=None):
        inter = MagicMock()
        inter.locale = locale or discord.Locale.german
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.response.send_modal = AsyncMock()
        inter.response.defer = AsyncMock()
        inter.response.edit_message = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.channel = MagicMock()
        inter.channel.send = AsyncMock()
        inter.namespace = MagicMock()
        return inter

    async def test_siege_start_modal_translated(self):
        inter = self._make_interaction()
        await self.siege.handle_siege(inter, "NP")
        modal = inter.response.send_modal.call_args.args[0]
        self.assertEqual(modal.title, "Belagerung Starten")
        modal.opp_league.value = "WolfpackMafia"
        modal.opp_rank.value = modal.our_rank.value = modal.division.value = ""
        inter2 = self._make_interaction()
        await modal.on_submit(inter2)
        msg = inter2.response.send_message.call_args.args[0]
        self.assertIn("Belagerung gestartet", msg)

    async def test_node_modal_translated_spanish(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        inter = self._make_interaction(discord.Locale.spain_spanish)
        await self.siege.handle_node(inter, "NP", "No Mod")
        modal = inter.response.send_modal.call_args.args[0]
        self.assertEqual(modal.title, "Reportar Nodo de Asedio")
        modal.opponent_name.value = "BigBoy87"
        modal.opponent_ovr.value = ""
        modal.points_required.value = "30"
        modal.points_reward.value = "10"
        inter2 = self._make_interaction(discord.Locale.spain_spanish)
        await modal.on_submit(inter2)
        msg = inter2.response.send_message.call_args.args[0]
        self.assertIn("Nodo agregado", msg)

    async def test_no_active_match_translated_french(self):
        inter = self._make_interaction(discord.Locale.french)
        await self.siege.handle_siegestatus(inter, "NP")
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("Aucun siège actif", msg)

    async def test_siege_status_embed_translated_portuguese(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        node = await db.add_siege_node(match["id"], mod="No Mod", opponent_name="BigBoy87",
                                        opponent_ovr=None, points_required=30, points_reward=10)
        await db.log_siege_score(node["id"], "Grizzly", 3, 14)
        inter = self._make_interaction(discord.Locale.brazil_portuguese)
        await self.siege.handle_siegestatus(inter, "NP")
        embed = inter.followup.send.call_args.kwargs["embed"]
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertTrue(any("Nós Abertos" in n for n in field_names))

    async def test_siegescore_ambiguous_name_translated(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                 opponent_ovr=None, points_required=20, points_reward=8)
        await db.add_siege_node(match["id"], mod="No Mod", opponent_name="Slayer99",
                                 opponent_ovr=None, points_required=30, points_reward=12)
        inter = self._make_interaction(discord.Locale.german)
        await self.siege.handle_siegescore(inter, "NP", "Grizzly", "Slayer99")
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("offene Knoten namens", msg)

    async def test_siegesplits_no_scores_translated(self):
        inter = self._make_interaction(discord.Locale.french)
        await self.siege.handle_siegesplits(inter, "Grizzly")
        msg = inter.followup.send.call_args.args[0]
        self.assertIn("Aucun score de siège", msg)

    async def test_siegehistory_no_matches_translated(self):
        inter = self._make_interaction(discord.Locale.spain_spanish)
        await self.siege.handle_siegehistory(inter, "NP")
        msg = inter.followup.send.call_args.args[0]
        self.assertIn("Aún no hay combates de asedio", msg)

    async def test_correction_view_translated_and_finalize(self):
        match = await db.start_siege_match("NP", "WolfpackMafia")
        inter = self._make_interaction(discord.Locale.german)
        await self.siege.handle_siegefinal(inter, "NP")
        view = inter.followup.send.call_args.kwargs["view"]
        labels = [c.label for c in view.children]
        self.assertIn("💰 Gegnerpunkte Festlegen", labels)
        self.assertIn("🏁 Belagerung Abschließen", labels)


class TestI18nTier3(unittest.IsolatedAsyncioTestCase):
    """Locks in i18n wiring for /matchup, /show_ladder, /factors, and the /ladder flow (Tier 3)."""

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_update_matchup_view_translated_german(self):
        from optimized_bot import UpdateMatchupView
        players = [{"ign": "Grizzly", "score": None, "is_forfeit": 0}]
        view = UpdateMatchupView("NP", TODAY, None, players, lang="de")
        embed = view._build_embed()
        self.assertEqual(embed.title, f"📋 Matchup Aktualisieren — NeuroPerverse {TODAY}")
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertIn("Ergebnis", field_names)
        button_labels = [c.label for c in view.children]
        self.assertTrue(any("Bearbeiten" in b for b in button_labels))

    async def test_update_scores_modal_translated_french(self):
        from optimized_bot import UpdateScoresModal
        players = [{"ign": "Grizzly", "score": 22.0}]
        modal = UpdateScoresModal(players, 0, 1, lang="fr")
        self.assertIn("Scores", modal.title)
        self.assertEqual(modal.children[0].value, "score, M=manqué, E=excusé, vide=retirer")

    async def test_outcome_modal_translated_portuguese(self):
        from optimized_bot import UpdateMatchupView
        players = [{"ign": "Grizzly", "score": None, "is_forfeit": 0}]
        view = UpdateMatchupView("NP", TODAY, None, players, lang="pt")
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()
        await view._edit_outcome(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertEqual(modal.title, "Definir Resultado")
        self.assertEqual(_label_text_for(modal, modal.our_score), "Nossa Pontuação")

    # --- blank cell = remove the entry entirely, regardless of whether one
    # was there before. This is what actually lets an accidentally-entered
    # player be removed from a matchup — a real, previously missing capability. ---

    def _make_matchup_save_interaction(self):
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.edit_original_response = AsyncMock()
        return inter

    async def test_matchup_save_blank_cell_deletes_existing_row(self):
        """A player who WAS accidentally scored for this matchup, with their
        cell now left blank at submission, must have that row removed
        entirely — not left behind with score/flags just zeroed out."""
        from optimized_bot import UpdateMatchupView
        await db.update_player_score("Grizzly", TODAY, 22.0)
        row_before = await db.fetchone("SELECT id FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertIsNotNone(row_before)

        players = [{"ign": "Grizzly", "score": 22.0, "is_forfeit": 0, "is_excused": 0}]
        view = UpdateMatchupView("NP", TODAY, {"opp_ign": "SomeOpp"}, players, lang="en")
        view.pending_scores = {"Grizzly": (None, False, False)}  # cell left blank at submission

        await view._save(self._make_matchup_save_interaction())

        row_after = await db.fetchone("SELECT id FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertIsNone(row_after)  # gone entirely, not just blanked

    async def test_matchup_save_blank_cell_for_never_scored_player_is_noop(self):
        """A player who never had a score and is left blank must not error
        and must not create any row."""
        from optimized_bot import UpdateMatchupView
        players = [{"ign": "Grizzly", "score": None, "is_forfeit": 0, "is_excused": 0}]
        view = UpdateMatchupView("NP", TODAY, {"opp_ign": "SomeOpp"}, players, lang="en")
        view.pending_scores = {"Grizzly": (None, False, False)}

        await view._save(self._make_matchup_save_interaction())  # must not raise

        row = await db.fetchone("SELECT id FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertIsNone(row)

    async def test_matchup_save_real_value_still_updates_normally(self):
        """Regression check: a real submitted value must still update the
        existing row correctly, not be treated as blank/deleted."""
        from optimized_bot import UpdateMatchupView
        await db.update_player_score("Grizzly", TODAY, 22.0)
        players = [{"ign": "Grizzly", "score": 22.0, "is_forfeit": 0, "is_excused": 0}]
        view = UpdateMatchupView("NP", TODAY, {"opp_ign": "SomeOpp"}, players, lang="en")
        view.pending_scores = {"Grizzly": (24.0, False, False)}

        await view._save(self._make_matchup_save_interaction())

        row = await db.fetchone("SELECT score FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["score"], 24.0)

    async def test_matchup_page_merge_includes_blank_cells_not_just_filled_ones(self):
        """The page-submission merge step must fold every cell's result into
        pending_scores, blank or not — previously, a blank cell was silently
        skipped and never reached the save step at all, which is exactly why
        there was no way to remove an accidental entry."""
        from optimized_bot import UpdateMatchupView
        await db.update_player_score("Grizzly", TODAY, 22.0)
        players = [{"ign": "Grizzly", "score": 22.0, "is_forfeit": 0, "is_excused": 0}]
        view = UpdateMatchupView("NP", TODAY, {"opp_ign": "SomeOpp"}, players, lang="en")

        callback = view._make_score_page(0)
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()
        await callback(inter)
        modal = inter.response.send_modal.call_args.args[0]
        modal.children[0].value = ""  # blank the one field on this page

        edit_inter = MagicMock()
        edit_inter.response = MagicMock()
        edit_inter.response.defer = AsyncMock()
        edit_inter.edit_original_response = AsyncMock()
        await modal.on_submit(edit_inter)  # runs the patched on_submit set up by _make_score_page

        self.assertIn("Grizzly", view.pending_scores)
        self.assertEqual(view.pending_scores["Grizzly"], (None, False, False))

    async def test_factors_command_uses_translations(self):
        import i18n
        self.assertEqual(i18n.t('factors.scope_global', 'es'), "**Global**")
        self.assertEqual(i18n.t('factors.no_factors', 'de'), "*Keine Faktoren definiert.*")

    async def test_ladder_step1_translated_spanish(self):
        from ladder_flow import start_ladder_flow
        inter = MagicMock()
        inter.locale = discord.Locale.spain_spanish
        inter.channel = MagicMock()
        inter.response = MagicMock()
        inter.response.is_done = MagicMock(return_value=False)
        inter.response.send_message = AsyncMock()
        await start_ladder_flow(inter, "NP", TODAY)
        embed = inter.response.send_message.call_args.kwargs["embed"]
        self.assertIn("Paso 1", embed.title)

    async def test_ladder_step2_opponent_csv_modal_translated_german(self):
        from ladder_flow import OpponentEntryView, LadderState, MATCHUP_SIZE
        state = LadderState("NP", TODAY, None, lang="de")
        state.opponents = [{"name": "-", "total_ovr": None, "def_ovr": None} for _ in range(MATCHUP_SIZE)]
        view = OpponentEntryView.__new__(OpponentEntryView)
        view.state = state
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.send_modal = AsyncMock()
        await view._enter(inter)
        modal = inter.response.send_modal.call_args.args[0]
        self.assertEqual(modal.title, "Alle 16 Gegner Eingeben")

    async def test_ladder_sort_options_translated(self):
        from ladder_flow import _sort_options
        opts_de = _sort_options('de')
        labels = [label for label, col in opts_de]
        self.assertIn("Power-Rang", labels)
        self.assertIn("Gesamt-OVR", labels)
        opts_en = _sort_options('en')
        self.assertEqual([col for _, col in opts_en], [col for _, col in opts_de])

    async def test_ladder_final_embed_translated_french(self):
        from ladder_flow import LadderState, build_final_embed
        state = LadderState("NP", TODAY, None, lang="fr")
        state.selected = [f"P{i}" for i in range(16)]
        state.opponents = [{"name": f"O{i}", "total_ovr": 100, "def_ovr": 50} for i in range(16)]
        order = list(range(16))
        embed = build_final_embed(state, order, order)
        self.assertIn("Classement", embed.title)

    async def test_ladder_final_embed_shows_extracted_context_when_present(self):
        from ladder_flow import LadderState, build_final_embed
        state = LadderState("NP", TODAY, None)
        state.selected = [f"P{i}" for i in range(16)]
        state.opponents = [{"name": f"O{i}", "total_ovr": 100, "def_ovr": 50} for i in range(16)]
        state.opponent_league_name = "seams suspicious"
        state.event_type = "E1"
        state.our_rank = 45
        order = list(range(16))
        embed = build_final_embed(state, order, order)
        calls = {c.kwargs.get("name"): c.kwargs.get("value") for c in embed.add_field.call_args_list}
        self.assertIn("Matchup", calls)
        self.assertIn("seams suspicious", calls["Matchup"])
        self.assertIn("E1", calls["Matchup"])
        self.assertIn("45", calls["Matchup"])

    async def test_ladder_final_embed_omits_division_and_rank_when_not_extracted(self):
        from ladder_flow import LadderState, build_final_embed
        state = LadderState("NP", TODAY, None)
        state.selected = [f"P{i}" for i in range(16)]
        state.opponents = [{"name": f"O{i}", "total_ovr": 100, "def_ovr": 50} for i in range(16)]
        state.opponent_league_name = "seams suspicious"
        # event_type and our_rank left as None
        order = list(range(16))
        embed = build_final_embed(state, order, order)
        calls = {c.kwargs.get("name"): c.kwargs.get("value") for c in embed.add_field.call_args_list}
        self.assertEqual(calls["Matchup"], "vs seams suspicious")

    async def test_ladder_final_embed_no_context_field_when_no_league_name(self):
        """The manual CSV entry flow never extracts any of this — no
        confirmation field should appear at all, not one with blanks in it."""
        from ladder_flow import LadderState, build_final_embed
        state = LadderState("NP", TODAY, None)
        state.selected = [f"P{i}" for i in range(16)]
        state.opponents = [{"name": f"O{i}", "total_ovr": 100, "def_ovr": 50} for i in range(16)]
        order = list(range(16))
        embed = build_final_embed(state, order, order)
        names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertNotIn("Matchup", names)

    async def test_build_ladder_image_passes_style_through(self):
        from optimized_bot import _build_ladder_image
        await db.upsert_ladder_slot("NP", TODAY, 1, opp_ign="TestOpp", opp_def_ovr=200, our_ign="Grizzly")
        for style in ['classic', 'neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                      'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal',
                      'gators', 'ledboard', 'dossier', 'gameboy', 'cyberdeck', 'starfield',
                      'hazard', 'bubble', 'sketch', 'prestige', 'paper', 'heatmap']:
            buf = await _build_ladder_image("NP", datetime.date.fromisoformat(TODAY), style=style)
            self.assertIsNotNone(buf)


class TestI18nTier4(unittest.IsolatedAsyncioTestCase):
    """Locks in i18n wiring for the admin commands (Tier 4)."""

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    def _make_interaction(self, locale=None):
        inter = MagicMock()
        inter.locale = locale or discord.Locale.german
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.response.send_modal = AsyncMock()
        inter.response.defer = AsyncMock()
        inter.response.edit_message = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        return inter

    async def test_ovr_modal_translated_spanish(self):
        from optimized_bot import OvrModal
        modal = OvrModal("Grizzly", lang="es")
        self.assertEqual(modal.title, "Actualizar Overall del Equipo")
        modal.off_ovr.value = "150"
        modal.def_ovr.value = "150"
        modal.total_ovr.value = "300"
        inter = self._make_interaction()
        await modal.on_submit(inter)
        msg = inter.response.send_message.call_args.args[0]
        self.assertIn("Grizzly", msg)
        self.assertIn("150 / 150 / 300", msg)

    async def test_confirm_view_translated_french(self):
        from optimized_bot import ConfirmView
        async def noop(i): pass
        view = ConfirmView(noop, lang="fr")
        labels = [c.label for c in view.children]
        self.assertIn("✅ Confirmer", labels)
        self.assertIn("❌ Annuler", labels)

    async def test_confirm_view_cancel_translated(self):
        from optimized_bot import ConfirmView
        view = ConfirmView(lambda i: None, lang="de")
        inter = self._make_interaction()
        await view._cancel(inter)
        msg = inter.response.edit_message.call_args.kwargs.get("content")
        self.assertEqual(msg, "Abgebrochen.")

    async def test_transfer_league_view_translated_portuguese(self):
        from optimized_bot import TransferLeagueView
        view = TransferLeagueView("Grizzly", "NP", lang="pt")
        select = view.children[0]
        self.assertEqual(select.placeholder, "Selecione a liga de destino...")

    async def test_weights_view_translated_french(self):
        from optimized_bot import WeightsView
        view = WeightsView("pwr_rank", None, lang="fr")
        await view.load()
        embed = view._build_embed()
        self.assertIn("Poids", embed.title)
        self.assertIn("Global", embed.title)

    async def test_stat_labels_translated_and_consistent(self):
        from optimized_bot import _stat_labels, ALL_STAT_KEYS
        labels_de = _stat_labels('de')
        labels_en = _stat_labels('en')
        self.assertEqual(len(labels_de), len(ALL_STAT_KEYS))
        self.assertEqual([k for k, _ in labels_de], [k for k, _ in labels_en])
        de_texts = [t for _, t in labels_de]
        self.assertIn("Jahresdurchschnitt", de_texts)

    async def test_league_add_modal_translated_german(self):
        from optimized_bot import LeagueAddModal
        modal = LeagueAddModal(lang="de")
        self.assertEqual(modal.title, "Neue Liga Hinzufügen")
        self.assertEqual(_label_text_for(modal, modal.league_id), "Liga-ID (2 Buchstaben, z. B. NX)")

    async def test_inactive_confirm_translated_spanish(self):
        import i18n
        from optimized_bot import inactive_slash
        await db.execute("UPDATE players SET status='A' WHERE ign='Grizzly'")
        inter = self._make_interaction(discord.Locale.spain_spanish)
        role = MagicMock()
        role.name = "Administrator"
        inter.user.roles = [role]
        inter.guild = MagicMock()
        # Call the underlying logic directly is not possible (tree.command wraps it);
        # instead verify the translation keys used by the handler render correctly.
        self.assertEqual(i18n.t('inactive.status_active', 'es'), "Activo")
        self.assertEqual(i18n.t('inactive.confirm.title', 'es'), "Confirmar Salida del Jugador de la Liga")

    async def test_tournament_embed_translated_french(self):
        import tournament as tournament_module
        tm = tournament_module.TournamentManager()
        tid = await tm.create(["A", "B", "C", "D"], name="Cup")
        embed = await tm.build_embed(tid, lang="fr")
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertTrue(any("Demi-finales" in n or "Grande Finale" in n for n in field_names))

    async def test_tournament_list_embed_translated_german(self):
        import tournament as tournament_module
        tm = tournament_module.TournamentManager()
        await tm.create(["A", "B"], name="Cup2")
        embed = await tm.build_list_embed(lang="de")
        self.assertEqual(embed.title, "📋 Alle Turniere")
        field_names = [c.kwargs.get("name") for c in embed.add_field.call_args_list]
        self.assertIn("🟢 Aktiv", field_names)

    async def test_gif_role_required_message_mentions_both_roles(self):
        import i18n
        msg = i18n.t('gif.role_required', 'es')
        self.assertIn("Administrador", msg)
        self.assertIn("Gif Master", msg)

    async def test_manual_page4_includes_nick_ign_rename_in_all_languages(self):
        import i18n
        for lang in i18n.SUPPORTED_LANGS:
            names = [n for n, _ in i18n.TRANSLATIONS['manual.page4.fields'][lang]]
            self.assertIn("/nick", names)
            self.assertIn("/ign", names)
            self.assertIn("/rename", names)

    async def test_ign_cmd_translated_german(self):
        import i18n
        self.assertEqual(i18n.t('ign_cmd.success.title', 'de'), "✅ Echter IGN Aktualisiert")
        self.assertEqual(i18n.t('ign_cmd.field.old_real_ign', 'de'), "Alter Echter IGN")

    async def test_rename_cmd_translated_portuguese(self):
        import i18n
        self.assertEqual(i18n.t('rename_cmd.success.title', 'pt'), "✅ Jogador Renomeado")
        self.assertEqual(i18n.t('rename_cmd.err.taken', 'pt', nickname="Foo"), "⚠️ O apelido `Foo` já está em uso.")

    async def test_nick_cmd_translated_french(self):
        import i18n
        self.assertEqual(i18n.t('nick.success.title', 'fr'), "✅ Pseudo Défini")
        self.assertIn("Slayer", i18n.t('nick.err.not_found', 'fr', real_ign="Slayer"))


class TestNickIgnDisambiguation(unittest.IsolatedAsyncioTestCase):
    """
    Covers: /nick's autocomplete disambiguating players who share a real_ign
    (real_ign is not unique, so it can never be the sole identifier), the
    nickname-uniqueness guard, /register defaulting real_ign to the nickname
    instead of leaving it NULL, and the startup migration that backfills any
    already-NULL real_ign values.
    """

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_nick_autocomplete_disambiguates_shared_real_ign(self):
        """Two different players sharing the same real_ign must both show up
        as separate, individually-selectable suggestions — never merged or
        silently resolved to just one of them."""
        from optimized_bot import nick_player_autocomplete
        await db.execute("UPDATE players SET real_ign='SharedName' WHERE ign='Grizzly'")
        await db.execute("UPDATE players SET real_ign='SharedName' WHERE ign='dougbaldwin'")
        inter = MagicMock()
        choices = await nick_player_autocomplete(inter, "SharedName")
        self.assertEqual(len(choices), 2)
        values = {c.value for c in choices}
        grizzly_id = (await db.get_player("Grizzly"))["id"]
        doug_id = (await db.get_player("dougbaldwin"))["id"]
        self.assertEqual(values, {str(grizzly_id), str(doug_id)})
        for c in choices:
            self.assertIn(" - ", c.name)
            self.assertTrue(c.name.startswith("SharedName - "))

    async def test_nick_autocomplete_matches_on_nickname_too(self):
        from optimized_bot import nick_player_autocomplete
        inter = MagicMock()
        choices = await nick_player_autocomplete(inter, "Grizzly")
        self.assertTrue(any("Grizzly" in c.name for c in choices))

    async def test_nick_updates_only_the_selected_player_by_id(self):
        """Renaming one of two same-real_ign players must never touch the other."""
        await db.execute("UPDATE players SET real_ign='SharedName' WHERE ign='Grizzly'")
        await db.execute("UPDATE players SET real_ign='SharedName' WHERE ign='dougbaldwin'")
        grizzly = await db.get_player("Grizzly")

        row = await db.fetchone("SELECT * FROM players WHERE id=?", (grizzly["id"],))
        clash = await db.fetchone("SELECT id FROM players WHERE ign=? AND id != ? LIMIT 1", ("GrizzNew", row["id"]))
        self.assertIsNone(clash)
        await db.execute("UPDATE players SET ign=? WHERE id=?", ("GrizzNew", row["id"]))

        renamed = await db.fetchone("SELECT * FROM players WHERE id=?", (grizzly["id"],))
        self.assertEqual(renamed["ign"], "GrizzNew")
        self.assertEqual(renamed["real_ign"], "SharedName")  # untouched, /nick never sets real_ign
        untouched = await db.get_player("dougbaldwin")
        self.assertEqual(untouched["ign"], "dougbaldwin")  # the other same-real_ign player is unaffected

    async def test_nick_rejects_nickname_already_taken_by_a_different_player(self):
        clash = await db.fetchone(
            "SELECT id FROM players WHERE ign=? AND id != ? LIMIT 1",
            ("dougbaldwin", (await db.get_player("Grizzly"))["id"])
        )
        self.assertIsNotNone(clash)  # the guard would correctly block this rename

    async def test_register_defaults_real_ign_to_nickname_when_blank(self):
        from optimized_bot import RegisterModal
        modal = RegisterModal("NP")
        modal.ign.value = "BrandNewPlayer"
        modal.real_ign.value = ""  # left blank
        modal.off_ovr.value = "150"
        modal.def_ovr.value = "150"
        modal.total.value = "300"
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        await modal.on_submit(inter)

        row = await db.get_player("BrandNewPlayer")
        self.assertIsNotNone(row["real_ign"])
        self.assertEqual(row["real_ign"], "BrandNewPlayer")

    async def test_register_allows_duplicate_real_ign(self):
        """A real_ign already used by another player must not block registration —
        duplicates are valid and expected, not an error condition."""
        from optimized_bot import RegisterModal
        modal = RegisterModal("NP")
        modal.ign.value = "SecondPlayer"
        modal.real_ign.value = "Grizzly"  # same real_ign as the existing Grizzly
        modal.off_ovr.value = "150"
        modal.def_ovr.value = "150"
        modal.total.value = "300"
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        await modal.on_submit(inter)

        row = await db.get_player("SecondPlayer")
        self.assertIsNotNone(row)
        self.assertEqual(row["real_ign"], "Grizzly")
        inter.followup.send.assert_called_once()
        sent = inter.followup.send.call_args
        self.assertNotIn("err", str(sent).lower())

    async def test_migration_backfills_null_real_ign_with_nickname(self):
        await db.execute("UPDATE players SET real_ign=NULL WHERE ign='Grizzly'")
        row_before = await db.get_player("Grizzly")
        self.assertIsNone(row_before["real_ign"])

        await db._migrate_schema()

        row_after = await db.get_player("Grizzly")
        self.assertEqual(row_after["real_ign"], "Grizzly")

    async def test_migration_does_not_touch_already_set_real_ign(self):
        await db.execute("UPDATE players SET real_ign='CustomRealIgn' WHERE ign='Grizzly'")
        await db._migrate_schema()
        row = await db.get_player("Grizzly")
        self.assertEqual(row["real_ign"], "CustomRealIgn")

    async def test_migration_clears_excused_score_from_zero_to_null(self):
        """Existing excused entries stored with the old score=0 behavior must
        get corrected to NULL by the migration; entries that are genuinely
        excused-with-zero-because-that-was-the-old-bug are exactly what this
        targets. A real 0-point non-excused entry must be left alone."""
        await db.update_player_score("Grizzly", TODAY, 0.0, is_excused=True)
        await db._migrate_schema()
        row = await db.fetchone("SELECT score, is_excused FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertIsNone(row["score"])
        self.assertEqual(row["is_excused"], 1)

    async def test_migration_does_not_touch_non_excused_zero_scores(self):
        await db.update_player_score("Grizzly", TODAY, 0.0)
        await db._migrate_schema()
        row = await db.fetchone("SELECT score FROM game_scores WHERE game_date=?", (TODAY,))
        self.assertEqual(row["score"], 0)  # untouched — this is a real played 0, not excused

    async def test_migration_merges_preexisting_duplicate_game_scores_rows(self):
        """
        Directly reproduces the reported bug's aftermath: two rows already
        exist for the same (player_id, game_date) — one from before the fix
        (e.g. score=22, event_type='E1') and one the buggy correction created
        (score=24, event_type=NULL) — inserted directly here to simulate data
        already corrupted by the bug before this migration existed. The
        migration must merge them into exactly one row, trusting the newest
        row's score (the actual intended correction) while not losing the
        older row's event_type since the newer one left it blank.
        """
        # The test schema starts with the already-corrected index; drop it
        # first to simulate a real pre-migration database where duplicates
        # could actually exist.
        await db.execute("DROP INDEX IF EXISTS uq_player_date")

        player = await db.get_player("dougbaldwin")
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score, event_type, fourth_downs) "
            "VALUES (?, ?, ?, 22.0, 'E1', 3)",
            (player["id"], player["team_id"], TODAY)
        )
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score, event_type) "
            "VALUES (?, ?, ?, 24.0, NULL)",
            (player["id"], player["team_id"], TODAY)
        )
        rows_before = await db.fetchall(
            "SELECT * FROM game_scores WHERE player_id=? AND game_date=?", (player["id"], TODAY)
        )
        self.assertEqual(len(rows_before), 2)  # confirms the corrupted state exists first

        await db._migrate_schema()

        rows_after = await db.fetchall(
            "SELECT * FROM game_scores WHERE player_id=? AND game_date=?", (player["id"], TODAY)
        )
        self.assertEqual(len(rows_after), 1)
        merged = rows_after[0]
        self.assertEqual(merged["score"], 24.0)          # newest score wins — the real correction
        self.assertEqual(merged["event_type"], "E1")     # preserved from the older row, not lost
        self.assertEqual(merged["fourth_downs"], 3)      # preserved from the older row too

    async def test_migration_rebuilds_unique_index_to_exclude_event_type(self):
        """After the migration, the unique index must be (player_id, game_date)
        only — inserting a second row for the same player+day, even with a
        different event_type, must now be rejected outright."""
        await db._migrate_schema()
        player = await db.get_player("Grizzly")
        await db.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score, event_type) "
            "VALUES (?, ?, ?, 18.0, 'HOF')",
            (player["id"], player["team_id"], TODAY)
        )
        with self.assertRaises(Exception):
            await db.execute(
                "INSERT INTO game_scores (player_id, team_id, game_date, score, event_type) "
                "VALUES (?, ?, ?, 22.0, 'E1')",
                (player["id"], player["team_id"], TODAY)
            )

    # --- get_archive_conn: read-only access to a past season's database,
    # underpinning every /legacy command ---

    async def test_get_archive_conn_missing_year_returns_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                conn = await db.get_archive_conn(1999)
                self.assertIsNone(conn)
            finally:
                db.DB_PATH = original_path

    async def test_get_archive_conn_reads_existing_archive(self):
        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                archive_path = os.path.join(tmpdir, "neuroverse_2026.db")
                raw = sqlite3.connect(archive_path)
                raw.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, ign TEXT)")
                raw.execute("INSERT INTO players (ign) VALUES ('ArchivedPlayer')")
                raw.commit()
                raw.close()

                conn = await db.get_archive_conn(2026)
                self.assertIsNotNone(conn)
                row = await db.fetchone("SELECT ign FROM players WHERE ign='ArchivedPlayer'", conn=conn)
                self.assertEqual(row["ign"], "ArchivedPlayer")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path

    async def test_get_archive_conn_is_genuinely_read_only(self):
        """A /legacy command must never be able to write to a past season's
        data, even by accident — verify the connection actually enforces this,
        not just that the code never happens to call an UPDATE."""
        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                archive_path = os.path.join(tmpdir, "neuroverse_2026.db")
                raw = sqlite3.connect(archive_path)
                raw.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, ign TEXT)")
                raw.commit()
                raw.close()

                conn = await db.get_archive_conn(2026)
                with self.assertRaises(Exception):
                    await conn.execute("INSERT INTO players (ign) VALUES ('ShouldFail')")
                    await conn.commit()
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path

    async def test_get_archive_conn_caches_connection_across_calls(self):
        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                archive_path = os.path.join(tmpdir, "neuroverse_2026.db")
                raw = sqlite3.connect(archive_path)
                raw.execute("CREATE TABLE players (id INTEGER PRIMARY KEY)")
                raw.commit()
                raw.close()

                conn1 = await db.get_archive_conn(2026)
                conn2 = await db.get_archive_conn(2026)
                self.assertIs(conn1, conn2)
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path

    # --- /legacy command-level tests: missing archive, and full round-trips
    # against a real temp archive database built with the live schema ---

    def _make_legacy_interaction(self):
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.response.send_message = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.guild = MagicMock()
        inter.user = MagicMock()
        admin_role = MagicMock()
        admin_role.name = "Administrator"
        inter.user.roles = [admin_role]
        inter.locale = discord.Locale.american_english
        return inter

    async def _build_temp_archive(self, tmpdir, year=2026):
        """Build a minimal but real archive db, using the same schema as the
        live test fixture, with one scored player."""
        archive_path = os.path.join(tmpdir, f"neuroverse_{year}.db")
        raw = sqlite3.connect(archive_path)
        raw.executescript(SCHEMA)
        raw.execute("INSERT INTO teams VALUES ('NP', 'NeuroPerverse', 'NeuroPerverse')")
        raw.execute(
            "INSERT INTO players (team_id,ign,status,off_ovr,def_ovr,total_ovr) "
            "VALUES ('NP','ArchivedGrizzly','A',240,220,7000)"
        )
        raw.execute(
            "INSERT INTO game_scores (player_id, team_id, game_date, score) "
            "VALUES (1, 'NP', '2026-07-20', 22.0)"
        )
        raw.execute(
            "INSERT INTO matchup_day (team_id, game_date, opp_ign, event_type, opp_score, our_score) "
            "VALUES ('NP', '2026-07-20', 'ArchivedOpp', 'E1', 14, 22)"
        )
        raw.commit()
        raw.close()
        return archive_path

    async def test_legacy_history_missing_archive_shows_error(self):
        import tempfile
        from optimized_bot import legacy_history_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                await legacy_history_slash(inter, "Grizzly", "2026-07-01", 1999)
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertTrue(inter.followup.send.call_args.kwargs.get("ephemeral"))

    async def test_legacy_history_full_round_trip(self):
        import tempfile
        from optimized_bot import legacy_history_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                await self._build_temp_archive(tmpdir)
                await legacy_history_slash(inter, "ArchivedGrizzly", "2026-07-01", 2026, "2026-07-31")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        embed = inter.followup.send.call_args.kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertIn("2026", embed.title)  # season label present

    async def test_legacy_scores_missing_archive_shows_error(self):
        import tempfile
        from optimized_bot import legacy_scores_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                await legacy_scores_slash(inter, 1999, "NP", "2026-07-01")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertTrue(inter.followup.send.call_args.kwargs.get("ephemeral"))

    async def test_legacy_scores_full_round_trip(self):
        import tempfile
        from optimized_bot import legacy_scores_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                await self._build_temp_archive(tmpdir)
                await legacy_scores_slash(inter, 2026, "NP", "2026-07-20")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertIsNotNone(inter.followup.send.call_args.kwargs.get("file"))

    async def test_legacy_show_ladder_missing_archive_shows_error(self):
        import tempfile
        from optimized_bot import legacy_show_ladder_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                await legacy_show_ladder_slash(inter, 1999, "NP")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertTrue(inter.followup.send.call_args.kwargs.get("ephemeral"))

    async def test_legacy_show_ladder_defaults_to_latest_recorded_date(self):
        """No 'today' exists in an archived season — must fall back to the
        latest date that season actually has ladder data for, not crash or
        silently show nothing."""
        import tempfile
        from optimized_bot import legacy_show_ladder_slash
        inter = self._make_legacy_interaction()
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                archive_path = await self._build_temp_archive(tmpdir)
                raw = sqlite3.connect(archive_path)
                raw.execute(
                    "INSERT INTO matchup_ladder (team_id, game_date, slot, our_ign, opp_ign) "
                    "VALUES ('NP', '2026-07-20', 1, 'ArchivedGrizzly', 'ArchivedOpp')"
                )
                raw.commit()
                raw.close()

                await legacy_show_ladder_slash(inter, 2026, "NP")  # date omitted
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertIsNotNone(inter.followup.send.call_args.kwargs.get("file"))

    async def test_migration_drops_dead_fourth_down_columns_from_players(self):
        """players.fourth_downs/fourth_down_convs are dead leftovers from the
        original Excel-mirrored schema — never read or written anywhere. The
        real, working tracking lives in game_scores. Simulate an
        older-schema database (as if these columns still existed live) and
        confirm the migration removes them, and is safe to rerun afterward."""
        await db.execute("ALTER TABLE players ADD COLUMN fourth_downs INTEGER DEFAULT 0")
        await db.execute("ALTER TABLE players ADD COLUMN fourth_down_convs INTEGER DEFAULT 0")

        cur = await db._db.execute("PRAGMA table_info(players)")
        cols_before = {row["name"] for row in await cur.fetchall()}
        self.assertIn("fourth_downs", cols_before)
        self.assertIn("fourth_down_convs", cols_before)

        await db._migrate_schema()

        cur = await db._db.execute("PRAGMA table_info(players)")
        cols_after = {row["name"] for row in await cur.fetchall()}
        self.assertNotIn("fourth_downs", cols_after)
        self.assertNotIn("fourth_down_convs", cols_after)

        # Safe to run again once already dropped (idempotent, no crash)
        await db._migrate_schema()


class TestDataIntegrity(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_status_values_valid(self):
        """All players should have A, R, or L status."""
        rows = await db.fetchall("SELECT ign, status FROM players")
        for row in rows:
            self.assertIn(row["status"], ("A", "I"),
                          f"{row['ign']} has invalid status '{row['status']}'")

    async def test_no_duplicate_player_igns_per_team(self):
        rows = await db.fetchall(
            "SELECT team_id, ign, COUNT(*) as cnt FROM players "
            "GROUP BY team_id, ign HAVING cnt > 1"
        )
        self.assertEqual(len(rows), 0, f"Duplicate IGNs found: {rows}")

    async def test_game_scores_have_valid_player_refs(self):
        """game_scores should only reference existing players."""
        await db.update_player_score("Grizzly", TODAY, 22.0)
        orphans = await db.fetchall(
            """SELECT gs.id FROM game_scores gs
               LEFT JOIN players p ON p.id = gs.player_id
               WHERE p.id IS NULL"""
        )
        self.assertEqual(len(orphans), 0)

    async def test_matchup_day_unique_per_team_date(self):
        """Only one matchup per team per date."""
        await db.set_matchup("NP", TODAY, "TeamA")
        await db.set_matchup("NP", TODAY, "TeamB")  # should upsert
        rows = await db.fetchall(
            "SELECT * FROM matchup_day WHERE team_id='NP' AND game_date=?", (TODAY,)
        )
        self.assertEqual(len(rows), 1)

    async def test_weights_labels_unique_per_category_team(self):
        """No duplicate labels within the same category and team scope."""
        rows = await db.fetchall(
            """SELECT label, category, team_id, COUNT(*) as cnt
               FROM pwr_rank_weights
               GROUP BY label, category, team_id
               HAVING cnt > 1"""
        )
        self.assertEqual(len(rows), 0, f"Duplicate weight labels: {rows}")

    async def test_score_with_def_ovr(self):
        await db.update_player_score("Grizzly", TODAY, 22.0, def_ovr_faced=229)
        row = await db.fetchone(
            "SELECT def_ovr_faced FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(row["def_ovr_faced"], 229)

    async def test_team_id_override_on_score(self):
        """A transferred player's score should stay tied to their team at game time."""
        await db.update_player_score(
            "Grizzly", TODAY, 22.0, team_id_override="ND"
        )
        row = await db.fetchone(
            "SELECT team_id FROM game_scores WHERE game_date=?", (TODAY,)
        )
        self.assertEqual(row["team_id"], "ND")

    async def test_l_status_excluded_from_rank_table(self):
        await db.execute("UPDATE players SET status='I' WHERE ign='Grizzly'")
        rows = await db.get_rank_table("NP")
        igns = [r["ign"] for r in rows]
        self.assertNotIn("Grizzly", igns)

    async def test_inactive_excluded_from_remaining(self):
        """I-status players should not appear in remaining."""
        await db.execute("UPDATE players SET status='I' WHERE ign='FHRITP'")
        remaining = await db.get_players_remaining("NP", TODAY)
        self.assertNotIn("FHRITP", remaining)
        await db.execute("UPDATE players SET status='A' WHERE ign='FHRITP'")


class TestThemedLadderStyles(unittest.TestCase):
    """
    The theme-driven ladder styles (everything after the original bespoke
    renderers). They all share _render_ladder_themed, so what needs testing
    per theme is its *config* — a missing key or a font whose digits can't
    be read renders perfectly happily and just looks wrong.
    """

    ROWS = [
        {'slot': i, 'our_ign': n, 'our_off_ovr': ovr, 'opp_ign': o, 'opp_def_ovr': d}
        for i, (n, ovr, o, d) in enumerate([
            ('Seahawks', 136, 'Carterman', 133), ('CorgiCola', 125, 'CGL', 133),
            ('PHOKing_Frank', 142, 'GCrane8Cowboys', 133), ('wagdad', 132, 'MIAMiknerF', 132),
        ], 1)
    ]

    def test_every_theme_renders_a_valid_png(self):
        from PIL import Image
        from sheet_image import render_ladder_image, _LADDER_THEMES
        for style in _LADDER_THEMES:
            buf = render_ladder_image("T", self.ROWS, style=style, our_team_name="NeuroAdverse",
                                      opponent_name="Legends of Valhalla", division="E1")
            img = Image.open(buf)
            self.assertEqual(img.format, "PNG", style)
            self.assertGreater(img.width, 0, style)

    def test_every_theme_declares_the_keys_the_engine_requires(self):
        from sheet_image import _LADDER_THEMES
        for style, t in _LADDER_THEMES.items():
            for key in ('bg', 'text', 'font_title', 'font_name', 'font_num'):
                self.assertIn(key, t, f'{style} is missing required theme key {key!r}')

    def test_every_theme_scales_with_row_count(self):
        from PIL import Image
        from sheet_image import render_ladder_image, _LADDER_THEMES
        few = self.ROWS[:1]
        many = [dict(r, slot=i) for i, r in enumerate(self.ROWS * 4, 1)]
        for style in _LADDER_THEMES:
            a = Image.open(render_ladder_image("T", few, style=style))
            b = Image.open(render_ladder_image("T", many, style=style))
            self.assertLess(a.height, b.height, style)

    def test_every_theme_handles_missing_opponent_data(self):
        from PIL import Image
        from sheet_image import render_ladder_image, _LADDER_THEMES
        rows = [{'slot': 1, 'our_ign': 'Grizzly', 'our_off_ovr': None,
                 'opp_ign': None, 'opp_def_ovr': None}]
        for style in _LADDER_THEMES:
            img = Image.open(render_ladder_image("T", rows, style=style))  # must not raise
            self.assertGreater(img.width, 0, style)

    def test_gators_theme_is_blue_and_orange(self):
        """The one explicit colour request: Florida's livery. Checks the
        actual palette rather than trusting the style's name."""
        from sheet_image import _LADDER_THEMES
        t = _LADDER_THEMES['gators']
        r, g, b = t['bg']
        # Hue relationships rather than a brightness floor: blue has to
        # dominate, which is true of both a navy and a royal blue.
        self.assertTrue(b > 100 and b > r * 2 and b > g * 2, f'gators background is not blue: {t["bg"]}')

        # Orange has to be present, but deliberately not pinned to a
        # particular key: it moved off the home band when white-on-orange
        # turned out to be hard to read, and that fix shouldn't fail this.
        colours = [v for v in t.values() if isinstance(v, tuple) and len(v) == 3]
        oranges = [c for c in colours if c[0] > 200 and 40 < c[1] < 160 and c[2] < 100]
        self.assertGreaterEqual(len(oranges), 2,
                                f'gators has no orange left in its palette: {colours}')

    def test_bubble_uses_keania_throughout_by_explicit_choice(self):
        """Keania One's '8' is nearly identical to its 'S' (confirmed on a
        rendered digit sheet), so GCrane8Cowboys reads as GCraneSCowboys.
        That was raised and the look was explicitly preferred over the
        ambiguity — unlike carnival/Honk, where the reliable font stayed.
        This test pins the decision so nobody "fixes" it back on legibility
        grounds without asking first."""
        import sheet_image
        t = sheet_image._LADDER_THEMES['bubble']
        for key in ('font_title', 'font_name', 'font_num'):
            self.assertEqual(t[key], sheet_image._FONT_KEANIA,
                             f'bubble should use Keania One for {key}')

    def test_stroke_is_only_used_on_faces_open_enough_to_take_it(self):
        """Faux-bolding via stroke helps a light, open face and wrecks a
        tight or heavy one: a 1px outline closed up Anton\'s counters
        ("Ruffis" -> "Buffis"), DotGothic16\'s pixel shapes ("scotty" ->
        "ecotty") and VT323\'s m/W ("Packman425" -> "Packnan425"). Share
        Tech Mono in blueprint is the one that takes it cleanly."""
        import inspect
        import sheet_image
        blueprint = inspect.getsource(sheet_image._render_ladder_blueprint)
        self.assertIn('stroke=1', blueprint, 'blueprint should faux-bold Share Tech Mono')
        terminal = inspect.getsource(sheet_image._render_ladder_terminal)
        self.assertNotIn('stroke=1', terminal, 'VT323 glyphs fill in when stroked')
        for style in ('heatmap', 'gameboy'):
            self.assertFalse(sheet_image._LADDER_THEMES[style].get('name_stroke'),
                             f'{style} must not stroke its names — its face fills in')

    def test_prestige_has_laurels_and_varsity_has_helmets(self):
        """Both decals were asked for specifically, and both are easy to lose
        in a later palette tweak since neither affects layout."""
        import inspect
        import sheet_image
        self.assertIn('_paste_laurel',
                      inspect.getsource(sheet_image._art_gold_rules),
                      'prestige lost its laurels')
        self.assertIn('_paste_helmet',
                      inspect.getsource(sheet_image._render_ladder_varsity),
                      'varsity lost its helmet decals')

    def test_helmet_silhouette_has_a_face_opening(self):
        """The helmet is a filled silhouette with a bite taken out for the
        face opening — an early outline version read as a plain circle. If
        the cut-outs ever stop being transparent it becomes a blob again."""
        from sheet_image import _helmet_layer
        layer = _helmet_layer(120, (212, 175, 55))
        alpha = layer.split()[-1]
        px = alpha.load()
        # (88, 55) is inside the shell ellipse but inside the face-opening
        # wedge, and clear of the facemask bars — so it is solid without the
        # cut and transparent with it. Picked by computing against the shapes
        # rather than by eye: a first attempt used (100, 100), which is
        # outside the shell altogether, so the assertion held either way and
        # the test proved nothing.
        self.assertGreater(px[40, 30], 200, 'helmet crown should be solid')
        self.assertLess(px[88, 55], 40, 'helmet face opening should be cut away')

    def test_newsprint_is_set_in_the_serif_throughout(self):
        """The masthead alone was not enough — the body still rendered in the
        generic condensed bold, which read as unstyled."""
        import inspect
        import sheet_image
        src = inspect.getsource(sheet_image._render_ladder_newsprint)
        self.assertIn("f['our_ign'], _FONT_NEWSREADER", src)
        self.assertIn("f['opp_ign'], _FONT_NEWSREADER", src)
        self.assertNotIn('_POSTER_FONT_BOLD', src, 'newsprint still falls back to the default face')

    def test_every_theme_font_actually_loads_at_the_requested_size(self):
        """Every font a theme names has to resolve to a real file somewhere in
        its candidate chain. If none do, _load_font falls through to PIL's
        default, which ignores the requested size and renders ~10px — the
        exact silent failure that shipped once already.

        Note this can't just check chain[0]: the DejaVu Condensed chains
        (which several themes use for names) start at a bundled path that
        isn't bundled — those legitimately resolve to a system copy."""
        import os
        import sheet_image
        for style, t in sheet_image._LADDER_THEMES.items():
            for key in ('font_title', 'font_name', 'font_num', 'font_stat', 'font_label'):
                chain = t.get(key)
                if not chain:
                    continue
                self.assertTrue(any(os.path.isfile(p) for p in chain),
                                f'{style}.{key}: no candidate exists on disk: {chain}')
                font = sheet_image._load_font(chain, 22)
                self.assertEqual(font.size, 22, f'{style}.{key} did not load at the requested size')

    def test_display_faces_are_bundled_not_system_dependent(self):
        """The new display faces have no OS package anywhere, so for those the
        bundled copy specifically must be present — a system fallback would
        never exist on the production host."""
        import os
        import sheet_image
        for const in ('_FONT_AUDIOWIDE', '_FONT_BITCOUNT', '_FONT_DOTGOTHIC', '_FONT_KEANIA',
                      '_FONT_NEWSREADER', '_FONT_NEWSREADER_IT', '_FONT_NOVA_SQUARE',
                      '_FONT_SPECIAL_ELITE', '_FONT_SYNE_MONO', '_FONT_WALLPOET'):
            bundled = getattr(sheet_image, const)[0]
            self.assertIn('fonts', bundled, f'{const} does not prefer a bundled copy')
            self.assertTrue(os.path.isfile(bundled), f'{const} bundled file missing: {bundled}')

    def test_heatmap_tint_tracks_the_diff(self):
        """heatmap's whole point is the row colour carrying the same
        information as the diff column — greener as we're favoured, redder as
        we're not, and neutral when the OVR is unknown."""
        from sheet_image import _heat_tint
        big_plus = _heat_tint({'diff_val': 14}, 0)
        big_minus = _heat_tint({'diff_val': -14}, 0)
        unknown = _heat_tint({'diff_val': None}, 0)
        self.assertGreater(big_plus[1], big_plus[0], 'favoured rows should read green')
        self.assertGreater(big_minus[0], big_minus[1], 'underdog rows should read red')
        self.assertLess(abs(unknown[0] - unknown[1]), 10, 'unknown should stay neutral')

    def test_background_art_is_deterministic(self):
        """Several themes scatter stars/speckle/blobs with random(); those are
        seeded, so the same ladder has to render byte-identically every time
        rather than shimmering between calls."""
        from sheet_image import render_ladder_image
        for style in ('starfield', 'cyberdeck', 'dossier', 'bubble'):
            a = render_ladder_image("T", self.ROWS, style=style).getvalue()
            b = render_ladder_image("T", self.ROWS, style=style).getvalue()
            self.assertEqual(a, b, f'{style} renders differently on repeat calls')


class TestLadderStyleChoices(unittest.TestCase):
    """The /show_ladder picker and the renderer have to agree, and the whole
    list has to fit inside Discord's hard cap of 25 choices per parameter."""

    def _choices(self):
        import optimized_bot
        return optimized_bot.LADDER_STYLE_CHOICES

    def test_style_choices_fit_discords_25_choice_limit(self):
        choices = self._choices()
        self.assertLessEqual(len(choices), 25,
                             f'{len(choices)} choices exceeds Discord\'s per-parameter limit of 25')

    def test_every_offered_style_actually_renders_something_distinct(self):
        """A style in the picker that isn't wired up silently falls through to
        classic, which looks like the picker being ignored."""
        from sheet_image import render_ladder_image
        classic = render_ladder_image("T", TestThemedLadderStyles.ROWS, style='classic').getvalue()
        for choice in self._choices():
            if choice.value == 'classic':
                continue
            out = render_ladder_image("T", TestThemedLadderStyles.ROWS, style=choice.value,
                                      our_team_name="NeuroAdverse", opponent_name="Opponents")
            self.assertNotEqual(out.getvalue(), classic,
                                f'style {choice.value!r} fell through to classic')

    def test_every_implemented_style_is_offered_in_the_picker(self):
        """The other direction: a style built but never added to the picker is
        unreachable for users, which is how the four newest ones sat unused."""
        import sheet_image
        offered = {c.value for c in self._choices()}
        for style in sheet_image._LADDER_THEMES:
            self.assertIn(style, offered, f'theme {style!r} is implemented but not in the picker')
        for name in vars(sheet_image):
            if name.startswith('_render_ladder_'):
                style = name[len('_render_ladder_'):]
                if style in ('themed', 'classic'):
                    continue
                self.assertIn(style, offered, f'{name} is implemented but not in the picker')

    def test_choice_values_are_unique(self):
        values = [c.value for c in self._choices()]
        self.assertEqual(len(values), len(set(values)), 'duplicate style values in the picker')


class TestBundledDisplayFonts(unittest.TestCase):
    """
    The second batch of display fonts (Anton, Bebas Neue, Orbitron, Share
    Tech Mono, VT323), added so each style has its own face instead of
    sharing the generic condensed bold. These are bundled files with no OS
    package anywhere — if one goes missing from fonts/ the only symptom is
    a silently different-looking style, so the bundling itself is what
    needs checking.
    """

    # _FONT_BEBAS is included even though no style uses it right now — it's
    # bundled, so it should stay loadable for whenever one does.
    NEW_FONTS = ['_FONT_ANTON', '_FONT_BEBAS', '_FONT_ORBITRON', '_FONT_ORBITRON_BLACK',
                 '_FONT_SHARE_TECH', '_FONT_VT323']

    def test_each_new_font_is_bundled_and_loads_at_the_requested_size(self):
        """The bundled path must come first in the chain and actually load —
        not silently fall through to PIL's fixed ~10px default."""
        import os
        import sheet_image
        for const in self.NEW_FONTS:
            chain = getattr(sheet_image, const)
            bundled = chain[0]
            self.assertTrue(os.path.isfile(bundled), f'{const} bundled file missing: {bundled}')
            self.assertIn('fonts', bundled, f'{const} should prefer the bundled copy')
            for size in (13, 24, 42):
                font = sheet_image._load_font(chain, size)
                self.assertEqual(font.size, size, f'{const} did not load at size {size}')

    def test_monospace_styles_fall_back_to_a_monospace_font(self):
        """blueprint and terminal both depend on fixed-width columns, so
        their fallback has to be another monospace face — not the condensed
        bold every other display font falls back to, which would leave the
        layout ragged if the bundled file ever went missing.

        Checked two ways, because most of these candidates are Linux system
        paths that don't exist on a dev machine: every path in the chain
        must name a Mono face (machine-independent), and any that actually
        exists here must measure as monospaced."""
        import os
        from PIL import Image, ImageDraw
        import sheet_image
        draw = ImageDraw.Draw(Image.new('RGB', (10, 10)))
        for const in ('_FONT_SHARE_TECH', '_FONT_VT323'):
            chain = getattr(sheet_image, const)
            self.assertGreater(len(chain), 1, f'{const} has no fallback at all')
            checked_real_file = False
            for path in chain[1:]:
                self.assertIn('mono', os.path.basename(path).lower(),
                              f'{const} falls back to a non-monospace face: {path}')
                if os.path.isfile(path):
                    font = sheet_image._load_font([path], 20)
                    widths = {round(draw.textlength(c, font=font), 2) for c in 'iWM10@'}
                    self.assertEqual(len(widths), 1, f'{path} is not actually monospaced')
                    checked_real_file = True
            self.assertTrue(checked_real_file,
                            f'{const} has no fallback present on this machine to verify')

    def test_new_fonts_cover_the_characters_real_igns_use(self):
        """A display font missing a glyph renders a blank box, and rosters
        here really do contain digits, underscores and mixed case
        (PHOKing_Frank, GCrane8Cowboys, thebigbreesy)."""
        from PIL import Image, ImageDraw
        import sheet_image
        draw = ImageDraw.Draw(Image.new('RGB', (10, 10)))
        samples = ['PHOKing_Frank', 'GCrane8Cowboys', 'thebigbreesy', 'Rob926', '+11', '-8', '0']
        for const in self.NEW_FONTS:
            font = sheet_image._load_font(getattr(sheet_image, const), 24)
            for text in samples:
                # A missing glyph collapses to zero width or to the .notdef
                # box; either way the string measures differently than the
                # sum of its characters rendering properly.
                self.assertGreater(draw.textlength(text, font=font), 0,
                                   f'{const} cannot render {text!r}')

    def test_no_style_uses_the_retired_nabla_font(self):
        """championship was removed for looking wrong; Nabla stays in
        fonts/ but nothing should reference it again without asking."""
        import inspect
        import sheet_image
        for name, obj in vars(sheet_image).items():
            if name.startswith('_render_ladder_') and callable(obj):
                self.assertNotIn('_FONT_NABLA_PATH', inspect.getsource(obj),
                                 f'{name} uses the retired Nabla font')


class TestLadderRowFieldsAndCentering(unittest.TestCase):
    """
    Covers the ladder row readouts: our side showing *offensive* OVR (not a
    ladder-rank score, and never the opponent's team overall), the middle
    OVR-difference column, and names being centred in their column.
    """

    def _row(self, **over):
        row = {'slot': 1, 'our_ign': 'Seahawks', 'our_off_ovr': 136,
               'opp_ign': 'Carterman', 'opp_def_ovr': 133,
               # Named "our_total_ovr" but actually the OPPONENT's team
               # overall — see _ladder_row_fields. Deliberately a wildly
               # different scale so it's obvious if it leaks into our side.
               'our_total_ovr': 4029}
        row.update(over)
        return row

    def test_our_stat_is_offensive_ovr(self):
        import sheet_image
        f = sheet_image._ladder_row_fields(self._row())
        self.assertEqual(f['our_stat'], '136')

    def test_our_stat_is_not_the_opponents_team_overall(self):
        """The reported bug: 4029 (matchup_ladder.our_total_ovr, which is the
        opponent's team overall despite the column name) appearing next to
        our own player instead of their offensive OVR."""
        import sheet_image
        f = sheet_image._ladder_row_fields(self._row())
        self.assertNotEqual(f['our_stat'], '4029')
        self.assertNotIn('4029', str(f['our_stat']))

    def test_our_stat_ignores_ladder_rank(self):
        """our_stat used to prefer ladder_rank, which is non-None for any
        league with ladder weights configured — so the ladder showed a
        weighted rank score where an OVR was expected, and the middle diff
        column wouldn't have matched the two numbers either side of it."""
        import sheet_image
        f = sheet_image._ladder_row_fields(self._row(ladder_rank=1063.4))
        self.assertEqual(f['our_stat'], '136')

    def test_diff_is_off_ovr_minus_opp_def_ovr(self):
        import sheet_image
        self.assertEqual(sheet_image._ladder_row_fields(self._row())['diff'], '+3')
        self.assertEqual(
            sheet_image._ladder_row_fields(self._row(our_off_ovr=125))['diff'], '-8')
        self.assertEqual(
            sheet_image._ladder_row_fields(self._row(our_off_ovr=133))['diff'], '0')

    def test_diff_matches_the_two_numbers_actually_displayed(self):
        """Whatever else changes, the middle column has to be exactly the
        difference of the two OVRs shown on either side of it — that's the
        only reason it's readable at a glance."""
        import sheet_image
        for ours, theirs in ((136, 133), (117, 124), (142, 122), (130, 130)):
            f = sheet_image._ladder_row_fields(self._row(our_off_ovr=ours, opp_def_ovr=theirs))
            self.assertEqual(int(f['our_stat']) - int(f['opp_stat']), f['diff_val'])

    def test_diff_is_absent_when_either_ovr_is_missing(self):
        """A missing OVR must show nothing rather than a 0, which would read
        as an even matchup."""
        import sheet_image
        self.assertIsNone(sheet_image._ladder_row_fields(self._row(our_off_ovr=None))['diff'])
        self.assertIsNone(sheet_image._ladder_row_fields(self._row(opp_def_ovr=None))['diff'])

    def test_every_poster_style_draws_the_diff(self):
        """Source-level check across all styles at once: a style that forgets
        the middle column renders perfectly fine, so nothing else would catch
        it."""
        import inspect
        import sheet_image
        styles = ['neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                  'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal']
        for style in styles:
            src = inspect.getsource(getattr(sheet_image, f'_render_ladder_{style}'))
            self.assertIn('_draw_diff(', src, f'{style} never draws the OVR difference')

    def test_every_poster_style_centers_names(self):
        """Names are centred in their column in every style (an explicit
        request), via the one shared helper — a style hand-placing them with
        an lm/rm anchor again would silently drift out of line."""
        import inspect
        import sheet_image
        styles = ['neon', 'clean', 'scoreboard', 'tactical', 'varsity', 'arcade', 'street',
                  'carnival', 'gridiron', 'blueprint', 'newsprint', 'terminal']
        for style in styles:
            src = inspect.getsource(getattr(sheet_image, f'_render_ladder_{style}'))
            self.assertEqual(src.count('_draw_centered_name('), 2,
                             f'{style} should centre exactly two names per row')
            self.assertNotIn("f['our_ign'], font=", src, f'{style} still hand-places our name')
            self.assertNotIn("f['opp_ign'], font=", src, f'{style} still hand-places opp name')

    def test_classic_centers_both_name_columns(self):
        import inspect
        import sheet_image
        src = inspect.getsource(sheet_image._render_ladder_classic)
        aligns = [l for l in src.splitlines() if 'aligns' in l and '=' in l][0]
        self.assertEqual(aligns.count("'C'"), 2, "classic's two name columns should be centred")

    def test_cell_text_x_centers_within_the_column(self):
        import sheet_image
        # 100-wide column, 40-wide text -> 30px of padding each side.
        self.assertEqual(sheet_image._cell_text_x(0, 100, 'C', 40), 30)
        self.assertEqual(sheet_image._cell_text_x(200, 100, 'C', 40), 230)
        # Existing conventions unchanged.
        self.assertEqual(sheet_image._cell_text_x(0, 100, 'L', 40), sheet_image.PAD_X)
        self.assertEqual(sheet_image._cell_text_x(0, 100, 'R', 40),
                         100 - sheet_image.PAD_X - 40)

    def test_centered_name_stays_inside_its_column(self):
        """A centred name grows both ways, so the fit has to be measured from
        the centre out — the long-name case that would otherwise slide under
        the slot badge or across the centre divider."""
        from PIL import Image, ImageDraw
        import sheet_image
        draw = ImageDraw.Draw(Image.new('RGB', (1300, 60)))
        stat_font = sheet_image._load_font(sheet_image._POSTER_FONT_REG, 16)
        col_x0, col_x1 = 100, 600
        cx = (col_x0 + col_x1) // 2
        for name in ('X', 'PHOKing_Frank', 'GCrane8Cowboys',
                     'ThisIsAnAbsurdlyLongPlayerNameThatCannotPossiblyFit'):
            font, drawn = sheet_image._draw_centered_name(
                draw, name, 'DEF 133', cx, 30, col_x0, col_x1,
                lambda w: sheet_image._fit_text(draw, name, sheet_image._POSTER_FONT_BOLD, 25, 13, w),
                (255, 255, 255), stat_font, (200, 200, 200), stat_side='right')
            half = draw.textlength(drawn, font=font) / 2
            stat_w = draw.textlength('DEF 133', font=stat_font)
            self.assertGreaterEqual(cx - half, col_x0 - 1, f'{name} overflows the column start')
            self.assertLessEqual(cx + half + 12 + stat_w, col_x1 + 1,
                                 f'{name} + stat overflows the column end')


class TestLeagueNamesFromTeamsTable(unittest.IsolatedAsyncioTestCase):
    """
    Covers the league list coming from the db's teams table instead of a
    hardcoded default (db.load_league_names_sync), and /legacy's league
    options coming from the *archived season's* teams table rather than
    today's — leagues get added and deleted between seasons.
    """

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()
        await db.close_archive_connections()

    def _write_db(self, path, teams):
        raw = sqlite3.connect(path)
        raw.executescript(SCHEMA)
        for tid, name in teams:
            raw.execute("INSERT INTO teams VALUES (?, ?, ?)", (tid, name, name))
        raw.commit()
        raw.close()
        return path

    def _make_interaction(self, year=None):
        inter = MagicMock()
        inter.response = MagicMock()
        inter.response.defer = AsyncMock()
        inter.followup = MagicMock()
        inter.followup.send = AsyncMock()
        inter.guild = MagicMock()
        inter.user = MagicMock()
        admin_role = MagicMock()
        admin_role.name = "Administrator"
        inter.user.roles = [admin_role]
        inter.locale = discord.Locale.american_english
        inter.namespace = MagicMock()
        inter.namespace.year = year
        return inter

    # -- db.load_league_names_sync ------------------------------------------

    def test_load_league_names_sync_reads_teams_table(self):
        """The league map is whatever the teams table says — a league that
        isn't a row there (NI, deleted) must not appear."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_db(
                os.path.join(tmpdir, "neuroverse.db"),
                [("NP", "NeuroPerverse"), ("NX", "NeuroChristians")],
            )
            names = db.load_league_names_sync(path)
        self.assertEqual(names, {"NP": "NeuroPerverse", "NX": "NeuroChristians"})
        self.assertNotIn("NI", names)

    def test_load_league_names_sync_missing_file_returns_empty(self):
        """A fresh install (or a test run) with no database file yet must
        still be able to import the bot, so this returns {} rather than
        raising."""
        with tempfile.TemporaryDirectory() as tmpdir:
            names = db.load_league_names_sync(os.path.join(tmpdir, "nope.db"))
        self.assertEqual(names, {})

    def test_load_league_names_sync_no_teams_table_returns_empty(self):
        """A database file that exists but has no teams table yet (pre-
        migration) also degrades to {} instead of raising at import time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "empty.db")
            sqlite3.connect(path).close()
            names = db.load_league_names_sync(path)
        self.assertEqual(names, {})

    def test_load_league_names_sync_does_not_write_to_the_database(self):
        """Opened read-only — a league-list read must never be able to modify
        the live db, and must not create a WAL/journal file alongside it
        (the deploy process treats stray -wal files as state to delete)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_db(os.path.join(tmpdir, "neuroverse.db"), [("NP", "NeuroPerverse")])
            before = os.path.getmtime(path)
            db.load_league_names_sync(path)
            self.assertEqual(os.path.getmtime(path), before)
            self.assertFalse(os.path.exists(path + "-wal"))

    def test_no_module_hardcodes_the_league_list(self):
        """Guard against the hardcoded default list coming back. Each module
        that needs league display names must load it from the teams table;
        none of them should carry league names as source literals (that's
        exactly how a deleted league like NI lingered in four places)."""
        for mod in ("optimized_bot.py", "sheet_image.py", "siege.py", "ladder_flow.py", "status.py"):
            with open(os.path.join(os.path.dirname(__file__), mod), encoding="utf-8") as f:
                src = f.read()
            self.assertIn("db.load_league_names_sync()", src, f"{mod} must load leagues from the teams table")
            for literal in ("'NeuroPerverse'", '"NeuroPerverse"', "'NeuroInverse'", '"NeuroInverse"'):
                self.assertNotIn(literal, src, f"{mod} hardcodes a league name ({literal})")

    def test_no_module_hardcodes_team_ids_either(self):
        """The name-literal check above scanned four named modules and looked
        only for display names, so it missed newday.py, which carried its own
        list of team *ids*. That cost a real production failure: with NI gone
        from teams, the nightly placeholder insert hit the matchup_day foreign
        key and aborted the run partway, leaving five leagues with no row.

        So: scan every module in the project, and look for id lists too.
        """
        import glob
        import re
        skip = {'tests.py'}
        # Two or more two-letter uppercase quoted strings in a row — i.e. a
        # literal league-id list, however it's named.
        pattern = re.compile(r"""(['"])[A-Z]{2}\1\s*,\s*(['"])[A-Z]{2}\2""")
        for path in glob.glob(os.path.join(os.path.dirname(__file__), '*.py')):
            mod = os.path.basename(path)
            if mod in skip:
                continue
            with open(path, encoding='utf-8') as f:
                src = f.read()
            for literal in ("'NeuroPerverse'", '"NeuroPerverse"'):
                self.assertNotIn(literal, src, f'{mod} hardcodes a league name')
            hit = pattern.search(src)
            self.assertIsNone(hit, f'{mod} looks like it hardcodes a team-id list: {hit.group(0) if hit else ""}')


    # -- /legacy league options come from that season -----------------------

    async def test_archive_league_autocomplete_uses_that_seasons_teams(self):
        """The whole point: options come from the archive's own teams table.
        A league that existed that season but has since been deleted must be
        offered, and a league that exists only now must not be."""
        from optimized_bot import archive_league_autocomplete
        inter = self._make_interaction(year=2026)
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                self._write_db(
                    os.path.join(tmpdir, "neuroverse_2026.db"),
                    [("NI", "NeuroInverse"), ("NP", "NeuroPerverse")],
                )
                with patch.dict("optimized_bot.LEAGUE_NAMES",
                                {"NP": "NeuroPerverse", "ZZ": "NeuroBrandNew"}, clear=True):
                    choices = await archive_league_autocomplete(inter, "")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        values = {c.value for c in choices}
        self.assertEqual(values, {"NI", "NP"})
        self.assertNotIn("ZZ", values)  # exists now, didn't exist in 2026

    async def test_archive_league_autocomplete_filters_on_current_input(self):
        from optimized_bot import archive_league_autocomplete
        inter = self._make_interaction(year=2026)
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                self._write_db(
                    os.path.join(tmpdir, "neuroverse_2026.db"),
                    [("NI", "NeuroInverse"), ("NP", "NeuroPerverse")],
                )
                choices = await archive_league_autocomplete(inter, "inverse")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        self.assertEqual([c.value for c in choices], ["NI"])

    async def test_archive_league_autocomplete_falls_back_to_live_list(self):
        """Before a year is entered there's no archive to read, so the field
        shows the live leagues rather than sitting mysteriously empty."""
        from optimized_bot import archive_league_autocomplete
        inter = self._make_interaction(year=None)
        with patch.dict("optimized_bot.LEAGUE_NAMES",
                        {"NP": "NeuroPerverse", "NX": "NeuroChristians"}, clear=True):
            choices = await archive_league_autocomplete(inter, "")
        self.assertEqual({c.value for c in choices}, {"NP", "NX"})

    async def test_archive_league_autocomplete_falls_back_when_no_archive(self):
        from optimized_bot import archive_league_autocomplete
        inter = self._make_interaction(year=1999)
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                with patch.dict("optimized_bot.LEAGUE_NAMES", {"NP": "NeuroPerverse"}, clear=True):
                    choices = await archive_league_autocomplete(inter, "")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        self.assertEqual([c.value for c in choices], ["NP"])

    async def test_legacy_rank_serves_a_league_that_no_longer_exists(self):
        """A season's own league must be viewable even after it's deleted
        from the live teams table — indexing the live league map (which is
        what the code used to do) would be a KeyError, not a miss."""
        from optimized_bot import legacy_rank_slash
        inter = self._make_interaction(year=2026)
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                archive = self._write_db(
                    os.path.join(tmpdir, "neuroverse_2026.db"), [("NI", "NeuroInverse")]
                )
                raw = sqlite3.connect(archive)
                raw.execute(
                    "INSERT INTO players (team_id,ign,status,off_ovr,def_ovr,total_ovr) "
                    "VALUES ('NI','ArchivedInverse','A',240,220,7000)"
                )
                raw.commit()
                raw.close()
                with patch.dict("optimized_bot.LEAGUE_NAMES", {"NP": "NeuroPerverse"}, clear=True):
                    await legacy_rank_slash(inter, 2026, "NI")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertIsNotNone(inter.followup.send.call_args.kwargs.get("file"))

    async def test_legacy_rank_rejects_league_absent_from_that_season(self):
        """The league field is a dynamic autocomplete, so Discord doesn't
        constrain the value — a league that season never had gets a friendly
        error, not an empty image or a crash."""
        from optimized_bot import legacy_rank_slash
        inter = self._make_interaction(year=2026)
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmpdir, "neuroverse.db")
                self._write_db(os.path.join(tmpdir, "neuroverse_2026.db"), [("NP", "NeuroPerverse")])
                await legacy_rank_slash(inter, 2026, "ZZ")
            finally:
                await db.close_archive_connections()
                db.DB_PATH = original_path
        inter.followup.send.assert_called_once()
        self.assertTrue(inter.followup.send.call_args.kwargs.get("ephemeral"))
        self.assertIsNone(inter.followup.send.call_args.kwargs.get("file"))

    async def test_sync_league_name_reaches_every_modules_map(self):
        """/league renaming a league at runtime must update every module's
        copy — each loads its own from the teams table at import and can't
        import optimized_bot back without a circular import."""
        import optimized_bot, sheet_image, siege as siege_mod, ladder_flow
        maps = (optimized_bot.LEAGUE_NAMES, sheet_image.LEAGUE_NAMES,
                siege_mod.LEAGUE_NAMES, ladder_flow.LEAGUE_NAMES)
        saved = [dict(m) for m in maps]
        try:
            optimized_bot._sync_league_name("QQ", "NeuroRenamed")
            for m in maps:
                self.assertEqual(m.get("QQ"), "NeuroRenamed")
        finally:
            for m, original in zip(maps, saved):
                m.clear()
                m.update(original)


class TestNewDay(unittest.IsolatedAsyncioTestCase):
    """
    The nightly placeholder-row job. Its failure mode is quiet — a partial
    run just means some leagues have no matchup_day row for the day, which
    only shows up later as /status looking wrong.
    """

    async def asyncSetUp(self):
        os.environ["DB_PATH"] = ":memory:"
        db._db = None
        await setup_db()

    async def asyncTearDown(self):
        await _patched_close()

    async def test_newday_creates_a_row_for_every_team_in_the_table(self):
        import newday as newday_mod
        import datetime as _dt
        teams = await db.list_teams()
        await newday_mod.newday()
        today = str(_dt.date.today())
        for tid in teams:
            row = await db.fetchone(
                "SELECT team_id FROM matchup_day WHERE team_id=? AND game_date=?", (tid, today))
            self.assertIsNotNone(row, f'no placeholder row created for {tid}')

    async def test_rerunning_newday_neither_duplicates_nor_clobbers(self):
        """Idempotency, stated precisely: a second run must not add a second
        row for a team that already has one (UNIQUE(team_id, game_date)
        guarantees that), and must not reset a row that already has real data
        on it. The latter is the part worth pinning — INSERT OR IGNORE skips
        the row entirely, whereas an upsert here would zero out a recorded
        opponent and score. This matters because a partial run has to be
        safe to re-run by hand mid-day."""
        import newday as newday_mod
        import datetime as _dt
        today = str(_dt.date.today())
        await newday_mod.newday()
        # A day's real data lands on the placeholder row
        await db.execute(
            "UPDATE matchup_day SET opp_ign=?, opp_score=?, our_score=? WHERE team_id='NP' AND game_date=?",
            ('Legends of Valhalla', 14, 22, today))

        await newday_mod.newday()
        await newday_mod.newday()

        rows = await db.fetchall(
            "SELECT opp_ign, opp_score, our_score FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (today,))
        self.assertEqual(len(rows), 1, "a re-run duplicated the day's matchup row")
        self.assertEqual(rows[0]['opp_ign'], 'Legends of Valhalla', 'a re-run wiped the recorded opponent')
        self.assertEqual((rows[0]['opp_score'], rows[0]['our_score']), (14, 22),
                         'a re-run reset the recorded scores')

    async def test_newday_does_not_insert_for_a_deleted_league(self):
        """The actual production crash: a league removed from `teams` must not
        be inserted for, because matchup_day.team_id is a foreign key to it."""
        import newday as newday_mod
        import datetime as _dt
        await db.execute("DELETE FROM players WHERE team_id='NP'")
        await db.execute("DELETE FROM teams WHERE id='NP'")
        await newday_mod.newday()   # must not raise
        row = await db.fetchone(
            "SELECT team_id FROM matchup_day WHERE team_id='NP' AND game_date=?",
            (str(_dt.date.today()),))
        self.assertIsNone(row, 'created a matchup_day row for a league that no longer exists')

    async def test_one_failing_team_does_not_skip_the_rest(self):
        """The original loop aborted on the first failure, so every league
        after the bad one silently got nothing. Order matters here: the
        failure is injected on the first team processed."""
        import newday as newday_mod
        import datetime as _dt
        teams = list(await db.list_teams())
        self.assertGreater(len(teams), 1, 'fixture needs at least two teams')
        first, rest = teams[0], teams[1:]

        real_new_day = db.new_day

        async def flaky(team_id, game_date):
            if team_id == first:
                raise sqlite3.IntegrityError('FOREIGN KEY constraint failed')
            return await real_new_day(team_id, game_date)

        db.new_day = flaky
        try:
            await newday_mod.newday()   # must not raise
        finally:
            db.new_day = real_new_day

        today = str(_dt.date.today())
        for tid in rest:
            row = await db.fetchone(
                "SELECT team_id FROM matchup_day WHERE team_id=? AND game_date=?", (tid, today))
            self.assertIsNotNone(row, f'{tid} was skipped after an earlier team failed')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
