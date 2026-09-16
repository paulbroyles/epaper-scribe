# Now Playing E-Ink Display — Deployment Instructions

## Overview

This project drives a 296×128 black/white/red e-ink display via OpenEPaperLink,
showing what's currently playing on an Apple TV / HomePod, and switching to a
saint's day display when nothing is playing.

## Prerequisites

- Home Assistant OS with the following add-ons installed and running:
  - OpenEPaperLink (HACS integration)
  - AppDaemon
  - Advanced SSH & Web Terminal (needed only for the Apple TV integration patch)
- A 296×128 BWR e-ink display registered in OpenEPaperLink
- An Apple TV and/or HomePod integrated into HA

---

## Step 1: Apply the Apple TV Integration Patch

> This fixes a bug where the Apple TV reports "off" instead of "playing" when
> the HomePod is playing audio while the Apple TV is asleep. Required for the
> display to respond to HomePod playback.

1. Open the **Advanced SSH & Web Terminal** add-on (requires Protection Mode off)
2. Get into the HA container:
   ```bash
   docker exec homeassistant python3 -c "
   path = '/usr/src/homeassistant/homeassistant/components/apple_tv/media_player.py'
   with open(path, 'r') as f:
       content = f.read()
   old = '''        if (
               self._is_feature_available(FeatureName.PowerState)
               and self.atv.power.power_state == PowerState.Off
           ):
               return MediaPlayerState.OFF
           if self._playing:
               state = self._playing.device_state
               if state in (DeviceState.Idle, DeviceState.Loading):
                   return MediaPlayerState.IDLE
               if state == DeviceState.Playing:
                   return MediaPlayerState.PLAYING
               if state in (DeviceState.Paused, DeviceState.Seeking, DeviceState.Stopped):
                   return MediaPlayerState.PAUSED
               return MediaPlayerState.IDLE  # Bad or unknown state?
           return None'''
   new = '''        if self._playing:
               state = self._playing.device_state
               if state == DeviceState.Playing:
                   return MediaPlayerState.PLAYING
               if state in (DeviceState.Paused, DeviceState.Seeking, DeviceState.Stopped):
                   return MediaPlayerState.PAUSED
               if state in (DeviceState.Idle, DeviceState.Loading):
                   return MediaPlayerState.IDLE
           if (
               self._is_feature_available(FeatureName.PowerState)
               and self.atv.power.power_state == PowerState.Off
           ):
               return MediaPlayerState.STANDBY
           return MediaPlayerState.IDLE if self._playing else None'''
   if old in content:
       content = content.replace(old, new)
       with open(path, 'w') as f:
           f.write(content)
       print('Patch applied successfully')
   else:
       print('ERROR: Pattern not found — patch may already be applied or HA version differs')
   "
   ```
3. Restart HA Core: **Settings → System → Restart**

> **Note:** This patch is wiped on every HA Core update and must be reapplied.
> Monitor https://github.com/home-assistant/core/issues/157110 for an official fix.

---

## Step 2: Configure HA Files

### 2a. inputs.yaml
Copy `ha-config/inputs.yaml` to `/config/inputs.yaml`.

Edit the `initial` value to match your media player entity ID:
```yaml
initial: "media_player.your_apple_tv"
```

### 2b. templates.yaml
Copy `ha-config/templates.yaml` to `/config/templates.yaml`.

Edit the trigger list to match your media player entity ID (appears twice):
```yaml
      entity_id:
        - input_text.now_playing_source_entity
        - media_player.your_apple_tv   # ← change this
    - platform: state
      entity_id: media_player.your_apple_tv   # ← and this
```

### 2c. configuration.yaml
Add these lines to `/config/configuration.yaml` if not already present:
```yaml
input_text: !include inputs.yaml
template: !include templates.yaml
```

### 2d. Validate and Restart
- **Developer Tools → YAML → Check Configuration**
- If clean: **Settings → System → Restart**

---

