"""
siege.py — Siege gamemode: matches, nodes (opposing players w/ mods), and scores.

A siege match pits 16 of our league's players (selected to play this specific
match, out of up to 18 active/rostered league members — "playing" and
"active/rostered" are distinct concepts here: /openspots' 18-cap is about
league membership, this 16 is about who's actually playing this match) against
an opposing league. Up to 10 opposing players carry a "mod"; the rest carry
"No Mod". Each opposing
player is a "node" — hidden in-game until someone reports it visible via
/node, at which point it becomes "open" and stays open until our league's
cumulative points against it meet or exceed its points_required, at which
point it flips to "cleared".

Commands (thin wrappers live in optimized_bot.py, calling into this module):
  /siege        (admin) — modal to start a new active match for a league
  /node                 — modal to report a newly-visible opponent/node
  /siegescore           — modal to log drives/points against an open node
  /siegestatus          — embed: open/cleared nodes, player totals, league score
  /updatesiege  (admin) — set opponent's total points + correct any node/score entry
  /siegefinal   (admin) — same corrections as /updatesiege, then closes the match
  /siegesplits          — a player's per-mod split across all siege matches
  /siegehistory         — a league's past completed siege matches
"""

import discord
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput
import db
import i18n

# Loaded from the db's teams table at import (see db.load_league_names_sync)
# rather than imported from optimized_bot, which would be a circular import.
# Both modules read the same source of truth, so they can't drift.
LEAGUE_NAMES = db.load_league_names_sync()

SIEGE_MODS = db.SIEGE_MODS


def _league_name(team_id: str) -> str:
    return LEAGUE_NAMES.get(team_id, team_id)


# ============================================================================
# /siege — start a new match
# ============================================================================

class SiegeStartModal(Modal, title="Start Siege Match"):
    def __init__(self, team_id: str, lang: str = 'en'):
        super().__init__()
        self.team_id = team_id
        self.lang    = lang
        self.title = i18n.t('siege.start.modal_title', lang)

        self.opp_league = TextInput(placeholder="e.g. WolfpackMafia", max_length=50)
        self.opp_rank = TextInput(required=False, max_length=20)
        self.our_rank = TextInput(required=False, max_length=20)
        self.division = TextInput(required=False, max_length=20)

        self.add_item(discord.ui.Label(text=i18n.t('siege.start.label_opp_league', lang), component=self.opp_league))
        self.add_item(discord.ui.Label(text=i18n.t('siege.start.label_opp_rank', lang), component=self.opp_rank))
        self.add_item(discord.ui.Label(text=i18n.t('siege.start.label_our_rank', lang), component=self.our_rank))
        self.add_item(discord.ui.Label(text=i18n.t('siege.start.label_division', lang), component=self.division))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            match = await db.start_siege_match(
                self.team_id,
                self.opp_league.value.strip(),
                opp_rank=self.opp_rank.value.strip() or None,
                our_rank=self.our_rank.value.strip() or None,
                division=self.division.value.strip() or None,
            )
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        league = _league_name(self.team_id)
        await interaction.response.send_message(
            i18n.t('siege.start.success', lang, league=league, opp_league=match['opp_league'])
        )


async def handle_siege(interaction: discord.Interaction, team_id: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.send_modal(SiegeStartModal(team_id, lang=lang))


# ============================================================================
# /node — report a newly-visible node
# ============================================================================

class NodeModal(Modal, title="Report Siege Node"):
    def __init__(self, match_id: int, mod: str, lang: str = 'en'):
        super().__init__()
        self.match_id = match_id
        self.mod      = mod
        self.lang     = lang
        self.title = i18n.t('siege.node.modal_title', lang)

        self.opponent_name = TextInput(placeholder="e.g. BigBoy87", max_length=50)
        self.opponent_ovr = TextInput(required=False, max_length=5)
        self.points_required = TextInput(placeholder="e.g. 30", max_length=5)
        self.points_reward = TextInput(placeholder="e.g. 10", max_length=5)

        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_opponent_name', lang), component=self.opponent_name))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_opponent_ovr', lang), component=self.opponent_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_points_required', lang), component=self.points_required))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_points_reward', lang), component=self.points_reward))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        name = self.opponent_name.value.strip()
        if not name:
            await interaction.response.send_message(i18n.t('siege.node.err_blank_name', lang), ephemeral=True)
            return
        try:
            ovr_val = int(self.opponent_ovr.value.strip()) if self.opponent_ovr.value.strip() else None
            req_val = int(self.points_required.value.strip())
            rew_val = int(self.points_reward.value.strip())
        except ValueError:
            await interaction.response.send_message(
                i18n.t('siege.node.err_invalid_numbers', lang), ephemeral=True
            )
            return

        try:
            node = await db.add_siege_node(self.match_id, self.mod, name, ovr_val, req_val, rew_val)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        ovr_str = i18n.t('siege.node.ovr_suffix', lang, ovr=ovr_val) if ovr_val else ""
        await interaction.response.send_message(
            i18n.t('siege.node.success', lang, name=node['opponent_name'], ovr=ovr_str, mod=self.mod,
                   req=req_val, reward=rew_val)
        )


