# E-Paper Scribe

A Home Assistant custom component that generates dithered content for e-ink displays. It acts as a **content provider, not a display controller** — it renders images and exposes metadata; your automations decide when and how to push that content to a display.

Designed for use with [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink), but the static files and sensor entities work with any display system that can fetch a URL or read HA state.

## How it works

Each config entry is a **provider** — a content source that knows how to fetch data, dither an image, and expose metadata as sensors. You configure providers via the UI and trigger them from automations or the Developer Tools.

When you call a service like `epaper_scribe.render_now_playing`, the integration:

1. Fetches content (artwork, calendar data, Wikipedia summary)
2. Dithers the image to your chosen palette (BW, BWR, or BWRY) using Floyd-Steinberg at the final display resolution
3. Writes a static PNG to `/config/www/epaper_scribe/` (accessible as `/local/epaper_scribe/…`)
4. Updates HA image and sensor entities with the new data
5. Returns the metadata dict so automations can use it directly in `drawcustom` payloads via `response_variable`

Display layout — coordinates, fonts, colors, text positioning — lives entirely in your automations. Different display sizes get different automations. The integration just provides the content.

## Providers

### Now Playing

Fetches album artwork and playback metadata from a media player entity.

- **Artwork:** retrieved via HA's internal `async_get_media_image()` API — no long-lived access token required
- **Semantic fields:** maps raw media player attributes to display-friendly `creator`, `title`, and `container` fields based on content type (music, podcast, TV show, movie)
- **Static file:** `/local/epaper_scribe/now_playing_artwork_128.png` (height in filename; configurable size)
- **Sensors:** `state`, `creator`, `title`, `container`, `content_type`

### Liturgical Calendar

Fetches today's Anglican liturgical calendar data and a Wikipedia saint portrait.

- **Calendar:** uses the [`liturgical-calendar`](https://pypi.org/project/liturgical-calendar/) pip package
- **Wikipedia:** fetches a thumbnail portrait and one-sentence description for the day's saint
- **Caching:** same-day renders return cached data; use `force_refresh: true` to bypass
- **Static file:** `/local/epaper_scribe/saints_day_artwork_64.png`
- **Sensors:** `saint_name`, `saint_role`, `season`, `week`, `description`, `has_saint`

## Installation

1. Copy `custom_components/epaper_scribe/` into your HA `/config/custom_components/` directory.
2. Copy `blueprints/` into your HA `/config/blueprints/` directory (optional, for the included blueprint).
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **E-Paper Scribe**.

## Configuration

The config flow is two steps:

1. **Select provider type** — Now Playing or Liturgical Calendar
2. **Configure the provider** — entity, palette, default image size

Multiple config entries are supported (e.g., two media players, or Now Playing + Calendar on the same instance).

### Palettes

| Key    | Colors                    |
|--------|---------------------------|
| `bw`   | Black, White              |
| `bwr`  | Black, White, Red         |
| `bwry` | Black, White, Red, Yellow |

## Services

Both services support `SupportsResponse.OPTIONAL` — use `response_variable` in automations to chain render → drawcustom without needing separate sensor lookups.

### `epaper_scribe.render_now_playing`

| Field                  | Required | Description |
|------------------------|----------|-------------|
| `entry_id`             | No       | Target a specific entry (needed if multiple Now Playing entries exist) |
| `media_player_entity`  | No       | Override the configured media player |
| `size`                 | No       | Override image size, e.g. `128x128` |

### `epaper_scribe.render_saints_day`

| Field           | Required | Description |
|-----------------|----------|-------------|
| `entry_id`      | No       | Target a specific entry |
| `force_refresh` | No       | Bypass the same-day cache (default: `false`) |
| `size`          | No       | Override image size, e.g. `64x64` |

## Example automation

```yaml
automation:
  - alias: "E-ink: Now Playing"
    trigger:
      - platform: state
        entity_id: media_player.kitchen_apple_tv
        to: "playing"
    action:
      - service: epaper_scribe.render_now_playing
        response_variable: np
      - service: open_epaper_link.drawcustom
        target:
          device_id: "your_device_id"
        data:
          background: white
          payload:
            - type: dlimg
              url: "/local/epaper_scribe/now_playing_artwork_128.png"
              x: 0
              y: 0
              xsize: 128
              ysize: 128
            - type: rectangle
              x_start: 129
              y_start: 0
              x_end: 295
              y_end: 38
              fill: red
              outline: red
            - type: text
              value: "{{ np.creator }}"
              x: 135
              y: 11
              size: 16
              font: ppb.ttf
              color: white
            - type: text
              value: "{{ np.title }}"
              x: 135
              y: 46
              size: 18
              font: ppb.ttf
              color: black
            - type: text
              value: "{{ np.container }}"
              x: 135
              y: 90
              size: 13
              font: rbm.ttf
              color: black
```

## Blueprint

A ready-to-import blueprint is included for a **296×128 BWR display** with now-playing artwork and liturgical calendar fallback:

`blueprints/automation/epaper_scribe/now_playing_with_calendar_fallback_296x128.yaml`

**Behavior:**
- Media player → `playing`: render now playing + push to display
- Media player → `paused` for N seconds (default 120): switch to calendar view
- Media player → `idle` / `off`: switch to calendar view
- 00:05 daily: refresh calendar for the new date

Import it via **Settings → Automations → Blueprints → Import Blueprint**.

## Adding a new provider

1. Create `custom_components/epaper_scribe/providers/my_provider.py`
2. Subclass `ContentProvider` and implement `async_render()`, `get_config_schema()`, `get_service_schema()`
3. Register it in `PROVIDER_REGISTRY` in both `__init__.py` and `config_flow.py`

No changes to `image.py`, `sensor.py`, or the config flow steps are needed.
