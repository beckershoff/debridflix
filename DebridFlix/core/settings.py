"""Settings stored as JSON so they can also be edited over SSH/FTP."""
import json
import os

CONFIG_PATH = os.environ.get("DEBRIDFLIX_CONFIG", "/etc/enigma2/debridflix.json")

DEFAULTS = {
    # language: auto = follow the box's menu language (German or English)
    "ui_language": "auto",
    "audio_languages": "en,de",      # preferred audio, in order: sorts streams and picks the track in the player
    # metadata
    "tmdb_key": "",
    "tmdb_language": "auto",         # auto = German titles/descriptions when the interface is German
    # Orion
    "stream_source": "auto",  # auto = Orion when its keys are set, else Torrentio
    "orion_app_key": "",
    "orion_user_key": "",
    "orion_limit": "50",
    "orion_fresh_lookup": False,
    # debrid services
    "pm_key": "",
    "rd_token": "", "rd_refresh": "", "rd_client_id": "", "rd_client_secret": "", "rd_expires": 0,
    "tb_key": "",
    "ad_key": "",
    "dl_key": "",
    "provider_priority": "premiumize,realdebrid,torbox,alldebrid,debridlink",
    # Trakt
    "trakt_client_id": "", "trakt_client_secret": "",
    "trakt_access": "", "trakt_refresh": "", "trakt_expires": 0,
    # subtitles
    "os_api_key": "", "os_username": "", "os_password": "",
    "subtitle_languages": "de,en",   # first language that has subtitles wins
    "subtitle_auto": False,
    # filters (remembered between sessions)
    "filter_cached_only": True,
    # what this box + TV can play (core/device.py); auto = highest mode the TV reports over HDMI
    "hide_unplayable": True,
    "max_resolution": "auto",
    "max_bitrate": "15",  # Mbit/s, estimated from file size and runtime; ~17 measured over this box's Wi-Fi
    "filter_resolution": "any",
    "filter_audio": "any",
    "filter_language": "any",
    "language_choices": "any,en,nl,de,fr,es,it,tr,sv",
    # misc
    "player_type": "4097",
    "cache_dir": "/tmp/debridflix",
    "debug": False,
}

# (label, key, kind, choices) - drives the on-box setup screen.
SETUP_FIELDS = [
    ("Language / Sprache", "ui_language", "choice", ["auto", "en", "de"]),
    ("Preferred audio languages", "audio_languages", "text", None),
    ("TMDB API key (v3)", "tmdb_key", "text", None),
    ("Metadata language", "tmdb_language", "choice", ["auto", "en-US", "de-DE", "nl-NL", "fr-FR", "es-ES", "it-IT", "tr-TR", "sv-SE"]),
    ("Stream search (auto = Orion if keys set, else Torrentio)", "stream_source", "choice", ["auto", "orion", "torrentio"]),
    ("Orion app key", "orion_app_key", "text", None),
    ("Orion user key", "orion_user_key", "text", None),
    ("Results per search", "orion_limit", "choice", ["20", "50", "100", "200"]),
    ("Orion fresh cache lookup (uses quota)", "orion_fresh_lookup", "bool", None),
    ("Hide streams this box/TV cannot play well", "hide_unplayable", "bool", None),
    ("Max resolution (auto = what the TV accepts)", "max_resolution", "choice", ["auto", "hd4k", "hd1080", "hd720", "any"]),
    ("Max bitrate in Mbit/s (Wi-Fi: 15)", "max_bitrate", "choice", ["8", "15", "25", "40", "60", "any"]),
    ("Premiumize API key", "pm_key", "text", None),
    ("Real-Debrid API token (or link with yellow)", "rd_token", "text", None),
    ("TorBox API key", "tb_key", "text", None),
    ("AllDebrid API key (or link with yellow)", "ad_key", "text", None),
    ("Debrid-Link API key", "dl_key", "text", None),
    ("Service priority", "provider_priority", "text", None),
    ("Trakt client ID", "trakt_client_id", "text", None),
    ("Trakt client secret (older apps only, else empty)", "trakt_client_secret", "text", None),
    ("OpenSubtitles API key", "os_api_key", "text", None),
    ("OpenSubtitles username", "os_username", "text", None),
    ("OpenSubtitles password", "os_password", "text", None),
    ("Subtitle languages", "subtitle_languages", "text", None),
    ("Load best subtitle automatically", "subtitle_auto", "bool", None),
    ("Language filter choices", "language_choices", "text", None),
    ("Player", "player_type", "choice", ["4097", "5002", "5001"]),
    ("Cache folder", "cache_dir", "text", None),
    ("Debug log (/tmp/debridflix.log)", "debug", "bool", None),
]


# Values that used to be the default and were written to every settings file. On load they are
# dropped again so the current default applies (only values the user really chose are kept).
LEGACY_DEFAULTS = {"subtitle_languages": "nl,en", "tmdb_language": "en-US"}

# How choice values are shown (translated with _() where they are displayed)
CHOICE_LABELS = {"auto": "auto", "any": "any", "en": "English", "de": "Deutsch", "orion": "Orion", "torrentio": "Torrentio",
                 "hd4k": "4K", "hd1080": "1080p", "hd720": "720p"}


class Settings(object):
    def __init__(self, path=None):
        self.path = path or CONFIG_PATH
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                for key, old in LEGACY_DEFAULTS.items():
                    if stored.get(key) == old:
                        del stored[key]
                self.data.update(stored)
        except (IOError, OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            # only what differs from the defaults, so improved defaults reach existing installs
            json.dump(dict((k, v) for k, v in self.data.items() if k not in DEFAULTS or DEFAULTS[k] != v), fh, indent=2, sort_keys=True)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            self.save()

    def update(self, values):
        self.data.update(values)
        self.save()

    def list(self, key):
        return [x.strip() for x in str(self.get(key) or "").split(",") if x.strip()]