## Step 3: Generate a Long-Lived Access Token

1. Click your profile name (bottom left in HA)
2. Scroll to **Long-Lived Access Tokens**
3. Click **Create Token**, name it "Artwork Script"
4. Copy the token — it's only shown once

---

## Step 4: Configure AppDaemon

### 4a. Python packages
In **Settings → Add-ons → AppDaemon → Configuration tab**, set:
```yaml
python_packages:
  - Pillow
  - requests
  - pillow-heif
  - liturgical-calendar
system_packages: []
```
Save and restart AppDaemon to install packages.

### 4b. Deploy app files

From your local machine (requires SSH access to HA):
```bash
make deploy HA_HOST=homeassistant.local
```

This copies the AppDaemon apps and HA config files in one step. If your HA
hostname or IP differs, pass `HA_HOST=<your-host>`. Run `make` with no
arguments to see available targets.

Alternatively, copy manually:
```
/addon_configs/a0d7b954_appdaemon/apps/
```

### 4c. Edit now_playing.py
Open `now_playing.py` and replace the placeholder values:
```python
HA_TOKEN = "YOUR_LONG_LIVED_ACCESS_TOKEN"   # from Step 3
# Also update the media player entity ID in do_update():
entity_picture = self.hass.get_state(
    "media_player.your_apple_tv",   # ← your entity ID
    attribute="entity_picture"
)
```

### 4d. Edit display_supervisor.py, now_playing.py, and saints_day.py
Replace the display MAC address and HA device ID in all three files:
```python
DEVICE_ID = "fd8f9a44064425f5f4a8c7ca5a63fd80"  # ← your HA device ID
```
Find your HA device ID at:
**Settings → Devices & Services → OpenEPaperLink → your display → URL in browser**

Also update the AppDaemon artwork serve URL if your AppDaemon port differs from 5050:
```python
ARTWORK_URL = "http://homeassistant.local:5050/local/now_playing_artwork.png"
```

### 4e. Restart AppDaemon
Check **Settings → Add-ons → AppDaemon → Log** for:
```
INFO display_supervisor: DisplaySupervisor initialized
INFO now_playing: NowPlaying app initialized
INFO saints_day: SaintsDay app initialized
```

---

## Step 5: Verify

1. Play something on your Apple TV / HomePod
2. The display should update within ~40 seconds (check-in interval) showing:
   - Dithered album art on the left (128×128)
   - Red band at top with artist/creator name
   - Track title below
   - Album/container below that
3. Stop or pause playback for 2+ minutes
4. The display should switch to the saint's day or liturgical season view

---

## Switching the Source Device

To point the display at a different media player without changing app code:

**Option A — Edit inputs.yaml** (requires HA restart):
```yaml
initial: "media_player.different_device"
```

**Option B — Edit the value at runtime** via Developer Tools → States,
find `input_text.now_playing_source_entity`, and change the value.
Also update the trigger list in `templates.yaml` and restart HA.

---

## Switching to the Catholic Calendar

In `saints_day.py`, find `do_update()` and change one line:
```python
# From:
saint_title, rank, season, week = self.fetch_saint_anglican()
# To:
saint_title, rank, season, week = self.fetch_saint_catholic()
```
Note: the Catholic API returns no saint on plain Lenten/Advent weekdays by design.

---

## File Reference

| File | Location | Purpose |
|------|----------|---------|
| `inputs.yaml` | `/config/inputs.yaml` | Defines the source media player entity |
| `templates.yaml` | `/config/templates.yaml` | Template sensors wrapping the media player |
| `display_supervisor.py` | AppDaemon apps dir | Watches state, delegates to now_playing or saints_day |
| `now_playing.py` | AppDaemon apps dir | Fetches media info, dithers artwork, updates display |
| `saints_day.py` | AppDaemon apps dir | Fetches saint/season data, updates display when idle |
| `apps.yaml` | AppDaemon apps dir | Registers all AppDaemon apps |
