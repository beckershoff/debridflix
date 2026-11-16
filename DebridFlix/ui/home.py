"""Home screen: hero panel on top, two poster rows below (active row + the next one)."""
from enigma import ePoint

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard

from .common import BG, GREY, PANEL, RED, Async, label, screen, set_pixmap

COLS = 9
POSTER_W, POSTER_H = 154, 231
X0, STEP = 60, 200
ROW_Y = (450, 770)


def _skin():
    body = '<widget name="logo" position="60,14" size="88,88" alphatest="blend" zPosition="2"/>\n'
    body += label("brand", 165, 28, 400, 60, 46, RED)
    body += label("hint", 580, 40, 1280, 40, 24, GREY, 'halign="right"')
    body += label("title", 60, 110, 1300, 70, 54)
    body += label("meta", 60, 188, 1300, 40, 28, GREY)
    body += label("overview", 60, 236, 1300, 160, 27)
    body += label("status", 1400, 110, 460, 280, 26, GREY, 'halign="right"')
    body += '<widget name="frame" position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="1"/>\n' % (
        X0 - 6, ROW_Y[0] - 6, POSTER_W + 12, POSTER_H + 12, RED)
    for r in (0, 1):
        body += label("rowtitle%d" % r, 60, ROW_Y[r] - 46, 1700, 38, 30)
        for c in range(COLS):
            x = X0 + c * STEP
            body += ('<widget name="t%d_%d" position="%d,%d" size="%d,%d" font="Regular;22" halign="center" valign="center" '
                     'foregroundColor="%s" backgroundColor="%s" zPosition="2"/>\n') % (r, c, x, ROW_Y[r], POSTER_W, POSTER_H, GREY, PANEL)
            body += '<widget name="p%d_%d" position="%d,%d" size="%d,%d" zPosition="3"/>\n' % (r, c, x, ROW_Y[r], POSTER_W, POSTER_H)
    return screen("DebridFlixHome", body)


