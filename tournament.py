"""
tournament.py — Single-elimination tournament manager, backed by SQLite via db.py.

Mirrors the public API of the original Google Sheets version exactly
so optimized_bot.py command handlers need minimal changes — that's why
some method shapes here may look more suited to a spreadsheet-style
backend than a natural fit for direct SQL, despite going through db.py
underneath.

Storage layout — no direct SQL in this file at all; every read/write goes
through db.py's own CRUD functions (create_tournament, list_tournaments,
get_tournament, get_matches, record_match_result, complete_tournament,
advance_tournament_round), which are the actual source of truth for the
tournaments/tournament_matches tables' schema, not a separate schema file:
  tournaments        — one row per tournament
  tournament_matches — one row per match
"""

import math
import random
import asyncio
import datetime
from collections import defaultdict

import discord
import db
import i18n
from logger_config import global_logger as logger


class TournamentManager:
    """
    Drop-in replacement for the gspread-backed TournamentManager.
    All public methods have the same signatures as the original.
    """

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    async def _generate_id(self) -> str:
        """Return a random 4-digit ID not already in tournaments."""
        existing = {r['id'] for r in await db.list_tournaments()}
        for _ in range(100):
            tid = str(random.randint(1000, 9999))
            if tid not in existing:
                return tid
        raise RuntimeError("Could not generate a unique tournament ID.")

    # ------------------------------------------------------------------
    # Public API  (same signatures as the original)
    # ------------------------------------------------------------------

    async def create(self, players: list, name: str = "Tournament") -> str:
        """
        Shuffle players, seed bracket, persist to DB.
        Returns the 4-digit ID string.
        """
        if len(players) < 2:
            raise ValueError("Need at least 2 players to start a tournament.")

        tid = await self._generate_id()

        players = list(players)
        random.shuffle(players)
        n    = len(players)
        size = 2 ** math.ceil(math.log2(max(n, 2)))
        players.extend(["BYE"] * (size - n))
        total_rounds = int(math.log2(size))

        matches = []
        for i in range(0, size, 2):
            p1, p2 = players[i], players[i + 1]
            auto   = p1 if p2 == "BYE" else (p2 if p1 == "BYE" else "")
            matches.append({
                'round':  1,
                'match':  len(matches) + 1,
                'p1':     p1,
                'p2':     p2,
                'winner': auto,
            })

        today = datetime.date.today()
        await db.create_tournament(tid, name, total_rounds, n, today)
        await db.insert_matches(tid, matches)

        logger.info(f"Tournament {tid} ({name}) created with {n} players")
        return tid

    async def record_result(self, tid: str, match_num: int, winner: str) -> tuple:
        """
        Record the winner of a match in the current round.
        Returns (winner, tournament_over).
        """
        tourn = await db.get_tournament(tid)
        if tourn is None:
            raise ValueError(f"No tournament found with ID **{tid}**.")

        cur_rnd = tourn['current_round']
        matches = await db.get_matches(tid)

        target = next(
            (m for m in matches if m['round'] == cur_rnd and m['match'] == match_num),
            None
        )
        if target is None:
            raise ValueError(
                f"Match **{match_num}** not found in round {cur_rnd} "
                f"of tournament **{tid}**."
            )
        if winner not in (target['p1'], target['p2']):
            raise ValueError(
                f"Winner must be **{target['p1']}** or **{target['p2']}**."
            )

        await db.record_match_result(tid, cur_rnd, match_num, winner)

        # Reload to check if round is done
        matches     = await db.get_matches(tid)
        rnd_matches = [m for m in matches if m['round'] == cur_rnd]
        all_done    = all(m['winner'] for m in rnd_matches)

        if all_done:
            if cur_rnd >= tourn['total_rounds']:
                await db.complete_tournament(tid, winner)
                return winner, True
            await self._advance_round(tid, cur_rnd, matches)

        return winner, False

    async def _advance_round(self, tid: str, completed: int, matches: list):
        winners  = [m['winner'] for m in matches if m['round'] == completed]
        next_rnd = completed + 1
        new_matches = []
        match_num   = 1

        for i in range(0, len(winners), 2):
            p1 = winners[i]
            p2 = winners[i + 1] if i + 1 < len(winners) else "BYE"
            auto = p1 if p2 == "BYE" else ""
            new_matches.append({
                'round':  next_rnd,
                'match':  match_num,
                'p1':     p1,
                'p2':     p2,
                'winner': auto,
            })
            match_num += 1

        await db.insert_matches(tid, new_matches)
        await db.advance_tournament_round(tid, next_rnd)

    # ------------------------------------------------------------------
    # Display  (identical embed logic as original)
    # ------------------------------------------------------------------

    async def build_embed(self, tid: str, lang: str = 'en') -> discord.Embed:
        tourn = await db.get_tournament(tid)
        if tourn is None:
            raise ValueError(f"No tournament found with ID **{tid}**.")

        matches    = await db.get_matches(tid)
        name       = tourn['name']
        status     = tourn['status']
        cur_rnd    = tourn['current_round']
        total      = tourn['total_rounds']

        labels = {}
        labels[total] = i18n.t('tournament.round_grand_final', lang)
        if total >= 2: labels[total - 1] = i18n.t('tournament.round_semifinals', lang)
        if total >= 3: labels[total - 2] = i18n.t('tournament.round_quarterfinals', lang)

        status_label = i18n.t('tournament.status_complete', lang) if status == "complete" else i18n.t('tournament.status_active', lang)
        color = discord.Color.gold() if status == "complete" else discord.Color.blue()
        embed = discord.Embed(
            title       = f"🏆 {name}  `[{tid}]`",
            description = i18n.t('tournament.status_line', lang, status=status_label),
            color       = color,
        )

        by_round = defaultdict(list)
        for m in matches:
            by_round[m['round']].append(m)

        for rnd in sorted(by_round):
            label = labels.get(rnd, i18n.t('tournament.round_n', lang, n=rnd))
            if rnd == cur_rnd and status == "active":
                label += i18n.t('tournament.current_suffix', lang)

            lines = []
            for m in by_round[rnd]:
                if m['p2'] == "BYE":
                    lines.append(f"`M{m['match']}` **{m['p1']}** {i18n.t('tournament.bye', lang)}")
                elif m['winner']:
                    loser = m['p2'] if m['winner'] == m['p1'] else m['p1']
                    lines.append(f"`M{m['match']}` ✅ **{m['winner']}** vs ~~{loser}~~")
                else:
                    lines.append(f"`M{m['match']}` ❓ {m['p1']} vs {m['p2']}")

            chunks, current, cur_len = [], [], 0
            for line in lines:
                if cur_len + len(line) + 1 > 1024:
                    chunks.append("\n".join(current))
                    current, cur_len = [line], len(line)
                else:
                    current.append(line)
                    cur_len += len(line) + 1
            if current:
                chunks.append("\n".join(current))

            for i, chunk in enumerate(chunks):
                embed.add_field(
                    name   = label if i == 0 else i18n.t('tournament.cont', lang, label=label),
                    value  = chunk or "—",
                    inline = False,
                )

        if status == "complete":
            champ = tourn.get('champion') or "?"
            embed.set_footer(text=i18n.t('tournament.champion_footer', lang, champ=champ))
        else:
            pending = sum(
                1 for m in matches
                if m['round'] == cur_rnd and not m['winner']
            )
            embed.set_footer(
                text=i18n.t('tournament.pending_footer', lang, id=tid, cur=cur_rnd, total=total, pending=pending)
            )
        return embed

    async def build_list_embed(self, lang: str = 'en') -> discord.Embed:
        rows  = await db.list_tournaments()
        embed = discord.Embed(title=i18n.t('tournament.list_title', lang), color=discord.Color.blurple())

        active    = [r for r in rows if r['status'] == 'active']
        completed = [r for r in rows if r['status'] == 'complete']

        def fmt(r):
            return i18n.t('tournament.list_row', lang, id=r['id'], name=r['name'],
                         count=r['player_count'], created=r['created'])

        def cfmt(r):
            champ = r.get('champion') or '?'
            return i18n.t('tournament.list_row_champion', lang, id=r['id'], name=r['name'],
                         champ=champ, count=r['player_count'], created=r['created'])

        if active:
            embed.add_field(
                name   = i18n.t('tournament.list_active', lang),
                value  = "\n".join(fmt(r) for r in active),
                inline = False,
            )
        if completed:
            embed.add_field(
                name   = i18n.t('tournament.list_completed', lang),
                value  = "\n".join(cfmt(r) for r in completed),
                inline = False,
            )
        if not rows:
            embed.description = i18n.t('tournament.no_tournaments', lang)

        return embed
