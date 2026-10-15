"""
agent.py — Claude Haiku vision agents for screenshot extraction.

Two unrelated screens, two extractors:

  extract_ladder_from_screenshots     — League vs League matchup screen (/ladder)
  extract_season_match_from_screenshot — Head to Head Arena "Game Stats"
                                         post-game screen (/seasonmatch)

The ladder extractor accepts up to 3 Discord attachment images, sends them to
Claude Haiku 5.5 and returns:
  - opponent_league_name: the opposing team/league's name, if visible
  - event_type:           the division (E1/E2/E3/HOF/Gold-), if visible
  - our_rank:             our team's power rank, if visible
  - opponents:   [{name, total_ovr, def_ovr}, ...]
  - our_players: [{real_ign, total_ovr, off_ovr, def_ovr}, ...]
"""

import os
import json
import base64
import aiohttp
from logger_config import global_logger as logger

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
# Haiku 5.5, not 4.5 — measured, not assumed. On a real 16-v-16 ladder
# (three overlapping screenshots, 2868x1320) graded field by field against a
# hand-read key, Haiku 4.5 got 24 of 35 rows wrong: it caps images at 1568px
# on the long edge, so these arrived at ~55% scale and it swapped 3/8/9 and
# 5/6 all over (the "3 read as 8" OVR reports), and when a player wasn't on
# the roster enum it repeated a roster name instead of declining. Haiku 5.5
# took ~2.2x the image tokens (it sees the screenshots near native size),
# read every OVR but one correctly, declined every off-roster row with null,
# and still costs less per call.
MODEL   = "claude-haiku-5-5"

# Haiku 5.5 thinks by default, and thinking counts toward max_tokens: at the
# old 3000 cap the first live run stopped mid-JSON. Low effort was what was
# measured above; it is plenty for transcription.
EFFORT  = "low"

SYSTEM_PROMPT = """You are a Madden Mobile league data extractor.
You will receive screenshots of a League vs League matchup screen.
The screen shows two teams side by side, each in its own header badge at the top.
The LEFT side is the opponent team.
The RIGHT side is OUR team (NeuroPerverse or another Neuro league).

Each side has exactly 16 players, listed top to bottom. Give every row its
"slot": its screen position, 1 for the topmost row through 16 for the bottom.
{
  "opponent_league_name": "OpponentTeamName",
  "event_type": "E1",
  "our_rank": 45,
  "opponents": [
    {"slot": 1, "name": "PlayerName", "total_ovr": 7200, "def_ovr": 245},
    {"slot": 2, "name": null, "total_ovr": null, "def_ovr": null},
    "... through slot 16"
  ],
  "our_players": [
    {"slot": 1, "real_ign": "PlayerName", "total_ovr": 7143, "off_ovr": 250, "def_ovr": 232},
    "... through slot 16"
  ]
}

Rules:
- slot is the screen position, not a ranking. Never sort or rearrange.
- A row you cannot read is still listed under its own slot number, with null
  fields. Never renumber the rows below it to close the gap - that turns one
  unreadable row into every later row being attributed to the wrong player.
- Each slot number from 1 to 16 appears exactly once on each side.
- opponent_league_name: the opposing team's name, shown in its header badge
  (the same place a name like "seams suspicious" or "Dynasty 1" would appear).
  Use null if not visible.
- event_type: the division shown in OUR team's header badge (e.g. "Elite I",
  "Elite II", "Elite III", "Hall of Fame", "Gold"). Convert what you see to
  this short code: "Elite I" -> "E1", "Elite II" -> "E2", "Elite III" -> "E3",
  "Hall of Fame" -> "HOF", "Gold" -> "Gold-". Use null if not visible or if it
  doesn't match one of these.
- our_rank: OUR team's power rank number, often shown as "#45" or similar next
  to our team's name in its header badge. Use null if not visible.
- Extract exactly what you see — do not guess or infer missing values
- Use null for any value you cannot read clearly
- Player names must be exactly as shown, including capitalisation and special characters
- total_ovr, off_ovr, def_ovr, our_rank are integers
- If a value is cut off or unreadable, use null
- Return ONLY the JSON object, no other text"""


