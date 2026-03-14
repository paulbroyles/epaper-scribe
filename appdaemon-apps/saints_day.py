import adbase as ad
import requests
from PIL import Image
from io import BytesIO
from datetime import date

DEVICE_ID = "fd8f9a44064425f5f4a8c7ca5a63fd80"
SAINT_ARTWORK_PATH = "/config/www/saint_artwork.png"
SAINT_ARTWORK_URL = "http://homeassistant.local:5050/local/saint_artwork.png"
ICON_SIZE = 64

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
CALENDAR_API = "http://calapi.inadiutorium.cz/api/v0/en/calendars/default/today"

ORDINALS = {
    "1": "First", "2": "Second", "3": "Third", "4": "Fourth",
    "5": "Fifth", "6": "Sixth", "7": "Seventh", "8": "Eighth",
    "9": "Ninth", "10": "Tenth", "11": "Eleventh", "12": "Twelfth",
}

SEASON_DATA = {
    "Lent": {
        "icon": "mdi:cross",
        "description": "A season of fasting, prayer, and almsgiving in preparation for Easter."
    },
    "Advent": {
        "icon": "mdi:candle",
        "description": "A season of hopeful waiting and preparation for the coming of Christ."
    },
    "Christmas": {
        "icon": "mdi:star",
        "description": "A season celebrating the birth of Jesus Christ."
    },
    "Easter": {
        "icon": "mdi:cross-celtic",
        "description": "A season of joy celebrating the resurrection of Jesus Christ."
    },
    "Epiphany": {
        "icon": "mdi:star-three-points",
        "description": "A season celebrating the manifestation of Christ to the world."
    },
    "Ordinary": {
        "icon": "mdi:book-cross",
        "description": "Ordinary Time: the season of the Church's daily life and growth."
    },
}

