"""Stream list with cached / resolution / audio / language filters and send-to-cloud."""
from enigma import RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER, eListboxPythonMultiContent, eServiceReference, gFont

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Screens.ChoiceBox import ChoiceBox
from Screens.Screen import Screen

from ..core.debrid import NotReady
from ..core.models import AUDIO_CHOICES, QUALITY_LABEL, RESOLUTION_CHOICES, channels_label, human_size
from ..core.service import NotCached
from .common import BG, GREY, Async, label, screen

KEY_COLORS = (("red", "#009f1313"), ("green", "#001f771f"), ("yellow", "#00a08500"), ("blue", "#0018188b"))


def _skin():
    body = label("title", 60, 30, 1800, 60, 44)
    body += label("status", 60, 95, 1800, 40, 26, GREY)
    body += ('<widget name="list" position="60,150" size="1800,800" itemHeight="80" backgroundColor="%s" '
             'scrollbarMode="showOnDemand" transparent="1"/>\n') % BG
    for index, (name, color) in enumerate(KEY_COLORS):
        body += ('<widget name="key_%s" position="%d,985" size="430,50" font="Regular;26" halign="center" valign="center" '
                 'foregroundColor="#00ffffff" backgroundColor="%s"/>\n') % (name, 60 + index * 457, color)
    body += label("hint", 60, 1040, 1800, 34, 22, GREY, 'halign="center"')
    return screen("DebridFlixStreams", body)


