"""
ladder_flow.py — Interactive multi-step ladder builder.

Flow:
  Step 1 — Player toggle: from the league's active (rostered) players, pick
           exactly 16 to play this ladder; anyone not picked is rested for
           it, not inactive — "active/rostered" (up to 18, league
           membership — see /openspots) and "playing" (exactly 16, this
           specific ladder) are distinct concepts, not synonyms.
  Step 2 — Opponent CSV entry: two modals, 8 opponents each
  Step 3 — Sort criteria picker
  Step 4 — Reorder: two independently movable lists
  Step 5 — Final embed posted to channel
"""

import discord
from discord.ui import View, Button, Select, Modal, TextInput
import asyncio
from logger_config import global_logger as logger
import db
import i18n
from utils import (EMBED_FIELD_LIMIT, FENCED_FIELD_LIMIT,
                   chunk_lines_to_fit, truncate_cell)

MATCHUP_SIZE     = 16  # how many of a league's active/rostered players actually play a given ladder — see this file's header docstring for the playing-vs-active distinction
PLAYERS_PER_PAGE = 20

# Width of the two name columns in the final monospace table. Names longer
# than this are cut with '..' — the format specs pad but never truncate, so
# without this one long IGN both wrecks the column alignment and makes its
# row long enough to breach the field limit on its own, which no amount of
# chunking can fix.
_NAME_COL = 18

# The table is wrapped in a code fence, so it gets the fenced budget — see
# utils.CODE_FENCE_OVERHEAD for why that is not just EMBED_FIELD_LIMIT.
_TABLE_BUDGET = FENCED_FIELD_LIMIT
SORT_OPTION_KEYS = [
    ("ladder.sort.pwr_rank",    "pwr_rank"),
    ("ladder.sort.yearly_avg",  "avg_yearly"),
    ("ladder.sort.7day_avg",    "avg_7day"),
    ("ladder.sort.total_ovr",   "total_ovr"),
    ("ladder.sort.ladder_rank", "ladder_rank"),
]


def _sort_options(lang: str):
    """Translated (label, column) pairs — same 5 options, localized label text."""
    return [(i18n.t(key, lang), col) for key, col in SORT_OPTION_KEYS]


async def report_ui_error(interaction: discord.Interaction, error: BaseException,
                          where: str, lang: str = 'en'):
    """
    What a view or modal in this flow does when its callback raises.

    discord.py's default View.on_error logs to the `discord.ui.view` logger
    and nothing else, so with the library's logging unconfigured (which it
    was until logger_config started wiring discord.* up explicitly — see that
    module's docstring) the clicker got Discord's bare "This interaction
    failed" and the traceback went nowhere at all.

    Two jobs here: get the traceback into the log with the step name
    attached, and tell the person who clicked something true about what
    happened. Best-effort on the second — if the interaction is already dead
    (that being one of the ways to get here) the followup raises too, and
    that must not mask the original error.
    """
    logger.error(
        "Ladder UI error in %s: %s: %s", where, type(error).__name__, error,
        exc_info=error,
    )
    try:
        msg = i18n.t('ladder.ui_error', lang, where=where,
                     error=f"{type(error).__name__}: {error}")
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        logger.exception("Could not report the ladder UI error to the user")


# Loaded from the db's teams table at import (see db.load_league_names_sync)
# rather than imported from optimized_bot, which would be a circular import.
LEAGUE_NAMES = db.load_league_names_sync()


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class LadderState:
    def __init__(self, team_id: str, game_date, channel, lang: str = 'en'):
        self.team_id   = team_id
        self.game_date = game_date
        self.channel   = channel
        self.lang       = lang
        self.players:   list[dict] = []  # the full active/rostered pool (up to 18) this ladder can choose from
        self.selected:  list[str]  = []  # exactly MATCHUP_SIZE (16) of the above, chosen to play — the rest of self.players are rested for this ladder, not inactive
        self.opponents: list[dict] = []
        # From screenshot extraction, when available — the opposing league's
        # own name/division/rank aren't per-slot data like opponents are, they
        # describe the matchup as a whole, so they live directly on the state.
        self.opponent_league_name: str | None = None
        self.event_type:           str | None = None
        self.our_rank:              int | None = None


