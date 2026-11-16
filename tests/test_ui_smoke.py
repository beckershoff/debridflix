"""Drives the screens against stand-in Enigma2 classes. It checks our own logic, not Enigma2 itself."""
import os, sys, tempfile, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

class Inst(object):
    def __init__(self): self.calls = []
    def __getattr__(self, name): return lambda *a: self.calls.append((name, a))
class Widget(object):
    def __init__(self, text=""): self.text = text; self.visible = True; self.instance = Inst()
    def setText(self, t): self.text = t
    def getText(self): return self.text
    def show(self): self.visible = True
    def hide(self): self.visible = False
class MenuList(Widget):
    def __init__(self, lst, enableWrapAround=False, content=None): Widget.__init__(self); self.list = lst; self.index = 0; self.l = Inst()
    def setList(self, lst): self.list = lst; self.index = 0
    def getCurrent(self): return self.list[self.index] if self.list else None
    def invalidateCurrent(self): pass
class Screen(dict):
    def __init__(self, session): self.session = session; self.onLayoutFinish = []; self.onClose = []; self.closed = None; self._cb = None
    def show(self): pass
    def hide(self): pass
    def close(self, *args):
        self.closed = args
        for f in self.onClose: f()
        self.session.stack.remove(self)
        if self._cb: self._cb(*args)
class Session(object):
    def __init__(self): self.stack = []; self.nav = Inst(); self.answers = []
    def open(self, cls, *a, **k): return self.openWithCallback(None, cls, *a, **k)
    def openWithCallback(self, cb, cls, *a, **k):
        if cls.__name__ in ("ChoiceBox", "VirtualKeyBoard", "MessageBox"):
            self.dialogs.append((cls.__name__, a, k))
            if cb and cls.__name__ != "MessageBox": cb(self.answers.pop(0)(k) if self.answers else None)
            return None
        dlg = cls(self, *a, **k); dlg._cb = cb; self.stack.append(dlg)
        for f in dlg.onLayoutFinish:  # like Enigma2: anything that is not a bound method of the screen is exec()'d
            if getattr(f, "__self__", None) is not dlg: raise TypeError("exec() arg 1 must be a string, bytes or code object")
            f()
        return dlg
    def instantiateDialog(self, cls, *a): return cls(self, *a)
    def deleteDialog(self, d): pass
    dialogs = []
class Deferred(object):
    def __init__(self, func, a):
        try: self.ok, self.val = True, func(*a)
        except Exception as e: self.ok, self.val = False, types.SimpleNamespace(value=e)
    def addCallbacks(self, good, bad): (good if self.ok else bad)(self.val); return self
    def addErrback(self, bad): return self
