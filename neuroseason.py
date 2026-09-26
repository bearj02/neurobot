"""
neuroseason.py — NeuroSeason gamemode: an NFL-shaped season played by
individual league members rather than by leagues.

Flow:
  /neuroseason create   (admin) — opens signups for a new season
  /neuroseason join             — a member signs up (up to 32)
  /neuroseason leave            — withdraw before the season starts
  /neuroseason start    (admin) — freezes the roster, splits it into two
                                  conferences and their divisions, and
                                  generates every regular-season matchup
  /seasonmatch                  — report a played matchup, from a screenshot
                                  or entered by hand
  /neuroseason standings        — division-by-division standings
  /neuroseason schedule         — the full slate, or one player's / one week's
  /neuroseason bracket          — the playoff bracket once the field is set
  /seasonstats                  — a player's stats, per season or career

Everything in the first half of this file is deliberately pure — plain dicts
in, plain dicts out, no database and no Discord — because the scheduling,
tiebreaker and seeding rules are the part most worth testing directly, and
@tree.command-decorated functions can't be called from the test suite at all
(see CLAUDE.md's testing conventions).

Two structural numbers that are NOT the same as the ones elsewhere in this
codebase: a season holds up to 32 *members* (not 18 like a league roster, not
16 like a siege/ladder), and the playoff field is 16 (not the 16 of a siege —
coincidental, unrelated concepts).
"""

import random
import datetime
from collections import defaultdict

import discord
from discord.ui import View, Button, Select, Modal, TextInput

import db
import i18n
from logger_config import global_logger as logger
# Reused rather than re-implemented: Discord's 1024-char-per-embed-field limit
# rejects the whole message, not just the offending field, and a 32-member
# standings table runs straight into it. See siege.py for the full reasoning.
from siege import _chunk_lines_to_fit as chunk_lines_to_fit

MAX_SEASON_MEMBERS = 32
MIN_SEASON_MEMBERS = 4
GAMES_PER_MEMBER   = 18
MAX_PLAYOFF_TEAMS  = 16

CONFERENCES = ("Neuro", "Verse")
DIVISION_SUFFIXES = ("East", "North", "South", "West")

# Playoff rounds, keyed by how many teams are left in a single conference.
# The final is the one round that isn't per-conference, so it isn't here.
_ROUND_BY_CONF_SIZE = {8: 'wildcard', 4: 'divisional', 2: 'conference'}
ROUND_ORDER = ('wildcard', 'divisional', 'conference', 'final')


# ===========================================================================
# Layout — how many conferences/divisions a given signup count gets
# ===========================================================================

