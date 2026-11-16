"""Orion (orionoid.com) client: stream search plus debrid cache lookup."""
from . import http
from .models import parse_orion_stream

API_URL = "https://api.orionoid.com"
LOOKUP_SERVICES = ("premiumize", "realdebrid", "torbox", "alldebrid", "debridlink", "offcloud")


class OrionError(Exception):
    pass


class Orion(object):
    name = "Orion"

    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)

    def configured(self):
        return bool(self.s.get("orion_app_key") and self.s.get("orion_user_key"))

    def _call(self, **params):
        if not self.configured():
            raise OrionError("Orion app key and user key are not set")
        body = {"keyapp": self.s.get("orion_app_key"), "keyuser": self.s.get("orion_user_key")}
        body.update(params)
        try:
            reply = http.request("POST", API_URL, data=body, timeout=40)
        except http.ApiError as err:
            raise OrionError("Orion: %s" % err)
        self.log("orion", params.get("mode"), params.get("action"), reply)
        if not isinstance(reply, dict):
            raise OrionError("Orion: unexpected reply")
        return reply

    @staticmethod
    def _ok(reply):
        result = reply.get("result") or {}
        return result.get("status") == "success", result

    def streams(self, kind, imdb=None, tmdb=None, season=None, episode=None, limit=None):
        """kind: 'movie' or 'show'. Returns a list of Stream objects (torrents only)."""
        params = {"mode": "stream", "action": "retrieve", "type": kind, "streamtype": "torrent",
                  "limitcount": int(limit or self.s.get("orion_limit") or 50)}
        if imdb:
            params["idimdb"] = str(imdb).replace("tt", "")
        elif tmdb:
            params["idtmdb"] = str(tmdb)
        else:
            raise OrionError("No IMDb or TMDB id for this title")
        if kind == "show":
            params["numberseason"] = season
            params["numberepisode"] = episode
        reply = self._call(**params)
        ok, result = self._ok(reply)
        data = reply.get("data") or {}
        if not ok:
            kind_of_error = str(result.get("type") or "")
            if "missing" in kind_of_error or "nostream" in kind_of_error or "notfound" in kind_of_error:
                return []
            raise OrionError("Orion: %s" % (result.get("message") or result.get("description") or "request failed"))
        out = []
        for raw in data.get("streams") or []:
            stream = parse_orion_stream(raw)
            if stream:
                out.append(stream)
        return out

    def lookup(self, hashes, services):
        """Ask Orion which hashes are cached. Returns {hash: {service: bool}}; empty when unknown."""
        services = [s for s in services if s in LOOKUP_SERVICES]
        if not hashes or not services:
            return {}
        reply = self._call(mode="debrid", action="lookup", type=",".join(services), **{"item[]": list(hashes)})
        ok, _ = self._ok(reply)
        if not ok:
            return {}
        data = reply.get("data")
        out = {}
        entries = []
        if isinstance(data, dict):
            # either {hash: {...}} or {"items"/"lookup": [...]}
            for key in ("items", "lookup", "streams"):
                if isinstance(data.get(key), list):
                    entries = data[key]
                    break
            else:
                entries = [dict(v, hash=k) for k, v in data.items() if isinstance(v, dict)]
        elif isinstance(data, list):
            entries = data
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            infohash = str(entry.get("hash") or entry.get("id") or entry.get("item") or "").lower()
            flags = entry.get("access") if isinstance(entry.get("access"), dict) else entry
            found = dict((s, flags[s]) for s in services if isinstance(flags.get(s), bool))
            if infohash and found:
                out[infohash] = found
        return out
