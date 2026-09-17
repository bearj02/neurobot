"""
newday.py — New-day logic.

Runs at 1pm ET daily (and can be triggered manually with !newday).
Creates a blank matchup_day placeholder row for each team so /status
works immediately at the start of a new game day.
"""

import datetime
import db
from logger_config import global_logger as logger

TEAM_IDS = ['NP', 'ND', 'NI', 'NA', 'NR', 'NC', 'NT', 'NX']


async def newday():
    """
    Prepare all teams for a new game day.
    Creates a blank matchup_day row for today if one doesn't already exist.
    Idempotent — safe to run more than once.
    """
    today = datetime.date.today()
    for tid in TEAM_IDS:
        await db.new_day(tid, today)
        logger.info(f"New day initialised for {tid} on {today}")
    logger.info("newday complete")