async def handle_node(interaction: discord.Interaction, team_id: str, mod: str):
    lang = i18n.resolve_lang(interaction)
    match = await db.get_active_siege_match(team_id)
    if match is None:
        await interaction.response.send_message(
            i18n.t('siege.no_active_match', lang, league=_league_name(team_id)),
            ephemeral=True
        )
        return
    await interaction.response.send_modal(NodeModal(match['id'], mod, lang=lang))


# ============================================================================
# /siegescore — log drives/points against an open node
# ============================================================================

class SiegeScoreModal(Modal, title="Log Siege Score"):
    def __init__(self, node_id: int, opponent_name: str, player_ign: str, lang: str = 'en'):
        super().__init__()
        self.node_id       = node_id
        self.opponent_name = opponent_name
        self.player_ign    = player_ign
        self.lang          = lang
        self.title = i18n.t('siege.score.modal_title', lang)

        self.drives = TextInput(placeholder="e.g. 10", max_length=3)
        self.points = TextInput(placeholder="e.g. 42", max_length=4)

        self.add_item(discord.ui.Label(text=i18n.t('siege.score.label_drives', lang), component=self.drives))
        self.add_item(discord.ui.Label(text=i18n.t('siege.score.label_points', lang), component=self.points))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            drives_val = int(self.drives.value.strip())
            points_val = int(self.points.value.strip())
        except ValueError:
            await interaction.response.send_message(i18n.t('siege.score.err_invalid', lang), ephemeral=True)
            return

        try:
            result = await db.log_siege_score(self.node_id, self.player_ign, drives_val, points_val)
        except ValueError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        cleared_str = i18n.t('siege.score.cleared_suffix', lang) if result['cleared'] else ""
        await interaction.response.send_message(
            i18n.t('siege.score.success', lang, player=self.player_ign, points=points_val,
                   drives=drives_val, opponent=self.opponent_name, cleared=cleared_str)
        )


async def siege_opponent_autocomplete(interaction: discord.Interaction, current: str):
    """
    Autocomplete for /siegescore's 'opponent' field — every open node in the
    league's active match, regardless of mod (no separate mod filter needed:
    named mods are unique per match, so the only real collision risk is among
    the up-to-6 "No Mod" nodes, and those need to show up here too).

    The underlying value is the node's id, not its name — invisible to the
    user (they just see and click the label), but it's what makes each of the
    up-to-6 same-mod "No Mod" nodes individually selectable even if two of
    them happen to share an opponent name.
    """
    league = getattr(interaction.namespace, 'league', None)
    if not league:
        return []
    team_id = league.upper()
    match = await db.get_active_siege_match(team_id)
    if match is None:
        return []
    nodes = await db.get_siege_nodes(match['id'], status='open')
    current_lower = current.lower()
    results = []
    for n in nodes:
        if current_lower and current_lower not in n['opponent_name'].lower():
            continue
        ovr_str = f", OVR {n['opponent_ovr']}" if n['opponent_ovr'] else ""
        label = f"{n['opponent_name']} — {n['mod']}{ovr_str}"
        results.append(app_commands.Choice(name=label[:100], value=str(n['id'])))
    return results[:25]