def sanitize_selection(selected: list[str], players: list[dict]) -> tuple[list[str], list[str]]:
    """
    Force `selected` into something the step-1 screen can actually render:
    only players who are in the pool, each at most once, at most
    MATCHUP_SIZE of them. Returns (clean, dropped).

    This exists because of a real bug. Step 1 shows a count of
    `len(state.selected)` while the tick on each player comes from
    `ign in state.selected` **for the players in the pool** — so anything in
    the list that isn't in the pool is counted but has no button, and
    anything in it twice is counted twice but ticks once. The reported
    symptom was 15 players ticked above a count of 16, with the phantom
    impossible to clear because nothing rendered it.

    The list arrives pre-populated from /ladder's screenshot extraction,
    which appended a match per extracted name with no dedup, no pool check
    and no cap — and the 16-player cap is enforced only inside the toggle
    callback, which never runs for a pre-populated list. That's how a count
    could start at 16 with 15 ticks and climb past 16 from there.

    Order is preserved: /ladder sorts the pre-selection by ladder_rank
    before handing it over, and that order decides the default slot order in
    step 3.
    """
    pool = {p['ign'] for p in players}
    clean: list[str] = []
    dropped: list[str] = []
    for ign in selected:
        if ign in clean:
            dropped.append(ign)          # same player matched twice
        elif ign not in pool:
            dropped.append(ign)          # not on this league's active roster
        elif len(clean) >= MATCHUP_SIZE:
            dropped.append(ign)          # past the cap
        else:
            clean.append(ign)
    return clean, dropped


# ---------------------------------------------------------------------------
# Step 1 — Player toggle: choosing who plays this ladder (vs. rests) from
# the league's full active/rostered pool
# ---------------------------------------------------------------------------

