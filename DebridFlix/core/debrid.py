"""Debrid / cloud-torrent services.

Every provider implements:
  configured()                      -> bool
  check_cached(hashes)              -> {hash: bool}  (only for hashes it can vouch for)
  add(magnet)                       -> starts a cloud download
  resolve(magnet, season, episode)  -> direct URL; raises NotReady when the torrent is
                                       not finished (it is left downloading in the cloud)
  account()                         -> short text for the "test connection" action
"""
import time

from . import http
from .models import hash_from_magnet, pick_file


class ProviderError(Exception):
    pass


class NotReady(ProviderError):
    """The torrent was accepted but is not downloaded yet."""


def _flatten_alldebrid(nodes, prefix=""):
    out = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        name = prefix + str(node.get("n") or node.get("filename") or "")
        if node.get("e"):
            out.extend(_flatten_alldebrid(node["e"], name + "/"))
        elif node.get("l") or node.get("link"):
            out.append({"name": name, "size": node.get("s") or node.get("size") or 0,
                        "link": node.get("l") or node.get("link")})
    return out


class Provider(object):
    key = ""
    name = ""
    short = ""

    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)

    def configured(self):
        return False

    def check_cached(self, hashes):
        return {}

    def _http(self, method, url, **kw):
        try:
            reply = http.request(method, url, **kw)
        except http.ApiError as err:
            detail = ""
            payload = err.payload
            if isinstance(payload, dict):
                detail = payload.get("error") or payload.get("detail") or payload.get("message") or ""
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code") or ""
            raise ProviderError("%s: %s" % (self.name, detail or err))
        self.log(self.key, method, url.split("?")[0], reply)
        return reply

    def _pick(self, files, season, episode):
        chosen = pick_file(files, season, episode)
        if not chosen:
            raise ProviderError("%s: no matching video file in this torrent" % self.name)
        return chosen


class Premiumize(Provider):
    key, name, short = "premiumize", "Premiumize", "PM"
    BASE = "https://www.premiumize.me/api"

    def configured(self):
        return bool(self.s.get("pm_key"))

    def _call(self, method, path, **fields):
        fields["apikey"] = self.s.get("pm_key")
        if method == "GET":
            reply = self._http("GET", self.BASE + path, params=fields)
        else:
            reply = self._http("POST", self.BASE + path, data=fields)
        if not isinstance(reply, dict) or reply.get("status") != "success":
            raise ProviderError("Premiumize: %s" % ((reply or {}).get("message") or "request failed"))
        return reply

    def check_cached(self, hashes):
        out = {}
        hashes = list(hashes)
        for start in range(0, len(hashes), 80):
            chunk = hashes[start:start + 80]
            reply = self._call("POST", "/cache/check", **{"items[]": chunk})
            for infohash, flag in zip(chunk, reply.get("response") or []):
                out[infohash] = bool(flag)
        return out

    def add(self, magnet):
        self._call("POST", "/transfer/create", src=magnet)
        return "Transfer created on Premiumize"

    def resolve(self, magnet, season=None, episode=None):
        try:
            reply = self._call("POST", "/transfer/directdl", src=magnet)
        except ProviderError:
            self.add(magnet)
            raise NotReady("Premiumize: not cached, transfer started")
        files = [{"name": c.get("path") or "", "size": c.get("size") or 0, "link": c.get("link") or c.get("stream_link")}
                 for c in reply.get("content") or []]
        return self._pick(files, season, episode)["link"]

    def account(self):
        reply = self._call("GET", "/account/info")
        until = reply.get("premium_until")
        return "customer %s, premium until %s" % (reply.get("customer_id"), time.strftime("%Y-%m-%d", time.gmtime(until)) if until else "n/a")


