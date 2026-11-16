"""Settings stored as JSON so they can also be edited over SSH/FTP."""
import json
import os

CONFIG_PATH = os.environ.get("DEBRIDFLIX_CONFIG", "/etc/enigma2/debridflix.json")

DEFAULTS = {
    # metadata
    "tmdb_key": "",
    "tmdb_language": "en-US",
    # Orion
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
    "subtitle_languages": "nl,en",
    "subtitle_auto": False,
    # filters (remembered between sessions)
    "filter_cached_only": True,
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
    ("TMDB API key (v3)", "tmdb_key", "text", None),
    ("Metadata language", "tmdb_language", "choice", ["en-US", "nl-NL", "de-DE", "fr-FR", "es-ES", "it-IT", "tr-TR", "sv-SE"]),
    ("Orion app key", "orion_app_key", "text", None),
    ("Orion user key", "orion_user_key", "text", None),
    ("Orion results per search", "orion_limit", "choice", ["20", "50", "100", "200"]),
    ("Orion fresh cache lookup (uses quota)", "orion_fresh_lookup", "bool", None),
    ("Premiumize API key", "pm_key", "text", None),
    ("Real-Debrid API token (or link with yellow)", "rd_token", "text", None),
    ("TorBox API key", "tb_key", "text", None),
    ("AllDebrid API key (or link with yellow)", "ad_key", "text", None),
    ("Debrid-Link API key", "dl_key", "text", None),
    ("Service priority", "provider_priority", "text", None),
    ("Trakt client ID", "trakt_client_id", "text", None),
    ("Trakt client secret", "trakt_client_secret", "text", None),
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
                self.data.update(stored)
        except (IOError, OSError, ValueError):
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
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
