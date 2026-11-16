"""Player: the box's own MoviePlayer plus an SRT overlay and Trakt 'watched' sync."""
from enigma import eTimer
from twisted.internet import threads

from Components.ActionMap import ActionMap
from Components.Label import Label
from Screens.ChoiceBox import ChoiceBox
from Screens.InfoBar import MoviePlayer
from Screens.Screen import Screen

from ..core.i18n import pick_track
from ..core.subtitles import SubtitleTrack
from .common import Async
from ..core.i18n import _


class SubtitleOverlay(Screen):
    skin = ('<screen name="DebridFlixSubtitles" position="0,820" size="1920,220" resolution="1920,1080" flags="wfNoBorder" backgroundColor="#ff000000" zPosition="9">\n'
            '<widget name="text" position="60,0" size="1800,220" font="Regular;46" halign="center" valign="bottom" '
            'foregroundColor="#00ffffff" backgroundColor="#ff000000" borderWidth="3" borderColor="#00000000" transparent="1"/>\n'
            '</screen>')

    def __init__(self, session):
        Screen.__init__(self, session)
        self["text"] = Label("")


class DebridFlixPlayer(MoviePlayer, Async):
    def __init__(self, session, service, app, item, season=None, episode=None):
        MoviePlayer.__init__(self, session, service)
        self.skinName = ["MoviePlayer"]
        self.initAsync()
        self.app, self.item, self.season, self.episode = app, item, season, episode
        self.track = None
        self.lastText = None
        self.overlay = session.instantiateDialog(SubtitleOverlay)
        self.subTimer = eTimer()
        self.subTimer.callback.append(self.subtitleTick)
        self["debridflixActions"] = ActionMap(["ColorActions"], {"blue": self.subtitleMenu}, -2)
        self.audioTries = 0
        self.audioTimer = eTimer()
        self.audioTimer.callback.append(self.chooseAudio)
        self.audioTimer.start(1000)
        self.onClose.append(self.cleanup)
        if app.s.get("subtitle_auto") and app.subs.configured():
            self.searchSubtitles(auto=True)

    # --- leaving --------------------------------------------------------
    def position(self):
        service = self.session.nav.getCurrentService()
        seek = service and service.seek()
        if not seek:
            return None, None
        pos, length = seek.getPlayPosition(), seek.getLength()
        return (pos[1] / 90.0 if not pos[0] else None), (length[1] / 90.0 if not length[0] else None)

    def finish(self, watched=False):
        pos, length = self.position()
        if watched or (pos and length and pos / length >= 0.8):
            if self.app.trakt.configured():
                threads.deferToThread(self.app.trakt.mark_watched, self.item, self.season, self.episode).addErrback(lambda f: None)
        self.close()

    def leavePlayer(self):
        self.finish()

    def leavePlayerOnExit(self):
        self.finish()

    def doEofInternal(self, playing):
        self.finish(watched=True)

    def showMovies(self):
        pass

    def cleanup(self):
        self.audioTimer.stop()
        self.subTimer.stop()
        self.overlay.hide()
        self.session.deleteDialog(self.overlay)

    # --- audio ----------------------------------------------------------
    def chooseAudio(self):
        """Switch to the preferred audio language (e.g. English, else German) once the tracks are known."""
        self.audioTries += 1
        service = self.session.nav.getCurrentService()
        audio = service and service.audioTracks()
        count = audio.getNumberOfTracks() if audio else 0
        if count == 0:
            if self.audioTries >= 15:
                self.audioTimer.stop()
            return
        self.audioTimer.stop()
        if count < 2:
            return
        languages = []
        for index in range(count):
            info = audio.getTrackInfo(index)
            languages.append((info.getLanguage() or info.getDescription() or "") if info else "")
        index = pick_track(languages, self.app.s.list("audio_languages"))
        if index is not None and index != audio.getCurrentTrack():
            audio.selectTrack(index)

    # --- subtitles ------------------------------------------------------
    def subtitleMenu(self):
        choices = [(_("Search subtitles (%s)") % self.app.s.get("subtitle_languages"), "search")]
        if self.track:
            choices += [(_("Subtitles off"), "off"), (_("Show subtitles 0.5 s later"), "later"), (_("Show subtitles 0.5 s earlier"), "earlier")]
        self.session.openWithCallback(self.subtitleMenuChosen, ChoiceBox, title=_("Subtitles"), list=choices)

    def subtitleMenuChosen(self, choice):
        if not choice:
            return
        if choice[1] == "search":
            self.searchSubtitles()
        elif choice[1] == "off":
            self.track = None
            self.subTimer.stop()
            self.overlay.hide()
        elif self.track:
            self.track.delay_ms += 500 if choice[1] == "later" else -500

    def searchSubtitles(self, auto=False):
        def search():
            item = self.item
            if not item.get("imdb"):
                item["imdb"] = self.app.tmdb.details(item["kind"], item["tmdb"])[0].get("imdb")
            return self.app.subs.search(item.get("imdb"), self.season, self.episode)

        def found(results):
            if not results:
                if not auto:
                    self.showInfo(_("No subtitles found."))
            elif auto:
                self.loadSubtitle(results[0])
            else:
                choices = [(_("%s   %s   (%s downloads)") % (r["language"].upper(), r["release"][:70], r["downloads"]), r) for r in results[:40]]
                self.session.openWithCallback(lambda c: c and self.loadSubtitle(c[1]), ChoiceBox, title=_("Choose a subtitle"), list=choices)

        self.bg(search, found, (lambda e: None) if auto else None)

    def loadSubtitle(self, result):
        def download():
            return SubtitleTrack.from_file(self.app.subs.download(result["file_id"], self.app.subtitle_path()))

        def ready(track):
            self.track = track
            self.lastText = None
            self.overlay.show()
            self.subTimer.start(200)

        self.bg(download, ready)

    def subtitleTick(self):
        if not self.track:
            return
        pos, _length = self.position()
        text = self.track.text_at(pos) if pos is not None else ""
        if text != self.lastText:
            self.lastText = text
            self.overlay["text"].setText(text)