class RealDebrid(Provider):
    key, name, short = "realdebrid", "Real-Debrid", "RD"
    BASE = "https://api.real-debrid.com/rest/1.0"
    OAUTH = "https://api.real-debrid.com/oauth/v2"
    OPEN_CLIENT = "X245A4XAIBGVM"  # Real-Debrid's public client id for open-source apps

    def configured(self):
        return bool(self.s.get("rd_token"))

    # --- device linking -------------------------------------------------
    def auth_start(self):
        reply = self._http("GET", self.OAUTH + "/device/code", params={"client_id": self.OPEN_CLIENT, "new_credentials": "yes"})
        return {"url": reply.get("verification_url") or "https://real-debrid.com/device", "code": reply["user_code"],
                "interval": int(reply.get("interval") or 5), "expires": int(reply.get("expires_in") or 600),
                "device_code": reply["device_code"]}

    def auth_poll(self, state):
        try:
            cred = http.request("GET", self.OAUTH + "/device/credentials",
                                params={"client_id": self.OPEN_CLIENT, "code": state["device_code"]})
        except http.ApiError as err:
            if err.status in (400, 403):
                return False  # not approved yet
            raise ProviderError("Real-Debrid: %s" % err)
        if not cred or not cred.get("client_secret"):
            return False
        self.s.set("rd_client_id", cred["client_id"], save=False)
        self.s.set("rd_client_secret", cred["client_secret"], save=False)
        self._token_request(state["device_code"])
        return True

    def _token_request(self, code):
        reply = self._http("POST", self.OAUTH + "/token", data={
            "client_id": self.s.get("rd_client_id"), "client_secret": self.s.get("rd_client_secret"),
            "code": code, "grant_type": "http://oauth.net/grant_type/device/1.0"})
        self.s.update({"rd_token": reply["access_token"], "rd_refresh": reply.get("refresh_token") or "",
                       "rd_expires": int(time.time()) + int(reply.get("expires_in") or 0)})

    def _headers(self):
        if self.s.get("rd_refresh") and self.s.get("rd_expires") and time.time() > int(self.s.get("rd_expires")) - 120:
            self._token_request(self.s.get("rd_refresh"))
        return {"Authorization": "Bearer %s" % self.s.get("rd_token")}

    # --- torrents -------------------------------------------------------
    def _info(self, torrent_id):
        return self._http("GET", self.BASE + "/torrents/info/%s" % torrent_id, headers=self._headers()) or {}

    def _add_and_select(self, magnet, season, episode, select_all):
        added = self._http("POST", self.BASE + "/torrents/addMagnet", data={"magnet": magnet}, headers=self._headers())
        torrent_id = added["id"]
        info = self._info(torrent_id)
        chosen = None
        if info.get("status") == "magnet_conversion":
            time.sleep(2)
            info = self._info(torrent_id)
        if info.get("status") == "waiting_files_selection":
            files = [{"name": f.get("path") or "", "size": f.get("bytes") or 0, "id": f.get("id")} for f in info.get("files") or []]
            chosen = pick_file(files, season, episode)
            wanted = "all" if (select_all or not chosen) else str(chosen["id"])
            self._http("POST", self.BASE + "/torrents/selectFiles/%s" % torrent_id, data={"files": wanted}, headers=self._headers())
            info = self._info(torrent_id)
        return info, chosen

    def add(self, magnet):
        info, _ = self._add_and_select(magnet, None, None, True)
        return "Added to Real-Debrid (%s)" % (info.get("status") or "queued")

    def resolve(self, magnet, season=None, episode=None):
        info, chosen = self._add_and_select(magnet, season, episode, False)
        links = info.get("links") or []
        if info.get("status") != "downloaded" or not links:
            raise NotReady("Real-Debrid: not cached, download started (%s, %s%%)" % (info.get("status") or "queued", info.get("progress") or 0))
        link = links[0]
        selected = [f for f in info.get("files") or [] if f.get("selected")]
        if len(links) > 1 and len(links) == len(selected):
            files = [{"name": f.get("path") or "", "size": f.get("bytes") or 0, "link": l} for f, l in zip(selected, links)]
            link = self._pick(files, season, episode)["link"]
        reply = self._http("POST", self.BASE + "/unrestrict/link", data={"link": link}, headers=self._headers())
        return reply["download"]

    def account(self):
        reply = self._http("GET", self.BASE + "/user", headers=self._headers())
        return "%s (%s), expires %s" % (reply.get("username"), reply.get("type"), str(reply.get("expiration") or "")[:10])


