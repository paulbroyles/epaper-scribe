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

MEDIAL_DOT = " · "

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
    dot_w = int(draw.textlength(MEDIAL_DOT, font=name_font))
    name_widths = [int(draw.textlength(seg.name, font=name_font)) for seg in segments]
    cur = x
    for i, seg in enumerate(segments):
        _text(img, draw, (cur, y), seg.name, name_font, color)
        cur += name_widths[i]
        if i < len(segments) - 1:
            _text(img, draw, (cur, y), MEDIAL_DOT, name_font, color)
            cur += dot_w


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

    dot_w = int(draw.textlength(MEDIAL_DOT, font=name_font))
    name_widths = [int(draw.textlength(seg.name, font=name_font)) for seg in segments]

    # X offset for each segment's name start
    x_offsets: list[int] = []
    cur = x
    for i, w in enumerate(name_widths):
        x_offsets.append(cur)
        cur += w
        if i < len(segments) - 1:
            cur += dot_w

    # Name line
    for i, seg in enumerate(segments):
        _text(img, draw, (x_offsets[i], y), seg.name, name_font, color)
        if i < len(segments) - 1:
            _text(img, draw, (x_offsets[i] + name_widths[i], y), MEDIAL_DOT, name_font, color)

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
) -> None:
    """Draw a simple liturgical season glyph centred in the square (x,y,side)."""
    import math

    s = season.lower() if season else ""
    cx = x + side // 2
    cy = y + side // 2
    pad = max(2, side // 6)
    r = side // 2 - pad
    arm_w = max(2, side // 8)

    def _latin_cross() -> None:
        # Vertical arm
        draw.rectangle([cx - arm_w // 2, y + pad, cx + arm_w // 2, y + side - pad], fill=color)
        # Horizontal arm, 2/5 down from top
        hy = y + pad + (side - 2 * pad) * 2 // 5
        draw.rectangle([x + pad, hy - arm_w // 2, x + side - pad, hy + arm_w // 2], fill=color)

    if "advent" in s:
        # Candle with triangular flame
        bw = max(2, side // 5)
        draw.rectangle([cx - bw // 2, cy - r // 3, cx + bw // 2, cy + r], fill=color)
        draw.polygon(
            [(cx, cy - r - r // 3), (cx - bw // 2, cy - r // 3), (cx + bw // 2, cy - r // 3)],
            fill=color,
        )
    elif "christmas" in s or "epiphany" in s:
        # Five-pointed star
        ri = r // 2
        pts = [
            (cx + (r if i % 2 == 0 else ri) * math.cos(math.radians(-90 + i * 36)),
             cy + (r if i % 2 == 0 else ri) * math.sin(math.radians(-90 + i * 36)))
            for i in range(10)
        ]
        draw.polygon(pts, fill=color)
    elif "easter" in s:
        # Latin cross + sunrise arc beneath crossbar
        _latin_cross()
        hy = y + pad + (side - 2 * pad) * 2 // 5
        lw = max(1, arm_w // 2)
        draw.arc(
            [cx - r // 2, hy + arm_w, cx + r // 2, cy + r],
            start=200, end=340, fill=color, width=lw,
        )
    else:
        # Latin cross for Lent, Ordinary, Holy Week, and everything else
        _latin_cross()


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
    background: tuple[int, int, int] = (255, 255, 255),
    foreground: tuple[int, int, int] = (0, 0, 0),
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

    # ---- Font loader --------------------------------------------------------
    def _load(pt: int) -> "FreeTypeFont":
        if font_path:
            try:
                return ImageFont.truetype(font_path, pt)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=pt)
        except TypeError:
            return ImageFont.load_default()

    role_pt = max(9, H // 11)
    desc_pt_min = max(8, H // 16)
    role_font = _load(role_pt)

    # ---- Portrait slot width ------------------------------------------------
    portrait_side = min(H // 2, W // 4)

    # ---- Probe draw context (1×1 throwaway) ---------------------------------
    probe_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # ---- Name / header font: shrink to fit full panel width -----------------
    if has_saint:
        name_line = MEDIAL_DOT.join(seg.name for seg in parsed.segments)
        name_pt = max(role_pt + 2, H // 4)
        while name_pt > role_pt + 2:
            if int(probe_draw.textlength(name_line, font=_load(name_pt))) <= W - 2 * PAD:
                break
            name_pt -= 1
    else:
        ferial_text = week if week else (season or "")
        name_pt = max(9, H // 10)
        while name_pt > 9:
            if int(probe_draw.textlength(ferial_text, font=_load(name_pt))) <= W - 2 * PAD:
                break
            name_pt -= 1

    name_font = _load(name_pt)

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
    avail_h = H - text_y - PAD

    # ---- Scale description font up to fill available space ------------------
    desc_pt = desc_pt_min
    if description and text_w > 0 and avail_h > 0:
        max_desc_pt = max(desc_pt_min, min(H // 2, 80))
        for pt in range(max_desc_pt, desc_pt_min - 1, -1):
            f = _load(pt)
            lines = _wrap_lines(description, text_w, probe_draw, f)
            _, _, _, lh = probe_draw.textbbox((0, 0), "Ag", font=f)
            if (lh + 1) * len(lines) <= avail_h:
                desc_pt = pt
                break

    desc_font = _load(desc_pt)

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
        dot_w_n = int(probe_draw.textlength(MEDIAL_DOT, font=name_font))
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
                cur += dot_w_n

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
        _draw_season_symbol(draw, season or "", 0, sym_y, sym_side, foreground)

    # ---- Text column: description at scaled-up font -------------------------
    if description and text_w > 0 and avail_h > 0:
        _draw_wrapped(img, draw, description, text_x, text_y, text_w, avail_h, desc_font, foreground)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
