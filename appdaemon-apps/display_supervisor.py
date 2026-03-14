import adbase as ad
from datetime import datetime, timezone

IDLE_STATES = ("unavailable", "unknown", "off", "idle", "")
PAUSED_TIMEOUT = 120  # seconds before switching to saint display

class DisplaySupervisor(ad.ADBase):

    def initialize(self):
        self.adapi = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS")
        self._mode_handle = None
        self._paused_handle = None

        self.hass.listen_state(
            self.on_state_change,
            "sensor.now_playing_state"
        )

        self.adapi.run_daily(self.on_midnight, "00:00:01")
        self.adapi.run_in(self.on_startup, 5)

        self.adapi.log("DisplaySupervisor initialized")

    def on_startup(self, kwargs):
        state = self.hass.get_state("sensor.now_playing_state")

        if state in IDLE_STATES:
            self.activate_saints_day()
        elif state == "paused":
            last_changed = self.hass.get_state(
                "sensor.now_playing_state",
                attribute="last_changed"
            )
            if last_changed:
                try:
                    changed_at = datetime.fromisoformat(
                        last_changed.replace("Z", "+00:00")
                    )
                    now = datetime.now(timezone.utc)
                    paused_seconds = (now - changed_at).total_seconds()
                    if paused_seconds >= PAUSED_TIMEOUT:
                        self.adapi.log(f"Already paused for {paused_seconds:.0f}s — going to saints_day")
                        self.activate_saints_day()
                    else:
                        remaining = PAUSED_TIMEOUT - paused_seconds
                        self.adapi.log(f"Paused for {paused_seconds:.0f}s — scheduling timeout in {remaining:.0f}s")
                        self._paused_handle = self.adapi.run_in(self.on_paused_timeout, remaining)
                        self.activate_now_playing()
                except Exception as e:
                    self.adapi.log(f"Could not parse last_changed: {e}", level="WARNING")
                    self.activate_now_playing()
            else:
                self.activate_now_playing()
        else:
            self.activate_now_playing()

    def on_midnight(self, kwargs):
        state = self.hass.get_state("sensor.now_playing_state")
        if state in IDLE_STATES or state == "paused":
            self.activate_saints_day(force_refresh=True)

    def on_state_change(self, entity, attribute, old, new, kwargs):
        # Cancel any pending debounce
        if self._mode_handle is not None:
            try:
                self.adapi.cancel_timer(self._mode_handle)
            except:
                pass
            self._mode_handle = None

        # Cancel any pending paused timeout
        if self._paused_handle is not None:
            try:
                self.adapi.cancel_timer(self._paused_handle)
                self._paused_handle = None
            except:
                pass

        if new == "playing":
            # Fire immediately on play
            self.activate_now_playing()
        elif new == "paused":
            # Start paused timeout
            self.adapi.log(f"Paused — will switch to saints_day in {PAUSED_TIMEOUT}s if still paused")
            self._paused_handle = self.adapi.run_in(self.on_paused_timeout, PAUSED_TIMEOUT)
        elif new in IDLE_STATES:
            # Debounce idle transitions
            if self._mode_handle is not None:
                self._mode_handle = self.adapi.run_in(self.do_mode_change, 2)
            else:
                self.do_mode_change({})

    def on_paused_timeout(self, kwargs):
        self._paused_handle = None
        state = self.hass.get_state("sensor.now_playing_state")
        if state == "paused":
            self.adapi.log("Still paused after timeout — switching to saints_day")
            self.activate_saints_day()

    def do_mode_change(self, kwargs):
        self._mode_handle = None
        state = self.hass.get_state("sensor.now_playing_state")
        self.adapi.log(f"Mode change — state is: {state}")
        if state in IDLE_STATES:
            self.activate_saints_day()
        else:
            self.activate_now_playing()

    def activate_now_playing(self):
        self.adapi.log("Activating now_playing mode")
        self.adapi.fire_event("display_mode", mode="now_playing")

    def activate_saints_day(self, force_refresh=False):
        self.adapi.log("Activating saints_day mode")
        self.adapi.fire_event("display_mode", mode="saints_day", force_refresh=force_refresh)