async def handle_siegescore(interaction: discord.Interaction, team_id: str, player: str, opponent: str):
    lang = i18n.resolve_lang(interaction)
    match = await db.get_active_siege_match(team_id)
    if match is None:
        await interaction.response.send_message(
            i18n.t('siege.no_active_match_short', lang, league=_league_name(team_id)), ephemeral=True
        )
        return

    node = None

    # Normal path: opponent came from the autocomplete list, so it's a node id.
    try:
        candidate_id = int(opponent)
    except ValueError:
        candidate_id = None
    if candidate_id is not None:
        candidate = await db.get_siege_node(candidate_id)
        if candidate and candidate['match_id'] == match['id'] and candidate['status'] == 'open':
            node = candidate

    # Fallback: admin typed a name by hand instead of picking a suggestion.
    # Only safe to resolve automatically if it's unambiguous.
    if node is None:
        matches = await db.get_siege_open_nodes_by_name(match['id'], opponent)
        if len(matches) == 1:
            node = matches[0]
        elif len(matches) > 1:
            await interaction.response.send_message(
                i18n.t('siege.score.ambiguous_name', lang, count=len(matches), name=opponent),
                ephemeral=True
            )
            return

    if node is None:
        await interaction.response.send_message(
            i18n.t('siege.score.no_node_found', lang, name=opponent), ephemeral=True
        )
        return

    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    await interaction.response.send_modal(SiegeScoreModal(node['id'], node['opponent_name'], player, lang=lang))


# ============================================================================
# /siegestatus — status embed (also reused by /updatesiege and /siegefinal)
# ============================================================================

# A siege match pits 16 of our league's players (playing this match, not
# necessarily every active/rostered league member — see this file's header
# docstring) against 16 opposing players, one node per opponent — so there
# is a hard, real ceiling of 16 open nodes at once, never more. This makes
# the generic _chunk_lines_to_fit default of 5 chunks (sized for a
# genuinely unbounded list, like player_totals below) needlessly generous
# for the open-nodes field specifically: even in the worst case (16 nodes,
# each with an unusually long opponent name), 2-3 chunks fully covers it.
# Capped at 3 rather than
# a smaller number to leave a little real margin, not because more is ever
# actually expected.
MAX_SIEGE_NODES = 16
_OPEN_NODES_MAX_CHUNKS = 3