def plan_layout(n: int) -> dict:
    """
    Split n members into two conferences and their divisions.

    Always two conferences (odd n gives the first conference the extra
    member). Divisions per conference is "as many as possible at three or
    more members each, capped at four" — which lands exactly on the NFL's
    2x4x4 at n=32 and degrades sensibly below that rather than refusing to
    run. Deliberately relative to the actual signup count, never a hardcoded
    table of special cases, for the same reason the /ladder OVR check is
    relative: a fixed table works for the sizes someone thought of and
    quietly does the wrong thing for the one they didn't.

    Returns {'divisions_per_conf': int,
             'conferences': [{'name': str, 'divisions': [{'name','size'}]}]}
    """
    if n < MIN_SEASON_MEMBERS:
        raise ValueError(f"A season needs at least {MIN_SEASON_MEMBERS} members, got {n}.")

    conf_sizes = [(n + 1) // 2, n // 2]
    smaller = min(conf_sizes)
    divisions_per_conf = max(1, min(4, smaller // 3))

    conferences = []
    for conf_name, size in zip(CONFERENCES, conf_sizes):
        base, rem = divmod(size, divisions_per_conf)
        divisions = []
        for i in range(divisions_per_conf):
            # A division of one is never useful — with more divisions than
            # there are members to fill them, drop the empty tail rather
            # than emitting zero-size divisions.
            d_size = base + (1 if i < rem else 0)
            if d_size == 0:
                continue
            divisions.append({'name': _division_name(conf_name, i, divisions_per_conf),
                              'size': d_size})
        conferences.append({'name': conf_name, 'divisions': divisions})

    return {'divisions_per_conf': divisions_per_conf, 'conferences': conferences}


def _division_name(conf_name: str, index: int, divisions_per_conf: int) -> str:
    """A one-division conference *is* the division, so it doesn't get a
    compass suffix that would imply siblings it doesn't have."""
    if divisions_per_conf == 1:
        return conf_name
    return f"{conf_name} {DIVISION_SUFFIXES[index]}"


def place_members(members: list[dict], layout: dict, rng: random.Random) -> list[dict]:
    """
    Deal the (shuffled) member list into the layout's divisions. Returns new
    dicts carrying 'conference' and 'division' alongside whatever came in.
    """
    pool = list(members)
    rng.shuffle(pool)
    placed = []
    i = 0
    for conf in layout['conferences']:
        for div in conf['divisions']:
            for _ in range(div['size']):
                m = dict(pool[i])
                m['conference'] = conf['name']
                m['division'] = div['name']
                placed.append(m)
                i += 1
    return placed


# ===========================================================================
# Schedule generation
# ===========================================================================

def _pair_key(a: int, b: int) -> tuple:
    return (a, b) if a < b else (b, a)


def build_schedule(members: list[dict], games: int = GAMES_PER_MEMBER,
                   rng: random.Random | None = None) -> list[dict]:
    """
    Build a full regular season where *every* member plays exactly `games`
    matchups, following the NFL's shape as closely as the field size allows:

      1. Every division rival, twice.
      2. Every member of one other division in your own conference, once.
      3. Every member of one division in the other conference, once.
      4. Whatever is left to reach `games` — same-conference opponents first
         (preferring people you haven't played yet), then other-conference
         ones, then, only if the field is too small for that, repeat
         meetings.

    At n=32 steps 1-3 come to 6 + 4 + 4 = 14 and step 4 adds the final 2 + 2,
    which is exactly the requested structure. Below 32 the same steps produce
    fewer games and step 4 covers a correspondingly larger share — which is
    what makes "always exactly 18" hold at any field size instead of only at
    the one that divides evenly.

    Returns a list of {'home_player_id','away_player_id','week'} dicts.
    """
    rng = rng or random.Random(0)
    ids = [m['player_id'] for m in members]
    if len(ids) < 2:
        raise ValueError("A season schedule needs at least two members.")

    conf_of = {m['player_id']: m['conference'] for m in members}
    div_of = {m['player_id']: m['division'] for m in members}

    meet: dict[tuple, int] = defaultdict(int)
    deg: dict[int, int] = {pid: 0 for pid in ids}
    pairs: list[tuple[int, int]] = []

    def add(a: int, b: int):
        pairs.append((a, b))
        meet[_pair_key(a, b)] += 1
        deg[a] += 1
        deg[b] += 1

    by_div: dict[str, list[int]] = defaultdict(list)
    for pid in ids:
        by_div[div_of[pid]].append(pid)

    # 1 — division rivals, home and away.
    for members_in_div in by_div.values():
        for i, a in enumerate(members_in_div):
            for b in members_in_div[i + 1:]:
                add(a, b)
                add(a, b)

    # 2 — one other division in the same conference, played through once.
    #     The pairing is randomised per season (seeded, so a given season
    #     always regenerates identically) rather than fixed, so the same two
    #     divisions aren't locked together season after season. An odd
    #     number of divisions leaves one unpaired; its members pick those
    #     games up in step 4 instead.
    for conf in CONFERENCES:
        divs = sorted({div_of[pid] for pid in ids if conf_of[pid] == conf})
        rng.shuffle(divs)
        for i in range(0, len(divs) - 1, 2):
            _play_divisions(by_div[divs[i]], by_div[divs[i + 1]], add)

    # 3 — one division from the other conference, played through once.
    a_divs = sorted({div_of[pid] for pid in ids if conf_of[pid] == CONFERENCES[0]})
    b_divs = sorted({div_of[pid] for pid in ids if conf_of[pid] == CONFERENCES[1]})
    rng.shuffle(a_divs)
    rng.shuffle(b_divs)
    for d_a, d_b in zip(a_divs, b_divs):
        _play_divisions(by_div[d_a], by_div[d_b], add)

    # 4 — fill everyone up to exactly `games`.
    remaining = {pid: games - deg[pid] for pid in ids}
    for pid, r in remaining.items():
        if r < 0:
            raise ValueError(
                f"The structured rounds already give a member {deg[pid]} games, "
                f"more than the {games} this season is set to — the field is too "
                f"small for that many divisions."
            )

    # 4a: same conference, someone not yet played, but only down to the last
    #     two games so that a couple of cross-conference slots survive.
    _greedy_fill(ids, remaining, meet, add, floor=2,
                 allowed=lambda a, b: conf_of[a] == conf_of[b] and meet[_pair_key(a, b)] == 0,
                 conf_of=conf_of)
    # 4b: other conference, someone not yet played.
    _greedy_fill(ids, remaining, meet, add, floor=0,
                 allowed=lambda a, b: conf_of[a] != conf_of[b] and meet[_pair_key(a, b)] == 0,
                 conf_of=conf_of)
    # 4c: anything at all. Small fields genuinely run out of fresh opponents,
    #     so this is where repeat meetings come from. Always succeeds: a
    #     multigraph with an even degree sum is realisable as long as no
    #     single member needs more games than everyone else combined, and
    #     pairing the two neediest members each time preserves that.
    _greedy_fill(ids, remaining, meet, add, floor=0,
                 allowed=lambda a, b: True, conf_of=conf_of)

    stranded = {pid: r for pid, r in remaining.items() if r > 0}
    if stranded:
        raise ValueError(
            f"Could not reach {games} games for every member; short: {stranded}. "
            "This should be impossible for a field of two or more — please report it."
        )

    scheduled = _assign_weeks(pairs, rng)
    return _assign_home_away(scheduled)


def _play_divisions(div_a: list[int], div_b: list[int], add):
    for a in div_a:
        for b in div_b:
            add(a, b)


def _greedy_fill(ids, remaining, meet, add, floor, allowed, conf_of):
    """
    Pair members down toward `floor` remaining games each, using only pairs
    `allowed` permits.

    Always takes the member who needs the most games and pairs them with
    whoever needs the most among the allowed candidates. That ordering isn't
    cosmetic: pairing the two largest is what keeps the remaining-degree
    sequence realisable, so the unrestricted final pass can never strand
    someone needing games with nobody left to play (the classic
    Havel-Hakimi argument, which holds for multigraphs whenever the degree
    sum is even).
    """
    while True:
        active = [pid for pid in ids if remaining[pid] > floor]
        if len(active) < 2:
            break
        active.sort(key=lambda p: (-remaining[p], p))
        a = active[0]
        candidates = [b for b in active[1:] if allowed(a, b)]
        if not candidates:
            # This member has no allowed partner left. Retry with the next
            # neediest member before giving the stage up entirely — one
            # exhausted member doesn't mean the rest are.
            progressed = False
            for a in active[1:]:
                candidates = [b for b in active if b != a and allowed(a, b)]
                if candidates:
                    progressed = True
                    break
            if not progressed:
                break
        candidates.sort(key=lambda b: (-remaining[b], meet[_pair_key(a, b)], b))
        b = candidates[0]
        add(a, b)
        remaining[a] -= 1
        remaining[b] -= 1


def _assign_weeks(pairs: list[tuple[int, int]], rng: random.Random,
                  attempts: int = 8) -> list[dict]:
    """
    Spread the matchups across weeks so nobody plays twice in one week.

    Fills one week at a time, each week taking as many matchups as it can fit
    and taking the most-booked members' games first — a member with games
    left to place is the one most likely to become the bottleneck later, so
    they get placed while there's still room. Best of several seeded
    attempts, so the same season always regenerates the same calendar rather
    than shimmering between runs.

    **The calendar runs slightly longer than the game count, and that's
    correct, not a bug.** Every division pairing meets twice, and two members
    can't play each other twice in the same week, which pushes the minimum
    possible number of weeks above the number of games each member plays
    (Vizing's theorem for multigraphs: the extra weeks come from the repeated
    pairs, not from the packing being sloppy). An 18-game season lands around
    20 weeks, so each member gets roughly two byes — which is the same shape
    the NFL's own 17-games-in-18-weeks has, just with one more bye.
    """
    best: list[dict] | None = None
    best_weeks: int | None = None
    for _ in range(attempts):
        edges = list(pairs)
        rng.shuffle(edges)
        left: dict[int, int] = defaultdict(int)
        for a, b in edges:
            left[a] += 1
            left[b] += 1

        attempt: list[dict] = []
        week = 0
        while edges:
            week += 1
            used: set[int] = set()
            deferred: list[tuple[int, int]] = []
            edges.sort(key=lambda e: -(left[e[0]] + left[e[1]]))
            for a, b in edges:
                if a in used or b in used:
                    deferred.append((a, b))
                    continue
                used.update((a, b))
                left[a] -= 1
                left[b] -= 1
                attempt.append({'home_player_id': a, 'away_player_id': b, 'week': week})
            edges = deferred

        if best_weeks is None or week < best_weeks:
            best, best_weeks = attempt, week
    best.sort(key=lambda m: m['week'])
    return best


def _assign_home_away(scheduled: list[dict]) -> list[dict]:
    """
    Even out home games. Purely cosmetic in this game — there's no home-field
    advantage to model — but a schedule where one member is always listed
    second reads like a bug even when it isn't.
    """
    home_count: dict[int, int] = defaultdict(int)
    out = []
    for m in scheduled:
        a, b = m['home_player_id'], m['away_player_id']
        if home_count[b] < home_count[a]:
            a, b = b, a
        home_count[a] += 1
        out.append({**m, 'home_player_id': a, 'away_player_id': b})
    return out


# ===========================================================================
# Standings and tiebreakers
# ===========================================================================

def _pct(wins: int, losses: int, ties: int) -> float:
    played = wins + losses + ties
    return (wins + 0.5 * ties) / played if played else 0.0


def compute_standings(members: list[dict], matches: list[dict]) -> list[dict]:
    """
    Build a standings row per member from the completed matches.

    Counts overall, division and conference records separately (all three are
    tiebreakers) plus points for and against. Only 'complete' matches count —
    a scheduled-but-unplayed matchup is not a loss.
    """
    conf_of = {m['player_id']: m.get('conference') for m in members}
    div_of = {m['player_id']: m.get('division') for m in members}

    rows = {
        m['player_id']: {
            'player_id': m['player_id'],
            'ign': m.get('ign'),
            'conference': m.get('conference'),
            'division': m.get('division'),
            'seed': m.get('seed'),
            'wins': 0, 'losses': 0, 'ties': 0,
            'div_wins': 0, 'div_losses': 0, 'div_ties': 0,
            'conf_wins': 0, 'conf_losses': 0, 'conf_ties': 0,
            'points_for': 0, 'points_against': 0,
        }
        for m in members
    }

    for mt in matches:
        if mt.get('status') != 'complete':
            continue
        h, a = mt['home_player_id'], mt['away_player_id']
        if h not in rows or a not in rows:
            continue
        hs = mt.get('home_score') or 0
        as_ = mt.get('away_score') or 0
        same_div = div_of[h] is not None and div_of[h] == div_of[a]
        same_conf = conf_of[h] is not None and conf_of[h] == conf_of[a]
        for pid, own, opp in ((h, hs, as_), (a, as_, hs)):
            r = rows[pid]
            r['points_for'] += own
            r['points_against'] += opp
            outcome = 'ties' if own == opp else ('wins' if own > opp else 'losses')
            r[outcome] += 1
            if same_div:
                r['div_' + outcome] += 1
            if same_conf:
                r['conf_' + outcome] += 1

    out = list(rows.values())
    for r in out:
        r['games'] = r['wins'] + r['losses'] + r['ties']
        r['win_pct'] = _pct(r['wins'], r['losses'], r['ties'])
    return out


def rank_rows(rows: list[dict], matches: list[dict]) -> list[dict]:
    """
    Order standings rows best-first, applying the tiebreakers in the
    requested order: head-to-head, then division record, then conference
    record, then points for.

    Head-to-head is computed *relative to the tied group* — for two tied
    members that's literally their record against each other, and for three
    or more it's each member's record against the rest of the group, which
    is how the NFL's own multi-team procedure starts. This is a deliberate
    simplification of the full NFL rulebook (which then drops to
    common-games, strength-of-victory and eventually a coin toss); the four
    tiebreakers asked for are applied exactly, and player_id breaks anything
    still level so the order is at least stable rather than arbitrary.
    """
    ordered = sorted(rows, key=lambda r: (-r['win_pct'], r['player_id']))
    out: list[dict] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1]['win_pct'] == ordered[i]['win_pct']:
            j += 1
        group = ordered[i:j + 1]
        out.extend(group if len(group) == 1 else _break_tie(group, matches))
        i = j + 1
    return out


def _break_tie(group: list[dict], matches: list[dict]) -> list[dict]:
    ids = {r['player_id'] for r in group}
    h2h = {pid: [0, 0, 0] for pid in ids}  # wins, losses, ties within the group
    for mt in matches:
        if mt.get('status') != 'complete':
            continue
        h, a = mt['home_player_id'], mt['away_player_id']
        if h not in ids or a not in ids:
            continue
        hs = mt.get('home_score') or 0
        as_ = mt.get('away_score') or 0
        if hs == as_:
            h2h[h][2] += 1
            h2h[a][2] += 1
        elif hs > as_:
            h2h[h][0] += 1
            h2h[a][1] += 1
        else:
            h2h[a][0] += 1
            h2h[h][1] += 1

    def key(r):
        w, l, t = h2h[r['player_id']]
        return (
            -_pct(w, l, t),
            -_pct(r['div_wins'], r['div_losses'], r['div_ties']),
            -_pct(r['conf_wins'], r['conf_losses'], r['conf_ties']),
            -r['points_for'],
            r['player_id'],
        )

    return sorted(group, key=key)


def playoff_field_size(member_count: int) -> int:
    """
    16 teams whenever the field can support it, which is every season of 16
    or more members. Below that a 16-team bracket literally cannot be drawn,
    so it falls to the largest power of two that fits — a clean bracket with
    no byes, rather than a 16-slot one padded with ghosts.
    """
    size = min(MAX_PLAYOFF_TEAMS, member_count)
    field = 2
    while field * 2 <= size:
        field *= 2
    return field


def compute_seeds(standings: list[dict], matches: list[dict],
                  playoff_teams: int) -> dict[str, list[dict]]:
    """
    Seed each conference: division winners first (ranked against each other),
    then the best of the rest as wild cards. Returns {conference: [rows]}
    with a 'seed' key set on each, best seed first.
    """
    per_conf = max(1, playoff_teams // 2)
    seeded: dict[str, list[dict]] = {}
    for conf in CONFERENCES:
        conf_rows = [r for r in standings if r['conference'] == conf]
        if not conf_rows:
            seeded[conf] = []
            continue
        divisions = sorted({r['division'] for r in conf_rows})
        winners = [rank_rows([r for r in conf_rows if r['division'] == d], matches)[0]
                   for d in divisions]
        winners = rank_rows(winners, matches)
        winner_ids = {r['player_id'] for r in winners}
        wildcards = rank_rows([r for r in conf_rows if r['player_id'] not in winner_ids], matches)
        field = (winners + wildcards)[:per_conf]
        for n, row in enumerate(field, start=1):
            row['seed'] = n
        seeded[conf] = field
    return seeded


# ===========================================================================
# Playoff bracket
# ===========================================================================

def round_name_for(teams_left_per_conf: int) -> str:
    """The round a given number of remaining per-conference teams plays."""
    return _ROUND_BY_CONF_SIZE.get(teams_left_per_conf, 'final')


def build_playoff_round(remaining: dict[str, list[dict]]) -> list[dict]:
    """
    Pair up one playoff round. `remaining` is {conference: [rows with 'seed']}.

    Re-seeded every round, NFL style — the best remaining seed always draws
    the worst remaining seed, rather than following a fixed bracket path. The
    higher seed is the home side.

    When each conference is down to its last team, the two of them meet in
    the final, which is the one round with no conference of its own.
    """
    conf_lists = {c: sorted(rows, key=lambda r: r['seed']) for c, rows in remaining.items()}
    sizes = {c: len(rows) for c, rows in conf_lists.items()}
    live = [c for c, s in sizes.items() if s > 0]

    if all(sizes.get(c, 0) <= 1 for c in live) and len(live) == 2:
        a, b = conf_lists[live[0]][0], conf_lists[live[1]][0]
        return [{'round': 'final', 'conference': None,
                 'home_player_id': a['player_id'], 'away_player_id': b['player_id']}]

    matches = []
    for conf in CONFERENCES:
        rows = conf_lists.get(conf, [])
        if len(rows) < 2:
            continue
        rname = round_name_for(len(rows))
        for i in range(len(rows) // 2):
            high, low = rows[i], rows[len(rows) - 1 - i]
            matches.append({'round': rname, 'conference': conf,
                            'home_player_id': high['player_id'],
                            'away_player_id': low['player_id']})
    return matches


# ===========================================================================
# Discord handlers
# ===========================================================================

def _season_rng(season_id: int) -> random.Random:
    """Seeded off the season's own id so regenerating a season's structure is
    reproducible instead of shimmering between runs — the same reasoning as
    the seeded background art in sheet_image.py."""
    return random.Random(season_id * 7919 + 13)


async def _resolve_player(interaction, ign: str, lang: str):
    """
    Look a player up by nickname, falling back to an unfiltered lookup.

    db.get_player() excludes inactive players, which is right for a live
    league command but wrong here: a season roster is frozen at signup, so
    someone who goes inactive halfway through still has scheduled matchups
    that have to be reportable and stats that have to stay readable. Without
    this fallback, a member going inactive would silently make their own
    remaining matches impossible to log.
    """
    player = await db.get_player(ign)
    if player is None:
        player = await db.fetchone("SELECT * FROM players WHERE ign = ? LIMIT 1", (ign,))
    if player is None:
        await _send(interaction, i18n.t('neuroseason.err.no_player', lang, player=ign))
        return None
    return player


async def _send(interaction: discord.Interaction, content=None, *, embed=None, ephemeral=True):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def _resolve_season(interaction, season_id: int, lang: str) -> dict | None:
    season = await db.get_neuro_season(season_id)
    if season is None:
        await _send(interaction, i18n.t('neuroseason.err.no_season', lang, season=season_id))
        return None
    return season


# --- /neuroseason create ---------------------------------------------------

async def handle_create(interaction: discord.Interaction, name: str):
    lang = i18n.resolve_lang(interaction)
    season = await db.create_neuro_season(name.strip())
    await interaction.response.send_message(
        i18n.t('neuroseason.create.success', lang,
               name=season['name'], season=season['id'], max=MAX_SEASON_MEMBERS)
    )


# --- /neuroseason join / leave --------------------------------------------

async def handle_join(interaction: discord.Interaction, season_id: int, ign: str):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    if season['status'] != 'signups':
        await _send(interaction, i18n.t('neuroseason.err.signups_closed', lang,
                                        name=season['name']))
        return

    player = await _resolve_player(interaction, ign, lang)
    if player is None:
        return

    members = await db.get_neuro_season_members(season_id)
    if len(members) >= (season['max_members'] or MAX_SEASON_MEMBERS):
        await _send(interaction, i18n.t('neuroseason.err.full', lang,
                                        name=season['name'], max=season['max_members']))
        return

    added = await db.add_neuro_season_member(season_id, player['id'], player['team_id'])
    if not added:
        await _send(interaction, i18n.t('neuroseason.join.already', lang,
                                        player=player['ign'], name=season['name']))
        return

    await interaction.response.send_message(
        i18n.t('neuroseason.join.success', lang, player=player['ign'], name=season['name'],
               count=len(members) + 1, max=season['max_members'] or MAX_SEASON_MEMBERS)
    )


async def handle_leave(interaction: discord.Interaction, season_id: int, ign: str):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    if season['status'] != 'signups':
        # Removing someone from a started season would leave their scheduled
        # matchups pointing at a member who isn't in it — the season would
        # have to be regenerated, which is a different operation entirely.
        await _send(interaction, i18n.t('neuroseason.err.already_started', lang,
                                        name=season['name']))
        return
    player = await _resolve_player(interaction, ign, lang)
    if player is None:
        return
    removed = await db.remove_neuro_season_member(season_id, player['id'])
    key = 'neuroseason.leave.success' if removed else 'neuroseason.leave.not_in'
    await _send(interaction, i18n.t(key, lang, player=player['ign'], name=season['name']),
                ephemeral=not removed)


# --- /neuroseason start ----------------------------------------------------

async def handle_start(interaction: discord.Interaction, season_id: int):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    if season['status'] != 'signups':
        await _send(interaction, i18n.t('neuroseason.err.already_started', lang,
                                        name=season['name']))
        return

    members = await db.get_neuro_season_members(season_id)
    if len(members) < MIN_SEASON_MEMBERS:
        await _send(interaction, i18n.t('neuroseason.err.too_few', lang,
                                        count=len(members), min=MIN_SEASON_MEMBERS))
        return

    # Generating a 32-member, 288-matchup schedule and writing it row by row
    # is comfortably past Discord's 3-second acknowledgement window, so defer
    # before any of the work rather than after it.
    await interaction.response.defer()

    rng = _season_rng(season_id)
    layout = plan_layout(len(members))
    placed = place_members(members, layout, rng)
    games = season['games_per_member'] or GAMES_PER_MEMBER

    try:
        schedule = build_schedule(placed, games=games, rng=rng)
    except ValueError as e:
        await interaction.followup.send(f"⚠️ {e}")
        return

    for m in placed:
        await db.set_neuro_season_member_placement(
            season_id, m['player_id'], m['conference'], m['division'])
    await db.insert_neuro_season_matches(season_id, schedule)

    weeks = max(m['week'] for m in schedule)
    await db.update_neuro_season(
        season_id, status='active', started_at=datetime.datetime.now().isoformat(timespec='seconds'),
        divisions_per_conf=layout['divisions_per_conf'], weeks=weeks,
        playoff_teams=playoff_field_size(len(members)))

    embed = discord.Embed(
        title=i18n.t('neuroseason.start.title', lang, name=season['name']),
        description=i18n.t('neuroseason.start.desc', lang, count=len(members),
                           games=games, weeks=weeks, matches=len(schedule),
                           playoff=playoff_field_size(len(members))),
        color=discord.Color.green(),
    )
    by_div = defaultdict(list)
    for m in placed:
        by_div[m['division']].append(m['ign'])
    for division, igns in by_div.items():
        embed.add_field(name=division, value="\n".join(igns) or "—", inline=True)
    await interaction.followup.send(embed=embed)


# --- /neuroseason list / standings / schedule ------------------------------

async def handle_list(interaction: discord.Interaction):
    lang = i18n.resolve_lang(interaction)
    seasons = await db.list_neuro_seasons()
    if not seasons:
        await _send(interaction, i18n.t('neuroseason.list.empty', lang))
        return
    lines = []
    for s in seasons:
        members = await db.get_neuro_season_members(s['id'])
        lines.append(i18n.t('neuroseason.list.row', lang, season=s['id'], name=s['name'],
                            status=_status_label(s['status'], lang), count=len(members)))
    embed = discord.Embed(title=i18n.t('neuroseason.list.title', lang),
                          color=discord.Color.blurple())
    for n, chunk in enumerate(chunk_lines_to_fit(lines)):
        embed.add_field(name="​" if n else i18n.t('neuroseason.list.header', lang),
                        value=chunk, inline=False)
    await _send(interaction, embed=embed, ephemeral=False)


def _status_label(status: str, lang: str) -> str:
    return i18n.t(f'neuroseason.status.{status}', lang)


async def season_divisions(season_id: int) -> list[str]:
    """Every division this particular season actually drew, in name order.

    Read from the season's own members rather than generated from
    CONFERENCES x DIVISION_SUFFIXES: the layout scales with the signup count,
    so a 16-member season has four divisions and a 32-member one has eight.
    Offering names a given season never drew would just produce empty
    tables."""
    rows = await db.fetchall(
        """
        SELECT DISTINCT division FROM neuro_season_members
        WHERE season_id=? AND division IS NOT NULL
        ORDER BY division
        """,
        (season_id,)
    )
    return [r['division'] for r in rows]


def _fmt_record(wins: int, losses: int, ties: int) -> str:
    """W-L, or W-L-T once there's actually been a tie.

    Three records now sit on every standings line, so the zero-tie case
    dropping its trailing '-0' is what keeps the row readable — and a tie is
    rare enough that showing it only when it happened is more informative
    than a column of '-0'."""
    return f"{wins}-{losses}" if not ties else f"{wins}-{losses}-{ties}"


async def handle_standings(interaction: discord.Interaction, season_id: int,
                           conference: str | None = None,
                           division: str | None = None):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    if season['status'] == 'signups':
        # Before /neuroseason start there are no divisions to group by, so
        # this would otherwise render one nameless block of everyone who has
        # signed up and call it a table.
        await _send(interaction, i18n.t('neuroseason.err.not_started', lang,
                                        name=season['name']))
        return

    members = await db.get_neuro_season_members(season_id)
    matches = await db.get_neuro_season_matches(season_id, stage='regular')
    standings = compute_standings(members, matches)

    # Autocomplete only ever *suggests* a value — Discord still accepts
    # whatever was typed — so the division has to be re-validated here, the
    # same way /legacy re-validates its league. Matched case-insensitively
    # because a hand-typed "neuro east" is unambiguously the same division.
    wanted_division = None
    if division:
        wanted_division = next(
            (d for d in await season_divisions(season_id) if d.lower() == division.lower()),
            None)
        if wanted_division is None:
            await _send(interaction, i18n.t(
                'neuroseason.err.no_division', lang, division=division,
                divisions=", ".join(await season_divisions(season_id)) or "—"))
            return

    by_div: dict[str, list[dict]] = defaultdict(list)
    for r in standings:
        if conference and r['conference'] != conference:
            continue
        if wanted_division and r['division'] != wanted_division:
            continue
        by_div[r['division'] or '—'].append(r)
    if not by_div:
        # A filter that matches nothing is a different problem from a season
        # that hasn't started — e.g. a real division asked for inside the
        # conference it isn't in. Saying "run /neuroseason start" there sends
        # someone off to fix something that isn't broken.
        key = ('neuroseason.err.empty_filter' if (conference or wanted_division)
               else 'neuroseason.err.not_started')
        await _send(interaction, i18n.t(key, lang, name=season['name'],
                                        conference=conference or "—",
                                        division=wanted_division or "—"))
        return

    embed = discord.Embed(
        title=i18n.t('neuroseason.standings.title', lang, name=season['name']),
        color=discord.Color.gold())
    for div_name in sorted(by_div):
        ranked = rank_rows(by_div[div_name], matches)
        lines = [
            i18n.t('neuroseason.standings.row', lang, pos=n, player=r['ign'],
                   rec=_fmt_record(r['wins'], r['losses'], r['ties']),
                   div=_fmt_record(r['div_wins'], r['div_losses'], r['div_ties']),
                   conf=_fmt_record(r['conf_wins'], r['conf_losses'], r['conf_ties']),
                   pf=r['points_for'], pa=r['points_against'])
            for n, r in enumerate(ranked, start=1)
        ]
        for n, chunk in enumerate(chunk_lines_to_fit(lines)):
            embed.add_field(name=div_name if n == 0 else f"{div_name} (cont.)",
                            value=chunk, inline=False)
    # Three records per line needs a key; the tiebreaker order is worth
    # stating alongside it, since those same three records are what
    # decides the order the rows are in.
    embed.set_footer(text=i18n.t('neuroseason.standings.legend', lang) + "\n"
                          + i18n.t('neuroseason.standings.footer', lang))
    await _send(interaction, embed=embed, ephemeral=False)


async def handle_schedule(interaction: discord.Interaction, season_id: int,
                          ign: str | None = None, week: int | None = None):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return

    player_id = None
    if ign:
        player = await _resolve_player(interaction, ign, lang)
        if player is None:
            return
        player_id = player['id']

    matches = await db.get_neuro_season_matches(season_id, player_id=player_id, week=week)
    if not matches:
        await _send(interaction, i18n.t('neuroseason.schedule.empty', lang,
                                        name=season['name']))
        return

    lines = [_match_line(m, lang) for m in matches]
    embed = discord.Embed(
        title=i18n.t('neuroseason.schedule.title', lang, name=season['name']),
        color=discord.Color.blue())
    # A 32-member season is 288 matchups, far more than five 1024-character
    # fields hold, so the unfiltered view genuinely will be cut short — say
    # so, and point at the filters that narrow it.
    chunks = chunk_lines_to_fit(lines)
    for n, chunk in enumerate(chunks):
        embed.add_field(name=i18n.t('neuroseason.schedule.header', lang) if n == 0 else "​",
                        value=chunk, inline=False)
    if sum(c.count("\n") + 1 for c in chunks) < len(lines):
        embed.set_footer(text=i18n.t('neuroseason.schedule.truncated', lang))
    await _send(interaction, embed=embed, ephemeral=False)


def _match_line(m: dict, lang: str) -> str:
    where = (i18n.t(f'neuroseason.round.{m["round"]}', lang) if m['stage'] == 'playoff'
             else i18n.t('neuroseason.schedule.week', lang, week=m['week']))
    if m['status'] == 'complete':
        return i18n.t('neuroseason.schedule.row_done', lang, num=m['match_num'], where=where,
                      home=m['home_ign'], away=m['away_ign'],
                      hs=m['home_score'], as_=m['away_score'])
    return i18n.t('neuroseason.schedule.row_pending', lang, num=m['match_num'], where=where,
                  home=m['home_ign'], away=m['away_ign'])


async def handle_bracket(interaction: discord.Interaction, season_id: int):
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    matches = await db.get_neuro_season_matches(season_id, stage='playoff')
    if not matches:
        await _send(interaction, i18n.t('neuroseason.bracket.none', lang, name=season['name']))
        return
    embed = discord.Embed(
        title=i18n.t('neuroseason.bracket.title', lang, name=season['name']),
        color=discord.Color.purple())
    by_round: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        by_round[m['round']].append(m)
    for rname in ROUND_ORDER:
        if rname not in by_round:
            continue
        lines = [_match_line(m, lang) for m in by_round[rname]]
        for n, chunk in enumerate(chunk_lines_to_fit(lines)):
            embed.add_field(name=i18n.t(f'neuroseason.round.{rname}', lang) if n == 0 else "​",
                            value=chunk, inline=False)
    if season['champion_player_id']:
        champ = await db.fetchone("SELECT ign FROM players WHERE id=?",
                                  (season['champion_player_id'],))
        if champ:
            embed.add_field(name=i18n.t('neuroseason.bracket.champion', lang),
                            value=f"🏆 **{champ['ign']}**", inline=False)
    await _send(interaction, embed=embed, ephemeral=False)


# --- /seasonstats ----------------------------------------------------------

async def handle_seasonstats(interaction: discord.Interaction, ign: str,
                             season_id: int | None = None):
    lang = i18n.resolve_lang(interaction)
    player = await _resolve_player(interaction, ign, lang)
    if player is None:
        return

    if season_id is not None:
        season = await _resolve_season(interaction, season_id, lang)
        if season is None:
            return
        stats = await db.get_neuro_season_player_stats(season_id, player['id'])
        if not stats:
            await _send(interaction, i18n.t('neuroseason.stats.none', lang,
                                            player=player['ign'], name=season['name']))
            return
        embed = _stats_embed(player['ign'], season['name'], stats, lang)
        member = await db.get_neuro_season_member(season_id, player['id'])
        if member and member['division']:
            embed.add_field(name=i18n.t('neuroseason.stats.division', lang),
                            value=member['division'], inline=True)
        if member and member['seed']:
            embed.add_field(name=i18n.t('neuroseason.stats.seed', lang),
                            value=str(member['seed']), inline=True)
        await _send(interaction, embed=embed, ephemeral=False)
        return

    career = await db.get_neuro_season_player_career(player['id'])
    if not career:
        await _send(interaction, i18n.t('neuroseason.stats.no_career', lang,
                                        player=player['ign']))
        return
    embed = discord.Embed(
        title=i18n.t('neuroseason.stats.career_title', lang, player=player['ign']),
        color=discord.Color.teal())
    lines = [
        i18n.t('neuroseason.stats.career_row', lang, season=row['season_id'],
               name=row['season_name'], w=row['wins'] or 0, l=row['losses'] or 0,
               t=row['ties'] or 0, pf=row['points'] or 0, td=row['touchdowns'] or 0)
        for row in career
    ]
    for n, chunk in enumerate(chunk_lines_to_fit(lines)):
        embed.add_field(name=i18n.t('neuroseason.stats.career_header', lang) if n == 0 else "​",
                        value=chunk, inline=False)
    await _send(interaction, embed=embed, ephemeral=False)


def _stats_embed(ign: str, season_name: str, stats: dict, lang: str) -> discord.Embed:
    embed = discord.Embed(
        title=i18n.t('neuroseason.stats.title', lang, player=ign, name=season_name),
        color=discord.Color.teal())
    embed.add_field(name=i18n.t('neuroseason.stats.record', lang),
                    value=f"{stats['wins'] or 0}-{stats['losses'] or 0}-{stats['ties'] or 0}",
                    inline=True)
    embed.add_field(name=i18n.t('neuroseason.stats.games', lang),
                    value=str(stats['games'] or 0), inline=True)
    embed.add_field(name=i18n.t('neuroseason.stats.pf_pa', lang),
                    value=f"{stats['points'] or 0} / {stats['points_against'] or 0}", inline=True)
    for field, key in (('rushing_yds', 'rush'), ('passing_yds', 'pass'),
                       ('kick_return_yds', 'kr'), ('touchdowns', 'td'),
                       ('turnovers', 'to'), ('field_goals', 'fg')):
        embed.add_field(name=i18n.t(f'neuroseason.stat.{key}', lang),
                        value=str(stats.get(field) or 0), inline=True)
    return embed


# ===========================================================================
# /seasonmatch — report a played matchup from its screenshot
# ===========================================================================

async def handle_seasonmatch(interaction: discord.Interaction, season_id: int, match_num: int,
                             left_ign: str, right_ign: str, screenshot=None):
    """
    Log a played matchup, from a result screenshot or entered by hand.

    The screenshot identifies the two sides only by NFL team logo, never by
    player name, which is exactly why the command takes left_player and
    right_player — the bot cannot work out on its own whose column is
    whose. Both must be the two members actually scheduled in this match,
    in either order; the left/right arguments are about the picture, not
    about who's listed first in the fixture. (When the screenshot is
    omitted there is no picture, and left/right are just two labels for the
    two sides — the fixture still decides who's home.)

    **The screenshot is optional.** Players forget to take one, and a match
    that genuinely happened still has to be reportable — so with no
    screenshot this opens the same editor with every stat blank. Every path
    lands in the same place: the review embed plus the stat editor, with
    nothing written until a human confirms.
    """
    lang = i18n.resolve_lang(interaction)
    season = await _resolve_season(interaction, season_id, lang)
    if season is None:
        return
    if season['status'] not in ('active', 'playoffs'):
        await _send(interaction, i18n.t('neuroseason.err.not_started', lang, name=season['name']))
        return

    match = await db.get_neuro_season_match(season_id, match_num)
    if match is None:
        await _send(interaction, i18n.t('neuroseason.err.no_match', lang,
                                        num=match_num, name=season['name']))
        return

    left = await _resolve_player(interaction, left_ign, lang)
    if left is None:
        return
    right = await _resolve_player(interaction, right_ign, lang)
    if right is None:
        return

    scheduled = {match['home_player_id'], match['away_player_id']}
    if {left['id'], right['id']} != scheduled:
        await _send(interaction, i18n.t('neuroseason.err.wrong_players', lang,
                                        num=match_num, home=match['home_ign'],
                                        away=match['away_ign']))
        return

    # Downloading the image and waiting on the vision model is far past
    # Discord's 3-second window, so defer first — before any of the work,
    # not after it (the /ladder manual-match flow had exactly this bug).
    await interaction.response.defer()

    left_stats = blank_stats()
    right_stats = blank_stats()
    source = 'manual'
    note = None

    if screenshot is not None:
        import agent
        try:
            extracted = await agent.extract_season_match_from_screenshot([screenshot.url])
        except Exception as e:
            # Deliberately not a dead end. The match still happened, and the
            # editor below can take every stat by hand — bailing here would
            # make a transient API failure mean "you can't report this at
            # all" when there's a perfectly good manual path one message
            # away.
            logger.error(
                f"/seasonmatch extraction failed for season {season_id} match {match_num}: {e}")
            note = i18n.t('neuroseason.err.extract_failed_manual', lang, error=str(e)[:200])
        else:
            left_stats.update({k: v for k, v in (extracted.get('left') or {}).items()
                               if k in db.SEASON_STAT_FIELDS})
            right_stats.update({k: v for k, v in (extracted.get('right') or {}).items()
                                if k in db.SEASON_STAT_FIELDS})
            source = 'screenshot'
            if left_stats.get('points') is None or right_stats.get('points') is None:
                note = i18n.t('neuroseason.err.no_scores_manual', lang)

    view = SeasonMatchConfirmView(season, match, left, right, left_stats, right_stats, lang,
                                  source=source)
    await interaction.followup.send(content=note, embed=view.build_embed(), view=view)


def blank_stats() -> dict:
    """Every stat column, explicitly unset. Not `{}` — a missing key and a
    key that's genuinely None mean the same thing here, and keeping the full
    shape means the editor and the embed never have to guess which stats
    exist."""
    return {f: None for f in db.SEASON_STAT_FIELDS}


# The seven per-match stats, split into modal-sized pages.
#
# A modal takes at most five top-level components. Putting both players'
# value for one stat in a single modal would fit only two stats per modal
# (four fields), so the split is per player instead: one page of four stats,
# one of three, giving every stat its own labelled field with no combined
# "3/0/0"-style fields to parse. Four menu entries (two players x two pages)
# cover all fourteen values.
STAT_PAGES = (
    ('score',  ('points', 'rushing_yds', 'passing_yds', 'kick_return_yds')),
    ('counts', ('touchdowns', 'turnovers', 'field_goals')),
)

# The i18n suffix and input width for each stat. Yardage genuinely reaches
# four digits over a season's worth of games; scores and counts don't.
_STAT_META = {
    'points':          ('pts',  3),
    'rushing_yds':     ('rush', 4),
    'passing_yds':     ('pass', 4),
    'kick_return_yds': ('kr',   4),
    'touchdowns':      ('td',   2),
    'turnovers':       ('to',   2),
    'field_goals':     ('fg',   2),
}


def _stat_label(field: str, lang: str) -> str:
    return i18n.t(f'neuroseason.stat.{_STAT_META[field][0]}', lang)


class SeasonMatchConfirmView(View):
    """
    Review-and-edit step for a season result. Nothing is written until a
    human presses Confirm.

    Two reasons this step exists at all, and they apply to both input
    routes. Vision extraction is imperfect — a misread leading digit is an
    already-observed failure mode on this project (see the /ladder OVR
    sanity check) — and a wrong season result is much harder to notice
    later than a wrong OVR, because it silently moves the standings and the
    playoff seeding. Typed-by-hand numbers are just as worth a second look
    before they land.

    Every one of the seven stats is editable for either player through the
    select menu, whether it arrived from a screenshot (pre-filled, correct
    the wrong one) or not (blank, type them in). Same widgets, same code
    path, so the two routes can't drift apart.
    """

    def __init__(self, season: dict, match: dict, left: dict, right: dict,
                 left_stats: dict, right_stats: dict, lang: str = 'en',
                 source: str = 'screenshot'):
        super().__init__(timeout=600)
        self.season = season
        self.match = match
        self.left = left
        self.right = right
        self.left_stats = left_stats
        self.right_stats = right_stats
        self.lang = lang
        self.source = source

        options = []
        for side, player in (('left', left), ('right', right)):
            for page_key, _fields in STAT_PAGES:
                options.append(discord.SelectOption(
                    label=f"{player['ign']} — {i18n.t(f'neuroseason.match.page_{page_key}', lang)}"[:100],
                    value=f"{side}:{page_key}",
                    description=i18n.t(f'neuroseason.match.page_{page_key}_desc', lang)[:100],
                ))
        edit_select = Select(
            placeholder=i18n.t('neuroseason.match.edit_select_placeholder', lang)[:150],
            options=options, row=0)
        edit_select.callback = self._on_edit_select
        self.add_item(edit_select)

        confirm = Button(label=i18n.t('neuroseason.match.confirm', lang),
                         style=discord.ButtonStyle.success, row=1)
        confirm.callback = self._on_confirm
        self.add_item(confirm)

        cancel = Button(label=i18n.t('neuroseason.match.cancel', lang),
                        style=discord.ButtonStyle.danger, row=1)
        cancel.callback = self._on_cancel
        self.add_item(cancel)

    def stats_for(self, side: str) -> dict:
        return self.left_stats if side == 'left' else self.right_stats

    def player_for(self, side: str) -> dict:
        return self.left if side == 'left' else self.right

    def build_embed(self) -> discord.Embed:
        lang = self.lang
        embed = discord.Embed(
            title=i18n.t('neuroseason.match.review_title', lang,
                         num=self.match['match_num'], name=self.season['name']),
            description=i18n.t('neuroseason.match.review_desc', lang,
                               left=self.left['ign'], lpts=_fmt(self.left_stats.get('points')),
                               right=self.right['ign'], rpts=_fmt(self.right_stats.get('points'))),
            color=discord.Color.orange())
        for _page_key, fields in STAT_PAGES:
            for field in fields:
                if field == 'points':
                    continue          # already the headline in the description
                embed.add_field(
                    name=_stat_label(field, lang),
                    value=f"{_fmt(self.left_stats.get(field))} — {_fmt(self.right_stats.get(field))}",
                    inline=True)
        footer_key = ('neuroseason.match.review_footer' if self.source == 'screenshot'
                      else 'neuroseason.match.manual_footer')
        embed.set_footer(text=i18n.t(footer_key, lang))
        return embed

    def _sides(self) -> tuple[dict, dict]:
        """(home_stats, away_stats) — left/right describe the screenshot, the
        match row decides which of them is the home side."""
        if self.left['id'] == self.match['home_player_id']:
            return self.left_stats, self.right_stats
        return self.right_stats, self.left_stats

    async def _on_edit_select(self, interaction: discord.Interaction):
        # Component -> modal is legal; modal -> modal is not, which is why
        # editing goes through this menu rather than chaining out of a
        # previous modal's submission.
        side, page_key = interaction.data['values'][0].split(':', 1)
        await interaction.response.send_modal(SeasonStatEditModal(self, side, page_key))

    async def _on_confirm(self, interaction: discord.Interaction):
        await interaction.response.defer()
        lang = self.lang
        home_stats, away_stats = self._sides()

        if home_stats.get('points') is None or away_stats.get('points') is None:
            # Saving now would record 0-0 and hand someone a loss they didn't
            # play. The rest of the stats are genuinely optional — a score
            # is not.
            await interaction.followup.send(i18n.t('neuroseason.err.missing_points', lang))
            return

        if (self.match['stage'] == 'playoff'
                and int(home_stats['points']) == int(away_stats['points'])):
            # A tie can't advance a bracket — there's no next round to send
            # two players into, and inventing a tiebreak here would be the
            # bot deciding a playoff game.
            await interaction.followup.send(i18n.t('neuroseason.err.playoff_tie', lang))
            return

        await db.record_neuro_season_result(
            self.season['id'], self.match['match_num'], home_stats, away_stats)

        for child in self.children:
            child.disabled = True
        await interaction.followup.send(
            i18n.t('neuroseason.match.saved', lang, num=self.match['match_num'],
                   left=self.left['ign'], lpts=_fmt(self.left_stats.get('points')),
                   right=self.right['ign'], rpts=_fmt(self.right_stats.get('points'))))

        note = await advance_season(self.season['id'], lang)
        if note:
            await interaction.followup.send(note)
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=i18n.t('neuroseason.match.cancelled', self.lang), embed=None, view=self)
        self.stop()


def _fmt(v) -> str:
    return "—" if v is None else str(v)


class SeasonStatEditModal(Modal, title="Edit stats"):
    """
    One page of one player's stats. Pre-filled with whatever's currently
    held (from the screenshot, or from an earlier pass through this same
    modal), blank where nothing is known yet.

    A blank field means "not recorded" and stores None — deliberately not 0,
    which is a real and different value on this screen (0 turnovers is a
    clean game, not a missing stat).
    """

    def __init__(self, parent: SeasonMatchConfirmView, side: str, page_key: str):
        super().__init__()
        self.parent = parent
        self.side = side
        self.page_key = page_key
        lang = parent.lang
        player = parent.player_for(side)
        stats = parent.stats_for(side)

        self.fields = dict(STAT_PAGES)[page_key]
        self.title = i18n.t('neuroseason.match.edit_page_title', lang,
                            player=player['ign'],
                            page=i18n.t(f'neuroseason.match.page_{page_key}', lang))[:45]

        self.inputs: dict[str, TextInput] = {}
        for field in self.fields:
            _label_key, max_len = _STAT_META[field]
            current = stats.get(field)
            box = TextInput(default='' if current is None else str(current),
                            required=False, max_length=max_len)
            self.inputs[field] = box
            # discord.ui.Label caps at 45 characters — German runs longest,
            # so the slice is not decoration.
            self.add_item(discord.ui.Label(text=_stat_label(field, lang)[:45], component=box))

    async def on_submit(self, interaction: discord.Interaction):
        lang = self.parent.lang
        parsed: dict[str, int | None] = {}
        for field, box in self.inputs.items():
            raw = (box.value or '').strip()
            if not raw:
                parsed[field] = None
                continue
            try:
                parsed[field] = int(raw)
            except ValueError:
                await interaction.response.send_message(
                    i18n.t('neuroseason.err.bad_stat', lang,
                           stat=_stat_label(field, lang), value=raw[:20]),
                    ephemeral=True)
                return
            if parsed[field] < 0:
                await interaction.response.send_message(
                    i18n.t('neuroseason.err.negative_stat', lang,
                           stat=_stat_label(field, lang)),
                    ephemeral=True)
                return

        # Applied only once every field on the page parsed, so a typo in the
        # last box can't leave the first three half-applied.
        self.parent.stats_for(self.side).update(parsed)
        await interaction.response.edit_message(embed=self.parent.build_embed(), view=self.parent)

# ===========================================================================
# Stage advancement — playoffs generate themselves as rounds finish
# ===========================================================================

async def advance_season(season_id: int, lang: str = 'en') -> str | None:
    """
    Move the season on if the stage that just finished is actually finished.

    Called after every saved result, and safe to call at any other time: it
    only ever acts when there are zero pending matches in the current stage
    or round, so an early call is a no-op rather than an error. Returns a
    message worth announcing, or None if nothing changed.
    """
    season = await db.get_neuro_season(season_id)
    if season is None:
        return None

    if season['status'] == 'active':
        if await db.count_neuro_season_pending(season_id, stage='regular'):
            return None
        return await _open_playoffs(season, lang)

    if season['status'] == 'playoffs':
        current = await _current_playoff_round(season_id)
        if current is None or await db.count_neuro_season_pending(
                season_id, stage='playoff', round_name=current):
            return None
        return await _advance_playoff_round(season, current, lang)

    return None


async def _current_playoff_round(season_id: int) -> str | None:
    """The furthest round that has any matches — playoff rounds are created
    one at a time, so the latest one present is the one being played."""
    matches = await db.get_neuro_season_matches(season_id, stage='playoff')
    rounds = {m['round'] for m in matches}
    for rname in reversed(ROUND_ORDER):
        if rname in rounds:
            return rname
    return None


async def _open_playoffs(season: dict, lang: str) -> str:
    season_id = season['id']
    members = await db.get_neuro_season_members(season_id)
    matches = await db.get_neuro_season_matches(season_id, stage='regular')
    standings = compute_standings(members, matches)
    field = season['playoff_teams'] or playoff_field_size(len(members))
    seeded = compute_seeds(standings, matches, field)

    # Clear every seed first: a member who missed the field must not keep a
    # seed from an earlier call, and this function can legitimately run more
    # than once if a result is corrected after the regular season ends.
    for m in members:
        await db.set_neuro_season_member_seed(season_id, m['player_id'], None)
    for rows in seeded.values():
        for row in rows:
            await db.set_neuro_season_member_seed(season_id, row['player_id'], row['seed'])

    round_matches = build_playoff_round(seeded)
    for m in round_matches:
        m['stage'] = 'playoff'
    await db.insert_neuro_season_matches(season_id, round_matches)
    await db.update_neuro_season(season_id, status='playoffs')

    rname = round_matches[0]['round'] if round_matches else 'final'
    return i18n.t('neuroseason.playoffs.opened', lang, name=season['name'], field=field,
                  round=i18n.t(f'neuroseason.round.{rname}', lang), count=len(round_matches))


async def _advance_playoff_round(season: dict, current: str, lang: str) -> str | None:
    season_id = season['id']
    matches = await db.get_neuro_season_matches(season_id, stage='playoff', round_name=current)
    winners = [m['winner_player_id'] for m in matches if m['winner_player_id']]

    if current == 'final':
        champion = winners[0] if winners else None
        await db.update_neuro_season(
            season_id, status='complete', champion_player_id=champion,
            completed_at=datetime.datetime.now().isoformat(timespec='seconds'))
        row = await db.fetchone("SELECT ign FROM players WHERE id=?", (champion,))
        return i18n.t('neuroseason.playoffs.champion', lang, name=season['name'],
                      player=(row or {}).get('ign', '?'))

    members = {m['player_id']: m for m in await db.get_neuro_season_members(season_id)}
    remaining: dict[str, list[dict]] = {c: [] for c in CONFERENCES}
    for pid in winners:
        m = members.get(pid)
        if m is None:
            continue
        remaining.setdefault(m['conference'], []).append(
            {'player_id': pid, 'seed': m['seed'] or 99})

    next_matches = build_playoff_round(remaining)
    for m in next_matches:
        m['stage'] = 'playoff'
    if not next_matches:
        return None
    await db.insert_neuro_season_matches(season_id, next_matches)
    rname = next_matches[0]['round']
    return i18n.t('neuroseason.playoffs.next_round', lang, name=season['name'],
                  round=i18n.t(f'neuroseason.round.{rname}', lang), count=len(next_matches))
