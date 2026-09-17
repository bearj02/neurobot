"""
utils.py — Shared helpers (no gspread dependency in the MySQL version).
"""

import asyncio
import aiohttp
from logger_config import global_logger as logger


async def safe_db_call(coro):
    """
    Await a DB coroutine with basic retry/backoff.
    Keeps the same call-site pattern as the old safe_gspread_call.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await coro
        except Exception as e:
            wait_time = 2 ** attempt
            logger.warning(
                f"DB call failed (attempt {attempt+1}/{max_retries}): {e}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
            else:
                raise