class PlayerToggleView(View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None):
        await report_ui_error(interaction, error, "step 1 (player selection)", self.state.lang)

    def __init__(self, state: LadderState):
        super().__init__(timeout=300)
        self.state = state
        self.page  = 0
        if not self.state.selected:
            self.state.selected = [p['ign'] for p in state.players[:MATCHUP_SIZE]]
        # Enforced here as well as at the entry point: this view renders the
        # count, so it's the last place the count and the ticks can be made
        # to agree no matter which path built the state. Idempotent on an
        # already-clean list.
        self.state.selected, dropped = sanitize_selection(
            self.state.selected, self.state.players)
        if dropped:
            logger.warning(
                f"Ladder selection for {self.state.team_id} dropped "
                f"{len(dropped)} unusable pre-selection(s): {dropped}"
            )
        self._rebuild()

    def _page_players(self):
        start = self.page * PLAYERS_PER_PAGE
        return self.state.players[start:start + PLAYERS_PER_PAGE]

    def _rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.state.players) - 1) // PLAYERS_PER_PAGE + 1)

        for i, p in enumerate(self._page_players()):
            ign      = p['ign']
            selected = ign in self.state.selected
            btn = Button(
                label=f"{'✅ ' if selected else ''}{ign}",
                style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
                row=i // 5
            )
            btn.callback = self._make_toggle(ign)
            self.add_item(btn)

        nav_row = 4

        if self.page > 0:
            prev = Button(label="◀", style=discord.ButtonStyle.blurple, row=nav_row)
            prev.callback = self._prev
            self.add_item(prev)

        count    = len(self.state.selected)
        next_btn = Button(
            label=i18n.t('ladder.step1.next_btn', self.state.lang, count=count, total=MATCHUP_SIZE),
            style=discord.ButtonStyle.green if count == MATCHUP_SIZE else discord.ButtonStyle.gray,
            disabled=(count != MATCHUP_SIZE),
            row=nav_row
        )
        next_btn.callback = self._advance
        self.add_item(next_btn)

        if self.page < total_pages - 1:
            nxt = Button(label="▶", style=discord.ButtonStyle.blurple, row=nav_row)
            nxt.callback = self._next
            self.add_item(nxt)

    def _make_toggle(self, ign: str):
        async def callback(interaction: discord.Interaction):
            if ign in self.state.selected:
                self.state.selected.remove(ign)
            else:
                if len(self.state.selected) >= MATCHUP_SIZE:
                    await interaction.response.send_message(
                        i18n.t('ladder.step1.already_selected', self.state.lang, total=MATCHUP_SIZE),
                        ephemeral=True
                    )
                    return
                self.state.selected.append(ign)
            self._rebuild()
            await interaction.response.edit_message(embed=self._build_embed(), view=self)
        return callback

    async def _prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _advance(self, interaction: discord.Interaction):
        """
        Step 1 -> step 2. Answers Discord and nothing else.

        This used to loop over every player in the pool running
        `UPDATE players SET status='A' WHERE ign=? AND team_id=?`, one
        db.execute (and therefore one commit, and therefore one fsync) per
        player, *before* responding to the click.

        That write was a guaranteed no-op: state.players comes from
        db.get_team_stats(), whose query is `team_id=? AND status='A'`, so
        every row it touched was already 'A'. Selection for a ladder is not
        stored on players.status at all — it lives in LadderState.selected
        and then in matchup_ladder (see this file's header on the
        active/rostered vs playing distinction).

        So it bought nothing and cost one fsync per rostered player on the
        critical path to Discord's 3-second acknowledgement deadline. Blow
        that deadline and the clicker gets "This interaction failed" with no
        further explanation, which is exactly the symptom this caused. The
        same failure mode is documented on db.upsert_ladder_slots, which was
        batched into a single transaction for this reason — this path just
        never got the same treatment.
        """
        self.stop()
        view = OpponentEntryView(self.state)
        await interaction.response.edit_message(embed=view._build_embed(), view=view)

    def _build_embed(self) -> discord.Embed:
        lang        = self.state.lang
        league      = LEAGUE_NAMES.get(self.state.team_id, self.state.team_id)
        count       = len(self.state.selected)
        total_pages = max(1, (len(self.state.players) - 1) // PLAYERS_PER_PAGE + 1)
        embed = discord.Embed(
            title=i18n.t('ladder.step1.title', lang, count=count, total=MATCHUP_SIZE),
            description=i18n.t('ladder.step1.desc', lang, league=league, page=self.page + 1,
                               total_pages=total_pages, total=MATCHUP_SIZE),
            color=discord.Color.blurple()
        )
        if self.state.selected:
            # One comma-joined line rather than one line per player, so this
            # is clamped directly instead of chunked. Same 1024 limit.
            value = ", ".join(f"`{truncate_cell(p, _NAME_COL)}`" for p in self.state.selected)
            if len(value) > EMBED_FIELD_LIMIT:
                value = value[:EMBED_FIELD_LIMIT - 3] + "..."
            embed.add_field(
                name=i18n.t('ladder.step1.selected_label', lang),
                value=value,
                inline=False
            )
        return embed


# ---------------------------------------------------------------------------
# Step 2 — Opponent CSV entry (two modals, 8 per modal)
# ---------------------------------------------------------------------------

def _parse_csv_opponents(text: str) -> list[dict]:
    """Parse comma-separated opponent lines: Name, TotalOVR, DefOVR"""
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        name      = parts[0] if len(parts) > 0 else '-'
        total_ovr = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else None
        def_ovr   = int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else None
        results.append({'name': name, 'total_ovr': total_ovr, 'def_ovr': def_ovr})
    return results


class OpponentCSVModal(Modal, title="Enter All 16 Opponents"):
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_ui_error(interaction, error, "step 2 (opponent entry)", self.lang)

    def __init__(self, lang: str = 'en'):
        super().__init__()
        self.lang = lang
        self.title = i18n.t('ladder.opponent_csv.modal_title', lang)

        self.opponents = TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="WolfpackMafia, 6481, 219\nTeamBeta, 7200, 245\n...",
            max_length=1600,
        )
        self.add_item(discord.ui.Label(text=i18n.t('ladder.opponent_csv.label', lang), component=self.opponents))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class LadderMatchupInfoModal(Modal, title="Matchup Info"):
    """
    Manually enter the opponent league name / division / our rank — the same
    matchup-level context an AI screenshot extraction would capture, for
    admins building the ladder by hand (CSV entry or manual toggling) instead.
    """
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_ui_error(interaction, error, "step 2 (matchup info)", self.state.lang)

    def __init__(self, state: LadderState):
        super().__init__()
        self.state = state
        lang = state.lang
        self.title = i18n.t('ladder.matchup_info_modal.title', lang)

        self.opp_name = TextInput(max_length=50, required=False)
        self.division = TextInput(max_length=10, required=False)
        self.rank = TextInput(max_length=4, required=False)

        self.add_item(discord.ui.Label(text=i18n.t('ladder.matchup_info_modal.label_opp', lang), component=self.opp_name))
        self.add_item(discord.ui.Label(text=i18n.t('ladder.matchup_info_modal.label_division', lang), component=self.division))
        self.add_item(discord.ui.Label(text=i18n.t('ladder.matchup_info_modal.label_rank', lang), component=self.rank))

        if state.opponent_league_name:
            self.opp_name.default = state.opponent_league_name
        if state.event_type:
            self.division.default = state.event_type
        if state.our_rank:
            self.rank.default = str(state.our_rank)

    async def on_submit(self, interaction: discord.Interaction):
        self.state.opponent_league_name = self.opp_name.value.strip() or None
        self.state.event_type = self.division.value.strip().upper() or None
        rank_val = self.rank.value.strip()
        self.state.our_rank = int(rank_val) if rank_val.isdigit() else None
        await interaction.response.defer()