class HomeScreen(Screen, Async):
    skin = _skin()

    def __init__(self, session, app):
        Screen.__init__(self, session)
        self.initAsync()
        self.app = app
        self.rows = []
        self.row = 0
        self.pending = set()
        self.cells = {}
        for name in ("brand", "hint", "title", "meta", "overview", "status", "frame", "rowtitle0", "rowtitle1"):
            self[name] = Label("")
        for r in (0, 1):
            for c in range(COLS):
                self["t%d_%d" % (r, c)] = Label("")
                self["p%d_%d" % (r, c)] = Pixmap()
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions", "MenuActions"], {
            "ok": self.keyOk, "cancel": self.close, "left": self.keyLeft, "right": self.keyRight,
            "up": self.keyUp, "down": self.keyDown, "red": self.keySearch, "green": self.keyWatchlist,
            "yellow": self.keyCachedOnly, "blue": self.keySetup, "menu": self.keySetup}, -1)
        self["logo"] = Pixmap()
        self.onLayoutFinish.append(self.start)

    # --- rows -----------------------------------------------------------
    def start(self):
        self["brand"].setText("DebridFlix")
        from .pair import LOGO
        if not set_pixmap(self["logo"], LOGO):
            self["logo"].hide()
        self.buildRows()

    def buildRows(self, keep=None):
        self.rows = [self.makeRow(title, loader) for title, loader in self.app.rows()]
        if keep:
            self.rows.insert(0, keep)
        self.row = 0
        missing = self.app.missing_setup()
        self["status"].setText("Setup needed:\n" + "\n".join(missing) + "\n\nBLUE, then YELLOW to pair with your phone" if missing else "")
        self.refresh()
        if self.app.tmdb.configured():
            self.bg(self.app.genre_rows, self.genresLoaded, lambda err: None)

    @staticmethod
    def makeRow(title, loader):
        return {"title": title, "loader": loader, "items": None, "loading": False, "error": "", "sel": 0, "offset": 0,
                "watchlist": title.startswith("My watchlist")}

    def genresLoaded(self, rows):
        self.rows += [self.makeRow(title, loader) for title, loader in rows]
        self.refresh()

    def loadRow(self, row):
        row["loading"] = True

        def done(items):
            row.update(items=items, loading=False, error="")
            self.refresh()

        def failed(error):
            row.update(items=[], loading=False, error=str(error))
            self.refresh()

        self.bg(lambda: self.app.load_row(row["loader"]), done, failed)

    def resetRows(self, only_watchlist=False):
        for row in self.rows:
            if row["watchlist"] or not only_watchlist:
                row.update(items=None, sel=0, offset=0)
        self.refresh()

    def current(self):
        if self.row < len(self.rows):
            row = self.rows[self.row]
            if row["items"] and row["sel"] < len(row["items"]):
                return row["items"][row["sel"]]
        return None

    # --- drawing --------------------------------------------------------
    def refresh(self):
        for d in (0, 1):
            index = self.row + d
            row = self.rows[index] if index < len(self.rows) else None
            if row and row["items"] is None and not row["loading"]:
                self.loadRow(row)
            text = ""
            if row:
                text = row["title"]
                if row["loading"]:
                    text += "   (loading...)"
                elif row["error"]:
                    text += "   - " + row["error"]
                elif not row["items"]:
                    text += "   (nothing here)"
            self["rowtitle%d" % d].setText(text)
            for c in range(COLS):
                item = None
                if row and row["items"] and row["offset"] + c < len(row["items"]):
                    item = row["items"][row["offset"] + c]
                self.drawCell(d, c, item)
        row = self.rows[self.row] if self.row < len(self.rows) else None
        column = (row["sel"] - row["offset"]) if row else 0
        if self["frame"].instance:
            self["frame"].instance.move(ePoint(X0 - 6 + column * STEP, ROW_Y[0] - 6))
        item = self.current()
        if item:
            self["frame"].show()
            self["title"].setText(item["title"])
            parts = [item.get("year") or "", "Movie" if item["kind"] == "movie" else "Series"]
            if item.get("rating"):
                parts.append("Rating %.1f" % float(item["rating"]))
            self["meta"].setText("   |   ".join(p for p in parts if p))
            self["overview"].setText(item.get("overview") or "")
        else:
            self["frame"].hide()
            for name in ("title", "meta", "overview"):
                self[name].setText("")
        self["hint"].setText("OK Details    RED Search    GREEN Watchlist    YELLOW Cached only: %s    BLUE Setup" % (
            "ON" if self.app.browse_cached_only else "off"))

    def drawCell(self, r, c, item):
        text, pix = self["t%d_%d" % (r, c)], self["p%d_%d" % (r, c)]
        if not item:
            text.hide()
            pix.hide()
            self.cells[(r, c)] = None
            return
        text.setText(item["title"])
        text.show()
        path = item.get("poster") or ""
        if path and self.cells.get((r, c)) == path:
            return  # this poster is already on screen
        if set_pixmap(pix, self.app.poster_cached(path)):
            self.cells[(r, c)] = path
            return
        pix.hide()
        self.cells[(r, c)] = None
        if path and path not in self.pending:
            self.pending.add(path)
            self.bg(lambda: self.app.poster_file(path), lambda found: self.posterDone(path, bool(found)), lambda _e: None)

    def posterDone(self, path, ok=True):
        if not ok:
            return  # stays in pending so a broken poster is not retried in a loop
        self.pending.discard(path)
        for d in (0, 1):
            index = self.row + d
            row = self.rows[index] if index < len(self.rows) else None
            if not row or not row["items"]:
                continue
            for c in range(COLS):
                pos = row["offset"] + c
                if pos < len(row["items"]) and row["items"][pos].get("poster") == path:
                    if set_pixmap(self["p%d_%d" % (d, c)], self.app.poster_cached(path)):
                        self.cells[(d, c)] = path

    # --- keys -----------------------------------------------------------
    def move(self, delta):
        if self.row >= len(self.rows):
            return
        row = self.rows[self.row]
        count = len(row["items"] or [])
        if not count:
            return
        row["sel"] = max(0, min(count - 1, row["sel"] + delta))
        if row["sel"] < row["offset"]:
            row["offset"] = row["sel"]
        elif row["sel"] >= row["offset"] + COLS:
            row["offset"] = row["sel"] - COLS + 1
        self.refresh()

    def keyLeft(self):
        self.move(-1)

    def keyRight(self):
        self.move(1)

    def keyUp(self):
        if self.row > 0:
            self.row -= 1
            self.refresh()

    def keyDown(self):
        if self.row < len(self.rows) - 1:
            self.row += 1
            self.refresh()

    def keyOk(self):
        item = self.current()
        if item:
            from .detail import DetailScreen
            self.session.openWithCallback(self.detailClosed, DetailScreen, self.app, item)

    def detailClosed(self, changed=False):
        if changed:
            self.resetRows(only_watchlist=True)

    def keySearch(self):
        self.session.openWithCallback(self.searchEntered, VirtualKeyBoard, title="Search movies and series", text="")

    def searchEntered(self, text):
        if not text:
            return
        self.rows = [r for r in self.rows if not r["title"].startswith("Search: ")]
        self.rows.insert(0, self.makeRow("Search: %s" % text, lambda: self.app.tmdb.search(text)))
        self.row = 0
        self.refresh()

    def keyWatchlist(self):
        item = self.current()
        if not item:
            return
        if not self.app.trakt.configured():
            self.showInfo("Link Trakt first: BLUE (Setup), then YELLOW.")
            return
        trakt = self.app.trakt

        def toggle():
            return trakt.set_watchlist(item, not trakt.in_watchlist(item))

        def done(state):
            self.showInfo("%s %s your Trakt watchlist" % (item["title"], "added to" if state else "removed from"), 3)
            self.resetRows(only_watchlist=True)

        self.bg(toggle, done)

    def keyCachedOnly(self):
        self.app.browse_cached_only = not self.app.browse_cached_only
        self.resetRows()

    def keySetup(self):
        from .setup import SetupScreen
        self.session.openWithCallback(self.setupClosed, SetupScreen, self.app)

    def setupClosed(self, *_args):
        search = [r for r in self.rows if r["title"].startswith("Search: ")]
        self.buildRows(keep=search[0] if search else None)