def mod(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
class Cfg(object):
    def __init__(self, default=None, **k): self.value = default
class MoviePlayer(Screen):
    def __init__(self, session, service): Screen.__init__(self, session); self.service = service
class SRef(object):
    def __init__(self, t, f, path): self.type, self.path = t, path
    def setName(self, n): self.name = n
class MessageBox(object): TYPE_INFO = 1; TYPE_ERROR = 2
DESKTOP = types.SimpleNamespace(width=lambda: 1280, height=lambda: 720)  # GUI at 720p, like the real box
mod("enigma", ePoint=lambda x, y: (x, y), getDesktop=lambda i: types.SimpleNamespace(size=lambda: DESKTOP), eTimer=lambda: types.SimpleNamespace(callback=[], start=lambda *a: None, stop=lambda: None),
    eListboxPythonMultiContent=object(), gFont=lambda *a: a, RT_HALIGN_LEFT=0, RT_HALIGN_RIGHT=1, RT_VALIGN_CENTER=4, eServiceReference=SRef)
for n in ("twisted", "twisted.internet", "Components", "Screens", "Tools", "Plugins"): mod(n)
mod("twisted.internet.threads", deferToThread=lambda f, *a: Deferred(f, a)); sys.modules["twisted.internet"].threads = sys.modules["twisted.internet.threads"]
mod("Components.ActionMap", ActionMap=lambda ctx, actions, prio=0: actions)
mod("Components.Label", Label=Widget); mod("Components.Pixmap", Pixmap=Widget); mod("Components.MenuList", MenuList=MenuList)
mod("Components.MultiContent", MultiContentEntryText=lambda **k: k)
class CLS(object):
    def __init__(self, lst, session=None): self["config"] = MenuList(lst)
mod("Components.ConfigList", ConfigListScreen=CLS)
mod("Components.config", ConfigSelection=Cfg, ConfigText=Cfg, ConfigYesNo=Cfg, getConfigListEntry=lambda *a: a)
mod("Screens.Screen", Screen=Screen); mod("Screens.MessageBox", MessageBox=MessageBox)
mod("Screens.ChoiceBox", ChoiceBox=type("ChoiceBox", (), {})); mod("Screens.VirtualKeyBoard", VirtualKeyBoard=type("VirtualKeyBoard", (), {}))
mod("Screens.InfoBar", MoviePlayer=MoviePlayer); mod("Tools.LoadPixmap", LoadPixmap=lambda p: "PIX:" + p)
mod("Plugins.Plugin", PluginDescriptor=type("PluginDescriptor", (), {"WHERE_PLUGINMENU": 1, "WHERE_EXTENSIONSMENU": 2, "__init__": lambda self, **k: None}))

from DebridFlix.core import http
from DebridFlix.core.settings import Settings
from DebridFlix.core.service import App
from tests.test_core import Fake, orion_stream, H1, H2

class UiSmoke(unittest.TestCase):
    def test_point_scales_to_desktop(self):
        from DebridFlix.ui.common import point
        self.assertEqual(point(54, 444), (36, 296))  # 1920x1080 skin coordinates -> 1280x720 desktop pixels

    def setUp(self):
        tmp = tempfile.mkdtemp(); s = Settings(os.path.join(tmp, "c.json"))
        s.update({"cache_dir": tmp, "tmdb_key": "t", "orion_app_key": "a", "orion_user_key": "u", "pm_key": "p",
                  "trakt_client_id": "c", "trakt_client_secret": "s", "trakt_access": "tok", "os_api_key": "k"})
        self.fake = f = Fake(); self._orig = http.request; http.request = f
        movies = [{"id": i, "title": "Movie %d" % i, "release_date": "2021-01-01", "poster_path": "/p%d.jpg" % i, "vote_average": 7} for i in range(1, 13)]
        f.on("GET", "/sync/watchlist/movies", [{"movie": {"title": "Movie 1", "year": 2021, "ids": {"tmdb": 1}}}])
        f.on("GET", "/sync/watchlist/shows", [])
        f.on("POST", "/sync/watchlist", {}); f.on("POST", "/sync/history", {})
        f.on("GET", "/genre/movie/list", {"genres": [{"id": 28, "name": "Action"}]}); f.on("GET", "/genre/tv/list", {"genres": []})
        f.on("GET", "/trending/movie", {"results": movies}); f.on("GET", "/trending/tv", {"results": [{"id": 50, "name": "Show", "poster_path": "/s.jpg"}]})
        f.on("GET", "/search/multi", {"results": [dict(movies[2], media_type="movie"), {"id": 9, "media_type": "person"}]})
        f.on("GET", "/tv/50/season/1", {"episodes": [{"episode_number": 1, "name": "Pilot", "air_date": "2020-01-01"}, {"episode_number": 2, "name": "Two"}]})
        f.on("GET", "/tv/50", {"id": 50, "name": "Show", "external_ids": {"imdb_id": "tt50"}, "seasons": [{"season_number": 0, "name": "Specials"}, {"season_number": 1, "name": "Season 1", "episode_count": 2}]})
        f.on("GET", "/movie/", lambda u, p, d, j: {"id": 1, "title": "Movie 1", "imdb_id": "tt1", "genres": [{"name": "Action"}], "runtime": 100, "poster_path": "/p1.jpg"})
        f.on("GET", "image.tmdb.org", b"JPEG")
        f.on("GET", "api.themoviedb.org", {"results": []})
        f.on("POST", "api.orionoid.com", {"result": {"status": "success"}, "data": {"streams": [
            orion_stream(H1, "hd1080", 6, ["en"], {}, "Show.S01E02.1080p.mkv"), orion_stream(H2, "hd4k", 6, ["en"], {}, "Show.S01E02.2160p.mkv")]}})
        f.on("POST", "/cache/check", lambda u, p, d, j: {"status": "success", "response": [h == H1 for h in d["items[]"]]})
        f.on("POST", "/transfer/directdl", {"status": "success", "content": [{"path": "Show.S01E02.mkv", "size": 9, "link": "https://pm/file.mkv"}]})
        f.on("POST", "/transfer/create", {"status": "success", "id": "x"})
        f.on("GET", "/subtitles", {"data": [{"attributes": {"language": "nl", "release": "R", "download_count": 1, "files": [{"file_id": 4}]}}]})
        f.on("POST", "/download", {"link": "https://os/x.srt"}); f.on("GET", "https://os/x.srt", b"1\n00:00:01,000 --> 00:00:03,000\nHallo\n")
        self.app = App(s); self.session = Session(); Session.dialogs = []
    def tearDown(self): http.request = self._orig

    def test_full_flow(self):
        from DebridFlix import plugin
        self.assertEqual(len(plugin.Plugins()), 1)
        from DebridFlix.ui.home import HomeScreen, COLS
        home = self.session.open(HomeScreen, self.app); act = home["actions"]
        self.assertEqual([r["title"] for r in home.rows][:3], ["My watchlist - Movies", "My watchlist - Series", "Trending movies"])
        self.assertEqual(home.rows[-1]["title"], "Movies - Action")
        self.assertEqual(home["title"].text, "Movie 1"); self.assertEqual(home["status"].text, "")
        self.assertTrue(home["p0_0"].visible); self.assertEqual(home.cells[(0, 0)], "/p1.jpg")
        act["down"](); act["down"]()
        self.assertIn("Trending movies", home["rowtitle0"].text); self.assertIn("Trending series", home["rowtitle1"].text)
        for _ in range(10): act["right"]()
        row = home.rows[home.row]; self.assertEqual((row["sel"], row["offset"]), (10, 10 - COLS + 1)); self.assertEqual(home["title"].text, "Movie 11")
        for _ in range(20): act["right"]()
        self.assertEqual(row["sel"], 11)
        self.session.answers = [lambda k: "movie"]; act["red"]()
        self.assertEqual(home.rows[0]["title"], "Search: movie"); self.assertEqual(home["title"].text, "Movie 3")
        act["green"]()  # watchlist toggle on Movie 3
        self.assertIn({"movies": [{"ids": {"tmdb": 3}}]}, [c[4] for c in self.fake.calls if c[1].endswith("/sync/watchlist")])
        act["yellow"](); self.assertTrue(self.app.browse_cached_only); act["yellow"]()
        # series: detail -> season -> episode -> streams -> play
        home.row = [r["title"] for r in home.rows].index("Trending series"); home.refresh()
        act["ok"](); detail = self.session.stack[-1]
        self.assertEqual([e[0] for e in detail["list"].list], ["Season 1   (2 episodes)", "Add to Trakt watchlist"])
        detail["actions"]["ok"](); self.assertEqual(len(detail["list"].list), 2)
        detail["list"].index = 1; detail["actions"]["ok"]()
        streams = self.session.stack[-1]
        self.assertEqual(streams["title"].text, "Show S01E02"); self.assertEqual(len(streams["list"].list), 1)
        self.assertIn("Cached only: ON", streams["key_red"].text)
        streams["actions"]["red"](); self.assertEqual(len(streams["list"].list), 2)
        streams["actions"]["green"](); self.assertEqual(len(streams["list"].list), 1); self.assertIn("4K", streams["key_green"].text)
        self.session.answers = [lambda k: k["list"][0]]; streams["actions"]["ok"]()  # 4K is not cached -> offer download
        self.assertEqual(Session.dialogs[-2][0], "ChoiceBox"); self.assertIn("Premiumize", streams["status"].text)
        for _ in range(4): streams["actions"]["green"]()
        streams["actions"]["red"](); streams["actions"]["ok"]()
        player = self.session.stack[-1]
        self.assertEqual((player.service.path, player.service.type, player.service.name), ("https://pm/file.mkv", 4097, "Show S01E02"))
        self.session.answers = [lambda k: k["list"][0], lambda k: k["list"][0]]
        player["debridflixActions"]["blue"]()
        self.assertEqual(player.track.text_at(2000), "Hallo")
        player.session.nav = types.SimpleNamespace(getCurrentService=lambda: types.SimpleNamespace(seek=lambda: types.SimpleNamespace(
            getPlayPosition=lambda: (0, 2000 * 90), getLength=lambda: (0, 2200 * 90))))
        player.subtitleTick(); self.assertEqual(player.overlay["text"].text, "Hallo")
        player.leavePlayer()
        self.assertEqual(self.fake.calls[-1][4]["shows"][0]["seasons"], [{"number": 1, "episodes": [{"number": 2}]}])
        self.assertIs(self.session.stack[-1], streams)
        streams["actions"]["cancel"](); detail["actions"]["cancel"](); detail["actions"]["cancel"]()
        self.assertIs(self.session.stack[-1], home)

    def test_setup(self):
        from DebridFlix.ui.setup import SetupScreen, DeviceAuthScreen
        setup = self.session.open(SetupScreen, self.app)
        field = dict((k, e) for k, _kind, e in setup.fields)
        self.session.answers = [lambda k: " newkey "]; setup["config"].index = 0; setup["debridflixSetupActions"]["ok"]()
        self.assertEqual(field["tmdb_key"].value, " newkey ")
        self.fake.on("GET", "/device/code", {"device_code": "D", "user_code": "ABCD", "interval": 5, "expires_in": 600, "verification_url": "https://real-debrid.com/device"})
        self.fake.on("GET", "/device/credentials", {"client_id": "cid", "client_secret": "sec"})
        self.fake.on("POST", "/oauth/v2/token", {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
        auth = self.session.open(DeviceAuthScreen, "RD", self.app.provider("realdebrid"))
        self.assertIn("ABCD", auth["text"].text); auth.poll()
        self.assertEqual(self.app.s.get("rd_token"), "AT"); self.assertEqual(auth.closed, (True,))
        setup.reloadForm(); self.assertEqual(field["rd_token"].value, "AT")
        setup["debridflixSetupActions"]["green"]()
        self.assertEqual(self.app.s.get("tmdb_key"), "newkey"); self.assertEqual(self.app.s.get("rd_token"), "AT")

    def test_pairing(self):
        import json, urllib.request, cv2, numpy as np
        from DebridFlix.core import qr
        from DebridFlix.ui.pair import PairScreen
        import DebridFlix.core.pairing as pairing
        pairing.local_ip = lambda: "127.0.0.1"
        screen = self.session.open(PairScreen, self.app)
        url = screen["url"].text
        self.assertTrue(url.startswith("http://127.0.0.1:")); self.assertTrue(screen["qr"].visible)
        img = cv2.imdecode(np.fromfile(os.path.join(self.app.s.get("cache_dir"), "pair_qr.png"), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(cv2.QRCodeDetector().detectAndDecode(img)[0], url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        page = opener.open(url, timeout=5).read().decode()
        self.assertIn("Real-Debrid API token", page); self.assertNotIn('value="p"', page); self.assertIn("saved - leave empty", page)
        self.assertEqual(opener.open(url + "logo.png", timeout=5).read()[:4], b"\x89PNG")
        with self.assertRaises(Exception): opener.open(url.replace(screen.server.token, "wrong"), timeout=5)
        body = "tb_key=TBKEY&pm_key=&subtitle_languages=de%2Cen&subtitle_auto=yes&tmdb_language=nl-NL&player_type=9999"
        reply = opener.open(urllib.request.Request(url + "save", data=body.encode()), timeout=5).read().decode()
        self.assertIn("Saved.", reply)
        s = self.app.s
        self.assertEqual((s.get("tb_key"), s.get("pm_key"), s.get("subtitle_languages"), s.get("subtitle_auto"), s.get("tmdb_language"), s.get("player_type")),
                         ("TBKEY", "p", "de,en", True, "nl-NL", "4097"))
        self.fake.on("GET", "/device/code", {"device_code": "D", "user_code": "WXYZ", "interval": 0, "expires_in": 60, "verification_url": "https://real-debrid.com/device"})
        self.fake.on("GET", "/device/credentials", {"client_id": "cid", "client_secret": "sec"})
        self.fake.on("POST", "/oauth/v2/token", {"access_token": "AT2", "refresh_token": "RT", "expires_in": 3600})
        import time as _t; real_sleep = _t.sleep; pairing.time.sleep = lambda n: real_sleep(0.05)
        try:
            opener.open(urllib.request.Request(url + "link/realdebrid", data=b""), timeout=5).read()
            for _ in range(40):
                status = json.loads(opener.open(url + "status", timeout=5).read())
                if status.get("realdebrid", {}).get("status") == "linked": break
                real_sleep(0.05)
        finally:
            pairing.time.sleep = real_sleep
        self.assertEqual(status["realdebrid"]["status"], "linked"); self.assertEqual(s.get("rd_token"), "AT2")
        screen.tick(); self.assertIn("Real-Debrid linked", screen["events"].text)
        screen["actions"]["cancel"](); self.assertEqual(screen.closed, (True,))

if __name__ == "__main__":
    unittest.main()
