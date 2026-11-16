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
        self.s.update({"cache_dir": self.tmp, "tmdb_key": "t", "orion_app_key": "a", "orion_user_key": "u"})
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
        path = self.app.subs.download(2, self.app.subtitle_path())
        self.assertEqual(subtitles.SubtitleTrack.from_file(path).text_at(1500), "Hoi")

    def test_settings_roundtrip(self):
        self.s.set("pm_key", "zzz")
        self.assertEqual(Settings(self.s.path).get("pm_key"), "zzz")
        self.assertEqual(oct(os.stat(self.s.path).st_mode & 0o777), "0o600")

if __name__ == "__main__":
    unittest.main()
