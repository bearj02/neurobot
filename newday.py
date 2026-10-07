"""
newday.py — New-day logic.

Runs at 1pm ET daily (and can be triggered manually with /newday).
Creates a blank matchup_day placeholder row for each team so /status
works immediately at the start of a new game day.
"""

import datetime
from zoneinfo import ZoneInfo
import db
from logger_config import global_logger as logger

_eastern = ZoneInfo("America/New_York")


def eastern_today() -> datetime.date:
    """
    Today's calendar date in Eastern time, regardless of the host's clock.

    This used to be datetime.date.today(), i.e. the *server's* local date,
    while everything else here (game_day(), the 1pm ET schedule) runs on
    Eastern. The hosts are not in Eastern — bot-hosting.net is European — so
    near midnight the placeholder row could land on a different date than
    the one /status and /matchup then look up.

    Deliberately the calendar date, not game_day(): the scheduled run fires
    at 13:00 ET and game_day() flips at that same instant, so a tick landing
    a hair early would read as yesterday.
    """
    return datetime.datetime.now(tz=_eastern).date()


async def newday() -> dict:
    """
    Prepare all teams for a new game day.
    Creates a blank matchup_day row for today if one doesn't already exist.
    Idempotent — safe to run more than once.

    Teams come from the `teams` table, never a hardcoded list. This used to
    be a module-level TEAM_IDS constant, which broke for real when NI was
    deleted: matchup_day.team_id is a foreign key to teams.id, so inserting
    a placeholder for a league that no longer exists raises
    IntegrityError("FOREIGN KEY constraint failed"). Note that INSERT OR
    IGNORE does *not* swallow that — its conflict resolution covers
    UNIQUE/NOT NULL/CHECK, not foreign keys.

    Returns {'date', 'ok', 'failed'} (team id lists) so callers can say what
    actually happened. Both callers used to report success unconditionally —
    /newday replied "✅ New day initialised" and the scheduler logged
    "complete" even when every insert had failed or there were no teams.
    """
    today = eastern_today()
    teams = await db.list_teams()
    if not teams:
        logger.error("newday: no teams found in the teams table — nothing to initialise")
        return {'date': today, 'ok': [], 'failed': []}

    ok, failed = [], []
    for tid in teams:
        # Per-team isolation: the original loop let one bad team abort the
        # whole run, so the leagues after it silently got no placeholder row
        # (NI failing third meant five leagues were skipped entirely).
        try:
            await db.new_day(tid, today)
            ok.append(tid)
            logger.info(f"New day initialised for {tid} on {today}")
        except Exception as e:
            failed.append(tid)
            logger.error(f"newday: failed to initialise {tid} on {today}: {e}", exc_info=True)

    if failed:
        logger.error(f"newday complete with {len(failed)} failure(s): {', '.join(failed)}")
    else:
        logger.info(f"newday complete for {len(teams)} teams")
    return {'date': today, 'ok': ok, 'failed': failed}
