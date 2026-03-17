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

from .const import PALETTES, PALETTE_BWR

_LOGGER = logging.getLogger(__name__)


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
    except Exception as exc:
        _LOGGER.error("async_render_to_file: failed to write placeholder to %s: %s", path, exc)
        return False

    if not image_bytes:
        return False

    try:
        dithered = await async_dither(hass, image_bytes, size, palette)
        await hass.async_add_executor_job(_write, dithered)
        return True
    except Exception as exc:
        _LOGGER.warning("Failed to dither image for %s: %s", filename, exc)
        return False
