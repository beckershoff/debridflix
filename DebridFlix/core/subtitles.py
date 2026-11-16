"""OpenSubtitles.com download plus a small SRT parser for the on-screen overlay."""
import bisect
import os
import re

from . import http

BASE = "https://api.opensubtitles.com/api/v1"
AGENT = "DebridFlix v0.1.0"


class SubtitleError(Exception):
    pass


class OpenSubtitles(object):
    def __init__(self, settings, log=None):
        self.s = settings
        self.log = log or (lambda *a: None)
        self._token = None

    def configured(self):
        return bool(self.s.get("os_api_key"))

    def _headers(self, login=False):
        headers = {"Api-Key": self.s.get("os_api_key"), "User-Agent": AGENT}
        if login and self.s.get("os_username"):
            if not self._token:
                try:
                    reply = http.request("POST", BASE + "/login", headers=headers, json_body={
                        "username": self.s.get("os_username"), "password": self.s.get("os_password")})
                    self._token = (reply or {}).get("token")
                except http.ApiError:
                    self._token = None
            if self._token:
                headers["Authorization"] = "Bearer %s" % self._token
        return headers

    def search(self, imdb, season=None, episode=None, languages=None):
        """Returns [{'file_id', 'language', 'release', 'downloads'}], best first."""
        if not self.configured():
            raise SubtitleError("OpenSubtitles API key is not set")
        number = str(imdb or "").replace("tt", "").lstrip("0")
        if not number:
            raise SubtitleError("No IMDb id for this title")
        params = {"languages": ",".join(sorted(languages or self.s.list("subtitle_languages"))), "order_by": "download_count"}
        if season is not None and episode is not None:
            params.update({"parent_imdb_id": number, "season_number": season, "episode_number": episode})
        else:
            params["imdb_id"] = number
        try:
            reply = http.request("GET", BASE + "/subtitles", params=params, headers=self._headers())
        except http.ApiError as err:
            raise SubtitleError("OpenSubtitles: %s" % err)
        self.log("opensubtitles", "search", reply)
        out = []
        for entry in (reply or {}).get("data") or []:
            attr = entry.get("attributes") or {}
            files = attr.get("files") or []
            if files and files[0].get("file_id"):
                out.append({"file_id": files[0]["file_id"], "language": attr.get("language") or "?",
                            "release": attr.get("release") or files[0].get("file_name") or "",
                            "downloads": attr.get("download_count") or 0})
        wanted = self.s.list("subtitle_languages")
        out.sort(key=lambda e: (wanted.index(e["language"]) if e["language"] in wanted else 99, -e["downloads"]))
        return out

    def download(self, file_id, dest):
        try:
            reply = http.request("POST", BASE + "/download", headers=self._headers(login=True), json_body={"file_id": file_id, "sub_format": "srt"})
            if not reply or not reply.get("link"):
                raise SubtitleError("OpenSubtitles: %s" % ((reply or {}).get("message") or "no download link"))
            content = http.request("GET", reply["link"], raw=True, headers={"User-Agent": AGENT})
        except http.ApiError as err:
            message = (err.payload or {}).get("message") if isinstance(err.payload, dict) else None
            raise SubtitleError("OpenSubtitles: %s" % (message or err))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(content)
        return dest


_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_TAG = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def _ms(h, m, s, frac):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int((frac + "000")[:3])


def decode(content):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", "replace")


def parse_srt(text):
    """Returns a sorted list of (start_ms, end_ms, text)."""
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = block.splitlines()
        for index, line in enumerate(lines):
            match = _TIME.search(line)
            if match:
                g = match.groups()
                body = "\n".join(_TAG.sub("", l).strip() for l in lines[index + 1:] if l.strip())
                if body:
                    cues.append((_ms(*g[0:4]), _ms(*g[4:8]), body))
                break
    cues.sort()
    return cues


class SubtitleTrack(object):
    def __init__(self, cues):
        self.cues = cues
        self.starts = [c[0] for c in cues]
        self.delay_ms = 0

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as fh:
            return cls(parse_srt(decode(fh.read())))

    def text_at(self, position_ms):
        position_ms -= self.delay_ms
        index = bisect.bisect_right(self.starts, position_ms) - 1
        if index >= 0:
            start, end, text = self.cues[index]
            if start <= position_ms <= end:
                return text
        return ""
