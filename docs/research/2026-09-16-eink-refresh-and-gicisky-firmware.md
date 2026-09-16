# E-ink refresh behavior and Gicisky custom firmware

**Research date:** 2026-09-16
**Status:** Deferred. No firmware changes made. The red-buffer limitation (see
[Region-only refresh](#region-only-refresh)) means custom firmware using
conventional waveforms could not deliver blink-free updates for red content,
which is a large part of the goal, so the risk of flashing is not currently
justified. The [phased-update addendum](#addendum-phased-updates) describes an
untested way the limitation might be avoided, which would change the payoff
(not the risk) of experimenting.

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
- **With conventional waveforms, any change to red content requires a
  full-panel refresh**, which flashes the entire screen. In Now Playing the artist name is white text on the red
  header bar, so an artist change would always blink the whole panel.
- Repeated partial updates build up ghosting, and unchanged red areas may fade;
  a periodic full refresh is needed regardless.
- Custom waveforms are fixed, while factory waveforms compensate for
  temperature, so partial-update quality varies with room temperature.

Consequence for the goal: with conventional waveforms, the best achievable is
"black/white changes don't blink; anything touching red blinks the whole
screen." For layouts that put changing content on red, that is a large part of
the problem left unsolved. The addendum below describes a possible way around
this.

### Addendum: phased updates

Added later on 2026-09-16, from follow-up discussion. Reasoning from how the
controller works and from atc1441's driver code; not tested, and no existing
implementation was found. Several points are confirmed or corrected by the
[hardware documentation addendum](#addendum-hardware-documentation) below;
corrections are marked inline.

**The controller doesn't know what "red" is.** For each pixel it reads one bit
from 0x24 and one from 0x26; the 2-bit value selects one of four waveform groups
in the LUT (register 0x32). "0x26 means red" is only how the factory waveform is
written. atc1441's fast no-red LUT is consistent with this: groups 0 and 2 get
the same drive, and groups 1 and 3 the same, so the 0x26 bit has no effect.
Custom firmware can assign the two bits any meaning, per update.

**Update in phases.** Load different buffer contents and a different LUT for
each phase:

1. **Black/white phase.** 0x26 holds the previous image. Unchanged pixels get
   no voltage (VSS); changed pixels are driven to black or white, including
   pixels leaving red.
2. **Red phase.** 0x26 holds the red layer. The two not-red groups get no
   voltage, so black and white pixels don't move. The 0x24 bit of red pixels is
   repurposed as a "changed" flag: newly red pixels get the red waveform,
   unchanged red pixels get nothing. *(Corrected: no flag is needed. Write only
   newly red pixels as red in this phase; unchanged red pixels are written as
   not-red and get no voltage. This matters because the SSD1683 has no usable
   fourth group in three-color mode, and the SSD1680's handling of the fourth
   code is ambiguous.)*

Only pixels that change move. In Now Playing, an artist change would flicker
only the letter shapes on the red header bar, not the whole panel. Every
transition decomposes into these phases, so black/white/red changes together
need no special case.

**Why phases rather than one pass.** A single pass could use the four groups as
transition codes (unchanged, to black, to white, to red). But leaving red likely
needs a different drive than leaving black or white (a quick push to white may
leave a pink tint; red pixels probably need a reset through black), and four
groups can't give each transition its own waveform. Each added phase adds four
groups.

**Refinement: prepare red pixels in phase 1.** The factory red waveform first
conditions a pixel (resets it through black and/or white), then runs the slow
red step. Split it at that boundary:

- Phase 1 runs the conditioning part on newly red pixels, in parallel with the
  black/white changes, leaving them in whatever state the factory waveform has
  at the split point. That may be black rather than white; the factory LUT, not
  a guess, should decide. *(Documentation: in E Ink's three-particle waveforms
  the pixel is freshly driven white just before the red step, so white.)*
- Phase 2 runs only the red step on those pixels.

Benefits:
- Phase 2 is shorter, since conditioning runs concurrently with the black/white
  work instead of after it. The flicker is the same; it just happens earlier.
- Red pixels receive exactly the factory sequence, only split in time, so its
  charge balance and temperature-tuned timing are preserved.
- The group budget fits: phase 1 uses unchanged / to black / to white /
  prepare-for-red; phase 2 uses no-drive / red step.

Constraint: in the SSD16xx LUT, phase durations and repeat counts are shared by
all groups; only per-group voltages differ. *(Confirmed for the SSD1680 (2.9");
the SSD1683 (4.2") gives each group its own timing.)* The black/white drive and the red
conditioning must therefore fit one timing grid in phase 1, with groups idle
(VSS) in slots they don't use.

**Full-panel fallback** still makes sense when a large share of the screen
changes (a full refresh looks cleaner and blinks no worse), after N phased
updates to clear ghosting, and on a schedule such as the midnight redraw.

**Risks and unknowns:**

- **Edge halos.** Fields from driven pixels spill onto undriven neighbours. Red
  particles are slow and sensitive, so red text on a red bar is where tinting
  would show.
- **Red pixels still flicker** during conditioning, but only those pixels.
- **Charge balance.** Factory waveforms keep each pixel's net charge balanced;
  custom sequences for black/white pixels must too, or the panel risks image
  retention. Splitting the factory red waveform helps for red pixels.
- **Relaxation between phases.** Swapping buffers and LUTs between phases takes
  time; whether a conditioned pixel still takes the red step correctly after
  that gap is unknown.
- **Temperature.** Red timing depends heavily on temperature. A possible
  shortcut: have the controller load its factory LUT for the current
  temperature from OTP (0x22 with 0xB1), read it back from register 0x33, and
  derive the phase LUTs from it. atc1441's driver writes 0x32 and reads it back
  via 0x33, but whether the OTP-loaded waveform can be read this way is not
  confirmed.
- **Speed.** Updates touching red stay slow; the red step is the slow part of
  any refresh. The gain is less blinking, not faster updates.
- Still requires custom firmware, so the flashing risks and the
  red-through-Home Assistant bug below are unchanged.

### Addendum: hardware documentation

Added later on 2026-09-16. Sources: Solomon Systech datasheets (SSD1680 Rev 0.14,
SSD1683 Rev 1.0, SSD1681 Rev 0.13, SSD1675B Rev 1.4), E Ink/SiPix patents,
peer-reviewed papers on three-color electrophoretic waveforms, Good Display,
Waveshare and Pervasive Displays documentation, driver source (GxEPD2,
OpenEPaperLink, atc1441), and a decode of the current `ATC_BLE_OEPL.bin`.
Page numbers refer to the datasheets' own numbering.

#### What's in the tags

- **2.9": Telink SoC, SSD16xx controller.** High confidence on Telink (users
  flashed the Telink image onto tags reporting firmware 0x8101). The firmware's
  preset 12 uses SSD16xx commands; 296×128 fits the SSD1680. Exact panel and
  chip part numbers are not published.
- **4.2": probably the newer Telink generation, SSD16xx.** An older 4.2" Gicisky
  (atc1441 teardown, 2022) used a TI CC2640R2F with 2 MB SPI flash and reported
  hardware ID 0x004B / firmware 0x101. Ours reports 0x404B / 0x8101, matching the
  Telink pattern. 400×300 fits the SSD1683 (or SSD1619A). Medium confidence.
- **Pin maps** decoded from `ATC_BLE_OEPL.bin` (build Sep 7 2026; decode
  cross-checked against a Hanshow user's known-good config):
  2.9" preset 12: RST PB5, DC PB6, BUSY PC4, CS PD2, CLK PD7, MOSI PB7,
  panel enable PA0. 4.2" preset 22: same except BUSY PC0. No external flash
  defined for either.
- **Memory** (Telink TLSR8359 product brief, assuming that part): 48 KB SRAM
  (32 KB retained in sleep), 512 KB flash. A previous-frame copy fits in RAM for
  the 2.9"; for the 4.2" it would have to live in flash.
- **Candidate panel specs** (Good Display; not confirmed to be our panels):
  GDEY029Z95 (2.9", SSD1680): full 16 s, fast 11 s, partial 1.5 s, 0–40 °C,
  "Partial update only supports black and white display, not red."
  GDEY042Z98 (4.2", SSD1683): full 22 s, fast 16 s, partial 1.3 s, 0–40 °C.
  GxEPD2 measured full refreshes of ~26 s (2.9" C90c) and ~23 s (GDEY042Z98).

#### Controller facts (resolves several unknowns)

- **Waveform group is chosen purely by the two RAM bits.** SSD1680 Table 6-4
  (p13): RED 0/BW 0 → LUT0 (black), 0/1 → LUT1 (white), 1/0 → LUT2 (red),
  1/1 → "LUT 3 = LUT2" (the LUT layout still gives LUT3 its own bytes; which
  applies is unstated). LUT4 is VCOM. Voltage codes (Table 6-6): 00 VSS,
  01 VSH1, 10 VSL, 11 VSH2. The repurposing idea is sound.
- **SSD1683 differs.** Three-color mode has only three pixel LUTs (red, white,
  black); RED 1/BW 1 has no row, so treat it as undefined. Its black/white mode
  has true old→new transition LUTs (WW, BW, WB, BB) — a natural fit for the
  black/white phase.
- **Timing.** SSD1680: "Common setting of 5 LUT – 48 phases" (12 groups × 4
  phases; only voltages are per-LUT). SSD1683: "VS, TP, SR, RP are individual
  set for different LUT" (p13), one frame rate for the whole update. Also note
  SSD1683 repeat counts treat 0 as "skip"; SSD1680 treats 0 as "once."
- **Every update scans the whole panel.** No window-limited drive; the RAM
  window (0x44/0x45) only limits writes. Unchanged pixels step through the
  frames too, so their LUT must be VSS.
- **Custom LUTs survive only certain update commands.** 0x22 = 0xC7/0xCF
  display with the LUT register as written; 0xF7/0xFF reload from OTP and
  overwrite it. 0x21 can make the controller treat the red RAM as all 0
  ("Bypass RAM content as 0") without rewriting it.
- **Reading back the factory LUT (0x33) is undocumented** in all four
  datasheets, but works in practice: OpenEPaperLink's ZBS243 firmware loads the
  OTP waveform for the current temperature (0x22 = 0xB1), reads it with 0x33,
  edits it and writes it back — on SSD1619/1675-class chips. Plausible for
  SSD1680/1683, not confirmed. On a flashed tag the ATC uploader's
  "Download RAW LUT" (command `000D`) would settle it.
- **OTP temperature ranges.** SSD1680 stores 36 waveform sets with temperature
  bounds; "The last match will be selected," and with no match the "display
  will not be updated." Temperature can be sensed (0x18 = 0x80) or written
  (0x1A), which is how drivers force faster waveforms.
- **Between phases.** Analog power can stay on across consecutive updates
  (0xC0 on; update without the power-off bits; 0x03 off), keeping the gap short
  and consistent. End option 0x3F: 0x22 discharges pixels with two scan frames;
  0x07 keeps the pixel voltage but requires waiting for discharge before the
  next operation (SSD1683 §6.6).
- **PingPong / Mode 2 RAM behaviour is undocumented.** GxEPD2 behaviour suggests
  the controller may update 0x26 itself after a Mode 2 update; rewrite 0x26
  before a red phase.
- **Nothing in the datasheets addresses DC balance or limits on custom LUTs.**

#### Red-formation physics

- **Particle model** (E Ink US9360733, US11004409): black and white strongly
  and oppositely charged; red weakly charged ("about 5% to about 30%" of
  black/white) with black's polarity. Sequence: optional DC-balance pulse,
  shaking (e.g. ±15 V × 20 ms × 50), a high voltage driving the pixel fully
  white, then a low voltage (+3 to +5 V) that brings red forward while black
  stays behind its threshold. "The better the white state in this period, the
  better the red state." **The pixel is white before the red step.**
- **The red voltage window is narrow:** about 0.7 V for near-best red
  (US11004409); a lab study found 2.5 V the threshold below which red fails to
  migrate and above which black moves too. Lab red steps run 2–4 s.
- **Leaving red needs a full reset.** Every patent sequence shakes and fully
  drives before any color; clean black needs repeated extra pulses for "less red
  tinting." Leftover red causes "red ghost image"; GxEPD2 saw a "slightly
  reddish background" after many fast black/white refreshes.
- **Pauses are compatible with red formation.** E Ink's red-forming variant
  interleaves waits (under 100 ms and under 1000 ms, repeated ≥4 times; waits of
  5–5,000 ms depending on dielectric resistance) to dissipate stored charge.
  Particles are bistable at 0 V. But remnant voltage from the previous drive
  shifts the effective voltage (a 15 V pulse right after an update acts "closer
  to 16 V", ~15.2 V a minute later; US10475396), and much of it decays within
  ~20 ms (US8558783). With a 0.7 V window, **keep the inter-phase gap short and
  consistent**; its effect will vary with temperature.
- **DC balance.** Imbalance leaves remnant voltage, causes timing-dependent
  ghosting and possibly "slow lifetime degradation" (US10475396). Factory
  waveforms add pre-pulses so each transition integrates to zero. Pervasive
  Displays suspended its *windowed* partial update (only a rectangle's data
  sent) because pixels outside the window "degrade faster over time" and are
  "in an unbalanced/unstable state." Its *fast* update, which sends the full
  image and lets the controller compare old and new so only changed pixels are
  driven, is listed as having no lifespan impact and is what they recommend —
  but for monochrome only; their color panels support only full updates. So the
  warning is about windowed updates, not about leaving unchanged pixels undriven
  in a well-designed differential waveform. Pervasive doesn't explain the
  mechanism. For the phased scheme: each changed pixel's combined path across
  both phases must integrate to zero; a pixel conditioned but not given its red
  step is unbalanced. Keep VCOM at DC throughout.
- **Edge effects.** On an E Ink black/white panel, a driven pixel next to a
  0 V neighbour produces a lateral "diffusion field" leaving contour ghosts of
  ~25/255 gray levels that are "difficult to restore." GxEPD2's author warns
  partial windows "may lead to ugly borders," especially on three-color panels.
  **No measurements exist for red**; weakly charged red near black's threshold
  is likely more susceptible.
- **Temperature.** Red panels are rated 0–40 °C and don't operate below 0 °C;
  E Ink treats below ~10 °C as needing special waveforms. No quantitative data
  on red timing versus temperature was found.

#### Manufacturer guidance

- Good Display: red areas don't support partial refresh; allow at least 180 s
  between updates; full refresh after every 5 partial updates; refresh
  three-color panels at least every 24 h; store showing white. Waveshare gives
  the same 180 s / 24 h guidance and warns against leaving panels powered.
- Pervasive Displays: fast update (full image, controller compares old/new,
  "Possible ghosting", no lifespan impact) is monochrome only; windowed partial
  update is "suspended indefinitely" for lifespan reasons; color panels get
  normal (full) updates only.
- GxEPD2: every three-color driver sets `hasFastPartialUpdate = false`.

Note for current use: the 180 s minimum interval is a precaution that Now
Playing may already exceed on quick track skips.

#### Prior attempts

- No published differential refresh that forms red while unchanged pixels sit
  at 0 V, and no split conditioning/red scheme.
- Closest: jlarnal's custom full-screen LUTs on a UC8151D 2.9" BWR panel, full
  color in under 4 s, with periodic "deep scrubbing"; pskowronek's modified
  Waveshare 2.7" LUTs (black ~10×, red 2–3× faster) with artifacts that build up
  and are cleared by the original LUTs.
- Nothing published on fast or partial refresh for Gicisky tags on
  ATC_BLE_OEPL. The firmware logs "AP LUT=… → full/fast refresh," but a
  dedicated fast routine exists only for TI-controller tags.

#### Assessment

The documentation supports the phased scheme's mechanics: groups are selected
by the RAM bits, custom LUTs can be loaded and kept, analog power can stay on
between phases, and the pixel's pre-red state is white. The simplified phase
plan needs only three codes per phase:

1. Phase 1: unchanged (VSS) / to black (full reset) / to white or
   prepare-for-red (full reset to white).
2. Phase 2: no drive (VSS) / red step (newly red pixels only).

Remaining risks are empirical and can't be settled from documents: red-edge
halos, sensitivity of the narrow red voltage window to the inter-phase gap and
temperature, designing DC-balanced black/white paths, and whether the SSD1680
exposes its OTP waveform through 0x33. The 4.2" (SSD1683, per-group timing) is
the easier controller to experiment on; the 2.9" is the easier memory budget.

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
C; the 4.2" adds memory work. With conventional waveforms the red-buffer
limitation still applies. The phased approach in the addendum would add
per-phase LUT design (ideally derived from the factory LUT) and its own
experimentation, but no extra memory beyond the previous-frame copy.

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

Added for the hardware documentation addendum (accessed 2026-09-16):

- SSD1680 datasheet Rev 0.14:
  https://cdn-learn.adafruit.com/assets/assets/000/097/631/original/SSD1680_Datasheet.pdf
- SSD1683 datasheet Rev 1.0: https://archive.org/details/ssd1683
  (also https://www.buydisplay.com/download/ic/SSD1683.pdf)
- SSD1681 datasheet Rev 0.13:
  https://cdn-learn.adafruit.com/assets/assets/000/099/573/original/SSD1681.pdf
- SSD1675B datasheet Rev 1.4:
  https://github.com/CursedHardware/epd-driver-ic/blob/master/SSD1675B.pdf
- OpenEPaperLink Tag_FW_ZBS243 `ssd-var.c` / `lut.h`:
  https://github.com/OpenEPaperLink/Tag_FW_ZBS243
- GxEPD2 (drivers `GxEPD2_290_C90c`, `GxEPD2_420c_GDEY042Z98`, README):
  https://github.com/ZinggJM/GxEPD2
- atc1441 ATC_BLE_OEPL_CH573 (`epd_ssd.c`): https://github.com/atc1441/ATC_BLE_OEPL_CH573
- ATC_BLE_OEPL firmware image: https://atc1441.github.io/ATC_BLE_OEPL.bin
- atc1441 4.2" Gicisky teardown (2022): https://x.com/atc1441/status/1489590921016619016
- Telink TLSR8359 product brief:
  https://w2.electrodragon.com/Chip-cn-dat/TELINK-dat/PB_TLSR8359-E_Product%20Brief%20for%20Telink%20ULP%202.4GHz%20RF%20SoC%20TLSR8359.pdf
- Good Display GDEY029Z95: https://www.good-display.com/product/527.html
  (datasheet https://v4.cecdn.yun300.cn/100001_1909185148/GDEY029Z95.pdf)
- Good Display GDEY042Z98: https://www.good-display.com/product/387.html
- Good Display precautions: https://www.good-display.com/news/80.html,
  https://www.good-display.com/news/170.html
- Waveshare color e-paper precautions:
  https://www.waveshare.com/wiki/Template:E-paper-precautions-color
- Pervasive Displays, updating the display:
  https://docs.pervasivedisplays.com/knowledge/Technology/updating-the-display.html
- Pervasive Displays product selection:
  https://www.pervasivedisplays.com/product/epd-product-selection/
- E Ink Spectra 3100 notes: https://alcom.eu/uploads/E-Ink-SpectraTM-3100.pdf
- Patents: US9360733 https://patents.google.com/patent/US9360733B2/en,
  US11004409 https://patents.google.com/patent/US11004409B2/en,
  US9640119 https://patents.google.com/patent/US9640119B2/en,
  US10475396 https://patents.google.com/patent/US10475396B2/en,
  US8558783 https://patents.google.com/patent/US8558783B2/en,
  US11404012 https://patents.google.com/patent/US11404012B2/en
- Papers: https://pmc.ncbi.nlm.nih.gov/articles/PMC12901054/,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC9000271/,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7915761/,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11509696/,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6187556/
- jlarnal fast three-color LUTs (u8g2 issue #1393):
  https://github.com/olikraus/u8g2/issues/1393
- pskowronek epaper-clock-and-more: https://github.com/pskowronek/epaper-clock-and-more
- Arduino forum, 3-color SSD1680:
  https://forum.arduino.cc/t/help-with-3-color-ssd1680-controller/944410
- OEPL HA integration issue #326:
  https://github.com/OpenEPaperLink/Home_Assistant_Integration/issues/326
