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
    side: int,
    color: tuple[int, int, int],
    background: tuple[int, int, int] = (255, 255, 255),
) -> None:
    """Draw a distinct liturgical season glyph centred in the square (x,y,side).

    Seasons handled:
      Advent        — candle with triangular flame
      Christmas     — manger (trapezoidal trough outline)
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
    cx = x + side // 2
    cy = y + side // 2
    pad = max(2, side // 6)
    r = side // 2 - pad
    arm_w = max(2, side // 8)
    lw = max(1, arm_w // 2)

    if "advent" in s:
        # ── Candle: rectangular body + triangular flame ──────────────────────
        bw = max(2, side // 5)
        draw.rectangle([cx - bw // 2, cy - r // 3, cx + bw // 2, cy + r], fill=color)
        draw.polygon(
            [(cx, cy - r - r // 3), (cx - bw // 2, cy - r // 3), (cx + bw // 2, cy - r // 3)],
            fill=color,
        )

    elif "christmas" in s:
        # ── Christmas tree: two-tier triangle + small star at apex ───────────
        star_r = max(3, r // 4)
        apex_y  = cy - r                       # top of tree / centre of star
        base_y  = cy + r                       # bottom of tree
        tree_h  = base_y - (apex_y + star_r)  # height available for triangles
        # Two tiers: upper narrower, lower full-width
        tier2_y = apex_y + star_r + tree_h * 6 // 10   # bottom of upper tier
        draw.polygon([
            (cx, apex_y + star_r),
            (cx - r * 7 // 10, tier2_y),
            (cx + r * 7 // 10, tier2_y),
        ], fill=color)
        draw.polygon([
            (cx, apex_y + star_r + tree_h // 4),
            (cx - r, base_y),
            (cx + r, base_y),
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
        # ── Celtic cross: equal-arm cross with a ring at the centre ──────────
        cross_r = r
        ring_r  = r * 5 // 9
        # Arms: equal length, centred on canvas
        arm_cy = cy     # centre of cross (not 2/5 offset — this is a Greek cross)
        draw.rectangle([cx - arm_w // 2, cy - cross_r, cx + arm_w // 2, cy + cross_r], fill=color)
        draw.rectangle([cx - cross_r, arm_cy - arm_w // 2, cx + cross_r, arm_cy + arm_w // 2], fill=color)
        # Ring overlay: background fill inside the circle outline erases the cross
        # so the ring appears to "interrupt" the arms, Celtic-cross style
        draw.ellipse([cx - ring_r, arm_cy - ring_r, cx + ring_r, arm_cy + ring_r],
                     fill=background, outline=color, width=lw)
        # Restore cross inside the ring (the four inner arm stubs)
        inner = ring_r - lw
        draw.rectangle([cx - arm_w // 2, arm_cy - inner, cx + arm_w // 2, arm_cy + inner], fill=color)
        draw.rectangle([cx - inner, arm_cy - arm_w // 2, cx + inner, arm_cy + arm_w // 2], fill=color)

    elif "lent" in s:
        # ── Tau cross: T-shape (horizontal + lower vertical arm only) ────────
        hy = y + pad + (side - 2 * pad) * 2 // 5   # crossbar y
        draw.rectangle([cx - arm_w // 2, hy, cx + arm_w // 2, y + side - pad], fill=color)
        draw.rectangle([x + pad, hy - arm_w // 2, x + side - pad, hy + arm_w // 2], fill=color)

    elif "holy week" in s or "holy_week" in s:
        # ── Palm frond: diagonal stem + opposing leaflet pairs ────────────────
        sx0, sy0 = cx - r // 4, cy + r       # base (lower left)
        sx1, sy1 = cx + r // 3, cy - r       # tip (upper right)
        stem_w = max(2, arm_w // 2)
        draw.line([(sx0, sy0), (sx1, sy1)], fill=color, width=stem_w)
        stem_angle = math.atan2(sy1 - sy0, sx1 - sx0)
        perp = stem_angle + math.pi / 2
        n = 4
        for i in range(n):
            t = (i + 1.5) / (n + 1.5)           # progress along stem (tip end)
            px = sx0 + t * (sx1 - sx0)
            py = sy0 + t * (sy1 - sy0)
            leaf_len = int(r * (0.5 - t * 0.15))
            for sign in (1, -1):
                ex = px + sign * leaf_len * math.cos(perp)
                ey = py + sign * leaf_len * math.sin(perp)
                draw.line([(int(px), int(py)), (int(ex), int(ey))], fill=color, width=stem_w)

    elif "easter" in s:
        # ── Latin cross with draped cloth over the crossbar ───────────────────
        hy = y + pad + (side - 2 * pad) * 2 // 5   # crossbar y
        # Draw cross first
        draw.rectangle([cx - arm_w // 2, y + pad, cx + arm_w // 2, y + side - pad], fill=color)
        draw.rectangle([x + pad, hy - arm_w // 2, x + side - pad, hy + arm_w // 2], fill=color)
        # Cloth: diagonal parallelogram (upper-right → lower-left) crossing crossbar
        ca = math.radians(-45)
        cdx, cdy = math.cos(ca), math.sin(ca)       # along-cloth unit vector
        pdx, pdy = -math.sin(ca), math.cos(ca)      # perpendicular unit vector
        half_len = r * 3 // 5
        half_wid = int(arm_w * 1.2)
        cloth_pts = [
            (cx + cdx * half_len + pdx * half_wid, hy + cdy * half_len + pdy * half_wid),
            (cx + cdx * half_len - pdx * half_wid, hy + cdy * half_len - pdy * half_wid),
            (cx - cdx * half_len - pdx * half_wid, hy - cdy * half_len - pdy * half_wid),
            (cx - cdx * half_len + pdx * half_wid, hy - cdy * half_len + pdy * half_wid),
        ]
        draw.polygon([(int(px), int(py)) for px, py in cloth_pts],
                     fill=background, outline=color)

    elif "pentecost" in s:
        # ── Three tongues of fire ─────────────────────────────────────────────
        n_flames = 3
        fw = max(3, r * 2 // (n_flames * 2 + 1))   # flame half-width
        spacing = fw * 2 + max(2, fw // 3)
        base_y = cy + r // 3
        for i in range(n_flames):
            fx = cx + (i - 1) * spacing
            tip_y = cy - r
            fh = base_y - tip_y
            # Teardrop: ellipse body + triangular tip
            draw.ellipse([fx - fw, tip_y + fh // 3, fx + fw, base_y], fill=color)
            draw.polygon([(fx, tip_y), (fx - fw, tip_y + fh // 3), (fx + fw, tip_y + fh // 3)],
                         fill=color)

    elif "trinity" in s:
        # ── Triquetra: three 300° arcs at 120° rotations ─────────────────────
        # Each circle passes through the other two circles' centres.
        # d = distance of arc-centre from main centre; arc_r = arc circle radius.
        d = r / (1 + math.sqrt(3))
        arc_r = d * math.sqrt(3)
        sq3h = math.sqrt(3) / 2
        centres = [
            (cx,               cy - d),           # top
            (cx + d * sq3h,    cy + d / 2),        # lower-right
            (cx - d * sq3h,    cy + d / 2),        # lower-left
        ]
        # (start, end) in Pillow's clockwise convention; each arc is 300°
        arcs = [(120, 60), (240, 180), (0, 300)]
        for (px, py), (start, end) in zip(centres, arcs):
            bbox = [px - arc_r, py - arc_r, px + arc_r, py + arc_r]
            draw.arc(bbox, start=start, end=end, fill=color, width=lw)

    elif "before advent" in s:
        # ── Crown: three-tined with solid body ────────────────────────────────
        crown_bot = cy + r // 2
        crown_mid = cy - r // 5      # top of solid body / base of tines
        tine_h = r * 4 // 5
        # Solid crown body
        draw.rectangle([cx - r, crown_mid, cx + r, crown_bot], fill=color)
        # Bottom band
        draw.rectangle([cx - r, crown_bot - lw * 2, cx + r, crown_bot], fill=color)
        # Three tines (centre tine tallest)
        tine_positions = [
            (cx - r * 2 // 3, tine_h * 3 // 4),  # left tine
            (cx,               tine_h),             # centre tine (tallest)
            (cx + r * 2 // 3, tine_h * 3 // 4),  # right tine
        ]
        tine_hw = r // 3    # half-width of each tine base
        for tx, th in tine_positions:
            draw.polygon([
                (tx, crown_mid - th),
                (tx - tine_hw, crown_mid),
                (tx + tine_hw, crown_mid),
            ], fill=color)

    else:
        # ── Fallback: plain Latin cross ───────────────────────────────────────
        draw.rectangle([cx - arm_w // 2, y + pad, cx + arm_w // 2, y + side - pad], fill=color)
        hy = y + pad + (side - 2 * pad) * 2 // 5
        draw.rectangle([x + pad, hy - arm_w // 2, x + side - pad, hy + arm_w // 2], fill=color)


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
            img.paste(simg, (0, portrait_y))
        except Exception:
            pass
    elif not has_saint:
        sym_side = min(portrait_side, slot_h)
        sym_y = portrait_y + (slot_h - sym_side) // 2
        _draw_season_symbol(draw, season or "", 0, sym_y, sym_side, foreground, background)

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
