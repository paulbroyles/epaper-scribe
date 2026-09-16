# E-ink refresh behavior and Gicisky custom firmware

**Research date:** 2026-09-16
**Status:** Deferred. No firmware changes made. The red-buffer limitation (see
[Region-only refresh](#region-only-refresh)) means custom firmware could not
deliver blink-free updates for red content, which is a large part of the goal,
so the risk of flashing is not currently justified.

Versions at the time: epaper_scribe 2.4.1, Home Assistant Core 2026.1.3,
OpenEPaperLink HA integration 2.8.0, OpenEPaperLink AP firmware (master as of
this date).

## Questions

1. Can red regions get the long, flashing three-color refresh while
   black/white regions get a lighter one?
2. Can unchanged regions be exempted from refresh? For example, in Now
   Playing the album art, album title and often the artist stay the same from
   track to track; could only the track title update?
3. Is any limit in the tag firmware or only in the AP code?
4. Which chips are in our tags, and what would flashing custom firmware
   involve?
5. What would writing or adapting firmware for region-only refresh take?

The interest is general: epaper_scribe may drive other displays, so the goal is
refresh improvements that carry over, not just fixes for Now Playing.

## Our hardware

Both tags are Gicisky BLE labels on stock firmware, reached through the
OpenEPaperLink ESP32 AP over Bluetooth. Data is from
`/config/.storage/open_epaper_link_tags` and `..._tagtypes` on the HA host.

| | Now Playing | Art Placard |
|---|---|---|
| OEPL name | Gicisky BLE EPD BWR 2.9" | Gicisky BLE EPD BWR 4.2" |
| OEPL hw_type | 179 (0xB3) | 181 (0xB5) |
| Resolution | 296×128 | 400×300 |
| Gicisky hardware ID (from MAC field) | 0x4033 | 0x404B |
| Stock firmware version | 0x8101 (reported as 33025) | 0x8101 |
| Capabilities | 0 (no custom LUTs) | 0 |
| AP `lut` setting | 1 (full) | 1 (full) |

The hardware ID is decoded by the AP in `ble_filter.cpp` (`compress_image`):
bits give resolution, panel type, colors, and a "no compression" flag
(0x4000, set on both).

## Findings

### Refresh modes in the current stack

- `open_epaper_link.drawcustom` accepts `refresh_type`
  (0 Full, 1 Fast, 2 Partial, 3 Partial2). Our blueprints don't set it, so it
  defaults to Full. The integration maps it to the AP's `lut` parameter
  (0→1 full, 1→3 fast, 2→2 fast no-reds, 3→0 no-repeats) in `services.py`.
- **For stock Gicisky tags the AP never sends that value.** The Gicisky upload
  in `ESP32_AP-Flasher/src/ble_writer.cpp` is: `0x01` init, `0x02` size,
  `0x03` start, then numbered 240-byte chunks. When the tag reports done
  (`0x08`) it refreshes on its own. There is no field for a refresh mode or a
  rectangle.
- **The limit is the tag firmware, not the AP.** The stock protocol has nowhere
  to put a mode, so the AP can't send one. For tags running atc1441's
  ATC_BLE_OEPL firmware, the same AP code sends an `AvailDataInfo` header whose
  `dataTypeArgument` carries the refresh mode, so the AP does forward it when
  the tag can accept it.
- **Identical frames are already skipped.** `newproto.cpp` compares the new
  image's MD5 with the tag's current one and logs "new image is the same as
  current image. not updating tag." Pause/resume and repeat renders don't
  blink.
- OpenEPaperLink transfers are always whole frames; no firmware in the OEPL
  ecosystem accepts a region update.

### How e-paper controllers refresh

- A refresh applies one waveform (LUT) across the whole active area. Red and
  black/white regions can't get different waveforms in one pass.
- Our tags use Solomon SSD16xx-family controllers (the firmware presets are
  named "Gici BWR SSD"). These controllers have no window-limited refresh: the
  RAM window commands (0x44/0x45) only limit where image data is written, and
  a display update (0x22/0x20) drives the whole panel.
- A "partial" refresh on these controllers is a waveform effect. The controller
  holds two buffers (0x24 and 0x26). In black/white partial mode, 0x26 holds the
  *previous* image and the waveform applies no voltage to pixels that didn't
  change, so unchanged areas stay still.

### Region-only refresh

**The red-buffer limitation.** On a black/white/red panel, buffer 0x26 holds the
red layer. It can't also hold the previous image. So:

- Black/white-only changes can be localized with a partial waveform, provided
  red is not driven during that update. This is the "fast no-reds" mode.
  atc1441's open-source ATC_TLSR_Paper drivers do exactly this: load a short
  LUT into 0x32, zero the red RAM, update with 0xC7.
- **Any change to red content requires a full-panel refresh**, which flashes
  the entire screen. In Now Playing the artist name is white text on the red
  header bar, so an artist change would always blink the whole panel.
- Repeated partial updates build up ghosting, and unchanged red areas may fade;
  a periodic full refresh is needed regardless.
- Custom waveforms are fixed, while factory waveforms compensate for
  temperature, so partial-update quality varies with room temperature.

Consequence for the goal: even with ideal custom firmware, the best achievable
is "black/white changes don't blink; anything touching red blinks the whole
screen." For layouts that put changing content on red, that is a large part of
the problem left unsolved.

### Chips and flashing

**Chip identification.** Both tags very likely use a Telink TLSR SoC
(TLSR8359 per atc1441). Evidence: the stock firmware version (0x8101) matches
units others have flashed, and a forum guide reports flashing both a Gicisky
2.9" and 4.2" successfully. Not certain: Gicisky has sold models with other
chips, and one user in 12/2024 called their 4.2" "not compatible" (after
flashing a 2.13" image).

Non-invasive check: pause the automations drawing to the tag, connect with a
BLE app (e.g. nRF Connect), and look for the Telink OTA service
`00010203-0405-0607-0809-0a0b0c0d1912`. atc1441's flasher uses the same check
("not using a Telink Chip or uses a different OTA method"). On the flasher page,
connect only: selecting a file starts flashing immediately.

**Procedure** (HA forum guide, post #18, and the OEPL HA integration README):

1. Use Chrome or Edge (Web Bluetooth); Safari lacks it. Disable automations
   that draw to the tag; keep the tag close to the computer.
2. Download `ATC_BLE_OEPL.bin` (universal image) from atc1441.github.io.
3. Open https://atc1441.github.io/BLE_EPaper_OTA.html, Connect, choose the tag,
   wait for "Connected, please select a file", select the .bin. Takes minutes.
4. Open https://atc1441.github.io/ATC_BLE_OEPL_Image_Upload.html, connect,
   Advanced view, Set Device Type: `12: 290 Gici BWR SSD` (2.9") or
   `22: 420 Gici BWR SSD` (4.2"). The tag reboots.
5. Test red with that page's image upload.
6. The tag appears in HA as a new device (via the AP, or directly over
   Bluetooth/ESPHome proxies with OEPL integration ≥ 2.0). Remove the old
   device and repoint the blueprints.

**Risks and known problems:**

- **Red lost through Home Assistant.**
  [OEPL HA integration issue #327](https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/327),
  open since 2026-01-06 (last comment 2026-04-12): flashed Gicisky 2.9", 2.13"
  and 4.2" BWR tags show red from atc1441's upload page, but `drawcustom` over
  direct Bluetooth renders red as black. Unknown whether uploads through the
  AP are affected. Critical for our layouts.
- **No return to stock.** Telink OTA only writes, and no stock image is
  published.
- **Recovery.** Wrong display type can be reset over Bluetooth from the upload
  page, though one user's 2.13" became unresponsive on the wrong preset (each of
  our sizes has only one Gicisky preset). Firmware that won't boot requires
  opening the case, soldering to the chip's SWS pin, and using a USB-UART
  adapter with https://atc1441.github.io/ATC_TLSR_Paper_UART_Flasher.html.
- **Flash failures.** One user's Windows laptop failed at 95–99% with GATT
  errors every time; a Mac succeeded first try.
- **Battery life** after flashing isn't documented; the firmware exposes an
  adjustable BLE advertising interval.
- **Upside reported:** near-instant updates and no more weekly AP resets.

**Refresh modes after flashing: unverified.**

- The OEPL HA integration's direct-Bluetooth path uses block upload for ATC
  tags (`ble/metadata.py`: "ATC devices don't support direct_write"), which
  carries no refresh mode. Its direct-write path, which does send a refresh
  byte, applies to OpenDisplay/OEPL-protocol firmware.
- Through the AP, the refresh mode is sent. The TLSR build of ATC_BLE_OEPL
  appears to be binary-only (no public source found), so whether it honors
  "fast no-reds" on these panels is unknown.
- The upload page's "LUT Playground" can load raw waveforms (SSD register 0x32,
  UC registers 0x20–0x25), so the firmware can at least change waveforms.
- Test once a tag is flashed: send through the AP with `refresh_type: 2`.

**Not applicable:** OpenDisplay firmware (the HA OpenDisplay integration, core
since 2026.4) targets nRF52840, nRF54, ESP32 and Silicon Labs chips, not
Telink.

### Custom firmware for region-only refresh: estimate

Design: keep the host side unchanged. The tag stores the last displayed frame;
when a whole frame arrives it compares them. If the red layer is identical, run
the black/white partial waveform with the old frame in 0x26; otherwise, or after
N partial updates, run a full refresh. It would work with epaper_scribe as is.

Work involved:

1. **Base.** atc1441's [ATC_TLSR_Paper](https://github.com/atc1441/ATC_TLSR_Paper)
   (TLSR8359, BLE, OTA, SSD16xx drivers with a no-red partial LUT) is open
   source but targets Hanshow tags. OEPL's `ARM_Tag_FW/OpenEPaperLink_TLSR` is
   also open but uses 802.15.4 (TLSR8258).
2. **Board bring-up.** Map the Gicisky pins (SPI, BUSY, RST, panel power) and
   write init sequences for 296×128 and 400×300.
3. **Waveform tuning.** Trial and error, temperature-sensitive. Most
   open-ended step.
4. **Memory.** Previous-frame copy: ~4.7 KB per layer for the 2.9" (likely
   fine); 15 KB per layer for the 4.2" (likely needs the tag's SPI flash).
5. **Protocol.** Match ATC/OEPL BLE so the AP and integration keep working.
   The AP side is open; the tag side of ATC_BLE_OEPL is not public, so this
   means reverse engineering. Alternative: a custom protocol sent directly from
   HA.
6. **Safety.** Always preserve OTA; solder SWS wires before experimenting.

Estimate: several weekends for the 2.9" for someone comfortable with embedded
C; the 4.2" adds memory work. And the red-buffer limitation still applies.

## Options that don't need firmware

- **Refresh-mode policy in epaper_scribe** (not built). epaper_scribe renders
  every frame, so it could compare with the last frame sent to a display and
  return a suggested `refresh_type`: Fast when the red layer is unchanged and
  the black/white change is small; Full otherwise, after N fast updates, or at
  the midnight redraw. The blueprint would pass it to `drawcustom`. Harmless on
  tags that ignore it; useful for OEPL-native tags (Solum/Hanshow) and possibly
  ATC-flashed tags.
- **Layout.** Keep frequently changing content off red. On a red panel, red is
  best reserved for content that changes rarely (e.g. the saint panel), not
  per-track information.
- **Hardware for future displays.** Black/white panels, or tags on OEPL
  firmware with working fast modes. True window-limited refresh needs a panel
  wired directly to a microcontroller running a driver such as GxEPD2, which
  epaper_scribe would reach outside OpenEPaperLink.

## Open questions

- Confirm the Telink OTA service on both tags.
- Does red survive uploads *through the AP* on ATC-flashed Gicisky tags?
- Does the TLSR ATC_BLE_OEPL firmware honor AP refresh modes on BWR panels?
- Exact display controller part numbers on the Gicisky boards.

## Sources

Accessed 2026-09-16.

- OpenEPaperLink source: https://github.com/OpenEPaperLink/OpenEPaperLink
  (`ESP32_AP-Flasher/src/ble_writer.cpp`, `ble_filter.cpp`, `newproto.cpp`,
  `resources/tagtypes/B3.json`, `B5.json`, `binaries/Tag/`)
- OEPL HA integration (installed copy on the HA host, and README):
  https://github.com/OpenEPaperLink/Home_Assistant_Integration
- OEPL HA integration issue #327:
  https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/327
- atc1441/ATC_GICISKY_ESL: https://github.com/atc1441/ATC_GICISKY_ESL
- atc1441/ATC_TLSR_Paper: https://github.com/atc1441/ATC_TLSR_Paper
  (`Firmware/src/epd_bwr_213.c`)
- atc1441/ATC_RTL_BLE_OEPL: https://github.com/atc1441/ATC_RTL_BLE_OEPL
- atc1441/ATC_BLE_OEPL_CH573: https://github.com/atc1441/ATC_BLE_OEPL_CH573
- Telink BLE E-Paper OTA flasher: https://atc1441.github.io/BLE_EPaper_OTA.html
- ATC_BLE_OEPL uploader: https://atc1441.github.io/ATC_BLE_OEPL_Image_Upload.html
- HA forum, "Using E-Ink Shop Price Tag with Home Assistant" (posts #18–21):
  https://community.home-assistant.io/t/using-e-ink-shop-price-tag-with-home-assistant/666150
- HA forum, "Support for Gicisky e-ink BLE ESL labels" (posts #25–26, #37–49):
  https://community.home-assistant.io/t/support-for-gicisky-e-ink-ble-esl-labels/778693
- Gadgetbridge, ATC_BLE_OEPL: https://gadgetbridge.org/gadgets/displays/atc_ble_oepl/
- eigger/hass-gicisky: https://github.com/eigger/hass-gicisky
- OpenDisplay: https://github.com/OpenDisplay, https://opendisplay.org