def _chunk_lines_to_fit(lines: list[str], max_chars: int = 1024, max_chunks: int = 5) -> list[str]:
    """
    Splits a list of lines into chunks, each chunk's newline-joined string
    at most max_chars long. Discord enforces a hard 1024-character limit
    per embed field value — a field built by joining one line per item
    (e.g. one per open siege node) can silently exceed that once there are
    enough items, and Discord rejects the ENTIRE message with an
    HTTPException (not a partial/truncated send) if any field value goes
    over, so this has to be handled before ever calling embed.add_field,
    not caught after the fact.

    Caps at max_chunks (default 5) so this can't separately blow past
    Discord's 25-fields-per-embed limit on an extreme siege with dozens of
    open nodes — the last chunk gets a "...and N more" note (counting
    actual dropped lines, not dropped chunks) instead of producing a 6th,
    7th, etc. field.
    """
    if not lines:
        return []

    # Pass 1: chunk purely by character budget, no count cap yet. Track how
    # many source lines land in each chunk so a later cap can report an
    # accurate dropped-line count, not a less useful dropped-chunk count.
    chunks: list[str] = []
    chunk_line_counts: list[int] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        added_len = len(line) + (1 if current else 0)  # +1 for the joining newline
        if current and current_len + added_len > max_chars:
            chunks.append("\n".join(current))
            chunk_line_counts.append(len(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += added_len
    if current:
        chunks.append("\n".join(current))
        chunk_line_counts.append(len(current))

    # Pass 2: cap the chunk COUNT if it exceeds max_chunks.
    if len(chunks) > max_chunks:
        kept = chunks[:max_chunks]
        dropped_lines = sum(chunk_line_counts[max_chunks:])
        note = f"...and {dropped_lines} more"
        last = kept[-1]
        if len(last) + 1 + len(note) <= max_chars:
            kept[-1] = last + "\n" + note
        else:
            kept[-1] = note  # extreme edge case: the last chunk was already at the character limit
        chunks = kept

    return chunks


def build_status_embed(team_id: str, match: dict, summary: dict, player_totals: list[dict], lang: str = 'en') -> discord.Embed:
    league = _league_name(team_id)
    embed = discord.Embed(
        title=i18n.t('siege.status.title', lang, league=league, opp_league=match['opp_league']),
        color=discord.Color.dark_red()
    )

    if match.get('our_rank') or match.get('opp_rank') or match.get('division'):
        embed.add_field(
            name=i18n.t('siege.status.matchup_info_label', lang),
            value=i18n.t('siege.status.matchup_info_value', lang,
                        our_rank=match.get('our_rank') or '—',
                        opp_rank=match.get('opp_rank') or '—',
                        division=match.get('division') or '—'),
            inline=False
        )

    open_nodes = sorted(summary['open_nodes'], key=lambda n: n['points_reward'], reverse=True)
    open_lines = []
    for n in open_nodes:
        star   = "⭐ " if n['id'] in summary['top_open_ids'] else ""
        ovr_str = i18n.t('siege.node.ovr_suffix', lang, ovr=n['opponent_ovr']) if n['opponent_ovr'] else ""
        open_lines.append(
            i18n.t('siege.status.open_node_line', lang, star=star, name=n['opponent_name'], ovr=ovr_str,
                   mod=n['mod'], so_far=n['points_so_far'], required=n['points_required'], reward=n['points_reward'])
        )
    open_label = i18n.t('siege.status.open_nodes_label', lang, count=len(summary['open_nodes']))
    if open_lines:
        # Chunked across multiple fields if needed — a long-running siege
        # with many open nodes can easily build a single-field value past
        # Discord's 1024-char-per-field limit, which previously made the
        # ENTIRE /siegestatus (and /siegefinal, /updatesiege, which share
        # this same embed builder) call fail outright with an HTTPException
        # on every single use, not just this one field silently truncating.
        # max_chunks is deliberately smaller here than the generic default —
        # see MAX_SIEGE_NODES/_OPEN_NODES_MAX_CHUNKS above for why 3 is
        # already generous for a field that can never realistically hold
        # more than 16 lines.
        chunks = _chunk_lines_to_fit(open_lines, max_chunks=_OPEN_NODES_MAX_CHUNKS)
        for i, chunk in enumerate(chunks):
            field_name = open_label if i == 0 else f"{open_label} (cont.)"
            embed.add_field(name=field_name, value=chunk, inline=False)
    else:
        embed.add_field(name=open_label, value=i18n.t('siege.status.no_nodes_yet', lang), inline=False)

    embed.add_field(
        name=i18n.t('siege.status.cleared_nodes_label', lang, count=len(summary['cleared_nodes'])),
        value=i18n.t('siege.status.cleared_totals_value', lang,
                     req=summary['cleared_required_total'], reward=summary['cleared_reward_total'])
              if summary['cleared_nodes'] else i18n.t('siege.status.none_cleared', lang),
        inline=False
    )

    if player_totals:
        lines = [f"`{p['ign']}`: **{int(p['points'])}** pts / **{int(p['drives'])}** drives" for p in player_totals]
        half = len(lines) // 2 + len(lines) % 2
        left_chunks  = _chunk_lines_to_fit(lines[:half]) or ["—"]
        right_chunks = _chunk_lines_to_fit(lines[half:])
        totals_label = i18n.t('siege.status.player_totals_label', lang)
        for i, chunk in enumerate(left_chunks):
            embed.add_field(name=totals_label if i == 0 else f"{totals_label} (cont.)", value=chunk, inline=True)
        for chunk in right_chunks:
            embed.add_field(name="\u200b", value=chunk, inline=True)

    embed.add_field(
        name=i18n.t('siege.status.league_ppd_label', lang),
        value=i18n.t('siege.status.league_ppd_value', lang, ppd=summary['ppd'],
                     bonus=f"{summary['ppd_bonus']:+d}", score=summary['league_score']),
        inline=False
    )

    if match.get('opp_total_points') is not None:
        embed.add_field(name=i18n.t('siege.status.opp_total_points_label', lang), value=str(match['opp_total_points']), inline=False)

    return embed


async def handle_siegestatus(interaction: discord.Interaction, team_id: str):
    lang = i18n.resolve_lang(interaction)
    match = await db.get_active_siege_match(team_id)
    if match is None:
        await interaction.response.send_message(
            i18n.t('siege.no_active_match_short', lang, league=_league_name(team_id)), ephemeral=True
        )
        return

    await interaction.response.defer()
    summary       = await db.get_siege_match_summary(match['id'])
    player_totals = await db.get_siege_all_player_totals(match['id'])
    embed         = build_status_embed(team_id, match, summary, player_totals, lang=lang)
    await interaction.followup.send(embed=embed)


# ============================================================================
# /updatesiege and /siegefinal — admin corrections (+ finalize)
# ============================================================================

class OpponentPointsModal(Modal, title="Set Opponent Total Points"):
    def __init__(self, match_id: int, existing=None, lang: str = 'en'):
        super().__init__()
        self.match_id = match_id
        self.lang     = lang
        self.title = i18n.t('siege.correction.opp_points_modal_title', lang)

        self.opp_points = TextInput(placeholder="e.g. 4200")
        self.add_item(discord.ui.Label(text=i18n.t('siege.correction.opp_points_label', lang), component=self.opp_points))
        if existing is not None:
            self.opp_points.default = str(existing)

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            val = float(self.opp_points.value.strip())
        except ValueError:
            await interaction.response.send_message(i18n.t('siege.correction.opp_points_err', lang), ephemeral=True)
            return
        await db.update_siege_match(self.match_id, opp_total_points=val)
        await interaction.response.send_message(i18n.t('siege.correction.opp_points_success', lang, val=f"{val:g}"), ephemeral=True)


class NodeEditModal(Modal, title="Edit Node"):
    def __init__(self, node: dict, lang: str = 'en'):
        super().__init__()
        self.node_id = node['id']
        self.lang    = lang
        self.title = i18n.t('siege.correction.node_edit_title', lang)

        self.opponent_name = TextInput(max_length=50, default=node['opponent_name'])
        self.opponent_ovr = TextInput(required=False, max_length=5)
        self.points_required = TextInput(max_length=5, default=str(node['points_required']))
        self.points_reward = TextInput(max_length=5, default=str(node['points_reward']))

        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_opponent_name', lang), component=self.opponent_name))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_opponent_ovr', lang), component=self.opponent_ovr))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_points_required', lang), component=self.points_required))
        self.add_item(discord.ui.Label(text=i18n.t('siege.node.label_points_reward', lang), component=self.points_reward))
        if node['opponent_ovr'] is not None:
            self.opponent_ovr.default = str(node['opponent_ovr'])

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        name = self.opponent_name.value.strip()
        if not name:
            await interaction.response.send_message(i18n.t('siege.node.err_blank_name', lang), ephemeral=True)
            return
        try:
            ovr_val = int(self.opponent_ovr.value.strip()) if self.opponent_ovr.value.strip() else None
            req_val = int(self.points_required.value.strip())
            rew_val = int(self.points_reward.value.strip())
        except ValueError:
            await interaction.response.send_message(
                i18n.t('siege.node.err_invalid_numbers', lang), ephemeral=True
            )
            return

        await db.update_siege_node(
            self.node_id, opponent_name=name, opponent_ovr=ovr_val,
            points_required=req_val, points_reward=rew_val
        )
        # points_required may have changed — re-derive open/cleared accordingly.
        await db.recheck_siege_node_status(self.node_id)
        node = await db.get_siege_node(self.node_id)
        status_str = i18n.t(f"siege.status_{node['status']}", lang)
        await interaction.response.send_message(
            i18n.t('siege.correction.node_success', lang, name=name, status=status_str, req=req_val, reward=rew_val),
            ephemeral=True
        )


