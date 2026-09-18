"""
optimized_bot.py — Neuroverse Discord bot with SQLite backend.

All commands upgraded to use discord.ui (buttons, modals, select menus,
autocomplete) where it improves the UX. Administrator operations use slash commands
with modals and confirmation buttons. Gameplay commands (!score, !opp, etc.)
keep their prefix style but get confirmation embeds and buttons.
"""

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
import random
import datetime
import asyncio
from zoneinfo import ZoneInfo
from functools import wraps
import time
import aiohttp
from dotenv import load_dotenv

import db
import ladder_flow
from ladder_flow import start_ladder_flow
import siege
import i18n
from status import get_status
import sheet_image
from sheet_image import send_rank_image, send_stats_image, clear_cache as clear_rank_cache
from newday import newday
from tournament import TournamentManager
tournaments = TournamentManager()
from logger_config import global_logger as logger

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DEV   = os.getenv('DEV')

eastern      = ZoneInfo("America/New_York")
new_day_time = datetime.time(hour=13, minute=0, second=0, tzinfo=eastern)


def game_day() -> datetime.date:
    """
    Return the current 'game day'.
    A game day runs from 1pm ET to 1pm ET the next day.
    Before 1pm ET → yesterday's date (previous game day still active).
    At/after 1pm ET → today's date (new game day has started).
    """
    now = datetime.datetime.now(tz=eastern)
    if now.hour < 13:
        return (now - datetime.timedelta(days=1)).date()
    return now.date()

# The league list comes straight from the db's teams table — there is
# deliberately no hardcoded default to fall back on, so a league added,
# renamed, or deleted there (NI/NeuroInverse, for instance) is reflected on
# the next restart without a code change, and can't silently disagree with
# what the database actually contains.
#
# Loaded synchronously (db.load_league_names_sync, stdlib sqlite3, read-only)
# rather than via the async db layer because LEAGUE_CHOICES below is consumed
# by @app_commands.choices decorators, which run while this module is still
# being imported — before db.init() and before there's an event loop at all.
LEAGUE_NAMES: dict = db.load_league_names_sync()

if not LEAGUE_NAMES:
    logger.error(
        "No leagues loaded from the teams table — every league-scoped command "
        "will register with an empty option list. Check that the database file "
        "exists and is readable, then restart."
    )

LEAGUE_CHOICES = [
    app_commands.Choice(name=name, value=tid)
    for tid, name in LEAGUE_NAMES.items()
]


def _sync_league_name(lid: str, name: str):
    """
    Push a league added or renamed at runtime by /league into every module's
    league-name map.

    sheet_image, siege, and ladder_flow each load their own copy from the
    teams table at import (db.load_league_names_sync) — they can't import
    this module without a circular import — so the new name has to be handed
    to each one explicitly, or /rank's image titles and siege's league labels
    keep showing the old name until the next restart.
    """
    for mapping in (LEAGUE_NAMES, sheet_image.LEAGUE_NAMES,
                    siege.LEAGUE_NAMES, ladder_flow.LEAGUE_NAMES):
        mapping[lid] = name

LADDER_STYLE_CHOICES = [
    app_commands.Choice(name="Classic (data table)", value="classic"),
    app_commands.Choice(name="Neon Clash (hexagon badges)", value="neon"),
    app_commands.Choice(name="Clean Cards (minimal modern)", value="clean"),
    app_commands.Choice(name="Scoreboard (bold broadcast)", value="scoreboard"),
    app_commands.Choice(name="Tactical (military/esports)", value="tactical"),
    app_commands.Choice(name="Varsity (collegiate athletics)", value="varsity"),
    app_commands.Choice(name="Arcade (retro 8-bit)", value="arcade"),
    app_commands.Choice(name="Street (urban/graffiti)", value="street"),
    app_commands.Choice(name="Carnival (playful/bouncy)", value="carnival"),
    app_commands.Choice(name="Gridiron (football field)", value="gridiron"),
    app_commands.Choice(name="Blueprint (technical schematic)", value="blueprint"),
    app_commands.Choice(name="Newsprint (broadsheet sports page)", value="newsprint"),
    app_commands.Choice(name="Terminal (CRT green phosphor)", value="terminal"),
    app_commands.Choice(name="Gators (blue & orange livery)", value="gators"),
    app_commands.Choice(name="LED Board (dot-matrix scoreboard)", value="ledboard"),
    app_commands.Choice(name="Dossier (typewritten scouting file)", value="dossier"),
    app_commands.Choice(name="Game Boy (green LCD)", value="gameboy"),
    app_commands.Choice(name="Cyberdeck (circuit/uplink)", value="cyberdeck"),
    app_commands.Choice(name="Starfield (deep space)", value="starfield"),
    app_commands.Choice(name="Hazard (industrial caution)", value="hazard"),
    app_commands.Choice(name="Bubble (pastel rounded)", value="bubble"),
    app_commands.Choice(name="Sketch (pencil on paper)", value="sketch"),
    app_commands.Choice(name="Prestige (black & gold)", value="prestige"),
    app_commands.Choice(name="Paper (quiet serif ledger)", value="paper"),
    app_commands.Choice(name="Heatmap (rows tinted by mismatch)", value="heatmap"),
]

# Discord allows a hard maximum of 25 choices per command parameter, and the
# list above is exactly at it. A 26th style cannot be added as a static
# choice — it would need an autocomplete callback instead (the same
# mechanism /legacy's league field uses).
assert len(LADDER_STYLE_CHOICES) <= 25, (
    f"{len(LADDER_STYLE_CHOICES)} ladder styles exceeds Discord's 25-choice limit"
)

def _validate_league(league: str, lang: str = 'en') -> str:
    key = league.upper()
    if key not in LEAGUE_NAMES:
        raise ValueError(i18n.t('common.invalid_league', lang, league=league, leagues=', '.join(LEAGUE_NAMES)))
    return key


ADMIN_EQUIVALENT_ROLES = {'Administrator', 'League Owner', 'Madden Admin'}


def _is_admin(interaction: discord.Interaction) -> bool:
    """Check if the user has an admin-equivalent role (Administrator, League Owner, or Madden Admin)."""
    if not interaction.guild:
        return False
    return any(r.name in ADMIN_EQUIVALENT_ROLES for r in interaction.user.roles)


async def _require_admin(interaction: discord.Interaction) -> bool:
    """Send an error and return False if user is not an Administrator."""
    if not _is_admin(interaction):
        lang = i18n.resolve_lang(interaction)
        await interaction.response.send_message(
            i18n.t('common.admin_required', lang), ephemeral=True
        )
        return False
    return True

tournaments: TournamentManager = TournamentManager()

# ============================================================================
# GIF QUEUE
# ============================================================================

gif_queue: asyncio.Queue = asyncio.Queue()
GIF_SEND_INTERVAL = 1.0

async def gif_sender():
    await bot.wait_until_ready()
    logger.info("gif_sender started")
    while not bot.is_closed():
        channel, payload = await gif_queue.get()
        try:
            if isinstance(payload, tuple):
                path, spoiler = payload
                await channel.send(file=discord.File(path, spoiler=spoiler))
            else:
                await channel.send(payload)
        except discord.errors.HTTPException as e:
            if e.status == 429:
                retry_after = float(e.response.headers.get('Retry-After', 5))
                await asyncio.sleep(retry_after)
                await gif_queue.put((channel, payload))
            else:
                logger.error(f"gif_sender HTTPException: {e}")
        except Exception as e:
            logger.error(f"gif_sender error: {e}")
        finally:
            gif_queue.task_done()
            await asyncio.sleep(GIF_SEND_INTERVAL)

# ============================================================================
# ERROR HANDLER
# ============================================================================

def discord_error_handler(func):
    @wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        try:
            return await func(ctx, *args, **kwargs)
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Connection error in {func.__name__}: {e}")
            await asyncio.sleep(3)
            try:
                return await func(ctx, *args, **kwargs)
            except Exception:
                await ctx.send("⚠️ Connection error. Please try again.")
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
    return wrapper

# ============================================================================
# GIF LOADING
# ============================================================================

def load_gif_folder(folder: str) -> list:
    try:
        return [f'{folder}/{f}' for f in os.listdir(folder)]
    except FileNotFoundError:
        logger.warning(f"GIF folder '{folder}' not found")
        return []

def reload_gifs():
    global gif_files, gif_files_bad, gif_files_20, gif_files_22, gif_files_24
    global gif_files_30, gif_files_26, gif_files_18, gif_files_14, gif_files_12
    global gif_files_8, gif_files_6, gif_files_16, gifs_defense, brunson_gifs, bingbonggifs
    gif_files     = load_gif_folder('gifs')
    gif_files_bad = load_gif_folder('gifsbad')
    gif_files_20  = load_gif_folder('gifs20')
    gif_files_22  = load_gif_folder('gifs22')
    gif_files_24  = load_gif_folder('gifs24')
    gif_files_30  = load_gif_folder('gifs30')
    gif_files_26  = load_gif_folder('gifs26')
    gif_files_18  = load_gif_folder('gifs18')
    gif_files_14  = load_gif_folder('gifs14')
    gif_files_12  = load_gif_folder('gifs12')
    gif_files_8   = load_gif_folder('gifs8')
    gif_files_6   = load_gif_folder('gifs6')
    gif_files_16  = load_gif_folder('gifs16')
    gifs_defense  = load_gif_folder('defense')
    brunson_gifs  = load_gif_folder('brunson')
    bingbonggifs  = load_gif_folder('bingbong')

reload_gifs()

def get_score_gif(score: int):
    gif_map = {
        22: gif_files_22, 20: gif_files_20, 24: gif_files_24,
        30: gif_files_30, 26: gif_files_26, 28: gif_files_24,
        18: gif_files_18, 16: gif_files_16, 14: gif_files_14,
        12: gif_files_12,  8: gif_files_8,   6: gif_files_6,
    }
    if score in (19, 21, 23):
        return 'HA! This ^ mf kicking extra points!'
    if score in gif_map and gif_map[score]:
        return random.choice(gif_map[score])
    if score <= 16 and gif_files_bad:
        return random.choice(gif_files_bad)
    return None

# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ============================================================================
# AUTOCOMPLETE HELPERS
# ============================================================================

async def player_autocomplete(interaction: discord.Interaction, current: str):
    rows = await db.fetchall(
        "SELECT DISTINCT ign FROM players WHERE status != 'I' AND ign LIKE ? LIMIT 25",
        (f"{current}%",)
    )
    return [app_commands.Choice(name=r['ign'], value=r['ign']) for r in rows]

async def player_all_autocomplete(interaction: discord.Interaction, current: str):
    """Includes all players including those who left — for /inactive and /transfer."""
    rows = await db.fetchall(
        "SELECT DISTINCT ign FROM players WHERE ign LIKE ? LIMIT 25",
        (f"{current}%",)
    )
    return [app_commands.Choice(name=r['ign'], value=r['ign']) for r in rows]

async def league_player_autocomplete(interaction: discord.Interaction, current: str):
    """
    Same active-roster list the ladder flow uses (team_id + status='A'), for
    any command that already has its own 'league' parameter selected — e.g.
    /siegescore. player_autocomplete searches ALL ~140+ active players across
    every league with no explicit sort order and a hard 25-result cap, so a
    player could easily fall outside the top 25 and simply never appear —
    especially right after a transfer, when an admin is specifically looking
    for someone by name within one league's much smaller roster (~15-25
    players), where they should always be findable regardless of prefix.
    """
    league = interaction.namespace.league
    if not league:
        return []
    rows = await db.fetchall(
        "SELECT ign FROM players WHERE team_id=? AND status='A' AND ign LIKE ? ORDER BY ign LIMIT 25",
        (league, f"{current}%")
    )
    return [app_commands.Choice(name=r['ign'], value=r['ign']) for r in rows]

async def nick_player_autocomplete(interaction: discord.Interaction, current: str):
    """
    For /nick's player field. real_ign is not unique across players (multiple
    people can share the same one), so this can't just autocomplete on that
    text — it shows every match as "real_ign - nickname" and encodes the
    specific player's own id as the choice value, so selecting a suggestion
    always identifies exactly one unambiguous player, never a name string
    that could match more than one row.
    """
    rows = await db.fetchall(
        "SELECT id, ign, real_ign FROM players WHERE (real_ign LIKE ? OR ign LIKE ?) LIMIT 25",
        (f"%{current}%", f"%{current}%")
    )
    return [
        app_commands.Choice(name=f"{r['real_ign']} - {r['ign']}"[:100], value=str(r['id']))
        for r in rows
    ]

# ============================================================================
# SHARED UI COMPONENTS
# ============================================================================

