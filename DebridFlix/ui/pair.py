"""Pairing screen: QR code that opens the box's setup page on your phone."""
import os

from enigma import eTimer

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.Screen import Screen

from ..core import qr
from ..core.pairing import PairingServer
from .common import GREY, Async, label, screen, set_pixmap

LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logo.png")


class PairScreen(Screen, Async):
    skin = screen("DebridFlixPair",
                  label("title", 60, 60, 1800, 70, 50) +
                  '<widget name="qr" position="160,260" size="480,480" zPosition="2"/>\n' +
                  label("text", 760, 260, 1060, 330, 36) +
                  label("url", 760, 600, 1060, 50, 34, "#0046d369") +
                  label("events", 760, 680, 1060, 200, 30, GREY) +
                  label("hint", 60, 980, 1800, 40, 26, GREY, 'halign="center"'))

    def __init__(self, session, app):
        Screen.__init__(self, session)
        self.initAsync()
        self.app = app
        self.server = PairingServer(app, logo_path=LOGO)
        self.seen = 0
        self["title"] = Label("Set up DebridFlix from your phone")
        self["qr"] = Pixmap()
        self["text"] = Label("1. Put your phone on the same Wi-Fi as this box.\n2. Scan the code with the camera.\n"
                             "3. Paste your keys, or tap Link for Real-Debrid, AllDebrid and Trakt.")
        self["url"] = Label("")
        self["events"] = Label("")
        self["hint"] = Label("The page only works while this screen is open.  OK / EXIT closes it.")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.finish, "cancel": self.finish}, -1)
        self.timer = eTimer()
        self.timer.callback.append(self.tick)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.stop)

    def start(self):
        try:
            url = self.server.start()
            path = os.path.join(self.app.s.get("cache_dir"), "pair_qr.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(qr.png(qr.encode(url)))
        except Exception as err:
            self["qr"].hide()
            self["url"].setText("Could not start pairing: %s" % err)
            return
        if not set_pixmap(self["qr"], path):
            self["qr"].hide()
        self["url"].setText(url)
        self.timer.start(1500)

    def tick(self):
        events = self.server.events
        if len(events) != self.seen:
            self.seen = len(events)
            self["events"].setText("\n".join(events[-4:]))

    def stop(self):
        self.timer.stop()
        self.server.stop()

    def finish(self):
        self.close(bool(self.server.events))
