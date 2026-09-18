"""
status.py — Matchup status embed for Discord.
"""

import datetime
from zoneinfo import ZoneInfo
import discord
import db
import i18n

# Read from the db's teams table at import, not hardcoded — see
# db.load_league_names_sync. This was the last module still carrying its own
# copy of the league list; it listed NI long after that league was deleted.
TEAM_NAMES = db.load_league_names_sync()

_eastern        = ZoneInfo("America/New_York")
MAX_SCORE       = 24   # max score per drive
MATCHUP_SIZE    = 16   # players per team per matchup


def game_day() -> datetime.date:
    """Game day runs 1pm ET to 1pm ET. Before 1pm = yesterday's game still active."""
    now = datetime.datetime.now(tz=_eastern)
    if now.hour < 13:
        return (now - datetime.timedelta(days=1)).date()
    return now.date()


def _score_bar(score: float, max_score: float, width: int = 12) -> str:
    """Render a block bar representing a score."""
    filled = round((score / max_score) * width) if max_score > 0 else 0
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


async def get_status(team_id: str, lang: str = 'en') -> discord.Embed:
    """Return a rich embed showing today's matchup status."""
    today = game_day()
    data  = await db.get_matchup_status(team_id, today)
    ln    = TEAM_NAMES.get(team_id, team_id)

    us_score     = float(data['us_score']     or 0)
    them_score   = float(data['them_score']   or 0)
    us_drives    = int(data['us_drives']      or 0)
    their_drives = int(data['their_drives']   or 0)
    opp_ign      = data['opp_ign']            or "?"
    remaining     = data['players_remaining']
    our_defaults  = int(data['our_defaults']   or 0)
    opp_defaults  = int(data['opp_defaults']   or 0)
    # Real active roster size for our team — this is NOT always 16, so the
    # "played" count below must be derived from it rather than a hardcoded MATCHUP_SIZE.
    active_roster = int(data.get('active_roster') or 0)

    # Our drives left = players who haven't scored yet (remaining list)
    us_drives_left   = len(remaining)
    # Opponent drives played = their_drives; left = MATCHUP_SIZE - their_drives - opp_defaults
    # (opponent roster size is unknown to us, so MATCHUP_SIZE remains the assumption there)
    them_drives_left = max(0, MATCHUP_SIZE - their_drives - opp_defaults)

    # Max possible scores accounting for defaults (defaults score 0)
    us_max_possible   = us_score + (us_drives_left   * MAX_SCORE)
    them_max_possible = them_score + (them_drives_left * MAX_SCORE)

    # Clinch math: need to beat opponent's max possible
    pts_to_clinch = max(0.0, them_max_possible - us_score + 1)

    if pts_to_clinch == 0:
        ppd_str  = i18n.t('status.already_clinched', lang)
        feasible = True
    elif us_drives_left > 0:
        ppd      = pts_to_clinch / us_drives_left
        ppd_str  = i18n.t('status.ppd_needed', lang, ppd=f"{ppd:.1f}")
        feasible = ppd <= MAX_SCORE
    else:
        ppd_str  = i18n.t('status.no_drives_left', lang)
        feasible = us_score > them_max_possible

    diff = us_score - them_score

    # Color and outlook
    if diff > 0:
        color       = discord.Color.green()
        outlook_str = i18n.t('status.ahead', lang)
        diff_str    = f"+{diff:.0f}"
    elif diff < 0:
        color       = discord.Color.red()
        outlook_str = i18n.t('status.behind', lang)
        diff_str    = f"{diff:.0f}"
    else:
        color       = discord.Color.yellow()
        outlook_str = i18n.t('status.tied', lang)
        diff_str    = "±0"

    embed = discord.Embed(
        title=f"🏈  {ln}  vs  {opp_ign}",
        color=color,
    )

    # Score bars
    bar_max  = max(us_score, them_score, 1) * 1.25
    us_bar   = _score_bar(us_score,   bar_max)
    them_bar = _score_bar(them_score, bar_max)

    embed.add_field(
        name=i18n.t('status.field.scoreboard', lang),
        value=(
            f"`{ln:<18}` **{us_score:.0f}** `{us_bar}`\n"
            f"`{opp_ign:<18}` **{them_score:.0f}** `{them_bar}`"
        ),
        inline=False
    )

    # Drives
    us_played     = active_roster - us_drives_left - our_defaults
    them_played   = their_drives
    default_note  = ""
    if our_defaults or opp_defaults:
        parts = []
        if our_defaults:  parts.append(i18n.t('status.defaults_us', lang, n=our_defaults))
        if opp_defaults:  parts.append(i18n.t('status.defaults_them', lang, n=opp_defaults))
        default_note = f"\n⚠️ {', '.join(parts)}"

    embed.add_field(
        name=i18n.t('status.field.drives', lang),
        value=(
            f"{ln}: **{us_played}** played · **{us_drives_left}** left\n"
            f"{opp_ign}: **{them_played}** played · **{them_drives_left}** left"
            + default_note
        ),
        inline=True
    )

    # Outlook
    embed.add_field(
        name=i18n.t('status.field.outlook', lang),
        value=f"{outlook_str}\n**{diff_str}** pts",
        inline=True
    )

    # Clinch
    if pts_to_clinch == 0:
        clinch_icon  = "🏆"
        clinch_value = i18n.t('status.clinched_value', lang)
    elif not feasible:
        clinch_icon  = "💀"
        clinch_value = i18n.t('status.need_value', lang, pts=f"{pts_to_clinch:.0f}", ppd=ppd_str,
                               impossible=i18n.t('status.impossible_suffix', lang))
    else:
        clinch_icon  = "🎯"
        clinch_value = i18n.t('status.need_value', lang, pts=f"{pts_to_clinch:.0f}", ppd=ppd_str, impossible="")

    embed.add_field(
        name=f"{clinch_icon} {i18n.t('status.field.to_clinch', lang)}",
        value=clinch_value,
        inline=True
    )

    # Players remaining
    if not remaining:
        remaining_str = i18n.t('status.all_scored', lang)
    else:
        remaining_str = " · ".join(f"`{p}`" for p in remaining)

    embed.add_field(
        name=i18n.t('status.field.remaining', lang, left=us_drives_left, total=active_roster - our_defaults),
        value=remaining_str or "—",
        inline=False
    )

    # Progress bar
    active_players = active_roster - our_defaults
    played_count   = active_players - us_drives_left
    bar_width      = 16
    filled         = round((played_count / active_players) * bar_width) if active_players else bar_width
    prog_bar       = "▓" * filled + "░" * (bar_width - filled)
    embed.set_footer(text=i18n.t('status.footer', lang, bar=prog_bar, played=played_count, total=active_players, today=today))

    return embed