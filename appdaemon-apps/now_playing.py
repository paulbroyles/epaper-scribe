import adbase as ad
from pillow_heif import register_heif_opener
register_heif_opener()
import requests
from PIL import Image
from io import BytesIO

DEVICE_ID = "fd8f9a44064425f5f4a8c7ca5a63fd80"
ARTWORK_PATH = "/config/www/now_playing_artwork.png"
ARTWORK_URL = "http://homeassistant.local:5050/local/now_playing_artwork.png"
ARTWORK_SIZE = 128
HA_BASE = "http://homeassistant.local:8123"
HA_TOKEN = "YOUR_LONG_LIVED_ACCESS_TOKEN"  # Replace with your token

class NowPlaying(ad.ADBase):

    def initialize(self):
        self.adapi = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS")
        self.hass.listen_event(self.on_display_mode, "display_mode")
        self.adapi.log("NowPlaying app initialized")

    def on_display_mode(self, event_name, data, kwargs):
        if data.get("mode") != "now_playing":
            return
        self.do_update()

    def do_update(self):
        state = self.hass.get_state("sensor.now_playing_state")
        if state in ("unavailable", "unknown", "off", "idle", ""):
            self.adapi.log(f"Skipping now_playing update — state is {state}")
            return

        creator        = self.hass.get_state("sensor.now_playing_creator")
        title          = self.hass.get_state("sensor.now_playing_title")
        container      = self.hass.get_state("sensor.now_playing_container")
        entity_picture = self.hass.get_state(
            "media_player.kitchen_apple_tv",  # Replace with your media player entity
            attribute="entity_picture"
        )

        self.adapi.log(f"Now playing: {creator} — {title} ({container})")

        if entity_picture:
            artwork_url = HA_BASE + entity_picture
            self.generate_artwork(artwork_url)
        else:
            self.save_placeholder()

        self.update_display(creator, title, container)

    def save_placeholder(self):
        img = Image.new("RGB", (ARTWORK_SIZE, ARTWORK_SIZE), (128, 128, 128))
        img.save(ARTWORK_PATH)

    def generate_artwork(self, artwork_url):
        try:
            artwork_url = artwork_url.replace("{w}", "256")
            artwork_url = artwork_url.replace("{h}", "256")
            artwork_url = artwork_url.replace("{c}", "")
            artwork_url = artwork_url.replace("{f}", "jpg")

            self.adapi.log(f"Fetching artwork: {artwork_url}")

            headers = {"Authorization": f"Bearer {HA_TOKEN}"}
            response = requests.get(artwork_url, timeout=5, headers=headers)
            response.raise_for_status()
            art = Image.open(BytesIO(response.content)).convert("RGB")
            art = art.resize((ARTWORK_SIZE, ARTWORK_SIZE), Image.LANCZOS)

            palette_img = Image.new("P", (1, 1))
            palette_img.putpalette(
                [255, 255, 255,
                   0,   0,   0,
                 255,   0,   0]
                + [0, 0, 0] * 253
            )

            art_dithered = art.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)
            art_dithered.convert("RGB").save(ARTWORK_PATH)
            self.adapi.log("Artwork saved successfully")

        except Exception as e:
            self.adapi.log(f"Artwork fetch failed: {e}", level="WARNING")
            self.save_placeholder()

    def update_display(self, creator, title, container):
        try:
            self.hass.call_service(
                "open_epaper_link/drawcustom",
                target={"device_id": DEVICE_ID},
                background="white",
                rotate=0,
                dither=0,
                payload=[
                    {
                        "type": "dlimg",
                        "url": ARTWORK_URL,
                        "x": 0,
                        "y": 0,
                        "xsize": 128,
                        "ysize": 128,
                        "resize_method": "stretch"
                    },
                    {
                        "type": "line",
                        "x_start": 128,
                        "y_start": 0,
                        "x_end": 128,
                        "y_end": 128,
                        "fill": "black",
                        "width": 1
                    },
                    {
                        "type": "rectangle",
                        "x_start": 129,
                        "y_start": 0,
                        "x_end": 295,
                        "y_end": 38,
                        "fill": "red",
                        "outline": "red"
                    },
                    {
                        "type": "text",
                        "value": creator or "",
                        "x": 135,
                        "y": 11,
                        "size": 16,
                        "font": "ppb.ttf",
                        "color": "white",
                        "max_width": 153,
                        "truncate": True
                    },
                    {
                        "type": "text",
                        "value": title or "",
                        "x": 135,
                        "y": 46,
                        "size": 18,
                        "font": "ppb.ttf",
                        "color": "black",
                        "max_width": 153,
                        "spacing": 2
                    },
                    {
                        "type": "text",
                        "value": container or "",
                        "x": 135,
                        "y": 90,
                        "size": 13,
                        "font": "rbm.ttf",
                        "color": "black",
                        "max_width": 153,
                        "spacing": 2
                    }
                ]
            )
            self.adapi.log("Display update sent successfully")

        except Exception as e:
            self.adapi.log(f"Display update failed: {e}", level="ERROR")
