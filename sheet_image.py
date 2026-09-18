"""
sheet_image.py — Render rank tables and ladder tables as PNG images using Pillow.
Sends as a Discord file attachment so they render correctly on all screen sizes.
"""

import io
import math
import os
import discord
from PIL import Image, ImageDraw, ImageFont
from logger_config import global_logger as logger
import db

# Read from the db's teams table at import, not hardcoded — see
# db.load_league_names_sync. Callers rendering an *archived* season should
# pass league_name= explicitly, since that season's league list is its own
# (see send_rank_image).
LEAGUE_NAMES = db.load_league_names_sync()

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Font files are bundled in a fonts/ folder right next to this file, and
# checked FIRST — before any system-wide path — so rendering never depends
# on the host OS happening to have a particular font package installed.
# This matters concretely: DejaVu fonts being present is an assumption this
# code was making, not something ever verified on the actual hosting
# environment, and a *different* font package (Liberation) introduced for
# the /show_ladder poster styles turned out not to be there at all — every
# piece of bold text in those styles silently collapsed to PIL's fixed
# ~10px placeholder font, because ImageFont.load_default() ignores whatever
# size was requested. Bundling removes this class of bug entirely: the
# correct font ships with the bot's own files, so it doesn't matter what
# fonts (if any) the server's OS image includes.
#
# To install: upload the .ttf files this delivery includes into a `fonts/`
# folder in the same directory as sheet_image.py on the server (i.e.
# alongside optimized_bot.py, db.py, etc.) — same File Manager upload
# process as any other file. No shell/package-manager access needed.

_FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

def _font_paths(bundled_filename, system_path):
    """Bundled copy first, then the system path some hosts may happen to
    have it at, in that order — _load_font tries each until one works."""
    return [os.path.join(_FONTS_DIR, bundled_filename), system_path]

FONT_PATH   = _font_paths('DejaVuSansMono.ttf',      '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')
FONT_BOLD   = _font_paths('DejaVuSansMono-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf')
# Falls back to the regular (non-italic) weight before giving up entirely —
# in production, this specific oblique file failed to load while its
# regular/bold siblings loaded fine, for reasons not fully explainable
# remotely (byte-identical to the source, correct size on upload). Rather
# than have one single font file be a point of failure for readable text
# size, degrade to "right size, not italic" instead of "PIL's tiny default".
FONT_ITALIC = _font_paths('DejaVuSansMono-Oblique.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf') + FONT_PATH
FONT_SIZE     = 18
TITLE_SIZE    = 44
SUBTITLE_SIZE = 20

def _load_font(path_or_paths, size):
    """
    Load a TrueType font at the given size, trying each candidate path in
    order (see _font_paths — bundled copy first, system path second). Only
    if every candidate fails does this fall back to PIL's built-in default
    font — which silently ignores whatever size was requested (always
    renders at a fixed ~10px) unless explicitly told otherwise. That
    fallback previously had no visible signal at all, which is exactly how
    an entire style's bold text collapsed to near-illegible size on an
    environment missing one specific font file. Now logs loudly if it's
    ever actually reached (so a missing font becomes a visible server-log
    issue, not a silent rendering bug) and asks the fallback for the
    requested size too, on the PIL versions that support it.
    """
    paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    logger.error(f"No usable font found among {paths} — falling back to PIL's default font at size {size}. "
                 f"This will look visibly wrong (default font ignores requested size on most PIL versions) "
                 f"until the correct font file is installed on this system.")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Older PIL versions don't accept a size argument here at all.
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

BG          = (30,  31,  34)
PANEL       = (43,  45,  49)
HEADER_BG   = (88,  101, 242)
HEADER_FG   = (255, 255, 255)
ROW_ALT     = (38,  40,  44)
ROW_FG      = (220, 221, 222)
SEP_COLOR   = (58,  60,  65)
TITLE_FG    = (255, 255, 255)
SUBTITLE_FG = (170, 173, 180)
ACCENT      = (88,  101, 242)

PAD_X  = 20
PAD_Y  = 10
RADIUS = 8


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------

