"""Stream model, parsing helpers and the filter logic."""
import base64
import re
import urllib.parse

QUALITY_RANK = {"sd": 1, "hd720": 2, "hd1080": 3, "hd2k": 4, "hd4k": 5, "hd6k": 6, "hd8k": 7}
QUALITY_LABEL = {"sd": "SD", "hd720": "720p", "hd1080": "1080p", "hd2k": "2K", "hd4k": "4K",
                 "hd6k": "6K", "hd8k": "8K"}
RESOLUTION_CHOICES = ["any", "hd4k", "hd1080", "hd720", "sd"]
AUDIO_CHOICES = ["any", "2.0", "5.1", "7.1"]
AUDIO_MIN_CHANNELS = {"2.0": 2, "5.1": 6, "7.1": 8}
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".wmv", ".m2ts", ".webm", ".mpg")


def hash_from_magnet(magnet):
    if not magnet:
        return ""
    match = re.search(r"btih:([A-Za-z0-9]+)", magnet)
    if not match:
        return ""
    value = match.group(1)
    if len(value) == 40:
        return value.lower()
    if len(value) == 32:
        try:
            return base64.b32decode(value.upper()).hex()
        except (ValueError, TypeError):
            return ""
    return ""


def build_magnet(infohash, name=""):
    magnet = "magnet:?xt=urn:btih:" + infohash
    if name:
        magnet += "&dn=" + urllib.parse.quote(name)
    return magnet


def human_size(size):
    try:
        size = float(size or 0)
    except (TypeError, ValueError):
        return "?"
    if size <= 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return ("%.1f %s" if unit == "GB" else "%.0f %s") % (size, unit)
        size /= 1024.0


def channels_label(channels):
    return {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}.get(channels, "%sch" % channels if channels else "?")


class Stream(object):
    def __init__(self, **kw):
        self.id = kw.get("id", "")
        self.name = kw.get("name", "")
        self.hash = kw.get("hash", "")
        self.magnet = kw.get("magnet", "")
        self.size = kw.get("size", 0)
        self.seeds = kw.get("seeds", 0)
        self.quality = kw.get("quality", "")
        self.video_codec = kw.get("video_codec", "")
        self.channels = kw.get("channels", 0)
        self.audio_codec = kw.get("audio_codec", "")
        self.languages = kw.get("languages", [])
        self.source = kw.get("source", "")
        self.cached = kw.get("cached", {})  # provider key -> True / False / None (unknown)

    @property
    def quality_label(self):
        if self.quality in QUALITY_LABEL:
            return QUALITY_LABEL[self.quality]
        return (self.quality or "?").upper()

    @property
    def rank(self):
        return QUALITY_RANK.get(self.quality, 0)

    def cached_on(self, keys):
        return [k for k in keys if self.cached.get(k)]

    def maybe_on(self, keys):
        """Services whose cache state is unknown (no Orion data, no direct check): Play will try them."""
        return [k for k in keys if k in self.cached and self.cached[k] is None]


def parse_orion_stream(raw):
    """Turn one Orion stream object into a Stream. Returns None for non-torrent links."""
    if not isinstance(raw, dict):
        return None
    info = raw.get("file") or {}
    video = raw.get("video") or {}
    audio = raw.get("audio") or {}
    meta = raw.get("stream") or {}
    access = raw.get("access") or {}
    links = raw.get("links") or []
    if isinstance(links, str):
        links = [links]
    if raw.get("link"):
        links = list(links) + [raw["link"]]
    magnet = next((l for l in links if isinstance(l, str) and l.startswith("magnet:")), "")
    infohash = (info.get("hash") or hash_from_magnet(magnet) or "").lower()
    name = info.get("name") or ""
    if not magnet and infohash:
        magnet = build_magnet(infohash, name)
    if not magnet:
        return None
    cached = {}
    for key, value in access.items():
        if isinstance(value, bool):
            cached[key] = value
    languages = audio.get("languages") or []
    if isinstance(languages, str):
        languages = [languages]
    from .i18n import name_languages
    languages = [str(l).lower() for l in languages]
    languages += [l for l in name_languages(info.get("name") or "") if l not in languages]
    try:
        channels = int(audio.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0
    return Stream(id=raw.get("id", ""), name=name, hash=infohash, magnet=magnet,
                  size=info.get("size") or 0, seeds=meta.get("seeds") or 0,
                  quality=(video.get("quality") or "").lower(), video_codec=video.get("codec") or "",
                  channels=channels, audio_codec=audio.get("codec") or "",
                  languages=[str(l).lower() for l in languages], source=meta.get("source") or "",
                  cached=cached)


class StreamFilter(object):
    def __init__(self, cached_only=True, resolution="any", audio="any", language="any", audio_preference=None):
        self.cached_only = cached_only
        self.audio_preference = list(audio_preference or [])
        self.resolution = resolution
        self.audio = audio
        self.language = language

    def match(self, stream, provider_keys):
        if self.cached_only and not (stream.cached_on(provider_keys) or stream.maybe_on(provider_keys)):
            return False
        if self.resolution != "any" and stream.quality != self.resolution:
            return False
        if self.audio != "any" and stream.channels < AUDIO_MIN_CHANNELS.get(self.audio, 0):
            return False
        if self.language != "any" and self.language not in stream.languages:
            return False
        return True

    def apply(self, streams, provider_keys):
        result = [s for s in streams if self.match(s, provider_keys)]
        # cached anywhere first, then "maybe" (unknown cache state), then the rest; within a tier the preferred audio
        # language (e.g. English, then German), then best quality
        from .i18n import audio_score
        result.sort(key=lambda s: (2 if s.cached_on(provider_keys) else 1 if s.maybe_on(provider_keys) else 0,
                                   -audio_score(s.languages, self.audio_preference) if self.audio_preference else 0,
                                   s.rank, float(s.seeds or 0) > 0, float(s.size or 0)), reverse=True)
        return result


def pick_file(files, season=None, episode=None):
    """files: list of dicts with 'name' and 'size'. Returns the dict to play, or None."""
    videos = []
    for entry in files:
        name = str(entry.get("name") or "")
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base.endswith(VIDEO_EXT) and "sample" not in base:
            videos.append(entry)
    if not videos:
        return None

    def size(entry):
        try:
            return float(entry.get("size") or 0)
        except (TypeError, ValueError):
            return 0

    if season is not None and episode is not None:
        patterns = [re.compile(r"s0*%d[ ._-]?e0*%d(?!\d)" % (season, episode), re.I),
                    re.compile(r"(?<!\d)0*%dx0*%d(?!\d)" % (season, episode), re.I)]
        hits = [v for v in videos if any(p.search(str(v.get("name"))) for p in patterns)]
        if hits:
            return max(hits, key=size)
        if len(videos) > 1:
            return None
    return max(videos, key=size)