class ScoreEditModal(Modal, title="Edit Score Entry"):
    def __init__(self, score: dict, lang: str = 'en'):
        super().__init__()
        self.score_id = score['id']
        self.lang     = lang
        self.title = i18n.t('siege.correction.score_edit_title', lang)

        self.drives = TextInput(max_length=3, default=str(score['drives']))
        self.points = TextInput(max_length=4, default=str(score['points']))

        self.add_item(discord.ui.Label(text=i18n.t('siege.score.label_drives', lang), component=self.drives))
        self.add_item(discord.ui.Label(text=i18n.t('siege.score.label_points', lang), component=self.points))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            drives_val = int(self.drives.value.strip())
            points_val = int(self.points.value.strip())
        except ValueError:
            await interaction.response.send_message(i18n.t('siege.score.err_invalid', lang), ephemeral=True)
            return
        await db.update_siege_score(self.score_id, drives=drives_val, points=points_val)
        await interaction.response.send_message(
            i18n.t('siege.correction.score_success', lang, points=points_val, drives=drives_val), ephemeral=True
        )


class SiegeCorrectionView(View):
    """
    Shared by /updatesiege and /siegefinal — set the opponent's total points,
    and correct any node's info or any logged score entry in the active match.
    /siegefinal additionally shows a Finalize Match button.

    Node/score lists are capped at 25 entries (Discord's Select limit); score
    entries show the most recent 25, which covers realistic same-match fixes.
    """

    def __init__(self, match: dict, nodes: list[dict], scores: list[dict], allow_finalize: bool = False, lang: str = 'en'):
        super().__init__(timeout=300)
        self.match = match
        self.lang  = lang

        opp_pts_btn = Button(label=i18n.t('siege.correction.btn_set_opp_points', lang), style=discord.ButtonStyle.primary, row=0)
        opp_pts_btn.callback = self._set_opp_points
        self.add_item(opp_pts_btn)

        if nodes:
            node_select = Select(
                placeholder=i18n.t('siege.correction.select_node_placeholder', lang),
                options=[
                    discord.SelectOption(
                        label=f"{n['opponent_name']} ({n['mod']})"[:100],
                        value=str(n['id']),
                        description=(
                            f"{n['status']} · req {n['points_required']} / reward {n['points_reward']}"
                        )[:100]
                    )
                    for n in nodes[:25]
                ],
                row=1
            )
            node_select.callback = self._edit_node
            self.add_item(node_select)

        if scores:
            score_select = Select(
                placeholder=i18n.t('siege.correction.select_score_placeholder', lang),
                options=[
                    discord.SelectOption(
                        label=f"{s['ign']} vs {s['opponent_name']} — {s['points']}pt/{s['drives']}dr"[:100],
                        value=str(s['id']),
                        description=(s['mod'] or '')[:100]
                    )
                    for s in scores[:25]
                ],
                row=2
            )
            score_select.callback = self._edit_score
            self.add_item(score_select)

        if allow_finalize:
            finalize_btn = Button(label=i18n.t('siege.correction.btn_finalize', lang), style=discord.ButtonStyle.danger, row=3)
            finalize_btn.callback = self._finalize
            self.add_item(finalize_btn)

    async def _set_opp_points(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            OpponentPointsModal(self.match['id'], self.match.get('opp_total_points'), lang=self.lang)
        )

    async def _edit_node(self, interaction: discord.Interaction):
        node_id = int(interaction.data['values'][0])
        node = await db.get_siege_node(node_id)
        if node is None:
            await interaction.response.send_message(i18n.t('siege.correction.node_gone', self.lang), ephemeral=True)
            return
        await interaction.response.send_modal(NodeEditModal(node, lang=self.lang))

    async def _edit_score(self, interaction: discord.Interaction):
        score_id = int(interaction.data['values'][0])
        score = await db.get_siege_score(score_id)
        if score is None:
            await interaction.response.send_message(i18n.t('siege.correction.score_gone', self.lang), ephemeral=True)
            return
        await interaction.response.send_modal(ScoreEditModal(score, lang=self.lang))

    async def _finalize(self, interaction: discord.Interaction):
        lang = self.lang
        self.stop()
        await db.finalize_siege_match(self.match['id'])
        summary = await db.get_siege_match_summary(self.match['id'])
        league  = _league_name(self.match['team_id'])
        opp_pts = self.match.get('opp_total_points')
        embed = discord.Embed(
            title=i18n.t('siege.correction.finalized_title', lang, league=league, opp_league=self.match['opp_league']),
            description=i18n.t('siege.correction.finalized_desc', lang,
                               score=summary['league_score'],
                               opp_pts=opp_pts if opp_pts is not None else '—'),
            color=discord.Color.gold()
        )
        embed.add_field(name=i18n.t('siege.correction.cleared_nodes_field', lang), value=str(len(summary['cleared_nodes'])), inline=True)
        embed.add_field(name=i18n.t('siege.correction.ppd_field', lang), value=str(summary['ppd']), inline=True)
        await interaction.response.edit_message(content=i18n.t('siege.correction.finalized_content', lang), embed=None, view=None)
        channel = interaction.channel
        if channel:
            await channel.send(embed=embed)