class OpponentEntryView(View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None):
        await report_ui_error(interaction, error, "step 2 (opponent entry)", self.state.lang)

    def __init__(self, state: LadderState):
        super().__init__(timeout=300)
        self.state = state
        if not self.state.opponents:
            self.state.opponents = [
                {'name': '-', 'total_ovr': None, 'def_ovr': None}
                for _ in range(MATCHUP_SIZE)
            ]
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        lang = self.state.lang
        filled = sum(1 for o in self.state.opponents if o['name'] != '-')

        edit = Button(
            label=i18n.t('ladder.step2.enter_btn', lang, filled=filled, total=MATCHUP_SIZE),
            style=discord.ButtonStyle.success if filled == MATCHUP_SIZE else discord.ButtonStyle.primary,
            row=0
        )
        edit.callback = self._enter
        self.add_item(edit)

        info_btn = Button(
            label=i18n.t('ladder.matchup_info_btn', lang),
            style=discord.ButtonStyle.success if self.state.opponent_league_name else discord.ButtonStyle.secondary,
            row=0
        )
        info_btn.callback = self._edit_matchup_info
        self.add_item(info_btn)

        done = Button(
            label=i18n.t('ladder.step2.done_btn', lang),
            style=discord.ButtonStyle.green if filled == MATCHUP_SIZE else discord.ButtonStyle.gray,
            disabled=(filled < MATCHUP_SIZE),
            row=1
        )
        done.callback = self._advance
        self.add_item(done)

    async def _edit_matchup_info(self, interaction: discord.Interaction):
        modal = LadderMatchupInfoModal(self.state)

        async def on_submit(inter):
            await LadderMatchupInfoModal.on_submit(modal, inter)
            self._rebuild()
            await inter.message.edit(embed=self._build_embed(), view=self)

        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    async def _enter(self, interaction: discord.Interaction):
        lang = self.state.lang
        modal = OpponentCSVModal(lang=lang)
        entered = [o for o in self.state.opponents if o['name'] != '-']

        if not entered:
            # Nothing entered yet this session — pull whatever was last saved
            # to this team's ladder for this date (e.g. from an AI extraction
            # in an earlier /ladder run that got aborted), so it can be
            # reviewed and edited instead of starting from scratch.
            saved = await db.get_ladder_snapshot(self.state.team_id, self.state.game_date)
            entered = [
                {'name': r['opp_ign'], 'total_ovr': r.get('our_total_ovr'), 'def_ovr': r['opp_def_ovr']}
                for r in saved if r.get('opp_ign')
            ]

        existing = '\n'.join(
            f"{o['name']}, {o['total_ovr'] or ''}, {o['def_ovr'] or ''}"
            for o in entered
        )
        if existing:
            modal.opponents.default = existing

        async def on_submit(inter):
            await OpponentCSVModal.on_submit(modal, inter)
            parsed = _parse_csv_opponents(modal.opponents.value)
            for i, opp in enumerate(parsed[:MATCHUP_SIZE]):
                self.state.opponents[i] = opp
            self._rebuild()
            await inter.message.edit(embed=self._build_embed(), view=self)

        modal.on_submit = on_submit
        await interaction.response.send_modal(modal)

    async def _advance(self, interaction: discord.Interaction):
        self.stop()
        picker = SortPickerView(self.state)
        embed  = discord.Embed(
            title=i18n.t('ladder.step3.title', self.state.lang),
            description=i18n.t('ladder.step3.desc', self.state.lang),
            color=discord.Color.purple()
        )
        # Answer Discord BEFORE touching the db. Discord fails the click if it
        # isn't acknowledged within 3 seconds, and the save used to come first
        # — on a slow disk (or if it raised) the button just "failed" with
        # nothing in the channel to say why.
        await interaction.response.edit_message(embed=embed, view=picker)
        # Save now, the same way the final "Confirm Matchups" step does — this
        # is the point the opponent list is confirmed. If the flow gets aborted
        # after this, re-running /ladder will pick it back up via _enter above.
        # Finishing the ladder later just overwrites these same rows.
        identity = list(range(MATCHUP_SIZE))
        await _save_or_report(interaction, self.state, identity, identity)

    def _build_embed(self) -> discord.Embed:
        lang   = self.state.lang
        league = LEAGUE_NAMES.get(self.state.team_id, self.state.team_id)
        filled = sum(1 for o in self.state.opponents if o['name'] != '-')
        embed  = discord.Embed(
            title=i18n.t('ladder.step2.title', lang, filled=filled, total=MATCHUP_SIZE),
            description=i18n.t('ladder.step2.desc', lang, league=league),
            color=discord.Color.orange()
        )
        if self.state.opponent_league_name:
            division = i18n.t('ladder.final.context_division', lang, division=self.state.event_type) if self.state.event_type else ""
            rank     = i18n.t('ladder.final.context_rank', lang, rank=self.state.our_rank) if self.state.our_rank else ""
            embed.add_field(
                name=i18n.t('ladder.final.field_context', lang),
                value=i18n.t('ladder.final.context_value', lang, opp=self.state.opponent_league_name,
                             division=division, rank=rank),
                inline=False
            )
        lines_1 = []
        lines_2 = []
        for i, o in enumerate(self.state.opponents):
            icon  = "✅" if o['name'] != '-' else "⬜"
            ovr   = f"  DEF:{o['def_ovr']}" if o['def_ovr'] else ""
            # Opponent names arrive from a free-text modal (1600 chars for
            # the whole CSV), so one of them can overrun the 1024-character
            # field limit unaided and take the whole message down with it.
            entry = f"{icon} `#{i+1}` {truncate_cell(o['name'], _NAME_COL)}{ovr}"
            if i < 8:
                lines_1.append(entry)
            else:
                lines_2.append(entry)
        for i, chunk in enumerate(chunk_lines_to_fit(lines_1, max_chunks=2)):
            embed.add_field(
                name=i18n.t('ladder.step2.slots1_8', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
                value=chunk, inline=True)
        for i, chunk in enumerate(chunk_lines_to_fit(lines_2, max_chunks=2)):
            embed.add_field(
                name=i18n.t('ladder.step2.slots9_16', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
                value=chunk, inline=True)
        return embed


# ---------------------------------------------------------------------------
# Step 3 — Sort criteria picker
# ---------------------------------------------------------------------------

class SortPickerView(View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None):
        await report_ui_error(interaction, error, "step 3 (sort picker)", self.state.lang)

    def __init__(self, state: LadderState):
        super().__init__(timeout=60)
        self.state = state
        options = [
            discord.SelectOption(label=label, value=col)
            for label, col in _sort_options(state.lang)
        ]
        sel = Select(
            placeholder=i18n.t('ladder.step3.placeholder', state.lang),
            options=options
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        col = interaction.data['values'][0]
        self.stop()
        view = ReorderView(self.state, our_sort_col=col)
        await interaction.response.edit_message(embed=view._build_embed(), view=view)


# ---------------------------------------------------------------------------
# Step 4 — Reorder
# ---------------------------------------------------------------------------

class ReorderView(View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None):
        await report_ui_error(interaction, error, "step 4 (reorder)", self.state.lang)

    def __init__(self, state: LadderState, our_sort_col: str = 'pwr_rank'):
        super().__init__(timeout=300)
        self.state      = state
        self.panel      = 'ours'
        self.our_cursor = 0
        self.opp_cursor = 0

        player_map = {p['ign']: p for p in state.players}
        def our_key(i):
            p   = player_map.get(state.selected[i], {})
            val = p.get(our_sort_col)
            if val is None:
                # Fall back to pwr_rank so NULLs sort by rank rather than to the bottom
                val = p.get('pwr_rank') or 0
            return val
        self.our_order = sorted(range(MATCHUP_SIZE), key=our_key, reverse=True)

        def opp_key(i):
            return state.opponents[i].get('def_ovr') or 0
        self.opp_order = sorted(range(MATCHUP_SIZE), key=opp_key, reverse=True)

        self._rebuild()

    @property
    def _cursor(self):
        return self.our_cursor if self.panel == 'ours' else self.opp_cursor

    @_cursor.setter
    def _cursor(self, val):
        if self.panel == 'ours':
            self.our_cursor = val
        else:
            self.opp_cursor = val

    def _active_list(self):
        return self.our_order if self.panel == 'ours' else self.opp_order

    def _set_active_list(self, lst):
        if self.panel == 'ours':
            self.our_order = lst
        else:
            self.opp_order = lst

    def _rebuild(self):
        self.clear_items()
        lang = self.state.lang

        panel_label = i18n.t('ladder.step4.panel_ours', lang) if self.panel == 'ours' else i18n.t('ladder.step4.panel_opps', lang)
        toggle = Button(
            label=i18n.t('ladder.step4.toggle_btn', lang, panel=panel_label),
            style=discord.ButtonStyle.blurple, row=0
        )
        toggle.callback = self._toggle_panel
        self.add_item(toggle)

        up_cursor = Button(label=i18n.t('ladder.step4.cursor_up', lang),   style=discord.ButtonStyle.secondary, row=1)
        up_cursor.callback = self._cursor_up
        self.add_item(up_cursor)

        dn_cursor = Button(label=i18n.t('ladder.step4.cursor_down', lang), style=discord.ButtonStyle.secondary, row=1)
        dn_cursor.callback = self._cursor_down
        self.add_item(dn_cursor)

        move_up = Button(label=i18n.t('ladder.step4.move_up', lang),   style=discord.ButtonStyle.primary, row=1)
        move_up.callback = self._move_up
        self.add_item(move_up)

        move_dn = Button(label=i18n.t('ladder.step4.move_down', lang), style=discord.ButtonStyle.primary, row=1)
        move_dn.callback = self._move_down
        self.add_item(move_dn)

        sort_opts = _sort_options(lang)
        for label, col in sort_opts[:3]:
            btn = Button(
                label=i18n.t('ladder.step4.sort_btn', lang, label=label),
                style=discord.ButtonStyle.gray if self.panel == 'ours' else discord.ButtonStyle.secondary,
                disabled=(self.panel != 'ours'),
                row=2
            )
            btn.callback = self._make_our_sort(col)
            self.add_item(btn)

        for label, col in sort_opts[3:]:
            btn = Button(
                label=i18n.t('ladder.step4.sort_btn', lang, label=label),
                style=discord.ButtonStyle.gray if self.panel == 'ours' else discord.ButtonStyle.secondary,
                disabled=(self.panel != 'ours'),
                row=3
            )
            btn.callback = self._make_our_sort(col)
            self.add_item(btn)

        confirm = Button(label=i18n.t('ladder.step4.confirm_btn', lang), style=discord.ButtonStyle.success, row=4)
        confirm.callback = self._confirm
        self.add_item(confirm)

    def _make_our_sort(self, col: str):
        async def callback(interaction: discord.Interaction):
            if self.panel != 'ours':
                await interaction.response.defer()
                return
            player_map = {p['ign']: p for p in self.state.players}
            def key(i):
                return player_map.get(self.state.selected[i], {}).get(col) or 0
            self.our_order = sorted(range(MATCHUP_SIZE), key=key, reverse=True)
            self.our_cursor = 0
            self._rebuild()
            await interaction.response.edit_message(embed=self._build_embed(), view=self)
        return callback

    async def _toggle_panel(self, interaction: discord.Interaction):
        self.panel = 'opps' if self.panel == 'ours' else 'ours'
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _cursor_up(self, interaction: discord.Interaction):
        self._cursor = max(0, self._cursor - 1)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _cursor_down(self, interaction: discord.Interaction):
        self._cursor = min(MATCHUP_SIZE - 1, self._cursor + 1)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _move_up(self, interaction: discord.Interaction):
        lst = self._active_list()
        i   = self._cursor
        if i > 0:
            lst[i], lst[i-1] = lst[i-1], lst[i]
            self._cursor = i - 1
            self._set_active_list(lst)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _move_down(self, interaction: discord.Interaction):
        lst = self._active_list()
        i   = self._cursor
        if i < MATCHUP_SIZE - 1:
            lst[i], lst[i+1] = lst[i+1], lst[i]
            self._cursor = i + 1
            self._set_active_list(lst)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _confirm(self, interaction: discord.Interaction):
        self.stop()
        embed = build_final_embed(self.state, self.our_order, self.opp_order)
        # Acknowledge first, save second — see OpponentEntryView._advance.
        await interaction.response.edit_message(
            content=i18n.t('ladder.step4.finalized_content', self.state.lang), embed=None, view=None
        )
        if not await _save_or_report(interaction, self.state, self.our_order, self.opp_order):
            return
        channel = interaction.channel or self.state.channel
        await channel.send(embed=embed)

    def _build_embed(self) -> discord.Embed:
        lang   = self.state.lang
        league = LEAGUE_NAMES.get(self.state.team_id, self.state.team_id)
        panel  = i18n.t('ladder.step4.panel_ours', lang) if self.panel == 'ours' else i18n.t('ladder.step4.panel_opps', lang)
        embed  = discord.Embed(
            title=i18n.t('ladder.step4.title', lang),
            description=i18n.t('ladder.step4.desc', lang, league=league, panel=panel, row=self._cursor + 1),
            color=discord.Color.purple()
        )

        # Same 1024-per-field limit that broke build_final_embed below, and
        # the same cause if it ever fires here: these join one line per slot
        # with no budget. Names are clamped so a single long one can't
        # overrun the field on its own, and the join is chunked so sixteen
        # ordinary ones can't either.
        our_lines = []
        for rank, idx in enumerate(self.our_order):
            ign    = self.state.selected[idx]
            p      = next((x for x in self.state.players if x['ign'] == ign), {})
            pwr    = f"{p['pwr_rank']:.1f}" if p.get('pwr_rank') else '-'
            marker = "**>**" if self.panel == 'ours' and rank == self.our_cursor else "   "
            our_lines.append(f"{marker} `{rank+1:02d}` {truncate_cell(ign, _NAME_COL)} *({pwr})*")

        opp_lines = []
        for rank, idx in enumerate(self.opp_order):
            opp    = self.state.opponents[idx]
            def_s  = str(opp['def_ovr']) if opp['def_ovr'] else '-'
            marker = "**>**" if self.panel == 'opps' and rank == self.opp_cursor else "   "
            opp_lines.append(
                f"{marker} `{rank+1:02d}` {truncate_cell(opp['name'], _NAME_COL)} *(DEF {def_s})*")

        for i, chunk in enumerate(chunk_lines_to_fit(our_lines, max_chunks=2)):
            embed.add_field(
                name=i18n.t('ladder.step4.field_our', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
                value=chunk, inline=True)
        for i, chunk in enumerate(chunk_lines_to_fit(opp_lines, max_chunks=2)):
            embed.add_field(
                name=i18n.t('ladder.step4.field_opp', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
                value=chunk, inline=True)
        return embed


# ---------------------------------------------------------------------------
# Final embed + DB save
# ---------------------------------------------------------------------------

def build_final_embed(state: LadderState,
                      our_order: list[int],
                      opp_order: list[int]) -> discord.Embed:
    lang   = state.lang
    league = LEAGUE_NAMES.get(state.team_id, state.team_id)
    embed  = discord.Embed(
        title=i18n.t('ladder.final.title', lang, league=league, date=state.game_date),
        color=discord.Color.gold()
    )

    # Confirmation of what was extracted from the screenshot (or set some
    # other way), shown before the admin commits to saving — only meaningful
    # once there's an opponent league name to attach the rest to.
    if state.opponent_league_name:
        division = i18n.t('ladder.final.context_division', lang, division=state.event_type) if state.event_type else ""
        rank     = i18n.t('ladder.final.context_rank', lang, rank=state.our_rank) if state.our_rank else ""
        embed.add_field(
            name=i18n.t('ladder.final.field_context', lang),
            value=i18n.t('ladder.final.context_value', lang, opp=state.opponent_league_name,
                         division=division, rank=rank),
            inline=False
        )

    col_player   = i18n.t('ladder.final.col_player', lang)
    col_opponent = i18n.t('ladder.final.col_opponent', lang)
    rows = [
        f"{'#':>2}  {truncate_cell(col_player, _NAME_COL):<{_NAME_COL}}  vs  "
        f"{truncate_cell(col_opponent, _NAME_COL):<{_NAME_COL}}  {'TOT':>5}  {'DEF':>5}",
        "-" * 62
    ]
    for slot in range(MATCHUP_SIZE):
        our_idx = our_order[slot]
        opp_idx = opp_order[slot]
        player  = truncate_cell(state.selected[our_idx], _NAME_COL)
        opp     = state.opponents[opp_idx]
        name    = truncate_cell(opp['name'], _NAME_COL)
        tot_str = str(opp['total_ovr']) if opp['total_ovr'] else '-'
        def_str = str(opp['def_ovr'])   if opp['def_ovr']   else '-'
        rows.append(
            f"{slot+1:>2}  {player:<{_NAME_COL}}  vs  {name:<{_NAME_COL}}  {tot_str:>5}  {def_str:>5}"
        )

    # This used to chunk at 1985 characters, which is a *description* budget,
    # not a field one — and then wrap each chunk in a code fence on top. An
    # embed field's value is capped at 1024, and Discord rejects the whole
    # message with a 400 if any field exceeds it. A full 16-slot ladder is
    # 18 lines of 60-62 characters, i.e. ~1100 before the fence, so this
    # never fit: /ladder's final step failed every single time it was run to
    # completion. Caught from a real traceback once discord.py's logging was
    # actually configured (see logger_config).
    for i, chunk in enumerate(chunk_lines_to_fit(rows, max_chars=_TABLE_BUDGET, max_chunks=4)):
        embed.add_field(
            name=i18n.t('ladder.final.field_matchups', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
            value=f"```\n{chunk}\n```",
            inline=False
        )
    return embed


async def save_ladder_to_db(state: LadderState,
                             our_order: list[int],
                             opp_order: list[int]):
    slots = []
    for slot in range(MATCHUP_SIZE):
        opp = state.opponents[opp_order[slot]]
        slots.append({
            'slot':          slot + 1,
            'opp_ign':       opp['name'],
            'opp_def_ovr':   opp.get('def_ovr'),
            'our_total_ovr': opp.get('total_ovr'),
            'our_ign':       state.selected[our_order[slot]],
        })
    await db.upsert_ladder_slots(state.team_id, state.game_date, slots)

    # Matchup-level context from screenshot extraction, if any of it was
    # actually visible/readable — set_matchup_info preserves whatever's
    # already there for any field left None, so this is safe to call even
    # when nothing at all was extracted (e.g. the manual CSV entry flow).
    # Uses set_matchup_info specifically, not set_matchup — the slot data
    # above was just written directly, so there's no need for (and a real
    # risk of conflicting with) set_matchup's separate ladder-snapshot step.
    if state.opponent_league_name or state.event_type or state.our_rank:
        await db.set_matchup_info(
            state.team_id, state.game_date,
            opp_ign=state.opponent_league_name,
            event_type=state.event_type,
            our_rank=state.our_rank,
        )


async def _save_or_report(interaction: discord.Interaction, state: LadderState,
                          our_order: list[int], opp_order: list[int]) -> bool:
    """
    save_ladder_to_db for a button handler that has already answered the
    interaction. A failure is logged with its traceback and reported to the
    clicker via followup, rather than escaping into discord.py's handler where
    nobody in the channel would ever see it. Returns whether the save worked.
    """
    try:
        await save_ladder_to_db(state, our_order, opp_order)
        return True
    except Exception as e:
        logger.exception(f"Ladder save failed for {state.team_id} on {state.game_date}: {e}")
        try:
            await interaction.followup.send(
                i18n.t('ladder.save_failed', state.lang, error=f"{type(e).__name__}: {e}"),
                ephemeral=True
            )
        except Exception:
            logger.exception("Could not report ladder save failure to the user")
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def start_ladder_flow(interaction: discord.Interaction,
                             team_id: str, game_date, bot=None,
                             preselected: list[str] | None = None,
                             preopponents: list[dict] | None = None,
                             opponent_league_name: str | None = None,
                             event_type: str | None = None,
                             our_rank: int | None = None):
    """
    Start the ladder builder flow.
    preselected:  list of IGNs to pre-select (from agent screenshot extraction)
    preopponents: list of {name, total_ovr, def_ovr} to pre-fill opponents
    opponent_league_name/event_type/our_rank: matchup-level context from the
        same screenshot extraction, if it was visible and readable.
    """
    lang    = i18n.resolve_lang(interaction)
    players = await db.get_team_stats(team_id)

    if not players:
        msg = i18n.t('ladder.no_active_players', lang, team=team_id)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return

    state         = LadderState(team_id, game_date, interaction.channel, lang=lang)
    state.players = [dict(p) for p in players]
    state.opponent_league_name = opponent_league_name
    state.event_type           = event_type
    state.our_rank              = our_rank

    # Pre-populate from agent if provided. Sanitized into a NEW list rather
    # than assigned: the caller's list is still held (and still appended to)
    # by the OVR-sanity and manual-match views as their batches resolve, so
    # sharing the object let a stale click on one of those earlier messages
    # mutate a live ladder's selection.
    if preselected:
        state.selected, dropped = sanitize_selection(list(preselected), state.players)
        if dropped:
            logger.warning(
                f"/ladder pre-selection for {team_id} dropped {len(dropped)} "
                f"name(s) not usable as a selection: {dropped}"
            )
    else:
        state.selected = [p['ign'] for p in state.players[:MATCHUP_SIZE]]

    if preopponents:
        state.opponents = preopponents

    view = PlayerToggleView(state)
    if interaction.response.is_done():
        await interaction.followup.send(embed=view._build_embed(), view=view)
    else:
        await interaction.response.send_message(embed=view._build_embed(), view=view)