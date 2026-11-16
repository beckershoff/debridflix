"""Phone pairing: a small web page served by the box while the pairing screen is open.

The TV shows a QR code with http://<box-ip>:<port>/<random token>/ . The page lets you paste
keys and link Real-Debrid / AllDebrid / Trakt with their device codes. LAN only, plain HTTP,
and the token changes every time the screen is opened.
"""
import html
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .i18n import _, language
from .settings import CHOICE_LABELS, SETUP_FIELDS

SECRET_MARKERS = ("_key", "_token", "_secret", "_password")
LINKABLE = (("realdebrid", "Real-Debrid"), ("alldebrid", "AllDebrid"), ("trakt", "Trakt"))
HELP = {
    "tmdb_key": "themoviedb.org > Settings > API",
    "orion_app_key": "panel.orionoid.com > Developers",
    "orion_user_key": "panel.orionoid.com > Account",
    "pm_key": "premiumize.me/account",
    "rd_token": "or use the Link button below",
    "tb_key": "torbox.app/settings",
    "ad_key": "or use the Link button below",
    "dl_key": "debrid-link.com/webapp/apikey",
    "trakt_client_id": "trakt.tv/oauth/applications - save, then Link",
    "os_api_key": "opensubtitles.com > API consumers",
}

PAGE = """<!doctype html><html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(t_title)s</title><style>
body{background:#141414;color:#eee;font-family:sans-serif;margin:0;padding:16px;max-width:560px;margin:auto}
h1{color:#e50914;font-size:24px;display:flex;align-items:center;gap:10px}h1 img{width:48px;height:48px}
h2{font-size:17px;margin:26px 0 8px;border-bottom:1px solid #333;padding-bottom:4px}
label{display:block;margin:12px 0 4px;font-size:14px}small{color:#888}
input,select{width:100%%;box-sizing:border-box;padding:11px;border-radius:6px;border:1px solid #444;background:#222;color:#eee;font-size:16px}
button{width:100%%;padding:13px;margin-top:12px;border:0;border-radius:6px;background:#e50914;color:#fff;font-size:16px;font-weight:bold}
button.alt{background:#333}.box{background:#222;border-radius:6px;padding:12px;margin-top:8px;font-size:15px}
.code{font-size:26px;letter-spacing:3px;font-weight:bold;color:#46d369}.ok{color:#46d369}.err{color:#ff6b6b}a{color:#6cb6ff}
</style></head><body><h1><img src="logo.png" alt="">DebridFlix</h1>
%(notice)s
<h2>%(t_links)s</h2>
%(links)s
<form method="post" action="save"><h2>%(t_keys)s</h2>
<small>%(t_keep)s</small>
%(fields)s
<button type="submit">%(t_save)s</button></form>
<script>
var T=%(js)s;
function render(s){for(var k in s){var e=document.getElementById('st_'+k),v=s[k];if(!e)continue;
if(v.status=='waiting')e.innerHTML=T.open+' <a target="_blank" href="'+v.url+'">'+v.url+'</a> '+T.enter+'<div class="code">'+v.code+'</div>'+T.wait;
else if(v.status=='linked')e.innerHTML='<span class="ok">'+T.linked+'</span>';
else if(v.status=='error')e.innerHTML='<span class="err">'+v.message+'</span>';
e.style.display=v.status?'block':'none';}}
function poll(){fetch('status').then(function(r){return r.json()}).then(render).catch(function(){})}
function link(k){fetch('link/'+k,{method:'POST'}).then(poll)}
setInterval(poll,3000);poll();
</script></body></html>"""


