"""
newday.py — New-day logic.

Runs at 1pm ET daily (and can be triggered manually with /newday).
Creates a blank matchup_day placeholder row for each team so /status
works immediately at the start of a new game day.
"""

import datetime
import db
from logger_config import global_logger as logger


async def newday():
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
    """
    today = datetime.date.today()
    teams = await db.list_teams()
    if not teams:
        logger.error("newday: no teams found in the teams table — nothing to initialise")
        return

    failed = []
    for tid in teams:
        # Per-team isolation: the original loop let one bad team abort the
        # whole run, so the leagues after it silently got no placeholder row
        # (NI failing third meant five leagues were skipped entirely).
        try:
            await db.new_day(tid, today)
            logger.info(f"New day initialised for {tid} on {today}")
        except Exception as e:
            failed.append(tid)
            logger.error(f"newday: failed to initialise {tid} on {today}: {e}", exc_info=True)

    if failed:
        logger.error(f"newday complete with {len(failed)} failure(s): {', '.join(failed)}")
    else:
        logger.info(f"newday complete for {len(teams)} teams")