async def _fetch_image_b64(session: aiohttp.ClientSession, url: str) -> tuple[str, str]:
    """Download an image and return (base64_data, media_type)."""
    async with session.get(url) as resp:
        data = await resp.read()
        content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
        return base64.b64encode(data).decode("utf-8"), content_type


# A whole ladder response is ~1500 tokens at most, so logging it in full costs
# a few KB — and the alternative is what hid the bug this helper exists for:
# the old `raw[:500]` cut the dump off mid-row, so there was no way to tell a
# model that emitted one bad character from one that ran out of max_tokens.
# The cap is only here so a pathological response can't flood the rotating
# file; when it bites, the log says so rather than quietly shortening.
_RAW_LOG_LIMIT = 20000


def _log_api_response(kind: str, data: dict, attempt: int = 1) -> str | None:
    """
    Log what the API actually returned, before anything tries to parse it.

    `stop_reason` is the field that distinguishes the two ways an extraction
    can fail with a JSONDecodeError: "max_tokens" means the response is a
    valid prefix that simply stopped (raise max_tokens), "end_turn" means the
    model finished and the JSON it wrote is genuinely malformed (a prompt or
    decoding-constraint problem). Without it, both look identical in the log.

    Returns the stop_reason so a caller can act on it.
    """
    usage = data.get("usage") or {}
    stop_reason = data.get("stop_reason")
    logger.info(
        "Haiku %s response (attempt %d): id=%s model=%s stop_reason=%s "
        "input_tokens=%s output_tokens=%s",
        kind, attempt, data.get("id"), data.get("model"), stop_reason,
        usage.get("input_tokens"), usage.get("output_tokens"),
    )
    return stop_reason


def _error_context(raw: str, pos: int, window: int = 100) -> str:
    """
    The text either side of the offset json.loads objected to, with a caret
    under the exact character.

    json's own message ("line 8 column 14 (char 243)") names a position in a
    blob that wasn't being logged in full, so it pointed at nothing. This
    puts the offending character on screen next to the complaint.

    The window is flattened onto one line — a real newline inside it would
    push the caret line away from the text it points at, which is the one
    thing this function exists to get right.
    """
    start = max(0, pos - window)
    end   = min(len(raw), pos + window)
    before = raw[start:pos].replace("\n", "\\n")
    after  = raw[pos:end].replace("\n", "\\n")
    return f"{before}{after}\n{' ' * len(before)}^ (char {pos})"


def _log_parse_failure(kind: str, raw: str, err: json.JSONDecodeError,
                       stop_reason: str | None, attempt: int = 1) -> None:
    """Everything needed to tell why an extraction failed, in one place."""
    body = raw if len(raw) <= _RAW_LOG_LIMIT else (
        raw[:_RAW_LOG_LIMIT] + f"\n...[truncated by the logger at {_RAW_LOG_LIMIT} chars; "
                               f"the response was {len(raw)}]"
    )
    logger.error(
        "Haiku %s JSON parse error (attempt %d): %s\n"
        "stop_reason=%s raw_len=%d\n"
        "--- context ---\n%s\n"
        "--- full raw response ---\n%s\n"
        "--- end raw response ---",
        kind, attempt, err, stop_reason, len(raw),
        _error_context(raw, err.pos), body,
    )


def _parse_error_message(kind: str, err: json.JSONDecodeError,
                         stop_reason: str | None) -> str:
    """
    The message the caller surfaces in Discord.

    "max_tokens" and a genuinely malformed response both arrive as a
    JSONDecodeError, and they need opposite responses from whoever is
    looking at it: one means raise the cap (or send fewer screenshots), the
    other means retry or fall back to entering the ladder by hand. Saying
    which is which here saves a trip to the log.
    """
    if stop_reason == "max_tokens":
        return (f"Haiku's {kind} response was cut off by the token limit "
                f"(stop_reason=max_tokens) — it never finished writing the JSON.")
    return (f"Could not parse Haiku's {kind} response as JSON: {err}. "
            f"The full response is in the bot log.")


