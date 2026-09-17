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

MATCHUP_SIZE     = 16  # how many of a league's active/rostered players actually play a given ladder — see this file's header docstring for the playing-vs-active distinction
PLAYERS_PER_PAGE = 20
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


LEAGUE_NAMES = {
    'NP': 'NeuroPerverse', 'ND': 'NeuroDiverse', 'NI': 'NeuroInverse',
    'NA': 'NeuroAdverse',  'NR': 'NeuroReverse',  'NC': 'NeuroChaos',
    'NT': 'NeuroTraverse', 'NX': 'NeuroChristians',
}


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


# ---------------------------------------------------------------------------
# Step 1 — Player toggle: choosing who plays this ladder (vs. rests) from
# the league's full active/rostered pool
# ---------------------------------------------------------------------------

class PlayerToggleView(View):
    def __init__(self, state: LadderState):
        super().__init__(timeout=300)
        self.state = state
        self.page  = 0
        if not self.state.selected:
            self.state.selected = [p['ign'] for p in state.players[:MATCHUP_SIZE]]
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
        self.stop()
        all_igns = [p['ign'] for p in self.state.players]
        for ign in all_igns:
            new_status = 'A'  # all roster players stay Active; ladder stores selection separately
            await db.execute(
                "UPDATE players SET status=? WHERE ign=? AND team_id=?",
                (new_status, ign, self.state.team_id)
            )
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
            embed.add_field(
                name=i18n.t('ladder.step1.selected_label', lang),
                value=", ".join(f"`{p}`" for p in self.state.selected),
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
    def __init__(self, lang: str = 'en'):
        super().__init__()
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
        # Save now, the same way the final "Confirm Matchups" step does — this
        # is the point the opponent list is confirmed. If the flow gets aborted
        # after this, re-running /ladder will pick it back up via _enter above.
        # Finishing the ladder later just overwrites these same rows.
        identity = list(range(MATCHUP_SIZE))
        await save_ladder_to_db(self.state, identity, identity)
        picker = SortPickerView(self.state)
        embed  = discord.Embed(
            title=i18n.t('ladder.step3.title', self.state.lang),
            description=i18n.t('ladder.step3.desc', self.state.lang),
            color=discord.Color.purple()
        )
        await interaction.response.edit_message(embed=embed, view=picker)

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
            entry = f"{icon} `#{i+1}` {o['name']}{ovr}"
            if i < 8:
                lines_1.append(entry)
            else:
                lines_2.append(entry)
        embed.add_field(name=i18n.t('ladder.step2.slots1_8', lang),  value="\n".join(lines_1), inline=True)
        embed.add_field(name=i18n.t('ladder.step2.slots9_16', lang), value="\n".join(lines_2), inline=True)
        return embed


# ---------------------------------------------------------------------------
# Step 3 — Sort criteria picker
# ---------------------------------------------------------------------------

class SortPickerView(View):
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
        await save_ladder_to_db(self.state, self.our_order, self.opp_order)
        await interaction.response.edit_message(
            content=i18n.t('ladder.step4.finalized_content', self.state.lang), embed=None, view=None
        )
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

        our_lines = []
        for rank, idx in enumerate(self.our_order):
            ign    = self.state.selected[idx]
            p      = next((x for x in self.state.players if x['ign'] == ign), {})
            pwr    = f"{p['pwr_rank']:.1f}" if p.get('pwr_rank') else '-'
            marker = "**>**" if self.panel == 'ours' and rank == self.our_cursor else "   "
            our_lines.append(f"{marker} `{rank+1:02d}` {ign} *({pwr})*")

        opp_lines = []
        for rank, idx in enumerate(self.opp_order):
            opp    = self.state.opponents[idx]
            def_s  = str(opp['def_ovr']) if opp['def_ovr'] else '-'
            marker = "**>**" if self.panel == 'opps' and rank == self.opp_cursor else "   "
            opp_lines.append(f"{marker} `{rank+1:02d}` {opp['name']} *(DEF {def_s})*")

        embed.add_field(name=i18n.t('ladder.step4.field_our', lang), value="\n".join(our_lines), inline=True)
        embed.add_field(name=i18n.t('ladder.step4.field_opp', lang), value="\n".join(opp_lines), inline=True)
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
        f"{'#':>2}  {col_player:<18}  vs  {col_opponent:<18}  {'TOT':>5}  {'DEF':>5}",
        "-" * 62
    ]
    for slot in range(MATCHUP_SIZE):
        our_idx = our_order[slot]
        opp_idx = opp_order[slot]
        player  = state.selected[our_idx]
        opp     = state.opponents[opp_idx]
        tot_str = str(opp['total_ovr']) if opp['total_ovr'] else '-'
        def_str = str(opp['def_ovr'])   if opp['def_ovr']   else '-'
        rows.append(
            f"{slot+1:>2}  {player:<18}  vs  {opp['name']:<18}  {tot_str:>5}  {def_str:>5}"
        )

    chunks, current, cur_len = [], [], 0
    for row in rows:
        if cur_len + len(row) + 1 > 1985:
            chunks.append("\n".join(current))
            current, cur_len = [row], len(row)
        else:
            current.append(row)
            cur_len += len(row) + 1
    if current:
        chunks.append("\n".join(current))

    for i, chunk in enumerate(chunks):
        embed.add_field(
            name=i18n.t('ladder.final.field_matchups', lang) if i == 0 else i18n.t('ladder.final.field_matchups_cont', lang),
            value=f"```\n{chunk}\n```",
            inline=False
        )
    return embed


async def save_ladder_to_db(state: LadderState,
                             our_order: list[int],
                             opp_order: list[int]):
    for slot in range(MATCHUP_SIZE):
        our_ign = state.selected[our_order[slot]]
        opp     = state.opponents[opp_order[slot]]
        await db.upsert_ladder_slot(
            state.team_id, state.game_date, slot + 1,
            opp_ign=opp['name'],
            opp_def_ovr=opp['def_ovr'],
            our_total_ovr=opp['total_ovr'],
            our_ign=our_ign,
        )

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

    # Pre-populate from agent if provided
    if preselected:
        state.selected = preselected
    else:
        state.selected = [p['ign'] for p in state.players[:MATCHUP_SIZE]]

    if preopponents:
        state.opponents = preopponents

    view = PlayerToggleView(state)
    if interaction.response.is_done():
        await interaction.followup.send(embed=view._build_embed(), view=view)
    else:
        await interaction.response.send_message(embed=view._build_embed(), view=view)