class StreamList(MenuList):
    def __init__(self):
        MenuList.__init__(self, [], enableWrapAround=True, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", 30))
        self.l.setFont(1, gFont("Regular", 23))
        self.l.setItemHeight(80)


def _text(x, w, text, color=0xFFFFFF, font=0, y=4, h=42, align=RT_HALIGN_LEFT):
    return MultiContentEntryText(pos=(x, y), size=(w, h), font=font, flags=align | RT_VALIGN_CENTER, text=text, color=color, color_sel=color)


class StreamsScreen(Screen, Async):
    skin = _skin()

    def __init__(self, session, app, item, season, episode, title):
        Screen.__init__(self, session)
        self.initAsync()
        self.app, self.item, self.season, self.episode, self.title_text = app, item, season, episode, title
        self.streams = None
        self.busy = False
        self["title"] = Label(title)
        self["status"] = Label("Searching Orion...")
        self["hint"] = Label("OK Play    MENU Send to a service (download)    EXIT Back")
        for name, _color in KEY_COLORS:
            self["key_" + name] = Label("")
        self["list"] = StreamList()
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "MenuActions"], {
            "ok": self.keyOk, "cancel": self.close, "red": self.toggleCached, "green": self.cycleResolution,
            "yellow": self.cycleAudio, "blue": self.cycleLanguage, "menu": self.keySend}, -1)
        self.onLayoutFinish.append(self.search)

    def search(self):
        self.updateKeys()
        self.bg(lambda: self.app.find_streams(self.item, self.season, self.episode), self.found, self.searchFailed)

    def found(self, streams):
        self.streams = streams
        self.rebuild()

    def searchFailed(self, error):
        self.streams = []
        self["status"].setText(str(error))

    # --- list -----------------------------------------------------------
    def rebuild(self):
        if self.streams is None:
            return
        providers = self.app.providers()
        keys = [p.key for p in providers]
        shorts = dict((p.key, p.short) for p in providers)
        shown = self.app.stream_filter().apply(self.streams, keys)
        entries = []
        for s in shown:
            on = s.cached_on(keys)
            maybe = s.maybe_on(keys)
            if on:
                badge, color = "Cached: " + " ".join(shorts[k] for k in on), 0x46D369
            elif maybe:
                badge, color = "Maybe: " + " ".join(shorts[k] for k in maybe), 0xE5A00D
            else:
                badge, color = "Not cached", 0x888888
            audio = channels_label(s.channels) + (" " + s.audio_codec.upper() if s.audio_codec else "")
            extra = "   ".join(x for x in (s.video_codec.upper(), "%s seeds" % s.seeds if s.seeds else "", s.source) if x)
            entries.append([s,
                            _text(15, 130, s.quality_label),
                            _text(150, 170, human_size(s.size)),
                            _text(330, 250, audio),
                            _text(590, 330, " ".join(l.upper() for l in s.languages[:6]) or "-"),
                            _text(930, 520, extra, 0xAAAAAA, 1),
                            _text(1460, 310, badge, color, align=RT_HALIGN_RIGHT),
                            _text(15, 1760, s.name, 0xAAAAAA, 1, 46, 30)])
        self["list"].setList(entries)
        cached_total = len([s for s in self.streams if s.cached_on(keys)])
        self["status"].setText("%s: %d of %d streams shown   |   %d cached on your services%s" % (
            self.app.stream_source().name, len(shown), len(self.streams), cached_total,
            "" if providers else "   |   no debrid service configured"))
        self.updateKeys()

    def updateKeys(self):
        s = self.app.s
        self["key_red"].setText("Cached only: %s" % ("ON" if s.get("filter_cached_only") else "off"))
        self["key_green"].setText("Resolution: %s" % QUALITY_LABEL.get(s.get("filter_resolution"), "Any"))
        self["key_yellow"].setText("Audio: %s" % ("Any" if s.get("filter_audio") == "any" else s.get("filter_audio") + "+"))
        self["key_blue"].setText("Language: %s" % ("Any" if s.get("filter_language") == "any" else str(s.get("filter_language")).upper()))

    def cycle(self, key, choices):
        current = self.app.s.get(key)
        index = choices.index(current) if current in choices else -1
        self.app.s.set(key, choices[(index + 1) % len(choices)])
        self.rebuild()
        self.updateKeys()

    def toggleCached(self):
        self.app.s.set("filter_cached_only", not self.app.s.get("filter_cached_only"))
        self.rebuild()
        self.updateKeys()

    def cycleResolution(self):
        self.cycle("filter_resolution", RESOLUTION_CHOICES)

    def cycleAudio(self):
        self.cycle("filter_audio", AUDIO_CHOICES)

    def cycleLanguage(self):
        choices = self.app.s.list("language_choices") or ["any"]
        if "any" not in choices:
            choices.insert(0, "any")
        self.cycle("filter_language", choices)

    def currentStream(self):
        current = self["list"].getCurrent()
        return current[0] if current else None

    # --- play / send ----------------------------------------------------
    def keyOk(self):
        stream = self.currentStream()
        if not stream or self.busy:
            return
        self.busy = True
        self["status"].setText("Getting the link...")
        self.bg(lambda: self.app.play(stream, self.season, self.episode), self.resolved, lambda e: self.playFailed(stream, e))

    def resolved(self, result):
        self.busy = False
        url, provider = result
        self["status"].setText("Playing from %s" % provider.name)
        from .player import DebridFlixPlayer
        sref = eServiceReference(int(self.app.s.get("player_type") or 4097), 0, url)
        sref.setName(self.title_text)
        self.session.open(DebridFlixPlayer, sref, self.app, self.item, self.season, self.episode)

    def playFailed(self, stream, error):
        self.busy = False
        if isinstance(error, NotCached):
            self["status"].setText("Not cached on your services")
            self.askSend(stream, "Not cached yet. Start the download on:")
        elif isinstance(error, NotReady):
            self.rebuild()
            self.showInfo(str(error) + "\nTry again once the service has finished downloading.")
        else:
            self.rebuild()
            self.showError(error)

    def keySend(self):
        stream = self.currentStream()
        if stream and not self.busy:
            self.askSend(stream, "Download this torrent on:")

    def askSend(self, stream, title):
        choices = [(p.name, p.key) for p in self.app.providers()]
        if not choices:
            self.showInfo("No debrid service configured. Open Setup from the home screen (BLUE).")
            return
        self.session.openWithCallback(lambda choice: self.sendChosen(stream, choice), ChoiceBox, title=title, list=choices)

    def sendChosen(self, stream, choice):
        if not choice:
            return
        self["status"].setText("Sending to %s..." % choice[0])
        self.bg(lambda: self.app.send(stream, choice[1]), lambda message: (self["status"].setText(message), self.showInfo(message)))