def _response_text(data: dict) -> str:
    """
    The model's text, with a markdown fence stripped if one is there.

    Joins every text block rather than reaching straight into
    `data["content"][0]["text"]`, which raised an IndexError (not a
    ValueError) on a response whose content list came back empty — a shape
    the caller's `except ValueError` had no chance of catching.

    The fence-stripping stays even though structured outputs make a fence
    very unlikely: it costs nothing, and it is still the right behaviour if
    the schema is ever removed.
    """
    blocks = data.get("content") or []
    text = "".join(
        b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


async def _post_and_parse(session: aiohttp.ClientSession, payload: dict,
                          headers: dict, kind: str, attempts: int = 2) -> dict:
    """
    Send one extraction request and return the parsed JSON, retrying once if
    the reply doesn't parse.

    Two layers, because they fail differently:

    - `output_config.format` on the payload constrains decoding to the
      schema, so the model *cannot* emit a missing quote or an unclosed
      brace. This is the actual fix for the failure that prompted it (a
      `/ladder` run where Haiku wrote `{"name": JosoPrime"` — one dropped
      character that killed the whole command).
    - The retry covers what a schema can't: a response with no text block at
      all, or anything else transient on the API side. It is deliberately a
      plain re-send of the identical request, not a repair attempt on the
      broken text — guessing where a quote belongs is exactly the kind of
      silent wrong answer this project avoids elsewhere.

    A `max_tokens` stop is never retried: an identical request will be cut
    off at the identical place, so a second call only burns time and money.
    Raise `max_tokens` (or send fewer screenshots) instead.
    """
    last_err: tuple[json.JSONDecodeError, str | None] | None = None

    for attempt in range(1, attempts + 1):
        async with session.post(API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Haiku API error {resp.status}: {text[:300]}")
            data = await resp.json()

        stop_reason = _log_api_response(kind, data, attempt)
        raw = _response_text(data)

        # The whole response at DEBUG, so a good extraction can be compared
        # against a bad one. LOG_LEVEL=DEBUG on the panel turns this on.
        logger.debug("Haiku %s raw response (%d chars): %s", kind, len(raw), raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            _log_parse_failure(kind, raw, e, stop_reason, attempt)
            last_err = (e, stop_reason)
            if stop_reason == "max_tokens" or attempt == attempts:
                break
            logger.warning(
                "Haiku %s attempt %d did not parse — re-sending the same request once",
                kind, attempt,
            )

    err, stop_reason = last_err
    raise ValueError(_parse_error_message(kind, err, stop_reason))


# ---------------------------------------------------------------------------
# Output schemas
#
# `output_config.format` constrains the model's decoding to these, which is
# what makes a syntactically invalid response impossible rather than merely
# unlikely. Schema rules worth knowing before editing one (they are checked
# server-side, and a violation is a 400, not a warning):
#
#   - every object needs `additionalProperties: False` and a `required` list
#     naming *all* of its properties;
#   - "optional" is expressed as a nullable type, not by leaving a key out of
#     `required` — which suits this prompt exactly, since it already asks for
#     null on anything not legible in the screenshot;
#   - numeric/length constraints (minimum, maxLength, ...) are not supported;
#   - **at most 16 union-typed properties per schema** (a nullable type is an
#     `anyOf`, so it counts). Counted per *schema property*, not per array
#     element, so a nullable field inside an array item counts once;
#   - **an unpublished cap on compiled grammar size.** Repeating a sub-schema
#     multiplies the grammar; an array's item schema compiles once. See
#     _side_schema for the two 400s this cost.
# ---------------------------------------------------------------------------

# The server-side cap on union-typed properties in one schema. A test counts
# both schemas against it.
MAX_UNION_PARAMS = 16

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _schema_object(properties: dict) -> dict:
    """An object schema with every key required and nothing else allowed."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# A ladder is exactly this many slots per side, and the screen order is the
# ladder order. Mirrors ladder_flow.MATCHUP_SIZE, which isn't imported here to
# keep discord out of this module's import graph — a test pins the two equal.
LADDER_SLOTS = 16

# Characters that survive the model fine but break the CSV the admin edits in
# step 2: that format is one `name, total, def` per line, split on commas, so
# a comma inside a name silently shifts the two numbers. Quotes and
# apostrophes are stripped alongside it because a name is round-tripped
# through a text modal and back, and a stray quote there is noise at best.
_CSV_HOSTILE = str.maketrans({",": " ", '"': "", "'": "", "`": "", "\n": " ", "\r": " "})


def sanitize_name(value):
    """
    Make an extracted name safe to put in the step-2 CSV and read back.

    Returns None unchanged — null is the model declining a row, and turning
    that into "" would make an unread row look like a read one.
    """
    if value is None:
        return None
    cleaned = " ".join(str(value).translate(_CSV_HOSTILE).split())
    return cleaned or None


def _side_schema(item_props: dict) -> dict:
    """One side of the ladder: an array of rows, each carrying its own slot.

    **This shape is the third attempt, and the first two each cost a live
    400**, so the constraints are worth knowing before changing it:

    - A bare array of rows (the original) can't be length-constrained —
      `minItems`/`maxItems` are rejected — and nothing tied a row to its
      position, which is how one run returned 21 rows and another 14
      opponents against 17 of ours, and how a skipped row would shift every
      row below it onto the wrong player.
    - Fixed keys `slot_1`..`slot_16` fixed the count, but with nullable
      fields that was 115 union-typed properties against a cap of 16; with
      the unions removed it still failed, as "compiled grammar is too large":
      32 inline copies of a row schema (each carrying the roster enum) is
      32 copies in the grammar.

    Here the row schema exists once, and `slot` is an enum of 1..16, so a
    row's position is something the model states rather than something its
    array index implies. `_rows_to_slots` places rows by that number: a
    missing row is an empty slot *in place*, never a shift, and a duplicate
    slot keeps the first row rather than overwriting it.
    """
    slot = {"type": "integer", "enum": list(range(1, LADDER_SLOTS + 1))}
    return {"type": "array",
            "items": _schema_object(dict({"slot": slot}, **item_props))}


def _rows_to_slots(rows, fields: tuple, side: str) -> list[dict]:
    """The model's rows back to the ordered 16-list callers expect, placed by
    each row's own `slot` — never by array position. Every slot is present;
    one the model didn't return is all-None."""
    out = {}
    dupes = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        slot = row.get("slot")
        if not isinstance(slot, int) or not 1 <= slot <= LADDER_SLOTS:
            continue
        if slot in out:
            dupes += 1          # first wins: a later duplicate is the guess
            continue
        out[slot] = {f: row.get(f) for f in fields}
    missing = LADDER_SLOTS - len(out)
    if dupes or missing:
        logger.warning(f"Haiku {side}: {missing} slot(s) not returned, "
                       f"{dupes} duplicate slot row(s) dropped")
    return [dict(out.get(i) or {f: None for f in fields}, _slot=i)
            for i in range(1, LADDER_SLOTS + 1)]


_OPP_FIELDS = ("name", "total_ovr", "def_ovr")
_OUR_FIELDS = ("real_ign", "total_ovr", "off_ovr", "def_ovr")


def build_ladder_schema(roster: list[str] | None = None) -> dict:
    """
    The ladder output schema, with `our_players[].real_ign` bound to this
    league's active roster when one is supplied.

    **This is the mechanism that makes our-side names correct, and it
    replaces reconciling them afterwards.** `enum` is enforced during
    decoding, so a name that is not on the roster is not a thing the model
    can emit — there is nothing to match, nothing to fuzzy-match, and
    nothing to clean up. Extracting free text and then reconciling it
    against the roster was the wrong shape: it made every downstream step
    responsible for a guarantee the request should have carried.

    `null` stays allowed. That is not a hole in the constraint — it is the
    difference between "this row is someone not on the roster" (now
    impossible) and "I could not read this row" (always possible, and the
    honest answer). Forcing a non-null pick would make an unreadable row
    into a confidently wrong one, which is strictly worse: a dropped row is
    visible in the count, a wrong row is not.

    **The enum narrows the candidates; it does not finish the job.**
    `real_ign` is explicitly not unique, so two active players in one league
    can share one, and the enum carries each distinct spelling once. Whether
    a returned name identifies exactly one player is a question only the
    caller can answer, and 0 or >1 both mean "ask the admin" — see
    db.get_players_by_real_ign and /ladder's resolution loop.

    With no roster the field falls back to free text, so the extractor still
    works for a league with no active players. Callers that have a roster
    should always pass it.
    """
    if roster:
        # sorted+set: the request body must be byte-stable across calls for
        # the server-side schema cache to hit. Collapsing a shared real_ign
        # to one entry is correct here — a duplicate enum value would mean
        # nothing to the model — and the ambiguity it hides is resolved by
        # the caller, not swallowed.
        names = sorted({n for n in roster if n})
    else:
        names = []
    real_ign = ({"anyOf": [{"type": "string", "enum": names}, {"type": "null"}]}
                if names else _NULLABLE_STR)

    return _schema_object({
        "opponent_league_name": _NULLABLE_STR,
        # The enum is the same conversion table the system prompt spells out,
        # now enforced rather than requested — db writes read event_type directly.
        "event_type": {"anyOf": [
            {"type": "string", "enum": ["E1", "E2", "E3", "HOF", "Gold-"]},
            {"type": "null"},
        ]},
        "our_rank": _NULLABLE_INT,
        # Opponent names are genuinely free text — they belong to the other
        # league and this bot has no roster for them.
        "opponents": _side_schema({
            "name":      _NULLABLE_STR,
            "total_ovr": _NULLABLE_INT,
            "def_ovr":   _NULLABLE_INT,
        }),
        "our_players": _side_schema({
            "real_ign":  real_ign,
            "total_ovr": _NULLABLE_INT,
            "off_ovr":   _NULLABLE_INT,
            "def_ovr":   _NULLABLE_INT,
        }),
    })


# The unbound form, for a caller with no roster to hand.
LADDER_OUTPUT_SCHEMA = build_ladder_schema()


async def extract_ladder_from_screenshots(attachment_urls: list[str],
                                          roster: list[str] | None = None) -> dict:
    """
    Send up to 3 screenshot URLs to Haiku and extract ladder data.

    Returns:
        {
            "opponent_league_name": str | None,
            "event_type":           str | None,  # E1/E2/E3/HOF/Gold-
            "our_rank":             int | None,
            "opponents":   [{name, total_ovr, def_ovr}, ...],
            "our_players": [{real_ign, total_ovr, off_ovr, def_ovr}, ...]
        }

    Raises:
        ValueError if the API call fails or response can't be parsed.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")

    if not attachment_urls:
        raise ValueError("No screenshots provided.")

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }

    async with aiohttp.ClientSession() as session:
        # Download all images concurrently
        import asyncio
        images = await asyncio.gather(*[
            _fetch_image_b64(session, url) for url in attachment_urls[:3]
        ])

        # Build content blocks — one image per screenshot
        content = []
        for b64, media_type in images:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": media_type,
                    "data":       b64,
                }
            })

        prompt = (
            f"These are {len(images)} screenshot(s) of a Madden Mobile "
            "League vs League matchup. Extract both the opponent players "
            "(left side) and our players (right side) as JSON."
        )
        prompt += (
            f"\n\nEach side has exactly {LADDER_SLOTS} players. Give each row "
            f"its slot, 1 through {LADDER_SLOTS}, by its position on screen "
            "from top to bottom. The order is the matchup order and carries "
            "meaning: slot 3 on the left faces slot 3 on the right. Do not "
            "sort, rank or rearrange them. If a row is not legible, still "
            "list it under its own slot with null fields — never renumber the "
            "rows below it, because that silently repairs one unreadable row "
            "into every later row being wrong."
        )
        if roster:
            # The schema already makes anything off this list undecodable.
            # Naming it here as well is what lets the model *read* a smudged
            # row as the roster entry it resembles, instead of abstaining —
            # the constraint prevents wrong answers, the list enables right
            # ones.
            names = sorted({n for n in roster if n})
            prompt += (
                "\n\nEvery player on the RIGHT side is one of these "
                f"{len(names)} league members, listed exactly as their name "
                "is spelled:\n"
                + "\n".join(f"- {n}" for n in names)
                + "\n\nFor each right-side slot, give the entry from that list "
                  "it matches. Use each name at most once. If a row is not "
                  "legible enough to tell which member it is, use null for "
                  "that slot's real_ign rather than guessing."
            )
        if len(images) > 1:
            prompt += ("\n\nThe screenshots may overlap and show some of the "
                       "same rows. They are views of one list — put each "
                       "player in the slot matching their position in it, not "
                       "once per screenshot.")
        content.append({"type": "text", "text": prompt})

        payload = {
            "model":      MODEL,
            # 16000. Thinking shares this budget with the JSON: a real full
            # 16-v-16 ladder on Haiku 5.5 at low effort came to 2964-3666
            # output tokens, and the same request at the old 3000 cap was cut
            # off mid-JSON. A max_tokens stop is the one parse failure
            # _post_and_parse deliberately won't retry, because an identical
            # request is cut off in the identical place.
            #
            # max_tokens is a ceiling, not a charge — raising it costs
            # nothing unless the tokens are actually generated.
            "max_tokens": 16000,
            "system":     SYSTEM_PROMPT,
            "output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema",
                           "schema": build_ladder_schema(roster)},
            },
            "messages":   [{"role": "user", "content": content}],
        }

        result = await _post_and_parse(session, payload, headers, "ladder")

    if "opponents" not in result or "our_players" not in result:
        raise ValueError("Haiku response missing 'opponents' or 'our_players' keys.")

    result.setdefault("opponent_league_name", None)
    result.setdefault("event_type", None)
    result.setdefault("our_rank", None)
    result["opponent_league_name"] = sanitize_name(result["opponent_league_name"])

    # Rows back to ordered 16-lists by their own slot number, so the index a
    # caller reads is the position on screen. Every slot is present whether
    # or not the model returned it; an unread row is Nones, in place.
    result["opponents"]   = _rows_to_slots(result["opponents"], _OPP_FIELDS, "opponents")
    result["our_players"] = _rows_to_slots(result["our_players"], _OUR_FIELDS, "our_players")
    for o in result["opponents"]:
        o["name"] = sanitize_name(o.get("name"))

    read_opp = sum(1 for o in result["opponents"] if o.get("name"))
    read_our = sum(1 for p in result["our_players"] if p.get("real_ign"))
    logger.info(
        f"Haiku read {read_opp}/{LADDER_SLOTS} opponent slots and "
        f"{read_our}/{LADDER_SLOTS} of our slots "
        f"(league={result['opponent_league_name']!r}, event_type={result['event_type']!r}, "
        f"our_rank={result['our_rank']!r}, roster_bound={bool(roster)})"
    )
    return result


SEASON_MATCH_SYSTEM_PROMPT = """You are a Madden Mobile match result extractor.
You will receive a screenshot of the "Head to Head Arena" post-game screen,
on its "GAME STATS" tab.

That screen shows two columns of numbers, one per player. The LEFT column
belongs to one player and the RIGHT column to the other. Each team's final
score sits at the top of its own column, next to its NFL team logo. Below the
score is a row per stat: Rushing, Passing, Kick Return, Touchdown, Turnovers,
Field Goal. A green check mark may appear beside whichever column leads a
given row — it is decoration, never a value, and must be ignored.

Return ONLY valid JSON with this exact structure:
{
  "left":  {"points": 24, "rushing_yds": 19, "passing_yds": 203,
            "kick_return_yds": 51, "touchdowns": 3, "turnovers": 0,
            "field_goals": 0},
  "right": {"points": 6, "rushing_yds": 0, "passing_yds": 52,
            "kick_return_yds": 33, "touchdowns": 1, "turnovers": 2,
            "field_goals": 0}
}

Rules:
- "left" is the left-hand column, "right" is the right-hand column, exactly as
  they appear on screen. Do not reorder them by score, by winner, or by
  anything else.
- points is the big score beside each team logo at the top, NOT the sum of
  anything below it.
- Strip units: "203 YDs" is 203.
- Every value is an integer. A value you cannot read clearly is null — never a
  guess, and never 0 as a stand-in for unreadable.
- A stat row that is genuinely absent from this screenshot is null for both
  sides.
- Return ONLY the JSON object, no other text."""

_SEASON_STAT_KEYS = ("points", "rushing_yds", "passing_yds", "kick_return_yds",
                     "touchdowns", "turnovers", "field_goals")

# Every stat is nullable on purpose, matching the prompt: a 0 standing in for
# "couldn't read it" would put a fabricated stat into the season record, and
# 0 is a real value on this screen (0 turnovers is a clean game).
_SEASON_SIDE_SCHEMA = _schema_object({k: _NULLABLE_INT for k in _SEASON_STAT_KEYS})

SEASON_MATCH_OUTPUT_SCHEMA = _schema_object({
    "left":  _SEASON_SIDE_SCHEMA,
    "right": _SEASON_SIDE_SCHEMA,
})


async def extract_season_match_from_screenshot(attachment_urls: list[str]) -> dict:
    """
    Read a Head to Head Arena "GAME STATS" screen and return both sides' stats.

    Returns {"left": {...}, "right": {...}}, each carrying every key in
    _SEASON_STAT_KEYS with an int or None value.

    Which real player is "left" and which is "right" is NOT knowable from the
    screenshot — it shows NFL team logos, not player names — so that mapping
    is the caller's job (/seasonmatch takes left_player and right_player for
    exactly this reason).

    Raises ValueError if the API call fails or the response can't be parsed.
    """
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in environment variables.")
    if not attachment_urls:
        raise ValueError("No screenshot provided.")

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }

    async with aiohttp.ClientSession() as session:
        b64, media_type = await _fetch_image_b64(session, attachment_urls[0])
        payload = {
            "model":      MODEL,
            # 8000, not 700: thinking counts toward it (see EFFORT).
            "max_tokens": 8000,
            "system":     SEASON_MATCH_SYSTEM_PROMPT,
            "output_config": {
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": SEASON_MATCH_OUTPUT_SCHEMA},
            },
            "messages":   [{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text",
                 "text": "Extract both columns of this Head to Head Arena game stats screen as JSON."},
            ]}],
        }
        result = await _post_and_parse(session, payload, headers, "season-match")

    if "left" not in result or "right" not in result:
        raise ValueError("Haiku response missing 'left' or 'right' keys.")

    # Normalise both sides to the full key set, so a caller can read any stat
    # without checking whether the model happened to include it.
    out = {}
    for side in ("left", "right"):
        vals = result.get(side) or {}
        out[side] = {k: _coerce_int(vals.get(k)) for k in _SEASON_STAT_KEYS}

    logger.info(f"Haiku extracted season match: left={out['left']['points']} "
                f"right={out['right']['points']}")
    return out


def _coerce_int(v):
    """'203 YDs' -> 203, '' -> None, None -> None. The prompt asks for bare
    integers, but a stray unit or a numeric string shouldn't break a match
    report."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = "".join(c for c in str(v) if c.isdigit() or c == "-")
    try:
        return int(digits)
    except ValueError:
        return None
