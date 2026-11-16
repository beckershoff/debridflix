"""Title page: poster, description, seasons/episodes, watchlist toggle."""
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from .common import BG, GREY, Async, label, screen, set_pixmap


def _skin():
    body = '<widget name="poster" position="60,90" size="342,513" zPosition="2"/>\n'
    body += label("title", 450, 80, 1400, 70, 54)
    body += label("meta", 450, 158, 1400, 40, 28, GREY)
    body += label("overview", 450, 210, 1400, 250, 27)
    body += ('<widget name="list" position="450,480" size="1400,500" font="Regular;32" itemHeight="50" '
             'backgroundColor="%s" scrollbarMode="showOnDemand" transparent="1"/>\n') % BG
    body += label("status", 60, 1010, 1800, 40, 26, GREY)
    return screen("DebridFlixDetail", body)


class DetailScreen(Screen, Async):
    skin = _skin()

    def __init__(self, session, app, item):
        Screen.__init__(self, session)
        self.initAsync()
        self.app = app
        self.item = dict(item)
        self.seasons = []
        self.season = None
        self.inWatchlist = None
        self.changed = False
        self["poster"] = Pixmap()
        self["title"] = Label(item["title"])
        self["meta"] = Label("")
        self["overview"] = Label(item.get("overview") or "")
        self["status"] = Label("Loading...")
        self["list"] = MenuList([])
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.keyOk, "cancel": self.keyCancel}, -1)
        self.onLayoutFinish.append(self.start)

    def start(self):
        self["poster"].hide()
        path = self.item.get("poster")
        if path:
            self.bg(lambda: self.app.poster_file(path, "w342"), lambda f: set_pixmap(self["poster"], f), lambda e: None)

        def load():
            item, seasons = self.app.full_item(self.item)
            state = None
            if self.app.trakt.configured():
                try:
                    state = self.app.trakt.in_watchlist(item)
                except Exception:
                    state = None
            return item, seasons, state

        self.bg(load, self.loaded)

    def loaded(self, result):
        item, self.seasons, self.inWatchlist = result
        self.item.update(item)
        parts = [self.item.get("year") or "", "Movie" if self.item["kind"] == "movie" else "Series",
                 ", ".join(self.item.get("genres") or [])]
        if self.item.get("runtime"):
            parts.append("%s min" % self.item["runtime"])
        if self.item.get("rating"):
            parts.append("Rating %.1f" % float(self.item["rating"]))
        self["meta"].setText("   |   ".join(p for p in parts if p))
        self["overview"].setText(self.item.get("overview") or "")
        self["status"].setText("")
        self.showMain()

    def showMain(self):
        self.season = None
        entries = []
        if self.item["kind"] == "movie":
            entries.append(("Find streams", ("streams", None)))
        else:
            for number, name, count in self.seasons:
                entries.append(("%s   (%d episodes)" % (name, count), ("season", number)))
        if self.inWatchlist is not None:
            entries.append(("Remove from Trakt watchlist" if self.inWatchlist else "Add to Trakt watchlist", ("watchlist", None)))
        self["list"].setList(entries)

    def keyOk(self):
        current = self["list"].getCurrent()
        if not current:
            return
        action, value = current[1]
        if action == "streams":
            self.openStreams(None, None, self.item["title"])
        elif action == "season":
            self["status"].setText("Loading episodes...")
            self.bg(lambda: self.app.tmdb.season(self.item["tmdb"], value), lambda eps: self.showEpisodes(value, eps))
        elif action == "episode":
            self.openStreams(self.season, value, "%s S%02dE%02d" % (self.item["title"], self.season, value))
        elif action == "watchlist":
            wanted = not self.inWatchlist
            self.bg(lambda: self.app.trakt.set_watchlist(self.item, wanted), self.watchlistSet)

    def watchlistSet(self, state):
        self.inWatchlist = state
        self.changed = True
        if self.season is None:
            self.showMain()

    def showEpisodes(self, season, episodes):
        self.season = season
        self["status"].setText("Season %d - EXIT goes back to the seasons" % season)
        self["list"].setList([("E%02d   %s   %s" % (number, name, ("(%s)" % date) if date else ""), ("episode", number))
                              for number, name, _overview, date in episodes if number])

    def openStreams(self, season, episode, title):
        from .streams import StreamsScreen
        self.session.open(StreamsScreen, self.app, self.item, season, episode, title)

    def keyCancel(self):
        if self.season is not None:
            self["status"].setText("")
            self.showMain()
        else:
            self.close(self.changed)