class TorBox(Provider):
    key, name, short = "torbox", "TorBox", "TB"
    BASE = "https://api.torbox.app/v1/api"

    def configured(self):
        return bool(self.s.get("tb_key"))

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.s.get("tb_key")}

    def _data(self, reply):
        if not isinstance(reply, dict) or reply.get("success") is False:
            raise ProviderError("TorBox: %s" % ((reply or {}).get("detail") or "request failed"))
        return reply.get("data")

    def check_cached(self, hashes):
        out = {}
        hashes = list(hashes)
        for start in range(0, len(hashes), 40):
            chunk = hashes[start:start + 40]
            data = self._data(self._http("GET", self.BASE + "/torrents/checkcached", headers=self._headers(),
                                         params={"hash": ",".join(chunk), "format": "list"}))
            found = set()
            if isinstance(data, list):
                found = set(str(e.get("hash") or "").lower() for e in data if isinstance(e, dict))
            elif isinstance(data, dict):
                found = set(str(k).lower() for k in data.keys())
            for infohash in chunk:
                out[infohash] = infohash in found
        return out

    def _create(self, magnet):
        data = self._data(self._http("POST", self.BASE + "/torrents/createtorrent", data={"magnet": magnet}, headers=self._headers())) or {}
        return data.get("torrent_id") or data.get("id")

    def add(self, magnet):
        self._create(magnet)
        return "Added to TorBox"

    def resolve(self, magnet, season=None, episode=None):
        torrent_id = self._create(magnet)
        if not torrent_id:
            raise NotReady("TorBox: torrent queued")
        info = self._data(self._http("GET", self.BASE + "/torrents/mylist", headers=self._headers(),
                                     params={"id": torrent_id, "bypass_cache": "true"})) or {}
        if isinstance(info, list):
            info = info[0] if info else {}
        if not (info.get("download_finished") or info.get("download_present")) or not info.get("files"):
            raise NotReady("TorBox: not cached, download started (%d%%)" % int(float(info.get("progress") or 0) * 100))
        files = [{"name": f.get("name") or f.get("short_name") or "", "size": f.get("size") or 0, "id": f.get("id")} for f in info["files"]]
        chosen = self._pick(files, season, episode)
        url = self._data(self._http("GET", self.BASE + "/torrents/requestdl", headers=self._headers(),
                                    params={"token": self.s.get("tb_key"), "torrent_id": torrent_id, "file_id": chosen["id"]}))
        if not url:
            raise ProviderError("TorBox: no download link returned")
        return url

    def account(self):
        data = self._data(self._http("GET", self.BASE + "/user/me", headers=self._headers())) or {}
        return "%s, plan %s" % (data.get("email"), data.get("plan"))


