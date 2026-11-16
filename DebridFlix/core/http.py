"""Tiny stdlib HTTP helper (no third-party modules needed on the box)."""
import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "DebridFlix/0.1 (Enigma2)"


class ApiError(Exception):
    def __init__(self, message, status=None, payload=None):
        Exception.__init__(self, message)
        self.status = status
        self.payload = payload


def request(method, url, params=None, data=None, json_body=None, headers=None, timeout=25, raw=False):
    """Perform a request. Returns parsed JSON (or bytes when raw=True, None on empty body)."""
    if params:
        clean = dict((k, v) for k, v in params.items() if v is not None)
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif data is not None:
        clean = dict((k, v) for k, v in data.items() if v is not None)
        body = urllib.parse.urlencode(clean, doseq=True).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
    except urllib.error.HTTPError as err:
        content = err.read()
        payload = None
        try:
            payload = json.loads(content.decode("utf-8", "replace"))
        except ValueError:
            pass
        raise ApiError("HTTP %s from %s" % (err.code, urllib.parse.urlsplit(url).netloc), err.code, payload)
    except (urllib.error.URLError, OSError) as err:
        raise ApiError("Network error: %s" % getattr(err, "reason", err))
    if raw:
        return content
    if not content.strip():
        return None
    try:
        return json.loads(content.decode("utf-8", "replace"))
    except ValueError:
        raise ApiError("Invalid JSON from %s" % urllib.parse.urlsplit(url).netloc)
