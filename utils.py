"""
utils.py — Shared helpers.
"""

import asyncio
from logger_config import global_logger as logger

# Discord's hard limit on a single embed field's `value`. Exceeding it on
# *any* field makes Discord reject the ENTIRE message with a 400
# (`Invalid Form Body ... Must be 1024 or fewer in length`) — not a partial
# send, not a truncation. So it has to be handled before add_field is ever
# called, never caught afterwards.
EMBED_FIELD_LIMIT = 1024

# A markdown code fence costs 8 characters ("```\n" + body + "\n```") and
# they count toward EMBED_FIELD_LIMIT like any others. Budgeting the full
# 1024 for the body and then wrapping it is how both build_final_embed and
# /test came to send fields of 1028-1107 characters, which Discord rejects
# outright. Anything fencing a field value budgets FENCED_FIELD_LIMIT.
CODE_FENCE_OVERHEAD = len("```\n") + len("\n```")
FENCED_FIELD_LIMIT = EMBED_FIELD_LIMIT - CODE_FENCE_OVERHEAD


def truncate_cell(text, width: int) -> str:
    """
    Clamp one column of a monospace table to `width`, with '..' marking a cut.

    Two jobs. The obvious one is alignment: the table formats use `:<18`,
    which pads but never truncates, so a longer name silently shifts every
    column after it on that row. The load-bearing one is that it bounds a
    row's length, and therefore the field's — opponent names come from a
    free-text modal with max_length=1600 for the whole CSV, so without this a
    single name could blow EMBED_FIELD_LIMIT on its own and no amount of
    chunking would help (a chunker can only split *between* lines).
    """
    text = str(text if text not in (None, '') else '-')
    return text if len(text) <= width else text[:max(1, width - 2)] + '..'


def chunk_lines_to_fit(lines: list[str], max_chars: int = EMBED_FIELD_LIMIT,
                       max_chunks: int = 5) -> list[str]:
    """
    Splits a list of lines into chunks, each chunk's newline-joined string
    at most max_chars long. Discord enforces a hard 1024-character limit
    per embed field value — a field built by joining one line per item
    (e.g. one per open siege node, or one per ladder slot) can silently
    exceed that once there are enough items, and Discord rejects the ENTIRE
    message with an HTTPException (not a partial/truncated send) if any
    field value goes over, so this has to be handled before ever calling
    embed.add_field, not caught after the fact.

    Caps at max_chunks (default 5) so this can't separately blow past
    Discord's 25-fields-per-embed limit on an extreme siege with dozens of
    open nodes — the last chunk gets a "...and N more" note (counting
    actual dropped lines, not dropped chunks) instead of producing a 6th,
    7th, etc. field.

    **Pass a reduced max_chars if the caller wraps the chunk in anything.**
    A code fence costs 8 characters ("```\\n" + chunk + "\\n```") and those
    count toward the field limit too — budgeting the full 1024 here and then
    wrapping is exactly how build_final_embed came to send 1024-plus fields.

    Lives here rather than in siege.py (where it was written) so ladder_flow
    can use the same proven implementation instead of a second copy that
    would drift. siege.py re-exports it under its old private name.
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
