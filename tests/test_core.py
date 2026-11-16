import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from DebridFlix.core import http, models, subtitles
from DebridFlix.core.settings import Settings
from DebridFlix.core.service import App, NotCached
from DebridFlix.core.debrid import NotReady, ProviderError

H1 = "a" * 40; H2 = "b" * 40; H3 = "c" * 40

def orion_stream(h, quality, channels, langs, access, name, size=5e9):
    return {"id": h[:6], "links": ["magnet:?xt=urn:btih:" + h], "file": {"hash": h, "name": name, "size": size},
            "video": {"quality": quality, "codec": "h265"}, "audio": {"channels": channels, "languages": langs, "codec": "eac3"},
            "stream": {"type": "torrent", "seeds": 10, "source": "x"}, "access": access}

class Fake(object):
    def __init__(self): self.calls = []; self.routes = []
    def on(self, method, fragment, reply): self.routes.append((method, fragment, reply))
    def __call__(self, method, url, params=None, data=None, json_body=None, headers=None, timeout=25, raw=False):
        self.calls.append((method, url, params, data, json_body, headers))
        for m, frag, reply in self.routes:
            if m == method and frag in url:
                r = reply(url, params, data, json_body) if callable(reply) else reply
                if isinstance(r, Exception): raise r
                return r
        raise AssertionError("unexpected %s %s" % (method, url))

class CoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s = Settings(os.path.join(self.tmp, "cfg.json"))
        self.s.update({"cache_dir": self.tmp, "tmdb_key": "t", "orion_app_key": "a", "orion_user_key": "u",
                       "hide_unplayable": False})  # device limits have their own tests
        self.fake = Fake(); self._orig = http.request; http.request = self.fake
        self.app = App(self.s)
        self.item = {"kind": "movie", "tmdb": 1, "imdb": "tt0063350", "title": "X"}
    def tearDown(self): http.request = self._orig

    def orion(self):
        self.fake.on("POST", "api.orionoid.com", {"result": {"status": "success"}, "data": {"streams": [
            orion_stream(H1, "hd1080", 6, ["en", "nl"], {"premiumize": False, "realdebrid": True}, "Movie.1080p.mkv"),
            orion_stream(H2, "hd4k", 8, ["en"], {"premiumize": False, "realdebrid": False}, "Movie.2160p.mkv", 2e10),
            orion_stream(H3, "hd720", 2, ["de"], {}, "Movie.720p.mkv", 1e9),
            {"id": "h", "links": ["https://hoster/x"], "file": {"name": "hoster"}}]}})

    def test_magnet_helpers(self):
        self.assertEqual(models.hash_from_magnet("magnet:?xt=urn:btih:" + H1.upper() + "&dn=x"), H1)
        import base64
        b32 = base64.b32encode(bytes.fromhex(H2)).decode()
        self.assertEqual(models.hash_from_magnet("magnet:?xt=urn:btih:" + b32), H2)

    def test_pick_file(self):
        files = [{"name": "Show.S01E01.mkv", "size": 5}, {"name": "Show.S01E02.mkv", "size": 6}, {"name": "Show.S01E12.mkv", "size": 9},
                 {"name": "sample.mkv", "size": 99}, {"name": "x.nfo", "size": 1}]
        self.assertEqual(models.pick_file(files, 1, 2)["name"], "Show.S01E02.mkv")
        self.assertEqual(models.pick_file(files, 1, 1)["name"], "Show.S01E01.mkv")
        self.assertIsNone(models.pick_file(files, 2, 1))
        self.assertEqual(models.pick_file(files)["name"], "Show.S01E12.mkv")
        self.assertEqual(models.pick_file([{"name": "a/1x03 title.mp4", "size": 1}, {"name": "a/1x04.mp4", "size": 2}], 1, 3)["name"], "a/1x03 title.mp4")

    def test_find_streams_merges_cache_and_filters(self):
        self.s.update({"pm_key": "p", "rd_token": "r", "tb_key": "t"})
        self.orion()
        self.fake.on("POST", "/cache/check", lambda u, p, d, j: {"status": "success", "response": [h == H2 for h in d["items[]"]]})
        self.fake.on("GET", "/torrents/checkcached", {"success": True, "data": [{"hash": H3}]})
        streams = self.app.find_streams(self.item)
        self.assertEqual(len(streams), 3)
        by = dict((s.hash, s) for s in streams)
        self.assertEqual(by[H1].cached_on(self.app.provider_keys()), ["realdebrid"])
        self.assertEqual(by[H2].cached_on(self.app.provider_keys()), ["premiumize"])
        self.assertEqual(by[H3].cached_on(self.app.provider_keys()), ["torbox"])
        body = self.fake.calls[0][3]
        self.assertEqual(body["idimdb"], "0063350"); self.assertEqual(body["type"], "movie")
        keys = self.app.provider_keys()
        f = models.StreamFilter(True, "any", "any", "any")
        self.assertEqual([s.hash for s in f.apply(streams, keys)], [H2, H1, H3])
        self.assertEqual([s.hash for s in models.StreamFilter(True, "hd1080", "any", "any").apply(streams, keys)], [H1])
        self.assertEqual([s.hash for s in models.StreamFilter(True, "any", "5.1", "any").apply(streams, keys)], [H2, H1])
        self.assertEqual([s.hash for s in models.StreamFilter(True, "any", "any", "nl").apply(streams, keys)], [H1])
        self.assertEqual([s.hash for s in models.StreamFilter(True, "any", "any", "any").apply(streams, ["torbox"])], [H3])
        self.assertEqual(len(models.StreamFilter(False, "any", "any", "any").apply(streams, [])), 3)

    def test_orion_no_streams(self):
        self.s.update({"pm_key": "p"})
        self.fake.on("POST", "api.orionoid.com", {"result": {"status": "error", "type": "streammissing", "message": "none"}})
        self.assertEqual(self.app.find_streams(self.item), [])

    def test_play_premiumize_and_not_cached(self):
        self.s.update({"pm_key": "p"})
        s = models.Stream(hash=H1, magnet="magnet:?xt=urn:btih:" + H1, cached={"premiumize": True})
        self.fake.on("POST", "/transfer/directdl", {"status": "success", "content": [
            {"path": "M/sample.mkv", "size": 1, "link": "https://x/s"}, {"path": "M/movie.mkv", "size": 100, "link": "https://x/m"}]})
        url, prov = self.app.play(s)
        self.assertEqual((url, prov.key), ("https://x/m", "premiumize"))
        with self.assertRaises(NotCached):
            self.app.play(models.Stream(hash=H2, magnet="m", cached={"premiumize": False}))

    def test_realdebrid_resolve_and_notready(self):
        self.s.update({"rd_token": "r"})
        state = {"status": "waiting_files_selection"}
        self.fake.on("POST", "/torrents/addMagnet", {"id": "T1"})
        def info(u, p, d, j):
            return {"status": state["status"], "progress": 3, "files": [{"id": 1, "path": "/S01E01.mkv", "bytes": 5, "selected": 0},
                    {"id": 2, "path": "/S01E02.mkv", "bytes": 5, "selected": 1}], "links": ["https://rd/l"] if state["status"] == "downloaded" else []}
        self.fake.on("GET", "/torrents/info/T1", info)
        def select(u, p, d, j):
            self.assertEqual(d["files"], "2"); state["status"] = state["next"]; return None
        self.fake.on("POST", "/torrents/selectFiles/T1", select)
        self.fake.on("POST", "/unrestrict/link", {"download": "https://dl/file.mkv"})
        state["next"] = "downloaded"
        s = models.Stream(hash=H1, magnet="magnet:?xt=urn:btih:" + H1, cached={"realdebrid": True})
        self.assertEqual(self.app.play(s, 1, 2)[0], "https://dl/file.mkv")
        state.update(status="waiting_files_selection", next="queued")
        with self.assertRaises(NotReady):
            self.app.play(s, 1, 2)
        self.assertFalse(s.cached["realdebrid"])

    def test_torbox_alldebrid_debridlink(self):
        self.s.update({"tb_key": "t", "ad_key": "a", "dl_key": "d"})
        self.fake.on("POST", "/torrents/createtorrent", {"success": True, "data": {"torrent_id": 7}})
        self.fake.on("GET", "/torrents/mylist", {"success": True, "data": {"download_finished": True, "files": [{"id": 3, "name": "m.mkv", "size": 9}]}})
        self.fake.on("GET", "/torrents/requestdl", lambda u, p, d, j: {"success": True, "data": "https://tb/%s/%s" % (p["torrent_id"], p["file_id"])})
        self.fake.on("POST", "/magnet/upload", {"status": "success", "data": {"magnets": [{"id": 5, "ready": True}]}})
        self.fake.on("POST", "/magnet/files", {"status": "success", "data": {"magnets": [{"id": "5", "files": [
            {"n": "Pack", "e": [{"n": "a.S02E03.mkv", "s": 4, "l": "https://ad/a"}, {"n": "a.S02E04.mkv", "s": 4, "l": "https://ad/b"}]}]}]}})
        self.fake.on("GET", "/link/unlock", lambda u, p, d, j: {"status": "success", "data": {"link": p["link"] + "/unlocked"}})
        self.fake.on("POST", "/seedbox/add", {"success": True, "value": {"id": "x", "downloadPercent": 100, "files": [
            {"name": "m.mkv", "size": 5, "downloadUrl": "https://dl/m", "downloadPercent": 100}]}})
        s = models.Stream(hash=H1, magnet="magnet:?xt=urn:btih:" + H1)
        self.assertEqual(self.app.play(s, provider_key="torbox")[0], "https://tb/7/3")
        self.assertEqual(self.app.play(s, 2, 4, provider_key="alldebrid")[0], "https://ad/b/unlocked")
        self.assertEqual(self.app.play(s, provider_key="debridlink")[0], "https://dl/m")
        self.assertIn("TorBox", self.app.send(s, "torbox"))

    def test_provider_priority(self):
        self.s.update({"pm_key": "p", "rd_token": "r", "tb_key": "t", "provider_priority": "torbox,realdebrid"})
        self.assertEqual(self.app.provider_keys(), ["torbox", "realdebrid", "premiumize"])

    def test_trakt_watchlist(self):
        self.s.update({"trakt_client_id": "c", "trakt_client_secret": "s", "trakt_access": "tok"})
        self.fake.on("GET", "/sync/watchlist/movies", [{"movie": {"title": "A", "year": 2020, "ids": {"tmdb": 11, "imdb": "tt1"}}}])
        self.fake.on("GET", "/sync/watchlist/shows", [])
        self.fake.on("POST", "/sync/watchlist/remove", {})
        self.fake.on("POST", "/sync/watchlist", {})
        self.fake.on("POST", "/sync/history", {})
        t = self.app.trakt
        self.assertTrue(t.in_watchlist({"kind": "movie", "tmdb": 11}))
        show = {"kind": "show", "tmdb": 22}
        self.assertFalse(t.in_watchlist(show))
        t.set_watchlist(show, True); self.assertTrue(t.in_watchlist(show))
        self.assertEqual(self.fake.calls[-1][4], {"shows": [{"ids": {"tmdb": 22}}]})
        t.set_watchlist(show, False); self.assertFalse(t.in_watchlist(show))
        t.mark_watched(show, 2, 5)
        self.assertEqual(self.fake.calls[-1][4]["shows"][0]["seasons"], [{"number": 2, "episodes": [{"number": 5}]}])
        self.assertEqual(self.fake.calls[-1][5]["Authorization"], "Bearer tok")

    def test_trakt_link_without_secret(self):
        # Trakt apps created since Oct 2026 have only a client ID (PKCE); device login must not need a secret
        self.s.update({"trakt_client_id": "c"})
        t = self.app.trakt
        self.assertTrue(t.has_app())
        self.fake.on("POST", "/oauth/device/code", {"device_code": "dev", "user_code": "ABCD1234",
                                                     "verification_url": "https://trakt.tv/activate", "interval": 5, "expires_in": 600})
        self.fake.on("POST", "/oauth/device/token", {"access_token": "acc", "refresh_token": "ref", "created_at": 1, "expires_in": 10})
        self.fake.on("POST", "/oauth/token", {"access_token": "acc2", "refresh_token": "ref2", "created_at": 9e9, "expires_in": 10})
        state = t.auth_start()
        self.assertEqual(state["code"], "ABCD1234")
        self.assertTrue(t.auth_poll(state))
        self.assertEqual(self.fake.calls[-1][4], {"code": "dev", "client_id": "c"})
        self.assertTrue(t.configured())
        t._headers()  # token expired -> refresh, still without a secret
        self.assertEqual(self.fake.calls[-1][4], {"refresh_token": "ref", "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
                                                  "grant_type": "refresh_token", "client_id": "c"})
        self.assertEqual(self.s.get("trakt_access"), "acc2")

    def test_torrentio_fallback_maybe_and_https_only(self):
        # no Orion keys -> auto uses Torrentio; RD has no cache check -> "maybe", and Play tries it
        self.s.update({"orion_app_key": "", "orion_user_key": "", "rd_token": "r"})
        self.assertEqual(self.app.missing_setup(), [])
        self.assertIs(self.app.stream_source(), self.app.torrentio)
        self.fake.on("GET", "torrentio.strem.fun/stream/movie/tt0063350.json", {"streams": [
            {"name": "Torrentio\n4k HDR", "title": "Movie 1994 2160p BluRay x265 DDP5.1\n\U0001f464 100 \U0001f4be 6.91 GB \u2699\ufe0f YTS\n\U0001f1ec\U0001f1e7 / \U0001f1f3\U0001f1f1",
             "infoHash": H1.upper(), "fileIdx": 0, "behaviorHints": {"filename": "Movie.2160p.mkv"}},
            {"name": "Torrentio\n1080p", "title": "Movie.1994.1080p.WEB.h264\n\U0001f464 0 \U0001f4be 900 MB \u2699\ufe0f 1337x",
             "infoHash": H2, "fileIdx": 1},
            {"name": "Torrentio\nhoster", "title": "no hash"}]})
        streams = self.app.find_streams(self.item)
        self.assertEqual([s.hash for s in streams], [H1, H2])
        a, b = streams
        self.assertEqual((a.quality, a.seeds, a.size, a.source, a.languages, a.video_codec, a.channels, a.audio_codec),
                         ("hd4k", 100, 6.91e9, "YTS", ["en", "nl"], "h265", 6, "eac3"))
        self.assertEqual((b.quality, b.size, b.video_codec), ("hd1080", 9e8, "h264"))
        self.assertTrue(a.magnet.startswith("magnet:?xt=urn:btih:" + H1))
        keys = self.app.provider_keys()
        self.assertEqual(a.maybe_on(keys), ["realdebrid"])
        self.assertEqual(len(models.StreamFilter(True, "any", "any", "any").apply(streams, keys)), 2)  # cached-only keeps "maybe"
        # Play: RD resolves to an https link -> played; a plain http link would be refused
        from unittest import mock
        from DebridFlix.core.debrid import RealDebrid
        with mock.patch.object(RealDebrid, "resolve", lambda self, magnet, s=None, e=None: "https://rd/file.mkv"):
            url, prov = self.app.play(a)
            self.assertEqual((url, prov.key), ("https://rd/file.mkv", "realdebrid"))
        for bad in ("http://rd/file.mkv", a.magnet):
            with mock.patch.object(RealDebrid, "resolve", lambda self, magnet, s=None, e=None, bad=bad: bad):
                with self.assertRaises(ProviderError):
                    self.app.play(a)

    def test_torrentio_balance_and_series_path(self):
        from DebridFlix.core import torrentio
        mk = lambda q, i: models.Stream(hash="%040d" % i, quality=q)
        out = torrentio.balance([mk("hd4k", i) for i in range(5)] + [mk("hd1080", 10 + i) for i in range(3)] + [mk("hd720", 20)], 4)
        self.assertEqual([s.quality for s in out], ["hd4k", "hd1080", "hd720", "hd4k"])
        self.fake.on("GET", "torrentio.strem.fun", {"streams": []})
        self.assertEqual(torrentio.Torrentio(self.s).streams("show", "tt0903747", 1, 2), [])
        self.assertIn("/stream/series/tt0903747:1:2.json", self.fake.calls[-1][1])
        self.s.set("stream_source", "orion")
        self.s.update({"orion_app_key": "", "orion_user_key": ""})
        self.assertTrue(any("Orion" in m for m in self.app.missing_setup()))

    def test_device_detect_from_proc(self):
        # the user's box: sf8008 (Hi3798MV200) can output 2160p, the Full HD TV reports up to 1080p
        from DebridFlix.core import device
        files = {device.PREFERRED: "1080p 1080p50 720p 720p50 1080i 1080i50 480p 576p 1080p24 1080p25 1080p30 480i 576i",
                 device.CHOICES: "pal ntsc 480i 480p 576i 576p 720p50 720p 1080i50 1080i 1080p50 1080p 2160p25 2160p50 2160p",
                 device.CHIPSET: "3798mv200"}
        from unittest import mock
        with mock.patch.object(device, "_read", lambda p: files.get(p, "")):
            d = device.detect()
        self.assertEqual(d, {"max_quality": "hd1080", "av1": False, "dv": False, "chipset": "3798mv200"})
        files[device.PREFERRED] = "2160p 1080p"
        with mock.patch.object(device, "_read", lambda p: files.get(p, "")):
            self.assertEqual(device.detect()["max_quality"], "hd4k")
        self.assertEqual(device.detect()["max_quality"], "")  # off-box: unknown = no limit

    def test_device_limits_hide_unplayable(self):
        from DebridFlix.core.device import DeviceLimits
        self.s.update({"hide_unplayable": True, "max_resolution": "auto", "max_bitrate": "15"})
        box = {"max_quality": "hd1080", "av1": False, "dv": False}
        lim = DeviceLimits.from_settings(self.s, box)
        S = lambda name, q="hd1080", size=4e9, codec="": models.Stream(name=name, quality=q, size=size, video_codec=codec)
        self.assertEqual(lim.allows(S("Movie.1080p.WEB-DL.x264.mkv"), 120), (True, ""))
        self.assertEqual(lim.allows(S("Movie.2160p.WEB.mkv", "hd4k"), 120), (False, "resolution"))
        self.assertEqual(lim.allows(S("Movie.1080p.AV1.mkv", codec="av1"), 120), (False, "AV1"))
        self.assertEqual(lim.allows(S("Movie.1080p.DV.mkv"), 120), (False, "Dolby Vision"))
        self.assertEqual(lim.allows(S("Movie.1080p.DV.HDR10.mkv"), 120), (True, ""))  # hybrid: HDR10 fallback
        self.assertEqual(lim.allows(S("Movie.1080p.DVDRip.mkv"), 120), (True, ""))  # "DVD" is not Dolby Vision
        self.assertEqual(lim.allows(S("Movie.1080p.Remux.mkv", size=3e10), 120), (False, "bitrate"))  # ~33 Mbit/s
        self.assertEqual(lim.allows(S("Show.S01E02.1080p.mkv", size=2e9), 45, True), (True, ""))   # ~6 Mbit/s
        self.assertEqual(lim.allows(S("Show.S01.1080p.Pack", size=5e10), 45, True), (True, ""))  # pack: size not per episode
        self.s.update({"max_resolution": "hd4k", "max_bitrate": "any"})
        self.assertEqual(DeviceLimits.from_settings(self.s, box).allows(S("x.2160p", "hd4k", 6e10), 120), (True, ""))
        self.s.set("hide_unplayable", False)
        self.assertEqual(DeviceLimits.from_settings(self.s, box).allows(S("x.AV1", "hd8k", 1e12, "av1")), (True, ""))

    def test_find_streams_drops_unplayable_before_balancing(self):
        self.s.update({"orion_app_key": "", "orion_user_key": "", "rd_token": "r",
                       "hide_unplayable": True, "max_resolution": "hd1080", "max_bitrate": "15"})
        self.app._detected = {"max_quality": "hd1080", "av1": False, "dv": False}
        raw = lambda h, title: {"name": "Torrentio", "title": title, "infoHash": h}
        self.fake.on("GET", "torrentio.strem.fun", {"streams": [
            raw(H1, "Movie.2160p.Remux\n\U0001f4be 60 GB"), raw(H2, "Movie.1080p.BluRay.x264\n\U0001f4be 9 GB"),
            raw(H3, "Movie.1080p.AV1\n\U0001f4be 2 GB"), raw("d" * 40, "Movie.720p.WEB\n\U0001f4be 1.5 GB")]})
        item = dict(self.item, runtime=120)
        streams = self.app.find_streams(item)
        self.assertEqual([s.hash for s in streams], [H2, "d" * 40])
        self.assertEqual(self.app.last_hidden, {"resolution": 1, "AV1": 1})

    def test_german_translation_complete(self):
        # every _("...") literal, setup label, choice label and hint has a German text with the same placeholders
        import ast, glob, re
        from DebridFlix.core.i18n_de import DE
        from DebridFlix.core.settings import SETUP_FIELDS, CHOICE_LABELS
        from DebridFlix.core.pairing import HELP
        root = os.path.join(os.path.dirname(__file__), "..", "DebridFlix")
        wanted = set()
        for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
            for n in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" and n.args:
                    if isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                        wanted.add(n.args[0].value)
        wanted |= set(f[0] for f in SETUP_FIELDS) | set(CHOICE_LABELS.values())
        wanted |= set(h for h in HELP.values() if not re.match(r"^[a-z.-]+\.(org|com|me|app)\b", h))
        wanted |= {"resolution", "AV1", "Dolby Vision", "bitrate"}
        self.assertEqual(sorted(w for w in wanted if w not in DE), [])
        spec = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdif%]")
        for en, de in DE.items():
            self.assertEqual(spec.findall(en), spec.findall(de), en)
        self.assertEqual(sorted(k for k in DE if k not in wanted), [])  # no stale entries

    def test_language_switch_and_helpers(self):
        from DebridFlix.core import i18n
        self.assertEqual(i18n.resolve("auto", "de_DE"), "de")
        self.assertEqual(i18n.resolve("auto", "nl_NL"), "en")
        self.assertEqual(i18n.resolve("en", "de_DE"), "en")
        self.s.set("ui_language", "auto")
        try:
            self.assertEqual(self.app.apply_language("de_DE"), "de")
            self.assertEqual(i18n._("Trending movies"), "Filme im Trend")
            self.assertEqual(i18n.tmdb_locale("auto"), "de-DE")
            self.assertEqual(i18n.tmdb_locale("en-US"), "en-US")
            self.assertEqual(self.app.rows()[0][0], "Filme im Trend")
            self.fake.on("GET", "themoviedb.org", {"results": []})
            self.app.tmdb.trending("movie")
            self.assertEqual(self.fake.calls[-1][2]["language"], "de-DE")
        finally:
            i18n.set_language("en")
        self.assertEqual(i18n._("Trending movies"), "Trending movies")

    def test_audio_languages_and_tracks(self):
        from DebridFlix.core.i18n import name_languages, audio_score, pick_track, lang_code
        self.assertEqual(name_languages("Movie.2020.German.DL.1080p.BluRay.x264"), ["de", "en"])
        self.assertEqual(name_languages("Movie.2020.GERMAN.1080p.WEB"), ["de"])
        self.assertEqual(name_languages("Movie.2020.1080p.WEB-DL.DDP5.1"), [])  # "WEB-DL" is not dual language
        self.assertEqual(name_languages("Movie 2020 ENG 1080p"), ["en"])
        self.assertEqual([lang_code(x) for x in ("eng", "ger", "deu", "English", "Deutsch", "en-US", "und")], ["en", "de", "de", "en", "de", "en", ""])
        self.assertEqual(audio_score([], ["en", "de"]), 0)        # untagged = English
        self.assertEqual(audio_score(["de"], ["en", "de"]), 1)
        self.assertEqual(audio_score(["fr"], ["en", "de"]), 2)
        self.assertEqual(pick_track(["deu", "eng"], ["en", "de"]), 1)
        self.assertEqual(pick_track(["ger", "fra"], ["en", "de"]), 0)
        self.assertIsNone(pick_track(["fra", "ita"], ["en", "de"]))
        # sorting: same tier -> English before German before others, even at lower quality
        mk = lambda h, q, langs: models.Stream(hash=h, quality=q, languages=langs, cached={"realdebrid": True})
        streams = [mk("g", "hd1080", ["de"]), mk("e", "hd720", []), mk("f", "hd1080", ["fr"]), mk("d", "hd720", ["de", "en"])]
        order = models.StreamFilter(True, "any", "any", "any", ["en", "de"]).apply(streams, ["realdebrid"])
        self.assertEqual([s.hash for s in order], ["e", "d", "g", "f"])  # e/d both have English (tie keeps order), then German

    def test_settings_save_only_changes_and_drop_legacy_defaults(self):
        import json as _json
        from DebridFlix.core.settings import Settings, DEFAULTS
        path = os.path.join(self.tmp, "legacy.json")
        with open(path, "w") as fh:  # what older versions wrote: every value, incl. the old defaults
            _json.dump(dict(DEFAULTS, subtitle_languages="nl,en", tmdb_language="en-US", tmdb_key="k"), fh)
        st = Settings(path)
        self.assertEqual(st.get("subtitle_languages"), "de,en")
        self.assertEqual(st.get("tmdb_language"), "auto")
        st.set("audio_languages", "de,en")
        stored = _json.load(open(path))
        self.assertEqual(stored, {"tmdb_key": "k", "audio_languages": "de,en"})

    def test_tmdb_and_cached_browse(self):
        self.s.update({"pm_key": "p"})
        self.fake.on("GET", "/trending/movie/week", {"results": [{"id": 1, "title": "One", "release_date": "2020-01-01", "poster_path": "/a.jpg"},
                                                                 {"id": 2, "title": "Two"}]})
        self.fake.on("GET", "/movie/1", {"id": 1, "title": "One", "imdb_id": "tt1"})
        self.fake.on("GET", "/movie/2", {"id": 2, "title": "Two", "imdb_id": "tt2"})
        self.fake.on("POST", "api.orionoid.com", lambda u, p, d, j: {"result": {"status": "success"}, "data": {"streams": [
            orion_stream(H1 if d["idimdb"] == "1" else H2, "hd1080", 2, [], {}, "x.mkv")]}})
        self.fake.on("POST", "/cache/check", lambda u, p, d, j: {"status": "success", "response": [h == H1 for h in d["items[]"]]})
        loader = self.app.rows()[0][1]
        self.assertEqual([i["title"] for i in self.app.load_row(loader)], ["One", "Two"])
        self.app.browse_cached_only = True
        self.assertEqual([i["title"] for i in self.app.load_row(loader)], ["One"])
        n = len(self.fake.calls)
        self.app.load_row(loader)  # second time served from disk cache
        self.assertEqual(len(self.fake.calls), n)

    def test_srt(self):
        text = "1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Hello</i>\r\nworld\r\n\r\n2\r\n00:00:05,000 --> 00:00:06,000\r\n{\\an8}Bye\r\n"
        track = subtitles.SubtitleTrack(subtitles.parse_srt(text))
        self.assertEqual(track.text_at(1500), "Hello\nworld"); self.assertEqual(track.text_at(3000), ""); self.assertEqual(track.text_at(5500), "Bye")
        track.delay_ms = 1000; self.assertEqual(track.text_at(6500), "Bye")
        self.assertEqual(subtitles.decode("caf\xe9".encode("cp1252")), "caf\xe9")

    def test_opensubtitles(self):
        self.s.update({"os_api_key": "k", "subtitle_languages": "nl,en"})
        self.fake.on("GET", "/subtitles", {"data": [
            {"attributes": {"language": "en", "release": "R1", "download_count": 50, "files": [{"file_id": 1}]}},
            {"attributes": {"language": "nl", "release": "R2", "download_count": 5, "files": [{"file_id": 2}]}}]})
        self.fake.on("POST", "/download", {"link": "https://os/file.srt"})
        self.fake.on("GET", "https://os/file.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHoi\n")
        res = self.app.subs.search("tt0063350", 1, 2)
        self.assertEqual([r["file_id"] for r in res], [2, 1])
        self.assertEqual(self.fake.calls[0][2]["parent_imdb_id"], "63350")
        path = self.app.subs.download(res[0], self.app.subtitle_path())
        self.assertEqual(subtitles.SubtitleTrack.from_file(path).text_at(1500), "Hoi")
        self.assertFalse(any("strem.io" in c[1] for c in self.fake.calls))  # API had the first language: no backup call

    def test_subtitle_backup_without_key(self):
        # no OpenSubtitles key: the keyless Stremio add-on, German before English, other languages dropped
        self.s.update({"os_api_key": "", "subtitle_languages": "de,en"})
        self.fake.on("GET", "opensubtitles-v3.strem.io/subtitles/series/tt0903747:1:2.json", {"subtitles": [
            {"url": "https://subs5.strem.io/en/download/a", "lang": "eng", "subtitleFileName": "BB.S01E02.en.srt"},
            {"url": "https://subs5.strem.io/en/download/b", "lang": "spa"},
            {"url": "https://subs5.strem.io/en/download/c", "lang": "ger", "subtitleFileName": "BB.S01E02.de.srt"}]})
        self.fake.on("GET", "subs5.strem.io/en/download/c", "1\r\n00:00:05,590 --> 00:00:07,799\r\nBisher bei \"Breaking Bad\".\r\n".encode("utf-8"))
        self.assertTrue(self.app.subs.configured())
        res = self.app.subs.search("tt0903747", 1, 2)
        self.assertEqual([(r["language"], r["source"]) for r in res], [("de", "stremio"), ("en", "stremio")])
        path = self.app.subs.download(res[0], self.app.subtitle_path())
        self.assertEqual(subtitles.SubtitleTrack.from_file(path).text_at(6000), 'Bisher bei "Breaking Bad".')
        # with a key that fails (quota, outage): still the backup
        self.s.set("os_api_key", "k")
        self.fake.on("GET", "api.opensubtitles.com", http.ApiError("down", 503))
        self.assertEqual(self.app.subs.search("tt0903747", 1, 2)[0]["source"], "stremio")

    def test_settings_roundtrip(self):
        self.s.set("pm_key", "zzz")
        self.assertEqual(Settings(self.s.path).get("pm_key"), "zzz")
        self.assertEqual(oct(os.stat(self.s.path).st_mode & 0o777), "0o600")

if __name__ == "__main__":
    unittest.main()
