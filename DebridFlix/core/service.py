"""Facade used by the UI: catalogue rows, stream search, playback resolving, cloud downloads."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import http
from .cache import DiskCache
from .debrid import NotReady, ProviderError, providers
from .device import DeviceLimits, detect
from .models import StreamFilter
from .orion import Orion
from .torrentio import Torrentio
from .settings import Settings
from .subtitles import OpenSubtitles
from .tmdb import Tmdb
from .trakt import Trakt
from . import i18n
from .i18n import _

LOG_PATH = "/tmp/debridflix.log"


class NotCached(Exception):
    pass


class App(object):
    def __init__(self, settings=None):
        self.s = settings or Settings()
        self.cache = DiskCache(os.path.join(self.s.get("cache_dir"), "data"))
        self.tmdb = Tmdb(self.s, self.cache)
        self.orion = Orion(self.s, self.log)
        self.torrentio = Torrentio(self.s, self.log)
        self.trakt = Trakt(self.s, self.log)
        self.subs = OpenSubtitles(self.s, self.log)
        self.browse_cached_only = False
        self._detected = None
        self.last_hidden = {}  # reason -> count, from the last find_streams()

    # --- helpers --------------------------------------------------------
    def log(self, *parts):
        if not self.s.get("debug"):
            return
        try:
            with open(LOG_PATH, "a") as fh:
                fh.write("%s %s\n" % (time.strftime("%H:%M:%S"), " | ".join(
                    p if isinstance(p, str) else json.dumps(p, default=str)[:4000] for p in parts)))
        except (IOError, OSError):
            pass

    def providers(self):
        return providers(self.s, self.log)

    def provider_keys(self):
        return [p.key for p in self.providers()]

    def provider(self, key):
        for p in providers(self.s, self.log, only_configured=False):
            if p.key == key:
                return p
        raise ProviderError(_("Unknown service %s") % key)

    def missing_setup(self):
        missing = []
        if not self.tmdb.configured():
            missing.append(_("TMDB API key"))
        if self.s.get("stream_source") == "orion" and not self.orion.configured():
            missing.append(_("Orion app + user key (or set Stream search to auto)"))
        if not self.providers():
            missing.append(_("at least one debrid service"))
        return missing

    def apply_language(self, system_locale=""):
        """Interface language from the setting; 'auto' follows Enigma2's menu language (e.g. 'de_DE')."""
        i18n.set_language(i18n.resolve(self.s.get("ui_language"), system_locale))
        return i18n.language()

    def device_limits(self):
        if self._detected is None:
            self._detected = detect()
        return DeviceLimits.from_settings(self.s, self._detected)

    def stream_filter(self):
        return StreamFilter(bool(self.s.get("filter_cached_only")), self.s.get("filter_resolution"),
                            self.s.get("filter_audio"), self.s.get("filter_language"), self.s.list("audio_languages"))

    # --- catalogue ------------------------------------------------------
    def rows(self):
        """Row definitions: [(title, loader)]. Loaders run in a worker thread."""
        t = self.tmdb
        rows = []
        if self.trakt.configured():
            rows.append((_("My watchlist - Movies"), lambda: self.watchlist_items("movie")))
            rows.append((_("My watchlist - Series"), lambda: self.watchlist_items("show")))
        rows += [
            (_("Trending movies"), lambda: t.trending("movie")),
            (_("Trending series"), lambda: t.trending("show")),
            (_("Popular movies"), lambda: t.popular("movie")),
            (_("Popular series"), lambda: t.popular("show")),
            (_("Top rated movies"), lambda: t.top_rated("movie")),
            (_("Top rated series"), lambda: t.top_rated("show")),
        ]
        return rows

    def genre_rows(self):
        rows = []
        for kind, label in (("movie", _("Movies - %s")), ("show", _("Series - %s"))):
            for genre_id, name in self.tmdb.genres(kind):
                rows.append((label % name, (lambda k=kind, g=genre_id: self.tmdb.discover(k, g))))
        return rows

    def watchlist_items(self, kind):
        entries = self.trakt.watchlist(kind)[:40]

        def enrich(entry):
            try:
                item = self.tmdb.by_id(kind, entry["tmdb"])
                item["imdb"] = item.get("imdb") or entry.get("imdb") or ""
                return item
            except Exception:
                return dict(entry, overview="", rating=0, poster="", backdrop="")

        with ThreadPoolExecutor(max_workers=6) as pool:
            return list(pool.map(enrich, entries))

    def load_row(self, loader):
        items = loader()
        if self.browse_cached_only:
            items = items[:18]
            with ThreadPoolExecutor(max_workers=6) as pool:
                flags = list(pool.map(self.title_cached, items))
            items = [i for i, flag in zip(items, flags) if flag]
        return items

    def title_cached(self, item):
        """True when at least one cached stream exists (movie, or S01E01 for a series). Cached 12 h."""
        key = "cached:%s:%s:%s" % (item["kind"], item["tmdb"], ",".join(self.provider_keys()))
        hit = self.cache.get(key, 12 * 3600)
        if hit is not None:
            return bool(hit)
        try:
            season, episode = (1, 1) if item["kind"] == "show" else (None, None)
            streams = self.find_streams(item, season, episode, limit=20)
            keys = self.provider_keys()
            flag = any(s.cached_on(keys) for s in streams)
        except Exception:
            return False
        self.cache.set(key, flag)
        return flag

    def full_item(self, item):
        """Adds IMDb id, genres and seasons. Returns (item, seasons)."""
        full, seasons = self.tmdb.details(item["kind"], item["tmdb"])
        return full, seasons

    # --- streams --------------------------------------------------------
    def find_streams(self, item, season=None, episode=None, limit=None):
        provs = self.providers()
        keys = [p.key for p in provs]
        imdb = item.get("imdb")
        if not imdb:
            imdb = self.tmdb.details(item["kind"], item["tmdb"])[0].get("imdb")
            item["imdb"] = imdb
        source = self.stream_source()
        limits = self.device_limits()
        hidden = {}

        def playable(stream):
            ok, reason = limits.allows(stream, item.get("runtime"), item["kind"] != "movie")
            if not ok:
                hidden[reason] = hidden.get(reason, 0) + 1
            return ok

        if source is self.orion:
            streams = self.orion.streams(item["kind"], imdb=imdb, tmdb=None if imdb else item["tmdb"],
                                         season=season, episode=episode, limit=limit)
            streams = [s for s in streams if playable(s)]
        else:
            streams = self.torrentio.streams(item["kind"], imdb=imdb, season=season, episode=episode, limit=limit, keep=playable)
        self.last_hidden = hidden
        hashes = [s.hash for s in streams if s.hash]
        if source is self.orion and self.s.get("orion_fresh_lookup") and hashes:
            try:
                fresh = self.orion.lookup(hashes, keys)
            except Exception as err:
                fresh = {}
                self.log("orionlookup", str(err))
            for stream in streams:
                stream.cached.update(fresh.get(stream.hash, {}))
        for provider in provs:
            try:
                known = provider.check_cached(hashes)
            except ProviderError as err:
                self.log("cachecheck", provider.key, str(err))
                continue
            for stream in streams:
                if stream.hash in known:
                    stream.cached[provider.key] = known[stream.hash]
        for stream in streams:  # no answer from Orion or the service: None = unknown, Play will try it
            for key in keys:
                stream.cached.setdefault(key, None)
        return streams

    def stream_source(self):
        """Orion when chosen or (auto) when its keys are set, else the keyless Torrentio search."""
        choice = self.s.get("stream_source") or "auto"
        if choice == "orion" or (choice == "auto" and self.orion.configured()):
            return self.orion
        return self.torrentio

    def play(self, stream, season=None, episode=None, provider_key=None):
        """Returns (url, provider). Raises NotCached when no configured service has it."""
        if provider_key:
            order = [self.provider(provider_key)]
        else:
            order = [p for p in self.providers() if stream.cached.get(p.key)]
            order += [p for p in self.providers() if p.key in stream.cached and stream.cached[p.key] is None]
        if not order:
            raise NotCached(_("Not cached on any of your services"))
        last = None
        for provider in order:
            try:
                url = provider.resolve(stream.magnet, season, episode)
                # only ever play the service's own HTTPS download: never a magnet / P2P, always encrypted
                if not str(url or "").lower().startswith("https://"):
                    raise ProviderError(_("%s returned a non-HTTPS link; refusing to play it") % provider.name)
                return url, provider
            except NotReady as err:
                stream.cached[provider.key] = False
                last = err
            except ProviderError as err:
                last = err
        raise last

    def send(self, stream, provider_key):
        """Starts a cloud download on the chosen service."""
        return self.provider(provider_key).add(stream.magnet)

    # --- subtitles / posters -------------------------------------------
    def subtitle_path(self):
        return os.path.join(self.s.get("cache_dir"), "subs", "current.srt")

    def poster_file(self, path, size="w154"):
        """Local file for a TMDB poster path; downloads when missing. Returns '' on failure."""
        if not path:
            return ""
        folder = os.path.join(self.s.get("cache_dir"), "posters", size)
        dest = os.path.join(folder, path.strip("/").replace("/", "_"))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            return dest
        try:
            content = http.request("GET", self.tmdb.image_url(path, size), raw=True, timeout=15)
            os.makedirs(folder, exist_ok=True)
            tmp = dest + ".part%d" % (int(time.time() * 1000) % 100000)
            with open(tmp, "wb") as fh:
                fh.write(content)
            os.replace(tmp, dest)
            return dest
        except (http.ApiError, IOError, OSError):
            return ""

    def poster_cached(self, path, size="w154"):
        if not path:
            return ""
        dest = os.path.join(self.s.get("cache_dir"), "posters", size, path.strip("/").replace("/", "_"))
        return dest if os.path.exists(dest) and os.path.getsize(dest) > 0 else ""

    def test_connections(self):
        lines = []
        for provider in providers(self.s, self.log, only_configured=False):
            if not provider.configured():
                lines.append(_("%s: not set") % provider.name)
                continue
            try:
                lines.append(_("%s: OK - %s") % (provider.name, provider.account()))
            except Exception as err:
                lines.append("%s" % err if str(err).startswith(provider.name) else "%s: %s" % (provider.name, err))
        if self.trakt.configured():
            try:
                lines.append(_("Trakt: OK - %s") % self.trakt.account())
            except Exception as err:
                lines.append(str(err))
        else:
            lines.append(_("Trakt: not linked"))
        lines.append(_("TMDB: %s") % (_("key set") if self.tmdb.configured() else _("not set")))
        lines.append(_("Orion: %s") % (_("keys set") if self.orion.configured() else _("not set")))
        return "\n".join(lines)