class ConfirmView(View):
    """Generic two-button confirm/cancel view."""
    def __init__(self, on_confirm, on_cancel=None, timeout=30, lang: str = 'en'):
        super().__init__(timeout=timeout)
        self.on_confirm = on_confirm
        self.on_cancel  = on_cancel
        self.lang       = lang

        confirm_btn = Button(label=i18n.t('confirm.btn_confirm', lang), style=discord.ButtonStyle.success)
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

        cancel_btn = Button(label=i18n.t('confirm.btn_cancel', lang), style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    async def _confirm(self, interaction: discord.Interaction):
        self.stop()
        await self.on_confirm(interaction)

    async def _cancel(self, interaction: discord.Interaction):
        self.stop()
        if self.on_cancel:
            await self.on_cancel(interaction)
        else:
            await interaction.response.edit_message(content=i18n.t('confirm.cancelled', self.lang), embed=None, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

# ============================================================================
# SCORE COMMAND — prefix + slash with past matchup dropdown + def OVR field
# ============================================================================

class ScoreModal(Modal, title="Record Score"):
    def __init__(self, player: str, row: dict,
                 game_date=None, matchup=None, channel=None, prefill_score: str = None, lang: str = 'en'):
        super().__init__()
        self.player    = player
        self.row       = row
        self.game_date = game_date or game_day()
        self.matchup   = matchup
        self.channel   = channel
        self.lang      = lang
        self.title     = i18n.t('score.modal.title', lang)

        self.score_val = TextInput(placeholder="e.g. 22, M, or E", max_length=4)
        self.def_ovr = TextInput(placeholder="e.g. 234", max_length=5, required=False)
        self.fourth_downs = TextInput(placeholder="e.g. 3", max_length=3, required=False)
        self.fourth_down_convs = TextInput(placeholder="e.g. 2", max_length=3, required=False)
        self.fumbles = TextInput(placeholder="e.g. 1", max_length=2, required=False)

        self.add_item(discord.ui.Label(text=i18n.t('score.modal.label_score', lang), component=self.score_val))
        self.add_item(discord.ui.Label(text=i18n.t('score.modal.label_def_ovr', lang), component=self.def_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('score.modal.label_4th_att', lang), component=self.fourth_downs))
        self.add_item(discord.ui.Label(text=i18n.t('score.modal.label_4th_conv', lang), component=self.fourth_down_convs))
        self.add_item(discord.ui.Label(text=i18n.t('score.modal.label_fumbles', lang), component=self.fumbles))
        if prefill_score:
            # Defensive second layer beyond score_slash's own validation —
            # Discord rejects modal creation outright (HTTPException, Invalid
            # Form Body) if a default value exceeds the field's max_length,
            # which previously surfaced as an unhandled crash with no
            # message to the user. Truncating here means this can't happen
            # regardless of what any current or future caller passes in.
            self.score_val.default = prefill_score[:self.score_val.max_length]

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        raw = self.score_val.value.strip().upper()
        is_excused = (raw == 'E')
        is_missed  = (raw == 'M')
        if is_excused or is_missed:
            pts = 0
        else:
            try:
                pts = int(raw)
            except ValueError:
                await interaction.response.send_message(
                    i18n.t('score.err.invalid_score', lang), ephemeral=True
                )
                return

        def_ovr_val = None
        if self.def_ovr.value.strip():
            try:
                def_ovr_val = int(self.def_ovr.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('score.err.invalid_def_ovr', lang), ephemeral=True)
                return

        fourth_downs_val = None
        fourth_convs_val = None
        if self.fourth_downs.value.strip():
            try:
                fourth_downs_val = int(self.fourth_downs.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('score.err.invalid_4th_att', lang), ephemeral=True)
                return
        if self.fourth_down_convs.value.strip():
            try:
                fourth_convs_val = int(self.fourth_down_convs.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('score.err.invalid_4th_conv', lang), ephemeral=True)
                return
        if fourth_downs_val is not None and fourth_convs_val is not None:
            if fourth_convs_val > fourth_downs_val:
                await interaction.response.send_message(
                    i18n.t('score.err.convs_exceed', lang), ephemeral=True
                )
                return

        fumbles_val = None
        if self.fumbles.value.strip():
            try:
                fumbles_val = int(self.fumbles.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('score.err.invalid_fumbles', lang), ephemeral=True)
                return

        # Negative numbers are kept as a legacy alias for missed drives, but the
        # stored score is always forced to 0 — missed drives are never a real score.
        is_missed = is_missed or (pts < 0 and not is_excused)
        # An excused entry has no real score at all — NULL, not 0. Storing 0
        # would be a real value sitting in the score column with nothing to
        # mark it as meaningless without also checking is_excused; NULL makes
        # that true everywhere by construction, not just in the places that
        # happen to remember to check the flag.
        if is_excused:
            actual = None
        elif is_missed:
            actual = 0
        else:
            actual = pts

        # team_id at time of game — use the team stored in the matchup snapshot
        # if backfilling, so transferred players stay tied to the right league
        team_override = None
        if self.matchup:
            # Find which team ran this matchup on that date
            team_override = self.matchup.get('team_id') or self.row['team_id']

        try:
            await db.update_player_score(
                self.player, self.game_date, actual,
                is_forfeit=is_missed,
                is_excused=is_excused,
                def_ovr_faced=def_ovr_val,
                team_id_override=team_override,
                fourth_downs=fourth_downs_val,
                fourth_down_convs=fourth_convs_val,
                fumbles=fumbles_val,
            )
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        league      = LEAGUE_NAMES.get(self.row['team_id'], self.row['team_id'])
        date_str    = i18n.t('score.suffix.date', lang, date=self.game_date) if self.game_date != game_day() else ""
        def_str     = i18n.t('score.suffix.def', lang, ovr=def_ovr_val) if def_ovr_val else ""
        missed_str  = i18n.t('score.suffix.missed', lang) if is_missed else (i18n.t('score.suffix.excused', lang) if is_excused else "")
        fourth_str  = ""
        if fourth_downs_val is not None and fourth_convs_val is not None:
            rate = round(fourth_convs_val / fourth_downs_val * 100) if fourth_downs_val else 0
            fourth_str = i18n.t('score.suffix.4th_rate', lang, convs=fourth_convs_val, attempts=fourth_downs_val, rate=rate)
        elif fourth_downs_val is not None:
            fourth_str = i18n.t('score.suffix.4th_noconv', lang, attempts=fourth_downs_val)
        fumbles_str = i18n.t('score.suffix.fumbles', lang, count=fumbles_val) if fumbles_val else ""

        gif_path = get_score_gif(actual) if actual is not None else None
        actual_display = actual if actual is not None else "—"
        await interaction.response.send_message(
            i18n.t('score.success', lang, player=self.player, league=league, actual=actual_display,
                   missed=missed_str, def_str=def_str, fourth=fourth_str, date=date_str) + fumbles_str
        )
        if self.channel and gif_path:
            if gif_path.endswith('.gif'):
                await gif_queue.put((self.channel, (gif_path, False)))
            else:
                await gif_queue.put((self.channel, gif_path))


class PastMatchupSelect(View):
    """
    Shows a dropdown of recent matchups so the user can pick which game
    they are backfilling a score for, then opens the ScoreModal.
    """
    def __init__(self, player: str, row: dict, matchups: list, channel, lang: str = 'en'):
        super().__init__(timeout=60)
        self.player   = player
        self.row      = row
        self.channel  = channel
        self.lang     = lang
        self.matchups = {str(m['game_date']): m for m in matchups}

        options = [discord.SelectOption(
            label=f"{m['game_date']} vs {m['opp_ign']}",
            value=str(m['game_date']),
            description=f"{m['event_type'] or ''} {m['outcome'] or i18n.t('score.past.pending', lang)}".strip() or None
        ) for m in matchups]

        select = Select(placeholder=i18n.t('score.past.placeholder', lang), options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        date_str = interaction.data['values'][0]
        matchup  = self.matchups.get(date_str)
        game_date = datetime.date.fromisoformat(date_str)
        self.stop()
        await interaction.response.send_modal(
            ScoreModal(self.player, self.row, game_date, matchup, self.channel, lang=self.lang)
        )


@tree.command(name="score", description="Record a player's score")
@app_commands.describe(
    player="Player IGN",
    points="Score (M=missed drives, E=excused)",
    matchup="Record for today's matchup or a past one"
)
@app_commands.choices(matchup=[
    app_commands.Choice(name="Today",        value="today"),
    app_commands.Choice(name="Past matchup", value="past"),
])
@app_commands.autocomplete(player=player_autocomplete)
async def score_slash(interaction: discord.Interaction, player: str, points: str,
                      matchup: str = "today"):
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    if matchup == "past":
        matchups = await db.get_recent_matchups(row['team_id'], limit=10)
        if not matchups:
            await interaction.response.send_message(
                i18n.t('score.no_past_matchups', lang),
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            i18n.t('score.past.prompt', lang, player=player),
            view=PastMatchupSelect(player, row, matchups, interaction.channel, lang=lang),
            ephemeral=True
        )
    else:
        # ScoreModal's score field has max_length=4 — a longer prefill value
        # makes Discord reject the modal entirely with an HTTPException
        # (Invalid Form Body), which previously surfaced as an unhandled
        # crash with no message to the user at all. Catch it here instead.
        if points and len(points) > 4:
            await interaction.response.send_message(
                i18n.t('score.err.points_too_long', lang, points=points), ephemeral=True
            )
            return
        await interaction.response.send_modal(
            ScoreModal(player, row, channel=interaction.channel,
                       prefill_score=points if points else None, lang=lang)
        )


# ============================================================================
# OVR COMMAND — slash with modal
# ============================================================================

class OvrModal(Modal, title="Update Team Overall"):
    def __init__(self, player: str, lang: str = 'en'):
        super().__init__()
        self.player = player
        self.lang   = lang
        self.title  = i18n.t('ovr.modal.title', lang)

        # Each TextInput is kept as a direct attribute (self.off_ovr, etc.) so
        # on_submit can keep reading .value exactly as before — the Label
        # wrapper is only needed to carry the (per-language) visible label text,
        # per discord.py 2.6+'s Components V2 modal system. Constructed fresh
        # here with the correct translated text rather than declared as class
        # attributes and mutated afterward, since TextInput.label used to be
        # freely mutable post-construction but its replacement, Label.text,
        # isn't confirmed to support that — building it correctly the first
        # time sidesteps the question entirely.
        self.off_ovr   = TextInput(placeholder="e.g. 240",  max_length=4)
        self.def_ovr   = TextInput(placeholder="e.g. 234",  max_length=4)
        self.total_ovr = TextInput(placeholder="e.g. 7059", max_length=5)

        self.add_item(discord.ui.Label(text=i18n.t('player.field.off_ovr', lang),   component=self.off_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('player.field.def_ovr', lang),   component=self.def_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('player.field.total_ovr', lang), component=self.total_ovr))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            off   = int(self.off_ovr.value)
            deff  = int(self.def_ovr.value)
            total = int(self.total_ovr.value)
        except ValueError:
            await interaction.response.send_message(i18n.t('ovr.err.invalid', lang), ephemeral=True)
            return
        try:
            await db.update_player_ovr(self.player, off, deff, total)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            i18n.t('ovr.success', lang, player=self.player, off=off, deff=deff, total=total)
        )


@tree.command(name="ovr", description="Update a player's team overall")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def ovr_slash(interaction: discord.Interaction, player: str):
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    await interaction.response.send_modal(OvrModal(player, lang=lang))


# ============================================================================
# AVG COMMAND — slash with select menu for type
# ============================================================================

AVG_TYPES = ['Yearly', 'HOF', 'E1', 'E2', 'E3', 'Gold-', '3', '7', '14', '30']

class AvgTypeSelect(View):
    def __init__(self, player: str, lang: str = 'en'):
        super().__init__(timeout=30)
        self.player = player
        self.lang = lang
        select = Select(
            placeholder=i18n.t('avg.select_placeholder', lang),
            options=[discord.SelectOption(label=t, value=t) for t in AVG_TYPES]
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        lang = self.lang
        atype = interaction.data['values'][0]
        self.stop()
        try:
            result = await db.get_player_avg_with_fumble_adj(self.player, atype)
        except ValueError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)
            return
        if result is None:
            await interaction.response.edit_message(
                content=i18n.t('avg.no_avg_found', lang, atype=atype, player=self.player), view=None
            )
            return
        fumble_adj = result['fumble_adjusted_avg']
        fumble_adj_str = f"{fumble_adj:.4f}" if fumble_adj is not None else "—"
        await interaction.response.edit_message(
            content=i18n.t('avg.result', lang, player=self.player, atype=atype,
                            avg=f"{result['avg']:.4f}", fumble_adj_avg=fumble_adj_str),
            view=None
        )


@tree.command(name="avg", description="Get a player's average")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def avg_slash(interaction: discord.Interaction, player: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer(ephemeral=True)
    row = await db.get_player(player)
    if row is None:
        await interaction.followup.send(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    await interaction.followup.send(
        i18n.t('avg.prompt', lang, player=player),
        view=AvgTypeSelect(player, lang=lang),
        ephemeral=True
    )


@tree.command(name="streak", description="Show a player's current hot streaks")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def streak_slash(interaction: discord.Interaction, player: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    streaks = await db.get_player_streaks(player)
    if streaks is None:
        await interaction.followup.send(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    await interaction.followup.send(
        i18n.t('streak.result', lang, player=player,
               kobe_streak=streaks['kobe_streak'], no_drop_streak=streaks['no_drop_streak'])
    )


@tree.command(name="openspots", description="Show how many open roster spots each league has")
async def openspots_slash(interaction: discord.Interaction):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    spots = await db.get_open_spots()
    lines = [
        i18n.t('openspots.line', lang, league=s['name'], open_spots=s['open_spots'], active=s['active_count'])
        for s in spots
    ]
    await interaction.followup.send(
        i18n.t('openspots.header', lang) + "\n" + "\n".join(lines)
    )


# ============================================================================
# STATUS COMMAND
# ============================================================================

@tree.command(name="status", description="Get today's matchup status for a league")
@app_commands.describe(league="League code")
@app_commands.choices(league=LEAGUE_CHOICES)
async def status_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    embed = await get_status(league, lang=lang)
    await interaction.response.send_message(embed=embed)


# ============================================================================
# OPP COMMAND — slash with modal
# ============================================================================

# ============================================================================
# RANK COMMAND
# ============================================================================

@tree.command(name="rank", description="Display the power ranking table for a league")
@app_commands.describe(league="League code")
@app_commands.choices(league=LEAGUE_CHOICES)
async def rank_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    await interaction.response.defer()
    ctx_like = await bot.get_context(await interaction.original_response())

    class InteractionCtx:
        channel = interaction.channel
        async def send(self, *args, **kwargs):
            await interaction.followup.send(*args, **kwargs)

    await send_rank_image(InteractionCtx(), league, use_cache=True)


@tree.command(name="stats", description="View league-wide averages for a team")
@app_commands.describe(
    league="League code",
    include_inactive="Include inactive/former players in this league (default: false)"
)
@app_commands.choices(league=LEAGUE_CHOICES)
async def stats_slash(interaction: discord.Interaction, league: str, include_inactive: bool = False):
    if not await _require_admin(interaction): return
    await interaction.response.defer()

    class InteractionCtx:
        channel = interaction.channel
        async def send(self, *args, **kwargs):
            await interaction.followup.send(*args, **kwargs)

    await send_stats_image(InteractionCtx(), league, include_inactive=include_inactive)


# ============================================================================
# LEGACY COMMAND GROUP — read-only lookups against an archived past season
# ============================================================================
# Each subcommand is the same as its live counterpart, with the same
# arguments, plus a "year" argument selecting which archived season database
# to read from (e.g. year:2026 -> neuroverse_2026.db, see db.get_archive_conn).
# Strictly read-only — archive connections are opened in SQLite's own
# read-only URI mode, so there's no path by which a /legacy command could
# accidentally write to a past season's data.

legacy_group = app_commands.Group(name="legacy", description="View stats from a previous, archived season")


async def archive_league_autocomplete(interaction: discord.Interaction, current: str):
    """
    League options for /legacy, pulled from *that season's own* teams table
    rather than the live one. Leagues change year over year — a season's
    archive can contain a league that has since been deleted, and miss one
    created afterward — so the live list is the wrong list for a past season.

    This has to be an autocomplete rather than @app_commands.choices: static
    choices are fixed when the command is registered with Discord and can't
    depend on another argument's value. Reading the already-entered year off
    interaction.namespace (the same mechanism league_player_autocomplete uses
    for its league) is the only way league options can follow year.

    Falls back to the live league list when year isn't filled in yet, isn't a
    valid year, or has no archive — so the field is never mysteriously empty
    while someone is still typing. The commands themselves re-validate the
    league against the archive (see _resolve_archive_league), since an
    autocomplete only suggests values and never restricts what Discord will
    accept.
    """
    names = None
    year = getattr(interaction.namespace, 'year', None)
    if year is not None:
        try:
            conn = await db.get_archive_conn(int(year))
        except (TypeError, ValueError):
            conn = None
        if conn is not None:
            names = await db.list_teams(conn=conn)
    if names is None:
        names = LEAGUE_NAMES

    cur = (current or "").lower()
    return [
        app_commands.Choice(name=name, value=tid)
        for tid, name in names.items()
        if cur in tid.lower() or cur in name.lower()
    ][:25]


async def _resolve_archive_league(interaction: discord.Interaction, conn, league: str, lang: str) -> str | None:
    """
    Validate a /legacy league against that season's own teams table, returning
    its display name for that season — or None after sending an error message.

    Two reasons this can't just index LEAGUE_NAMES the way the live commands
    do: the league field is a dynamic autocomplete (see
    archive_league_autocomplete), so Discord doesn't constrain the value for
    us; and a league that existed in the archived season may not exist today,
    which would be a KeyError on the live map rather than a perfectly valid
    lookup against the archive.

    Assumes the interaction is already deferred — every /legacy command defers
    before opening its archive connection.
    """
    names = await db.list_teams(conn=conn)
    if league not in names:
        await interaction.followup.send(
            i18n.t('common.invalid_league', lang, league=league,
                   leagues=', '.join(names) or '—'),
            ephemeral=True
        )
        return None
    return names[league]


@legacy_group.command(name="rank", description="Display the power ranking table for a league from a past season")
@app_commands.describe(year="Season year (e.g. 2026)", league="League (options come from that season)")
@app_commands.autocomplete(league=archive_league_autocomplete)
async def legacy_rank_slash(interaction: discord.Interaction, year: int, league: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    league_name = await _resolve_archive_league(interaction, conn, league, lang)
    if league_name is None:
        return

    class InteractionCtx:
        channel = interaction.channel
        async def send(self, *args, **kwargs):
            await interaction.followup.send(*args, **kwargs)

    await send_rank_image(InteractionCtx(), league, conn=conn, league_name=league_name,
                          season_label=i18n.t('legacy.season_label', lang, year=year))


@legacy_group.command(name="stats", description="View league-wide averages for a team from a past season")
@app_commands.describe(
    year="Season year (e.g. 2026)",
    league="League (options come from that season)",
    include_inactive="Include inactive/former players in this league (default: false)"
)
@app_commands.autocomplete(league=archive_league_autocomplete)
async def legacy_stats_slash(interaction: discord.Interaction, year: int, league: str, include_inactive: bool = False):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    league_name = await _resolve_archive_league(interaction, conn, league, lang)
    if league_name is None:
        return

    class InteractionCtx:
        channel = interaction.channel
        async def send(self, *args, **kwargs):
            await interaction.followup.send(*args, **kwargs)

    await send_stats_image(
        InteractionCtx(), league, include_inactive=include_inactive,
        conn=conn, league_name=league_name,
        season_label=i18n.t('legacy.season_label', lang, year=year)
    )


@legacy_group.command(name="player", description="View a player's full stats card from a past season")
@app_commands.describe(player="Player IGN (as it was during that season)", year="Season year (e.g. 2026)")
async def legacy_player_slash(interaction: discord.Interaction, player: str, year: int):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    row = await db.get_player(player, conn=conn)
    if row is None:
        await interaction.followup.send(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    embed = await _build_player_card_embed(
        player, row, lang, conn=conn, season_label=i18n.t('legacy.season_label', lang, year=year)
    )
    await interaction.followup.send(embed=embed)


@legacy_group.command(name="history", description="View a player's score history over a date range from a past season")
@app_commands.describe(
    player="Player IGN (as it was during that season)",
    start="Start date (YYYY-MM-DD)",
    year="Season year (e.g. 2026)",
    end="End date (YYYY-MM-DD), defaults to start date",
)
async def legacy_history_slash(interaction: discord.Interaction, player: str, start: str, year: int, end: str = None):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    try:
        start_date = datetime.date.fromisoformat(start)
    except ValueError:
        await interaction.followup.send(i18n.t('history.err.start_date', lang), ephemeral=True)
        return

    if end is None:
        end_date = start_date
    else:
        try:
            end_date = datetime.date.fromisoformat(end)
        except ValueError:
            await interaction.followup.send(i18n.t('history.err.end_date', lang), ephemeral=True)
            return

    if end_date < start_date:
        await interaction.followup.send(i18n.t('history.err.end_before_start', lang), ephemeral=True)
        return

    season_label = i18n.t('legacy.season_label', lang, year=year)
    embed = await _build_history_embed(player, start_date, end_date, lang, conn=conn, season_label=season_label)
    if embed is None:
        await interaction.followup.send(
            i18n.t('history.no_scores', lang, player=player, start=start_date, end=end_date)
        )
        return
    await interaction.followup.send(embed=embed)


@legacy_group.command(name="scores", description="View scores for a league across a date range as a grid, from a past season")
@app_commands.describe(
    year="Season year (e.g. 2026)",
    league="League (options come from that season)",
    start="Start date (YYYY-MM-DD)",
    end="End date (YYYY-MM-DD), defaults to start date"
)
@app_commands.autocomplete(league=archive_league_autocomplete)
async def legacy_scores_slash(interaction: discord.Interaction, year: int, league: str, start: str, end: str = None):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    league_name = await _resolve_archive_league(interaction, conn, league, lang)
    if league_name is None:
        return

    try:
        start_date = datetime.date.fromisoformat(start)
    except ValueError:
        await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
        return

    if end is None:
        end_date = start_date
    else:
        try:
            end_date = datetime.date.fromisoformat(end)
        except ValueError:
            await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    if end_date < start_date:
        await interaction.followup.send(i18n.t('scores.err.range_order', lang), ephemeral=True)
        return

    season_label = i18n.t('legacy.season_label', lang, year=year)
    result = await _build_scores_result(league, start_date, end_date, lang, conn=conn, season_label=season_label)
    if result is None:
        await interaction.followup.send(
            i18n.t('scores.no_scores_range', lang, league=league_name, start=start_date, end=end_date)
        )
        return
    buf, content = result
    await interaction.followup.send(
        content=content or None,
        file=discord.File(buf, filename=f"{league}_scores_{year}.png")
    )


@legacy_group.command(name="show_ladder", description="Display the ladder matchups for a league from a past season")
@app_commands.describe(
    year="Season year (e.g. 2026)",
    league="League to display (options come from that season)",
    date="Date (YYYY-MM-DD), defaults to the season's last recorded date",
    style="Visual style for the image (defaults to Classic)"
)
@app_commands.choices(style=LADDER_STYLE_CHOICES)
@app_commands.autocomplete(league=archive_league_autocomplete)
async def legacy_show_ladder_slash(interaction: discord.Interaction, year: int, league: str, date: str = None, style: str = "classic"):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    conn = await db.get_archive_conn(year)
    if conn is None:
        await interaction.followup.send(i18n.t('legacy.err.no_archive', lang, year=year), ephemeral=True)
        return

    league_name = await _resolve_archive_league(interaction, conn, league, lang)
    if league_name is None:
        return

    if date is None:
        # No "today" in an archived season — fall back to the latest date
        # that season actually has ladder data for.
        latest = await db.fetchone(
            "SELECT MAX(game_date) AS d FROM matchup_ladder WHERE team_id=?", (league,), conn=conn
        )
        if latest and latest.get('d'):
            game_date = datetime.date.fromisoformat(latest['d'])
        else:
            game_date = datetime.date(year, 1, 1)  # arbitrary; get_ladder's static fallback will be used
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    season_label = i18n.t('legacy.season_label', lang, year=year)
    buf = await _build_ladder_image(league, game_date, conn=conn, season_label=season_label,
                                    style=style, league_name=league_name)
    if buf is None:
        await interaction.followup.send(
            i18n.t('ladder_cmd.err.no_data', lang, league=league_name), ephemeral=True
        )
        return

    await interaction.followup.send(
        file=discord.File(buf, filename=f"ladder_{league_name}_{year}.png")
    )


tree.add_command(legacy_group)


# ============================================================================
# SCORES COMMAND
# ============================================================================

async def _build_scores_result(league: str, start_date, end_date, lang: str, conn=None, season_label: str | None = None):
    """
    Shared logic for /scores and /legacy scores.
    Returns (image_buffer, legend_content) or None if there are no scores in range.
    """
    num_days = (end_date - start_date).days + 1
    dates = [(start_date + datetime.timedelta(days=i)).isoformat() for i in range(num_days)]

    rows = await db.fetchall(
        """
        SELECT p.ign, gs.game_date, gs.score, gs.is_forfeit, gs.is_excused
        FROM game_scores gs JOIN players p ON p.id = gs.player_id
        WHERE gs.team_id = ? AND gs.game_date BETWEEN ? AND ?
        """,
        (league, str(start_date), str(end_date)), conn=conn
    )

    if not rows:
        return None

    # Roster order matches /rank's convention (sorted by pwr_rank)
    roster = await db.get_rank_table(league, conn=conn)
    roster_igns = [r['ign'] for r in roster]

    # Any player who scored in this range but isn't on the current active
    # roster (transferred, deactivated since) still gets a row — nothing
    # from this range should silently disappear.
    scored_igns = {r['ign'] for r in rows}
    all_igns = roster_igns + [ign for ign in sorted(scored_igns) if ign not in roster_igns]

    by_player = {ign: {} for ign in all_igns}
    for r in rows:
        if r['is_excused']:
            cell = 'E'
        elif r['is_forfeit']:
            cell = 'M'
        elif r['score'] is not None:
            cell = f"{r['score']:.0f}"
        else:
            cell = None
        by_player[r['ign']][r['game_date']] = cell

    roster_rows = [{'ign': ign, 'scores': by_player[ign]} for ign in all_igns]

    # Team total per date (real scores only — excused/missing contribute nothing)
    totals_by_date = {}
    for d in dates:
        total = sum(
            r['score'] for r in rows
            if r['game_date'] == d and not r['is_forfeit'] and not r['is_excused'] and r['score'] is not None
        )
        totals_by_date[d] = total
    roster_rows.append({
        'ign': i18n.t('scores.total_row_label', lang),
        'scores': {d: f"{totals_by_date[d]:.0f}" for d in dates}
    })

    from sheet_image import render_scores_grid
    title = i18n.t('scores.grid_title', lang, league=LEAGUE_NAMES[league], start=start_date, end=end_date)
    if season_label:
        title += f"  {season_label}"
    buf = render_scores_grid(title, dates, roster_rows)

    # Matchup legend (opponent per date) sent as message content alongside the image
    matchups = await db.fetchall(
        "SELECT game_date, opp_ign FROM matchup_day WHERE team_id=? AND game_date BETWEEN ? AND ? AND opp_ign IS NOT NULL ORDER BY game_date",
        (league, str(start_date), str(end_date)), conn=conn
    )
    content = ""
    if matchups:
        legend_lines = [i18n.t('scores.legend_line', lang, date=m['game_date'][5:], opp=m['opp_ign']) for m in matchups]
        content = i18n.t('scores.legend_title', lang) + "\n" + "\n".join(legend_lines)

    return buf, content


@tree.command(name="scores", description="View scores for a league across a date range as a grid")
@app_commands.describe(
    league="League code",
    start="Start date (YYYY-MM-DD), defaults to today",
    end="End date (YYYY-MM-DD), defaults to start date"
)
@app_commands.choices(league=LEAGUE_CHOICES)
async def scores_slash(interaction: discord.Interaction, league: str, start: str = None, end: str = None):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()

    if start is None:
        start_date = game_day()
    else:
        try:
            start_date = datetime.date.fromisoformat(start)
        except ValueError:
            await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    if end is None:
        end_date = start_date
    else:
        try:
            end_date = datetime.date.fromisoformat(end)
        except ValueError:
            await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    if end_date < start_date:
        await interaction.followup.send(i18n.t('scores.err.range_order', lang), ephemeral=True)
        return

    result = await _build_scores_result(league, start_date, end_date, lang)
    if result is None:
        await interaction.followup.send(
            i18n.t('scores.no_scores_range', lang, league=LEAGUE_NAMES[league], start=start_date, end=end_date)
        )
        return
    buf, content = result

    await interaction.followup.send(
        content=content or None,
        file=discord.File(buf, filename=f"{league}_scores.png")
    )


# ============================================================================
# PLAYER CARD — /player command with full stats embed
# ============================================================================

def _fmt_avg_with_fumble_adj(plain: float | None, fumble_adj: float | None, lang: str) -> str:
    """Combined 'plain (FA: fumble_adj)' display for one average — folding
    both numbers into a single field's value, not a separate field per
    average, to stay within Discord's 25-fields-per-embed limit once all
    10 averages need to show their fumble-adjusted counterpart too, not
    just yearly."""
    if plain is None:
        return "—"
    plain_str = f"{plain:.2f}"
    if fumble_adj is None:
        return plain_str
    return i18n.t('player.avg_with_fumble_adj', lang, plain=plain_str, fumble_adj=f"{fumble_adj:.2f}")


async def _build_player_card_embed(player: str, row: dict, lang: str, conn=None, season_label: str | None = None) -> discord.Embed:
    """
    Shared player-card embed builder for /player and /legacy player.
    row: the player row already looked up by the caller (via db.get_player).
    conn: optional archive connection (see db.get_archive_conn) for /legacy.
    """
    league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])
    status = i18n.t('player.status_active', lang) if row['status'] == 'A' else i18n.t('player.status_inactive', lang)
    stats  = await db.get_player_stats(row['id'], row['team_id'], conn=conn)

    title = f"🏈 {player}"
    if season_label:
        title += f"  {season_label}"
    embed = discord.Embed(title=title, color=discord.Color.blurple())
    embed.add_field(name=i18n.t('player.field.league', lang),    value=league,                                        inline=True)
    embed.add_field(name=i18n.t('player.field.status', lang),    value=status,                                        inline=True)
    embed.add_field(name=i18n.t('player.field.pwr_rank', lang),  value=f"{stats['pwr_rank']:.2f}"   if stats['pwr_rank']    else "—", inline=True)
    embed.add_field(name=i18n.t('player.field.off_ovr', lang),   value=str(row['off_ovr']   or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.def_ovr', lang),   value=str(row['def_ovr']   or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.total_ovr', lang), value=str(row['total_ovr'] or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.games', lang),     value=str(stats['games']   or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.points', lang),    value=str(stats['points']  or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.kobes', lang),     value=str(stats['kobes']   or "—"),                  inline=True)

    # All 10 averages, each showing its fumble-adjusted counterpart inline
    # (see _fmt_avg_with_fumble_adj) — not just yearly, and not just the 6
    # averages that used to be the only ones shown here at all; 30-day,
    # 14-day, E3, and Gold- are new additions to this card specifically so
    # their fumble-adjusted values have somewhere to go.
    for field_key, plain_key, fa_key in [
        ('yearly_avg', 'avg_yearly', 'avg_yearly_fumble_adj'),
        ('30day_avg',  'avg_30day',  'avg_30day_fumble_adj'),
        ('14day_avg',  'avg_14day',  'avg_14day_fumble_adj'),
        ('7day_avg',   'avg_7day',   'avg_7day_fumble_adj'),
        ('3day_avg',   'avg_3day',   'avg_3day_fumble_adj'),
        ('hof_avg',    'hof_avg',    'hof_avg_fumble_adj'),
        ('e1_avg',     'e1_avg',     'e1_avg_fumble_adj'),
        ('e2_avg',     'e2_avg',     'e2_avg_fumble_adj'),
        ('e3_avg',     'e3_avg',     'e3_avg_fumble_adj'),
        ('gold_avg',   'gold_avg',   'gold_avg_fumble_adj'),
    ]:
        embed.add_field(
            name=i18n.t(f'player.field.{field_key}', lang),
            value=_fmt_avg_with_fumble_adj(stats[plain_key], stats[fa_key], lang),
            inline=True
        )

    embed.add_field(name=i18n.t('player.field.3td_pct', lang),   value=f"{stats['three_td_pct']:.1%}" if stats['three_td_pct'] else "—", inline=True)
    embed.add_field(name=i18n.t('player.field.2pt_pct', lang),   value=f"{stats['two_pt_pct']:.1%}"   if stats['two_pt_pct']   else "—", inline=True)
    embed.add_field(name=i18n.t('player.field.fumbles', lang),   value=str(stats['fumbles'] or "—"),                  inline=True)
    embed.add_field(name=i18n.t('player.field.missed_drives', lang), value=str(stats['missed_drives'] or "0"),         inline=True)

    fourth = await db.get_player_fourth_down_rate(player, conn=conn)
    if fourth and fourth['attempts']:
        rate_str = f"{fourth['conv_rate']}%" if fourth['conv_rate'] is not None else "—"
        embed.add_field(name=i18n.t('player.field.4th_downs', lang), value=f"{fourth['conversions']}/{fourth['attempts']} ({rate_str})", inline=True)

    return embed


@tree.command(name="player", description="View a player's full stats card")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def player_slash(interaction: discord.Interaction, player: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    row = await db.get_player(player)
    if row is None:
        await interaction.followup.send(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    embed = await _build_player_card_embed(player, row, lang)
    await interaction.followup.send(embed=embed)


# ============================================================================
# DSCORE COMMAND — defensive score tracking (points allowed + avg off OVR faced)
# ============================================================================

_VALID_DRIVE_OUTCOMES = {'0', '1', '2', '3', '4', '5', '6', '7', '8', 'F', 'I', 'S'}

def _parse_drive_outcome(raw: str) -> str | None:
    """
    A single drive-outcome value: '' -> None (not entered), '0'-'8' -> points
    allowed on that drive, 'F'/'I'/'S' (case-insensitive) -> fumble/
    interception/safety turnover. Raises ValueError on anything else.
    """
    raw = raw.strip().upper()
    if not raw:
        return None
    if raw in _VALID_DRIVE_OUTCOMES:
        return raw
    raise ValueError(raw)


def _dscore_build_drive_modal(drive_num: int, drive_outcomes: list, player: str, game_date,
                               points_allowed: int, lang: str = 'en'):
    """Picks the right modal type for a given drive based on its already-known outcome."""
    outcome = drive_outcomes[drive_num - 1]
    if outcome in ('F', 'I', 'S'):
        return DscoreTurnoverModal(player, game_date, drive_num, outcome, drive_outcomes, points_allowed, lang)
    return DscoreDriveModal(player, game_date, drive_num, outcome, drive_outcomes, points_allowed, lang)


async def _dscore_advance_or_finish(interaction: discord.Interaction, player: str, game_date,
                                     drive_num: int, drive_outcomes: list, points_allowed: int, lang: str):
    """
    After a drive's detail has been saved: if more drives remain, prompt to
    continue via a button (Discord never allows a modal to be opened directly
    from within another modal's on_submit — only from a slash command or a
    component interaction like a button click). If this was the last drive,
    finalize the average OVR and send the final confirmation.
    """
    if drive_num < 3:
        next_num = drive_num + 1
        view = DscoreContinueView(player, game_date, next_num, drive_outcomes, points_allowed, lang)
        await interaction.response.send_message(
            i18n.t('dscore.continue_prompt', lang, n=drive_num, next=next_num), view=view
        )
        return

    await db.finalize_dscore_avg_ovr(player, game_date)
    row = await db.get_player_dscore(player, game_date)
    date_str = i18n.t('score.suffix.date', lang, date=game_date) if game_date != game_day() else ""
    ovr_str = i18n.t('dscore.suffix.ovr', lang, ovr=f"{row['avg_off_ovr_faced']:g}") if row and row.get('avg_off_ovr_faced') is not None else ""

    ovr_cols = {1: 'drive1_ovr', 2: 'drive2_ovr', 3: 'drive3_ovr'}
    drives_summary = ", ".join(
        f"D{n}: {drive_outcomes[n-1]}" + (f" (OVR {row[ovr_cols[n]]})" if row and row.get(ovr_cols[n]) is not None else "")
        for n in (1, 2, 3)
    )
    drives_str = i18n.t('dscore.suffix.drives', lang, summary=drives_summary)

    placeholder_dash = "—"
    play_cols = {1: ("drive1_turnover_down", "drive1_turnover_distance", "drive1_turnover_play", "drive1_turnover_forced_by"),
                 2: ("drive2_turnover_down", "drive2_turnover_distance", "drive2_turnover_play", "drive2_turnover_forced_by"),
                 3: ("drive3_turnover_down", "drive3_turnover_distance", "drive3_turnover_play", "drive3_turnover_forced_by")}
    play_lines = []
    for n in (1, 2, 3):
        if drive_outcomes[n - 1] not in ('F', 'I', 'S'):
            continue
        down_c, dist_c, play_c, fb_c = play_cols[n]
        type_name = i18n.t(f"dscore.turnover_type.{drive_outcomes[n-1]}", lang)
        play_lines.append(i18n.t(
            'dscore.turnover_success.play_line', lang, n=n, type=type_name,
            down=(row[down_c] if row and row.get(down_c) else placeholder_dash),
            distance=(row[dist_c] if row and row.get(dist_c) else placeholder_dash),
            play=(row[play_c] if row and row.get(play_c) else placeholder_dash),
            forced_by=(row[fb_c] if row and row.get(fb_c) else placeholder_dash),
        ))
    plays_block = ("\n" + "\n".join(play_lines)) if play_lines else ""

    await interaction.response.send_message(
        i18n.t('dscore.success', lang, player=player, allowed=points_allowed,
               ovr=ovr_str, drives=drives_str, date=date_str) + plays_block
    )


class DscoreContinueView(discord.ui.View):
    """One button: clicking it opens the next drive's modal (normal or
    turnover, whichever that drive's already-known outcome calls for)."""
    def __init__(self, player: str, game_date, drive_num: int, drive_outcomes: list,
                 points_allowed: int, lang: str = 'en'):
        super().__init__(timeout=300)
        self.player = player
        self.game_date = game_date
        self.drive_num = drive_num
        self.drive_outcomes = drive_outcomes
        self.points_allowed = points_allowed
        self.lang = lang

        button = Button(label=i18n.t('dscore.continue_button.label', lang, n=drive_num),
                         style=discord.ButtonStyle.primary)
        button.callback = self._on_click
        self.add_item(button)

    async def _on_click(self, interaction: discord.Interaction):
        modal = _dscore_build_drive_modal(
            self.drive_num, self.drive_outcomes, self.player, self.game_date,
            self.points_allowed, self.lang
        )
        await interaction.response.send_modal(modal)


class DscoreDriveModal(Modal, title="Drive Detail"):
    """A normal (non-turnover) drive: tracks only the opposing player's OVR faced."""
    def __init__(self, player: str, game_date, drive_num: int, drive_outcome: str,
                 drive_outcomes: list, points_allowed: int, lang: str = 'en'):
        super().__init__()
        self.player = player
        self.game_date = game_date
        self.drive_num = drive_num
        self.drive_outcomes = drive_outcomes
        self.points_allowed = points_allowed
        self.lang = lang
        self.title = i18n.t('dscore.modal.title_drive', lang, n=drive_num)

        self.ovr = TextInput(placeholder="e.g. 235", max_length=5, required=False)
        self.add_item(discord.ui.Label(text=i18n.t('dscore.modal.label_ovr', lang), component=self.ovr))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        ovr_val = None
        if self.ovr.value.strip():
            try:
                ovr_val = int(self.ovr.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('dscore.err.invalid_avg_ovr', lang), ephemeral=True)
                return

        await db.update_dscore_drive_detail(self.player, self.game_date, self.drive_num, ovr_val)
        await _dscore_advance_or_finish(
            interaction, self.player, self.game_date, self.drive_num,
            self.drive_outcomes, self.points_allowed, lang
        )


class DscoreTurnoverModal(Modal, title="Drive Turnover"):
    """A turnover drive: tracks OVR faced plus down/distance/play/forced-by."""
    def __init__(self, player: str, game_date, drive_num: int, drive_type: str,
                 drive_outcomes: list, points_allowed: int, lang: str = 'en'):
        super().__init__()
        self.player = player
        self.game_date = game_date
        self.drive_num = drive_num
        self.drive_type = drive_type
        self.drive_outcomes = drive_outcomes
        self.points_allowed = points_allowed
        self.lang = lang

        type_name = i18n.t(f'dscore.turnover_type.{drive_type}', lang)
        self.title = i18n.t('dscore.turnover_modal.title', lang, n=drive_num, type=type_name)

        self.ovr = TextInput(placeholder="e.g. 235", max_length=5, required=False)
        self.down = TextInput(placeholder=i18n.t('dscore.turnover_modal.placeholder_down', lang),
                               max_length=10, required=False)
        self.distance = TextInput(placeholder=i18n.t('dscore.turnover_modal.placeholder_distance', lang),
                                   max_length=10, required=False)
        self.play = TextInput(placeholder=i18n.t('dscore.turnover_modal.placeholder', lang),
                               max_length=200, required=False)
        self.forced_by = TextInput(placeholder=i18n.t('dscore.turnover_modal.placeholder_forced_by', lang),
                                    max_length=50, required=False)

        self.add_item(discord.ui.Label(text=i18n.t('dscore.modal.label_ovr', lang), component=self.ovr))
        self.add_item(discord.ui.Label(text=i18n.t('dscore.turnover_modal.label_down', lang), component=self.down))
        self.add_item(discord.ui.Label(text=i18n.t('dscore.turnover_modal.label_distance', lang), component=self.distance))
        self.add_item(discord.ui.Label(text=i18n.t('dscore.turnover_modal.label_play', lang), component=self.play))
        self.add_item(discord.ui.Label(text=i18n.t('dscore.turnover_modal.label_forced_by', lang), component=self.forced_by))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        ovr_val = None
        if self.ovr.value.strip():
            try:
                ovr_val = int(self.ovr.value.strip())
            except ValueError:
                await interaction.response.send_message(i18n.t('dscore.err.invalid_avg_ovr', lang), ephemeral=True)
                return

        down_val      = self.down.value.strip() or None
        distance_val  = self.distance.value.strip() or None
        play_val      = self.play.value.strip() or None
        forced_by_val = self.forced_by.value.strip() or None

        await db.update_dscore_drive_detail(
            self.player, self.game_date, self.drive_num, ovr_val,
            down_val, distance_val, play_val, forced_by_val
        )
        await _dscore_advance_or_finish(
            interaction, self.player, self.game_date, self.drive_num,
            self.drive_outcomes, self.points_allowed, lang
        )


def _parse_dscore_drives(drive1: str, drive2: str, drive3: str) -> tuple[list[str], int]:
    """
    Parses and validates all 3 drive-outcome strings, shared by /dscore and
    /dscore_multiple so both stay identical on this point. Returns
    (drive_outcomes, points_allowed). Raises ValueError with the 1-based
    drive number (1, 2, or 3) as the exception's message if that drive's
    value isn't valid — the caller maps this back to a translated, labeled
    error message, since only the caller knows which i18n label goes with
    which drive number.
    """
    drive_outcomes = []
    for i, raw in enumerate((drive1, drive2, drive3), start=1):
        try:
            parsed = _parse_drive_outcome(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValueError(str(i))
        drive_outcomes.append(parsed)
    points_allowed = sum(int(v) for v in drive_outcomes if v not in ('F', 'I', 'S'))
    return drive_outcomes, points_allowed


@tree.command(name="dscore", description="Record a player's defensive score for a day (one opponent faced all 3 drives)")
@app_commands.describe(
    player="Player IGN",
    drive1="1st Drive (0-8/F/I/S)",
    drive2="2nd Drive (0-8/F/I/S)",
    drive3="3rd Drive (0-8/F/I/S)",
    ovr="Offensive OVR of the player who faced them (applied to all 3 drives)",
    date="Date (YYYY-MM-DD), defaults to today",
)
@app_commands.autocomplete(player=player_autocomplete)
async def dscore_slash(interaction: discord.Interaction, player: str, drive1: str, drive2: str, drive3: str,
                        ovr: int, date: str = None):
    """
    Simplified path for the common case in this game's ecosystem: the same
    single opponent plays all 3 drives against a given player, so there's
    only one OVR to record, not three. No modal at all — everything is an
    inline slash-command argument, including the OVR (unlike
    /dscore_multiple, which opens a modal per drive specifically because
    a different opponent could have faced each one).
    """
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    if date is None:
        game_date = game_day()
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    drive_labels = [
        i18n.t('dscore.modal.label_drive1', lang),
        i18n.t('dscore.modal.label_drive2', lang),
        i18n.t('dscore.modal.label_drive3', lang),
    ]
    try:
        drive_outcomes, points_allowed = _parse_dscore_drives(drive1, drive2, drive3)
    except ValueError as e:
        label = drive_labels[int(str(e)) - 1]
        await interaction.response.send_message(
            i18n.t('dscore.err.invalid_drive', lang, label=label), ephemeral=True
        )
        return

    try:
        await db.update_player_dscore_single_opponent(player, game_date, points_allowed, ovr, *drive_outcomes)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return

    date_str = i18n.t('score.suffix.date', lang, date=game_date) if game_date != game_day() else ""
    ovr_str = i18n.t('dscore.suffix.ovr', lang, ovr=f"{ovr:g}")
    drives_summary = ", ".join(f"D{n}: {drive_outcomes[n-1]}" for n in (1, 2, 3))
    drives_str = i18n.t('dscore.suffix.drives', lang, summary=drives_summary)

    await interaction.response.send_message(
        i18n.t('dscore.success', lang, player=player, allowed=points_allowed,
               ovr=ovr_str, drives=drives_str, date=date_str)
    )


@tree.command(name="dscore_multiple", description="Record a player's defensive score for a day, drive by drive (different opponents per drive)")
@app_commands.describe(
    player="Player IGN",
    drive1="1st Drive (0-8/F/I/S)",
    drive2="2nd Drive (0-8/F/I/S)",
    drive3="3rd Drive (0-8/F/I/S)",
    date="Date (YYYY-MM-DD), defaults to today",
)
@app_commands.autocomplete(player=player_autocomplete)
async def dscore_multiple_slash(interaction: discord.Interaction, player: str, drive1: str, drive2: str, drive3: str,
                                 date: str = None):
    """
    Full drive-by-drive flow, unchanged from the original /dscore — kept
    for the less common case where more than one opponent actually faced
    the player across the 3 drives, so each drive needs its own OVR (and,
    for a turnover drive, its own down/distance/play/forced-by detail) via
    a modal. /dscore itself now handles the common single-opponent case
    without any modal at all — see that command for the simplified path.
    """
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    if date is None:
        game_date = game_day()
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    drive_labels = [
        i18n.t('dscore.modal.label_drive1', lang),
        i18n.t('dscore.modal.label_drive2', lang),
        i18n.t('dscore.modal.label_drive3', lang),
    ]
    try:
        drive_outcomes, points_allowed = _parse_dscore_drives(drive1, drive2, drive3)
    except ValueError as e:
        label = drive_labels[int(str(e)) - 1]
        await interaction.response.send_message(
            i18n.t('dscore.err.invalid_drive', lang, label=label), ephemeral=True
        )
        return

    try:
        await db.update_player_dscore(player, game_date, points_allowed, None, *drive_outcomes)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return

    # First drive's modal opens directly from the slash command interaction —
    # valid, since (unlike a modal submission) a command interaction can open one.
    modal = _dscore_build_drive_modal(1, drive_outcomes, player, game_date, points_allowed, lang)
    await interaction.response.send_modal(modal)


# ============================================================================
# SIEGE COMMANDS
# ============================================================================

SIEGE_MOD_CHOICES = [app_commands.Choice(name=m, value=m) for m in siege.SIEGE_MODS]


@tree.command(name="siege", description="Start a new siege match for a league")
@app_commands.describe(league="Your league")
@app_commands.choices(league=LEAGUE_CHOICES)
async def siege_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_siege(interaction, league)


@tree.command(name="node", description="Report a newly-visible siege node")
@app_commands.describe(league="Your league", mod="Which mod this opponent carries")
@app_commands.choices(league=LEAGUE_CHOICES, mod=SIEGE_MOD_CHOICES)
async def node_slash(interaction: discord.Interaction, league: str, mod: str):
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_node(interaction, league, mod)


@tree.command(name="siegescore", description="Log drives/points scored against an open siege node")
@app_commands.describe(league="Your league", player="Player IGN", opponent="Opposing player (open nodes only)")
@app_commands.choices(league=LEAGUE_CHOICES)
@app_commands.autocomplete(player=league_player_autocomplete, opponent=siege.siege_opponent_autocomplete)
async def siegescore_slash(interaction: discord.Interaction, league: str, player: str, opponent: str):
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_siegescore(interaction, league, player, opponent)


@tree.command(name="siegestatus", description="Check the status of a league's active siege match")
@app_commands.describe(league="Your league")
@app_commands.choices(league=LEAGUE_CHOICES)
async def siegestatus_slash(interaction: discord.Interaction, league: str):
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_siegestatus(interaction, league)


@tree.command(name="updatesiege", description="Set opponent points and correct siege node/score entries")
@app_commands.describe(league="Your league")
@app_commands.choices(league=LEAGUE_CHOICES)
async def updatesiege_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_updatesiege(interaction, league)


@tree.command(name="siegefinal", description="Close out a league's active siege match")
@app_commands.describe(league="Your league")
@app_commands.choices(league=LEAGUE_CHOICES)
async def siegefinal_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_siegefinal(interaction, league)


@tree.command(name="siegesplits", description="A player's siege stats broken down by mod")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def siegesplits_slash(interaction: discord.Interaction, player: str):
    await siege.handle_siegesplits(interaction, player)


@tree.command(name="siegehistory", description="Past completed siege matches for a league")
@app_commands.describe(league="Your league")
@app_commands.choices(league=LEAGUE_CHOICES)
async def siegehistory_slash(interaction: discord.Interaction, league: str):
    try:
        league = _validate_league(league)
    except ValueError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await siege.handle_siegehistory(interaction, league)


class RegisterModal(Modal, title="Register New Player"):
    def __init__(self, team_id: str, lang: str = 'en'):
        super().__init__()
        self.team_id = team_id
        self.lang    = lang
        self.title = i18n.t('register.modal.title', lang)

        self.ign = TextInput(max_length=50, required=True)
        self.real_ign = TextInput(max_length=50, required=False,
                                   placeholder=i18n.t('register.modal.placeholder_real_ign', lang))
        self.off_ovr = TextInput(max_length=5, required=True)
        self.def_ovr = TextInput(max_length=5, required=True)
        self.total = TextInput(max_length=6, required=True)

        self.add_item(discord.ui.Label(text=i18n.t('register.modal.label_nickname', lang), component=self.ign))
        self.add_item(discord.ui.Label(text=i18n.t('register.modal.label_real_ign', lang), component=self.real_ign))
        self.add_item(discord.ui.Label(text=i18n.t('player.field.off_ovr', lang), component=self.off_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('player.field.def_ovr', lang), component=self.def_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('player.field.total_ovr', lang), component=self.total))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        await interaction.response.defer()

        nickname = self.ign.value.strip()
        if not nickname:
            await interaction.followup.send(i18n.t('register.err.blank_nickname', lang), ephemeral=True)
            return

        real = self.real_ign.value.strip() or nickname

        # Global uniqueness check on nickname
        existing = await db.fetchone(
            "SELECT team_id, status FROM players WHERE ign=? LIMIT 1", (nickname,)
        )
        if existing:
            league_name = LEAGUE_NAMES.get(existing['team_id'], existing['team_id'])
            status_note = i18n.t('register.status_inactive_suffix', lang) if existing['status'] == 'I' else ""
            await interaction.followup.send(
                i18n.t('register.err.already_registered', lang, nickname=nickname, league=league_name, status=status_note),
                ephemeral=True
            )
            return

        try:
            off  = int(self.off_ovr.value.strip())
            deff = int(self.def_ovr.value.strip())
            tot  = int(self.total.value.strip())
        except ValueError:
            await interaction.followup.send(i18n.t('register.err.invalid_ovr', lang), ephemeral=True)
            return

        await db.execute(
            "INSERT INTO players (team_id, ign, real_ign, status, off_ovr, def_ovr, total_ovr) "
            "VALUES (?, ?, ?, 'A', ?, ?, ?)",
            (self.team_id, nickname, real, off, deff, tot)
        )

        embed = discord.Embed(title=i18n.t('register.success.title', lang), color=discord.Color.green())
        embed.add_field(name=i18n.t('register.success.field_nickname', lang), value=nickname,                        inline=True)
        embed.add_field(name=i18n.t('register.success.field_league', lang),   value=LEAGUE_NAMES[self.team_id],      inline=True)
        embed.add_field(name=i18n.t('register.success.field_ovr', lang),      value=f"{off} / {deff} / {tot}",       inline=True)
        if real:
            embed.add_field(name=i18n.t('register.success.field_real_ign', lang), value=real, inline=True)
        await interaction.followup.send(embed=embed)


@tree.command(name="register", description="Register a new player")
@app_commands.describe(league="League to add the player to")
@app_commands.choices(league=LEAGUE_CHOICES)
async def register_slash(interaction: discord.Interaction, league: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.send_modal(RegisterModal(league, lang=lang))


# ============================================================================
# ADMIN: /transfer — select menu for destination league
# ============================================================================

class TransferLeagueView(View):
    def __init__(self, player: str, current_team: str, lang: str = 'en'):
        super().__init__(timeout=60)
        self.player       = player
        self.current_team = current_team
        self.lang         = lang
        options = [
            discord.SelectOption(
                label=name, value=tid,
                description="Current league" if tid == current_team else None,
                default=(tid == current_team)
            )
            for tid, name in LEAGUE_NAMES.items()
        ]
        select = Select(placeholder=i18n.t('transfer.select_placeholder', lang), options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        lang = self.lang
        new_team = interaction.data['values'][0]
        self.stop()
        if new_team == self.current_team:
            await interaction.response.edit_message(
                content=i18n.t('transfer.already_there', lang, player=self.player, league=LEAGUE_NAMES[new_team]), view=None
            )
            return
        await db.execute(
            "UPDATE players SET team_id=? WHERE ign=? AND status != 'I'",
            (new_team, self.player)
        )
        await interaction.response.edit_message(
            content=i18n.t('transfer.success', lang, player=self.player,
                          from_league=LEAGUE_NAMES[self.current_team], to_league=LEAGUE_NAMES[new_team]),
            view=None
        )


@tree.command(name="transfer", description="Transfer a player to a different league")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def transfer_slash(interaction: discord.Interaction, player: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return
    current = row['team_id']
    await interaction.response.send_message(
        i18n.t('transfer.prompt', lang, player=player, league=LEAGUE_NAMES[current]),
        view=TransferLeagueView(player, current, lang=lang),
        ephemeral=True
    )


# ============================================================================
# ADMIN: /inactive — button confirmation
# ============================================================================

@tree.command(name="inactive", description="Mark a player as inactive")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_all_autocomplete)
async def inactive_slash(interaction: discord.Interaction, player: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    row = await db.fetchone(
        "SELECT * FROM players WHERE ign=? LIMIT 1", (player,)
    )
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    current_status = {'A': i18n.t('inactive.status_active', lang), 'I': i18n.t('inactive.status_already', lang)}.get(row['status'], row['status'])
    league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])

    embed = discord.Embed(
        title=i18n.t('inactive.confirm.title', lang),
        description=i18n.t('inactive.confirm.desc', lang, player=player, league=league, status=current_status),
        color=discord.Color.orange()
    )

    async def do_inactive(inter):
        await db.execute(
            "UPDATE players SET status='I' WHERE ign=?", (player,)
        )
        await inter.response.edit_message(
            content=i18n.t('inactive.success', lang, player=player), embed=None, view=None
        )

    await interaction.response.send_message(embed=embed, view=ConfirmView(do_inactive, lang=lang), ephemeral=True)


# ============================================================================
# ADMIN: /reactivate
# ============================================================================

@tree.command(name="reactivate", description="Reactivate an inactive player")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_all_autocomplete)
async def reactivate_slash(interaction: discord.Interaction, player: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    row = await db.fetchone("SELECT * FROM players WHERE ign=? LIMIT 1", (player,))
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    async def do_reactivate(inter):
        await db.execute(
            "UPDATE players SET status='A' WHERE ign=?", (player,)
        )
        league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])
        await inter.response.edit_message(
            content=i18n.t('reactivate.success', lang, player=player, league=league), embed=None, view=None
        )

    embed = discord.Embed(
        title=i18n.t('reactivate.confirm.title', lang),
        description=i18n.t('reactivate.confirm.desc', lang, player=player, league=LEAGUE_NAMES.get(row['team_id'], '')),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, view=ConfirmView(do_reactivate, lang=lang), ephemeral=True)


# ============================================================================
# ADMIN: /ladder — custom ladder generator
# ============================================================================

def _is_ovr_change_suspicious(old_val: int | None, new_val: int, threshold: float = 0.30) -> bool:
    """
    Flags an OVR change as suspicious based on its size *relative to that
    player's own previous value* — never an absolute/hardcoded range, since
    the league-wide OVR range shifts unpredictably over a season (currently
    ~3000-4000, but this must keep working correctly whatever it becomes
    later). A jump of more than `threshold` (30% by default) in either
    direction is treated as suspicious — this is deliberately generous
    enough to allow a real, large legitimate jump (a player getting a much
    stronger build) through untouched, while still catching the specific
    reported failure mode: vision misreading a leading digit (3 misread as
    8) turns e.g. 3200 into 8200, a +156% jump that this easily catches.
    A None/zero old value means there's nothing to compare against (a
    brand new player) — never suspicious in that case.
    """
    if not old_val:
        return False
    return abs(new_val - old_val) / old_val > threshold


def _check_ovr_changes(row: dict, extracted: dict) -> dict:
    """
    Pure comparison (no DB writes) between a matched player's current OVR
    columns and freshly-extracted values. Returns
    {'normal': {col: new_val}, 'suspicious': {col: (old_val, new_val)}} —
    normal changes are safe to commit immediately; suspicious ones should
    be held for admin confirmation before ever reaching the ladder.
    """
    normal = {}
    suspicious = {}
    for col, key in [("total_ovr", "total_ovr"), ("off_ovr", "off_ovr"), ("def_ovr", "def_ovr")]:
        new_val = extracted.get(key)
        old_val = row[col]
        if new_val is None or old_val == new_val:
            continue
        if _is_ovr_change_suspicious(old_val, new_val):
            suspicious[col] = (old_val, new_val)
        else:
            normal[col] = new_val
    return {'normal': normal, 'suspicious': suspicious}


async def _commit_ovr_updates(row: dict, updates: dict, lang: str) -> str | None:
    """
    Writes a dict of {col: new_val} to the players table and returns a
    notification string, or None if updates is empty. Shared by the normal
    auto-apply path and the sanity-check review view's "accept" action, so
    both produce identical notification formatting.
    """
    if not updates:
        return None
    ovr_changes = [f"{col}: {row[col]} → {new_val}" for col, new_val in updates.items()]
    set_clause = ", ".join(f"{k}=?" for k in updates)
    await db.execute(
        f"UPDATE players SET {set_clause} WHERE id=?",
        (*updates.values(), row["id"])
    )
    return i18n.t('ladder_cmd.ovr_updated', lang, ign=row['ign'], changes=', '.join(ovr_changes))


async def _apply_extracted_ovr(row: dict, extracted: dict, lang: str) -> str | None:
    """
    Compare a matched player's current OVR columns against freshly-extracted
    values and update any that changed. Returns a notification string if
    anything was updated, or None if nothing changed. Shared by both the
    automatic exact real_ign match and the manual-match flow below, so a
    manually-matched player gets identical OVR-update treatment to an
    automatically-matched one.

    NOTE: this applies every changed field unconditionally, including
    suspicious ones — kept only for direct callers (e.g. /ovr, where a
    human is deliberately typing the value in) that want the old
    always-apply behavior. The /ladder screenshot flow uses
    _check_ovr_changes + _commit_ovr_updates instead, specifically so a
    suspicious jump can be held for confirmation rather than silently
    applied and later requiring a manual correction.
    """
    ovr_changes = []
    updates = {}
    for col, key in [("total_ovr", "total_ovr"), ("off_ovr", "off_ovr"), ("def_ovr", "def_ovr")]:
        new_val = extracted.get(key)
        old_val = row[col]
        if new_val is not None and old_val != new_val:
            ovr_changes.append(f"{col}: {old_val} → {new_val}")
            updates[col] = new_val

    if not updates:
        return None
    set_clause = ", ".join(f"{k}=?" for k in updates)
    await db.execute(
        f"UPDATE players SET {set_clause} WHERE id=?",
        (*updates.values(), row["id"])
    )
    return i18n.t('ladder_cmd.ovr_updated', lang, ign=row['ign'], changes=', '.join(ovr_changes))


class OvrSanityCheckView(View):
    """
    Shown when the screenshot extraction found one or more OVR changes that
    look suspiciously large relative to that specific player's own previous
    value (see _is_ovr_change_suspicious) — the most common real cause is
    the AI vision misreading a leading digit (3 misread as 8 is the
    specifically reported pattern, turning e.g. 3200 into 8200). Lets the
    admin accept or reject each flagged change before it ever reaches the
    ladder, instead of it being silently applied and only noticed later
    because it skewed ladder rankings — which then requires a manual
    correction after the fact, exactly what this exists to avoid.

    Same 4-per-screen cap and chaining-to-a-followup-batch design as
    LadderPlayerMatchView, for the same reason (Discord's 5-action-row
    limit) — see that class's docstring for the full reasoning.
    """
    MAX_ENTRIES = 4

    def __init__(self, suspicious_changes: list[dict], league: str, game_date, interaction_channel, bot,
                 preselected: list, preopponents: list, ladder_event_type, ladder_our_rank,
                 opponent_league_name, notifications: list[str], lang: str = 'en',
                 batch_num: int = 1, total_entries: int | None = None):
        super().__init__(timeout=300)
        self.league = league
        self.game_date = game_date
        self.channel = interaction_channel
        self.bot = bot
        self.preselected = preselected
        self.preopponents = preopponents
        self.ladder_event_type = ladder_event_type
        self.ladder_our_rank = ladder_our_rank
        self.opponent_league_name = opponent_league_name
        self.notifications = list(notifications)
        self.lang = lang
        self.current_batch = suspicious_changes[:self.MAX_ENTRIES]
        self.remaining_entries = suspicious_changes[self.MAX_ENTRIES:]
        self.batch_num = batch_num
        self.total_entries = total_entries if total_entries is not None else len(suspicious_changes)
        self.decisions: dict[int, str] = {}  # row id -> "accept" | "reject", default reject if untouched

        for item in self.current_batch:
            row = item['row']
            suspicious = item['suspicious']
            changes_desc = ", ".join(f"{col} {old}→{new}" for col, (old, new) in suspicious.items())
            options = [
                discord.SelectOption(
                    label=i18n.t('ladder_cmd.sanity.accept_option', lang, changes=changes_desc)[:100],
                    value="accept"
                ),
                discord.SelectOption(
                    label=i18n.t('ladder_cmd.sanity.reject_option', lang)[:100],
                    value="reject"
                ),
            ]
            select = Select(
                placeholder=i18n.t('ladder_cmd.sanity.placeholder', lang, ign=row['ign'])[:150],
                options=options
            )
            select.callback = self._make_callback(row['id'])
            self.add_item(select)

        confirm_btn = Button(label=i18n.t('ladder_cmd.sanity.confirm_btn', lang), style=discord.ButtonStyle.green)
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

    def _make_callback(self, row_id: int):
        async def callback(interaction: discord.Interaction):
            value = interaction.data['values'][0]
            self.decisions[row_id] = value
            await interaction.response.defer()
        return callback

    async def _on_confirm(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()
        for item in self.current_batch:
            row = item['row']
            decision = self.decisions.get(row['id'], "reject")  # unreviewed = safest default, reject
            if decision == "accept":
                updates = {col: new for col, (old, new) in item['suspicious'].items()}
                note = await _commit_ovr_updates(row, updates, self.lang)
                if note:
                    self.notifications.append(note)
            # "reject" — leave the player's existing OVR untouched entirely.

        if self.remaining_entries:
            next_batch_num = self.batch_num + 1
            next_view = OvrSanityCheckView(
                suspicious_changes=self.remaining_entries, league=self.league, game_date=self.game_date,
                interaction_channel=self.channel, bot=self.bot, preselected=self.preselected,
                preopponents=self.preopponents, ladder_event_type=self.ladder_event_type,
                ladder_our_rank=self.ladder_our_rank, opponent_league_name=self.opponent_league_name,
                notifications=self.notifications, lang=self.lang,
                batch_num=next_batch_num, total_entries=self.total_entries,
            )
            handled_so_far = self.total_entries - len(self.remaining_entries)
            names_list = "\n".join(f"• `{item['row']['ign']}`" for item in next_view.current_batch)
            await interaction.followup.send(
                i18n.t('ladder_cmd.sanity.next_batch', self.lang,
                       done=handled_so_far, total=self.total_entries, list=names_list),
                view=next_view
            )
            return

        if self.notifications:
            await interaction.followup.send(
                i18n.t('ladder_cmd.ovr_updates_header', self.lang, changes="\n".join(self.notifications)),
                ephemeral=True
            )

        await start_ladder_flow(
            interaction, self.league, self.game_date, bot=self.bot,
            preselected=self.preselected, preopponents=self.preopponents,
            opponent_league_name=self.opponent_league_name,
            event_type=self.ladder_event_type, our_rank=self.ladder_our_rank,
        )


class LadderPlayerMatchView(View):
    """
    Shown when the screenshot extraction found one or more of "our" players
    it couldn't match to a known league member by exact real_ign — usually
    because the AI vision read the name slightly wrong (mixed-up characters,
    a garbled special character, etc.), not because they aren't actually in
    the league. Lets the admin manually point each unrecognized name at the
    correct roster member so their OVR still updates, instead of that
    player's extraction silently being dropped.

    Discord allows at most 5 action rows per view, and each select needs its
    own row, so this handles at most 4 unmatched names per screen (leaving
    one row for the Confirm/Skip All buttons). Any remaining names beyond
    that chain into a follow-up view of the same kind once this batch is
    confirmed/skipped — nothing is ever silently dropped just because there
    were more than 4 in one screenshot; it just takes more than one screen.
    """
    MAX_ENTRIES = 4

    def __init__(self, missing_entries: list[dict], league: str, roster: list[dict],
                 already_matched: list[str], game_date, interaction_channel, bot,
                 preopponents: list, ladder_event_type, ladder_our_rank, opponent_league_name,
                 notifications: list[str], lang: str = 'en', batch_num: int = 1, total_entries: int | None = None,
                 suspicious_ovr_changes: list[dict] | None = None):
        super().__init__(timeout=300)
        self.league = league
        self.game_date = game_date
        self.channel = interaction_channel
        self.bot = bot
        self.lang = lang
        self.missing_entries = missing_entries[:self.MAX_ENTRIES]
        self.remaining_entries = missing_entries[self.MAX_ENTRIES:]
        self.roster = roster
        self.preselected = list(already_matched)
        self.preopponents = preopponents
        self.ladder_event_type = ladder_event_type
        self.ladder_our_rank = ladder_our_rank
        self.opponent_league_name = opponent_league_name
        self.notifications = list(notifications)
        self.suspicious_ovr_changes = list(suspicious_ovr_changes) if suspicious_ovr_changes else []
        self.selections: dict[str, str | None] = {}
        self.batch_num = batch_num
        self.total_entries = total_entries if total_entries is not None else len(missing_entries)

        used_igns = set(already_matched)
        for entry in self.missing_entries:
            extracted_name = entry.get("real_ign") or "?"
            options = [discord.SelectOption(
                label=i18n.t('ladder_cmd.match.skip_option', lang), value="__skip__"
            )]
            for p in roster:
                if p['ign'] in used_igns:
                    continue
                label = f"{p['real_ign']} ({p['ign']})" if p.get('real_ign') and p['real_ign'] != p['ign'] else p['ign']
                options.append(discord.SelectOption(label=label[:100], value=p['ign']))
            options = options[:25]

            select = Select(
                placeholder=i18n.t('ladder_cmd.match.placeholder', lang, name=extracted_name)[:150],
                options=options
            )
            select.callback = self._make_callback(extracted_name)
            self.add_item(select)

        confirm_btn = Button(label=i18n.t('ladder_cmd.match.confirm_btn', lang), style=discord.ButtonStyle.green)
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        skip_btn = Button(label=i18n.t('ladder_cmd.match.skip_all_btn', lang), style=discord.ButtonStyle.gray)
        skip_btn.callback = self._on_skip_all
        self.add_item(skip_btn)

    def _make_callback(self, extracted_name: str):
        async def callback(interaction: discord.Interaction):
            value = interaction.data['values'][0]
            self.selections[extracted_name] = None if value == "__skip__" else value
            await interaction.response.defer()
        return callback

    async def _finish(self, interaction: discord.Interaction):
        if self.remaining_entries:
            # More unmatched names than fit in one screen — continue with a
            # follow-up batch of the same kind rather than dropping them.
            next_batch_num = self.batch_num + 1
            next_view = LadderPlayerMatchView(
                missing_entries=self.remaining_entries, league=self.league, roster=self.roster,
                already_matched=self.preselected, game_date=self.game_date,
                interaction_channel=self.channel, bot=self.bot,
                preopponents=self.preopponents, ladder_event_type=self.ladder_event_type,
                ladder_our_rank=self.ladder_our_rank, opponent_league_name=self.opponent_league_name,
                notifications=self.notifications, lang=self.lang,
                batch_num=next_batch_num, total_entries=self.total_entries,
                suspicious_ovr_changes=self.suspicious_ovr_changes,
            )
            handled_so_far = self.total_entries - len(self.remaining_entries)
            unmatched_list = "\n".join(
                f"• `{e.get('real_ign', '?')}`" for e in next_view.missing_entries
            )
            await interaction.followup.send(
                i18n.t('ladder_cmd.match.next_batch', self.lang,
                       done=handled_so_far, total=self.total_entries, list=unmatched_list),
                view=next_view
            )
            return

        # Every name-match batch is resolved — if any matched player also had
        # a suspiciously large OVR jump, review those before ever reaching
        # the ladder, same as if there'd been no name-matching step at all.
        if self.suspicious_ovr_changes:
            view = OvrSanityCheckView(
                suspicious_changes=self.suspicious_ovr_changes, league=self.league, game_date=self.game_date,
                interaction_channel=self.channel, bot=self.bot, preselected=self.preselected,
                preopponents=self.preopponents, ladder_event_type=self.ladder_event_type,
                ladder_our_rank=self.ladder_our_rank, opponent_league_name=self.opponent_league_name,
                notifications=self.notifications, lang=self.lang,
            )
            names_list = "\n".join(f"• `{item['row']['ign']}`" for item in view.current_batch)
            await interaction.followup.send(
                i18n.t('ladder_cmd.sanity.prompt', self.lang, list=names_list),
                view=view
            )
            return

        if self.notifications:
            await interaction.followup.send(
                i18n.t('ladder_cmd.ovr_updates_header', self.lang, changes="\n".join(self.notifications)),
                ephemeral=True
            )

        # Sort by ladder_rank, matching the same convention the no-missing-
        # players path in ladder_slash already uses before calling this.
        team_stats = {p["ign"]: p for p in await db.get_team_stats(self.league)}
        self.preselected.sort(key=lambda ign: team_stats.get(ign, {}).get("ladder_rank") or 0, reverse=True)

        # Every batch is now resolved (matched or explicitly skipped) — hand
        # off to the ladder builder using the real interaction directly.
        # (A previous version built a fake stand-in object here to satisfy
        # start_ladder_flow's interaction.response.is_done() check, but gave
        # it a `response` attribute that was actually the followup webhook —
        # is_done() doesn't exist on that, so this crashed with an
        # AttributeError right after the OVR-update notification above had
        # already gone out, which is exactly why that notification appeared
        # but the ladder builder never did. The real interaction already
        # supports is_done()/followup/channel/locale correctly on its own
        # once deferred — no proxy needed at all.)
        await start_ladder_flow(
            interaction, self.league, self.game_date, bot=self.bot,
            preselected=self.preselected, preopponents=self.preopponents,
            opponent_league_name=self.opponent_league_name,
            event_type=self.ladder_event_type, our_rank=self.ladder_our_rank,
        )

    async def _on_confirm(self, interaction: discord.Interaction):
        # Defer immediately, before any DB work — Discord only allows 3
        # seconds to acknowledge an interaction, and matching multiple
        # entries against the database (a lookup plus a potential OVR update
        # per entry) can add up. Deferring first removes any risk of the
        # interaction expiring before it's acknowledged (which showed up
        # exactly as "didn't respond in time" — the button click itself
        # failing, not anything after it).
        await interaction.response.defer()
        self.stop()
        for entry in self.missing_entries:
            extracted_name = entry.get("real_ign") or "?"
            chosen_ign = self.selections.get(extracted_name)
            if not chosen_ign:
                continue
            row = await db.get_player(chosen_ign)
            if row is None:
                continue
            checked = _check_ovr_changes(row, entry)
            note = await _commit_ovr_updates(row, checked['normal'], self.lang)
            if note:
                self.notifications.append(note)
            if checked['suspicious']:
                self.suspicious_ovr_changes.append({'row': row, 'suspicious': checked['suspicious']})
            if chosen_ign not in self.preselected:
                self.preselected.append(chosen_ign)
        await self._finish(interaction)

    async def _on_skip_all(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()
        await self._finish(interaction)


@tree.command(name="ladder", description="Build today's ladder matchups interactively")
@app_commands.describe(
    league="Your league",
    date="Date (YYYY-MM-DD), defaults to today",
    screenshot1="First League vs League screenshot",
    screenshot2="Second screenshot (optional)",
    screenshot3="Third screenshot (optional)",
)
@app_commands.choices(league=LEAGUE_CHOICES)
async def ladder_slash(interaction: discord.Interaction, league: str,
                       date: str = None,
                       screenshot1: discord.Attachment = None,
                       screenshot2: discord.Attachment = None,
                       screenshot3: discord.Attachment = None):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)

    if date is None:
        game_date = game_day()
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    # Collect provided screenshots
    attachments = [a for a in [screenshot1, screenshot2, screenshot3] if a is not None]

    if not attachments:
        # No screenshots — go straight to manual flow. If a previous /ladder run
        # (with screenshots) already saved opponents to the live ladder for this
        # date, the opponent-entry step will offer to load them automatically.
        await start_ladder_flow(interaction, league, game_date, bot=bot)
        return

    # Screenshots provided — run the agent
    await interaction.response.defer()

    from agent import extract_ladder_from_screenshots

    try:
        extracted = await extract_ladder_from_screenshots([a.url for a in attachments])
    except ValueError as e:
        await interaction.followup.send(i18n.t('ladder_cmd.err.screenshot_extraction_failed', lang, error=e), ephemeral=True)
        return

    opponents   = extracted.get("opponents", [])
    our_players = extracted.get("our_players", [])
    opponent_league_name = extracted.get("opponent_league_name")
    ladder_event_type    = extracted.get("event_type")
    ladder_our_rank      = extracted.get("our_rank")

    # Validate our players against the DB
    notifications = []
    missing       = []  # full extracted dicts, not just names — needed to apply OVR once matched
    preselected   = []
    suspicious_ovr_changes = []  # {'row': ..., 'suspicious': {col: (old, new)}} — held for admin review

    for p in our_players:
        real_ign = p.get("real_ign")
        if not real_ign:
            continue

        row = await db.get_player_by_real_ign(real_ign)

        if row is None:
            missing.append(p)
            continue

        checked = _check_ovr_changes(row, p)
        note = await _commit_ovr_updates(row, checked['normal'], lang)
        if note:
            notifications.append(note)
        if checked['suspicious']:
            suspicious_ovr_changes.append({'row': row, 'suspicious': checked['suspicious']})
        preselected.append(row["ign"])

    # Format opponents for ladder flow
    preopponents = [
        {
            "name":      o.get("name", "—"),
            "total_ovr": o.get("total_ovr"),
            "def_ovr":   o.get("def_ovr"),
        }
        for o in opponents
    ]

    if missing:
        # One or more "our" players couldn't be matched by exact real_ign —
        # usually the AI vision misread a name slightly, not that they aren't
        # actually in the league. Let the admin manually point each one at
        # the correct roster member instead of silently dropping their OVR
        # update and just warning about it.
        roster = await db.fetchall(
            "SELECT ign, real_ign FROM players WHERE team_id=? AND status='A' ORDER BY ign", (league,)
        )
        view = LadderPlayerMatchView(
            missing_entries=missing, league=league, roster=roster,
            already_matched=preselected, game_date=game_date,
            interaction_channel=interaction.channel, bot=bot,
            preopponents=preopponents, ladder_event_type=ladder_event_type,
            ladder_our_rank=ladder_our_rank, opponent_league_name=opponent_league_name,
            notifications=notifications, lang=lang,
            suspicious_ovr_changes=suspicious_ovr_changes,
        )
        unmatched_list = "\n".join(f"• `{m.get('real_ign', '?')}`" for m in missing[:LadderPlayerMatchView.MAX_ENTRIES])
        await interaction.followup.send(
            i18n.t('ladder_cmd.match.prompt', lang, league=LEAGUE_NAMES[league], list=unmatched_list),
            view=view
        )
        return

    # Sort our players by ladder_rank
    team_stats   = {p["ign"]: p for p in await db.get_team_stats(league)}
    preselected.sort(
        key=lambda ign: team_stats.get(ign, {}).get("ladder_rank") or 0,
        reverse=True
    )

    # One or more OVR changes look suspiciously large relative to that
    # player's own previous value (most likely a vision misread, e.g. a
    # leading 3 read as an 8) — review before this ever reaches the ladder,
    # rather than silently applying it and needing a manual correction
    # after it's already skewed rankings.
    if suspicious_ovr_changes:
        view = OvrSanityCheckView(
            suspicious_changes=suspicious_ovr_changes, league=league, game_date=game_date,
            interaction_channel=interaction.channel, bot=bot, preselected=preselected,
            preopponents=preopponents, ladder_event_type=ladder_event_type,
            ladder_our_rank=ladder_our_rank, opponent_league_name=opponent_league_name,
            notifications=notifications, lang=lang,
        )
        names_list = "\n".join(f"• `{item['row']['ign']}`" for item in view.current_batch)
        await interaction.followup.send(
            i18n.t('ladder_cmd.sanity.prompt', lang, list=names_list),
            view=view
        )
        return

    # Send OVR change notifications
    if notifications:
        changes_msg = "\n".join(notifications)
        await interaction.followup.send(
            i18n.t('ladder_cmd.ovr_updates_header', lang, changes=changes_msg),
            ephemeral=True
        )

    # Launch ladder flow with pre-populated data
    await start_ladder_flow(
        interaction, league, game_date, bot=bot,
        preselected=preselected,
        preopponents=preopponents,
        opponent_league_name=opponent_league_name,
        event_type=ladder_event_type,
        our_rank=ladder_our_rank,
    )


# ============================================================================
# MISC COMMANDS
# ============================================================================

# ============================================================================
# TOURNAMENT COMMANDS (unchanged)
# ============================================================================

# ============================================================================
# BOT EVENTS
# ============================================================================

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    try:
        await db.init()
        logger.info("Database ready")

        # Back up immediately on every startup — this is exactly the moment
        # an accidental file overwrite (uploading the wrong/older db over the
        # live one during a deploy) would otherwise go unnoticed and
        # unrecoverable. A fresh timestamped copy here means there's always
        # a very recent known-good snapshot to fall back on.
        await db.backup_database()

        # Register as guild commands (rank above global in autofill)
        # then clear global registrations so there's no overlap
        for guild in bot.guilds:
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        tree.clear_commands(guild=None)  # wipe global list locally
        await tree.sync()               # push empty list to Discord globally
        logger.info(f"Slash commands registered to {len(bot.guilds)} guild(s), globals cleared")

        bot.loop.create_task(gif_sender())
        logger.info("GIF queue started")

        if DEV == 'production':
            scheduled_newday.start()
            scheduled_backup.start()
            logger.info("Scheduled tasks started")

    except Exception as e:
        logger.error(f"Error during initialisation: {e}", exc_info=True)


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    content = message.content
    channel = message.channel

    gif_triggers = [
        ('22!',gif_files_22),('20!',gif_files_20),('24!',gif_files_24),
        ('30!',gif_files_30),('26!',gif_files_26),('28!',gif_files_24),
        ('18!',gif_files_18),('16!',gif_files_16),('14!',gif_files_14),
        ('12!',gif_files_12),('8!', gif_files_8), ('6!', gif_files_6),
        ('0!', gif_files_bad),('D-Up!',gifs_defense),
    ]

    if content == 'Kobe!':
        await gif_queue.put((channel, (random.choice(gif_files), True)))
    elif content == 'Brunson!':
        await gif_queue.put((channel, (random.choice(brunson_gifs), False)))
    elif 'bingbong' in content:
        await gif_queue.put((channel, (random.choice(bingbonggifs), False)))
    elif any(kp in content for kp in ('19!','21!','23!')):
        await gif_queue.put((channel, 'HA! This ^ mf kicking extra points!'))
    else:
        for trigger, pool in gif_triggers:
            if trigger in content and pool:
                await gif_queue.put((channel, (random.choice(pool), False)))
                break

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Prefix commands were fully retired in favor of slash commands — this
        # is the one place a Discord Locale can't be read from an interaction,
        # since prefix commands come from a plain message, not an interaction.
        # The guild's own configured language is the best available substitute.
        locale = str(ctx.guild.preferred_locale) if ctx.guild else None
        lang = i18n.DISCORD_LOCALE_TO_LANG.get(locale, 'en')
        await ctx.send(i18n.t('prefix.deprecated', lang))
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏱️ Cooldown. Try again in {error.retry_after:.1f}s.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("⚠️ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing argument: `{error.param.name}`")
    else:
        logger.error(f"Command error: {error}", exc_info=True)


async def _handle_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """
    Core logic for the global slash-command error handler — extracted into
    a plain, testable function since @tree.error's decorated function
    itself becomes untestable under this codebase's test stub (tree is a
    MagicMock, so @tree.error(func) returns another MagicMock, not func
    itself — same underlying reason @tree.command-decorated functions
    can't be called directly either).
    """
    cmd_name = interaction.command.name if interaction.command else '?'
    logger.error(f"Slash command error in /{cmd_name}: {error}", exc_info=True)

    # Unwrap CommandInvokeError to see the actual underlying exception a
    # command's own code raised (confirmed against discord.py's own source:
    # app_commands.CommandInvokeError exposes this via .original), rather
    # than the generic wrapper — needed to tell a transient Discord-side
    # issue (worth a short retry) apart from a permanently-expired
    # interaction (retrying is guaranteed to fail the exact same way,
    # since the interaction token itself is now invalid, not anything
    # about the request).
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error

    # "Unknown interaction" (404, Discord error code 10062) means THIS
    # SPECIFIC interaction already expired or was otherwise invalidated by
    # the time the bot tried to use it — nothing the bot can do lets it
    # respond to this one anymore; the user needs to run the command
    # again. The previous version of this handler tried to report the
    # error via the same interaction regardless, which would fail with
    # the identical error a second time and get silently swallowed by a
    # bare except — wasting a call for no benefit and leaving no trace of
    # what actually happened. Log clearly instead and stop.
    if isinstance(original, discord.NotFound) and getattr(original, 'code', None) == 10062:
        logger.error(f"/{cmd_name}'s interaction had already expired before the bot could respond to "
                     f"the original error — nothing further to do; the user will need to run the command again.")
        return

    msg = f"⚠️ An error occurred: {error}"

    # A genuine Discord-side rate limit / service degradation (429, e.g.
    # error code 40062 "Service resource is being rate limited") can clear
    # within a second or two — unlike an expired interaction, a short
    # retry here is worth attempting rather than leaving the user with no
    # response at all for what's often a transient blip.
    is_rate_limited = isinstance(original, discord.HTTPException) and getattr(original, 'status', None) == 429
    max_attempts = 2 if is_rate_limited else 1

    for attempt in range(max_attempts):
        if attempt > 0:
            await asyncio.sleep(2)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        except discord.NotFound:
            # The interaction expired between the original error and this
            # attempt to report it — same "nothing further to do" case.
            return
        except Exception:
            continue


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await _handle_app_command_error(interaction, error)


# ============================================================================
# SCHEDULED TASKS
# ============================================================================

@tasks.loop(time=new_day_time)
async def scheduled_newday():
    try:
        await newday()
        clear_rank_cache()
        logger.info("Scheduled newday complete")
    except Exception as e:
        logger.error(f"Error in scheduled_newday: {e}", exc_info=True)


@tasks.loop(time=new_day_time)
async def scheduled_backup():
    try:
        await db.backup_database()
    except Exception as e:
        logger.error(f"Error in scheduled_backup: {e}", exc_info=True)


# ============================================================================
# /matchup — input daily matchup info + interactive ladder builder
# ============================================================================

SLOTS_PER_PAGE = 5



# ============================================================================
# WEIGHT MANAGEMENT COMMANDS
# ============================================================================

WEIGHT_CATEGORIES = [
    app_commands.Choice(name="Power Rank Factors", value="pwr_rank"),
    app_commands.Choice(name="Ladder Factors",     value="ladder"),
]


# ---------------------------------------------------------------------------
# /weights — combined weight manager
# ---------------------------------------------------------------------------

class WeightEditModal(Modal, title="Edit Weight"):
    def __init__(self, label: str, current: float, lang: str = 'en'):
        super().__init__(title=i18n.t('weights.edit_modal.title', lang, label=label))
        self.w_label   = label
        self.lang      = lang
        self.new_weight = TextInput(placeholder="e.g. 0.35", max_length=10, default=str(current))
        self.add_item(discord.ui.Label(text=i18n.t('weights.edit_modal.label_value', lang), component=self.new_weight))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = float(self.new_weight.value.strip())
        except ValueError:
            await interaction.response.send_message(i18n.t('weights.err.must_be_number', self.lang), ephemeral=True)
            return
        self._result = val
        await interaction.response.defer()


# All numeric player stat columns that can be used as weight factors.
# Keys reference i18n's stat.* translations; display text is resolved per-lang
# via _stat_labels(lang) rather than kept as a static English list.
ALL_STAT_KEYS = [
    ("yearly_avg",        "stat.yearly_avg"),
    ("30day_avg",         "stat.30day_avg"),
    ("14day_avg",         "stat.14day_avg"),
    ("7day_avg",          "stat.7day_avg"),
    ("3day_avg",          "stat.3day_avg"),
    ("hof_avg",           "stat.hof_avg"),
    ("e1_avg",            "stat.e1_avg"),
    ("e2_avg",            "stat.e2_avg"),
    ("e3_avg",            "stat.e3_avg"),
    ("gold_avg",          "stat.gold_avg"),
    ("total_ovr",         "stat.total_ovr"),
    ("team_total_ovr",    "stat.team_total_ovr"),
    ("total_ovr_ladder",  "stat.total_ovr_ladder"),
    ("off_ovr",           "stat.off_ovr"),
    ("off_ovr_ladder",    "stat.off_ovr_ladder"),
    ("def_ovr",           "stat.def_ovr"),
    ("30day_ladder",      "stat.30day_ladder"),
    ("kobes",             "stat.kobes"),
    ("points",            "stat.points"),
    ("games",             "stat.games"),
    ("three_td",          "stat.three_td"),
    ("three_td_pct",      "stat.three_td_pct"),
    ("two_pt_pct",        "stat.two_pt_pct"),
    ("fumbles",           "stat.fumbles"),
    ("fourth_down_conv_pct", "stat.fourth_down_conv_pct"),
    # Fumble-adjusted variants (fumbles treated as null drives — see
    # db._fumble_adjusted_avg) of every averages-based factor that's
    # actually wired into the pwr_rank/ladder_rank formulas below. Only
    # these seven pwr_rank-side and four ladder-side averages have a
    # fumble-adjusted counterpart, matching exactly which plain averages
    # the formulas themselves use.
    ("yearly_avg_fumble_adj",     "stat.yearly_avg_fumble_adj"),
    ("30day_avg_fumble_adj",      "stat.30day_avg_fumble_adj"),
    ("hof_avg_fumble_adj",        "stat.hof_avg_fumble_adj"),
    ("e1_avg_fumble_adj",         "stat.e1_avg_fumble_adj"),
    ("e2_avg_fumble_adj",         "stat.e2_avg_fumble_adj"),
    ("e3_avg_fumble_adj",         "stat.e3_avg_fumble_adj"),
    ("gold_avg_fumble_adj",       "stat.gold_avg_fumble_adj"),
    ("3day_avg_fumble_adj",       "stat.3day_avg_fumble_adj"),
    ("7day_avg_fumble_adj",       "stat.7day_avg_fumble_adj"),
    ("14day_avg_fumble_adj",      "stat.14day_avg_fumble_adj"),
    ("30day_ladder_fumble_adj",   "stat.30day_ladder_fumble_adj"),
]


def _stat_labels(lang: str):
    """Translated (label_key, display_text) pairs for the weight-factor stat picker."""
    return [(key, i18n.t(tkey, lang)) for key, tkey in ALL_STAT_KEYS]


class WeightAddValueModal(Modal, title="Set Weight Value"):
    def __init__(self, label: str, default_display: str, lang: str = 'en'):
        super().__init__()
        self.w_label              = label
        self.lang                 = lang
        self.title = i18n.t('weights.add_value_modal.title', lang)

        self.display_label = TextInput(placeholder="e.g. Kobe Bonus", max_length=50, default=default_display)
        self.weight = TextInput(placeholder="e.g. 0.10", max_length=10)

        self.add_item(discord.ui.Label(text=i18n.t('weights.add_value_modal.label_display', lang), component=self.display_label))
        self.add_item(discord.ui.Label(text=i18n.t('weights.add_value_modal.label_weight', lang), component=self.weight))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            float(self.weight.value.strip())
        except ValueError:
            await interaction.response.send_message(i18n.t('weights.err.weight_must_be_number', self.lang), ephemeral=True)
            return
        await interaction.response.defer()


class WeightAddSelectView(View):
    """Step 1 of adding a weight: pick the stat label from a dropdown of unused options."""

    def __init__(self, category: str, team_id: str | None, existing_labels: list[str], parent_view, lang: str = 'en'):
        super().__init__(timeout=60)
        self.category     = category
        self.team_id      = team_id
        self.parent_view  = parent_view
        self.lang         = lang
        self.origin_msg   = None  # set after send so we can edit it back

        available = [
            (label, display)
            for label, display in _stat_labels(lang)
            if label not in existing_labels
        ]

        if not available:
            return  # All stats already used

        options = [
            discord.SelectOption(label=display, value=label)
            for label, display in available
        ]
        sel = Select(placeholder=i18n.t('weights.select_stat_placeholder', lang), options=options[:25])
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        lang    = self.lang
        label   = interaction.data["values"][0]
        display = next((d for l, d in _stat_labels(lang) if l == label), label)
        self.stop()

        # Store reference to the ephemeral select message so we can delete it after
        origin_msg = interaction.message

        modal = WeightAddValueModal(label, display, lang=lang)
        orig  = modal.on_submit

        async def patched(inter):
            await orig(inter)
            val = float(modal.weight.value.strip())
            await db.add_weight(
                modal.w_label,
                modal.display_label.value.strip(),
                val,
                self.category,
                self.team_id
            )
            await self.parent_view.load()
            # Edit the original weights embed back into view
            if origin_msg:
                try:
                    await origin_msg.edit(content="", embed=None, view=None)
                except Exception:
                    pass
            # Update the parent weights message
            await inter.followup.send(
                embed=self.parent_view._build_embed(),
                view=self.parent_view,
                ephemeral=True
            )

        modal.on_submit = patched
        await interaction.response.send_modal(modal)


class WeightsView(View):
    """
    Interactive weight manager.
    Shows all weights for a category as a list.
    Each row has an Edit button. Bottom row has Add and a Delete select.
    """

    def __init__(self, category: str, team_id: str | None = None, lang: str = 'en'):
        super().__init__(timeout=180)
        self.category = category
        self.team_id  = team_id
        self.lang     = lang
        self.weights: list[dict] = []

    async def load(self):
        self.weights = await db.get_weights(self.category, self.team_id)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lang = self.lang

        # Edit buttons: max 4 per row, rows 0-2 (up to 12 weights displayed)
        # A Select takes the full width of a row, so keep it on its own row
        for i, w in enumerate(self.weights[:12]):
            label = w['display_label'] or w['label']
            btn   = Button(
                label=i18n.t('weights.edit_btn', lang, label=label, value=w['weight']),
                style=discord.ButtonStyle.secondary,
                row=i // 4
            )
            btn.callback = self._make_edit(w)
            self.add_item(btn)

        # Row 3: Add and Recalculate buttons (2 buttons = fine)
        add_btn = Button(label=i18n.t('weights.add_btn', lang), style=discord.ButtonStyle.success, row=3)
        add_btn.callback = self._add
        self.add_item(add_btn)

        recalc_btn = Button(label=i18n.t('weights.recalc_btn', lang), style=discord.ButtonStyle.blurple, row=3)
        recalc_btn.callback = self._recalc_all
        self.add_item(recalc_btn)

        # Row 4: Delete select (takes full row width on its own)
        if self.weights:
            del_options = [
                discord.SelectOption(
                    label=w['display_label'] or w['label'],
                    value=w['label'],
                    description=i18n.t('weights.delete_option_desc', lang, value=w['weight'])
                )
                for w in self.weights
            ]
            del_sel = Select(
                placeholder=i18n.t('weights.delete_select_placeholder', lang),
                options=del_options,
                row=4
            )
            del_sel.callback = self._delete
            self.add_item(del_sel)

    def _build_embed(self) -> discord.Embed:
        lang      = self.lang
        cat_label = i18n.t('weights.title_pwr', lang) if self.category == "pwr_rank" else i18n.t('weights.title_ladder', lang)
        scope     = i18n.t('weights.scope_league', lang, league=LEAGUE_NAMES[self.team_id]) if self.team_id else i18n.t('weights.scope_global', lang)
        embed     = discord.Embed(
            title=i18n.t('weights.title', lang, cat=cat_label, scope=scope),
            color=discord.Color.blurple()
        )
        if not self.weights:
            embed.description = i18n.t('weights.no_weights', lang)
        else:
            lines = []
            for w in self.weights:
                name  = w["display_label"] or w["label"]
                scope_s = i18n.t('weights.override_note', lang, league=LEAGUE_NAMES.get(w['team_id'], w['team_id'])) if w.get("team_id") else ""
                lines.append(f"`{w['label']:<22}` **{w['weight']}**  {name}{scope_s}")
            embed.description = "\n".join(lines)
        embed.set_footer(text=i18n.t('weights.footer', lang))
        return embed

    def _make_edit(self, w: dict):
        async def callback(interaction: discord.Interaction):
            modal = WeightEditModal(w["display_label"] or w["label"], w["weight"], lang=self.lang)
            orig  = modal.on_submit

            async def patched(inter):
                await orig(inter)
                await db.set_weight(w["label"], modal._result, self.team_id)
                await self.load()
                await inter.edit_original_response(embed=self._build_embed(), view=self)

            modal.on_submit = patched
            await interaction.response.send_modal(modal)
        return callback

    async def _add(self, interaction: discord.Interaction):
        existing_labels = [w['label'] for w in self.weights]
        select_view = WeightAddSelectView(
            self.category, self.team_id, existing_labels, self, lang=self.lang
        )
        if not select_view.children:
            await interaction.response.send_message(
                i18n.t('weights.all_used', self.lang), ephemeral=True
            )
            return
        await interaction.response.send_message(
            i18n.t('weights.which_stat_prompt', self.lang),
            view=select_view,
            ephemeral=True
        )
        select_view.origin_msg = await interaction.original_response()

    async def _recalc_all(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.load()
        embed = self._build_embed()
        embed.set_footer(text=i18n.t('weights.recalc_footer', self.lang))
        await interaction.edit_original_response(content=None, embed=embed, view=self)

    async def _delete(self, interaction: discord.Interaction):
        lang     = self.lang
        label    = interaction.data["values"][0]
        w        = next((x for x in self.weights if x['label'] == label), None)
        name     = w['display_label'] or label if w else label

        # Show confirm/cancel buttons before actually deleting
        confirm_view = View(timeout=30)

        confirm_btn = Button(label=i18n.t('weights.delete_btn', lang, name=name), style=discord.ButtonStyle.danger)
        cancel_btn  = Button(label=i18n.t('weights.cancel_btn', lang),            style=discord.ButtonStyle.secondary)

        async def do_confirm(inter: discord.Interaction):
            confirm_view.stop()
            await db.delete_weight(label, self.team_id)
            await self.load()
            await inter.response.edit_message(
                content=None, embed=self._build_embed(), view=self
            )

        async def do_cancel(inter: discord.Interaction):
            confirm_view.stop()
            await inter.response.edit_message(content=None, embed=self._build_embed(), view=self)

        confirm_btn.callback = do_confirm
        cancel_btn.callback  = do_cancel
        confirm_view.add_item(confirm_btn)
        confirm_view.add_item(cancel_btn)

        await interaction.response.edit_message(
            content=i18n.t('weights.delete_confirm_prompt', lang, name=name, label=label),
            embed=None,
            view=confirm_view
        )


@tree.command(name="weights", description="View and manage power rank or ladder weight factors")
@app_commands.describe(
    category="Which formula to manage",
    league="Optional: manage league-specific overrides"
)
@app_commands.choices(category=WEIGHT_CATEGORIES, league=LEAGUE_CHOICES)
async def weights_slash(interaction: discord.Interaction,
                        category: str, league: str = None):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    view = WeightsView(category, league, lang=lang)
    await view.load()
    await interaction.response.send_message(
        embed=view._build_embed(), view=view, ephemeral=True
    )


# ============================================================================
# /manual — ephemeral command reference
# ============================================================================

MANUAL_PAGE_COLORS = [
    discord.Color.blue(), discord.Color.green(), discord.Color.dark_red(),
    discord.Color.orange(), discord.Color.purple(),
]


class ManualView(View):
    def __init__(self, lang: str = 'en'):
        super().__init__(timeout=120)
        self.page = 0
        self.lang = lang
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        total = len(i18n.MANUAL_PAGE_KEYS)

        if self.page > 0:
            prev = Button(label=i18n.t('manual.nav.prev', self.lang), style=discord.ButtonStyle.secondary, row=0)
            prev.callback = self._prev
            self.add_item(prev)

        close = Button(label=i18n.t('manual.nav.close', self.lang), style=discord.ButtonStyle.danger, row=0)
        close.callback = self._close
        self.add_item(close)

        if self.page < total - 1:
            nxt = Button(label=i18n.t('manual.nav.next', self.lang), style=discord.ButtonStyle.secondary, row=0)
            nxt.callback = self._next
            self.add_item(nxt)

    def _build_embed(self) -> discord.Embed:
        page_key = i18n.MANUAL_PAGE_KEYS[self.page]
        total    = len(i18n.MANUAL_PAGE_KEYS)
        embed    = discord.Embed(
            title=i18n.t(f'{page_key}.title', self.lang),
            description=i18n.t('manual.nav.footer', self.lang, page=self.page + 1, total=total),
            color=MANUAL_PAGE_COLORS[self.page]
        )
        for name, value in i18n.tlist(f'{page_key}.fields', self.lang):
            embed.add_field(name=f"`{name}`", value=value, inline=False)
        return embed

    async def _prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _close(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(
            content=i18n.t('manual.closed', self.lang), embed=None, view=None
        )


@tree.command(name="manual", description="Show all bot commands and how to use them")
async def manual_slash(interaction: discord.Interaction):
    lang = i18n.resolve_lang(interaction)
    view = ManualView(lang)
    await interaction.response.send_message(
        embed=view._build_embed(), view=view, ephemeral=True
    )


# ============================================================================
# /show_ladder — display today's (or a date's) ladder matchups
# ============================================================================

async def _build_ladder_image(league: str, game_date, conn=None, season_label: str | None = None,
                              style: str = 'classic', league_name: str | None = None):
    """
    Shared logic for /show_ladder and /legacy show_ladder.
    Returns an image buffer, or None if there's no ladder data at all for this league.
    style: 'classic', 'neon', 'clean', or 'scoreboard' — see sheet_image.render_ladder_image.
    league_name: display name to title the image with. /legacy passes the name
      from that season's own teams table, since a league it archived may not
      be in the live LEAGUE_NAMES at all anymore (KeyError, not a miss).
    """
    # Try daily snapshot first
    rows = await db.get_ladder_snapshot(league, game_date, conn=conn)

    # Fall back to static reference if no snapshot
    if not rows:
        rows = await db.get_ladder(league, conn=conn)
        source = "static reference"
    else:
        source = f"snapshot for {game_date}"

    if not rows:
        return None

    # Enrich with live ladder_rank and off_ovr per player where our_ign is known
    team_stats = {p['ign']: p for p in await db.get_team_stats(league, conn=conn)}
    enriched = []
    for r in rows:
        r = dict(r)
        ign = r.get('our_ign')
        if ign and ign in team_stats:
            r['ladder_rank'] = team_stats[ign].get('ladder_rank')
            r['our_off_ovr'] = team_stats[ign].get('off_ovr') or r.get('our_off_ovr')
        else:
            r.setdefault('ladder_rank', None)
            r.setdefault('our_off_ovr', None)
        enriched.append(r)

    from sheet_image import render_ladder_image

    league_name = league_name or LEAGUE_NAMES.get(league, league)

    # Show the opposing league in the title, if it's been recorded for this
    # date — either from a screenshot extraction or set directly via /matchup.
    matchup = await db.fetchone(
        "SELECT opp_ign, event_type FROM matchup_day WHERE team_id=? AND game_date=?",
        (league, str(game_date)), conn=conn
    )
    opp_name = matchup.get('opp_ign') if matchup else None
    division = matchup.get('event_type') if matchup else None
    if opp_name:
        opp_str = f" vs {opp_name}"
        if division:
            opp_str += f" ({division})"
    else:
        opp_str = ""

    title = f"{league_name}{opp_str}"
    if season_label:
        title += f"  {season_label}"
    return render_ladder_image(
        title, enriched, subtitle=f"Ladder ({source})", style=style,
        our_team_name=league_name, opponent_name=opp_name, division=division,
    )


@tree.command(name="show_ladder", description="Display the ladder matchups for a league")
@app_commands.describe(
    league="League to display",
    date="Date (YYYY-MM-DD), defaults to today",
    style="Visual style for the image (defaults to Classic)"
)
@app_commands.choices(league=LEAGUE_CHOICES, style=LADDER_STYLE_CHOICES)
async def show_ladder_slash(interaction: discord.Interaction,
                             league: str, date: str = None, style: str = "classic"):
    lang = i18n.resolve_lang(interaction)
    if date is None:
        game_date = game_day()
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    await interaction.response.defer()

    buf = await _build_ladder_image(league, game_date, style=style)
    if buf is None:
        await interaction.followup.send(
            i18n.t('ladder_cmd.err.no_data', lang, league=LEAGUE_NAMES[league]), ephemeral=True
        )
        return

    league_name = LEAGUE_NAMES[league]
    await interaction.followup.send(
        file=discord.File(buf, filename=f"ladder_{league_name}.png")
    )


# ============================================================================
# /outcome — record the final score (Administrator only)
# ============================================================================

# ============================================================================
# /summary — full matchup summary (Administrator only)
# ============================================================================

# ============================================================================
# /factors — display current weight factors for a league
# ============================================================================

@tree.command(name="factors", description="Show the current power rank and ladder weight factors for a league")
@app_commands.describe(league="League (optional — shows global weights if omitted)")
@app_commands.choices(league=LEAGUE_CHOICES)
async def factors_slash(interaction: discord.Interaction, league: str = None):
    lang = i18n.resolve_lang(interaction)
    pwr_weights    = await db.get_weights('pwr_rank',  league)
    ladder_weights = await db.get_weights('ladder',    league)

    scope = f"**{LEAGUE_NAMES[league]}**" if league else i18n.t('factors.scope_global', lang)
    embed = discord.Embed(
        title=i18n.t('factors.title', lang, scope=scope),
        color=discord.Color.blurple()
    )

    def build_table(weights: list[dict]) -> str:
        if not weights:
            return i18n.t('factors.no_factors', lang)
        col_factor = i18n.t('factors.col_factor', lang)
        col_weight = i18n.t('factors.col_weight', lang)
        col_total  = i18n.t('factors.col_total', lang)
        rows   = [f"{col_factor:<22}  {col_weight:>7}"]
        rows.append("─" * 31)
        total  = 0.0
        for w in weights:
            name   = w['display_label'] or w['label']
            rows.append(f"{name:<22}  {w['weight']:>7}")
            total += w['weight']
        rows.append("─" * 31)
        rows.append(f"{col_total:<22}  {round(total, 4):>7}")
        return "```\n" + "\n".join(rows) + "\n```"

    embed.add_field(
        name=i18n.t('factors.field_pwr', lang),
        value=build_table(pwr_weights),
        inline=False
    )
    embed.add_field(
        name=i18n.t('factors.field_ladder', lang),
        value=build_table(ladder_weights),
        inline=False
    )

    if league:
        embed.set_footer(text=i18n.t('factors.footer_team', lang))
    else:
        embed.set_footer(text=i18n.t('factors.footer_global', lang))

    await interaction.response.send_message(embed=embed)



# ============================================================================
# /history — player score history over a date range
# ============================================================================

async def _build_history_embed(player: str, start_date, end_date, lang: str, conn=None, season_label: str | None = None) -> discord.Embed | None:
    """
    Shared history embed builder for /history and /legacy history.
    Returns None if there are no scores in range — caller shows the
    "no scores" message in that case.
    """
    # event_type/tier lives on the matchup_day row for that
    # (team_id, game_date), not reliably on the game_scores entry itself —
    # LEFT JOIN since not every date necessarily has a recorded matchup
    # (e.g. a score logged for a day nobody ran /ladder or /matchup for),
    # in which case the tier is genuinely unknown, not zero rows.
    rows = await db.fetchall(
        """
        SELECT gs.game_date, gs.score, md.event_type, gs.is_forfeit, gs.is_excused,
               gs.def_ovr_faced, gs.fourth_downs, gs.fourth_down_convs, gs.fumbles
        FROM game_scores gs
        JOIN players p ON p.id = gs.player_id
        LEFT JOIN matchup_day md ON md.team_id = gs.team_id AND md.game_date = gs.game_date
        WHERE p.ign = ? AND gs.game_date >= ? AND gs.game_date <= ?
        ORDER BY gs.game_date ASC
        """,
        (player, str(start_date), str(end_date)), conn=conn
    )

    if not rows:
        return None

    # Stats
    scores      = [r['score'] for r in rows if not r['is_forfeit'] and not r.get('is_excused') and r['score'] is not None]
    missed_ct   = sum(1 for r in rows if r['is_forfeit'])
    total_4th   = sum(r['fourth_downs']      or 0 for r in rows)
    total_conv  = sum(r['fourth_down_convs'] or 0 for r in rows)
    total_fumbles = sum(r['fumbles'] or 0 for r in rows if not r['is_forfeit'] and not r['is_excused'])
    conv_rate   = f"{round(total_conv/total_4th*100,1)}%" if total_4th else "—"
    avg         = round(sum(scores)/len(scores), 2) if scores else 0
    high        = max(scores) if scores else 0
    low         = min(scores) if scores else 0

    # Header line
    col_date = i18n.t('history.col.date', lang)
    col_evt  = i18n.t('history.col.evt', lang)
    col_sc   = i18n.t('history.col.sc', lang)
    col_def  = i18n.t('history.col.def', lang)
    col_4th  = i18n.t('history.col.4th', lang)
    header = f"{col_date:<12} {col_evt:<5} {col_sc:>4} {col_def:>5} {col_4th:>7}"
    sep    = "─" * len(header)

    # Build all data lines
    data_lines = []
    for r in rows:
        evt    = (r['event_type'] or "—")[:5]
        score  = "E" if r['is_excused'] else ("M" if r['is_forfeit'] else (f"{r['score']:.0f}" if r['score'] is not None else "—"))
        def_s  = str(r['def_ovr_faced']) if r['def_ovr_faced'] else "—"
        fourth = f"{r['fourth_down_convs']}/{r['fourth_downs']}" if r['fourth_downs'] else "—"
        data_lines.append(f"{r['game_date']:<12} {evt:<5} {score:>4} {def_s:>5} {fourth:>7}")

    # Stats footer
    footer = [sep, i18n.t('history.footer.games_avg', lang, games=len(rows), avg=avg, hi=high, lo=low)]
    if total_4th:
        footer.append(i18n.t('history.footer.4th_downs', lang, conv=total_conv, total=total_4th, rate=conv_rate))
    if missed_ct:
        footer.append(i18n.t('history.footer.missed', lang, count=missed_ct))
    if total_fumbles:
        footer.append(i18n.t('history.footer.fumbles', lang, count=total_fumbles))

    # Split data into pages of 15 rows each, each page fits in one code block
    PAGE = 15
    title = i18n.t('history.title', lang, player=player, start=start_date, end=end_date)
    if season_label:
        title += f"  {season_label}"
    embed = discord.Embed(title=title, color=discord.Color.blue())

    pages = [data_lines[i:i+PAGE] for i in range(0, len(data_lines), PAGE)]
    for idx, page in enumerate(pages):
        block_lines = [header, sep] + page
        # Add footer only on last page
        if idx == len(pages) - 1:
            block_lines += footer
        value = "```\n" + "\n".join(block_lines) + "\n```"
        # Safety check — truncate if somehow still over 1024
        if len(value) > 1020:
            value = "```\n" + "".join(block_lines[:15]) + "...```"
        embed.add_field(
            name=i18n.t('history.field.scores_paged', lang, page=idx+1, total=len(pages)) if len(pages) > 1 else i18n.t('history.field.scores', lang),
            value=value,
            inline=False
        )

    return embed


@tree.command(name="history", description="View a player's score history over a date range")
@app_commands.describe(
    player="Player IGN",
    start="Start date (YYYY-MM-DD)",
    end="End date (YYYY-MM-DD), defaults to today",
)
@app_commands.autocomplete(player=player_autocomplete)
async def history_slash(interaction: discord.Interaction,
                        player: str,
                        start: str,
                        end: str = None):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()

    try:
        start_date = datetime.date.fromisoformat(start)
    except ValueError:
        await interaction.followup.send(i18n.t('history.err.start_date', lang), ephemeral=True)
        return

    if end is None:
        end_date = datetime.date.today()
    else:
        try:
            end_date = datetime.date.fromisoformat(end)
        except ValueError:
            await interaction.followup.send(i18n.t('history.err.end_date', lang), ephemeral=True)
            return

    if end_date < start_date:
        await interaction.followup.send(i18n.t('history.err.end_before_start', lang), ephemeral=True)
        return

    embed = await _build_history_embed(player, start_date, end_date, lang)
    if embed is None:
        await interaction.followup.send(
            i18n.t('history.no_scores', lang, player=player, start=start_date, end=end_date)
        )
        return

    await interaction.followup.send(embed=embed)



# ============================================================================
# /league — add or rename a league
# ============================================================================

class LeagueAddModal(Modal, title="Add New League"):
    def __init__(self, lang: str = 'en'):
        super().__init__()
        self.lang = lang
        self.title = i18n.t('league.add_modal.title', lang)

        self.league_id = TextInput(max_length=2)
        self.league_name = TextInput(max_length=50)

        self.add_item(discord.ui.Label(text=i18n.t('league.add_modal.label_id', lang), component=self.league_id))
        self.add_item(discord.ui.Label(text=i18n.t('league.add_modal.label_name', lang), component=self.league_name))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        lid  = self.league_id.value.strip().upper()
        name = self.league_name.value.strip()

        if len(lid) != 2 or not lid.isalpha():
            await interaction.response.send_message(
                i18n.t('league.err.id_must_be_2_letters', lang), ephemeral=True
            )
            return

        existing = await db.fetchone("SELECT id FROM teams WHERE id=?", (lid,))
        if existing:
            await interaction.response.send_message(
                i18n.t('league.err.already_exists', lang, id=lid), ephemeral=True
            )
            return

        await db.execute(
            "INSERT INTO teams (id, name, sheet_name) VALUES (?, ?, ?)",
            (lid, name, name)
        )
        # Add to every module's league-name map and to LEAGUE_CHOICES at runtime
        _sync_league_name(lid, name)
        LEAGUE_CHOICES.append(app_commands.Choice(name=name, value=lid))

        await interaction.response.send_message(
            i18n.t('league.add.success', lang, name=name, id=lid), ephemeral=True
        )


class LeagueRenameView(View):
    def __init__(self, leagues: list[dict], lang: str = 'en'):
        super().__init__(timeout=60)
        self.lang = lang
        options = [
            discord.SelectOption(label=f"{r['name']} ({r['id']})", value=r['id'])
            for r in leagues
        ]
        sel = Select(placeholder=i18n.t('league.rename_select_placeholder', lang), options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        lid = interaction.data["values"][0]
        lang = self.lang
        self.stop()

        class RenameModal(Modal, title=f"Rename League {lid}"):
            def __init__(self2):
                super().__init__()
                self2.title = i18n.t('league.rename_modal_title', lang, id=lid)
                self2.new_name = TextInput(max_length=50)
                self2.add_item(discord.ui.Label(text=i18n.t('league.rename_modal_label', lang), component=self2.new_name))

            async def on_submit(self2, inter):
                name = self2.new_name.value.strip()
                await db.execute("UPDATE teams SET name=?, sheet_name=? WHERE id=?", (name, name, lid))
                _sync_league_name(lid, name)
                # Update LEAGUE_CHOICES
                for i, c in enumerate(LEAGUE_CHOICES):
                    if c.value == lid:
                        LEAGUE_CHOICES[i] = app_commands.Choice(name=name, value=lid)
                        break
                await inter.response.send_message(
                    i18n.t('league.rename.success', lang, id=lid, name=name),
                    ephemeral=True
                )

        await interaction.response.send_modal(RenameModal())


@tree.command(name="league", description="Add a new league or rename an existing one")
@app_commands.describe(action="What to do")
@app_commands.choices(action=[
    app_commands.Choice(name="Add new league",    value="add"),
    app_commands.Choice(name="Rename a league",   value="rename"),
])
async def league_slash(interaction: discord.Interaction, action: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    if action == "add":
        await interaction.response.send_modal(LeagueAddModal(lang=lang))
    elif action == "rename":
        leagues = await db.fetchall("SELECT id, name FROM teams ORDER BY id")
        await interaction.response.send_message(
            i18n.t('league.which_rename_prompt', lang),
            view=LeagueRenameView(leagues, lang=lang),
            ephemeral=True
        )



# ============================================================================
# !test — run the test suite and post results (Administrator only)
# ============================================================================

# ============================================================================
# /matchup — edit matchup info + all player scores (Administrator only)
# ============================================================================

class UpdateMatchupInfoModal(Modal, title="Matchup Info"):
    def __init__(self, matchup: dict | None, lang: str = 'en'):
        super().__init__()
        self.title = i18n.t('matchup.info_modal.title', lang)

        self.opp_ign = TextInput(max_length=50, required=False)
        self.event_type = TextInput(max_length=10, required=False)
        self.our_rank = TextInput(max_length=4, required=False)
        self.opp_rank = TextInput(max_length=4, required=False)

        self.add_item(discord.ui.Label(text=i18n.t('matchup.info_modal.label_opp', lang), component=self.opp_ign))
        self.add_item(discord.ui.Label(text=i18n.t('matchup.info_modal.label_division', lang), component=self.event_type))
        self.add_item(discord.ui.Label(text=i18n.t('matchup.info_modal.label_our_rank', lang), component=self.our_rank))
        self.add_item(discord.ui.Label(text=i18n.t('matchup.info_modal.label_opp_rank', lang), component=self.opp_rank))
        if matchup:
            if matchup.get('opp_ign'):    self.opp_ign.default    = matchup['opp_ign']
            if matchup.get('event_type'): self.event_type.default = matchup['event_type']
            if matchup.get('our_rank'):   self.our_rank.default   = str(matchup['our_rank'])
            if matchup.get('opp_rank'):   self.opp_rank.default   = str(matchup['opp_rank'])

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class UpdateScoresModal(Modal):
    def __init__(self, players: list[dict], page: int, total_pages: int, lang: str = 'en'):
        super().__init__(title=i18n.t('matchup.scores_modal.title', lang, page=page + 1, total=total_pages))
        self.player_names = []
        placeholder = i18n.t('matchup.scores_modal.placeholder', lang)
        for p in players:
            ign   = p['ign']
            if p.get('is_excused'):
                score = 'E'
            elif p.get('is_forfeit'):
                score = 'M'
            elif p.get('score') is not None:
                score = str(int(p['score'])) if p['score'] == int(p['score']) else str(p['score'])
            else:
                score = ''
            field = TextInput(
                label=ign[:45],
                default=score,
                placeholder=placeholder,
                max_length=6,
                required=False
            )
            self.player_names.append(ign)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

    def get_scores(self) -> dict[str, tuple[float | None, bool, bool]]:
        """Return {ign: (score, is_forfeit, is_excused)} for all filled fields."""
        result = {}
        for i, ign in enumerate(self.player_names):
            field = self.children[i]
            val   = field.value.strip().upper() if field.value else ''
            if not val:
                result[ign] = (None, False, False)
            elif val in ('M', 'F'):  # F kept as a legacy alias for missed drives
                result[ign] = (0.0, True, False)
            elif val == 'E':
                result[ign] = (None, False, True)
            else:
                try:
                    result[ign] = (float(val), False, False)
                except ValueError:
                    result[ign] = (None, False, False)
        return result


class UpdateMatchupView(View):
    """Multi-step update flow: matchup info → score pages → outcome → confirm."""

    PAGE_SIZE = 5

    def __init__(self, team_id: str, game_date, matchup: dict | None,
                 players: list[dict], lang: str = 'en'):
        super().__init__(timeout=300)
        self.team_id   = team_id
        self.game_date = game_date
        self.matchup   = matchup or {}
        self.players   = players
        self.lang      = lang
        self.pending_scores: dict[str, tuple] = {}
        self.total_pages = max(1, -(-len(players) // self.PAGE_SIZE))
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lang = self.lang

        edit_info = Button(label=i18n.t('matchup.btn.edit_info', lang), style=discord.ButtonStyle.primary, row=0)
        edit_info.callback = self._edit_info
        self.add_item(edit_info)

        for page in range(self.total_pages):
            start = page * self.PAGE_SIZE
            end   = start + self.PAGE_SIZE
            chunk = self.players[start:end]
            filled = sum(
                1 for p in chunk
                if (p['ign'] in self.pending_scores and self.pending_scores[p['ign']][0] is not None)
                or (p['ign'] not in self.pending_scores and p.get('score') is not None)
            )
            lbl   = i18n.t('matchup.btn.scores_page', lang, page=page + 1, total=self.total_pages, filled=filled, count=len(chunk))
            btn   = Button(label=lbl,
                           style=discord.ButtonStyle.success if filled == len(chunk) else discord.ButtonStyle.secondary,
                           row=1 + page // 5)
            btn.callback = self._make_score_page(page)
            self.add_item(btn)

        # Row 3: outcome button
        outcome    = self.matchup.get('outcome')    or ''
        our_score  = self.matchup.get('our_score')  or 0
        opp_score  = self.matchup.get('opp_score')  or 0
        opp_drives = self.matchup.get('opp_drives') or 0
        if outcome:
            outcome_label = i18n.t('matchup.outcome_label', lang, outcome=outcome, our=our_score, opp=opp_score, drives=opp_drives)
        else:
            outcome_label = i18n.t('matchup.btn.set_outcome', lang)
        outcome_btn = Button(
            label=outcome_label[:80],
            style=discord.ButtonStyle.success if outcome else discord.ButtonStyle.secondary,
            row=3
        )
        outcome_btn.callback = self._edit_outcome
        self.add_item(outcome_btn)

        # Row 4: save — count pending new entries + players already scored in DB
        filled_total = sum(
            1 for p in self.players
            if (p['ign'] in self.pending_scores and self.pending_scores[p['ign']][0] is not None)
            or (p['ign'] not in self.pending_scores and p.get('score') is not None)
        )
        save = Button(
            label=i18n.t('matchup.btn.save', lang, filled=filled_total, total=len(self.players)),
            style=discord.ButtonStyle.green if filled_total == len(self.players) else discord.ButtonStyle.gray,
            row=4
        )
        save.callback = self._save
        self.add_item(save)

    def _build_embed(self) -> discord.Embed:
        lang   = self.lang
        league = LEAGUE_NAMES.get(self.team_id, self.team_id)
        embed  = discord.Embed(
            title=i18n.t('matchup.embed.title', lang, league=league, date=self.game_date),
            color=discord.Color.orange()
        )

        # Matchup info
        opp      = self.matchup.get('opp_ign', '—')
        evt      = self.matchup.get('event_type', '—')
        our_rank = self.matchup.get('our_rank', '—')
        opp_rank = self.matchup.get('opp_rank', '—')
        embed.add_field(
            name=i18n.t('matchup.field.matchup', lang),
            value=i18n.t('matchup.field.matchup_value', lang, opp=opp, division=evt, our_rank=our_rank, opp_rank=opp_rank),
            inline=False
        )

        # Outcome info
        our_s      = self.matchup.get('our_score',  '—')
        our_drives = self.matchup.get('our_drives', '—')
        opp_s      = self.matchup.get('opp_score',  '—')
        opp_drives = self.matchup.get('opp_drives', '—')
        outcome    = self.matchup.get('outcome',    '—')
        embed.add_field(
            name=i18n.t('matchup.field.outcome', lang),
            value=i18n.t('matchup.field.outcome_value', lang, outcome=outcome, our_s=our_s, our_drives=our_drives,
                        opp_s=opp_s, opp_drives=opp_drives),
            inline=False
        )

        # Score summary
        lines = []
        for p in self.players:
            ign = p['ign']
            if ign in self.pending_scores:
                tup    = self.pending_scores[ign]
                score, missed = tup[0], tup[1]
                excused = tup[2] if len(tup) > 2 else False
                val  = "E" if excused else ("M" if missed else (str(score) if score is not None else "—"))
                icon = "✅"
            else:
                val  = str(p['score']) if p.get('score') is not None else "—"
                icon = "📌"
            lines.append(f"{icon} {ign}: **{val}**")

        half = len(lines) // 2 + len(lines) % 2
        embed.add_field(name=i18n.t('matchup.field.scores', lang), value="\n".join(lines[:half]) or "—", inline=True)
        embed.add_field(name="\u200b",  value="\n".join(lines[half:]) or "—", inline=True)
        embed.set_footer(text=i18n.t('matchup.footer', lang))
        return embed

    async def _edit_info(self, interaction: discord.Interaction):
        modal = UpdateMatchupInfoModal(self.matchup, lang=self.lang)
        orig  = modal.on_submit

        async def patched(inter):
            await orig(inter)
            val = modal.opp_ign.value.strip()
            if val:    self.matchup['opp_ign']    = val
            val = modal.event_type.value.strip().upper()
            if val:    self.matchup['event_type'] = val
            val = modal.our_rank.value.strip()
            if val:
                try:   self.matchup['our_rank']   = int(val)
                except: pass
            val = modal.opp_rank.value.strip()
            if val:
                try:   self.matchup['opp_rank']   = int(val)
                except: pass
            self._rebuild()
            await inter.edit_original_response(embed=self._build_embed(), view=self)

        modal.on_submit = patched
        await interaction.response.send_modal(modal)

    def _make_score_page(self, page: int):
        async def callback(interaction: discord.Interaction):
            start  = page * self.PAGE_SIZE
            chunk  = self.players[start:start + self.PAGE_SIZE]
            # Pre-fill with pending scores if already set, else existing
            prefilled = []
            for p in chunk:
                ign = p['ign']
                if ign in self.pending_scores:
                    tup    = self.pending_scores[ign]
                    score  = tup[0]
                    forfeit  = tup[1]
                    excused  = tup[2] if len(tup) > 2 else False
                    prefilled.append({'ign': ign, 'score': score,
                                      'is_forfeit': forfeit, 'is_excused': excused})
                else:
                    prefilled.append(p)
            modal = UpdateScoresModal(prefilled, page, self.total_pages, lang=self.lang)
            orig  = modal.on_submit

            async def patched(inter):
                await orig(inter)
                for ign, score_tuple in modal.get_scores().items():
                    score, forfeit, excused = score_tuple
                    # Whatever was in the cell at submission — blank, a number, M, or E —
                    # is now the intended value, whether or not something was there
                    # before. A blank cell always means "clear this entry", the same
                    # whether the admin never touched it or explicitly deleted an
                    # existing value; there's no need to distinguish the two.
                    self.pending_scores[ign] = (score, forfeit, excused)
                self._rebuild()
                await inter.edit_original_response(embed=self._build_embed(), view=self)

            modal.on_submit = patched
            await interaction.response.send_modal(modal)
        return callback

    async def _edit_outcome(self, interaction: discord.Interaction):
        """Open the outcome editor modal pre-filled with existing values."""
        lang = self.lang

        class OutcomeEditModal(Modal, title="Set Outcome"):
            async def on_submit(self2, inter):
                await inter.response.defer()

        modal = OutcomeEditModal()
        modal.title = i18n.t('matchup.outcome_modal.title', lang)

        modal.our_score = TextInput(max_length=6, required=False)
        modal.our_drives = TextInput(max_length=4, required=False)
        modal.opp_score = TextInput(max_length=6, required=False)
        modal.opp_drives = TextInput(max_length=4, required=False)
        modal.outcome = TextInput(max_length=4, required=False)

        modal.add_item(discord.ui.Label(text=i18n.t('matchup.outcome_modal.label_our_score', lang), component=modal.our_score))
        modal.add_item(discord.ui.Label(text=i18n.t('matchup.outcome_modal.label_our_drives', lang), component=modal.our_drives))
        modal.add_item(discord.ui.Label(text=i18n.t('matchup.outcome_modal.label_opp_score', lang), component=modal.opp_score))
        modal.add_item(discord.ui.Label(text=i18n.t('matchup.outcome_modal.label_opp_drives', lang), component=modal.opp_drives))
        modal.add_item(discord.ui.Label(text=i18n.t('matchup.outcome_modal.label_result', lang), component=modal.outcome))
        if self.matchup.get('our_score'):  modal.our_score.default  = str(self.matchup['our_score'])
        if self.matchup.get('our_drives'): modal.our_drives.default = str(self.matchup['our_drives'])
        if self.matchup.get('opp_score'):  modal.opp_score.default  = str(self.matchup['opp_score'])
        if self.matchup.get('opp_drives'): modal.opp_drives.default = str(self.matchup['opp_drives'])
        if self.matchup.get('outcome'):    modal.outcome.default    = self.matchup['outcome']

        orig = modal.on_submit
        async def patched(inter):
            await orig(inter)
            val = modal.our_score.value.strip()
            if val:
                try: self.matchup['our_score']  = int(val)
                except: pass
            val = modal.our_drives.value.strip()
            if val:
                try: self.matchup['our_drives'] = int(val)
                except: pass
            val = modal.opp_score.value.strip()
            if val:
                try: self.matchup['opp_score']  = int(val)
                except: pass
            val = modal.opp_drives.value.strip()
            if val:
                try: self.matchup['opp_drives'] = int(val)
                except: pass
            val = modal.outcome.value.strip().upper()
            if val in ('WIN', 'LOSS', 'TIE'):
                self.matchup['outcome'] = val
            self._rebuild()
            await inter.edit_original_response(embed=self._build_embed(), view=self)

        modal.on_submit = patched
        await interaction.response.send_modal(modal)

    async def _save(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()

        saved_scores   = 0
        saved_matchup  = False

        # Save matchup info
        if self.matchup.get('opp_ign'):
            existing = await db.fetchone(
                "SELECT id FROM matchup_day WHERE team_id=? AND game_date=?",
                (self.team_id, str(self.game_date))
            )
            if existing:
                await db.execute(
                    """UPDATE matchup_day SET opp_ign=?, event_type=?,
                       our_score=?, our_drives=?, opp_score=?, opp_drives=?, outcome=?,
                       our_rank=?, opp_rank=?, our_defaults=?, opp_defaults=?
                       WHERE team_id=? AND game_date=?""",
                    (self.matchup.get('opp_ign'), self.matchup.get('event_type'),
                     self.matchup.get('our_score'), self.matchup.get('our_drives', 0),
                     self.matchup.get('opp_score'), self.matchup.get('opp_drives', 0),
                     self.matchup.get('outcome'),
                     self.matchup.get('our_rank'), self.matchup.get('opp_rank'),
                     self.matchup.get('our_defaults', 0), self.matchup.get('opp_defaults', 0),
                     self.team_id, str(self.game_date))
                )
            else:
                await db.execute(
                    """INSERT INTO matchup_day (team_id, game_date, opp_ign, event_type,
                       our_score, our_drives, opp_score, opp_drives, outcome,
                       our_rank, opp_rank, our_defaults, opp_defaults)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self.team_id, str(self.game_date),
                     self.matchup.get('opp_ign'), self.matchup.get('event_type'),
                     self.matchup.get('our_score'), self.matchup.get('our_drives', 0),
                     self.matchup.get('opp_score'), self.matchup.get('opp_drives', 0),
                     self.matchup.get('outcome'),
                     self.matchup.get('our_rank'), self.matchup.get('opp_rank'),
                     self.matchup.get('our_defaults', 0), self.matchup.get('opp_defaults', 0))
                )
            saved_matchup = True

        # Save player scores
        for ign, score_tuple in self.pending_scores.items():
            score, is_forfeit = score_tuple[0], score_tuple[1]
            is_excused = score_tuple[2] if len(score_tuple) > 2 else False
            player = await db.fetchone(
                "SELECT id, team_id FROM players WHERE ign=? AND status != 'I' LIMIT 1", (ign,)
            )
            if not player: continue

            # Find any existing score for this player on this date
            # (don't filter on event_type — scores may have been imported with E1/E2/etc.)
            existing = await db.fetchone(
                "SELECT id FROM game_scores WHERE player_id=? AND game_date=? LIMIT 1",
                (player['id'], str(self.game_date))
            )

            is_blank = score is None and not is_forfeit and not is_excused
            if is_blank:
                # Nothing in the cell at submission — the entry should not
                # exist at all (e.g. a player who was accidentally scored for
                # a matchup they weren't actually part of). If there's an
                # existing row, remove it entirely rather than leaving a
                # phantom row with everything blanked out; if there was never
                # a row, there's nothing to do.
                if existing:
                    await db.execute("DELETE FROM game_scores WHERE id=?", (existing['id'],))
                    saved_scores += 1
                continue

            if existing:
                await db.execute(
                    "UPDATE game_scores SET score=?, is_forfeit=?, is_excused=? WHERE id=?",
                    (score, int(is_forfeit), int(is_excused), existing['id'])
                )
            else:
                await db.execute(
                    "INSERT INTO game_scores (player_id, team_id, game_date, score, is_forfeit, is_excused) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (player['id'], player['team_id'], str(self.game_date),
                     score, int(is_forfeit), int(is_excused))
                )
            saved_scores += 1

        lang   = self.lang
        league = LEAGUE_NAMES.get(self.team_id, self.team_id)
        embed  = discord.Embed(
            title=i18n.t('matchup.saved.title', lang),
            color=discord.Color.green()
        )
        if saved_matchup:
            opp = self.matchup.get('opp_ign', '?')
            embed.add_field(name=i18n.t('matchup.saved.field_matchup', lang),
                            value=i18n.t('matchup.saved.matchup_value', lang, opp=opp), inline=True)
        embed.add_field(name=i18n.t('matchup.saved.field_scores', lang),
                        value=i18n.t('matchup.saved.scores_value', lang, count=saved_scores), inline=True)
        await interaction.edit_original_response(embed=embed, view=None)


@tree.command(name="matchup", description="Edit matchup info and player scores for a given day")
@app_commands.describe(
    league="League to update",
    date="Date (YYYY-MM-DD), defaults to today",
    our_defaults="Number of default teams on our side",
    opp_defaults="Number of default teams on opponent side"
)
@app_commands.choices(league=LEAGUE_CHOICES)
async def matchup_slash(interaction: discord.Interaction,
                               league: str, date: str = None,
                               our_defaults: int = None, opp_defaults: int = None):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()

    if date is None:
        game_date = game_day()
    else:
        try:
            game_date = datetime.date.fromisoformat(date)
        except ValueError:
            await interaction.followup.send(i18n.t('common.invalid_date_format', lang), ephemeral=True)
            return

    # Load existing matchup
    matchup = await db.fetchone(
        "SELECT * FROM matchup_day WHERE team_id=? AND game_date=?",
        (league, str(game_date))
    )

    # Apply defaults overrides if passed, otherwise use stored values
    matchup_dict = dict(matchup) if matchup else {}
    if our_defaults is not None:
        matchup_dict['our_defaults'] = max(0, min(our_defaults, 15))
    if opp_defaults is not None:
        matchup_dict['opp_defaults'] = max(0, min(opp_defaults, 15))

    # Load active players with their scores for this date
    rows = await db.fetchall(
        """
        SELECT p.ign,
               gs.score,
               gs.is_forfeit
        FROM players p
        LEFT JOIN game_scores gs
            ON gs.player_id = p.id
           AND gs.game_date = ?
        WHERE p.team_id = ? AND p.status = 'A'
        ORDER BY p.total_ovr DESC
        """,
        (str(game_date), league)
    )

    if not rows:
        await interaction.followup.send(
            i18n.t('matchup.err.no_active_players', lang, league=LEAGUE_NAMES[league]), ephemeral=True
        )
        return

    players = [dict(r) for r in rows]
    view    = UpdateMatchupView(league, game_date, matchup_dict if matchup_dict else None, players, lang=lang)
    await interaction.edit_original_response(embed=view._build_embed(), view=view)



# ============================================================================
# /opp — show a player's opponent for today's ladder matchup
# ============================================================================

@tree.command(name="opp", description="Show a player's opponent in today's ladder matchup")
@app_commands.describe(player="Player IGN")
@app_commands.autocomplete(player=player_autocomplete)
async def opp_slash(interaction: discord.Interaction, player: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()

    player_row = await db.get_player(player)
    if player_row is None:
        await interaction.followup.send(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    team_id   = player_row['team_id']
    today     = game_day()

    # Try daily snapshot first
    slot_row = await db.fetchone(
        """SELECT ml.slot, ml.our_ign, ml.opp_ign, ml.opp_def_ovr, ml.our_total_ovr,
                  ml.tier, ml.result, ml.our_pts, ml.opp_pts
           FROM matchup_ladder ml
           WHERE ml.team_id = ? AND ml.game_date = ? AND ml.our_ign = ?""",
        (team_id, str(today), player)
    )

    # Fall back to static reference
    source = i18n.t('opp.source_today', lang)
    if slot_row is None:
        slot_row = await db.fetchone(
            """SELECT slot, our_ign, opp_ign, opp_def_ovr, our_total_ovr, tier, tier_score
               FROM ladder_matchups
               WHERE team_id = ? AND our_ign = ?""",
            (team_id, player)
        )
        source = i18n.t('opp.source_static', lang)

    if slot_row is None:
        await interaction.followup.send(
            i18n.t('opp.no_matchup', lang, player=player),
            ephemeral=True
        )
        return

    league    = LEAGUE_NAMES.get(team_id, team_id)
    slot      = slot_row['slot']
    opp_ign   = slot_row['opp_ign']
    opp_def   = slot_row['opp_def_ovr']
    our_ovr   = slot_row['our_total_ovr']
    tier      = slot_row.get('tier')
    result    = slot_row.get('result')
    our_pts   = slot_row.get('our_pts')
    opp_pts   = slot_row.get('opp_pts')

    # Get player's score today if available
    score_row = await db.fetchone(
        """SELECT gs.score, gs.is_forfeit, gs.is_excused
           FROM game_scores gs
           JOIN players p ON p.id = gs.player_id
           WHERE p.ign = ? AND gs.game_date = ?
           LIMIT 1""",
        (player, str(today))
    )

    if result:
        color = discord.Color.green()  if result == 'WIN'  else                 discord.Color.red()    if result == 'LOSS' else                 discord.Color.yellow()
    else:
        color = discord.Color.blurple()

    embed = discord.Embed(
        title=f"🏈  {player}  vs  {opp_ign}",
        description=f"**{league}** · Slot #{slot} · {source}",
        color=color
    )

    embed.add_field(
        name=i18n.t('opp.field.opponent', lang),
        value=f"**{opp_ign}**\n" + i18n.t('opp.def_ovr_label', lang, ovr=opp_def or '\u2014'),
        inline=True
    )

    embed.add_field(
        name=i18n.t('opp.field.your_ovr', lang),
        value=f"**{our_ovr or '\u2014'}**" + (i18n.t('opp.tier_label', lang, tier=tier) if tier else ""),
        inline=True
    )

    if score_row and score_row['score'] is not None:
        if score_row['is_excused']:
            score_str = i18n.t('opp.score_excused', lang)
        elif score_row['is_forfeit']:
            score_str = i18n.t('opp.score_missed', lang)
        else:
            score_str = f"**{score_row['score']:.0f}**"
        embed.add_field(name=i18n.t('opp.field.your_score', lang), value=score_str, inline=True)
    else:
        embed.add_field(name=i18n.t('opp.field.your_score', lang), value=i18n.t('opp.not_scored', lang), inline=True)

    if result:
        pts_str = f"{our_pts}–{opp_pts}" if our_pts is not None else ""
        embed.add_field(
            name=i18n.t('opp.field.result', lang),
            value=f"**{result}** {pts_str}",
            inline=False
        )

    embed.set_footer(text=i18n.t('opp.footer', lang, today=today))
    await interaction.followup.send(embed=embed)



# ============================================================================
# !nukeguildcmds — one-time use: clear all guild-registered commands
# ============================================================================


# ============================================================================
# /newday — manually trigger new day reset
# ============================================================================

@tree.command(name="newday", description="Manually trigger the new day reset")
async def newday_slash(interaction: discord.Interaction):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    await newday()
    clear_rank_cache()
    await interaction.followup.send(i18n.t('newday.success', lang))


# ============================================================================
# /sync — force re-register slash commands to this server
# ============================================================================

@tree.command(name="sync", description="Force sync slash commands to this server")
async def sync_slash(interaction: discord.Interaction):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    tree.copy_global_to(guild=interaction.guild)
    await tree.sync(guild=interaction.guild)
    tree.clear_commands(guild=None)
    await tree.sync()
    count = len(tree.get_commands(guild=interaction.guild))
    await interaction.followup.send(i18n.t('sync.success', lang, count=count))


# ============================================================================
# /reloadgifs — reload all gif folders from disk
# ============================================================================

@tree.command(name="reloadgifs", description="Reload all GIF folders from disk")
async def reloadgifs_slash(interaction: discord.Interaction):
    lang = i18n.resolve_lang(interaction)
    if not (_is_admin(interaction) or any(r.name == 'Gif Master' for r in interaction.user.roles)):
        await interaction.response.send_message(i18n.t('gif.role_required', lang), ephemeral=True)
        return
    reload_gifs()
    await interaction.response.send_message(i18n.t('gif.reload_success', lang))


# ============================================================================
# /addgif — add a GIF to a folder
# ============================================================================

GIF_FOLDER_MAP = {
    "kobe": "gifs", "bad": "gifsbad", "6": "gifs6", "8": "gifs8",
    "12": "gifs12", "14": "gifs14", "16": "gifs16", "18": "gifs18",
    "20": "gifs20", "22": "gifs22", "24": "gifs24", "26": "gifs26",
    "30": "gifs30", "defense": "defense", "brunson": "brunson", "bingbong": "bingbong",
}

GIF_FOLDER_CHOICES = [
    app_commands.Choice(name=k, value=k) for k in GIF_FOLDER_MAP
]


@tree.command(name="addgif", description="Add a GIF to a folder")
@app_commands.describe(folder="Which GIF folder to add to", gif="The .gif file to upload")
@app_commands.choices(folder=GIF_FOLDER_CHOICES)
async def addgif_slash(interaction: discord.Interaction,
                       folder: str, gif: discord.Attachment):
    lang = i18n.resolve_lang(interaction)
    if not (_is_admin(interaction) or any(r.name == 'Gif Master' for r in interaction.user.roles)):
        await interaction.response.send_message(i18n.t('gif.role_required', lang), ephemeral=True)
        return
    await interaction.response.defer()

    folder_path = GIF_FOLDER_MAP.get(folder)
    if not folder_path:
        await interaction.followup.send(i18n.t('gif.err.invalid_folder', lang), ephemeral=True)
        return

    if not gif.filename.lower().endswith(".gif"):
        await interaction.followup.send(i18n.t('gif.err.not_gif', lang), ephemeral=True)
        return

    if gif.size > 5 * 1024 * 1024:
        await interaction.followup.send(
            i18n.t('gif.err.too_large', lang, size=gif.size // 1024), ephemeral=True
        )
        return

    save_path = os.path.join(folder_path, gif.filename)
    if os.path.exists(save_path):
        base, ext = os.path.splitext(gif.filename)
        save_path = os.path.join(folder_path, f"{base}_{int(time.time())}{ext}")

    await gif.save(save_path)
    reload_gifs()
    await interaction.followup.send(i18n.t('gif.add_success', lang, filename=os.path.basename(save_path), folder=folder_path))


# ============================================================================
# /tournament — manage tournaments
# ============================================================================

@tree.command(name="tournament_start", description="Start a new tournament")
@app_commands.describe(name="Tournament name", players="Space-separated list of player IGNs")
async def tournament_start_slash(interaction: discord.Interaction, name: str, players: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    player_list = players.split()
    if len(player_list) < 2:
        await interaction.followup.send(i18n.t('tournament.err.need_2_players', lang))
        return
    try:
        tid = await tournaments.create(player_list, name=name)
    except ValueError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return
    embed = await tournaments.build_embed(tid, lang=lang)
    await interaction.followup.send(i18n.t('tournament.start.success', lang, name=name, id=tid), embed=embed)


@tree.command(name="tournament_result", description="Record a tournament match result")
@app_commands.describe(tournament_id="Tournament ID", match_num="Match number", winner="Winning player IGN")
async def tournament_result_slash(interaction: discord.Interaction,
                                   tournament_id: str, match_num: int, winner: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    try:
        recorded, over = await tournaments.record_result(tournament_id, match_num, winner)
    except ValueError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return
    embed = await tournaments.build_embed(tournament_id, lang=lang)
    if over:
        await interaction.followup.send(i18n.t('tournament.champion', lang, winner=recorded), embed=embed)
    else:
        await interaction.followup.send(i18n.t('tournament.match_result', lang, num=match_num, winner=recorded), embed=embed)


@tree.command(name="tournament_bracket", description="View a tournament bracket")
@app_commands.describe(tournament_id="Tournament ID")
async def tournament_bracket_slash(interaction: discord.Interaction, tournament_id: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    try:
        embed = await tournaments.build_embed(tournament_id, lang=lang)
    except ValueError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return
    await interaction.followup.send(embed=embed)


@tree.command(name="tournament_list", description="List all tournaments")
async def tournament_list_slash(interaction: discord.Interaction):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    embed = await tournaments.build_list_embed(lang=lang)
    await interaction.followup.send(embed=embed)


# ============================================================================
# /nukeguildcmds — clear stale guild commands (one-time use)
# ============================================================================

@tree.command(name="nukeguildcmds", description="Clear all guild-registered commands for this bot")
async def nukeguildcmds_slash(interaction: discord.Interaction):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    import aiohttp
    guild_id = str(interaction.guild_id)
    app_id   = str(bot.application_id)
    token    = os.getenv("DISCORD_TOKEN")
    headers  = {"Authorization": f"Bot {token}"}
    base     = "https://discord.com/api/v10"

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"{base}/applications/{app_id}/guilds/{guild_id}/commands") as r:
            our_cmds = await r.json()
        async with session.put(
            f"{base}/applications/{app_id}/guilds/{guild_id}/commands", json=[]
        ) as r:
            status = r.status
        async with session.get(f"{base}/applications/{app_id}/commands") as r:
            global_cmds = await r.json()

    await interaction.followup.send(
        i18n.t('nuke.result', lang, guild_id=guild_id, count=len(our_cmds), status=status, global_count=len(global_cmds))
    )


# ============================================================================
# /test — run the unit test suite
# ============================================================================

@tree.command(name="test", description="Run the unit test suite and post results")
async def test_slash(interaction: discord.Interaction):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "tests.py", "-v",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="."
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        await interaction.followup.send(i18n.t('test_cmd.timeout', lang))
        return
    except Exception as e:
        await interaction.followup.send(i18n.t('test_cmd.failed_to_run', lang, error=e))
        return

    output     = (stdout + stderr).decode("utf-8", errors="replace")
    lines      = output.splitlines()
    ran_line   = next((l for l in lines if l.startswith("Ran ")), "")
    status_line = next((l for l in lines if l in ("OK",) or l.startswith("FAILED")), "")
    passed     = proc.returncode == 0

    color = discord.Color.green() if passed else discord.Color.red()
    icon  = "✅" if passed else "❌"
    embed = discord.Embed(title=i18n.t('test_cmd.title', lang, icon=icon), color=color)
    embed.add_field(name=i18n.t('test_cmd.field_summary', lang), value=f"`{ran_line}` — **{status_line}**", inline=False)

    if not passed:
        fail_lines = []
        in_block   = False
        for line in lines:
            if line.startswith("FAIL:") or line.startswith("ERROR:"):
                in_block = True
            if in_block:
                fail_lines.append(line)
            if in_block and line.startswith("---"):
                in_block = False
        detail = "\n".join(fail_lines)
        if len(detail) > 1020:
            detail = detail[:1017] + "..."
        if detail:
            embed.add_field(name=i18n.t('test_cmd.field_failures', lang), value=f"```\n{detail}\n```", inline=False)

    await interaction.followup.send(embed=embed)



# ============================================================================
# /nick, /ign, /rename — player name management
# ============================================================================

@tree.command(name="nick", description="Set a player's nickname (bot display name)")
@app_commands.describe(
    player="Start typing their real IGN or current nickname to find them",
    nickname="The new nickname to use in the bot"
)
@app_commands.autocomplete(player=nick_player_autocomplete)
async def nick_slash(interaction: discord.Interaction, player: str, nickname: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)

    # `player` is expected to be a player id string, selected from the
    # autocomplete list — real_ign alone can't reliably identify one exact
    # player since it isn't unique, so this never looks anyone up by that
    # text directly.
    row = None
    if player.isdigit():
        row = await db.fetchone("SELECT * FROM players WHERE id=?", (int(player),))
    if row is None:
        await interaction.response.send_message(
            i18n.t('nick.err.not_found', lang, real_ign=player),
            ephemeral=True
        )
        return

    # Make sure the new nickname isn't already taken by a different player
    clash = await db.fetchone(
        "SELECT id FROM players WHERE ign=? AND id != ? LIMIT 1",
        (nickname, row['id'])
    )
    if clash:
        await interaction.response.send_message(
            i18n.t('nick.err.taken', lang, nickname=nickname),
            ephemeral=True
        )
        return

    old_nick = row['ign']
    real_ign = row['real_ign']
    await db.execute(
        "UPDATE players SET ign=? WHERE id=?",
        (nickname, row['id'])
    )
    league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])
    embed = discord.Embed(title=i18n.t('nick.success.title', lang), color=discord.Color.green())
    embed.add_field(name=i18n.t('register.success.field_real_ign', lang), value=real_ign,  inline=True)
    embed.add_field(name=i18n.t('register.success.field_nickname', lang), value=nickname,  inline=True)
    embed.add_field(name=i18n.t('player.field.league', lang),             value=league,    inline=True)
    if old_nick != nickname:
        embed.set_footer(text=i18n.t('nick.footer.previously_known', lang, old_nick=old_nick))
    await interaction.response.send_message(embed=embed)


@tree.command(name="ign", description="Update a player's real in-game name (for when they change it in-game)")
@app_commands.describe(
    player="The player's current nickname",
    new_real_ign="Their new real in-game name"
)
@app_commands.autocomplete(player=player_autocomplete)
async def ign_slash(interaction: discord.Interaction, player: str, new_real_ign: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)

    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(
            i18n.t('common.player_not_found', lang, player=player), ephemeral=True
        )
        return

    old_real = row['real_ign'] or row['ign']
    await db.execute(
        "UPDATE players SET real_ign=? WHERE id=?",
        (new_real_ign, row['id'])
    )
    league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])
    embed = discord.Embed(title=i18n.t('ign_cmd.success.title', lang), color=discord.Color.green())
    embed.add_field(name=i18n.t('register.success.field_nickname', lang), value=player,       inline=True)
    embed.add_field(name=i18n.t('ign_cmd.field.old_real_ign', lang),       value=old_real,     inline=True)
    embed.add_field(name=i18n.t('ign_cmd.field.new_real_ign', lang),       value=new_real_ign, inline=True)
    embed.add_field(name=i18n.t('player.field.league', lang),              value=league,       inline=True)
    await interaction.response.send_message(embed=embed)


@tree.command(name="rename", description="Change a player's nickname")
@app_commands.describe(
    player="The player's current nickname",
    new_nickname="Their new nickname"
)
@app_commands.autocomplete(player=player_autocomplete)
async def rename_slash(interaction: discord.Interaction, player: str, new_nickname: str):
    if not await _require_admin(interaction): return
    lang = i18n.resolve_lang(interaction)

    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(
            i18n.t('common.player_not_found', lang, player=player), ephemeral=True
        )
        return

    # Check global nickname uniqueness
    clash = await db.fetchone(
        "SELECT id FROM players WHERE ign=? AND id != ? LIMIT 1",
        (new_nickname, row['id'])
    )
    if clash:
        await interaction.response.send_message(
            i18n.t('rename_cmd.err.taken', lang, nickname=new_nickname),
            ephemeral=True
        )
        return

    await db.execute(
        "UPDATE players SET ign=? WHERE id=?",
        (new_nickname, row['id'])
    )
    league = LEAGUE_NAMES.get(row['team_id'], row['team_id'])
    embed = discord.Embed(title=i18n.t('rename_cmd.success.title', lang), color=discord.Color.green())
    embed.add_field(name=i18n.t('rename_cmd.field.old_nickname', lang), value=player,       inline=True)
    embed.add_field(name=i18n.t('rename_cmd.field.new_nickname', lang), value=new_nickname, inline=True)
    embed.add_field(name=i18n.t('player.field.league', lang),           value=league,       inline=True)
    await interaction.response.send_message(embed=embed)


# ============================================================================
# STARTUP
# ============================================================================

async def safe_start():
    try:
        for attempt in range(3):
            try:
                await bot.start(TOKEN)
                return
            except discord.errors.HTTPException as e:
                if e.status == 429:
                    headers   = getattr(e.response, 'headers', {})
                    raw       = headers.get('Retry-After', '300')
                    try:
                        wait_time = float(raw)
                    except (ValueError, TypeError):
                        wait_time = 300 * (2 ** attempt)
                    if wait_time > 3600:
                        logger.critical(f"Cloudflare ban. Retry-After: {wait_time}s. Exiting.")
                        raise SystemExit(1)
                    logger.warning(f"Rate limited ({attempt+1}/3). Waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except (asyncio.CancelledError, SystemExit, KeyboardInterrupt):
                # Clean shutdown — don't retry
                raise
            except Exception as e:
                logger.error(f"Failed to start: {e}", exc_info=True)
                raise
    finally:
        # Always close DB on exit, regardless of how we stopped
        if not bot.is_closed():
            await bot.close()
        await db.close_archive_connections()
        await db.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(safe_start())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)