class AllDebrid(Provider):
    key, name, short = "alldebrid", "AllDebrid", "AD"
    BASE = "https://api.alldebrid.com/v4"
    AGENT = "debridflix"

    def configured(self):
        return bool(self.s.get("ad_key"))

    def _call(self, method, path, auth=True, **fields):
        headers = {"Authorization": "Bearer %s" % self.s.get("ad_key")} if auth else {}
        if method == "GET":
            fields["agent"] = self.AGENT
            reply = self._http("GET", self.BASE + path, params=fields, headers=headers)
        else:
            reply = self._http("POST", self.BASE + path, params={"agent": self.AGENT}, data=fields, headers=headers)
        if not isinstance(reply, dict) or reply.get("status") != "success":
            error = (reply or {}).get("error") or {}
            raise ProviderError("AllDebrid: %s" % (error.get("message") or error.get("code") or "request failed"))
        return reply.get("data") or {}

    def auth_start(self):
        data = self._call("GET", "/pin/get", auth=False)
        return {"url": data.get("base_url") or "https://alldebrid.com/pin", "code": data["pin"],
                "interval": 5, "expires": int(data.get("expires_in") or 600), "check": data["check"]}

    def auth_poll(self, state):
        data = self._call("GET", "/pin/check", auth=False, check=state["check"], pin=state["code"])
        if data.get("activated") and data.get("apikey"):
            self.s.set("ad_key", data["apikey"])
            return True
        return False

    def _upload(self, magnet):
        data = self._call("POST", "/magnet/upload", **{"magnets[]": [magnet]})
        entry = (data.get("magnets") or [{}])[0]
        if entry.get("error"):
            raise ProviderError("AllDebrid: %s" % (entry["error"].get("message") or "magnet rejected"))
        return entry

    def add(self, magnet):
        self._upload(magnet)
        return "Added to AllDebrid"

    def resolve(self, magnet, season=None, episode=None):
        entry = self._upload(magnet)
        if not entry.get("ready"):
            raise NotReady("AllDebrid: not cached, download started")
        data = self._call("POST", "/magnet/files", **{"id[]": [entry["id"]]})
        node = (data.get("magnets") or [{}])[0]
        files = _flatten_alldebrid(node.get("files") or node.get("links"))
        chosen = self._pick(files, season, episode)
        return self._call("GET", "/link/unlock", link=chosen["link"])["link"]

    def account(self):
        user = self._call("GET", "/user").get("user") or {}
        return "%s, premium: %s" % (user.get("username"), user.get("isPremium"))


class DebridLink(Provider):
    key, name, short = "debridlink", "Debrid-Link", "DL"
    BASE = "https://debrid-link.com/api/v2"

    def configured(self):
        return bool(self.s.get("dl_key"))

    def _call(self, method, path, **kw):
        reply = self._http(method, self.BASE + path, headers={"Authorization": "Bearer %s" % self.s.get("dl_key")}, **kw)
        if not isinstance(reply, dict) or not reply.get("success"):
            raise ProviderError("Debrid-Link: %s" % ((reply or {}).get("error") or "request failed"))
        return reply.get("value")

    def _add(self, magnet):
        return self._call("POST", "/seedbox/add", json_body={"url": magnet, "async": True}) or {}

    def add(self, magnet):
        self._add(magnet)
        return "Added to Debrid-Link"

    def resolve(self, magnet, season=None, episode=None):
        torrent = self._add(magnet)
        files = [{"name": f.get("name") or "", "size": f.get("size") or 0, "link": f.get("downloadUrl"),
                  "done": float(f.get("downloadPercent") or 0) >= 100} for f in torrent.get("files") or []]
        if not files:
            raise NotReady("Debrid-Link: torrent queued")
        chosen = self._pick(files, season, episode)
        if not chosen["done"] or not chosen["link"]:
            raise NotReady("Debrid-Link: not cached, download started (%s%%)" % int(float(torrent.get("downloadPercent") or 0)))
        return chosen["link"]

    def account(self):
        value = self._call("GET", "/account/infos") or {}
        return "%s, premium days left: %s" % (value.get("pseudo") or value.get("username"), int((value.get("premiumLeft") or 0) / 86400))


ALL_PROVIDERS = [Premiumize, RealDebrid, TorBox, AllDebrid, DebridLink]


def providers(settings, log=None, only_configured=True):
    """Provider instances ordered by the user's priority list."""
    order = settings.list("provider_priority")
    instances = [cls(settings, log) for cls in ALL_PROVIDERS]
    instances.sort(key=lambda p: order.index(p.key) if p.key in order else len(order))
    if only_configured:
        instances = [p for p in instances if p.configured()]
    return instances


__all__ = ["providers", "ProviderError", "NotReady", "ALL_PROVIDERS", "hash_from_magnet"]
