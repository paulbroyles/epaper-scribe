"""Constants for E-Paper Scribe."""

DOMAIN = "epaper_scribe"

CONF_PROVIDER_TYPE = "provider_type"
CONF_MEDIA_PLAYER_ENTITY = "media_player_entity"
CONF_PALETTE = "palette"
CONF_DEFAULT_SIZE = "default_size"
CONF_CALENDAR_TYPE = "calendar_type"
CONF_API_KEY = "api_key"

PALETTE_BW = "bw"
PALETTE_BWR = "bwr"
PALETTE_BWRY = "bwry"

PALETTES: dict[str, list[int]] = {
    PALETTE_BW: [255, 255, 255, 0, 0, 0],
    PALETTE_BWR: [255, 255, 255, 0, 0, 0, 255, 0, 0],
    PALETTE_BWRY: [255, 255, 255, 0, 0, 0, 255, 0, 0, 255, 255, 0],
}

PROVIDER_NOW_PLAYING = "now_playing"
PROVIDER_SAINTS_DAY = "saints_day"
PROVIDER_WORD_OF_DAY = "word_of_day"

WWW_PATH = "/config/www/epaper_scribe"