async def _send_correction_view(interaction: discord.Interaction, team_id: str, allow_finalize: bool):
    lang = i18n.resolve_lang(interaction)
    match = await db.get_active_siege_match(team_id)
    if match is None:
        await interaction.response.send_message(
            i18n.t('siege.no_active_match_short', lang, league=_league_name(team_id)), ephemeral=True
        )
        return

    await interaction.response.defer()
    summary       = await db.get_siege_match_summary(match['id'])
    player_totals = await db.get_siege_all_player_totals(match['id'])
    embed         = build_status_embed(team_id, match, summary, player_totals, lang=lang)

    nodes  = await db.get_siege_nodes(match['id'])
    scores = await db.get_siege_scores_for_match(match['id'])
    view   = SiegeCorrectionView(match, nodes, scores, allow_finalize=allow_finalize, lang=lang)
    await interaction.followup.send(embed=embed, view=view)


async def handle_updatesiege(interaction: discord.Interaction, team_id: str):
    await _send_correction_view(interaction, team_id, allow_finalize=False)


async def handle_siegefinal(interaction: discord.Interaction, team_id: str):
    await _send_correction_view(interaction, team_id, allow_finalize=True)


# ============================================================================
# /siegesplits and /siegehistory — player/league viewing commands
# ============================================================================

