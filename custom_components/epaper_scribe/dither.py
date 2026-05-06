"""Shared Pillow dithering utility for e-paper displays.

Pipeline: resize to target size first, then dither. This order is critical —
dithering at the final pixel dimensions produces much better results than
dithering large and downscaling, because Floyd-Steinberg error diffusion
creates spatial patterns that get destroyed by resampling.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

from .const import PALETTES, PALETTE_BWR

_LOGGER = logging.getLogger(__name__)


def dither_pil_image(img: "Image.Image", palette_name: str) -> "Image.Image":
    """Dither a PIL Image to the named palette and return an RGB PIL Image.

    Synchronous — intended to be called from within an executor job so it
    doesn't block the event loop.  Use this to dither individual external
    images (portrait, album art) before compositing them onto the canvas,
    rather than dithering the fully-composed canvas.
    """
    palette_colors = PALETTES.get(palette_name, PALETTES[PALETTE_BWR])
    n_colors = len(palette_colors) // 3
    padded = palette_colors + [0, 0, 0] * (256 - n_colors)
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(padded)
    dithered = img.convert("RGB").quantize(
        palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG
    )
    return dithered.convert("RGB")


def _dither_sync(image_bytes: bytes, size: tuple[int, int], palette_name: str) -> bytes:
    """Synchronous dithering — run in executor to avoid blocking the event loop."""
    palette_colors = PALETTES.get(palette_name, PALETTES[PALETTE_BWR])

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img = img.resize(size, Image.LANCZOS)

    # Pad palette to 256 colors (768 bytes required by Pillow)
    n_colors = len(palette_colors) // 3
    padded = palette_colors + [0, 0, 0] * (256 - n_colors)

    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(padded)

    dithered = img.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
    result = dithered.convert("RGB")

    buf = BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


async def async_dither(
    hass,
    image_bytes: bytes,
    size: tuple[int, int],
    palette_name: str = PALETTE_BWR,
) -> bytes:
    """Resize then dither an image. Returns PNG bytes. Non-blocking."""
    return await hass.async_add_executor_job(
        _dither_sync, image_bytes, size, palette_name
    )


def make_placeholder(
    size: tuple[int, int],
    color: tuple[int, int, int] = (128, 128, 128),
) -> bytes:
    """Generate a solid-color placeholder as PNG bytes."""
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def async_render_to_file(
    hass,
    filename: str,
    image_bytes: bytes | None,
    size: tuple[int, int],
    palette: str = PALETTE_BWR,
    placeholder_color: tuple[int, int, int] = (128, 128, 128),
) -> bool:
    """Write a dithered image to <config>/www/epaper_scribe/<filename>.

    Always writes a placeholder first so the file exists even if dithering
    fails. Then attempts to dither image_bytes and overwrites the placeholder
    if successful.

    Returns True if a real dithered image was written, False if the
    placeholder was used (no image_bytes, or dithering raised an exception).
    """
    www_dir = hass.config.path("www", "epaper_scribe")
    path = os.path.join(www_dir, filename)
    _LOGGER.debug("async_render_to_file: writing to %s", path)

    def _write(data: bytes) -> None:
        os.makedirs(www_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        _LOGGER.debug("async_render_to_file: wrote %d bytes to %s", len(data), path)

    try:
        await hass.async_add_executor_job(_write, make_placeholder(size, placeholder_color))
        _LOGGER.warning("async_render_to_file: placeholder written to %s", path)
    except Exception as exc:
        _LOGGER.error("async_render_to_file: failed to write placeholder to %s: %s", path, exc)
        return False

    if not image_bytes:
        return False

    try:
        dithered = await async_dither(hass, image_bytes, size, palette)
        await hass.async_add_executor_job(_write, dithered)
        _LOGGER.warning("async_render_to_file: dithered image written to %s", path)
        return True
    except Exception as exc:
        _LOGGER.warning("Failed to dither image for %s: %s", filename, exc)
        return False


async def async_write_to_file(
    hass,
    filename: str,
    image_bytes: bytes | None,
    size: tuple[int, int],
    placeholder_color: tuple[int, int, int] = (128, 128, 128),
) -> bool:
    """Write a pre-rendered image to <config>/www/epaper_scribe/<filename>
    WITHOUT dithering the full canvas.

    Use this when the canvas is already rendered in palette-correct colors
    (pure black/white/red) and any embedded external images have already been
    individually dithered before compositing.  Skipping the full-canvas
    Floyd-Steinberg pass preserves crisp pixel-rendered text and icons.

    Always writes a placeholder first so the file exists even if the write
    fails.  Returns True if the real image was written, False if only the
    placeholder was used.
    """
    www_dir = hass.config.path("www", "epaper_scribe")
    path = os.path.join(www_dir, filename)
    _LOGGER.debug("async_write_to_file: writing to %s", path)

    def _write(data: bytes) -> None:
        os.makedirs(www_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        _LOGGER.debug("async_write_to_file: wrote %d bytes to %s", len(data), path)

    try:
        await hass.async_add_executor_job(_write, make_placeholder(size, placeholder_color))
    except Exception as exc:
        _LOGGER.error("async_write_to_file: failed to write placeholder to %s: %s", path, exc)
        return False

    if not image_bytes:
        return False

    try:
        await hass.async_add_executor_job(_write, image_bytes)
        _LOGGER.debug("async_write_to_file: image written to %s", path)
        return True
    except Exception as exc:
        _LOGGER.warning("async_write_to_file: failed to write image to %s: %s", path, exc)
        return False
