"""Trakt: device login, watchlist sync, watched history."""
import time

from . import http
from .i18n import _

BASE = "https://api.trakt.tv"


class TraktError(Exception):
    pass


class Trakt(object):
    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)
        self._ids = None  # {"movie": set(tmdb ids), "show": set(tmdb ids)}

    def has_app(self):
        # Trakt apps created since Oct 2026 get no client secret (PKCE-only); the device flow works with the ID alone
        return bool(self.s.get("trakt_client_id"))

    def _client(self, body):
        """Adds client_id, and client_secret only for older apps that still have one."""
        body["client_id"] = self.s.get("trakt_client_id")
        if self.s.get("trakt_client_secret"):
            body["client_secret"] = self.s.get("trakt_client_secret")
        return body

    def configured(self):
        return bool(self.has_app() and self.s.get("trakt_access"))

    def _headers(self, auth=True):
        headers = {"trakt-api-version": "2", "trakt-api-key": self.s.get("trakt_client_id"), "Content-Type": "application/json"}
        if auth:
            if self.s.get("trakt_refresh") and self.s.get("trakt_expires") and time.time() > int(self.s.get("trakt_expires")) - 86400:
                self._refresh()
            headers["Authorization"] = "Bearer %s" % self.s.get("trakt_access")
        return headers

    def _call(self, method, path, body=None, auth=True, params=None):
        try:
            reply = http.request(method, BASE + path, json_body=body, headers=self._headers(auth), params=params)
        except http.ApiError as err:
            raise TraktError("Trakt: %s" % err)
        self.log("trakt", method, path, reply)
        return reply

    def _store(self, reply):
        self.s.update({"trakt_access": reply["access_token"], "trakt_refresh": reply.get("refresh_token") or "",
                       "trakt_expires": int(reply.get("created_at") or time.time()) + int(reply.get("expires_in") or 0)})

    def _refresh(self):
        try:
            reply = http.request("POST", BASE + "/oauth/token", json_body=self._client({
                "refresh_token": self.s.get("trakt_refresh"), "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                "grant_type": "refresh_token"}))
            self._store(reply)
        except (http.ApiError, KeyError):
            pass

    # --- device linking -------------------------------------------------
    def auth_start(self):
        if not self.has_app():
            raise TraktError(_("Enter the Trakt client ID first"))
        reply = self._call("POST", "/oauth/device/code", {"client_id": self.s.get("trakt_client_id")}, auth=False)
        return {"url": reply.get("verification_url") or "https://trakt.tv/activate", "code": reply["user_code"],
                "interval": int(reply.get("interval") or 5), "expires": int(reply.get("expires_in") or 600),
                "device_code": reply["device_code"]}

    def auth_poll(self, state):
        try:
            reply = http.request("POST", BASE + "/oauth/device/token", headers=self._headers(False), json_body=self._client({
                "code": state["device_code"]}))
        except http.ApiError as err:
            if err.status in (400, 429):
                return False  # pending / slow down
            raise TraktError("Trakt: %s" % err)
        if not reply or not reply.get("access_token"):
            return False
        self._store(reply)
        return True

    # --- watchlist ------------------------------------------------------
    def watchlist(self, kind):
        """Returns [{'kind', 'tmdb', 'imdb', 'title', 'year'}] newest first."""
        path = "/sync/watchlist/%s" % ("movies" if kind == "movie" else "shows")
        out = []
        for entry in self._call("GET", path) or []:
            media = entry.get("movie") or entry.get("show") or {}
            ids = media.get("ids") or {}
            if ids.get("tmdb"):
                out.append({"kind": kind, "tmdb": ids["tmdb"], "imdb": ids.get("imdb") or "",
                            "title": media.get("title") or "?", "year": str(media.get("year") or "")})
        if self._ids is None:
            self._ids = {"movie": set(), "show": set()}
        self._ids[kind] = set(i["tmdb"] for i in out)
        return out

    def in_watchlist(self, item):
        if self._ids is None:
            self.watchlist("movie")
            self.watchlist("show")
        return item["tmdb"] in self._ids[item["kind"]]

    @staticmethod
    def _body(item, extra=None):
        entry = {"ids": {"tmdb": item["tmdb"]}}
        entry.update(extra or {})
        return {"movies" if item["kind"] == "movie" else "shows": [entry]}

    def set_watchlist(self, item, wanted):
        """Adds or removes the title on Trakt; returns the new state."""
        self._call("POST", "/sync/watchlist" if wanted else "/sync/watchlist/remove", self._body(item))
        if self._ids is not None:
            (self._ids[item["kind"]].add if wanted else self._ids[item["kind"]].discard)(item["tmdb"])
        return wanted

    def mark_watched(self, item, season=None, episode=None):
        extra = None
        if item["kind"] == "show":
            extra = {"seasons": [{"number": season, "episodes": [{"number": episode}]}]}
        self._call("POST", "/sync/history", self._body(item, extra))

    def account(self):
        user = (self._call("GET", "/users/settings") or {}).get("user") or {}
        return user.get("username") or "linked"
