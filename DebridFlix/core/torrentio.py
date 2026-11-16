"""Torrentio: keyless torrent search by IMDb id. Fallback while Orion keys are missing.

Only the infohash is used: it is handed to the user's debrid service, which fetches the torrent
on its own servers. The box itself never joins a swarm.
Reply: {"streams": [{"name": "Torrentio\\n4k HDR", "title": "<release>\\n<file>\\n👤 100 💾 6.91 GB ⚙️ YTS\\n🇬🇧 / 🇳🇱",
                     "infoHash": "...", "fileIdx": 0, "behaviorHints": {"filename": "..."}}]}
"""
import re

from . import http
from .i18n import _, name_languages
from .models import Stream, build_magnet

BASE = "https://torrentio.strem.fun"
# Torrentio sits behind Cloudflare, which rejects urllib's default agent
HEADERS = {"User-Agent": "Mozilla/5.0 (Enigma2; DebridFlix)"}

FLAGS = {"🇬🇧": "en", "🇺🇸": "en", "🇳🇱": "nl", "🇩🇪": "de", "🇫🇷": "fr", "🇪🇸": "es", "🇲🇽": "es", "🇮🇹": "it",
         "🇹🇷": "tr", "🇸🇪": "sv", "🇷🇺": "ru", "🇵🇹": "pt", "🇧🇷": "pt", "🇵🇱": "pl", "🇯🇵": "ja", "🇰🇷": "ko",
         "🇨🇳": "zh", "🇮🇳": "hi", "🇩🇰": "da", "🇳🇴": "no", "🇫🇮": "fi", "🇺🇦": "uk", "🇨🇿": "cs", "🇭🇺": "hu",
         "🇬🇷": "el", "🇷🇴": "ro", "🇸🇦": "ar"}
UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


class TorrentioError(Exception):
    pass


def _quality(text):
    t = text.lower()
    for marks, value in ((("2160", "4k", "uhd"), "hd4k"), (("1440", "2k"), "hd2k"), (("1080",), "hd1080"),
                         (("720",), "hd720"), (("480", "576", "sd", "dvd", "cam", "scr"), "sd")):
        if any(m in t for m in marks):
            return value
    return ""


def _channels(text):
    m = re.search(r"(?<![\d.])([257])[ .]([01])(?![\d.])", text)
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"(?<!\d)([2678])\s?ch\b", text, re.I)  # "6CH" = 5.1
    return int(m.group(1)) if m else 0


def _codec(text, options):
    t = text.lower()
    return next((label for marks, label in options if any(m in t for m in marks)), "")


def parse_torrentio_stream(raw):
    if not isinstance(raw, dict) or not raw.get("infoHash"):
        return None
    infohash = str(raw["infoHash"]).lower()
    lines = str(raw.get("title") or "").split("\n")
    hints = raw.get("behaviorHints") or {}
    name = hints.get("filename") or lines[0]
    info = " ".join(lines)
    seeds = re.search(r"👤\s*(\d+)", info)
    size = re.search(r"💾\s*([\d.]+)\s*([KMGT]?B)", info)
    source = re.search(r"⚙️\s*([^\n👤💾]+)", "\n".join(lines))
    languages = []
    for flag, code in FLAGS.items():
        if flag in info and code not in languages:
            languages.append(code)
    text = " ".join([str(raw.get("name") or ""), lines[0], name])
    languages += [l for l in name_languages(" ".join([lines[0], name])) if l not in languages]
    return Stream(id=infohash[:8], name=name, hash=infohash, magnet=build_magnet(infohash, name),
                  size=float(size.group(1)) * UNITS[size.group(2)] if size else 0,
                  seeds=int(seeds.group(1)) if seeds else 0, quality=_quality(text),
                  video_codec=_codec(text, ((("x265", "h265", "hevc"), "h265"), (("x264", "h264", "avc"), "h264"), (("av1",), "av1"))),
                  channels=_channels(text),
                  audio_codec=_codec(text, ((("atmos",), "atmos"), (("truehd",), "truehd"), (("dts",), "dts"),
                                            (("ddp", "eac3", "dd+"), "eac3"), (("ac3", "dd5"), "ac3"), (("aac",), "aac"))),
                  languages=languages, source=(source.group(1).strip() if source else "Torrentio"))


def balance(streams, limit):
    """Torrentio sorts 4K first; take results round-robin per resolution so 1080p/720p are not cut off."""
    groups = {}
    for s in streams:
        groups.setdefault(s.quality, []).append(s)
    out = []
    queues = list(groups.values())
    while queues and len(out) < limit:
        for q in list(queues):
            if q:
                out.append(q.pop(0))
            if not q:
                queues.remove(q)
            if len(out) >= limit:
                break
    return out


class Torrentio(object):
    name = "Torrentio"

    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)

    def streams(self, kind, imdb=None, season=None, episode=None, limit=None, keep=None):
        """keep: optional predicate applied before the per-resolution balancing (drop unplayable first)."""
        if not imdb:
            raise TorrentioError(_("No IMDb id for this title"))
        imdb = imdb if str(imdb).startswith("tt") else "tt%s" % imdb
        path = "/stream/movie/%s.json" % imdb if kind == "movie" else "/stream/series/%s:%s:%s.json" % (imdb, season or 1, episode or 1)
        try:
            reply = http.request("GET", BASE + path, headers=HEADERS, timeout=30)
        except http.ApiError as err:
            raise TorrentioError("Torrentio: %s" % err)
        self.log("torrentio", path, "%d streams" % len((reply or {}).get("streams") or []))
        out = [s for s in (parse_torrentio_stream(r) for r in (reply or {}).get("streams") or []) if s and (keep is None or keep(s))]
        return balance(out, int(limit or self.s.get("orion_limit") or 50))
