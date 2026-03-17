# Adding a New Content Provider

Each content provider is a single file in `custom_components/epaper_scribe/providers/`.
Adding one requires touching six files total — the provider itself, plus five small
registration entries. No other files need changes.

---

## 1. Create the provider file

`providers/my_provider.py` — implement `ContentProvider`:

```python
from ..dither import async_render_to_file
from . import ContentProvider, SensorDescription

SENSORS = [
    SensorDescription("field_key", "Display Name", "mdi:icon-name"),
    # one entry per sensor entity this provider exposes
]

class MyProvider(ContentProvider):
    PROVIDER_TYPE = "my_provider"       # snake_case, unique across all providers
    PROVIDER_NAME = "My Provider"       # shown in HA UI
    SENSORS = SENSORS

    @staticmethod
    def get_config_schema() -> dict:
        # keys the user fills in during config flow setup
        return {
            vol.Optional(CONF_PALETTE, default=PALETTE_BWR): vol.In(["bw","bwr","bwry"]),
            vol.Optional(CONF_DEFAULT_SIZE, default="296x128"): str,
        }

    @staticmethod
    def get_service_schema() -> dict:
        # keys accepted by the render service call
        return {
            vol.Optional("force_refresh", default=False): bool,
        }

    async def async_render(self, **kwargs) -> dict[str, Any]:
        size = _parse_size(self.config.get(CONF_DEFAULT_SIZE, "296x128"))
        palette = self.config.get(CONF_PALETTE, PALETTE_BWR)

        # --- fetch your data ---
        image_bytes = await ...   # or None if no image

        # --- write image file (always safe, never raises) ---
        filename = f"my_provider_{size[1]}.png"
        await async_render_to_file(
            self.hass, filename, image_bytes, size, palette,
            placeholder_color=(200, 200, 200),
        )
        # async_render_to_file guarantees:
        #   • placeholder written first → file always exists
        #   • dithered image overwrites placeholder on success
        #   • returns True if real image written, False if placeholder used

        data = {"field_key": "value", ...}
        self._sensor_data = data
        self._image_last_updated = datetime.now()
        return data
```

### Shared utilities

| Import | Purpose |
|---|---|
| `async_render_to_file(hass, filename, image_bytes, size, palette, placeholder_color)` | Write placeholder + dither + overwrite. Returns `bool` (has real image). |
| `async_get_clientsession(hass)` | aiohttp session for external HTTP calls |
| `hass.async_add_executor_job(fn, *args)` | Run blocking code off the event loop |

---

## 2. Register in `const.py`

```python
PROVIDER_MY_PROVIDER = "my_provider"
```

---

## 3. Register in `__init__.py`

Import the class and add to `PROVIDER_REGISTRY`, then add a service handler:

```python
from .providers.my_provider import MyProvider

PROVIDER_REGISTRY = {
    ...
    PROVIDER_MY_PROVIDER: MyProvider,
}
```

In `_register_services`, copy an existing handler — change the isinstance check,
warning text, and service name to match your provider.

---

## 4. Add config flow step in `config_flow.py`

Import `PROVIDER_MY_PROVIDER` and `MyProvider`, add to `PROVIDER_REGISTRY`, add to
`async_show_menu`, and add `async_step_my_provider` + an options flow branch
following the existing pattern.

---

## 5. Add strings in `strings.json` and `translations/en.json`

Add a menu option under `config.step.user.menu_options` and a step entry under
`config.step` with `title` and `data` labels for each config field.

---

## 6. Document the service in `services.yaml`

Add a `render_my_provider` block listing `entry_id`, `force_refresh`, and any
provider-specific fields.

---

## 7. Add a display layout to the blueprints

- **`display_control_296x128.yaml`** — add to the `fields.mode.selector.select.options`
  list and add a `choose` branch with `conditions: "{{ mode == 'my_provider' }}"`.
- **`now_playing_with_calendar_fallback_296x128.yaml`** — add to the `fallback_mode`
  selector options and add a branch in the fallback `choose` if you want it
  available as a reactive fallback mode.

---

## Checklist

- [ ] `providers/my_provider.py` — `ContentProvider` subclass
- [ ] `const.py` — `PROVIDER_MY_PROVIDER` constant
- [ ] `__init__.py` — registry entry + service handler
- [ ] `config_flow.py` — menu option + step + options flow branch
- [ ] `strings.json` + `translations/en.json` — menu label + field labels
- [ ] `services.yaml` — service documentation
- [ ] Blueprints — display layout in script and/or automation blueprint
- [ ] Bump `manifest.json` version and create a GitHub release
