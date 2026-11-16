"""TMDB catalogue: rows, search, details, seasons."""
from . import http

BASE = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p/"


class TmdbError(Exception):
    pass


def normalize(raw, kind=None):
    """kind: 'movie' or 'show'."""
    media = raw.get("media_type")
    if not kind:
        kind = "show" if media == "tv" else "movie" if media == "movie" else None
    if kind not in ("movie", "show") or not raw.get("id"):
        return None
    date = raw.get("release_date") or raw.get("first_air_date") or ""
    return {"kind": kind, "tmdb": raw["id"], "imdb": raw.get("imdb_id") or "",
            "title": raw.get("title") or raw.get("name") or "?", "year": date[:4],
            "overview": raw.get("overview") or "", "rating": raw.get("vote_average") or 0,
            "poster": raw.get("poster_path") or "", "backdrop": raw.get("backdrop_path") or ""}


class Tmdb(object):
    def __init__(self, settings, cache=None):
        self.s = settings
        self.cache = cache

    def configured(self):
        return bool(self.s.get("tmdb_key"))

    def _get(self, path, ttl=6 * 3600, **params):
        if not self.configured():
            raise TmdbError("TMDB API key is not set")
        params["language"] = self.s.get("tmdb_language")
        key = "tmdb:%s:%s" % (path, sorted(params.items()))
        if self.cache:
            hit = self.cache.get(key, ttl)
            if hit is not None:
                return hit
        params["api_key"] = self.s.get("tmdb_key")
        try:
            reply = http.request("GET", BASE + path, params=params)
        except http.ApiError as err:
            raise TmdbError("TMDB: %s" % err)
        if self.cache and reply is not None:
            self.cache.set(key, reply)
        return reply or {}

    @staticmethod
    def _path(kind):
        return "movie" if kind == "movie" else "tv"

    def _list(self, reply, kind=None):
        return [i for i in (normalize(r, kind) for r in reply.get("results") or []) if i]

    def trending(self, kind):
        return self._list(self._get("/trending/%s/week" % self._path(kind)), kind)

    def popular(self, kind):
        return self._list(self._get("/%s/popular" % self._path(kind)), kind)

    def top_rated(self, kind):
        return self._list(self._get("/%s/top_rated" % self._path(kind)), kind)

    def genres(self, kind):
        return [(g["id"], g["name"]) for g in self._get("/genre/%s/list" % self._path(kind), ttl=7 * 86400).get("genres") or []]

    def discover(self, kind, genre_id):
        return self._list(self._get("/discover/%s" % self._path(kind), with_genres=genre_id, sort_by="popularity.desc"), kind)

    def search(self, query):
        return self._list(self._get("/search/multi", ttl=3600, query=query, include_adult="false"))

    def details(self, kind, tmdb_id):
        """Returns (item, seasons). seasons is a list of (number, name, episode_count) for shows."""
        raw = self._get("/%s/%s" % (self._path(kind), tmdb_id), ttl=86400, append_to_response="external_ids")
        item = normalize(raw, kind) or {"kind": kind, "tmdb": tmdb_id, "title": "?", "year": "", "overview": "",
                                        "rating": 0, "poster": "", "backdrop": "", "imdb": ""}
        item["imdb"] = raw.get("imdb_id") or (raw.get("external_ids") or {}).get("imdb_id") or ""
        item["genres"] = [g.get("name") for g in raw.get("genres") or []]
        item["runtime"] = raw.get("runtime") or (raw.get("episode_run_time") or [0])[0]
        seasons = [(s.get("season_number"), s.get("name") or "Season %s" % s.get("season_number"), s.get("episode_count") or 0)
                   for s in raw.get("seasons") or [] if s.get("season_number")]
        return item, seasons

    def season(self, tmdb_id, number):
        raw = self._get("/tv/%s/season/%s" % (tmdb_id, number), ttl=86400)
        return [(e.get("episode_number"), e.get("name") or "", e.get("overview") or "", e.get("air_date") or "")
                for e in raw.get("episodes") or []]

    def by_id(self, kind, tmdb_id):
        return self.details(kind, tmdb_id)[0]

    @staticmethod
    def image_url(path, size="w154"):
        return IMAGE + size + path if path else ""
