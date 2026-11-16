"""Player: the box's own MoviePlayer plus an SRT overlay and Trakt 'watched' sync."""
from enigma import eTimer
from twisted.internet import threads

from Components.ActionMap import ActionMap
from Components.Label import Label
from Screens.ChoiceBox import ChoiceBox
from Screens.InfoBar import MoviePlayer
from Screens.Screen import Screen

from ..core.i18n import lang_code, pick_track
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
        self.autoDone = False
        self.audioTimer = eTimer()
        self.audioTimer.callback.append(self.chooseAudio)
        self.audioTimer.start(1000)
        self.onClose.append(self.cleanup)

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
                self.autoSubtitles()
            return
        self.audioTimer.stop()
        self.autoSubtitles()  # the file's tracks are known now, embedded subtitles too
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
    def embeddedSubtitles(self):
        """Subtitle tracks inside the video file: [(entry, language code)]. Shown by Enigma2 itself."""
        try:
            service = self.session.nav.getCurrentService()
            subtitle = service and service.subtitle()
            entries = (subtitle and subtitle.getSubtitleList()) or []
        except Exception:
            return []
        return [(entry, lang_code(entry[4] if len(entry) > 4 else "")) for entry in entries]

    def subtitlesOff(self):
        self.track = None
        self.subTimer.stop()
        self.overlay.hide()
        if getattr(self, "selected_subtitle", None):
            self.enableSubtitle(None)

    def useEmbedded(self, entry):
        self.subtitlesOff()
        self.enableSubtitle(entry)

    def subtitleMenu(self):
        choices = []
        for index, (entry, code) in enumerate(self.embeddedSubtitles()):
            choices.append((_("In the video: %s") % (code.upper() or (_("track %d") % (index + 1))), ("embedded", entry)))
        choices.append((_("Search subtitles (%s)") % self.app.s.get("subtitle_languages"), ("search", None)))
        if self.track or getattr(self, "selected_subtitle", None):
            choices.append((_("Subtitles off"), ("off", None)))
        if self.track:
            choices += [(_("Show subtitles 0.5 s later"), ("later", None)), (_("Show subtitles 0.5 s earlier"), ("earlier", None))]
        self.session.openWithCallback(self.subtitleMenuChosen, ChoiceBox, title=_("Subtitles"), list=choices)

    def subtitleMenuChosen(self, choice):
        if not choice:
            return
        action, value = choice[1]
        if action == "embedded":
            self.useEmbedded(value)
        elif action == "search":
            self.searchSubtitles()
        elif action == "off":
            self.subtitlesOff()
        elif self.track:
            self.track.delay_ms += 500 if action == "later" else -500

    def autoSubtitles(self):
        """'Load best subtitle automatically': first language in subtitle_languages that exists, embedded or online."""
        if not self.app.s.get("subtitle_auto") or self.autoDone:
            return
        self.autoDone = True
        wanted = self.app.s.list("subtitle_languages")
        rank = lambda code: wanted.index(code) if code in wanted else len(wanted)
        embedded = sorted(((rank(code), entry) for entry, code in self.embeddedSubtitles() if code in wanted), key=lambda x: x[0])
        if embedded and embedded[0][0] == 0:
            self.useEmbedded(embedded[0][1])  # best possible: first language, no download
            return
        self.searchSubtitles(auto=True, beat=embedded[0] if embedded else None)

    def searchSubtitles(self, auto=False, beat=None):
        """beat: (rank, embedded entry) to fall back on when online has nothing in a better language."""
        def search():
            item = self.item
            if not item.get("imdb"):
                item["imdb"] = self.app.tmdb.details(item["kind"], item["tmdb"])[0].get("imdb")
            return self.app.subs.search(item.get("imdb"), self.season, self.episode)

        def found(results):
            wanted = self.app.s.list("subtitle_languages")
            if auto:
                best = results[0] if results else None
                online_rank = wanted.index(best["language"]) if best and best["language"] in wanted else len(wanted)
                if beat and beat[0] <= online_rank:
                    self.useEmbedded(beat[1])
                elif best:
                    self.loadSubtitle(best)
            elif not results:
                self.showInfo(_("No subtitles found."))
            else:
                label = lambda r: (_("%s   %s   (%s downloads)") % (r["language"].upper(), r["release"][:60], r["downloads"])
                                   if r.get("source") != "stremio" else "%s   %s   (Stremio)" % (r["language"].upper(), r["release"][:60]))
                choices = [(label(r), r) for r in results[:40]]
                self.session.openWithCallback(lambda c: c and self.loadSubtitle(c[1]), ChoiceBox, title=_("Choose a subtitle"), list=choices)

        self.bg(search, found, (lambda e: beat and self.useEmbedded(beat[1])) if auto else None)

    def loadSubtitle(self, result):
        def download():
            return SubtitleTrack.from_file(self.app.subs.download(result, self.app.subtitle_path()))

        def ready(track):
            self.subtitlesOff()  # one subtitle source at a time
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