class SaintsDay(ad.ADBase):

    def initialize(self):
        self.adapi = self.get_ad_api()
        self.hass = self.get_plugin_api("HASS")
        self._cached_date = None
        self._cached_data = None
        self._today_wiki_url = ""
        self.hass.listen_event(self.on_display_mode, "display_mode")
        self.adapi.log("SaintsDay app initialized")

    def on_display_mode(self, event_name, data, kwargs):
        if data.get("mode") != "saints_day":
            return
        force_refresh = data.get("force_refresh", False)
        self.do_update(force_refresh=force_refresh)

    def do_update(self, force_refresh=False):
        today = date.today()

        if not force_refresh and self._cached_date == today and self._cached_data:
            self.adapi.log("Using cached saint data")
            cached = self._cached_data
            if cached.get("has_saint"):
                self.update_saint_display(**{k: v for k, v in cached.items() if k != "has_saint"})
            else:
                self.update_season_display(today, cached["season"], cached["week"])
            return

        saint_title, rank, season, week = self.fetch_saint_anglican()

        if not saint_title:
            self.adapi.log("No saint found — showing season")
            self._cached_date = today
            self._cached_data = {"has_saint": False, "season": season, "week": week}
            self.update_season_display(today, season, week)
            return

        name, role = self.parse_saint_title(saint_title)
        description, image_url = self.fetch_wikipedia(name)
        self.fetch_and_dither_image(image_url)

        self._cached_date = today
        self._cached_data = {
            "has_saint": True,
            "name": name,
            "role": role,
            "rank": rank,
            "season": season,
            "week": week,
            "description": description
        }

        self.update_saint_display(name, role, rank, season, week, description)

    # --- Active source: Anglican pip package ---

    def fetch_saint_anglican(self):
        try:
            from liturgical_calendar.liturgical import liturgical_calendar
            from datetime import date as date_type
            day = liturgical_calendar(date_type.today())

            name = day.get("name", "")
            season = day.get("season", "")
            week = day.get("week", "")
            rank = day.get("type", "")
            wiki_url = day.get("url", "")

            self._today_wiki_url = wiki_url

            self.adapi.log(f"Anglican calendar: '{name}' ({rank}) — {week or season}")

            if not name:
                return None, None, season, week

            return name, rank, season, week

        except Exception as e:
            self.adapi.log(f"Anglican calendar failed: {e}", level="WARNING")
            return None, None, None, None

    # --- Inactive source: Catholic API (preserved for easy switching) ---

    def fetch_saint_catholic(self):
        """
        Fetches today's saint from the Roman Catholic Church Calendar API.
        Note: returns no saint on Lenten/Advent ferial days by design.
        To use instead of fetch_saint_anglican, replace the call in do_update()
        and update the return signature to match (name, rank, season, week).
        """
        try:
            response = requests.get(CALENDAR_API, timeout=5)
            response.raise_for_status()
            data = response.json()

            season = data.get("season", "").replace("_", " ").title()
            celebrations = data.get("celebrations", [])

            saints = [
                c for c in celebrations
                if c.get("title") and c.get("rank") != "ferial"
            ]

            if not saints:
                return None, None, season, ""

            best = min(saints, key=lambda c: c.get("rank_num", 99))
            title = best.get("title", "")
            rank = best.get("rank", "").replace("_", " ").title()

            self.adapi.log(f"Catholic calendar: {title} ({rank})")
            return title, rank, season, ""

        except Exception as e:
            self.adapi.log(f"Catholic calendar API failed: {e}", level="WARNING")
            return None, None, None, None

    # --- Shared logic ---

    def format_week(self, week):
        """Convert 'Lent 3' to 'Third Week of Lent' etc."""
        if not week:
            return week
        parts = week.strip().split()
        if len(parts) == 2:
            season_name, number = parts[0], parts[1]
            ordinal = ORDINALS.get(number, number)
            return f"{ordinal} Week of {season_name}"
        return week

    def parse_saint_title(self, title):
        name = title
        role = ""

        if "," in title:
            parts = title.split(",", 1)
            name = parts[0].strip()
            role = parts[1].strip()

        for prefix in ("Saint ", "Blessed ", "Venerable ", "Our Lady of "):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        return name, role

    def fetch_wikipedia(self, search_term):
        try:
            headers = {"User-Agent": "HomeAssistantDisplay/1.0"}

            wiki_url = getattr(self, "_today_wiki_url", "")
            if wiki_url and "/wiki/" in wiki_url:
                page_title = wiki_url.split("/wiki/")[-1]
                api_url = WIKIPEDIA_API + page_title
            else:
                api_url = WIKIPEDIA_API + requests.utils.quote(search_term)

            response = requests.get(api_url, timeout=5, headers=headers)

            if response.status_code == 404:
                api_url = WIKIPEDIA_API + requests.utils.quote("Saint " + search_term)
                response = requests.get(api_url, timeout=5, headers=headers)

            response.raise_for_status()
            data = response.json()

            extract = data.get("extract", "")
            sentences = extract.split(". ")
            description = sentences[0].strip()
            if description and not description.endswith("."):
                description += "."

            thumbnail = data.get("thumbnail", {})
            image_url = thumbnail.get("source", "")

            self.adapi.log(f"Wikipedia: {description[:50]}...")
            return description, image_url

        except Exception as e:
            self.adapi.log(f"Wikipedia fetch failed: {e}", level="WARNING")
            return "", ""

    def fetch_and_dither_image(self, image_url):
        def save_placeholder():
            img = Image.new("RGB", (ICON_SIZE, ICON_SIZE), (180, 160, 140))
            img.save(SAINT_ARTWORK_PATH)

        if not image_url:
            save_placeholder()
            return

        try:
            response = requests.get(image_url, timeout=5, headers={
                "User-Agent": "HomeAssistantDisplay/1.0"
            })
            response.raise_for_status()
            img = Image.open(BytesIO(response.content)).convert("RGB")
            img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)

            palette_img = Image.new("P", (1, 1))
            palette_img.putpalette(
                [255, 255, 255,
                   0,   0,   0,
                 255,   0,   0]
                + [0, 0, 0] * 253
            )

            dithered = img.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)
            dithered.convert("RGB").save(SAINT_ARTWORK_PATH)
            self.adapi.log("Saint image saved successfully")

        except Exception as e:
            self.adapi.log(f"Saint image fetch failed: {e}", level="WARNING")
            save_placeholder()

    def get_season_key(self, season):
        if not season:
            return "Ordinary"
        for key in SEASON_DATA:
            if key.lower() in season.lower():
                return key
        return "Ordinary"

    # --- Display methods ---

    def update_saint_display(self, name, role, rank, season, week, description):
        try:
            subtitle = role if role else rank or ""
            header = self.format_week(week) if week else season or ""

            self.hass.call_service(
                "open_epaper_link/drawcustom",
                target={"device_id": DEVICE_ID},
                background="white",
                rotate=0,
                dither=0,
                payload=[
                    {
                        "type": "dlimg",
                        "url": SAINT_ARTWORK_URL,
                        "x": 0,
                        "y": 28,
                        "xsize": ICON_SIZE,
                        "ysize": ICON_SIZE,
                        "resize_method": "cover"
                    },
                    {
                        "type": "line",
                        "x_start": ICON_SIZE,
                        "y_start": 28,
                        "x_end": ICON_SIZE,
                        "y_end": 128,
                        "fill": "black",
                        "width": 1
                    },
                    {
                        "type": "rectangle",
                        "x_start": 0,
                        "y_start": 0,
                        "x_end": 295,
                        "y_end": 28,
                        "fill": "red",
                        "outline": "red"
                    },
                    {
                        "type": "text",
                        "value": header,
                        "x": 6,
                        "y": 6,
                        "size": 13,
                        "font": "rbm.ttf",
                        "color": "white",
                        "max_width": 283,
                        "truncate": True
                    },
                    {
                        "type": "text",
                        "value": name or "",
                        "x": ICON_SIZE + 6,
                        "y": 32,
                        "size": 16,
                        "font": "ppb.ttf",
                        "color": "black",
                        "max_width": 224,
                        "truncate": True
                    },
                    {
                        "type": "text",
                        "value": subtitle,
                        "x": ICON_SIZE + 6,
                        "y": 54,
                        "size": 13,
                        "font": "rbm.ttf",
                        "color": "black",
                        "max_width": 224,
                        "truncate": True
                    },
                    {
                        "type": "line",
                        "x_start": ICON_SIZE + 6,
                        "y_start": 72,
                        "x_end": 290,
                        "y_end": 72,
                        "fill": "black",
                        "width": 1
                    },
                    {
                        "type": "text",
                        "value": description or "",
                        "x": ICON_SIZE + 6,
                        "y": 78,
                        "size": 11,
                        "font": "rbm.ttf",
                        "color": "black",
                        "max_width": 224,
                        "spacing": 2
                    }
                ]
            )
            self.adapi.log("Saint display updated successfully")

        except Exception as e:
            self.adapi.log(f"Saint display update failed: {e}", level="ERROR")

    def update_season_display(self, today, season, week):
        try:
            season_key = self.get_season_key(season)
            season_info = SEASON_DATA.get(season_key, SEASON_DATA["Ordinary"])
            icon = season_info["icon"]
            description = season_info["description"]
            header = self.format_week(week) if week else season or today.strftime("%B %-d")

            self.hass.call_service(
                "open_epaper_link/drawcustom",
                target={"device_id": DEVICE_ID},
                background="white",
                rotate=0,
                dither=0,
                payload=[
                    {
                        "type": "icon",
                        "value": icon,
                        "x": 0,
                        "y": 28,
                        "size": ICON_SIZE,
                        "fill": "black"
                    },
                    {
                        "type": "line",
                        "x_start": ICON_SIZE,
                        "y_start": 28,
                        "x_end": ICON_SIZE,
                        "y_end": 128,
                        "fill": "black",
                        "width": 1
                    },
                    {
                        "type": "rectangle",
                        "x_start": 0,
                        "y_start": 0,
                        "x_end": 295,
                        "y_end": 28,
                        "fill": "black",
                        "outline": "black"
                    },
                    {
                        "type": "text",
                        "value": header,
                        "x": 6,
                        "y": 6,
                        "size": 13,
                        "font": "rbm.ttf",
                        "color": "white",
                        "max_width": 283,
                        "truncate": True
                    },
                    {
                        "type": "text",
                        "value": description,
                        "x": ICON_SIZE + 6,
                        "y": 34,
                        "size": 14,
                        "font": "rbm.ttf",
                        "color": "black",
                        "max_width": 224,
                        "spacing": 3
                    },
                    {
                        "type": "text",
                        "value": today.strftime("%A, %B %-d"),
                        "x": ICON_SIZE + 6,
                        "y": 112,
                        "size": 11,
                        "font": "rbm.ttf",
                        "color": "black",
                        "max_width": 224,
                        "truncate": True
                    }
                ]
            )
            self.adapi.log(f"Season display updated: {header}")

        except Exception as e:
            self.adapi.log(f"Season display update failed: {e}", level="ERROR")