def _wrap_text(text, font, max_width, measure_fn):
    """Greedily wrap text into lines that each fit within max_width."""
    words = text.split(' ')
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or measure_fn(candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _cell_text_x(col_x, col_w, align, text_w):
    """
    Left edge to draw a table cell's text at, for its column's alignment.
    'L' left-pads, 'C' centres within the column, anything else right-aligns
    (the pre-existing convention — 'R' is what every caller passes).
    """
    if align == 'L':
        return col_x + PAD_X
    if align == 'C':
        return col_x + (col_w - text_w) // 2
    return col_x + col_w - PAD_X - text_w


def _render_table(title, headers, rows, aligns=None, subtitle=None):
    """
    Render a table as a PNG and return a BytesIO buffer.
    subtitle: optional secondary line rendered smaller and italicized below
    the main title (e.g. "Ladder (snapshot 2026-07-20)").
    aligns: per-column 'L'/'C'/'R' — see _cell_text_x.
    """
    font        = _load_font(FONT_PATH,   FONT_SIZE)
    font_bold   = _load_font(FONT_BOLD,   FONT_SIZE)
    font_title  = _load_font(FONT_BOLD,   TITLE_SIZE)
    font_sub    = _load_font(FONT_ITALIC, SUBTITLE_SIZE)

    if aligns is None:
        aligns = ['L'] * len(headers)

    dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    def tw(text, fnt=None):
        return int(dummy.textlength(text, font=fnt or font))

    col_widths = [
        max(tw(headers[j], font_bold),
            max((tw(row[j]) for row in rows), default=0))
        + PAD_X * 2
        for j in range(len(headers))
    ]

    row_h   = FONT_SIZE + PAD_Y * 2
    table_w = sum(col_widths)
    img_w   = table_w + PAD_X * 2

    # Wrap the title (and subtitle, if given) to fit within the table's own
    # width — a long title never widens the image itself, it just takes up
    # more vertical space instead.
    title_lines = _wrap_text(title, font_title, img_w - PAD_X * 2, tw)
    title_text  = "\n".join(title_lines)
    title_bbox  = dummy.multiline_textbbox((0, 0), title_text, font=font_title)
    title_block_h = (title_bbox[3] - title_bbox[1])

    subtitle_text = None
    subtitle_block_h = 0
    subtitle_gap = 0
    if subtitle:
        subtitle_lines = _wrap_text(subtitle, font_sub, img_w - PAD_X * 2, tw)
        subtitle_text  = "\n".join(subtitle_lines)
        subtitle_bbox  = dummy.multiline_textbbox((0, 0), subtitle_text, font=font_sub)
        subtitle_block_h = (subtitle_bbox[3] - subtitle_bbox[1])
        subtitle_gap = 4

    title_h = title_block_h + subtitle_gap + subtitle_block_h + PAD_Y * 2 + 4
    img_h   = title_h + row_h * (1 + len(rows)) + PAD_Y * 2

    img  = Image.new('RGB', (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)

    # Panel
    draw.rounded_rectangle(
        [PAD_X - 4, title_h - 4, img_w - PAD_X + 4, img_h - PAD_Y],
        radius=RADIUS, fill=PANEL
    )

    # Title (+ optional smaller, italicized subtitle beneath it)
    draw.multiline_text((PAD_X, PAD_Y), title_text, font=font_title, fill=TITLE_FG)
    if subtitle_text:
        draw.multiline_text(
            (PAD_X, PAD_Y + title_block_h + subtitle_gap),
            subtitle_text, font=font_sub, fill=SUBTITLE_FG
        )
    draw.line([(PAD_X, title_h - 2), (img_w - PAD_X, title_h - 2)],
              fill=ACCENT, width=2)

    # Header row
    draw.rectangle([PAD_X - 4, title_h,
                    img_w - PAD_X + 4, title_h + row_h], fill=HEADER_BG)
    x = PAD_X
    for j, (hdr, cw) in enumerate(zip(headers, col_widths)):
        tx = _cell_text_x(x, cw, aligns[j], tw(hdr, font_bold))
        draw.text((tx, title_h + PAD_Y), hdr, font=font_bold, fill=HEADER_FG)
        x += cw

    # Data rows
    for i, row in enumerate(rows):
        y    = title_h + row_h + i * row_h
        fill = ROW_ALT if i % 2 == 0 else PANEL
        draw.rectangle([PAD_X - 4, y, img_w - PAD_X + 4, y + row_h], fill=fill)
        x = PAD_X
        for j, (cell, cw) in enumerate(zip(row, col_widths)):
            tx = _cell_text_x(x, cw, aligns[j], tw(cell))
            draw.text((tx, y + PAD_Y), cell, font=font, fill=ROW_FG)
            x += cw
        draw.line([(PAD_X, y + row_h), (img_w - PAD_X, y + row_h)],
                  fill=SEP_COLOR, width=1)

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Rank table
# ---------------------------------------------------------------------------

async def send_rank_image(ctx, team_id, conn=None, season_label=None, league_name=None, **kwargs):
    """Fetch roster from DB, render as PNG, send as file.
    conn: optional archive connection (see db.get_archive_conn) for /legacy.
    season_label: optional suffix for the title, e.g. "(2026 Season)".
    league_name: display name override. /legacy passes that season's own name
      for the league, since the module-level LEAGUE_NAMES holds today's
      leagues and a past season's may no longer be among them."""
    try:
        players = await db.get_rank_table(team_id, conn=conn)
        if not players:
            await ctx.send(f"No active roster data found for `{team_id}`.")
            return

        league  = league_name or LEAGUE_NAMES.get(team_id, team_id)
        headers = ['#', 'Player', 'Pwr Rank', 'OVR', 'Games', 'Yearly', '7-Day', 'Kobes']
        aligns  = ['R', 'L',      'R',        'R',   'R',     'R',      'R',     'R']
        rows = []
        for i, r in enumerate(players, 1):
            rows.append([
                str(i),
                str(r['ign'] or ''),
                f"{r['pwr_rank']:.2f}"   if r.get('pwr_rank')   else '--',
                str(r.get('total_ovr')   or '--'),
                str(r.get('games')       or '--'),
                f"{r['avg_yearly']:.2f}" if r.get('avg_yearly') else '--',
                f"{r['avg_7day']:.2f}"   if r.get('avg_7day')   else '--',
                str(r.get('kobes')       or '--'),
            ])

        title = f"{league} - Power Rankings"
        if season_label:
            title += f"  {season_label}"
        buf = _render_table(title, headers, rows, aligns)
        await ctx.send(file=discord.File(buf, filename=f"{team_id}_rank.png"))
        logger.info(f"Rank image sent for {team_id}")

    except Exception as e:
        logger.error(f"Error in send_rank_image for {team_id}: {e}", exc_info=True)
        await ctx.send(f"Error generating rank table: {e}")


async def send_stats_image(ctx, team_id, include_inactive=False, conn=None, season_label=None,
                           league_name=None):
    """
    League stats as a PNG — stat categories across the top, one row per
    player underneath (same layout as /rank), plus a final League Avg row
    summarizing the whole league.
    conn/season_label/league_name: see send_rank_image.
    """
    try:
        stats = await db.get_league_stats(team_id, include_inactive=include_inactive, conn=conn)
        if not stats:
            await ctx.send(f"No stats found for `{team_id}`.")
            return

        league  = league_name or LEAGUE_NAMES.get(team_id, team_id)
        headers = ['#', 'Player', 'Games', 'Yearly', '30-Day', '7-Day', '3-Day',
                   'HOF', 'E1', 'E2', 'E3', 'Gold-', 'Kobes', '3+TD%', '2PT%', 'Fumbles']
        aligns  = ['R', 'L', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R', 'R']

        def fmt(v, pct=False):
            if v is None:
                return '--'
            return f"{v:.1%}" if pct else f"{v:.2f}"

        rows = []
        for i, p in enumerate(stats['players'], 1):
            rows.append([
                str(i),
                str(p['ign'] or ''),
                str(p.get('games') or '--'),
                fmt(p.get('avg_yearly')),
                fmt(p.get('avg_30day')),
                fmt(p.get('avg_7day')),
                fmt(p.get('avg_3day')),
                fmt(p.get('hof_avg')),
                fmt(p.get('e1_avg')),
                fmt(p.get('e2_avg')),
                fmt(p.get('e3_avg')),
                fmt(p.get('gold_avg')),
                str(p.get('kobes') or '--'),
                fmt(p.get('three_td_pct'), pct=True),
                fmt(p.get('two_pt_pct'), pct=True),
                str(p.get('fumbles') or '--'),
            ])

        # League-average summary row at the bottom
        rows.append([
            '', 'LEAGUE AVG',
            str(stats['games']),
            fmt(stats['avg_yearly']),
            fmt(stats['avg_30day']),
            fmt(stats['avg_7day']),
            fmt(stats['avg_3day']),
            fmt(stats['hof_avg']),
            fmt(stats['e1_avg']),
            fmt(stats['e2_avg']),
            fmt(stats['e3_avg']),
            fmt(stats['gold_avg']),
            str(stats['kobes']),
            fmt(stats['three_td_pct'], pct=True),
            fmt(stats['two_pt_pct'], pct=True),
            str(stats['fumbles']),
        ])

        scope = "  (incl. inactive)" if include_inactive else ""
        title = f"{league} — League Stats{scope}"
        if season_label:
            title += f"  {season_label}"
        buf = _render_table(title, headers, rows, aligns)
        await ctx.send(file=discord.File(buf, filename=f"{team_id}_stats.png"))
        logger.info(f"Stats image sent for {team_id}")

    except Exception as e:
        logger.error(f"Error in send_stats_image for {team_id}: {e}", exc_info=True)
        await ctx.send(f"Error generating stats table: {e}")


# ---------------------------------------------------------------------------
# Ladder table
# ---------------------------------------------------------------------------

def render_ladder_image(title, rows, subtitle=None, style='classic',
                         our_team_name=None, opponent_name=None, division=None):
    """
    Render a ladder matchup table as a PNG and return a BytesIO buffer.
    style: 'classic' (original data-dense table), 'neon' (bold hexagon-badge
    poster, Orbitron), 'clean' (minimal modern cards), 'scoreboard'
    (bold flat-color broadcast, Anton), 'tactical' (military/esports, Black
    Ops One), 'varsity' (collegiate athletics, Graduate), 'arcade' (retro
    8-bit, Press Start 2P), 'street' (urban/graffiti, Bungee Inline),
    'carnival' (playful, Honk), 'gridiron' (football field, Black Ops One),
    'blueprint' (technical schematic, Share Tech Mono), 'newsprint' (light
    broadsheet sports page, Graduate masthead — the only light-background
    style), or 'terminal' (CRT green phosphor, VT323).
    our_team_name/opponent_name/division: only used by the non-classic
    styles, for their two-team header — safe to omit for 'classic'.
    """
    if style == 'neon':
        return _render_ladder_neon(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'clean':
        return _render_ladder_clean(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'scoreboard':
        return _render_ladder_scoreboard(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'tactical':
        return _render_ladder_tactical(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'varsity':
        return _render_ladder_varsity(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'arcade':
        return _render_ladder_arcade(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'street':
        return _render_ladder_street(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'carnival':
        return _render_ladder_carnival(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'gridiron':
        return _render_ladder_gridiron(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'blueprint':
        return _render_ladder_blueprint(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'newsprint':
        return _render_ladder_newsprint(rows, our_team_name, opponent_name, division, subtitle)
    elif style == 'terminal':
        return _render_ladder_terminal(rows, our_team_name, opponent_name, division, subtitle)
    elif style in _LADDER_THEMES:
        return _render_ladder_themed(rows, our_team_name, opponent_name, division, subtitle,
                                     _LADDER_THEMES[style])
    return _render_ladder_classic(title, rows, subtitle=subtitle)


def _render_ladder_classic(title, rows, subtitle=None):
    """The original data-dense table style — every column, no team header art."""
    # Both name columns are centred ('C'), matching every poster style — the
    # numeric columns stay right-aligned so their digits still line up.
    headers = ['#', 'Our Player', 'Ladder Rank', 'Off OVR', 'Opponent', 'Opp TOT', 'Opp DEF', '+/-', 'Result']
    aligns  = ['R', 'C',          'R',            'R',       'C',        'R',        'R',       'R',   'L']

    data = []
    for r in rows:
        result_str = ''
        if r.get('result'):
            pts = f" {r.get('our_pts', 0)}-{r.get('opp_pts', 0)}" \
                  if r.get('our_pts') is not None else ''
            result_str = f"{r['result']}{pts}"

        our_off  = r.get('our_off_ovr')
        opp_def  = r.get('opp_def_ovr') or r.get('def_ovr')
        opp_tot  = r.get('our_total_ovr') or r.get('our_total_ovr_live')  # stored as our matchup slot OVR
        ldr_rank = r.get('ladder_rank')

        if our_off and opp_def:
            diff = our_off - opp_def
            pm   = f"+{diff}" if diff > 0 else str(diff)
        else:
            pm = '--'

        data.append([
            str(r['slot']),
            r.get('our_ign')   or '--',
            f"{ldr_rank:.1f}"  if ldr_rank  else '--',
            str(our_off)       if our_off   else '--',
            r.get('opp_ign')   or '--',
            str(opp_tot)       if opp_tot   else '--',
            str(opp_def)       if opp_def   else '--',
            pm,
            result_str         or '--',
        ])

    return _render_table(title, headers, data, aligns, subtitle=subtitle)


def _ladder_row_fields(r):
    """
    Shared field extraction for every poster-style renderer.

    our_stat is our player's **offensive** OVR. It used to prefer
    ladder_rank when that was available (which it is for any league with
    ladder weights configured — i.e. in practice, all of them), so what the
    ladder actually showed next to our players was a weighted rank score,
    not an OVR at all. It's off_ovr unconditionally now, which is also what
    makes the middle diff column check out by eye: our_stat - opp_stat is
    exactly the diff. classic keeps its own separate Ladder Rank column, so
    that number is still available there.

    Note that `our_total_ovr` on a ladder row is NOT ours despite the name —
    it's the *opponent's* team overall (see ladder_flow's opponent CSV
    mapping, which writes opp['total_ovr'] into that column). Nothing here
    should use it for our side.

    diff is off_ovr - opp_def_ovr, pre-formatted with a sign, for the middle
    column between the two matchup sides.
    """
    our_stat = r.get('our_off_ovr')
    opp_stat = r.get('opp_def_ovr') or r.get('def_ovr')
    result_str = None
    if r.get('result'):
        pts = f" {r.get('our_pts', 0)}-{r.get('opp_pts', 0)}" if r.get('our_pts') is not None else ''
        result_str = f"{r['result']}{pts}"

    diff = diff_val = None
    if our_stat and opp_stat:
        diff_val = int(our_stat) - int(opp_stat)
        diff = f"+{diff_val}" if diff_val > 0 else str(diff_val)

    return {
        'slot': r['slot'],
        'our_ign': r.get('our_ign') or '—',
        'our_stat': f"{our_stat:.1f}" if isinstance(our_stat, float) else (str(our_stat) if our_stat else None),
        'opp_ign': r.get('opp_ign') or '—',
        'opp_stat': str(opp_stat) if opp_stat else None,
        'result': result_str,
        'diff': diff,
        'diff_val': diff_val,
    }


# Centre gutter reserved for the diff column in the poster styles — the name
# columns stop this far short of the midline on each side.
_DIFF_GUTTER = 46


def _draw_diff(draw, f, mid, cy, font, pos_fill, neg_fill, zero_fill=None, stroke=0):
    """
    Draw a row's OVR difference (off OVR - opponent def OVR) centred on the
    midline, coloured by sign. Nothing is drawn when either side's OVR is
    missing, rather than a misleading 0.
    stroke: see _draw_centered_name — faux-bolds faces with no bold weight.
    """
    if not f['diff']:
        return
    if f['diff_val'] > 0:
        fill = pos_fill
    elif f['diff_val'] < 0:
        fill = neg_fill
    else:
        fill = zero_fill or pos_fill
    draw.text((mid, cy), f['diff'], font=font, fill=fill, anchor="mm",
              stroke_width=stroke, stroke_fill=fill if stroke else None)


def _chevron_points(x0, x1, y0, y1, point_dir, notch_ratio=0.45):
    notch = int((y1 - y0) * notch_ratio)
    if point_dir == 1:
        return [(x0, y0), (x1 - notch, y0), (x1, (y0 + y1) // 2), (x1 - notch, y1), (x0, y1)]
    return [(x0 + notch, y0), (x1, y0), (x1, y1), (x0 + notch, y1), (x0, (y0 + y1) // 2)]


def _gradient_fill_polygon(img, points, color1, color2):
    """Fill an arbitrary polygon with a horizontal linear gradient."""
    W, H = img.size
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    xs = [p[0] for p in points]
    x0, x1 = min(xs), max(xs)
    grad = Image.new('RGB', (W, H), color1)
    gdraw = ImageDraw.Draw(grad)
    span = max(x1 - x0, 1)
    for x in range(x0, x1 + 1):
        t = (x - x0) / span
        c = tuple(int(color1[i] + (color2[i] - color1[i]) * t) for i in range(3))
        gdraw.line([(x, 0), (x, H)], fill=c)
    img.paste(grad, (0, 0), mask)


# Two periods rather than a single "…" character: the bundled display fonts
# (Press Start 2P especially) only cover basic Latin, so an ellipsis glyph
# would render as a missing-character box in exactly the styles that need
# truncation most, being the widest per character.
_TRUNCATE_SUFFIX = '..'


def _truncate_to_width(draw, text, font, max_width):
    """Shorten text (with a trailing '..') until it fits max_width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    cut = text
    while cut and draw.textlength(cut + _TRUNCATE_SUFFIX, font=font) > max_width:
        cut = cut[:-1]
    return (cut + _TRUNCATE_SUFFIX) if cut else text[:1]


def _draw_centered_name(draw, text, stat, cx, cy, col_x0, col_x1, fitter,
                        name_fill, stat_font, stat_fill, stat_side='right', gap=12,
                        stroke=0):
    """
    Draw a player name horizontally centred on cx within the column
    [col_x0, col_x1], with its stat immediately beside it on stat_side.

    Every ladder style centres its names (an explicit request) rather than
    flush-aligning them against the slot badge, so the geometry lives here
    once instead of in each renderer. What differs per style is only the
    font, the colours and the column bounds — all passed in. `fitter` is a
    callable taking a max width and returning a font, which keeps each
    style's own font constant and max/min sizes inside that style's own
    source (where the font-choice tests can still see them).

    The fit budget is measured from the centre outward, not from the full
    column width: a centred name grows in *both* directions, so it has to
    fit between cx and whichever edge is nearer, after subtracting the
    stat's width and gap on the side the stat sits on. That's what stops a
    long name from sliding under the slot badge or across the centre
    divider.
    """
    stat_w = int(draw.textlength(stat, font=stat_font)) if stat else 0
    room_stat_side = (col_x1 - cx) if stat_side == 'right' else (cx - col_x0)
    room_far_side = (cx - col_x0) if stat_side == 'right' else (col_x1 - cx)
    half = min(room_far_side, room_stat_side - (stat_w + gap if stat else 0))
    budget = max(int(half) * 2, 20)
    font = fitter(budget)
    # _fit_text stops shrinking at its floor size and returns it even if the
    # text still doesn't fit, so a name long enough to exceed the column at
    # that floor gets truncated rather than centred *through* the slot badge
    # on one side and the centre divider on the other.
    text = _truncate_to_width(draw, text, font, budget)
    # stroke faux-bolds a face that ships only a Regular weight (Share Tech
    # Mono, VT323, DotGothic16 all do) by outlining each glyph in its own
    # colour. Cheaper and far more predictable than hunting for a bold file
    # that doesn't exist, and 1px is enough at these sizes.
    draw.text((cx, cy), text, font=font, fill=name_fill, anchor="mm",
              stroke_width=stroke, stroke_fill=name_fill if stroke else None)
    if stat:
        half_w = draw.textlength(text, font=font) / 2
        if stat_side == 'right':
            draw.text((cx + half_w + gap, cy), stat, font=stat_font, fill=stat_fill, anchor="lm")
        else:
            draw.text((cx - half_w - gap, cy), stat, font=stat_font, fill=stat_fill, anchor="rm")
    # Returns the text as drawn, not as passed in — it may have been
    # truncated, which a caller measuring the result needs to know.
    return font, text


def _fit_text(draw, text, font_path, max_size, min_size, max_width):
    """Shrink font size until text fits max_width, down to a floor size."""
    size = max_size
    while size > min_size:
        f = _load_font(font_path, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 1
    return _load_font(font_path, min_size)


_POSTER_FONT_BOLD   = _font_paths('DejaVuSansCondensed-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf') + _font_paths('DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
_POSTER_FONT_REG    = _font_paths('DejaVuSansCondensed.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf') + _font_paths('DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
# Same regular-weight fallback reasoning as FONT_ITALIC above.
_POSTER_FONT_ITALIC = _font_paths('DejaVuSansCondensed-Oblique.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Oblique.ttf') + _POSTER_FONT_REG

# Display fonts for the tactical/varsity/arcade styles. These are custom
# fonts with no standard OS package/system path (unlike DejaVu), so there's
# only the bundled copy — but each still falls back to the reliable DejaVu
# Condensed Bold (not PIL's default) if that bundled file is ever missing,
# so a missing display font degrades to "looks like a different style"
# rather than "illegibly tiny".
_FONT_BLACK_OPS   = [os.path.join(_FONTS_DIR, 'BlackOpsOne-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_GRADUATE    = [os.path.join(_FONTS_DIR, 'Graduate-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_PRESS_START = [os.path.join(_FONTS_DIR, 'PressStart2P-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_BUNGEE = [os.path.join(_FONTS_DIR, 'BungeeInline-Regular.ttf')] + _POSTER_FONT_BOLD

# Second batch of display fonts, one per style that previously had none
# (see the style table in CLAUDE.md). All static weights on purpose — the
# variable-font handling Honk and Nabla need is fragile enough that it's
# worth avoiding wherever a static file exists, and Orbitron shipped both.
_FONT_ANTON          = [os.path.join(_FONTS_DIR, 'Anton-Regular.ttf')] + _POSTER_FONT_BOLD
# Bebas Neue is bundled and unused: gridiron briefly used it, but sharing
# tactical's Black Ops One was preferred. Available for a future style.
_FONT_BEBAS          = [os.path.join(_FONTS_DIR, 'BebasNeue-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_ORBITRON       = [os.path.join(_FONTS_DIR, 'Orbitron-Bold.ttf')] + _POSTER_FONT_BOLD
_FONT_ORBITRON_BLACK = [os.path.join(_FONTS_DIR, 'Orbitron-Black.ttf')] + _FONT_ORBITRON
# These two fall back to the *monospace* family rather than the condensed
# bold every other display font falls back to: 'blueprint' and 'terminal'
# both depend on fixed-width columns lining up, so if the bundled file ever
# goes missing they need to degrade to another monospace face, not to a
# proportional one that would leave the layout ragged.
_FONT_SHARE_TECH     = [os.path.join(_FONTS_DIR, 'ShareTechMono-Regular.ttf')] + FONT_BOLD
_FONT_VT323          = [os.path.join(_FONTS_DIR, 'VT323-Regular.ttf')] + FONT_BOLD

# Third font batch, one face per themed style added on top of the originals.
# Cap-height ratios against the DejaVu baseline these sizes were tuned for
# were measured per family, not assumed — Wallpoet (0.80x), Syne Mono
# (0.87x) and DotGothic16 (1.13x) all need their own size scaling, which
# lives in each theme's own font sizes below.
_FONT_AUDIOWIDE      = [os.path.join(_FONTS_DIR, 'Audiowide-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_BITCOUNT       = [os.path.join(_FONTS_DIR, 'BitcountGridDouble-Bold.ttf')] + FONT_BOLD
_FONT_DOTGOTHIC      = [os.path.join(_FONTS_DIR, 'DotGothic16-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_KEANIA         = [os.path.join(_FONTS_DIR, 'KeaniaOne-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_NEWSREADER     = [os.path.join(_FONTS_DIR, 'Newsreader_24pt-Bold.ttf')] + _POSTER_FONT_BOLD
_FONT_NEWSREADER_IT  = [os.path.join(_FONTS_DIR, 'Newsreader_24pt-Italic.ttf')] + _POSTER_FONT_ITALIC
_FONT_NOVA_SQUARE    = [os.path.join(_FONTS_DIR, 'NovaSquare-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_SPECIAL_ELITE  = [os.path.join(_FONTS_DIR, 'SpecialElite-Regular.ttf')] + _POSTER_FONT_BOLD
_FONT_SYNE_MONO      = [os.path.join(_FONTS_DIR, 'SyneMono-Regular.ttf')] + FONT_PATH
_FONT_WALLPOET       = [os.path.join(_FONTS_DIR, 'Wallpoet-Regular.ttf')] + _POSTER_FONT_BOLD

# Honk and Nabla are variable fonts — their look depends on setting specific
# variation axes (Honk: Morph/Shadow: Nabla: Extrusion Depth/Edge Highlight),
# not just size. Both break down into illegible blocks below roughly
# 16-18px regardless of axis settings (confirmed by direct testing), so
# anywhere text might need to shrink below that (a long name, a crowded
# small badge) uses a reliable non-variable font instead — these two are
# reserved for titles/labels/rank badges that stay above that floor.
_FONT_HONK_PATH  = os.path.join(_FONTS_DIR, 'Honk-Regular-VariableFont_MORF,SHLN.ttf')
_FONT_NABLA_PATH = os.path.join(_FONTS_DIR, 'Nabla-Regular-VariableFont_EDPT,EHLT.ttf')
_VARIABLE_FONT_MIN_SAFE_SIZE = 16


def _load_variable_font(path, size, axes, fallback_paths):
    """
    Load a variable font at a specific axis setting, falling back to a
    reliable non-variable font (which doesn't support set_variation_by_axes
    at all) if the variable font file is missing or too old a PIL/Pillow
    version to support variation axes.
    """
    try:
        f = ImageFont.truetype(path, size)
        f.set_variation_by_axes(axes)
        return f
    except Exception as e:
        logger.error(f"Variable font not usable at {path} with axes {axes} ({e}) — "
                     f"falling back to a non-variable font at size {size}.")
        return _load_font(fallback_paths, size)


def _fit_variable_text(draw, text, path, axes, fallback_paths, max_size, min_size, max_width):
    """
    Like _fit_text, but for a variable font — never shrinks below
    _VARIABLE_FONT_MIN_SAFE_SIZE (where Honk/Nabla become illegible
    blocks); if the text still doesn't fit at that floor, falls back
    entirely to the reliable fallback font instead of shrinking further.
    """
    safe_min = max(min_size, _VARIABLE_FONT_MIN_SAFE_SIZE)
    size = max_size
    while size >= safe_min:
        f = _load_variable_font(path, size, axes, fallback_paths)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 1
    # Doesn't fit even at the variable font's safe floor — hand off to the
    # reliable fallback font instead of forcing the variable font smaller.
    return _fit_text(draw, text, fallback_paths, safe_min, min_size, max_width)


def _draw_text_glow(img, xy, text, fnt, fill, glow_color, anchor="mm", glow_radius=10, glow_alpha=140):
    """Draw text with a soft colored glow behind it. Mutates and returns img as RGB."""
    from PIL import ImageFilter
    glow_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow_layer).text(xy, text, font=fnt, fill=(*glow_color, glow_alpha), anchor=anchor)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(glow_radius))
    composited = Image.alpha_composite(img.convert('RGBA'), glow_layer).convert('RGB')
    img.paste(composited, (0, 0))
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def _radial_glow_layer(size, center, radius, color, max_alpha=70):
    """An RGBA layer with a soft radial glow, meant to be alpha_composited under content."""
    from PIL import ImageFilter
    layer = Image.new('RGBA', size, (0, 0, 0, 0))
    mask = Image.new('L', size, 0)
    ImageDraw.Draw(mask).ellipse(
        [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius], fill=max_alpha
    )
    mask = mask.filter(ImageFilter.GaussianBlur(radius // 2))
    solid = Image.new('RGBA', size, (*color, 255))
    layer.paste(solid, (0, 0), mask)
    return layer


def _vertical_gradient_bg(size, top_color, bottom_color):
    W, H = size
    img = Image.new('RGB', size, top_color)
    draw = ImageDraw.Draw(img)
    span = max(H, 1)
    for y in range(H):
        t = y / span
        c = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=c)
    return img


def _drop_shadow_rounded_rect(img, box, radius, blur=8, offset=(0, 5), alpha=90):
    """Paint a soft drop shadow behind where a rounded rect will be drawn. Mutates img."""
    from PIL import ImageFilter
    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]], radius=radius, fill=(0, 0, 0, alpha)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    composited = Image.alpha_composite(img.convert('RGBA'), shadow).convert('RGB')
    img.paste(composited, (0, 0))


def _gradient_fill_rounded_rect(img, box, radius, color1, color2, direction='v'):
    W, H = img.size
    x0, y0, x1, y1 = box
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    grad = Image.new('RGB', (W, H), color1)
    gdraw = ImageDraw.Draw(grad)
    if direction == 'v':
        span = max(y1 - y0, 1)
        for y in range(int(y0), int(y1) + 1):
            t = (y - y0) / span
            c = tuple(int(color1[i] + (color2[i] - color1[i]) * t) for i in range(3))
            gdraw.line([(x0, y), (x1, y)], fill=c)
    else:
        span = max(x1 - x0, 1)
        for x in range(int(x0), int(x1) + 1):
            t = (x - x0) / span
            c = tuple(int(color1[i] + (color2[i] - color1[i]) * t) for i in range(3))
            gdraw.line([(x, y0), (x, y1)], fill=c)
    img.paste(grad, (0, 0), mask)


def _draw_text_shadow(draw, xy, text, fnt, fill, shadow_color=(0, 0, 0), offset=(3, 3), anchor="lm"):
    x, y = xy
    draw.text((x + offset[0], y + offset[1]), text, font=fnt, fill=shadow_color, anchor=anchor)
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)


def _render_ladder_neon(rows, our_team_name, opponent_name, division, subtitle):
    """
    Bold hexagon-badge team-vs-team poster, purple vs blue, with glow
    effects, set in Orbitron (geometric sci-fi; Black weight for the title,
    Bold for everything else).
    Deliberately tight vertical spacing: Discord scales an entire image down
    to fit its ~400x300 chat preview box, preserving aspect ratio — a tall,
    narrow image (the original version of this was ~1100x1826, a 0.6:1
    ratio) gets shrunk far more aggressively than a wider, shorter one, so
    bigger fonts alone don't survive that scaling. Tightening row height and
    widening the canvas targets something closer to Discord's own preview
    ratio, so text stays legible after Discord's own scaling, not just in
    the raw file.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"

    W = 1300
    row_h = 58
    header_h = 170
    n = len(rows)
    H = header_h + n * row_h + 20

    PURPLE1, PURPLE2 = (72, 20, 140), (150, 60, 230)
    BLUE1, BLUE2 = (10, 40, 140), (50, 120, 240)

    img = _vertical_gradient_bg((W, H), (10, 8, 22), (4, 4, 12))
    img = img.convert('RGBA')
    img.alpha_composite(_radial_glow_layer((W, H), (W * 0.28, 85), 220, PURPLE2, max_alpha=65))
    img.alpha_composite(_radial_glow_layer((W, H), (W * 0.72, 85), 220, BLUE2, max_alpha=65))
    img = img.convert('RGB')
    draw = ImageDraw.Draw(img)

    title_text = f"{our_team_name} vs {opponent_name}"
    # Black weight for the title only, Bold everywhere else in this style
    title_font = _fit_text(draw, title_text, _FONT_ORBITRON_BLACK, 44, 24, W - 70)
    _draw_text_glow(img, (W / 2, 32), title_text, title_font, (255, 255, 255), PURPLE2, glow_radius=8, glow_alpha=130)
    draw = ImageDraw.Draw(img)
    if division or subtitle:
        sub_font = _load_font(_FONT_ORBITRON, 19)
        draw.text((W / 2, 62), (division or subtitle or "").upper(), font=sub_font, fill=(180, 184, 208), anchor="mm")

    hy0, hy1 = 84, 140
    mid = W // 2
    left_pts = _chevron_points(24, mid - 40, hy0, hy1, 1)
    right_pts = _chevron_points(mid + 40, W - 24, hy0, hy1, -1)
    _gradient_fill_polygon(img, left_pts, PURPLE1, PURPLE2)
    _gradient_fill_polygon(img, right_pts, BLUE2, BLUE1)
    draw = ImageDraw.Draw(img)
    draw.line(left_pts + [left_pts[0]], fill=(210, 170, 255), width=3)
    draw.line(right_pts + [right_pts[0]], fill=(160, 205, 255), width=3)

    left_w = mid - 40 - 24 - 24
    right_w = W - 24 - (mid + 40) - 24
    our_label_font = _fit_text(draw, "OUR TEAM", _FONT_ORBITRON, 28, 16, left_w)
    opp_label_font = _fit_text(draw, "OPPONENTS", _FONT_ORBITRON, 28, 16, right_w)
    sub_team_font = _fit_text(draw, our_team_name, _POSTER_FONT_REG, 16, 10, left_w)
    sub_opp_font = _fit_text(draw, opponent_name, _POSTER_FONT_REG, 16, 10, right_w)
    draw.text((24 + (mid - 40 - 24) / 2, (hy0 + hy1) // 2 - 12), "OUR TEAM", font=our_label_font, fill=(255, 255, 255), anchor="mm")
    draw.text((24 + (mid - 40 - 24) / 2, (hy0 + hy1) // 2 + 15), our_team_name, font=sub_team_font, fill=(230, 215, 255), anchor="mm")
    draw.text((mid + 40 + (W - 24 - mid - 40) / 2, (hy0 + hy1) // 2 - 12), "OPPONENTS", font=opp_label_font, fill=(255, 255, 255), anchor="mm")
    draw.text((mid + 40 + (W - 24 - mid - 40) / 2, (hy0 + hy1) // 2 + 15), opponent_name, font=sub_opp_font, fill=(210, 230, 255), anchor="mm")

    vs_font = _load_font(_FONT_ORBITRON, 36)
    _draw_text_glow(img, (mid, (hy0 + hy1) // 2), "VS", vs_font, (255, 255, 255), (255, 255, 255), glow_radius=8, glow_alpha=190)
    draw = ImageDraw.Draw(img)

    rank_font = _load_font(_FONT_ORBITRON, 26)

    def hex_badge(cx, cy, r, fill, text, point_dir):
        if point_dir == 1:
            pts = [(cx - r, cy - r), (cx + r * 0.5, cy - r), (cx + r, cy), (cx + r * 0.5, cy + r), (cx - r, cy + r)]
        else:
            pts = [(cx - r * 0.5, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r * 0.5, cy + r), (cx - r, cy)]
        draw.polygon(pts, fill=fill)
        draw.polygon(pts, outline=(255, 255, 255), width=2)
        draw.text((cx, cy), text, font=rank_font, fill=(255, 255, 255), anchor="mm")

    # Name columns run from just inside each hexagon badge to just short of
    # the centre gutter; names are centred within them (see
    # _draw_centered_name), so these are real bounds, not just a start x.
    our_col = (88, mid - _DIFF_GUTTER)
    opp_col = (mid + _DIFF_GUTTER, W - 88)
    diff_font = _load_font(_FONT_ORBITRON, 20)
    stat_font_row = _load_font(_POSTER_FONT_ITALIC, 20)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h - 5
        cy = (y0 + y1) // 2
        row_bg_l = (34, 20, 54) if i % 2 == 0 else (24, 14, 40)
        row_bg_r = (14, 26, 54) if i % 2 == 0 else (10, 18, 38)
        # Panels pull back from the midline to leave the diff column room
        # between them, instead of meeting at a 12px seam.
        draw.rounded_rectangle([24, y0, mid - 34, y1], radius=9, fill=row_bg_l)
        draw.rounded_rectangle([mid + 34, y0, W - 24, y1], radius=9, fill=row_bg_r)
        draw.rounded_rectangle([24, y0, mid - 34, y1], radius=9, outline=(90, 50, 140), width=1)
        draw.rounded_rectangle([mid + 34, y0, W - 24, y1], radius=9, outline=(40, 80, 150), width=1)
        _draw_diff(draw, f, mid, cy, diff_font, (150, 255, 190), (255, 150, 170))

        hex_badge(52, cy, 22, PURPLE2, str(f['slot']), 1)
        _draw_centered_name(
            draw, f['our_ign'], f"({f['our_stat']})" if f['our_stat'] else None,
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_ORBITRON, 27, 14, w),
            (245, 245, 250), stat_font_row, (200, 175, 255), stat_side='right',
        )

        hex_badge(W - 52, cy, 22, BLUE2, str(f['slot']), -1)
        _draw_centered_name(
            draw, f['opp_ign'], f"(DEF {f['opp_stat']})" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_ORBITRON, 27, 14, w),
            (245, 245, 250), stat_font_row, (170, 205, 255), stat_side='left',
        )

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_clean(rows, our_team_name, opponent_name, division, subtitle):
    """
    Minimal modern cards, indigo (ours) vs pink (opponent) accents, with soft
    depth. Deliberately tight: see _render_ladder_neon's docstring for why —
    Discord scales the whole image to fit its chat preview box, so a shorter,
    wider image survives that scaling far better than a tall one. Switched
    from a two-line-per-row layout (name above, stat below) to name+stat on
    one line, which is what actually let row height shrink this much without
    cramming the text itself.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponent"

    W = 1300
    row_h = 56
    row_gap = 8
    header_h = 130
    n = len(rows)
    H = header_h + n * (row_h + row_gap) + 20

    CARD = (34, 35, 46)
    ACCENT_OURS1, ACCENT_OURS2 = (99, 102, 241), (168, 130, 255)
    ACCENT_OPP1, ACCENT_OPP2 = (244, 114, 182), (255, 160, 130)
    TEXT_MAIN = (245, 245, 250)
    TEXT_SUB = (170, 173, 190)

    img = _vertical_gradient_bg((W, H), (24, 25, 34), (14, 15, 22))
    draw = ImageDraw.Draw(img)

    title_font = _fit_text(draw, our_team_name, _POSTER_FONT_BOLD, 40, 24, W - 88)
    draw.text((36, 28), our_team_name, font=title_font, fill=TEXT_MAIN, anchor="lm")
    sub_bits = ["Ladder"]
    if opponent_name:
        sub_bits.append(f"vs {opponent_name}")
    if division:
        sub_bits.append(division)
    elif subtitle:
        sub_bits.append(subtitle)
    sub_font = _load_font(_POSTER_FONT_REG, 19)
    draw.text((36, 58), "  •  ".join(sub_bits), font=sub_font, fill=TEXT_SUB, anchor="lm")

    label_font = _load_font(_POSTER_FONT_BOLD, 17)
    pill_y = 88
    _gradient_fill_rounded_rect(img, [36, pill_y, 152, pill_y + 30], 15, ACCENT_OURS1, ACCENT_OURS2, 'v')
    draw = ImageDraw.Draw(img)
    draw.text((94, pill_y + 15), "OUR TEAM", font=label_font, fill=(255, 255, 255), anchor="mm")
    _gradient_fill_rounded_rect(img, [164, pill_y, 290, pill_y + 30], 15, ACCENT_OPP1, ACCENT_OPP2, 'v')
    draw = ImageDraw.Draw(img)
    draw.text((227, pill_y + 15), "OPPONENT", font=label_font, fill=(255, 255, 255), anchor="mm")

    stat_font = _load_font(_POSTER_FONT_ITALIC, 18)
    rank_font = _load_font(_POSTER_FONT_BOLD, 20)
    diff_font = _load_font(_POSTER_FONT_BOLD, 17)
    side_max_w = (W - 72 - 90) / 2 - 20  # rough available width per side

    # All row shadows drawn onto one shared layer and blurred once, rather
    # than once per row — a full-image Gaussian blur per row scales badly.
    from PIL import ImageFilter
    shadow_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    y = header_h
    for _ in rows:
        y0, y1 = y, y + row_h
        shadow_draw.rounded_rectangle([36, y0 + 4, W - 36, y1 + 4], radius=12, fill=(0, 0, 0, 90))
        y += row_h + row_gap
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img.convert('RGBA'), shadow_layer).convert('RGB')
    draw = ImageDraw.Draw(img)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rounded_rectangle([36, y0, W - 36, y1], radius=12, fill=CARD)
        _gradient_fill_rounded_rect(img, [36, y0, 42, y1], 3, ACCENT_OURS1, ACCENT_OURS2, 'v')
        _gradient_fill_rounded_rect(img, [W - 42, y0, W - 36, y1], 3, ACCENT_OPP2, ACCENT_OPP1, 'v')
        draw = ImageDraw.Draw(img)

        # The centre badge is a pill rather than a circle so the slot number
        # and the diff can share it — this style has no end-of-row slot
        # badges to fall back on, so the slot has to stay in the middle.
        cx = W // 2
        pill_w, pill_h = 108, 38
        draw.rounded_rectangle([cx - pill_w // 2, cy - pill_h // 2, cx + pill_w // 2, cy + pill_h // 2],
                               radius=pill_h // 2, fill=(46, 44, 60))
        draw.rounded_rectangle([cx - pill_w // 2, cy - pill_h // 2, cx + pill_w // 2, cy + pill_h // 2],
                               radius=pill_h // 2, outline=(80, 78, 100), width=2)
        draw.line([(cx, cy - 12), (cx, cy + 12)], fill=(80, 78, 100), width=1)
        draw.text((cx - 26, cy), str(f['slot']), font=rank_font, fill=TEXT_MAIN, anchor="mm")
        _draw_diff(draw, f, cx + 27, cy, diff_font, (150, 240, 185), (255, 155, 175))

        # Stats sit outboard here (away from the centre pill), the mirror of
        # most styles — that's what keeps the two names tight against the
        # middle of the card.
        our_col = (60, cx - pill_w // 2 - 12)
        opp_col = (cx + pill_w // 2 + 12, W - 60)
        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, 25, 14, w),
            TEXT_MAIN, stat_font, (190, 175, 255), stat_side='left',
        )
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, 25, 14, w),
            TEXT_MAIN, stat_font, (255, 175, 205), stat_side='right',
        )

        y += row_h + row_gap

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_scoreboard(rows, our_team_name, opponent_name, division, subtitle):
    """
    Bold flat-color broadcast style, orange vs teal, with diagonal cuts for
    energy, set in Anton (heavy condensed broadcast caps). Deliberately tight — see _render_ladder_neon's docstring for why.
    """
    our_team_name_disp = (our_team_name or "Our Team").upper()
    opponent_name_disp = (opponent_name or "Opponents").upper()

    W = 1300
    row_h = 58
    header_h = 150
    n = len(rows)
    H = header_h + n * row_h + 16

    BG = (10, 10, 13)
    ORANGE1, ORANGE2 = (255, 120, 0), (255, 170, 40)
    TEAL1, TEAL2 = (0, 160, 156), (30, 210, 200)
    TEXT_MAIN = (255, 255, 255)
    TEXT_DIM = (185, 187, 195)
    ROW_A, ROW_B = (22, 23, 28), (28, 29, 35)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Diagonal speed-line accent strip at the very top for a broadcast feel
    draw.rectangle([0, 0, W, 10], fill=ORANGE1)
    for i in range(-2, int(W / 70) + 4):
        x = i * 70
        draw.polygon([(x, 0), (x + 40, 0), (x - 20, 10), (x - 60, 10)], fill=(255, 190, 90))

    title_font = _load_font(_FONT_ANTON, 42)
    _draw_text_shadow(draw, (36, 40), "LADDER MATCHUPS", title_font, TEXT_MAIN, offset=(3, 3))
    sub_text = f"{our_team_name_disp}   vs   {opponent_name_disp}"
    if division or subtitle:
        sub_text += f"   •   {(division or subtitle).upper()}"
    sub_font = _fit_text(draw, sub_text, _FONT_ANTON, 19, 13, W - 72)
    draw.text((36, 74), sub_text, font=sub_font, fill=TEXT_DIM, anchor="lm")

    band_y0, band_y1 = 100, 140
    cut = 28
    mid = W // 2
    draw.polygon([(0, band_y0), (mid + cut, band_y0), (mid - cut, band_y1), (0, band_y1)], fill=ORANGE1)
    draw.polygon([(mid + cut, band_y0), (W, band_y0), (W, band_y1), (mid - cut, band_y1)], fill=TEAL1)
    band_font_l = _fit_text(draw, "OUR TEAM", _FONT_ANTON, 22, 14, mid - 72)
    band_font_r = _fit_text(draw, "OPPONENTS", _FONT_ANTON, 22, 14, mid - 72)
    draw.text((36, (band_y0 + band_y1) // 2), "OUR TEAM", font=band_font_l, fill=(20, 15, 10), anchor="lm")
    draw.text((W - 36, (band_y0 + band_y1) // 2), "OPPONENTS", font=band_font_r, fill=(6, 24, 24), anchor="rm")

    rank_font = _load_font(_FONT_ANTON, 26)
    stat_font = _load_font(_POSTER_FONT_ITALIC, 18)
    name_font_base_size = 24
    our_col = (66, mid - _DIFF_GUTTER)
    opp_col = (mid + _DIFF_GUTTER, W - 66)
    diff_font = _load_font(_FONT_ANTON, 20)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([0, y0, W, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        # Angled rank block instead of a plain rectangle
        draw.polygon([(0, y0), (56, y0), (44, y1), (0, y1)], fill=ORANGE1)
        draw.text((24, cy), str(f['slot']), font=rank_font, fill=(20, 15, 10), anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_ANTON, name_font_base_size, 14, w),
            TEXT_MAIN, stat_font, ORANGE2, stat_side='right',
        )

        draw.line([(mid, y0 + 6), (mid, cy - 16)], fill=(70, 70, 78), width=2)
        draw.line([(mid, cy + 16), (mid, y1 - 6)], fill=(70, 70, 78), width=2)
        _draw_diff(draw, f, mid, cy, diff_font, ORANGE2, TEAL2)

        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_ANTON, name_font_base_size, 14, w),
            TEXT_MAIN, stat_font, TEAL2, stat_side='left',
        )

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_tactical(rows, our_team_name, opponent_name, division, subtitle):
    """Military/esports-tournament style, Black Ops One stencil font, olive/amber palette."""
    our_team_name = our_team_name or "Our Squad"
    opponent_name = opponent_name or "Enemy Squad"

    W = 1300
    row_h = 58
    header_h = 160
    n = len(rows)
    H = header_h + n * row_h + 18

    BG = (16, 18, 14)
    OLIVE1, OLIVE2 = (58, 66, 42), (86, 96, 58)
    AMBER = (255, 176, 0)
    TEXT_MAIN = (230, 232, 220)
    TEXT_DIM = (150, 155, 135)
    ROW_A, ROW_B = (24, 26, 20), (30, 33, 25)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    stripe_h = 10
    draw.rectangle([0, 0, W, stripe_h], fill=(20, 20, 16))
    for i in range(-2, int(W / 40) + 4):
        x = i * 40
        draw.polygon([(x, 0), (x + 20, 0), (x + 8, stripe_h), (x - 12, stripe_h)], fill=AMBER)

    title_text = f"{our_team_name} vs {opponent_name}"
    title_font = _fit_text(draw, title_text, _FONT_BLACK_OPS, 38, 18, W - 72)
    draw.text((36, 32), title_text, font=title_font, fill=TEXT_MAIN)
    sub_font = _load_font(_POSTER_FONT_REG, 18)
    sub_text = "TACTICAL DEPLOYMENT" + (f"  //  {division.upper()}" if division else (f"  //  {subtitle}" if subtitle else ""))
    draw.text((36, 68), sub_text, font=sub_font, fill=TEXT_DIM)

    band_y0, band_y1 = 98, 138
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=OLIVE2)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=(40, 44, 32))
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=AMBER, width=2)
    lbl_l = _fit_text(draw, "OUR SQUAD", _FONT_BLACK_OPS, 22, 12, W // 2 - 90)
    lbl_r = _fit_text(draw, "ENEMY SQUAD", _FONT_BLACK_OPS, 22, 12, W // 2 - 90)
    draw.text((50, (band_y0 + band_y1) // 2), "OUR SQUAD", font=lbl_l, fill=(20, 20, 16), anchor="lm")
    draw.text((W - 50, (band_y0 + band_y1) // 2), "ENEMY SQUAD", font=lbl_r, fill=AMBER, anchor="rm")

    rank_font = _load_font(_FONT_BLACK_OPS, 20)
    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    tagw = 54
    our_col = (36 + tagw + 10, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 36 - tagw - 10)
    diff_font = _load_font(_FONT_BLACK_OPS, 18)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        draw.polygon([(36, y0), (36 + tagw, y0), (36 + tagw, y1), (36 + 12, y1), (36, y1 - 12)], fill=OLIVE2)
        draw.text((36 + tagw / 2, cy), str(f['slot']), font=rank_font, fill=(20, 20, 16), anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_BLACK_OPS, 22, 12, w),
            TEXT_MAIN, stat_font, AMBER, stat_side='right',
        )

        draw.line([(W // 2, y0 + 8), (W // 2, cy - 16)], fill=(60, 64, 50), width=2)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 8)], fill=(60, 64, 50), width=2)
        _draw_diff(draw, f, W // 2, cy, diff_font, AMBER, (200, 90, 90))
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_BLACK_OPS, 22, 12, w),
            TEXT_MAIN, stat_font, (200, 90, 90), stat_side='left',
        )

        draw.polygon([(W - 36 - tagw, y0), (W - 36, y0), (W - 36, y1 - 12), (W - 36 - 12, y1), (W - 36 - tagw, y1)], fill=(40, 44, 32))
        draw.text((W - 36 - tagw / 2, cy), str(f['slot']), font=rank_font, fill=AMBER, anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_varsity(rows, our_team_name, opponent_name, division, subtitle):
    """
    Collegiate athletics program style, Graduate slab-serif, navy/gold, with
    a blank football helmet decal either side of the title.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"

    W = 1300
    row_h = 58
    header_h = 168
    n = len(rows)
    H = header_h + n * row_h + 18

    NAVY = (16, 24, 56)
    NAVY2 = (26, 38, 78)
    GOLD = (212, 175, 55)
    CREAM = (240, 234, 214)
    ROW_A, ROW_B = (20, 28, 60), (26, 36, 70)

    img = Image.new('RGB', (W, H), NAVY)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 6], fill=GOLD)

    # Blank helmet decals flanking the title, facing inward, in a muted gold
    # so they read as program-cover livery without competing with the type.
    # Sized and placed to clear the HOME TEAM / VISITORS band at y=116.
    helmet = (104, 86, 38)
    _paste_helmet(img, 148, 58, 104, helmet, facing=1)
    _paste_helmet(img, W - 148, 58, 104, helmet, facing=-1)
    draw = ImageDraw.Draw(img)

    title_font = _fit_text(draw, our_team_name.upper(), _FONT_GRADUATE, 54, 26, W - 72)
    draw.text((W / 2, 46), our_team_name.upper(), font=title_font, fill=CREAM, anchor="mm")
    sub_font = _load_font(_POSTER_FONT_REG, 18)
    sub_bits = ["ATHLETIC LADDER", f"vs {opponent_name}"]
    if division:
        sub_bits.append(division)
    elif subtitle:
        sub_bits.append(subtitle)
    sub_text = "  •  ".join(sub_bits)
    sub_font = _fit_text(draw, sub_text, _POSTER_FONT_REG, 18, 12, W - 72)
    draw.text((W / 2, 82), sub_text, font=sub_font, fill=(180, 188, 210), anchor="mm")
    draw.line([(60, 102), (W - 60, 102)], fill=GOLD, width=2)

    band_y0, band_y1 = 116, 156
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=GOLD)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=NAVY2)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=GOLD, width=2)
    lbl_l = _fit_text(draw, "HOME TEAM", _FONT_GRADUATE, 24, 12, W // 2 - 90)
    lbl_r = _fit_text(draw, "VISITORS", _FONT_GRADUATE, 24, 12, W // 2 - 90)
    draw.text((36 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "HOME TEAM", font=lbl_l, fill=NAVY, anchor="mm")
    draw.text((W // 2 + 6 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "VISITORS", font=lbl_r, fill=GOLD, anchor="mm")

    rank_font = _load_font(_FONT_GRADUATE, 20)
    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    our_col = (36 + 50 + 10, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 36 - 50 - 10)
    diff_font = _load_font(_FONT_GRADUATE, 18)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        draw.rectangle([36, y0, 36 + 50, y1], fill=GOLD)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=NAVY, anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_GRADUATE, 24, 12, w),
            CREAM, stat_font, (210, 215, 235), stat_side='right',
        )

        draw.line([(W // 2, y0 + 8), (W // 2, cy - 16)], fill=(60, 70, 110), width=2)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 8)], fill=(60, 70, 110), width=2)
        _draw_diff(draw, f, W // 2, cy, diff_font, GOLD, (230, 150, 150))
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_GRADUATE, 24, 12, w),
            CREAM, stat_font, (230, 200, 120), stat_side='left',
        )
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=NAVY2)
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], outline=GOLD, width=1)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font, fill=GOLD, anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_arcade(rows, our_team_name, opponent_name, division, subtitle):
    """Retro 8-bit arcade style, Press Start 2P pixel font, neon magenta/cyan palette."""
    our_team_name = our_team_name or "Player 1"
    opponent_name = opponent_name or "Player 2"

    W = 1300
    row_h = 58
    header_h = 172
    n = len(rows)
    H = header_h + n * row_h + 18

    BG = (10, 6, 22)
    MAGENTA = (255, 40, 180)
    CYAN = (40, 230, 255)
    YELLOW = (255, 230, 60)
    TEXT_MAIN = (235, 235, 245)
    ROW_A, ROW_B = (18, 12, 34), (24, 16, 42)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    for x in range(0, W, 6):
        draw.line([(x, 0), (x, 8)], fill=(30, 20, 50))
    draw.rectangle([0, 8, W, 10], fill=MAGENTA)

    # Press Start 2P is very wide per character — keep the title short and
    # let _fit_text shrink further for long team names rather than overflow.
    title_font = _fit_text(draw, our_team_name.upper(), _FONT_PRESS_START, 30, 10, W - 72)
    draw.text((36, 28), our_team_name.upper(), font=title_font, fill=CYAN)
    sub_text = f"VS {opponent_name.upper()}" + (f" - {division.upper()}" if division else (f" - {subtitle}" if subtitle else ""))
    sub_font = _fit_text(draw, sub_text, _FONT_PRESS_START, 14, 8, W - 72)
    draw.text((36, 76), sub_text, font=sub_font, fill=YELLOW)

    band_y0, band_y1 = 116, 156
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=(40, 10, 60))
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], outline=MAGENTA, width=2)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=(6, 30, 44))
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=CYAN, width=2)
    lbl_l = _fit_text(draw, "PLAYER 1", _FONT_PRESS_START, 16, 7, W // 2 - 90)
    lbl_r = _fit_text(draw, "PLAYER 2", _FONT_PRESS_START, 16, 7, W // 2 - 90)
    draw.text((36 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "PLAYER 1", font=lbl_l, fill=MAGENTA, anchor="mm")
    draw.text((W // 2 + 6 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "PLAYER 2", font=lbl_r, fill=CYAN, anchor="mm")

    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    our_col = (36 + 50 + 10, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 36 - 50 - 10)
    diff_font = _load_font(_FONT_PRESS_START, 12)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        rank_font = _fit_text(draw, str(f['slot']), _FONT_PRESS_START, 16, 7, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=(40, 10, 60))
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=MAGENTA, anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_PRESS_START, 20, 8, w),
            TEXT_MAIN, stat_font, YELLOW, stat_side='right',
        )

        draw.line([(W // 2, y0 + 8), (W // 2, cy - 16)], fill=(60, 50, 90), width=2)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 8)], fill=(60, 50, 90), width=2)
        _draw_diff(draw, f, W // 2, cy, diff_font, YELLOW, MAGENTA)
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_PRESS_START, 20, 8, w),
            TEXT_MAIN, stat_font, CYAN, stat_side='left',
        )
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=(6, 30, 44))
        rank_font_r = _fit_text(draw, str(f['slot']), _FONT_PRESS_START, 16, 7, 44)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font_r, fill=CYAN, anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_street(rows, our_team_name, opponent_name, division, subtitle):
    """Urban/graffiti style, Bungee Inline font, hot pink/electric yellow/cyan on concrete gray."""
    import random
    our_team_name = our_team_name or "Home Crew"
    opponent_name = opponent_name or "Rival Crew"

    W = 1300
    row_h = 58
    header_h = 168
    n = len(rows)
    H = header_h + n * row_h + 18

    BG = (28, 28, 30)
    PINK = (255, 45, 120)
    YELLOW = (240, 230, 40)
    CYAN = (60, 220, 210)
    TEXT_MAIN = (245, 245, 248)
    ROW_A, ROW_B = (36, 36, 40), (42, 42, 46)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    rng = random.Random(7)  # fixed seed — same splatter pattern every render, not flickering between calls
    for _ in range(70):
        x = rng.randint(0, W)
        y = rng.randint(0, 14)
        r = rng.randint(1, 4)
        c = rng.choice([PINK, YELLOW, CYAN])
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
    draw.rectangle([0, 14, W, 18], fill=PINK)

    title_text = f"{our_team_name} vs {opponent_name}"
    title_font = _fit_text(draw, title_text, _FONT_BUNGEE, 34, 16, W - 72)
    draw.text((36, 34), title_text, font=title_font, fill=YELLOW)
    sub_font = _load_font(_POSTER_FONT_REG, 18)
    sub_text = "STREET LADDER" + (f"  //  {division.upper()}" if division else (f"  //  {subtitle}" if subtitle else ""))
    draw.text((36, 78), sub_text, font=sub_font, fill=(190, 190, 200))

    band_y0, band_y1 = 108, 148
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=PINK)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=(20, 50, 48))
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=CYAN, width=2)
    lbl_l = _fit_text(draw, "HOME CREW", _FONT_BUNGEE, 20, 12, W // 2 - 90)
    lbl_r = _fit_text(draw, "RIVAL CREW", _FONT_BUNGEE, 20, 12, W // 2 - 90)
    draw.text((50, (band_y0 + band_y1) // 2), "HOME CREW", font=lbl_l, fill=(30, 10, 20), anchor="lm")
    draw.text((W - 50, (band_y0 + band_y1) // 2), "RIVAL CREW", font=lbl_r, fill=CYAN, anchor="rm")

    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    our_col = (36 + 50 + 10, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 36 - 50 - 10)
    diff_font = _load_font(_POSTER_FONT_BOLD, 20)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        rank_font = _fit_text(draw, str(f['slot']), _FONT_BUNGEE, 18, 10, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=PINK)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=(30, 10, 20), anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_BUNGEE, 22, 10, w),
            TEXT_MAIN, stat_font, YELLOW, stat_side='right',
        )

        draw.line([(W // 2, y0 + 8), (W // 2, cy - 16)], fill=(70, 70, 76), width=2)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 8)], fill=(70, 70, 76), width=2)
        _draw_diff(draw, f, W // 2, cy, diff_font, YELLOW, PINK)
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_BUNGEE, 22, 10, w),
            TEXT_MAIN, stat_font, CYAN, stat_side='left',
        )
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=(20, 50, 48))
        rank_font_r = _fit_text(draw, str(f['slot']), _FONT_BUNGEE, 18, 10, 44)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font_r, fill=CYAN, anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_carnival(rows, our_team_name, opponent_name, division, subtitle):
    """
    Playful carnival/party style, Honk (variable font: Morph/Shadow axes)
    for titles and labels only. Honk's digits become illegible blocks below
    ~16-18px regardless of axis settings, so rank badges and player
    names/stats use the reliable bold font instead — see
    _VARIABLE_FONT_MIN_SAFE_SIZE and _fit_variable_text.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"
    honk_axes = [0, 100]  # no morph, max shadow — the bounce-block look, confirmed most legible

    W = 1300
    row_h = 58
    header_h = 168
    n = len(rows)
    H = header_h + n * row_h + 18

    BG = (36, 16, 48)
    RED = (240, 70, 90)
    TEAL = (40, 200, 190)
    YELLOW = (255, 210, 60)
    TEXT_MAIN = (250, 248, 250)
    ROW_A, ROW_B = (46, 22, 58), (52, 26, 64)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    colors = [RED, YELLOW, TEAL]
    flag_w = 44
    for i in range(int(W / flag_w) + 2):
        x = i * flag_w
        draw.polygon([(x, 0), (x + flag_w, 0), (x + flag_w / 2, 16)], fill=colors[i % 3])

    title_text = f"{our_team_name} vs {opponent_name}"
    title_font = _fit_variable_text(draw, title_text, _FONT_HONK_PATH, honk_axes, _POSTER_FONT_BOLD, 36, 16, W - 72)
    draw.text((36, 32), title_text, font=title_font, fill=YELLOW)
    sub_font = _load_font(_POSTER_FONT_REG, 18)
    sub_text = "CARNIVAL LADDER" + (f"  //  {division.upper()}" if division else (f"  //  {subtitle}" if subtitle else ""))
    draw.text((36, 78), sub_text, font=sub_font, fill=(210, 195, 220))

    band_y0, band_y1 = 108, 148
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=RED)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=TEAL)
    lbl_l = _fit_variable_text(draw, "OUR TEAM", _FONT_HONK_PATH, honk_axes, _POSTER_FONT_BOLD, 22, 12, W // 2 - 90)
    lbl_r = _fit_variable_text(draw, "OPPONENTS", _FONT_HONK_PATH, honk_axes, _POSTER_FONT_BOLD, 22, 12, W // 2 - 90)
    draw.text((50, (band_y0 + band_y1) // 2), "OUR TEAM", font=lbl_l, fill=(255, 255, 255), anchor="lm")
    draw.text((W - 50, (band_y0 + band_y1) // 2), "OPPONENTS", font=lbl_r, fill=(20, 50, 48), anchor="rm")

    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    our_col = (36 + 50 + 10, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 36 - 50 - 10)
    diff_font = _load_font(_POSTER_FONT_BOLD, 20)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        # Rank numbers use the reliable bold font, not Honk — a 44px-wide
        # badge forces single/double-digit numbers well below Honk's safe
        # size floor, which is exactly where it breaks into illegible blocks.
        rank_font = _fit_text(draw, str(f['slot']), _POSTER_FONT_BOLD, 22, 12, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=RED)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=(255, 255, 255), anchor="mm")

        # Names stay on the reliable font, not Honk, unlike the other 5
        # display-font styles — confirmed directly that Honk's digit glyphs
        # are inherently hard to distinguish from letters in mixed
        # alphanumeric names (JX8, Dukie06, GKH1987 all become borderline
        # illegible even at a safe size, and even with zero shadow), and
        # this league's rosters commonly have exactly that kind of name.
        # Honk stays reserved for the title/labels, which are known text
        # without that mixed pattern.
        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, 24, 13, w),
            TEXT_MAIN, stat_font, YELLOW, stat_side='right',
        )

        draw.line([(W // 2, y0 + 8), (W // 2, cy - 16)], fill=(80, 50, 90), width=2)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 8)], fill=(80, 50, 90), width=2)
        _draw_diff(draw, f, W // 2, cy, diff_font, YELLOW, RED)
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, 24, 13, w),
            TEXT_MAIN, stat_font, TEAL, stat_side='left',
        )
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=TEAL)
        rank_font_r = _fit_text(draw, str(f['slot']), _POSTER_FONT_BOLD, 22, 12, 44)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font_r, fill=(20, 50, 48), anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_gridiron(rows, our_team_name, opponent_name, division, subtitle):
    """
    Football-field style: green turf, white yard lines and hash marks, each
    row sitting on its own yard line with the slot number as a field number.
    The only style whose layout comes from the sport itself rather than a
    generic poster treatment. Shares tactical's Black Ops One by explicit
    preference — the two styles look nothing alike otherwise (olive stencil
    vs green field), so the shared face is not a problem to solve.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"

    W = 1300
    row_h = 58
    header_h = 164
    n = len(rows)
    H = header_h + n * row_h + 30

    TURF1, TURF2 = (26, 92, 44), (22, 80, 38)   # mowed-stripe alternation
    WHITE = (245, 248, 244)
    LINE = (225, 235, 225)
    ENDZONE = (16, 52, 28)
    ACCENT = (250, 204, 21)

    img = Image.new('RGB', (W, H), TURF1)
    draw = ImageDraw.Draw(img)

    # Header "end zone" band
    draw.rectangle([0, 0, W, header_h - 12], fill=ENDZONE)
    for x in range(0, W, 48):
        draw.line([(x, 0), (x, header_h - 12)], fill=(20, 60, 34), width=1)
    draw.rectangle([0, header_h - 14, W, header_h - 10], fill=WHITE)

    title_text = f"{our_team_name}  vs  {opponent_name}"
    title_font = _fit_text(draw, title_text.upper(), _FONT_BLACK_OPS, 40, 18, W - 80)
    draw.text((W / 2, 46), title_text.upper(), font=title_font, fill=WHITE, anchor="mm")

    sub_bits = ["GAME DAY LADDER"]
    if division:
        sub_bits.append(division.upper())
    elif subtitle:
        sub_bits.append(subtitle)
    sub_font = _fit_text(draw, "  •  ".join(sub_bits), _POSTER_FONT_REG, 18, 12, W - 80)
    draw.text((W / 2, 80), "  •  ".join(sub_bits), font=sub_font, fill=(170, 210, 180), anchor="mm")

    band_y0, band_y1 = 104, 142
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=WHITE)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=WHITE, width=2)
    lbl_l = _fit_text(draw, "HOME", _FONT_BLACK_OPS, 22, 12, W // 2 - 90)
    lbl_r = _fit_text(draw, "AWAY", _FONT_BLACK_OPS, 22, 12, W // 2 - 90)
    draw.text((36 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "HOME", font=lbl_l, fill=ENDZONE, anchor="mm")
    draw.text((W // 2 + 6 + (W // 2 - 42) / 2, (band_y0 + band_y1) // 2), "AWAY", font=lbl_r, fill=WHITE, anchor="mm")

    num_font = _load_font(_FONT_BLACK_OPS, 26)
    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    our_col = (90, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 90)
    diff_font = _load_font(_FONT_BLACK_OPS, 18)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([0, y0, W, y1], fill=(TURF1 if i % 2 == 0 else TURF2))

        # Yard line across the row, with hash marks above and below
        draw.line([(0, y0), (W, y0)], fill=LINE, width=2)
        for x in range(60, W - 60, 40):
            draw.line([(x, y0 + 8), (x, y0 + 15)], fill=(190, 210, 195), width=1)

        # Slot number as a field number, on both sidelines
        draw.text((44, cy), str(f['slot']), font=num_font, fill=WHITE, anchor="lm")
        draw.text((W - 44, cy), str(f['slot']), font=num_font, fill=WHITE, anchor="rm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_BLACK_OPS, 25, 13, w),
            WHITE, stat_font, ACCENT, stat_side='right',
        )

        draw.line([(W // 2, y0 + 6), (W // 2, cy - 16)], fill=LINE, width=3)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 6)], fill=LINE, width=3)
        _draw_diff(draw, f, W // 2, cy, diff_font, ACCENT, (255, 170, 150))
        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_BLACK_OPS, 25, 13, w),
            WHITE, stat_font, (255, 190, 170), stat_side='left',
        )

        y += row_h

    draw.line([(0, y), (W, y)], fill=LINE, width=2)
    return _to_png_buffer(img)


def _render_ladder_blueprint(rows, our_team_name, opponent_name, division, subtitle):
    """
    Technical-schematic style: blueprint blue with a fine grid, thin cyan
    rules, corner registration marks and dimension ticks. Set in Share Tech
    Mono — a genuinely monospaced face, which is most of what makes it read
    as a drawing rather than a poster. That font ships a Regular weight
    only, so everything here is a size up from the equivalent elsewhere and
    faux-bolded with a 1px stroke; at the original sizes it was too light to
    read comfortably.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"

    W = 1300
    row_h = 56
    header_h = 158
    n = len(rows)
    H = header_h + n * row_h + 44

    BG = (17, 34, 64)
    GRID_MINOR = (26, 48, 86)
    GRID_MAJOR = (34, 62, 108)
    CYAN = (125, 211, 252)
    INK = (226, 240, 255)
    DIM = (130, 160, 200)
    AMBER = (251, 191, 36)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    for x in range(0, W, 20):
        draw.line([(x, 0), (x, H)], fill=GRID_MINOR, width=1)
    for yy in range(0, H, 20):
        draw.line([(0, yy), (W, yy)], fill=GRID_MINOR, width=1)
    for x in range(0, W, 100):
        draw.line([(x, 0), (x, H)], fill=GRID_MAJOR, width=1)
    for yy in range(0, H, 100):
        draw.line([(0, yy), (W, yy)], fill=GRID_MAJOR, width=1)

    # Drawing border + corner registration marks
    draw.rectangle([22, 22, W - 22, H - 22], outline=CYAN, width=1)
    draw.rectangle([30, 30, W - 30, H - 30], outline=(60, 100, 160), width=1)
    for cx, cy_ in ((22, 22), (W - 22, 22), (22, H - 22), (W - 22, H - 22)):
        draw.line([(cx - 10, cy_), (cx + 10, cy_)], fill=CYAN, width=1)
        draw.line([(cx, cy_ - 10), (cx, cy_ + 10)], fill=CYAN, width=1)

    title_text = f"{our_team_name} / {opponent_name}"
    title_font = _fit_text(draw, title_text.upper(), _FONT_SHARE_TECH, 40, 18, W - 130)
    draw.text((52, 56), title_text.upper(), font=title_font, fill=INK, anchor="lm")

    meta_font = _load_font(_FONT_SHARE_TECH, 17)
    meta = f"MATCHUP SCHEMATIC   REV. {division.upper() if division else (subtitle or 'CURRENT')}   SLOTS 1-{n}"
    draw.text((52, 88), meta, font=meta_font, fill=DIM, anchor="lm")
    draw.line([(52, 108), (W - 52, 108)], fill=CYAN, width=1)

    lbl_font = _load_font(_FONT_SHARE_TECH, 18)
    draw.text((52, 130), "[ OURS ]", font=lbl_font, fill=CYAN, anchor="lm")
    draw.text((W - 52, 130), "[ OPPONENT ]", font=lbl_font, fill=AMBER, anchor="rm")
    # Dimension line between the two labels
    draw.line([(150, 130), (W - 190, 130)], fill=(60, 100, 160), width=1)
    draw.line([(150, 125), (150, 135)], fill=(60, 100, 160), width=1)
    draw.line([(W - 190, 125), (W - 190, 135)], fill=(60, 100, 160), width=1)

    slot_font = _load_font(_FONT_SHARE_TECH, 21)
    stat_font = _load_font(_FONT_SHARE_TECH, 18)
    our_col = (44 + 46 + 12, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 44 - 46 - 12)
    diff_font = _load_font(_FONT_SHARE_TECH, 22)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2

        draw.line([(40, y1), (W - 40, y1)], fill=(30, 56, 98), width=1)
        draw.rectangle([44, y0 + 8, 44 + 46, y1 - 8], outline=CYAN, width=1)
        draw.text((44 + 23, cy), f"{f['slot']:02d}", font=slot_font, fill=CYAN, anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f"[{f['our_stat']}]" if f['our_stat'] else None,
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_SHARE_TECH, 26, 15, w),
            INK, stat_font, CYAN, stat_side='right', stroke=1,
        )

        # Centre join, drawn like a schematic connector
        mid = W // 2
        # Dimension-style leaders either side of the difference readout
        draw.line([(mid - 40, cy), (mid - 22, cy)], fill=(70, 112, 172), width=1)
        draw.line([(mid + 22, cy), (mid + 40, cy)], fill=(70, 112, 172), width=1)
        _draw_diff(draw, f, mid, cy, diff_font, CYAN, AMBER, stroke=1)

        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_SHARE_TECH, 26, 15, w),
            INK, stat_font, AMBER, stat_side='left', stroke=1,
        )
        draw.rectangle([W - 44 - 46, y0 + 8, W - 44, y1 - 8], outline=AMBER, width=1)
        draw.text((W - 44 - 23, cy), f"{f['slot']:02d}", font=slot_font, fill=AMBER, anchor="mm")

        y += row_h

    return _to_png_buffer(img)


def _render_ladder_newsprint(rows, our_team_name, opponent_name, division, subtitle):
    """
    Broadsheet sports-page style: off-white newsprint paper, black ink, a
    halftone dot texture in the masthead and hairline column rules. The
    first light-background poster style — every other one is dark, so this
    is the one that reads very differently in Discord's light theme.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"

    W = 1300
    row_h = 56
    header_h = 176
    n = len(rows)
    H = header_h + n * row_h + 40

    PAPER = (242, 239, 231)
    PAPER_ALT = (234, 230, 220)
    INK = (26, 24, 22)
    INK_SOFT = (96, 92, 86)
    RED = (167, 40, 34)

    img = Image.new('RGB', (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    # Masthead with a halftone dot field behind it
    draw.rectangle([0, 0, W, 116], fill=INK)
    for gy in range(6, 116, 8):
        for gx in range(6, W, 8):
            r = 1 if (gx // 8 + gy // 8) % 2 == 0 else 2
            draw.ellipse([gx - r, gy - r, gx + r, gy + r], fill=(48, 45, 42))

    # Newsreader throughout — masthead, column heads, names, stats and slot
    # numbers — with its true italic on the kicker and the stat text, the way
    # a real sports page sets them. An earlier pass used it for the masthead
    # only and left the body in the condensed bold, which read as unstyled.
    title_text = f"{our_team_name} vs {opponent_name}"
    title_font = _fit_text(draw, title_text.upper(), _FONT_NEWSREADER, 46, 20, W - 100)
    draw.text((W / 2, 46), title_text.upper(), font=title_font, fill=PAPER, anchor="mm")
    kicker = "THE LADDER REPORT"
    if division:
        kicker += f"   —   {division.upper()} DIVISION"
    elif subtitle:
        kicker += f"   —   {subtitle}"
    kicker_font = _fit_text(draw, kicker, _FONT_NEWSREADER_IT, 19, 12, W - 100)
    draw.text((W / 2, 88), kicker, font=kicker_font, fill=(190, 186, 176), anchor="mm")

    draw.line([(40, 128), (W - 40, 128)], fill=INK, width=3)
    draw.line([(40, 134), (W - 40, 134)], fill=INK, width=1)

    col_font = _load_font(_FONT_NEWSREADER, 18)
    draw.text((44, 156), "OUR SIDE", font=col_font, fill=INK, anchor="lm")
    draw.text((W - 44, 156), "OPPOSITION", font=col_font, fill=RED, anchor="rm")
    draw.line([(40, 170), (W - 40, 170)], fill=INK_SOFT, width=1)

    slot_font = _load_font(_FONT_NEWSREADER, 20)
    stat_font = _load_font(_FONT_NEWSREADER_IT, 17)
    our_col = (44 + 42 + 12, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 44 - 42 - 12)
    diff_font = _load_font(_FONT_NEWSREADER, 21)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        if i % 2:
            draw.rectangle([40, y0, W - 40, y1], fill=PAPER_ALT)

        draw.rectangle([44, y0 + 10, 44 + 42, y1 - 10], fill=INK)
        draw.text((44 + 21, cy), str(f['slot']), font=slot_font, fill=PAPER, anchor="mm")

        _draw_centered_name(
            draw, f['our_ign'], f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_NEWSREADER, 25, 14, w),
            INK, stat_font, INK_SOFT, stat_side='right',
        )

        # Hairline column rule, the way a newspaper separates two columns
        draw.line([(W // 2, y0 + 6), (W // 2, cy - 16)], fill=INK_SOFT, width=1)
        draw.line([(W // 2, cy + 16), (W // 2, y1 - 6)], fill=INK_SOFT, width=1)
        _draw_diff(draw, f, W // 2, cy, diff_font, INK, RED)

        _draw_centered_name(
            draw, f['opp_ign'], f"DEF {f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_NEWSREADER, 25, 14, w),
            INK, stat_font, RED, stat_side='left',
        )
        draw.rectangle([W - 44 - 42, y0 + 10, W - 44, y1 - 10], outline=RED, width=2)
        draw.text((W - 44 - 21, cy), str(f['slot']), font=slot_font, fill=RED, anchor="mm")

        draw.line([(40, y1), (W - 40, y1)], fill=(214, 210, 200), width=1)
        y += row_h

    draw.line([(40, y + 8), (W - 40, y + 8)], fill=INK, width=3)
    return _to_png_buffer(img)


def _render_ladder_terminal(rows, our_team_name, opponent_name, division, subtitle):
    """
    CRT-terminal style: green phosphor on near-black, scanline overlay and
    a prompt-led row format, set in VT323 (an actual CRT terminal face, and
    genuinely monospaced — a terminal whose columns don't line up stops
    looking like one). Deliberately plain-text: no panels, badges or rules.
    """
    our_team_name = our_team_name or "OURS"
    opponent_name = opponent_name or "THEM"

    W = 1300
    row_h = 54
    header_h = 150
    n = len(rows)
    H = header_h + n * row_h + 56

    BG = (8, 12, 9)
    GREEN = (74, 246, 128)
    GREEN_DIM = (44, 150, 84)
    GREEN_FAINT = (24, 70, 44)
    AMBER = (250, 204, 21)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([24, 24, W - 24, H - 24], outline=GREEN_FAINT, width=1)

    # Every size here is ~1.55x the monospace-family equivalent: VT323's
    # glyphs fill only ~0.73 of the em box (measured directly), and earlier
    # passes at 1.0x and 1.36x were both too light to read easily. Size only,
    # no stroke: a 1px outline filled in this face's 'm' and 'W' ("Packman425"
    # rendering as "Packnan425"). Of the Regular-only faces, Share Tech Mono
    # in blueprint is the one open enough to take a stroke.
    head_font = _fit_text(draw, "LADDER", _FONT_VT323, 48, 24, W - 120)
    draw.text((48, 56), "LADDER", font=head_font, fill=GREEN, anchor="lm")
    path_font = _load_font(_FONT_VT323, 25)
    draw.text((48, 88), f"$ ladder --ours \"{our_team_name}\" --them \"{opponent_name}\"", font=path_font, fill=GREEN_DIM, anchor="lm")
    meta = f"# division={division or '-'}  slots={n}" + (f"  note={subtitle}" if subtitle else "")
    meta_font = _fit_text(draw, meta, _FONT_VT323, 23, 17, W - 110)
    draw.text((48, 112), meta, font=meta_font, fill=GREEN_FAINT, anchor="lm")
    draw.text((48, 134), "-" * 96, font=_load_font(_FONT_VT323, 19), fill=GREEN_FAINT, anchor="lm")

    slot_font = _load_font(_FONT_VT323, 26)
    stat_font = _load_font(_FONT_VT323, 23)
    our_col = (110, W // 2 - _DIFF_GUTTER)
    opp_col = (W // 2 + _DIFF_GUTTER, W - 60)
    diff_font = _load_font(_FONT_VT323, 27)

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2

        draw.text((48, cy), ">", font=slot_font, fill=GREEN_DIM, anchor="lm")
        draw.text((72, cy), f"{f['slot']:02d}", font=slot_font, fill=AMBER, anchor="lm")

        _draw_centered_name(
            draw, f['our_ign'], f"({f['our_stat']})" if f['our_stat'] else None,
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, f['our_ign'], _FONT_VT323, 32, 19, w),
            GREEN, stat_font, GREEN_DIM, stat_side='right',
        )

        _draw_diff(draw, f, W // 2, cy, diff_font, GREEN, AMBER)

        _draw_centered_name(
            draw, f['opp_ign'], f"def:{f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, f['opp_ign'], _FONT_VT323, 32, 19, w),
            GREEN, stat_font, AMBER, stat_side='left',
        )

        y += row_h

    draw.text((48, y + 14), "$ _", font=_load_font(_FONT_VT323, 25), fill=GREEN, anchor="lm")

    # Scanlines last, over everything, so the whole frame reads as one CRT
    scan = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(scan)
    for yy in range(0, H, 3):
        sdraw.line([(0, yy), (W, yy)], fill=(0, 0, 0, 48), width=1)
    img = Image.alpha_composite(img.convert('RGBA'), scan).convert('RGB')

    return _to_png_buffer(img)


# ---------------------------------------------------------------------------
# Themed ladder styles
# ---------------------------------------------------------------------------
# The styles above each grew their own bespoke renderer, which was fine for
# a handful but means the row geometry (centred names, the diff column, the
# slot badges) is restated every time. Everything below shares one renderer
# driven by a theme dict, so a new style is a palette + a font + a badge
# shape + an optional background-art hook, and none of them can drift out
# of line with the shared row logic.
#
# A theme's keys, all optional except the ones marked:
#   bg, row_a, row_b, text, dim       colours (bg/text required)
#   pos, neg                          diff colours (default: text)
#   font_title/font_name/font_num     font candidate lists (required)
#   font_stat                         defaults to _POSTER_FONT_ITALIC
#   title_size/name_size/name_min/num_size/stat_size/sub_size
#   header                            'bands' | 'rule' | 'plate'
#   band_l, band_r, band_text_l, band_text_r, label_l, label_r
#   badge                             'block' | 'pill' | 'tag' | 'outline' | 'none'
#   badge_l, badge_r, badge_text_l, badge_text_r
#   rows                              'alt' | 'line' | 'card'
#   sep                               separator colour for 'line'
#   divider                           centre divider colour (None = no rule)
#   bg_art                            fn(img, draw, W, H, header_h)
#   row_tint                          fn(f, i) -> colour or None
#   upper                             upper-case names/labels (caps-only faces)
#   stat_prefix                       e.g. 'DEF ' (default) for the opponent
#   row_h, header_h

# PIL antialiases neither polygons nor lines, so any art that is mostly
# diagonals (laurels, chevrons, swept bands) is drawn at this multiple and
# downscaled with LANCZOS. Drawn at 1x the edges come out stair-stepped —
# which is exactly what made an earlier gators header look blocky.
_ART_SUPERSAMPLE = 4


def _shade(color, factor):
    """Lighten (factor > 1) or darken (factor < 1) an RGB tuple."""
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def _draw_slot_badge(draw, shape, box, fill, outline, text, font, text_fill,
                     stroke=0, mirror=False):
    """
    Draw one row's slot badge in whichever shape the theme asked for.
    mirror flips the asymmetric shapes for the right-hand badge, so an angled
    pair leans into the middle instead of both leaning the same way.
    """
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if shape == 'pill':
        draw.rounded_rectangle(box, radius=(y1 - y0) // 2, fill=fill, outline=outline, width=2)
    elif shape == 'tag':
        notch = 12
        pts = ([(x0, y0), (x1, y0), (x1, y1 - notch), (x1 - notch, y1), (x0, y1)] if not mirror
               else [(x0, y0), (x1, y0), (x1, y1), (x0 + notch, y1), (x0, y1 - notch)])
        draw.polygon(pts, fill=fill, outline=outline)
    elif shape == 'slant':
        # Parallelogram — the badge itself leans, which is what gives a row a
        # sense of motion without disturbing the layout around it.
        lean = 9
        pts = ([(x0 + lean, y0), (x1 + lean, y0), (x1 - lean, y1), (x0 - lean, y1)] if not mirror
               else [(x0 - lean, y0), (x1 - lean, y0), (x1 + lean, y1), (x0 + lean, y1)])
        draw.polygon(pts, fill=fill, outline=outline)
    elif shape == 'outline':
        draw.rectangle(box, fill=None, outline=outline or fill, width=2)
    elif shape == 'block':
        draw.rectangle(box, fill=fill, outline=outline, width=1 if outline else 0)
    # 'none' draws no shape at all, just the numeral
    draw.text((cx, cy), text, font=font, fill=text_fill, anchor="mm",
              stroke_width=stroke, stroke_fill=text_fill if stroke else None)


def _render_ladder_themed(rows, our_team_name, opponent_name, division, subtitle, t):
    """Shared renderer for every theme-driven ladder style. See the notes above."""
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"
    up = (lambda s: s.upper()) if t.get('upper') else (lambda s: s)

    W = 1300
    row_h = t.get('row_h', 58)
    header_h = t.get('header_h', 160)
    n = len(rows)
    H = header_h + n * row_h + 20

    text = t['text']
    dim = t.get('dim', _shade(text, 0.65))
    pos = t.get('pos', text)
    neg = t.get('neg', text)
    badge_w = t.get('badge_w', 52)
    badge = t.get('badge', 'block')
    # Faux-bold weights for faces that ship Regular only (see
    # _draw_centered_name). 0 everywhere else, so nothing changes by default.
    name_stroke = t.get('name_stroke', 0)
    num_stroke = t.get('num_stroke', name_stroke)
    title_stroke = t.get('title_stroke', name_stroke)

    img = Image.new('RGB', (W, H), t['bg'])
    draw = ImageDraw.Draw(img)
    if t.get('bg_art'):
        t['bg_art'](img, draw, W, H, header_h)
        draw = ImageDraw.Draw(img)

    # --- header -----------------------------------------------------------
    title_text = up(f"{our_team_name} vs {opponent_name}")
    title_font = _fit_text(draw, title_text, t['font_title'], t.get('title_size', 40), 16,
                           W - t.get('title_pad', 90))
    sub_bits = [up(t.get('kicker', 'LADDER'))]
    if division:
        sub_bits.append(up(division))
    elif subtitle:
        sub_bits.append(up(subtitle))
    sub_text = "  •  ".join(sub_bits)
    sub_font = _fit_text(draw, sub_text, t.get('font_sub', t['font_name']), t.get('sub_size', 18), 11, W - 90)

    # Themes whose header art runs near the type can push the title and
    # kicker down rather than moving the art — gators' swept top band sits
    # just above the title and was clipping its ascenders.
    title_y = t.get('title_y', 46)
    sub_y = t.get('sub_y', 84)

    header_kind = t.get('header', 'bands')
    if header_kind == 'plate':
        draw.text((44, title_y), title_text, font=title_font, fill=text, anchor="lm",
                  stroke_width=title_stroke, stroke_fill=text if title_stroke else None)
        draw.text((44, sub_y - 2), sub_text, font=sub_font, fill=dim, anchor="lm")
    else:
        draw.text((W / 2, title_y), title_text, font=title_font, fill=text, anchor="mm",
                  stroke_width=title_stroke, stroke_fill=text if title_stroke else None)
        draw.text((W / 2, sub_y), sub_text, font=sub_font, fill=dim, anchor="mm")

    if header_kind == 'bands':
        by0, by1 = header_h - 56, header_h - 20
        band_l = t.get('band_l', pos)
        band_r = t.get('band_r', t.get('bg'))
        draw.rectangle([36, by0, W // 2 - 8, by1], fill=band_l)
        draw.rectangle([W // 2 + 8, by0, W - 36, by1], fill=band_r, outline=t.get('band_r_outline', band_l), width=2)
        lbl_font = _fit_text(draw, "OPPONENTS", t.get('font_label', t['font_name']),
                             t.get('label_size', 21), 11, W // 2 - 90)
        lbl_fill_l = t.get('band_text_l', t['bg'])
        lbl_fill_r = t.get('band_text_r', band_l)
        draw.text((36 + (W // 2 - 44) / 2, (by0 + by1) // 2), up(t.get('label_l', 'Our Team')),
                  font=lbl_font, fill=lbl_fill_l, anchor="mm",
                  stroke_width=title_stroke, stroke_fill=lbl_fill_l if title_stroke else None)
        draw.text((W // 2 + 8 + (W // 2 - 44) / 2, (by0 + by1) // 2), up(t.get('label_r', 'Opponents')),
                  font=lbl_font, fill=lbl_fill_r, anchor="mm",
                  stroke_width=title_stroke, stroke_fill=lbl_fill_r if title_stroke else None)
    elif header_kind == 'rule':
        draw.line([(44, header_h - 26), (W - 44, header_h - 26)], fill=t.get('sep', dim), width=2)

    # --- rows -------------------------------------------------------------
    name_font_max = t.get('name_size', 24)
    name_font_min = t.get('name_min', 13)
    num_font = _load_font(t['font_num'], t.get('num_size', 20))
    stat_font = _load_font(t.get('font_stat', _POSTER_FONT_ITALIC), t.get('stat_size', 16))
    diff_font = _load_font(t['font_num'], t.get('diff_size', t.get('num_size', 20)))

    gutter = t.get('gutter', _DIFF_GUTTER)
    our_col = (36 + badge_w + 14, W // 2 - gutter)
    opp_col = (W // 2 + gutter, W - 36 - badge_w - 14)
    stat_prefix = t.get('stat_prefix', 'DEF ')

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h - (6 if t.get('rows') == 'card' else 0)
        cy = (y0 + y1) // 2

        tint = t['row_tint'](f, i) if t.get('row_tint') else None
        row_kind = t.get('rows', 'alt')
        if row_kind == 'card':
            draw.rounded_rectangle([36, y0, W - 36, y1], radius=10,
                                   fill=tint or (t.get('row_a') if i % 2 == 0 else t.get('row_b')))
        elif row_kind == 'alt' or tint:
            draw.rectangle([36, y0, W - 36, y1], fill=tint or (t.get('row_a') if i % 2 == 0 else t.get('row_b')))
        if row_kind == 'line':
            draw.line([(36, y1), (W - 36, y1)], fill=t.get('sep', dim), width=1)

        _draw_slot_badge(draw, badge, [36, y0 + 6, 36 + badge_w, y1 - 6],
                         t.get('badge_l', pos), t.get('badge_l_outline'),
                         str(f['slot']), num_font, t.get('badge_text_l', t['bg']),
                         stroke=num_stroke)
        _draw_slot_badge(draw, badge, [W - 36 - badge_w, y0 + 6, W - 36, y1 - 6],
                         t.get('badge_r', t.get('bg')), t.get('badge_r_outline', t.get('badge_l', pos)),
                         str(f['slot']), num_font, t.get('badge_text_r', t.get('badge_l', pos)),
                         stroke=num_stroke, mirror=True)

        if t.get('divider'):
            draw.line([(W // 2, y0 + 6), (W // 2, cy - 15)], fill=t['divider'], width=2)
            draw.line([(W // 2, cy + 15), (W // 2, y1 - 6)], fill=t['divider'], width=2)

        _draw_centered_name(
            draw, up(f['our_ign']), f['our_stat'],
            sum(our_col) // 2, cy, our_col[0], our_col[1],
            lambda w: _fit_text(draw, up(f['our_ign']), t['font_name'], name_font_max, name_font_min, w),
            text, stat_font, t.get('our_stat_fill', pos), stat_side='right', stroke=name_stroke,
        )
        _draw_centered_name(
            draw, up(f['opp_ign']), f"{stat_prefix}{f['opp_stat']}" if f['opp_stat'] else None,
            sum(opp_col) // 2, cy, opp_col[0], opp_col[1],
            lambda w: _fit_text(draw, up(f['opp_ign']), t['font_name'], name_font_max, name_font_min, w),
            text, stat_font, t.get('opp_stat_fill', neg), stat_side='left', stroke=name_stroke,
        )
        _draw_diff(draw, f, W // 2, cy, diff_font, pos, neg, t.get('zero', dim), stroke=num_stroke)

        y += row_h

    return _to_png_buffer(img)


# --- background-art hooks, one per theme that has one ----------------------

def _draw_leaf(draw, x, y, length, width, angle_deg, color):
    """One laurel leaf: a pointed oval, drawn as a diamond rotated to angle."""
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    px, py = -dy, dx
    draw.polygon([
        (x, y),
        (x + dx * length * 0.45 + px * width * 0.5, y + dy * length * 0.45 + py * width * 0.5),
        (x + dx * length, y + dy * length),
        (x + dx * length * 0.45 - px * width * 0.5, y + dy * length * 0.45 - py * width * 0.5),
    ], fill=color)


def _laurel_layer(L, color, leaves=9):
    """
    One laurel branch on an RGBA layer: a curved stem sweeping up and to the
    left, leaves alternating either side and tapering toward the tip, a curl
    at the tip and two berries at the base.

    Drawn supersampled and downscaled because PIL antialiases neither
    polygons nor lines, and a laurel is nothing but diagonals — at 1x the
    leaves come out visibly stair-stepped.

    Returned as a layer specifically so the facing pair is a
    FLIP_LEFT_RIGHT of this one. Generating the second branch by negating
    coordinates instead produces a 180-degree rotation, which reads as two
    branches pointing the same way round rather than as a wreath.
    """
    S = L * _ART_SUPERSAMPLE
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = tuple(color) + (255,)

    # Quadratic bezier stem
    p0, p1, p2 = (0.80 * S, 0.96 * S), (0.10 * S, 0.80 * S), (0.30 * S, 0.06 * S)

    def bez(t):
        u = 1 - t
        return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])

    d.line([bez(i / 60) for i in range(61)], fill=c,
           width=max(2, int(S * 0.016)), joint='curve')

    for i in range(leaves):
        t = 0.10 + (0.86 - 0.10) * (i / (leaves - 1))
        x, y = bez(t)
        nx, ny = bez(min(t + 0.02, 1.0))
        tangent = math.degrees(math.atan2(ny - y, nx - x))
        size = S * 0.30 * (1.0 - 0.45 * t)
        side = 1 if i % 2 == 0 else -1
        _draw_leaf(d, x, y, size, size * 0.40, tangent + side * 46, c)

    tipx, tipy = bez(0.97)
    d.arc([tipx - 0.09 * S, tipy - 0.09 * S, tipx + 0.05 * S, tipy + 0.05 * S],
          start=20, end=250, fill=c, width=max(2, int(S * 0.013)))
    bx, by = bez(0.06)
    for ox, oy in ((0.045, -0.02), (0.085, 0.01)):
        r = S * 0.016
        d.ellipse([bx + ox * S - r, by + oy * S - r, bx + ox * S + r, by + oy * S + r], fill=c)

    return img.resize((L, L), Image.LANCZOS)


def _paste_laurel(img, cx, cy, size, color, facing=1):
    """Paste a laurel centred on (cx, cy); facing=-1 mirrors it horizontally."""
    layer = _laurel_layer(size, color)
    if facing < 0:
        layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
    img.paste(layer, (int(cx - size / 2), int(cy - size / 2)), layer)



def _helmet_layer(size, color, width=None):
    """
    RGBA layer holding a blank side-profile football helmet facing right:
    domed shell, jaw behind the ear, a bite taken out of the lower front for
    the face opening, and a two-bar facemask with a chin bar.

    Built as a filled silhouette on its own layer rather than outline arcs
    drawn straight onto the image — an outline version was tried first and
    read as a circle with an eye rather than a helmet. Having it on a layer
    also means the mirrored copy is a flip rather than a second set of
    hand-mirrored coordinates.
    """
    L = size
    width = width or max(3, int(L * 0.055))
    img = Image.new('RGBA', (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = tuple(color) + (255,)
    clear = (0, 0, 0, 0)

    d.ellipse([0.05 * L, 0.04 * L, 0.80 * L, 0.78 * L], fill=c)
    d.rectangle([0.05 * L, 0.36 * L, 0.50 * L, 0.66 * L], fill=c)
    d.pieslice([0.05 * L, 0.36 * L, 0.50 * L, 0.84 * L], start=0, end=180, fill=c)
    # Face opening — what separates a helmet from a plain circle
    d.pieslice([0.26 * L, 0.24 * L, 1.10 * L, 1.02 * L], start=238, end=372, fill=clear)
    d.ellipse([0.24 * L, 0.36 * L, 0.40 * L, 0.52 * L], fill=clear)
    # Facemask
    d.line([(0.40 * L, 0.56 * L), (0.90 * L, 0.52 * L)], fill=c, width=width)
    d.line([(0.34 * L, 0.72 * L), (0.86 * L, 0.68 * L)], fill=c, width=width)
    d.line([(0.89 * L, 0.50 * L), (0.86 * L, 0.70 * L)], fill=c, width=width)
    d.line([(0.34 * L, 0.72 * L), (0.20 * L, 0.66 * L)], fill=c, width=width)
    return img


def _paste_helmet(img, cx, cy, size, color, facing=1):
    """Paste a helmet decal centred on (cx, cy); facing=-1 mirrors it."""
    layer = _helmet_layer(size, color)
    if facing < 0:
        layer = layer.transpose(Image.FLIP_LEFT_RIGHT)
    img.paste(layer, (int(cx - size / 2), int(cy - size / 2)), layer)

def _art_hazard_stripes(img, draw, W, H, header_h):
    for i in range(-2, W // 36 + 4):
        x = i * 36
        draw.polygon([(x, 0), (x + 18, 0), (x + 18 - 24, 24), (x - 24, 24)], fill=(250, 204, 21))
        draw.polygon([(x, H - 24), (x + 18, H - 24), (x + 18 - 24, H), (x - 24, H)], fill=(250, 204, 21))


def _art_dot_matrix(img, draw, W, H, header_h):
    for gy in range(6, H, 6):
        for gx in range(6, W, 6):
            draw.point((gx, gy), fill=(30, 26, 14))


def _art_stars(img, draw, W, H, header_h):
    import random
    rnd = random.Random(7)  # seeded: the same ladder must render identically every time
    for _ in range(420):
        x, y = rnd.randrange(W), rnd.randrange(H)
        b = rnd.choice([70, 110, 160, 220])
        r = 1 if b < 160 else 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(b, b, min(255, b + 30)))
    draw.arc([-300, header_h - 420, W + 300, header_h + 120], start=0, end=180, fill=(60, 80, 170), width=3)


def _art_circuit(img, draw, W, H, header_h):
    import random
    rnd = random.Random(11)
    for _ in range(26):
        x = rnd.randrange(60, W - 60)
        y = rnd.randrange(10, H - 10)
        run = rnd.choice([70, 110, 160])
        draw.line([(x, y), (x + run, y)], fill=(16, 52, 62), width=2)
        draw.line([(x + run, y), (x + run + 24, y + rnd.choice([-24, 24]))], fill=(16, 52, 62), width=2)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(24, 82, 92))


def _art_speckle(img, draw, W, H, header_h):
    import random
    rnd = random.Random(3)
    for _ in range(2600):
        x, y = rnd.randrange(W), rnd.randrange(H)
        draw.point((x, y), fill=(198, 186, 158))


def _art_pixel_grid(img, draw, W, H, header_h):
    """LCD pixel grid — faint dark lines on the pale panel, matching the way
    a DMG screen's cell boundaries show through."""
    for x in range(0, W, 4):
        draw.line([(x, 0), (x, H)], fill=(142, 176, 20))
    for y in range(0, H, 4):
        draw.line([(0, y), (W, y)], fill=(142, 176, 20))


def _art_pastel_blobs(img, draw, W, H, header_h):
    import random
    rnd = random.Random(5)
    for _ in range(18):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r = rnd.choice([40, 70, 110])
        draw.ellipse([x - r, y - r, x + r, y + r],
                     fill=rnd.choice([(255, 235, 245), (235, 248, 255), (240, 255, 245)]))


def _art_paper_grid(img, draw, W, H, header_h):
    for x in range(0, W, 26):
        draw.line([(x, 0), (x, H)], fill=(238, 236, 228))
    for y in range(0, H, 26):
        draw.line([(0, y), (W, y)], fill=(238, 236, 228))
    # Doubled, slightly offset border, the way a hand-drawn box never closes twice the same
    draw.rectangle([22, 22, W - 22, H - 22], outline=(120, 120, 130), width=2)
    draw.rectangle([26, 25, W - 25, H - 26], outline=(170, 170, 180), width=1)


def _art_gold_rules(img, draw, W, H, header_h):  # noqa: D401 - img used for pasting
    """Gold frame, corner ticks, and a pair of laurel branches flanking the
    title — the laurels are what make the gold read as a trophy plate rather
    than just a dark table with a border."""
    gold = (212, 175, 55)
    draw.rectangle([18, 18, W - 18, H - 18], outline=gold, width=2)
    draw.rectangle([26, 26, W - 26, H - 26], outline=_shade(gold, 0.5), width=1)
    for cx, cy in ((26, 26), (W - 26, 26), (26, H - 26), (W - 26, H - 26)):
        draw.line([(cx - 14, cy), (cx + 14, cy)], fill=gold, width=2)
        draw.line([(cx, cy - 14), (cx, cy + 14)], fill=gold, width=2)
    # Laurels either side of the title, opening toward it — a true mirrored
    # pair (see _laurel_layer), spaced well apart and clear of the frame.
    laurel = _shade(gold, 0.95)
    _paste_laurel(img, 128, 72, 100, laurel, facing=1)
    _paste_laurel(img, W - 128, 72, 100, laurel, facing=-1)


def _art_gator_chomp(img, draw, W, H, header_h):
    """
    Team livery: a swept orange band along the very top, a soft two-tone
    diagonal through the header, an angled base rule, and a raking stripe
    down the right edge.

    Two things this deliberately does NOT do, both from feedback on an
    earlier version: it keeps every orange element clear of the title band
    (white type on that orange was hard to read), and it draws the diagonals
    supersampled rather than as 1x polygons (chevrons at 1x looked blocky).
    """
    SS = _ART_SUPERSAMPLE
    layer = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    orange = (250, 70, 22, 255)
    orange_lt = (255, 132, 70, 255)
    blue_lt = (9, 42, 158, 255)
    blue_dk = (2, 20, 96, 255)

    # Lighter blue wedge sweeping across the header — motion behind the
    # title without touching its contrast, both tones being dark blue.
    d.polygon([(0, 0), (W * SS, 0), (W * SS, int(0.62 * header_h * SS)),
               (0, int(0.92 * header_h * SS))], fill=blue_lt)
    # Top swept band, well above the title, plus a thin echo below it
    d.polygon([(0, 0), (W * SS, 0), (W * SS, 13 * SS), (0, 25 * SS)], fill=orange)
    d.polygon([(0, 30 * SS), (W * SS, 18 * SS), (W * SS, 23 * SS), (0, 35 * SS)], fill=orange_lt)
    # Angled base rule under the header — thin, so it reads as trim rather
    # than a second band competing with the two team bands above it
    d.polygon([(0, (header_h - 11) * SS), (W * SS, (header_h - 17) * SS),
               (W * SS, (header_h - 9) * SS), (0, (header_h - 3) * SS)], fill=orange)
    # Raking stripe off the right edge, starting below the header so it can't
    # notch the base rule
    d.polygon([((W - 150) * SS, header_h * SS), (W * SS, header_h * SS),
               (W * SS, H * SS), ((W - 240) * SS, H * SS)], fill=blue_dk)

    smooth = layer.resize((W, H), Image.LANCZOS)
    img.paste(smooth, (0, 0), smooth)



def _art_heat_angles(img, draw, W, H, header_h):
    """
    Angled header field for heatmap — diagonal wedges either side of the
    midline, so the board reads as two opposing sides rather than a grid.
    Supersampled for the same reason the other diagonal art is.
    """
    SS = _ART_SUPERSAMPLE
    layer = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    hh = (header_h - 20) * SS
    d.polygon([(0, 0), ((W // 2 - 40) * SS, 0), ((W // 2 - 120) * SS, hh), (0, hh)],
              fill=(24, 30, 26, 255))
    d.polygon([((W // 2 + 40) * SS, 0), (W * SS, 0), (W * SS, hh), ((W // 2 - 40) * SS, hh)],
              fill=(32, 24, 26, 255))
    d.polygon([((W // 2 - 44) * SS, 0), ((W // 2 + 44) * SS, 0),
               ((W // 2 - 36) * SS, hh), ((W // 2 - 124) * SS, hh)], fill=(44, 44, 52, 255))
    smooth = layer.resize((W, H), Image.LANCZOS)
    img.paste(smooth, (0, 0), smooth)


def _heat_tint(f, i):
    """Row background scaled by how lopsided the matchup is — the diff
    column's own number, turned into colour. Neutral when it's unknown."""
    if f['diff_val'] is None:
        return (26, 26, 30)
    d = max(-15, min(15, f['diff_val']))
    if d >= 0:
        k = d / 15
        return (int(20 + 10 * k), int(26 + 74 * k), int(30 + 28 * k))
    k = -d / 15
    return (int(30 + 80 * k), int(24 + 14 * k), int(28 + 18 * k))


_LADDER_THEMES = {
    # Blue and orange, as asked for — Florida's livery.
    'gators': dict(
        # Florida's actual pair: #0021A5 blue, #FA4616 orange. The rows sit a
        # little either side of the true blue so alternating rows read at all
        # while the overall field stays on the real colour.
        bg=(3, 26, 124), row_a=(0, 33, 165), row_b=(4, 28, 143), text=(255, 255, 255),
        dim=(186, 205, 250), pos=(250, 110, 40), neg=(255, 190, 120), zero=(205, 220, 252),
        # Audiowide, not Bebas: the blocky all-caps slab read as a spreadsheet
        # with team colours. This one has movement to it, and keeps lowercase
        # so IGN casing survives.
        font_title=_FONT_AUDIOWIDE, font_name=_FONT_AUDIOWIDE, font_num=_FONT_AUDIOWIDE,
        title_size=40, name_size=22, num_size=19, label_size=19, sub_size=16,
        # Header is taller than the default so the title clears the swept
        # band above it and the kicker still clears the team bands below.
        title_y=58, sub_y=92, header_h=176,
        # White on this orange measured poorly for contrast and was called
        # out as hard to read, so the home band is now light with navy type
        # and the orange is reserved for fills behind dark text.
        header='bands', band_l=(244, 246, 255), band_r=(3, 26, 124), band_text_l=(4, 24, 110),
        band_text_r=(255, 132, 70), band_r_outline=(250, 70, 22),
        label_l='Gators', label_r='Seminoles',
        badge='slant', badge_l=(250, 70, 22), badge_text_l=(8, 20, 78),
        badge_r=(3, 26, 124), badge_r_outline=(250, 70, 22), badge_text_r=(250, 140, 60),
        divider=(40, 70, 170), kicker='Swamp Ladder', bg_art=_art_gator_chomp,
    ),
    'ledboard': dict(
        bg=(8, 8, 6), row_a=(16, 15, 10), row_b=(12, 11, 8), text=(255, 176, 0),
        dim=(140, 96, 10), pos=(120, 255, 130), neg=(255, 90, 70), zero=(200, 150, 40),
        font_title=_FONT_BITCOUNT, font_name=_FONT_BITCOUNT, font_num=_FONT_BITCOUNT,
        title_size=36, name_size=23, num_size=21, sub_size=17, label_size=18,
        header='bands', band_l=(255, 176, 0), band_r=(8, 8, 6), band_text_l=(8, 8, 6),
        badge='outline', badge_l=(255, 176, 0), badge_l_outline=(255, 176, 0),
        badge_text_l=(255, 176, 0), badge_text_r=(255, 176, 0),
        divider=(60, 44, 8), kicker='Board', bg_art=_art_dot_matrix,
        font_stat=_FONT_BITCOUNT, stat_size=15,
    ),
    'dossier': dict(
        bg=(224, 212, 186), row_a=(215, 202, 173), row_b=(224, 212, 186), text=(44, 38, 32),
        dim=(112, 100, 84), pos=(38, 78, 44), neg=(158, 42, 30), zero=(92, 82, 70),
        font_title=_FONT_SPECIAL_ELITE, font_name=_FONT_SPECIAL_ELITE, font_num=_FONT_SPECIAL_ELITE,
        title_size=38, name_size=23, num_size=20, sub_size=17,
        header='plate', badge='block', badge_l=(44, 38, 32), badge_text_l=(224, 212, 186),
        badge_r=(224, 212, 186), badge_r_outline=(158, 42, 30), badge_text_r=(158, 42, 30),
        rows='line', sep=(190, 176, 148), divider=(190, 176, 148),
        kicker='Scouting File', bg_art=_art_speckle, font_stat=_FONT_SPECIAL_ELITE,
    ),
    'gameboy': dict(
        # The real DMG panel is dark ink on a pale yellow-green LCD, not light
        # text on dark green — inverting it fixes both the muddy look and the
        # contrast. Palette is the actual DMG four: 9bbc0f / 8bac0f / 306230 /
        # 0f380f.
        bg=(155, 188, 15), row_a=(139, 172, 15), row_b=(155, 188, 15), text=(15, 56, 15),
        dim=(48, 98, 48),
        # Two of the four DMG shades, both dark enough to read on the panel:
        # darkest for positive, mid-dark for negative. (The earlier dark-panel
        # version couldn't do this — nothing had enough contrast — so both
        # signs shared one colour.)
        pos=(15, 56, 15), neg=(48, 98, 48), zero=(48, 98, 48),
        our_stat_fill=(48, 98, 48), opp_stat_fill=(48, 98, 48),
        # Deliberately NO stroke here, unlike the other Regular-only faces: a
        # 1px outline on a thin pixel font at this size fills in the letter
        # counters, and names came out smudged ("scotty" reading as "ecotty",
        # slot 16 as 18). Inverting the panel to dark-on-light already gives
        # the weight that was missing; size does the rest.
        font_title=_FONT_DOTGOTHIC, font_name=_FONT_DOTGOTHIC, font_num=_FONT_DOTGOTHIC,
        title_size=36, name_size=23, num_size=21, sub_size=17, label_size=18,
        header='bands', band_l=(15, 56, 15), band_r=(155, 188, 15),
        band_text_l=(155, 188, 15), band_text_r=(15, 56, 15), band_r_outline=(15, 56, 15),
        badge='block', badge_l=(15, 56, 15), badge_text_l=(155, 188, 15),
        badge_r=(155, 188, 15), badge_r_outline=(15, 56, 15), badge_text_r=(15, 56, 15),
        divider=(48, 98, 48), kicker='Link Cable', bg_art=_art_pixel_grid,
        font_stat=_FONT_DOTGOTHIC, stat_size=16,
    ),
    'cyberdeck': dict(
        bg=(6, 18, 26), row_a=(10, 30, 40), row_b=(8, 24, 33), text=(205, 250, 245),
        dim=(90, 150, 155), pos=(0, 230, 200), neg=(175, 125, 255), zero=(120, 170, 175),
        font_title=_FONT_AUDIOWIDE, font_name=_FONT_AUDIOWIDE, font_num=_FONT_AUDIOWIDE,
        title_size=34, name_size=21, num_size=18, sub_size=16, label_size=17,
        header='bands', band_l=(0, 200, 175), band_r=(6, 18, 26), band_text_l=(6, 18, 26),
        band_text_r=(175, 125, 255), band_r_outline=(175, 125, 255),
        badge='pill', badge_l=(0, 200, 175), badge_text_l=(6, 18, 26),
        badge_r=(6, 18, 26), badge_r_outline=(175, 125, 255), badge_text_r=(175, 125, 255),
        divider=(20, 70, 80), kicker='Uplink', bg_art=_art_circuit,
    ),
    'starfield': dict(
        bg=(8, 10, 32), row_a=(15, 18, 48), row_b=(11, 14, 40), text=(228, 232, 255),
        dim=(130, 140, 190), pos=(255, 215, 120), neg=(130, 175, 255), zero=(170, 178, 220),
        font_title=_FONT_NOVA_SQUARE, font_name=_FONT_NOVA_SQUARE, font_num=_FONT_NOVA_SQUARE,
        title_size=38, name_size=23, num_size=20,
        header='bands', band_l=(255, 215, 120), band_r=(8, 10, 32), band_text_l=(8, 10, 32),
        band_text_r=(255, 215, 120),
        badge='pill', badge_l=(255, 215, 120), badge_text_l=(8, 10, 32),
        badge_r=(8, 10, 32), badge_r_outline=(130, 175, 255), badge_text_r=(130, 175, 255),
        divider=(40, 48, 100), kicker='Orbit', bg_art=_art_stars,
    ),
    'hazard': dict(
        bg=(26, 25, 22), row_a=(34, 32, 27), row_b=(29, 27, 23), text=(246, 242, 228),
        dim=(150, 145, 128), pos=(250, 204, 21), neg=(240, 120, 60), zero=(190, 184, 160),
        font_title=_FONT_WALLPOET, font_name=_FONT_WALLPOET, font_num=_FONT_WALLPOET,
        # Wallpoet measures 0.80x the baseline cap height, hence the larger numbers here
        title_size=46, name_size=30, name_min=16, num_size=26, sub_size=22, label_size=24,
        header_h=178, header='bands', band_l=(250, 204, 21), band_r=(26, 25, 22),
        band_text_l=(26, 25, 22), band_text_r=(250, 204, 21),
        badge='tag', badge_l=(250, 204, 21), badge_text_l=(26, 25, 22),
        badge_r=(40, 38, 32), badge_text_r=(250, 204, 21),
        divider=(70, 66, 54), kicker='Caution', bg_art=_art_hazard_stripes,
    ),
    'bubble': dict(
        bg=(255, 250, 252), row_a=(255, 238, 244), row_b=(240, 249, 255), text=(62, 52, 74),
        dim=(148, 138, 162), pos=(236, 72, 132), neg=(45, 190, 165), zero=(150, 140, 165),
        # Keania One throughout, including names and numbers. Its '8' is
        # genuinely hard to tell from its 'S' (so GCrane8Cowboys reads as
        # GCraneSCowboys) — that was raised and the look was explicitly
        # preferred over the ambiguity, unlike carnival/Honk where the
        # reliable font stayed. Don't "fix" this back without asking.
        font_title=_FONT_KEANIA, font_label=_FONT_KEANIA,
        font_name=_FONT_KEANIA, font_num=_FONT_KEANIA,
        title_size=42, name_size=25, num_size=21,
        header='bands', band_l=(236, 72, 132), band_r=(255, 250, 252), band_text_l=(255, 255, 255),
        band_text_r=(236, 72, 132), band_r_outline=(45, 190, 165),
        badge='pill', badge_l=(236, 72, 132), badge_text_l=(255, 255, 255),
        badge_r=(255, 250, 252), badge_r_outline=(45, 190, 165), badge_text_r=(45, 190, 165),
        rows='card', divider=None, kicker='Bubble Ladder', bg_art=_art_pastel_blobs,
    ),
    'sketch': dict(
        bg=(250, 249, 244), row_a=(255, 255, 252), row_b=(245, 244, 238), text=(52, 52, 58),
        dim=(130, 130, 140), pos=(48, 108, 78), neg=(170, 60, 50), zero=(120, 120, 130),
        font_title=_FONT_SYNE_MONO, font_name=_FONT_SYNE_MONO, font_num=_FONT_SYNE_MONO,
        # Syne Mono measures 0.87x the baseline cap height
        title_size=40, name_size=26, name_min=15, num_size=22, sub_size=20,
        header='rule', sep=(160, 160, 170),
        badge='outline', badge_l=(90, 110, 200), badge_l_outline=(90, 110, 200),
        badge_text_l=(52, 52, 58), badge_r_outline=(160, 160, 170), badge_text_r=(90, 90, 100),
        rows='line', divider=(196, 196, 206), kicker='Rough Draft', bg_art=_art_paper_grid,
        font_stat=_FONT_SYNE_MONO,
    ),
    'prestige': dict(
        bg=(12, 10, 8), row_a=(23, 20, 15), row_b=(17, 15, 11), text=(246, 239, 222),
        dim=(150, 136, 104), pos=(212, 175, 55), neg=(196, 122, 96), zero=(170, 156, 124),
        font_title=_FONT_GRADUATE, font_name=_FONT_GRADUATE, font_num=_FONT_GRADUATE,
        title_size=46, name_size=25, num_size=21, upper=True,
        # Reserve room either side so a long matchup title can't run under
        # the laurel decals.
        title_pad=340,
        header_h=172, header='bands', band_l=(212, 175, 55), band_r=(12, 10, 8),
        band_text_l=(12, 10, 8), band_text_r=(212, 175, 55),
        badge='block', badge_l=(212, 175, 55), badge_text_l=(12, 10, 8),
        badge_r=(20, 17, 13), badge_r_outline=(212, 175, 55), badge_text_r=(212, 175, 55),
        divider=(70, 60, 40), kicker='Title Bout', bg_art=_art_gold_rules,
    ),
    'paper': dict(
        bg=(252, 251, 247), row_a=(255, 255, 253), row_b=(246, 245, 240), text=(34, 34, 38),
        dim=(120, 118, 112), pos=(28, 88, 58), neg=(150, 36, 30), zero=(120, 118, 112),
        font_title=_FONT_NEWSREADER, font_name=_FONT_NEWSREADER, font_num=_FONT_NEWSREADER,
        font_stat=_FONT_NEWSREADER_IT, title_size=44, name_size=25, num_size=20, sub_size=19,
        header='rule', sep=(206, 204, 196),
        badge='none', badge_text_l=(150, 36, 30), badge_text_r=(150, 36, 30), badge_w=40,
        rows='line', divider=(224, 222, 214), kicker='The Ledger',
    ),
    'heatmap': dict(
        bg=(18, 18, 21), text=(240, 240, 244), dim=(140, 140, 150),
        pos=(120, 235, 160), neg=(255, 130, 120), zero=(200, 200, 210),
        font_title=_FONT_ANTON, font_name=_FONT_ANTON, font_num=_FONT_ANTON,
        # Bigger, not stroked: Anton is already a heavy condensed face and a
        # 1px outline closed up its counters ("Ruffis" read as "Buffis",
        # "Rob926" as "Bob926"). Stroke only helps genuinely light faces.
        title_size=46, name_size=27, num_size=23,
        header='bands', band_l=(120, 235, 160), band_r=(18, 18, 21), band_text_l=(18, 18, 21),
        band_text_r=(255, 130, 120), label_l='Favoured', label_r='Underdog',
        badge='slant', badge_l=(52, 52, 60), badge_text_l=(240, 240, 244),
        badge_r=(52, 52, 60), badge_r_outline=None, badge_text_r=(240, 240, 244),
        divider=(70, 70, 80), kicker='Mismatch Map', row_tint=_heat_tint,
        bg_art=_art_heat_angles,
    ),
}


def _to_png_buffer(img):
    """Save a finished image to a fresh BytesIO and rewind it."""
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def render_scores_grid(title, dates, roster_rows):
    """
    Render a players-by-dates score grid as a PNG and return a BytesIO buffer.
    dates:       ordered list of ISO date strings, one per column.
    roster_rows: list of dicts, one per player row:
                 {'ign': str, 'scores': {date: cell_text_or_None}}
    A blank cell (no score recorded that date) renders as '--'.
    """
    headers = ['Player'] + [d[5:] for d in dates]  # 'YYYY-MM-DD' -> 'MM-DD'
    aligns  = ['L'] + ['R'] * len(dates)

    rows = []
    for r in roster_rows:
        row = [r['ign']]
        for d in dates:
            cell = r['scores'].get(d)
            row.append(cell if cell is not None else '--')
        rows.append(row)

    return _render_table(title, headers, rows, aligns)


def clear_cache(**kwargs):
    """No-op kept for call-site compatibility."""
    pass
