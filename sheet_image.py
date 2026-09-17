"""
sheet_image.py — Render rank tables and ladder tables as PNG images using Pillow.
Sends as a Discord file attachment so they render correctly on all screen sizes.
"""

import io
import os
import discord
from PIL import Image, ImageDraw, ImageFont
from logger_config import global_logger as logger
import db

LEAGUE_NAMES = {
    'NP': 'NeuroPerverse', 'ND': 'NeuroDiverse', 'NI': 'NeuroInverse',
    'NA': 'NeuroAdverse',  'NR': 'NeuroReverse',  'NC': 'NeuroChaos',
    'NT': 'NeuroTraverse', 'NX': 'NeuroChristians',
}

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


def _render_table(title, headers, rows, aligns=None, subtitle=None):
    """
    Render a table as a PNG and return a BytesIO buffer.
    subtitle: optional secondary line rendered smaller and italicized below
    the main title (e.g. "Ladder (snapshot 2026-07-20)").
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
        tx = x + PAD_X if aligns[j] == 'L' else x + cw - PAD_X - tw(hdr, font_bold)
        draw.text((tx, title_h + PAD_Y), hdr, font=font_bold, fill=HEADER_FG)
        x += cw

    # Data rows
    for i, row in enumerate(rows):
        y    = title_h + row_h + i * row_h
        fill = ROW_ALT if i % 2 == 0 else PANEL
        draw.rectangle([PAD_X - 4, y, img_w - PAD_X + 4, y + row_h], fill=fill)
        x = PAD_X
        for j, (cell, cw) in enumerate(zip(row, col_widths)):
            tx = x + PAD_X if aligns[j] == 'L' else x + cw - PAD_X - tw(cell)
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

async def send_rank_image(ctx, team_id, conn=None, season_label=None, **kwargs):
    """Fetch roster from DB, render as PNG, send as file.
    conn: optional archive connection (see db.get_archive_conn) for /legacy.
    season_label: optional suffix for the title, e.g. "(2026 Season)"."""
    try:
        players = await db.get_rank_table(team_id, conn=conn)
        if not players:
            await ctx.send(f"No active roster data found for `{team_id}`.")
            return

        league  = LEAGUE_NAMES.get(team_id, team_id)
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


async def send_stats_image(ctx, team_id, include_inactive=False, conn=None, season_label=None):
    """
    League stats as a PNG — stat categories across the top, one row per
    player underneath (same layout as /rank), plus a final League Avg row
    summarizing the whole league.
    conn/season_label: see send_rank_image.
    """
    try:
        stats = await db.get_league_stats(team_id, include_inactive=include_inactive, conn=conn)
        if not stats:
            await ctx.send(f"No stats found for `{team_id}`.")
            return

        league  = LEAGUE_NAMES.get(team_id, team_id)
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
    team-vs-team poster), 'clean' (minimal modern cards), 'scoreboard'
    (bold flat-color broadcast style), 'tactical' (military/esports, Black
    Ops One), 'varsity' (collegiate athletics, Graduate), 'arcade' (retro
    8-bit, Press Start 2P), 'street' (urban/graffiti, Bungee Inline),
    'carnival' (playful, Honk), or 'championship' (gold 3D, Nabla).
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
    elif style == 'championship':
        return _render_ladder_championship(rows, our_team_name, opponent_name, division, subtitle)
    return _render_ladder_classic(title, rows, subtitle=subtitle)


def _render_ladder_classic(title, rows, subtitle=None):
    """The original data-dense table style — every column, no team header art."""
    headers = ['#', 'Our Player', 'Ladder Rank', 'Off OVR', 'Opponent', 'Opp TOT', 'Opp DEF', '+/-', 'Result']
    aligns  = ['R', 'L',          'R',            'R',       'L',        'R',        'R',       'R',   'L']

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
    """Shared field extraction for the three poster-style renderers."""
    our_stat = r.get('ladder_rank') or r.get('our_off_ovr')
    opp_stat = r.get('opp_def_ovr') or r.get('def_ovr')
    result_str = None
    if r.get('result'):
        pts = f" {r.get('our_pts', 0)}-{r.get('opp_pts', 0)}" if r.get('our_pts') is not None else ''
        result_str = f"{r['result']}{pts}"
    return {
        'slot': r['slot'],
        'our_ign': r.get('our_ign') or '—',
        'our_stat': f"{our_stat:.1f}" if isinstance(our_stat, float) else (str(our_stat) if our_stat else None),
        'opp_ign': r.get('opp_ign') or '—',
        'opp_stat': str(opp_stat) if opp_stat else None,
        'result': result_str,
    }


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
    Bold hexagon-badge team-vs-team poster, purple vs blue, with glow effects.
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
    title_font = _fit_text(draw, title_text, _POSTER_FONT_BOLD, 44, 24, W - 70)
    _draw_text_glow(img, (W / 2, 32), title_text, title_font, (255, 255, 255), PURPLE2, glow_radius=8, glow_alpha=130)
    draw = ImageDraw.Draw(img)
    if division or subtitle:
        sub_font = _load_font(_POSTER_FONT_BOLD, 19)
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
    our_label_font = _fit_text(draw, "OUR TEAM", _POSTER_FONT_BOLD, 28, 16, left_w)
    opp_label_font = _fit_text(draw, "OPPONENTS", _POSTER_FONT_BOLD, 28, 16, right_w)
    sub_team_font = _fit_text(draw, our_team_name, _POSTER_FONT_REG, 16, 10, left_w)
    sub_opp_font = _fit_text(draw, opponent_name, _POSTER_FONT_REG, 16, 10, right_w)
    draw.text((24 + (mid - 40 - 24) / 2, (hy0 + hy1) // 2 - 12), "OUR TEAM", font=our_label_font, fill=(255, 255, 255), anchor="mm")
    draw.text((24 + (mid - 40 - 24) / 2, (hy0 + hy1) // 2 + 15), our_team_name, font=sub_team_font, fill=(230, 215, 255), anchor="mm")
    draw.text((mid + 40 + (W - 24 - mid - 40) / 2, (hy0 + hy1) // 2 - 12), "OPPONENTS", font=opp_label_font, fill=(255, 255, 255), anchor="mm")
    draw.text((mid + 40 + (W - 24 - mid - 40) / 2, (hy0 + hy1) // 2 + 15), opponent_name, font=sub_opp_font, fill=(210, 230, 255), anchor="mm")

    vs_font = _load_font(_POSTER_FONT_BOLD, 36)
    _draw_text_glow(img, (mid, (hy0 + hy1) // 2), "VS", vs_font, (255, 255, 255), (255, 255, 255), glow_radius=8, glow_alpha=190)
    draw = ImageDraw.Draw(img)

    rank_font = _load_font(_POSTER_FONT_BOLD, 26)

    def hex_badge(cx, cy, r, fill, text, point_dir):
        if point_dir == 1:
            pts = [(cx - r, cy - r), (cx + r * 0.5, cy - r), (cx + r, cy), (cx + r * 0.5, cy + r), (cx - r, cy + r)]
        else:
            pts = [(cx - r * 0.5, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r * 0.5, cy + r), (cx - r, cy)]
        draw.polygon(pts, fill=fill)
        draw.polygon(pts, outline=(255, 255, 255), width=2)
        draw.text((cx, cy), text, font=rank_font, fill=(255, 255, 255), anchor="mm")

    name_max_w = mid - 24 - 100 - 24 - 120  # rough space left for name+stat between badge and center

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h - 5
        cy = (y0 + y1) // 2
        row_bg_l = (34, 20, 54) if i % 2 == 0 else (24, 14, 40)
        row_bg_r = (14, 26, 54) if i % 2 == 0 else (10, 18, 38)
        draw.rounded_rectangle([24, y0, mid - 6, y1], radius=9, fill=row_bg_l)
        draw.rounded_rectangle([mid + 6, y0, W - 24, y1], radius=9, fill=row_bg_r)
        draw.rounded_rectangle([24, y0, mid - 6, y1], radius=9, outline=(90, 50, 140), width=1)
        draw.rounded_rectangle([mid + 6, y0, W - 24, y1], radius=9, outline=(40, 80, 150), width=1)

        hex_badge(52, cy, 22, PURPLE2, str(f['slot']), 1)
        name_font = _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, 27, 14, name_max_w)
        draw.text((100, cy), f['our_ign'], font=name_font, fill=(245, 245, 250), anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=name_font)
            stat_font = _load_font(_POSTER_FONT_ITALIC, 20)
            draw.text((100 + ow + 12, cy), f"({f['our_stat']})", font=stat_font, fill=(200, 175, 255), anchor="lm")

        hex_badge(W - 52, cy, 22, BLUE2, str(f['slot']), -1)
        name_font_r = _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, 27, 14, name_max_w)
        stat_text = f"(DEF {f['opp_stat']})" if f['opp_stat'] else ""
        stat_font = _load_font(_POSTER_FONT_ITALIC, 20)
        stat_w = draw.textlength(stat_text, font=stat_font) if stat_text else 0
        name_w = draw.textlength(f['opp_ign'], font=name_font_r)
        gap = 12 if stat_text else 0
        start_x = W - 100 - name_w - gap - stat_w
        draw.text((start_x, cy), f['opp_ign'], font=name_font_r, fill=(245, 245, 250), anchor="lm")
        if stat_text:
            draw.text((start_x + name_w + gap, cy), stat_text, font=stat_font, fill=(170, 205, 255), anchor="lm")

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

        cx = W // 2
        draw.ellipse([cx - 19, cy - 19, cx + 19, cy + 19], fill=(46, 44, 60))
        draw.ellipse([cx - 19, cy - 19, cx + 19, cy + 19], outline=(80, 78, 100), width=2)
        draw.text((cx, cy), str(f['slot']), font=rank_font, fill=TEXT_MAIN, anchor="mm")

        right_edge = cx - 34
        our_font = _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, 25, 14, side_max_w)
        draw.text((right_edge, cy), f['our_ign'], font=our_font, fill=TEXT_MAIN, anchor="rm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=our_font)
            draw.text((right_edge - ow - 12, cy), f"{f['our_stat']}", font=stat_font, fill=(190, 175, 255), anchor="rm")

        left_edge = cx + 34
        opp_font = _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, 25, 14, side_max_w)
        draw.text((left_edge, cy), f['opp_ign'], font=opp_font, fill=TEXT_MAIN, anchor="lm")
        if f['opp_stat']:
            ow2 = draw.textlength(f['opp_ign'], font=opp_font)
            draw.text((left_edge + ow2 + 12, cy), f"DEF {f['opp_stat']}", font=stat_font, fill=(255, 175, 205), anchor="lm")

        y += row_h + row_gap

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_scoreboard(rows, our_team_name, opponent_name, division, subtitle):
    """
    Bold flat-color broadcast style, orange vs teal, with diagonal cuts for
    energy. Deliberately tight — see _render_ladder_neon's docstring for why.
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

    title_font = _load_font(_POSTER_FONT_BOLD, 42)
    _draw_text_shadow(draw, (36, 40), "LADDER MATCHUPS", title_font, TEXT_MAIN, offset=(3, 3))
    sub_text = f"{our_team_name_disp}   vs   {opponent_name_disp}"
    if division or subtitle:
        sub_text += f"   •   {(division or subtitle).upper()}"
    sub_font = _fit_text(draw, sub_text, _POSTER_FONT_BOLD, 19, 13, W - 72)
    draw.text((36, 74), sub_text, font=sub_font, fill=TEXT_DIM, anchor="lm")

    band_y0, band_y1 = 100, 140
    cut = 28
    mid = W // 2
    draw.polygon([(0, band_y0), (mid + cut, band_y0), (mid - cut, band_y1), (0, band_y1)], fill=ORANGE1)
    draw.polygon([(mid + cut, band_y0), (W, band_y0), (W, band_y1), (mid - cut, band_y1)], fill=TEAL1)
    band_font_l = _fit_text(draw, "OUR TEAM", _POSTER_FONT_BOLD, 22, 14, mid - 72)
    band_font_r = _fit_text(draw, "OPPONENTS", _POSTER_FONT_BOLD, 22, 14, mid - 72)
    draw.text((36, (band_y0 + band_y1) // 2), "OUR TEAM", font=band_font_l, fill=(20, 15, 10), anchor="lm")
    draw.text((W - 36, (band_y0 + band_y1) // 2), "OPPONENTS", font=band_font_r, fill=(6, 24, 24), anchor="rm")

    rank_font = _load_font(_POSTER_FONT_BOLD, 26)
    stat_font = _load_font(_POSTER_FONT_ITALIC, 18)
    name_font_base_size = 24
    name_max_w = mid - 78 - 90

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([0, y0, W, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        # Angled rank block instead of a plain rectangle
        draw.polygon([(0, y0), (56, y0), (44, y1), (0, y1)], fill=ORANGE1)
        draw.text((24, cy), str(f['slot']), font=rank_font, fill=(20, 15, 10), anchor="mm")

        name_font = _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, name_font_base_size, 14, name_max_w)
        draw.text((78, cy), f['our_ign'], font=name_font, fill=TEXT_MAIN, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=name_font)
            draw.text((78 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=ORANGE2, anchor="lm")

        draw.line([(mid, y0 + 6), (mid, y1 - 6)], fill=(70, 70, 78), width=2)

        name_font_r = _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, name_font_base_size, 14, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        stat_w = draw.textlength(stat_text, font=stat_font) if stat_text else 0
        name_w = draw.textlength(f['opp_ign'], font=name_font_r)
        end_x = W - 78
        draw.text((end_x, cy), f['opp_ign'], font=name_font_r, fill=TEXT_MAIN, anchor="rm")
        if stat_text:
            draw.text((end_x - name_w - 12, cy), stat_text, font=stat_font, fill=TEAL2, anchor="rm")

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
    name_max_w = W // 2 - 100 - 90
    tagw = 54

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        draw.polygon([(36, y0), (36 + tagw, y0), (36 + tagw, y1), (36 + 12, y1), (36, y1 - 12)], fill=OLIVE2)
        draw.text((36 + tagw / 2, cy), str(f['slot']), font=rank_font, fill=(20, 20, 16), anchor="mm")

        nf = _fit_text(draw, f['our_ign'], _FONT_BLACK_OPS, 22, 12, name_max_w)
        draw.text((36 + tagw + 20, cy), f['our_ign'], font=nf, fill=TEXT_MAIN, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + tagw + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=AMBER, anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(60, 64, 50), width=2)
        nf_r = _fit_text(draw, f['opp_ign'], _FONT_BLACK_OPS, 22, 12, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - tagw - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=TEXT_MAIN, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=(200, 90, 90), anchor="rm")

        draw.polygon([(W - 36 - tagw, y0), (W - 36, y0), (W - 36, y1 - 12), (W - 36 - 12, y1), (W - 36 - tagw, y1)], fill=(40, 44, 32))
        draw.text((W - 36 - tagw / 2, cy), str(f['slot']), font=rank_font, fill=AMBER, anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_varsity(rows, our_team_name, opponent_name, division, subtitle):
    """Collegiate athletics program style, Graduate slab-serif font, navy/gold palette."""
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
    name_max_w = W // 2 - 100 - 90

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        draw.rectangle([36, y0, 36 + 50, y1], fill=GOLD)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=NAVY, anchor="mm")

        nf = _fit_text(draw, f['our_ign'], _FONT_GRADUATE, 24, 12, name_max_w)
        draw.text((36 + 50 + 20, cy), f['our_ign'], font=nf, fill=CREAM, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + 50 + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=(210, 215, 235), anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(60, 70, 110), width=2)
        nf_r = _fit_text(draw, f['opp_ign'], _FONT_GRADUATE, 24, 12, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - 50 - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=CREAM, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=(230, 200, 120), anchor="rm")
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
    name_max_w = W // 2 - 100 - 90

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))

        rank_font = _fit_text(draw, str(f['slot']), _FONT_PRESS_START, 16, 7, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=(40, 10, 60))
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=MAGENTA, anchor="mm")

        nf = _fit_text(draw, f['our_ign'], _FONT_PRESS_START, 20, 8, name_max_w)
        draw.text((36 + 50 + 20, cy), f['our_ign'], font=nf, fill=TEXT_MAIN, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + 50 + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=YELLOW, anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(60, 50, 90), width=2)
        nf_r = _fit_text(draw, f['opp_ign'], _FONT_PRESS_START, 20, 8, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - 50 - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=TEXT_MAIN, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=CYAN, anchor="rm")
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
    name_max_w = W // 2 - 100 - 90

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        rank_font = _fit_text(draw, str(f['slot']), _FONT_BUNGEE, 18, 10, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=PINK)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=(30, 10, 20), anchor="mm")

        nf = _fit_text(draw, f['our_ign'], _FONT_BUNGEE, 22, 10, name_max_w)
        draw.text((36 + 50 + 20, cy), f['our_ign'], font=nf, fill=TEXT_MAIN, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + 50 + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=YELLOW, anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(70, 70, 76), width=2)
        nf_r = _fit_text(draw, f['opp_ign'], _FONT_BUNGEE, 22, 10, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - 50 - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=TEXT_MAIN, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=CYAN, anchor="rm")
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
    name_max_w = W // 2 - 100 - 90

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
        nf = _fit_text(draw, f['our_ign'], _POSTER_FONT_BOLD, 24, 13, name_max_w)
        draw.text((36 + 50 + 20, cy), f['our_ign'], font=nf, fill=TEXT_MAIN, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + 50 + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=YELLOW, anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(80, 50, 90), width=2)
        nf_r = _fit_text(draw, f['opp_ign'], _POSTER_FONT_BOLD, 24, 13, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - 50 - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=TEXT_MAIN, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=TEAL, anchor="rm")
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=TEAL)
        rank_font_r = _fit_text(draw, str(f['slot']), _POSTER_FONT_BOLD, 22, 12, 44)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font_r, fill=(20, 50, 48), anchor="mm")

        y += row_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _render_ladder_championship(rows, our_team_name, opponent_name, division, subtitle):
    """
    Gold championship/trophy style, Nabla (variable font: 3D extrusion) for
    title and rank badges. Nabla stays legible down to ~16-18px (tested
    directly, more robust than Honk), so rank badges can safely use it —
    still routed through _fit_variable_text for the same safety floor.
    """
    our_team_name = our_team_name or "Our Team"
    opponent_name = opponent_name or "Opponents"
    nabla_axes = [100, 12]  # default depth/highlight — confirmed clearest of the combinations tested

    W = 1300
    row_h = 58
    header_h = 170
    n = len(rows)
    H = header_h + n * row_h + 18

    BG = (12, 10, 8)
    GOLD1, GOLD2 = (255, 215, 0), (180, 140, 20)
    CREAM = (250, 245, 230)
    ROW_A, ROW_B = (22, 19, 14), (28, 24, 18)

    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 6], fill=GOLD1)

    title_text = f"{our_team_name} vs {opponent_name}"
    title_font = _fit_variable_text(draw, title_text, _FONT_NABLA_PATH, nabla_axes, _POSTER_FONT_BOLD, 34, 16, W - 72)
    draw.text((36, 30), title_text, font=title_font, fill=GOLD1)
    sub_font = _load_font(_POSTER_FONT_REG, 18)
    sub_text = "CHAMPIONSHIP LADDER" + (f"  //  {division.upper()}" if division else (f"  //  {subtitle}" if subtitle else ""))
    draw.text((36, 86), sub_text, font=sub_font, fill=(190, 175, 140))

    band_y0, band_y1 = 116, 156
    draw.rectangle([36, band_y0, W // 2 - 6, band_y1], fill=GOLD1)
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], fill=(30, 26, 20))
    draw.rectangle([W // 2 + 6, band_y0, W - 36, band_y1], outline=GOLD1, width=2)
    lbl_font = _load_font(_POSTER_FONT_BOLD, 22)
    draw.text((50, (band_y0 + band_y1) // 2), "OUR TEAM", font=lbl_font, fill=(20, 16, 10), anchor="lm")
    draw.text((W - 50, (band_y0 + band_y1) // 2), "OPPONENTS", font=lbl_font, fill=GOLD1, anchor="rm")

    stat_font = _load_font(_POSTER_FONT_ITALIC, 16)
    name_max_w = W // 2 - 100 - 90

    y = header_h
    for i, raw in enumerate(rows):
        f = _ladder_row_fields(raw)
        y0, y1 = y, y + row_h
        cy = (y0 + y1) // 2
        draw.rectangle([36, y0, W - 36, y1], fill=(ROW_A if i % 2 == 0 else ROW_B))
        rank_font = _fit_variable_text(draw, str(f['slot']), _FONT_NABLA_PATH, nabla_axes, _POSTER_FONT_BOLD, 24, 16, 44)
        draw.rectangle([36, y0, 36 + 50, y1], fill=GOLD1)
        draw.text((36 + 25, cy), str(f['slot']), font=rank_font, fill=(20, 16, 10), anchor="mm")

        nf = _fit_variable_text(draw, f['our_ign'], _FONT_NABLA_PATH, nabla_axes, _POSTER_FONT_BOLD, 24, 13, name_max_w)
        draw.text((36 + 50 + 20, cy), f['our_ign'], font=nf, fill=CREAM, anchor="lm")
        if f['our_stat']:
            ow = draw.textlength(f['our_ign'], font=nf)
            draw.text((36 + 50 + 20 + ow + 12, cy), f"{f['our_stat']}", font=stat_font, fill=GOLD2, anchor="lm")

        draw.line([(W // 2, y0 + 8), (W // 2, y1 - 8)], fill=(60, 52, 40), width=2)
        nf_r = _fit_variable_text(draw, f['opp_ign'], _FONT_NABLA_PATH, nabla_axes, _POSTER_FONT_BOLD, 24, 13, name_max_w)
        stat_text = f"DEF {f['opp_stat']}" if f['opp_stat'] else ""
        end_x = W - 36 - 50 - 20
        draw.text((end_x, cy), f['opp_ign'], font=nf_r, fill=CREAM, anchor="rm")
        if stat_text:
            ow2 = draw.textlength(f['opp_ign'], font=nf_r)
            draw.text((end_x - ow2 - 12, cy), stat_text, font=stat_font, fill=(220, 190, 90), anchor="rm")
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], fill=(30, 26, 20))
        draw.rectangle([W - 36 - 50, y0, W - 36, y1], outline=GOLD1, width=1)
        rank_font_r = _fit_variable_text(draw, str(f['slot']), _FONT_NABLA_PATH, nabla_axes, _POSTER_FONT_BOLD, 24, 16, 44)
        draw.text((W - 36 - 25, cy), str(f['slot']), font=rank_font_r, fill=GOLD1, anchor="mm")

        y += row_h

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