def local_ip():
    """The box's LAN address (no packet is actually sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def is_secret(key):
    return key.endswith(SECRET_MARKERS)


class PairingServer(object):
    def __init__(self, app, port=8765, logo_path=None):
        self.app = app
        self.port = port
        self.logo_path = logo_path
        self.token = secrets.token_urlsafe(6)
        self.links = {}    # service -> {"status", "url", "code", "message"}
        self.events = []   # human-readable lines for the TV screen
        self.httpd = None

    # --- lifecycle ------------------------------------------------------
    def start(self):
        handler = self._handler()
        last = None
        for port in ([self.port] if self.port == 0 else range(self.port, self.port + 6)):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
                break
            except OSError as err:
                last = err
        if not self.httpd:
            raise last
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        thread = threading.Thread(target=self.httpd.serve_forever, name="debridflix-pairing")
        thread.daemon = True
        thread.start()
        return self.url()

    def stop(self):
        httpd, self.httpd = self.httpd, None
        if httpd:
            threading.Thread(target=lambda: (httpd.shutdown(), httpd.server_close())).start()

    def url(self, host=None):
        return "http://%s:%d/%s/" % (host or local_ip(), self.port, self.token)

    # --- actions --------------------------------------------------------
    def save(self, form):
        values = {}
        for _label, key, kind, choices in SETUP_FIELDS:
            if key not in form:
                continue
            value = form[key].strip()
            if kind == "bool":
                values[key] = value == "yes"
            elif kind == "choice":
                if value in choices:
                    values[key] = value
            elif value or not is_secret(key):
                values[key] = value
        self.app.s.update(values)
        self.events.append(_("Settings saved from the phone"))

    def link(self, service):
        names = dict(LINKABLE)
        if service not in names:
            return
        target = self.app.trakt if service == "trakt" else self.app.provider(service)
        try:
            state = target.auth_start()
        except Exception as err:
            self.links[service] = {"status": "error", "message": str(err)}
            return
        url = state["url"]
        if service == "trakt":
            url = url.rstrip("/") + "/" + state["code"]
        self.links[service] = {"status": "waiting", "url": url, "code": state["code"]}

        def wait():
            deadline = time.time() + state.get("expires", 600)
            while self.httpd and time.time() < deadline:
                time.sleep(max(2, int(state.get("interval", 5))))
                try:
                    if target.auth_poll(state):
                        self.links[service] = {"status": "linked"}
                        self.events.append(_("%s linked") % names[service])
                        return
                except Exception as err:
                    self.links[service] = {"status": "error", "message": str(err)}
                    return
            self.links[service] = {"status": "error", "message": _("The code expired. Try again.")}

        thread = threading.Thread(target=wait)
        thread.daemon = True
        thread.start()

    # --- page -----------------------------------------------------------
    def page(self, saved=False):
        s = self.app.s
        fields = []
        for text, key, kind, choices in SETUP_FIELDS:
            value = s.get(key)
            hint = _(HELP.get(key, ""))
            head = '<label for="%s">%s%s</label>' % (key, html.escape(_(text)), " <small>- %s</small>" % html.escape(hint) if hint else "")
            if kind == "bool":
                options = "".join('<option value="%s"%s>%s</option>' % (v, " selected" if (v == "yes") == bool(value) else "", label)
                                  for v, label in (("yes", _("yes")), ("no", _("no"))))
                fields.append('%s<select id="%s" name="%s">%s</select>' % (head, key, key, options))
            elif kind == "choice":
                options = "".join('<option value="%s"%s>%s</option>' % (html.escape(c, True), " selected" if c == str(value) else "",
                                                                       html.escape(_(CHOICE_LABELS.get(c, c)))) for c in choices)
                fields.append('%s<select id="%s" name="%s">%s</select>' % (head, key, key, options))
            elif is_secret(key):
                fields.append('%s<input id="%s" name="%s" autocomplete="off" autocapitalize="off" placeholder="%s">' % (
                    head, key, key, _("saved - leave empty to keep") if value else _("not set")))
            else:
                fields.append('%s<input id="%s" name="%s" autocapitalize="off" value="%s">' % (head, key, key, html.escape(str(value or ""), True)))
        linked = {"realdebrid": bool(s.get("rd_token")), "alldebrid": bool(s.get("ad_key")), "trakt": bool(s.get("trakt_access"))}
        links = "".join(
            '<button type="button" class="alt" onclick="link(\'%s\')">%s %s</button><div class="box" id="st_%s" style="display:none"></div>' % (
                key, _("Re-link") if linked[key] else _("Link"), name, key) for key, name in LINKABLE)
        notice = '<div class="box ok">%s</div>' % html.escape(_("Saved. You can close this page or keep going.")) if saved else ""
        js = json.dumps({"open": _("Open"), "enter": _("and enter"), "wait": _("Waiting for approval..."), "linked": _("Linked.")})
        return PAGE % {"fields": "\n".join(fields), "links": links, "notice": notice, "lang": language(), "js": js,
                       "t_title": html.escape(_("DebridFlix pairing")), "t_links": html.escape(_("Link accounts")),
                       "t_keys": html.escape(_("Keys and options")), "t_save": html.escape(_("Save to the box")),
                       "t_keep": html.escape(_('Fields showing "saved" already have a value; leave them empty to keep it.'))}

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _route(self):
                parts = urllib.parse.urlsplit(self.path)
                prefix = "/%s/" % server.token
                if not parts.path.startswith(prefix):
                    return None, parts
                return parts.path[len(prefix):], parts

            def do_GET(self):
                route, parts = self._route()
                if route is None:
                    self._send(404, b"Not found")
                elif route == "":
                    self._send(200, server.page("saved=1" in parts.query).encode("utf-8"))
                elif route == "status":
                    self._send(200, json.dumps(server.links).encode("utf-8"), "application/json")
                elif route == "logo.png" and server.logo_path and os.path.exists(server.logo_path):
                    with open(server.logo_path, "rb") as fh:
                        self._send(200, fh.read(), "image/png")
                else:
                    self._send(404, b"Not found")

            def do_POST(self):
                route, _parts = self._route()
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
                if route is None:
                    self._send(404, b"Not found")
                elif route == "save":
                    form = dict((k, v[0]) for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items())
                    server.save(form)
                    self._send(303, headers={"Location": "/%s/?saved=1" % server.token})
                elif route.startswith("link/"):
                    server.link(route[5:])
                    self._send(200, b"{}", "application/json")
                else:
                    self._send(404, b"Not found")

        return Handler
