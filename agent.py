"""
agent.py — Claude Haiku vision agent for ladder screenshot extraction.

Accepts up to 3 Discord attachment images, sends them to claude-haiku-4-5
and returns:
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
MODEL   = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a Madden Mobile league data extractor.
You will receive screenshots of a League vs League matchup screen.
The screen shows two teams side by side, each in its own header badge at the top.
The LEFT side is the opponent team.
The RIGHT side is OUR team (NeuroPerverse or another Neuro league).

Extract ALL of the following and return ONLY valid JSON with this exact structure:
{
  "opponent_league_name": "OpponentTeamName",
  "event_type": "E1",
  "our_rank": 45,
  "opponents": [
    {"name": "PlayerName", "total_ovr": 7200, "def_ovr": 245}
  ],
  "our_players": [
    {"real_ign": "PlayerName", "total_ovr": 7143, "off_ovr": 250, "def_ovr": 232}
  ]
}

Rules:
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


async def extract_ladder_from_screenshots(attachment_urls: list[str]) -> dict:
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

        content.append({
            "type": "text",
            "text": (
                f"These are {len(images)} screenshot(s) of a Madden Mobile "
                "League vs League matchup. Extract both the opponent players "
                "(left side) and our players (right side) as JSON."
            )
        })

        payload = {
            "model":      MODEL,
            "max_tokens": 1500,
            "system":     SYSTEM_PROMPT,
            "messages":   [{"role": "user", "content": content}],
        }

        async with session.post(API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(f"Haiku API error {resp.status}: {text[:300]}")
            data = await resp.json()

    # Parse response
    raw = data["content"][0]["text"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Haiku JSON parse error: {e}\nRaw: {raw[:500]}")
        raise ValueError(f"Could not parse Haiku response as JSON: {e}")

    if "opponents" not in result or "our_players" not in result:
        raise ValueError("Haiku response missing 'opponents' or 'our_players' keys.")

    result.setdefault("opponent_league_name", None)
    result.setdefault("event_type", None)
    result.setdefault("our_rank", None)

    logger.info(
        f"Haiku extracted {len(result['opponents'])} opponents "
        f"and {len(result['our_players'])} our players "
        f"(league={result['opponent_league_name']!r}, event_type={result['event_type']!r}, "
        f"our_rank={result['our_rank']!r})"
    )
    return result