async def handle_siegesplits(interaction: discord.Interaction, player: str):
    lang = i18n.resolve_lang(interaction)
    row = await db.get_player(player)
    if row is None:
        await interaction.response.send_message(i18n.t('common.player_not_found', lang, player=player), ephemeral=True)
        return

    await interaction.response.defer()
    splits = await db.get_siege_splits(player)
    if not splits:
        await interaction.followup.send(i18n.t('siege.splits.no_scores', lang, player=player))
        return

    embed = discord.Embed(title=i18n.t('siege.splits.title', lang, player=player), color=discord.Color.dark_gold())
    lines = []
    total_pts, total_drv = 0, 0
    for s in splits:
        ppd = round(s['points'] / s['drives'], 2) if s['drives'] else 0
        lines.append(i18n.t('siege.splits.mod_line', lang, mod=s['mod'], points=int(s['points']), drives=int(s['drives']), ppd=ppd))
        total_pts += s['points']
        total_drv += s['drives']
    embed.add_field(name=i18n.t('siege.splits.by_mod_label', lang), value="\n".join(lines), inline=False)

    overall_ppd = round(total_pts / total_drv, 2) if total_drv else 0
    embed.add_field(
        name=i18n.t('siege.splits.overall_label', lang),
        value=i18n.t('siege.splits.overall_value', lang, points=int(total_pts), drives=int(total_drv), ppd=overall_ppd),
        inline=False
    )
    await interaction.followup.send(embed=embed)


async def handle_siegehistory(interaction: discord.Interaction, team_id: str):
    lang = i18n.resolve_lang(interaction)
    await interaction.response.defer()
    history = await db.get_siege_history(team_id)
    if not history:
        await interaction.followup.send(i18n.t('siege.history.no_matches', lang, league=_league_name(team_id)))
        return

    embed = discord.Embed(title=i18n.t('siege.history.title', lang, league=_league_name(team_id)), color=discord.Color.dark_teal())
    lines = []
    for m in history:
        summary  = await db.get_siege_match_summary(m['id'])
        opp_pts  = m.get('opp_total_points')
        date_str = m['completed_at'][:10] if m.get('completed_at') else '—'
        lines.append(
            i18n.t('siege.history.line', lang, opp_league=m['opp_league'], date=date_str,
                   score=summary['league_score'], opp_pts=opp_pts if opp_pts is not None else '—')
        )
    embed.description = "\n\n".join(lines)
    await interaction.followup.send(embed=embed)
