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

    **Only correct for the 13:00 ET scheduled run**, which is the one caller
    that passes it. See game_day() below for why.
    """
    return datetime.datetime.now(tz=_eastern).date()


def game_day() -> datetime.date:
    """
    The current game day — the same 1pm-ET-to-1pm-ET window every other part
    of the bot means by "today" (optimized_bot.game_day, status.game_day).

    This is what a *manual* /newday has to use, and using eastern_today()
    instead was a real bug. The two disagree for thirteen hours out of every
    twenty-four: between 00:00 and 13:00 ET, eastern_today() has already
    rolled over to the new calendar date while game_day() is still on the
    previous one, because the game day doesn't start until 1pm.

    So an admin running /newday at, say, 9am ET got a placeholder row
    written for *tomorrow's* game day, while /status, /ladder, /score and
    /matchup all went on reading the current one — and found nothing there.
    The row was created exactly as asked; it was just filed under a date
    nothing else was looking at, which reads from the outside as "/newday
    doesn't do anything".

    The scheduled run keeps eastern_today() deliberately: it fires at
    13:00 ET, the same instant game_day() flips, so a tick landing a
    fraction early would read as yesterday and re-initialise the day that
    just ended. At 13:00 ET the calendar date and the game day are the same
    date anyway, so passing it explicitly is both correct and safe.
    """
    now = datetime.datetime.now(tz=_eastern)
    if now.hour < 13:
        return (now - datetime.timedelta(days=1)).date()
    return now.date()


async def newday(for_date: datetime.date | None = None) -> dict:
    """
    Prepare all teams for a new game day.
    Creates a blank matchup_day row for today if one doesn't already exist.
    Idempotent — safe to run more than once.

    for_date: which day to initialise. Defaults to game_day(), i.e. the day
    the rest of the bot currently considers "today". The 13:00 ET scheduler
    passes eastern_today() instead — see game_day() above for why those are
    different functions and why each caller wants the one it uses.

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
    today = for_date or game_day()
    teams = await db.list_teams()
    if not teams:
        logger.error("newday: no teams found in the teams table — nothing to initialise")
        return {'date': today, 'ok': [], 'failed': []}
    logger.info(f"newday: initialising {len(teams)} team(s) for {today}: {', '.join(teams)}")

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
