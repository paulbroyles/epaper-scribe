"""Saint name parsing and Pillow rendering for E-Paper Scribe.

Handles the full range of raw name strings from both the Anglican
liturgical-calendar package and romcal:

  Anglican examples
  -----------------
  "Philip and James, Apostles"          → [("Philip and James", "Apostles")]
  "Cyprian, Bishop of Carthage"         → [("Cyprian", "Bishop of Carthage")]
  "Charles, king and martyr"            → [("Charles", "king and martyr")]
  "Mary, Martha and Lazarus"            → [("Mary, Martha and Lazarus", "")]  ← list comma
  "Perpetua, Felicity and companions"   → [("Perpetua, Felicity and companions", "")]
  "Gregory, and his sister Macrina"     → [("Gregory, and his sister Macrina", "")]
  "Columba (transferred)"               → transferred=True, [("Columba", "")]

  Catholic / romcal examples
  --------------------------
  "Saint Vincent, Deacon and Martyr"             → [("Vincent", "Deacon and Martyr")]
  "Joseph, Husband of Mary"                      → [("Joseph", "Husband of Mary")]
  "Saints Cyril, Monk and Methodius, Bishop"     → [("Cyril","Monk"),("Methodius","Bishop")]
  "Saint Blase, Bishop Martyr and Saint Ansgar…" → [("Blase","Bishop Martyr"),("Ansgar","Bishop")]
  "Saint George, Martyr/Saint Adalbert, Bishop…" → [("George","Martyr"),("Adalbert","Bishop…")]
  "Saint Bede…/Saint Gregory VII…/…"             → three segments
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.ImageDraw import ImageDraw
    from PIL.ImageFont import FreeTypeFont

def _name_separators(n: int) -> list[str]:
    """Return separator strings between *n* name segments.

    n=1 → []
    n=2 → [" and "]
    n=3 → [", ", ", and "]
    n≥4 → [", ", …, ", ", ", and "]
    """
    if n <= 1:
        return []
    if n == 2:
        return [" and "]
    return [", "] * (n - 2) + [", and "]


def _join_names(segments: "list[NameSegment]") -> str:
    """Join segment names with grammatical 'and' / Oxford comma."""
    names = [seg.name for seg in segments]
    n = len(names)
    if n == 0:
        return ""
    if n == 1:
        return names[0]
    seps = _name_separators(n)
    result = names[0]
    for i, sep in enumerate(seps):
        result += sep + names[i + 1]
    return result

# Words that, when they appear as the first token after a comma, mean the
# comma is a name/descriptor separator rather than a list separator.
# Comparison is case-insensitive.
_DESCRIPTOR_WORDS: frozenset[str] = frozenset({
    # Ecclesiastical roles
    "bishop", "bishops", "martyr", "martyrs", "apostle", "apostles",
    "priest", "priests", "pope", "popes", "virgin", "virgins",
    "deacon", "deacons", "monk", "monks", "abbot", "abbess",
    "hermit", "confessor", "doctor", "religious", "evangelist",
    "patron", "founder", "missionary",
    # Relational descriptors ("Joseph, Husband of Mary")
    "husband", "wife", "mother", "father",
    # Secular titles
    "king", "queen", "emperor", "empress",
    # Article before a title phrase ("The First Martyr", "The Great")
    "the",
})

_NAME_PREFIXES: tuple[str, ...] = (
    "Saints ", "Saint ", "Blessed ", "Venerable ", "Our Lady of ",
)


@dataclass
class NameSegment:
    """One person within a feast entry."""
    name: str        # display name with honorific prefix stripped
    descriptor: str  # role/title ("Bishop and Martyr", "Apostle", …); may be ""


@dataclass
class ParsedSaintName:
    segments: list[NameSegment] = field(default_factory=list)
    transferred: bool = False  # Anglican "(transferred)" suffix was present


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_saint_name(raw: str) -> ParsedSaintName:
    """Parse a raw feast name string into structured display segments."""
    transferred = raw.endswith("(transferred)")
    if transferred:
        raw = raw[: -len("(transferred)")].rstrip()

    # Romcal slash-separated multi-person ("George, Martyr/Adalbert, Bishop…")
    if "/" in raw:
        segments: list[NameSegment] = []
        for seg in raw.split("/"):
            segments.extend(_parse_single(seg.strip()))
        return ParsedSaintName(segments=segments, transferred=transferred)

    # "… and Saint/Saints Name" pattern ("Blase, Bishop Martyr and Saint Ansgar…")
    if re.search(r"\band\s+Saints?\s+\w", raw, re.IGNORECASE):
        parts = re.split(r"\s+and\s+(?=Saints?\s)", raw, flags=re.IGNORECASE)
        segments = []
        for p in parts:
            segments.extend(_parse_single(p.strip()))
        return ParsedSaintName(segments=segments, transferred=transferred)

    return ParsedSaintName(segments=_parse_single(raw), transferred=transferred)


def _strip_prefix(s: str) -> str:
    for prefix in _NAME_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _parse_single(entry: str) -> list[NameSegment]:
    """Parse one entry string; may return two segments for the
    "Name, Role and Name2, Role2" Catholic pattern (no slash, no Saint repeat)."""
    display = _strip_prefix(entry.strip())

    if "," not in display:
        return [NameSegment(name=display, descriptor="")]

    name_part, rest = display.split(",", 1)
    name_part = name_part.strip()
    rest = rest.strip()

    first_word = rest.split()[0].lower() if rest.split() else ""

    if first_word in _DESCRIPTOR_WORDS:
        # Check for embedded second person: "Role and ProperName[, Role]"
        # e.g. rest = "Monk and Methodius, Bishop"
        and_match = re.search(r"\s+and\s+([A-Z]\w*)", rest)
        if and_match and and_match.group(1).lower() not in _DESCRIPTOR_WORDS:
            # Split on " and <Capital>" — first capital word that isn't a role
            before_and, after_and = re.split(
                r"\s+and\s+(?=[A-Z])", rest, maxsplit=1
            )
            seg2 = _parse_single(after_and.strip())
            return [NameSegment(name=name_part, descriptor=before_and.strip())] + seg2

        return [NameSegment(name=name_part, descriptor=rest)]

    # List comma — treat the whole display string as the undivided name
    return [NameSegment(name=display, descriptor="")]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _text(
    img: "Image.Image",
    draw: "ImageDraw",
    xy: tuple[int, int],
    text: str,
    font: "FreeTypeFont",
    color: tuple[int, int, int],
) -> None:
    """Anti-aliasing-free text rendering for BWR e-ink output.

    TrueType fonts produce sub-pixel gray pixels that survive into Floyd-
    Steinberg dithering as noise fringe.  We eliminate this by rendering into
    a temporary L-mode image, thresholding to pure black/white, then pasting
    the target *color* through the resulting mask.
    """
    from PIL import Image as _Image, ImageDraw as _ImageDraw

    tmp = _Image.new("L", img.size, 255)
    _ImageDraw.Draw(tmp).text(xy, text, font=font, fill=0)
    mask = tmp.point(lambda v: 255 if v < 128 else 0)
    img.paste(_Image.new("RGB", img.size, color), mask=mask)


def _draw_name_line(
    img: "Image.Image",
    draw: "ImageDraw",
    parsed: ParsedSaintName,
    x: int,
    y: int,
    name_font: "FreeTypeFont",
    color: tuple[int, int, int],
) -> None:
    """Draw only the name line (no descriptor). Used for the header band."""
    segments = parsed.segments
    if not segments:
        return
    seps = _name_separators(len(segments))
    sep_widths = [int(draw.textlength(s, font=name_font)) for s in seps]
    name_widths = [int(draw.textlength(seg.name, font=name_font)) for seg in segments]
    cur = x
    for i, seg in enumerate(segments):
        _text(img, draw, (cur, y), seg.name, name_font, color)
        cur += name_widths[i]
        if i < len(segments) - 1:
            _text(img, draw, (cur, y), seps[i], name_font, color)
            cur += sep_widths[i]


def render_saint_name(
    img: "Image.Image",
    draw: "ImageDraw",
    parsed: ParsedSaintName,
    x: int,
    y: int,
    name_font: "FreeTypeFont",
    desc_font: "FreeTypeFont",
    color: tuple[int, int, int] = (0, 0, 0),
) -> int:
    """Draw the name line and, if any descriptors exist, the descriptor line.

    Descriptor text for each segment is rendered directly below that segment's
    name start — pixel-aligned using Pillow text measurement.

    Returns the y coordinate immediately after the last rendered line, so the
    caller can position the next element.
    """
    segments = parsed.segments
    if not segments:
        return y

    seps = _name_separators(len(segments))
    sep_widths = [int(draw.textlength(s, font=name_font)) for s in seps]
    name_widths = [int(draw.textlength(seg.name, font=name_font)) for seg in segments]

    # X offset for each segment's name start
    x_offsets: list[int] = []
    cur = x
    for i, w in enumerate(name_widths):
        x_offsets.append(cur)
        cur += w
        if i < len(segments) - 1:
            cur += sep_widths[i]

    # Name line
    for i, seg in enumerate(segments):
        _text(img, draw, (x_offsets[i], y), seg.name, name_font, color)
        if i < len(segments) - 1:
            _text(img, draw, (x_offsets[i] + name_widths[i], y), seps[i], name_font, color)

    _, _, _, name_h = draw.textbbox((0, 0), "Ag", font=name_font)
    desc_y = y + name_h + 2

    # Descriptor line — each descriptor at the x-offset of its name
    has_descriptors = any(seg.descriptor for seg in segments)
    if has_descriptors:
        for i, seg in enumerate(segments):
            if seg.descriptor:
                _text(img, draw, (x_offsets[i], desc_y), seg.descriptor, desc_font, color)
        _, _, _, desc_h = draw.textbbox((0, 0), "Ag", font=desc_font)
        return desc_y + desc_h

    return y + name_h


# ---------------------------------------------------------------------------
# Season symbols (ferial left column)
# ---------------------------------------------------------------------------

def _draw_season_symbol(
    draw: "ImageDraw",
    season: str,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
    background: tuple[int, int, int] = (255, 255, 255),
) -> None:
    """Draw a distinct liturgical season glyph in the slot (x, y, w, h).

    Vertically-oriented shapes (candle, tree, tau cross, Latin crosses) use the
    full w × h slot; naturally square shapes (star, Celtic cross, triquetra,
    crown, flames) centre a square within it so their geometry is undistorted.

    Seasons handled:
      Advent        — candle with triangular flame
      Christmas     — two-tier tree + star at apex
      Epiphany      — eight-pointed star (two overlapping squares)
      before Lent   — Celtic / sun cross (equal-arm cross inside a circle)
      Lent          — tau cross (T-shape; no top arm)
      Holy Week     — palm frond (diagonal stem + leaflet pairs)
      Easter        — Latin cross with draped cloth over crossbar
      Pentecost     — three tongues of fire
      Trinity       — triquetra (three interlocked arcs)
      before Advent — crown (three-tined)
      fallback      — plain Latin cross
    """
    import math

    s = season.lower() if season else ""
    cx = x + w // 2
    cy = y + h // 2
    # Square icons use the smaller dimension; centred in the full slot.
    side = min(w, h)
    pad = max(2, side // 6)
    r = side // 2 - pad
    arm_w = max(2, side // 8)
    lw = max(1, arm_w // 2)

    if "before advent" in s:
        # ── Crown: three triangular tines + solid band + jewel circles ───────
        # Checked before "advent" so substring match doesn't hit candle branch.
        pad_w   = max(2, w // 22)
        pad_bot = max(4, h // 14)
        x0 = x + pad_w;  x1 = x + w - pad_w;  bw = x1 - x0
        crown_h = min(h, w) * 76 // 100
        band_h  = crown_h * 60 // 100
        cbot    = y + h - pad_bot
        btop    = cbot - band_h
        tine_w  = bw // 4
        lt_l = x0;               lt_r = x0 + tine_w
        ct_l = cx - tine_w // 2; ct_r = cx + tine_w // 2
        rt_l = x1 - tine_w;     rt_r = x1
        tine_h_side = crown_h - band_h
        tine_h_mid  = tine_h_side + tine_h_side // 3
        # Band
        draw.rectangle([x0, btop, x1, cbot], fill=color)
        # Three triangular tines (centre tallest)
        draw.polygon([(lt_l, btop), (lt_r, btop), ((lt_l+lt_r)//2, btop-tine_h_side)], fill=color)
        draw.polygon([(ct_l, btop), (ct_r, btop), (cx, btop-tine_h_mid)], fill=color)
        draw.polygon([(rt_l, btop), (rt_r, btop), ((rt_l+rt_r)//2, btop-tine_h_side)], fill=color)
        # Jewel dots (white circles) on band
        jy = btop + band_h // 2;  jd = max(2, band_h // 5)
        for jx in [(lt_l+lt_r)//2, cx, (rt_l+rt_r)//2]:
            draw.ellipse([jx-jd, jy-jd, jx+jd, jy+jd], fill=background)

    elif "advent" in s:
        # ── Single candle: outlined body + visible wick line + teardrop flame ─
        # Layout (top → bottom): flame | wick gap | candle body.
        # The wick is drawn LAST so it's on top of both flame base and body top,
        # guaranteeing it's always visible as a thin dark separator.
        pad_h        = max(2, h // 12)
        body_bot_hw  = max(4, w // 5)
        body_top_hw  = max(2, w // 6)
        wick_gap     = max(8, h // 9)          # clear gap between flame and body
        flame_h      = max(10, h * 2 // 7)
        flame_hw     = max(3, body_top_hw - 1)
        flame_base_hw = max(2, w // 14)        # narrow at wick, wider than wick_hw
        # y coordinates (top → bottom)
        flame_tip_y  = y + pad_h
        flame_base_y = flame_tip_y + flame_h   # flame ends here
        body_top_y   = flame_base_y + wick_gap # body starts here (gap = wick zone)
        body_bot_y   = y + h - pad_h
        # (1) Candle body: outlined trapezoid, white fill
        draw.polygon([
            (cx - body_top_hw, body_top_y),
            (cx + body_top_hw, body_top_y),
            (cx + body_bot_hw, body_bot_y),
            (cx - body_bot_hw, body_bot_y),
        ], fill=background, outline=color)
        # (2) Flame: 7-point rounded teardrop in warm yellow-orange.
        # At actual resolution the dithering pipeline converts this to a
        # red+white mix that reads as a warm flame on the BWR display.
        flame_upper_y = flame_tip_y + int(flame_h * 0.22)   # narrow upper shoulder
        flame_mid_y   = flame_tip_y + int(flame_h * 0.55)   # widest point
        flame_color   = (255, 180, 0)   # yellow-orange → dithers to red+white
        draw.polygon([
            (cx,                            flame_tip_y),
            (cx + flame_hw * 55 // 100,     flame_upper_y),
            (cx + flame_hw,                 flame_mid_y),
            (cx + flame_base_hw,            flame_base_y),
            (cx - flame_base_hw,            flame_base_y),
            (cx - flame_hw,                 flame_mid_y),
            (cx - flame_hw * 55 // 100,     flame_upper_y),
        ], fill=flame_color)
        # (3) Wick: 1 px line through the gap — drawn LAST for guaranteed visibility
        draw.line([(cx, flame_base_y), (cx, body_top_y)], fill=color, width=1)

    elif "christmas" in s:
        # ── Christmas tree: two-tier triangle + small star at apex ───────────
        # Uses full w × h for maximum tree height.
        pad_h = max(1, h // 12)
        pad_w = max(2, w // 10)
        rw = w // 2 - pad_w           # half-width of tree base
        star_r = max(3, rw // 4)
        apex_y = y + pad_h
        base_y = y + h - pad_h
        tree_h = base_y - (apex_y + star_r)
        tier2_y = apex_y + star_r + tree_h * 6 // 10
        draw.polygon([
            (cx, apex_y + star_r),
            (cx - rw * 7 // 10, tier2_y),
            (cx + rw * 7 // 10, tier2_y),
        ], fill=color)
        draw.polygon([
            (cx, apex_y + star_r + tree_h // 4),
            (cx - rw, base_y),
            (cx + rw, base_y),
        ], fill=color)
        # Small 5-pointed star at apex
        ri_s = star_r // 2
        star_pts = [
            (cx + (star_r if i % 2 == 0 else ri_s) * math.cos(math.radians(-90 + i * 36)),
             apex_y + (star_r if i % 2 == 0 else ri_s) * math.sin(math.radians(-90 + i * 36)))
            for i in range(10)
        ]
        draw.polygon(star_pts, fill=color)

    elif "epiphany" in s:
        # ── Eight-pointed star: two overlapping squares (Magi's star) ────────
        ri = r * 5 // 12          # inner radius (corner indentation)
        pts = []
        for i in range(16):
            angle = math.radians(-90 + i * 22.5)
            radius = r if i % 2 == 0 else ri
            pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        draw.polygon(pts, fill=color)

    elif "before lent" in s:
        # ── Celtic cross: equal-width arms inside a ring ─────────────────────
        # Classic Celtic cross: standard-width straight arms with an overlaid
        # circle (ring) where they intersect.  Straight (non-flared) arms so
        # there are no "triangular" shapes at the ends at all.
        cross_r = r
        ring_r  = r * 55 // 100
        # Thinner arms: half-width = arm_w//4 ≈ 2 px → 4 px total stroke
        arm_narrow = max(1, arm_w // 4)
        arm_wide   = arm_narrow
        cross_lw   = arm_narrow            # ring outline matches arm thickness
        # Four arms (rectangles) outside the ring
        draw.polygon([(cx - arm_narrow, cy - ring_r), (cx + arm_narrow, cy - ring_r),
                      (cx + arm_wide,   cy - cross_r), (cx - arm_wide,   cy - cross_r)], fill=color)
        draw.polygon([(cx - arm_narrow, cy + ring_r), (cx + arm_narrow, cy + ring_r),
                      (cx + arm_wide,   cy + cross_r), (cx - arm_wide,   cy + cross_r)], fill=color)
        draw.polygon([(cx - ring_r, cy - arm_narrow), (cx - ring_r, cy + arm_narrow),
                      (cx - cross_r, cy + arm_wide),  (cx - cross_r, cy - arm_wide)], fill=color)
        draw.polygon([(cx + ring_r, cy - arm_narrow), (cx + ring_r, cy + arm_narrow),
                      (cx + cross_r, cy + arm_wide),  (cx + cross_r, cy - arm_wide)], fill=color)
        # Ring: background fill + bolder outline (use global lw, not thin cross_lw)
        draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                     fill=background, outline=color, width=lw)
        # Restore inner arm stubs inside the ring
        inner = ring_r - cross_lw
        draw.rectangle([cx - arm_narrow, cy - inner, cx + arm_narrow, cy + inner], fill=color)
        draw.rectangle([cx - inner, cy - arm_narrow, cx + inner, cy + arm_narrow], fill=color)

    elif "lent" in s:
        # ── Ichthus outline (Christian fish symbol) ───────────────────────────
        # Horizontal fish facing right (rounded nose right, forked tail left).
        # Drawn as outline (not solid fill) — fill=background, outline=color.
        # Body: lens shape from two sine arcs. Uses full slot width.
        fish_w   = w * 5 // 7                   # total width (body + tail) ≈ 71%
        fish_hh  = max(4, fish_w // 5)           # half-height (≈5:1 aspect)
        tail_len = max(4, fish_hh * 4 // 3)
        fish_lw  = max(2, side // 20)            # outline stroke width
        body_left  = cx - fish_w // 2 + tail_len
        body_right = cx + fish_w // 2
        n = 24
        pts_top = [(body_left + (body_right - body_left) * i / n,
                    cy - fish_hh * math.sin(math.pi * i / n)) for i in range(n + 1)]
        pts_bot = [(body_left + (body_right - body_left) * i / n,
                    cy + fish_hh * math.sin(math.pi * i / n)) for i in range(n, -1, -1)]
        draw.polygon(pts_top + pts_bot[1:-1], fill=background, outline=color, width=fish_lw)
        # Forked tail: V-shape to the left of body_left — also outlined
        tail_x  = cx - fish_w // 2
        notch_x = tail_x + tail_len * 2 // 5
        draw.polygon([
            (int(body_left), int(cy)),
            (int(tail_x),    int(cy - fish_hh)),
            (int(notch_x),   int(cy)),
            (int(tail_x),    int(cy + fish_hh)),
        ], fill=background, outline=color, width=fish_lw)

    elif "holy week" in s or "holy_week" in s:
        # ── Palm frond: quadratic-Bézier rachis + 14 leaflet pairs ───────────
        # Approved design (preview v27+). Rachis curves from lower-right (base)
        # to upper-left (tip).  Each leaflet is a filled lozenge polygon;
        # a spine line from base→tip guarantees full length at actual resolution.
        # hw/mhw clamped to ≥1 so short leaflets never collapse to zero width.
        def _b2(p0, p1, p2, t):
            return ((1-t)**2*p0[0]+2*t*(1-t)*p1[0]+t**2*p2[0],
                    (1-t)**2*p0[1]+2*t*(1-t)*p1[1]+t**2*p2[1])
        def _b2t(p0, p1, p2, t):
            dx = 2*(1-t)*(p1[0]-p0[0])+2*t*(p2[0]-p1[0])
            dy = 2*(1-t)*(p1[1]-p0[1])+2*t*(p2[1]-p1[1])
            ln = math.hypot(dx, dy); return dx/ln, dy/ln
        P0 = (x + w*46//64, y + h*76//84)
        P1 = (x + w*22//64, y + h*38//84)
        P2 = (x + w*16//64, y + h*6//84)
        MAX_LEN = w*30//64
        rachis_lw = max(1, w*2//64)
        for j in range(30):
            a = _b2(P0, P1, P2, j/30); b = _b2(P0, P1, P2, (j+1)/30)
            draw.line([(int(a[0]),int(a[1])),(int(b[0]),int(b[1]))],
                      fill=color, width=rachis_lw)
        cos60 = 0.5; sin60 = 0.866; N_LF = 14
        for i in range(N_LF):
            t = 0.06 + i*(0.91/(N_LF-1))
            ix, iy = _b2(P0, P1, P2, t)
            ux, uy = _b2t(P0, P1, P2, t)
            r_dx = ux*cos60 - uy*sin60; r_dy = ux*sin60 + uy*cos60
            rl = math.hypot(r_dx, r_dy); r_dx /= rl; r_dy /= rl
            l_dx = ux*cos60 + uy*sin60; l_dy = -ux*sin60 + uy*cos60
            ll2 = math.hypot(l_dx, l_dy); l_dx /= ll2; l_dy /= ll2
            llen = max(4, int(MAX_LEN*(1.0-0.65*t)))
            hw = max(1, llen//12); C = 2
            for (ldx, ldy) in [(r_dx, r_dy), (l_dx, l_dy)]:
                tip_x = ix + llen*ldx; tip_y = iy + llen*ldy
                mx = ix + 0.5*llen*ldx + C*ux; my = iy + 0.5*llen*ldy + C*uy
                ppx = -ldy; ppy = ldx; mhw = max(1, hw*2//3)
                draw.polygon([
                    (int(ix+hw*ppx), int(iy+hw*ppy)),
                    (int(mx+mhw*ppx), int(my+mhw*ppy)),
                    (int(tip_x), int(tip_y)),
                    (int(mx-mhw*ppx), int(my-mhw*ppy)),
                    (int(ix-hw*ppx), int(iy-hw*ppy)),
                ], fill=color)
                # Spine line guarantees full leaflet length at actual resolution
                draw.line([(int(ix), int(iy)), (int(tip_x), int(tip_y))],
                          fill=color, width=1)

    elif "easter" in s:
        # ── Latin cross with draped cloth over the crossbar ───────────────────
        # Design: sag cloth terminates at arm_top (tucks behind arm from above);
        # tails begin at arm_bot (emerge from behind arm below).  Cloth drawn as
        # filled polygons with perpendicular offsets so edges are pixel-precise
        # and survive BWR Floyd-Steinberg dithering without fragmentation.
        # Uses full w × h: extra height lengthens the stem and cloth tails.
        _pad      = max(1, w // 8)
        _arm_w    = max(2, w // 10)
        _left_x   = x + _pad
        _right_x  = x + w - _pad
        _top_y    = y + _pad
        _bot_y    = y + h - _pad
        _hy       = _top_y + (_bot_y - _top_y) * 2 // 5
        _vbar_l   = cx - _arm_w // 2
        _arm_top  = _hy - _arm_w // 2
        _arm_bot  = _hy + _arm_w // 2
        _arm_run  = _vbar_l - _left_x
        _cl_x     = _left_x  + int(_arm_run * 0.28)
        _cr_x     = _right_x - int(_arm_run * 0.28)
        _span     = _cr_x - _cl_x
        _cloth_w  = max(2, int(_arm_w * 0.55))
        _ow       = max(1, _arm_w // 7)
        _half_out = _cloth_w // 2 + _ow
        _half_in  = _cloth_w // 2
        _tby      = _arm_bot + int((_bot_y - _arm_bot) * 0.68)
        _sag_d    = int((_tby - _arm_top) * 0.48)
        _ts       = int(_arm_run * 0.28)

        # Cross
        draw.rectangle([cx - _arm_w // 2, _top_y, cx + _arm_w // 2, _bot_y], fill=color)
        draw.rectangle([_left_x, _arm_top, _right_x, _arm_bot], fill=color)

        def _cloth_poly(pts: list) -> None:
            """Render cloth strip as two filled polygons (black outer, white inner)
            using perpendicular offsets for accurate, dither-stable edges."""
            n = len(pts)
            if n < 2:
                return
            def _perp(i: int):
                if i == 0:
                    dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
                elif i == n - 1:
                    dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
                else:
                    dx, dy = pts[i+1][0] - pts[i-1][0], pts[i+1][1] - pts[i-1][1]
                L = math.sqrt(dx * dx + dy * dy) or 1.0
                return dy / L, -dx / L           # unit rightward perpendicular
            def _ip(p):
                return int(round(p[0])), int(round(p[1]))
            perps = [_perp(i) for i in range(n)]
            top_o = [_ip((pts[i][0] - perps[i][0] * _half_out,
                          pts[i][1] - perps[i][1] * _half_out)) for i in range(n)]
            bot_o = [_ip((pts[i][0] + perps[i][0] * _half_out,
                          pts[i][1] + perps[i][1] * _half_out)) for i in range(n)]
            draw.polygon(top_o + bot_o[::-1], fill=color)
            top_i = [_ip((pts[i][0] - perps[i][0] * _half_in,
                          pts[i][1] - perps[i][1] * _half_in)) for i in range(n)]
            bot_i = [_ip((pts[i][0] + perps[i][0] * _half_in,
                          pts[i][1] + perps[i][1] * _half_in)) for i in range(n)]
            draw.polygon(top_i + bot_i[::-1], fill=background)

        # Sag: parabola from (cl_x, arm_top) sagging down to (cr_x, arm_top)
        _cloth_poly([(_cl_x + _span * i / 24,
                      _arm_top + _sag_d * 4 * (i / 24) * (1 - i / 24))
                     for i in range(25)])
        # Left tail: from (cl_x, arm_bot) down-outward to tail bottom
        _cloth_poly([(_cl_x + (_cl_x - _ts - _cl_x) * i / 8,
                      _arm_bot + (_tby - _arm_bot) * i / 8)
                     for i in range(9)])
        # Right tail: from (cr_x, arm_bot) down-outward to tail bottom
        _cloth_poly([(_cr_x + _ts * i / 8,
                      _arm_bot + (_tby - _arm_bot) * i / 8)
                     for i in range(9)])

    elif "pentecost" in s:
        # ── Dove descending into flame — approved design (preview v63) ────────
        # The outer flame is always drawn red regardless of the color param.
        # The dove (body, wings, beak, halo) uses background (white).
        # All offsets are for the canonical 64×84 slot; sw/sh adapt to other sizes.
        _flame_red = (210, 0, 0)
        sw = w / 64; sh = h / 84
        def _p(dx, dy):   # scale offset and return absolute point
            return (int(cx + dx*sw), int(y + dy*sh))
        # Outer flame (two-tongued teardrop, fills slot) — always red
        draw.polygon([
            _p( 4,  2), _p(12, 10), _p(20, 20), _p(25, 32), _p(27, 44),
            _p(26, 54), _p(22, 63), _p(16, 71), _p( 8, 77), _p( 3, 80),
            _p(-3, 80), _p(-8, 77), _p(-16,71), _p(-22,63), _p(-26,54),
            _p(-27,44), _p(-25,32), _p(-20,22), _p(-22,16), _p(-16, 6),
            _p(-8, 14), _p(-2, 22), _p( 1, 14),
        ], fill=_flame_red)
        # Body + oval head (white dove, tail-notch at top)
        draw.polygon([
            _p( 7, 24), _p( 4, 32), _p( 4, 60),
            _p( 6, 63), _p( 6, 66), _p( 4, 69),
            _p( 2, 71), _p(-2, 71), _p(-4, 69),
            _p(-6, 66), _p(-6, 63), _p(-4, 60),
            _p(-4, 32), _p(-7, 24), _p( 0, 28),   # (0,28) = tail-notch vertex
        ], fill=background)
        # Beak: small downward triangle
        draw.polygon([_p(-3, 69), _p(3, 69), _p(0, 75)], fill=background)
        # Right wing — swept-back sickle
        draw.polygon([
            _p( 4, 36), _p(16, 28), _p(19, 40), _p(13, 54), _p(4, 56),
        ], fill=background)
        # Left wing — mirror
        draw.polygon([
            _p(-4, 36), _p(-16,28), _p(-19,40), _p(-13,54), _p(-4,56),
        ], fill=background)
        # Halo — thin white circle around head (drawn last, on top of wings)
        hcx = int(cx); hcy = int(y + 65*sh); hr2 = max(1, int(9*sw))
        draw.ellipse([hcx-hr2, hcy-hr2, hcx+hr2, hcy+hr2],
                     outline=background, width=1)

    elif "trinity" in s:
        # ── Triquetra: three inner interlocked arcs, full-slot scale ─────────
        # Uses tri_r = side//2 - small_pad so arcs fill the slot width.
        sq3h    = math.sqrt(3) / 2
        tri_pad = 0
        tri_r   = side // 2 - tri_pad
        d       = tri_r * 407 // 1000   # d=13 at side=64; arcs fill slot width
        arc_r   = int(d * math.sqrt(3))
        tri_lw  = max(2, tri_r // 7)    # slightly thicker for visual weight
        c1 = (cx,                  cy - d)
        c2 = (cx + int(d * sq3h), cy + d // 2)
        c3 = (cx - int(d * sq3h), cy + d // 2)
        def _tarc(centre, start, end):
            px, py = centre
            bb = [px - arc_r, py - arc_r, px + arc_r, py + arc_r]
            draw.arc(bb, start=start, end=end, fill=color, width=tri_lw)
        _tarc(c1,   3, 177)
        _tarc(c2, 118, 303)
        _tarc(c3, 237,  62)

    else:
        # ── Fallback: plain Latin cross ───────────────────────────────────────
        # Uses full w × h: longer stem gives better cross proportions.
        draw.rectangle([cx - arm_w // 2, y + pad, cx + arm_w // 2, y + h - pad], fill=color)
        hy = y + pad + (h - 2 * pad) * 2 // 5
        draw.rectangle([x + pad, hy - arm_w // 2, x + w - pad, hy + arm_w // 2], fill=color)


# ---------------------------------------------------------------------------
# Full panel compositor
# ---------------------------------------------------------------------------

def render_saints_day_image(
    size: tuple[int, int],
    parsed: "ParsedSaintName | None",
    season: str,
    week: str,
    description: str,
    saint_image_bytes: bytes | None = None,
    font_path: str | None = None,
    name_font_path: str | None = None,
    background: tuple[int, int, int] = (255, 255, 255),
    foreground: tuple[int, int, int] = (0, 0, 0),
    calendar_tag: str = "",
    palette: str | None = None,
) -> bytes:
    """Compose a complete saints-day panel and return PNG bytes at *size*.

    Saint day  — header (red):   name, white text
                 subtitle (black): descriptor(s) aligned under each name, white text
                 left col:        portrait cropped to fill slot exactly
                 right col:       description at the largest font that fits
    Ferial day — header (black): week / season, white text
                 left col:       season symbol centred vertically
                 right col:      season description at largest fitting font

    The PNG is at exactly *size*; the caller's dithering pipeline needs no resize.
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = size
    PAD = max(3, W // 80)
    has_saint = bool(parsed and parsed.segments)
    has_descriptors = has_saint and any(seg.descriptor for seg in parsed.segments)

    # ---- Font loaders -------------------------------------------------------
    # _load_body — description text, role subtitle, calendar tag
    # _load_name — saint name header (uses name_font_path if set, else font_path)
    def _load_body(pt: float) -> "FreeTypeFont":
        if font_path:
            try:
                return ImageFont.truetype(font_path, pt)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=round(pt))
        except TypeError:
            return ImageFont.load_default()

    def _load_name(pt: float) -> "FreeTypeFont":
        _path = name_font_path or font_path
        if _path:
            try:
                return ImageFont.truetype(_path, pt)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=round(pt))
        except TypeError:
            return ImageFont.load_default()

    role_pt = max(9, H // 11)
    desc_pt_min = max(10, H // 12)    # display floor — nothing rendered below this
    desc_budget_pt = max(9, H // 14)  # budget floor — used only to compute how much
                                       # text to extract; may be < desc_pt_min
    role_font = _load_body(role_pt)

    # ---- Portrait slot width ------------------------------------------------
    portrait_side = min(H // 2, W // 4)

    # ---- Probe draw context (1×1 throwaway) ---------------------------------
    probe_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # ---- Calendar tag: measure early for float layout -----------------------
    tag_pt = max(9, H // 12)   # ~10 pt at 128 px — comfortably legible
    tag_font_obj = _load_body(tag_pt)
    _, _, _, tag_h = probe_draw.textbbox((0, 0), "Ag", font=tag_font_obj)
    box_pad = PAD                                        # inner padding around tag text
    # Width cleared for the tag box (tag text + padding on both sides + gap)
    tag_text_w = int(probe_draw.textlength(calendar_tag, font=tag_font_obj)) if calendar_tag else 0
    tag_float_w = tag_text_w + 3 * box_pad if calendar_tag else 0   # column width to leave free
    # Height of the float zone (tag box + gap above it)
    tag_float_h = tag_h + 2 * box_pad if calendar_tag else 0

    # ---- Name / header font: shrink to fit full panel width -----------------
    if has_saint:
        name_line = _join_names(parsed.segments)
        name_pt = max(role_pt + 2, H // 5)
        while name_pt > role_pt + 2:
            if int(probe_draw.textlength(name_line, font=_load_name(name_pt))) <= W - 2 * PAD:
                break
            name_pt -= 1
    else:
        ferial_text = week if week else (season or "")
        name_pt = max(9, H // 10)
        while name_pt > 9:
            if int(probe_draw.textlength(ferial_text, font=_load_name(name_pt))) <= W - 2 * PAD:
                break
            name_pt -= 1

    name_font = _load_name(name_pt)

    # ---- Band heights -------------------------------------------------------
    _, _, _, name_h = probe_draw.textbbox((0, 0), "Ag", font=name_font)
    _, _, _, role_h = probe_draw.textbbox((0, 0), "Ag", font=role_font)
    header_h = PAD + name_h + PAD
    subtitle_h = (PAD + role_h + PAD) if has_descriptors else 0

    # ---- Layout geometry ----------------------------------------------------
    portrait_y = header_h + subtitle_h
    slot_w = portrait_side
    slot_h = H - portrait_y
    text_x = portrait_side + PAD
    text_w = W - text_x - PAD
    text_y = portrait_y + PAD
    avail_h = H - text_y - PAD     # full available height; float handles tag clearance

    # ---- Determine display text and font size --------------------------------
    #
    # Step 1 — content budget: wrap the full description at the legibility
    #   floor font, take however many lines fit in avail_h, then trim back to
    #   the last sentence boundary.  This is the fixed display text — as much
    #   content as the panel can ever show at the smallest acceptable size.
    #
    # Step 2 — enlarge: find the largest font at which all of that display text
    #   still fits.  The text is already correctly sized; we just scale the font
    #   up as far as the layout allows.

    def _wrap_for_pt(pt: float, text: str):
        """Return (lines, max_lines) using float-aware wrapping at *pt*."""
        f = _load_body(pt)
        _, _, _, lh = probe_draw.textbbox((0, 0), "Ag", font=f)
        lh_step = lh + 1
        mx = max(1, avail_h // lh_step)
        if calendar_tag and tag_float_w > 0:
            fs = max(0, (avail_h - tag_float_h) // lh_step)
            rw = max(1, text_w - tag_float_w)
            return _wrap_lines_float(text, text_w, rw, fs, probe_draw, f), mx
        return _wrap_lines(text, text_w, probe_draw, f), mx

    # Step 1: compute display text
    # Use desc_budget_pt (can be smaller than the display floor) to measure the
    # maximum capacity of the panel, so we extract as much content as possible
    # before the enlargement step scales the font back up.
    display_text = description
    if description and text_w > 0 and avail_h > 0:
        floor_lines, max_lines_floor = _wrap_for_pt(desc_budget_pt, description)
        candidate = " ".join(floor_lines[:max_lines_floor])
        last_end = max(candidate.rfind("."), candidate.rfind("!"), candidate.rfind("?"))
        display_text = candidate[: last_end + 1] if last_end >= 0 else candidate

    # Step 2: find largest font where display_text fits.
    # Step by 0.1pt when a TrueType path is available (truetype() accepts floats);
    # fall back to 1pt integer steps for the bitmap default font.
    desc_pt: float = desc_pt_min
    if display_text and text_w > 0 and avail_h > 0:
        max_desc_pt = max(desc_pt_min, min(H // 2, 80))
        step = 0.1 if font_path else 1.0   # body font governs stepping
        pt = float(max_desc_pt)
        while pt >= desc_pt_min:
            lines, max_lines = _wrap_for_pt(pt, display_text)
            if len(lines) <= max_lines:
                desc_pt = pt
                break
            pt = round(pt - step, 1)

    desc_font = _load_body(desc_pt)

    # ---- Canvas -------------------------------------------------------------
    img = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(img)

    # ---- Header band (name, coloured background) ----------------------------
    header_color = (255, 0, 0) if has_saint else (0, 0, 0)
    draw.rectangle([0, 0, W - 1, header_h - 1], fill=header_color)

    if has_saint:
        _draw_name_line(img, draw, parsed, PAD, PAD, name_font, (255, 255, 255))
    else:
        _text(img, draw, (PAD, PAD), ferial_text, name_font, (255, 255, 255))

    # ---- Subtitle band (descriptors, black background, white text) ----------
    if subtitle_h:
        draw.rectangle([0, header_h, W - 1, header_h + subtitle_h - 1], fill=(0, 0, 0))
        # Each descriptor aligned under its name's x offset in the header
        seps_n = _name_separators(len(parsed.segments))
        sep_ws_n = [int(probe_draw.textlength(s, font=name_font)) for s in seps_n]
        name_widths_n = [
            int(probe_draw.textlength(seg.name, font=name_font))
            for seg in parsed.segments
        ]
        cur = PAD
        for i, seg in enumerate(parsed.segments):
            if seg.descriptor:
                _text(img, draw, (cur, header_h + PAD), seg.descriptor, role_font, (255, 255, 255))
            cur += name_widths_n[i]
            if i < len(parsed.segments) - 1:
                cur += sep_ws_n[i]

    # ---- Left column: portrait or season symbol -----------------------------
    if has_saint and saint_image_bytes:
        try:
            simg = Image.open(BytesIO(saint_image_bytes)).convert("RGB")
            si_w, si_h = simg.size
            if slot_h > 0 and si_h > 0:
                slot_aspect = slot_w / slot_h
                img_aspect = si_w / si_h
                if img_aspect > slot_aspect:
                    # Wider than slot → center-crop horizontally
                    crop_w = max(1, int(si_h * slot_aspect))
                    left = (si_w - crop_w) // 2
                    simg = simg.crop((left, 0, left + crop_w, si_h))
                else:
                    # Taller than slot → top-crop vertically (faces near top)
                    crop_h = max(1, int(si_w / slot_aspect))
                    simg = simg.crop((0, 0, si_w, min(crop_h, si_h)))
            simg = simg.resize((slot_w, slot_h), Image.LANCZOS)
            if palette:
                from .dither import dither_pil_image
                simg = dither_pil_image(simg, palette)
            img.paste(simg, (0, portrait_y))
        except Exception:
            pass
    elif not has_saint:
        _draw_season_symbol(draw, season or "", 0, portrait_y, portrait_side, slot_h, foreground, background)

    # ---- Text column: description at scaled-up font -------------------------
    if display_text and text_w > 0 and avail_h > 0:
        if calendar_tag and tag_float_w > 0:
            _, _, _, lh = probe_draw.textbbox((0, 0), "Ag", font=desc_font)
            float_start = max(0, (avail_h - tag_float_h) // (lh + 1))
            reduced_w = max(1, text_w - tag_float_w)
            _draw_wrapped_float(
                img, draw, display_text,
                text_x, text_y, text_w, reduced_w, float_start, avail_h,
                desc_font, foreground,
            )
        else:
            _draw_wrapped(img, draw, display_text, text_x, text_y, text_w, avail_h, desc_font, foreground)

    # ---- Calendar tag (bottom-right corner, floating text) -----------------
    if calendar_tag:
        tag_x = W - PAD - tag_text_w
        tag_y = H - PAD - tag_h
        _text(img, draw, (tag_x, tag_y), calendar_tag, tag_font_obj, foreground)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wrap_lines_float(
    text: str,
    full_width: int,
    reduced_width: int,
    float_start_line: int,
    draw: "ImageDraw",
    font: "FreeTypeFont",
) -> list[str]:
    """Word-wrap with a right-side float starting at *float_start_line*.

    Lines before *float_start_line* use *full_width*; lines at or after use
    *reduced_width* (leaving space for the floating tag box).
    """
    lines: list[str] = []
    line = ""
    for word in text.split():
        max_w = full_width if len(lines) < float_start_line else reduced_width
        candidate = (line + " " + word).strip()
        if int(draw.textlength(candidate, font=font)) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
                # Re-evaluate width for the new line we're about to start
                max_w = full_width if len(lines) < float_start_line else reduced_width
            line = word
    if line:
        lines.append(line)
    return lines


def _draw_wrapped_float(
    img: "Image.Image",
    draw: "ImageDraw",
    text: str,
    x: int,
    y: int,
    full_width: int,
    reduced_width: int,
    float_start_line: int,
    max_height: int,
    font: "FreeTypeFont",
    color: tuple[int, int, int],
) -> int:
    """Draw *text* word-wrapped with a right float, truncating at a sentence boundary."""
    _, _, _, line_h = draw.textbbox((0, 0), "Ag", font=font)
    line_h += 1
    max_lines = max(1, max_height // line_h)

    all_lines = _wrap_lines_float(text, full_width, reduced_width, float_start_line, draw, font)

    if len(all_lines) > max_lines:
        candidate_text = " ".join(all_lines[:max_lines])
        last_end = max(
            candidate_text.rfind("."),
            candidate_text.rfind("!"),
            candidate_text.rfind("?"),
        )
        if last_end >= 0:
            candidate_text = candidate_text[: last_end + 1]
        display_lines = _wrap_lines_float(candidate_text, full_width, reduced_width, float_start_line, draw, font)
    else:
        display_lines = all_lines

    for ln in display_lines:
        _text(img, draw, (x, y), ln, font, color)
        y += line_h
    return y


def _wrap_lines(text: str, max_width: int, draw: "ImageDraw", font: "FreeTypeFont") -> list[str]:
    """Word-wrap *text* to *max_width* px. Returns list of display lines."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if int(draw.textlength(candidate, font=font)) <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _draw_wrapped(
    img: "Image.Image",
    draw: "ImageDraw",
    text: str,
    x: int,
    y: int,
    max_width: int,
    max_height: int,
    font: "FreeTypeFont",
    color: tuple[int, int, int],
) -> int:
    """Word-wrap *text* into *max_width* px, stopping within *max_height* px.

    When truncation is required, backs up to the nearest sentence boundary so
    the display never ends mid-sentence.
    """
    _, _, _, line_h = draw.textbbox((0, 0), "Ag", font=font)
    line_h += 1
    max_lines = max(1, max_height // line_h)

    all_lines = _wrap_lines(text, max_width, draw, font)

    if len(all_lines) > max_lines:
        # Candidate block fills the space — find last sentence end within it
        candidate_text = " ".join(all_lines[:max_lines])
        last_end = max(
            candidate_text.rfind("."),
            candidate_text.rfind("!"),
            candidate_text.rfind("?"),
        )
        if last_end >= 0:
            candidate_text = candidate_text[: last_end + 1]
        display_lines = _wrap_lines(candidate_text, max_width, draw, font)
    else:
        display_lines = all_lines

    for ln in display_lines:
        _text(img, draw, (x, y), ln, font, color)
        y += line_h
    return y
