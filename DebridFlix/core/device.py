"""What this box + TV can actually play, so the stream list can hide what would stutter or not decode.

Reads /proc/stb (Enigma2 boxes); off-box every check returns "no limit".
"""
import re

from .models import QUALITY_RANK

PREFERRED = "/proc/stb/video/videomode_preferred"   # modes the TV reports via HDMI EDID
CHOICES = "/proc/stb/video/videomode_choices"       # modes the box can output
CHIPSET = "/proc/stb/info/chipset"

# HiSilicon chips used in OpenATV boxes: HEVC 10-bit + HDR10 yes, AV1 and Dolby Vision no
NO_AV1 = ("3798mv200", "3798mv300", "3798cv200", "3716mv430", "bcm7252", "bcm7251", "bcm7444", "bcm7445")
NO_DV = NO_AV1

DV = re.compile(r"(?<![a-z0-9])(dv|dovi|dolby[ ._-]?vision)(?![a-z0-9])", re.I)
HDR10 = re.compile(r"(?<![a-z0-9])(hdr|hdr10|hdr10\+|hdr10plus)(?![a-z0-9])", re.I)
AV1 = re.compile(r"(?<![a-z0-9])av1(?![a-z0-9])", re.I)
EPISODE = re.compile(r"s\d{1,2}[ ._-]?e\d{1,3}|\d{1,2}x\d{2}", re.I)


def _read(path):
    try:
        with open(path) as fh:
            return fh.read().strip().lower()
    except (IOError, OSError):
        return ""


def _max_quality(modes):
    best = ""
    for mode in modes.split():
        m = re.match(r"(\d{3,4})[pi]", mode)
        if not m:
            continue
        lines = int(m.group(1))
        q = "hd4k" if lines >= 2160 else "hd1080" if lines >= 1080 else "hd720" if lines >= 720 else "sd"
        if QUALITY_RANK[q] > QUALITY_RANK.get(best, 0):
            best = q
    return best


def detect():
    """{'max_quality': 'hd1080' | '' (unknown), 'av1': bool, 'dv': bool, 'chipset': str}"""
    chipset = _read(CHIPSET)
    tv, box = _max_quality(_read(PREFERRED)), _max_quality(_read(CHOICES))
    if tv and box:
        best = tv if QUALITY_RANK[tv] <= QUALITY_RANK[box] else box
    else:
        best = tv or box
    return {"max_quality": best, "av1": chipset not in NO_AV1, "dv": chipset not in NO_DV, "chipset": chipset}


class DeviceLimits(object):
    """Built from settings + detect(). allows() -> (bool, reason)."""

    def __init__(self, max_quality="", max_mbps=0, av1=True, dv=True):
        self.max_quality = max_quality      # '' = no limit
        self.max_mbps = float(max_mbps or 0)  # 0 = no limit
        self.av1 = av1
        self.dv = dv

    @classmethod
    def from_settings(cls, settings, detected=None):
        if not settings.get("hide_unplayable"):
            return cls()
        detected = detected if detected is not None else detect()
        quality = settings.get("max_resolution") or "auto"
        if quality == "auto":
            quality = detected.get("max_quality") or ""
        elif quality == "any":
            quality = ""
        mbps = settings.get("max_bitrate") or "any"
        return cls(quality, 0 if mbps == "any" else float(mbps), detected.get("av1", True), detected.get("dv", True))

    @staticmethod
    def mbps(stream, runtime_min, is_show=False):
        """Estimated average bitrate, or 0 when it cannot be told (season pack, no size)."""
        if not stream.size:
            return 0
        if is_show and not EPISODE.search(stream.name or ""):
            return 0  # season pack: size covers many episodes
        minutes = float(runtime_min or (50 if is_show else 110))
        return float(stream.size) * 8 / (minutes * 60) / 1e6

    def allows(self, stream, runtime_min=None, is_show=False):
        text = " ".join((stream.name or "", stream.video_codec or ""))
        if self.max_quality and stream.rank > QUALITY_RANK.get(self.max_quality, 99):
            return False, "resolution"
        if not self.av1 and (AV1.search(text) or (stream.video_codec or "").lower() == "av1"):
            return False, "AV1"
        if not self.dv and DV.search(text) and not HDR10.search(text):
            return False, "Dolby Vision"  # DV-only (profile 5) shows wrong colours; DV+HDR10 hybrids fall back fine
        if self.max_mbps:
            rate = self.mbps(stream, runtime_min, is_show)
            if rate > self.max_mbps:
                return False, "bitrate"
        return True, ""
