"""Setup: keys and options, account linking with a device code, connection test."""
import time

from enigma import eTimer

from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.config import ConfigSelection, ConfigText, ConfigYesNo, getConfigListEntry
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard

from ..core.settings import SETUP_FIELDS
from .common import BG, GREY, Async, label, screen


def _setup_skin():
    body = label("title", 60, 30, 1800, 60, 44)
    body += ('<widget name="config" position="60,120" size="1800,800" font="Regular;30" itemHeight="50" backgroundColor="%s" '
             'scrollbarMode="showOnDemand" transparent="1"/>\n') % BG
    for index, (name, color) in enumerate((("red", "#009f1313"), ("green", "#001f771f"), ("yellow", "#00a08500"))):
        body += ('<widget name="key_%s" position="%d,985" size="430,50" font="Regular;26" halign="center" valign="center" '
                 'foregroundColor="#00ffffff" backgroundColor="%s"/>\n') % (name, 60 + index * 457, color)
    body += label("hint", 60, 940, 1800, 36, 24, GREY)
    return screen("DebridFlixSetup", body)


class SetupScreen(ConfigListScreen, Screen, Async):
    skin = _setup_skin()

    def __init__(self, session, app):
        Screen.__init__(self, session)
        self.initAsync()
        self.app = app
        self.fields = []
        entries = []
        for text, key, kind, choices in SETUP_FIELDS:
            value = app.s.get(key)
            if kind == "bool":
                element = ConfigYesNo(default=bool(value))
            elif kind == "choice":
                element = ConfigSelection(default=str(value) if str(value) in choices else choices[0], choices=choices)
            else:
                element = ConfigText(default=str(value or ""), fixed_size=False)
            self.fields.append((key, kind, element))
            entries.append(getConfigListEntry(text, element))
        ConfigListScreen.__init__(self, entries, session=session)
        self["title"] = Label("DebridFlix setup")
        self["hint"] = Label("OK opens the keyboard for text fields. Everything is stored in /etc/enigma2/debridflix.json")
        self["key_red"] = Label("Cancel")
        self["key_green"] = Label("Save")
        self["key_yellow"] = Label("Phone pairing / link / test")
        self["debridflixSetupActions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "ok": self.keyOk, "cancel": self.close, "red": self.close, "green": self.keySave, "yellow": self.keyLink}, -2)

    def store(self):
        values = {}
        for key, kind, element in self.fields:
            values[key] = bool(element.value) if kind == "bool" else str(element.value).strip()
        self.app.s.update(values)

    def reloadForm(self):
        for key, kind, element in self.fields:
            if key in ("rd_token", "ad_key"):
                element.value = str(self.app.s.get(key) or "")
        self["config"].invalidateCurrent()

    def keyOk(self):
        current = self["config"].getCurrent()
        if current and isinstance(current[1], ConfigText):
            element = current[1]
            self.session.openWithCallback(lambda text: self.textEntered(element, text), VirtualKeyBoard, title=current[0], text=element.value)

    def textEntered(self, element, text):
        if text is not None:
            element.value = text
            self["config"].invalidateCurrent()

    def keySave(self):
        self.store()
        self.close(True)

    def keyLink(self):
        self.store()
        choices = [("Set up from your phone (QR code)", "pair"),
                   ("Link Real-Debrid (code on real-debrid.com/device)", "realdebrid"),
                   ("Link AllDebrid (PIN)", "alldebrid"),
                   ("Link Trakt (code on trakt.tv/activate)", "trakt"),
                   ("Test all connections", "test")]
        self.session.openWithCallback(self.linkChosen, ChoiceBox, title="Accounts", list=choices)

    def linkChosen(self, choice):
        if not choice:
            return
        if choice[1] == "pair":
            from .pair import PairScreen
            self.session.openWithCallback(self.pairClosed, PairScreen, self.app)
            return
        if choice[1] == "test":
            self.bg(self.app.test_connections, lambda text: self.session.open(MessageBox, text, MessageBox.TYPE_INFO))
            return
        target = self.app.trakt if choice[1] == "trakt" else self.app.provider(choice[1])
        self.session.openWithCallback(self.linkClosed, DeviceAuthScreen, choice[0], target)

    def pairClosed(self, changed=False):
        if changed:  # the phone wrote new values; show them instead of the stale form
            self.close(True)

    def linkClosed(self, linked=False):
        self.reloadForm()
        if linked:
            self.showInfo("Account linked.", 4)


class DeviceAuthScreen(Screen, Async):
    skin = screen("DebridFlixDeviceAuth", label("title", 60, 200, 1800, 70, 48, extra='halign="center"') +
                  label("text", 60, 330, 1800, 400, 44, extra='halign="center"') +
                  label("hint", 60, 900, 1800, 40, 26, GREY, 'halign="center"'))

    def __init__(self, session, title, target):
        Screen.__init__(self, session)
        self.initAsync()
        self.target = target
        self.state = None
        self.deadline = 0
        self.polling = False
        self["title"] = Label(title)
        self["text"] = Label("Requesting a code...")
        self["hint"] = Label("EXIT cancels")
        self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.close, "ok": self.close}, -1)
        self.timer = eTimer()
        self.timer.callback.append(self.poll)
        self.onLayoutFinish.append(lambda: self.bg(self.target.auth_start, self.started, self.failed))
        self.onClose.append(self.timer.stop)

    def started(self, state):
        self.state = state
        self.deadline = time.time() + state.get("expires", 600)
        self["text"].setText("On your phone or computer open\n%s\n\nand enter the code\n%s" % (state["url"], state["code"]))
        self.timer.start(max(2, int(state.get("interval", 5))) * 1000)

    def poll(self):
        if self.polling:
            return
        if time.time() > self.deadline:
            self.failed("The code has expired. Try again.")
            return
        self.polling = True
        self.bg(lambda: self.target.auth_poll(self.state), self.polled, self.failed)

    def polled(self, done):
        self.polling = False
        if done:
            self.timer.stop()
            self.close(True)

    def failed(self, error):
        self.polling = False
        self.timer.stop()
        self["text"].setText(str(error))
