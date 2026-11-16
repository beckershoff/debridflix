"""Shared UI helpers: background jobs and skin colours (FHD, 1920x1080)."""
from twisted.internet import threads

from Screens.MessageBox import MessageBox

BG = "#00141414"
PANEL = "#00262626"
RED = "#00e50914"
GREY = "#00aaaaaa"
WHITE = "#00ffffff"


class Async(object):
    """Run blocking work in a thread; callbacks fire on the main loop and only while the screen is open."""

    def initAsync(self):
        self._alive = True
        self.onClose.append(self._asyncClosed)

    def _asyncClosed(self):
        self._alive = False

    def bg(self, func, ok=None, err=None):
        def good(result):
            if self._alive and ok:
                ok(result)

        def bad(failure):
            if self._alive:
                (err or self.showError)(failure.value)

        threads.deferToThread(func).addCallbacks(good, bad)

    def showError(self, error):
        self.session.open(MessageBox, str(error) or error.__class__.__name__, MessageBox.TYPE_ERROR, timeout=10)

    def showInfo(self, text, timeout=6):
        self.session.open(MessageBox, text, MessageBox.TYPE_INFO, timeout=timeout)


def label(name, x, y, w, h, size, color=WHITE, extra=""):
    return '<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="%s" backgroundColor="%s" transparent="1" %s/>\n' % (
        name, x, y, w, h, size, color, BG, extra)


def screen(name, body, title="DebridFlix"):
    return '<screen name="%s" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="%s" title="%s">\n%s</screen>' % (
        name, BG, title, body)


def set_pixmap(widget, path):
    """Show a JPEG/PNG file in a Pixmap widget. Returns True when it worked."""
    from Tools.LoadPixmap import LoadPixmap
    if not path or widget.instance is None:
        return False
    try:
        ptr = LoadPixmap(path)
    except Exception:
        ptr = None
    if not ptr:
        return False
    try:
        widget.instance.setScale(1)
    except Exception:
        pass
    widget.instance.setPixmap(ptr)
    widget.show()
    return True
