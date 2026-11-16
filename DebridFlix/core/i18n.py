"""Interface language (English / German) and language-code helpers.

Strings are written in English in the code and wrapped in _(); German lives in i18n_de.DE.
tests/test_core checks that every _("...") literal in the package has a German entry.
"""
import re

LANGUAGES = ("en", "de")
_current = "en"


def set_language(code):
    global _current
    _current = code if code in LANGUAGES else "en"


def language():
    return _current


def _(text):
    if _current == "de":
        from .i18n_de import DE
        return DE.get(text, text)
    return text


def resolve(setting, system_locale=""):
    """setting: 'auto' | 'en' | 'de'; system_locale: Enigma2's OSD language, e.g. 'de_DE'."""
    if setting in LANGUAGES:
        return setting
    code = str(system_locale or "").lower()[:2]
    return code if code in LANGUAGES else "en"


def tmdb_locale(setting):
    """TMDB metadata language; 'auto' follows the interface language."""
    if setting and setting != "auto":
        return setting
    return "de-DE" if _current == "de" else "en-US"


# ISO 639-1/-2 and English names -> 2-letter code (audio tracks report 'eng', 'ger', 'deu', 'English', ...)
CODES = {
    "en": "en", "eng": "en", "english": "en", "englisch": "en",
    "de": "de", "ger": "de", "deu": "de", "german": "de", "deutsch": "de",
    "nl": "nl", "nld": "nl", "dut": "nl", "dutch": "nl", "nederlands": "nl",
    "fr": "fr", "fre": "fr", "fra": "fr", "french": "fr", "es": "es", "spa": "es", "spanish": "es",
    "it": "it", "ita": "it", "italian": "it", "tr": "tr", "tur": "tr", "turkish": "tr",
    "sv": "sv", "swe": "sv", "swedish": "sv", "ru": "ru", "rus": "ru", "russian": "ru",
    "pt": "pt", "por": "pt", "portuguese": "pt", "pl": "pl", "pol": "pl", "polish": "pl",
    "ja": "ja", "jpn": "ja", "japanese": "ja", "ko": "ko", "kor": "ko", "korean": "ko",
}


def lang_code(text):
    """'eng' / 'English' / 'en-US' / 'ger' -> 'en' / 'de'; '' when unknown."""
    t = str(text or "").strip().lower()
    if t in CODES:
        return CODES[t]
    head = re.split(r"[^a-z]", t)[0] if t else ""
    return CODES.get(head, "")


# Release-name tags. "DL" = German scene tag for German + original (English) audio.
_TAGS = (
    (re.compile(r"(?<![a-z0-9])(german|deutsch|ger)(?![a-z0-9])", re.I), ("de",)),
    (re.compile(r"(?<!web[ ._-])(?<![a-z0-9])dl(?![a-z0-9])", re.I), ("de", "en")),  # German scene tag; not "WEB-DL"
    (re.compile(r"(?<![a-z0-9])dual(?![a-z0-9])", re.I), ("en",)),  # original + English dub (e.g. anime)
    (re.compile(r"(?<![a-z0-9])(english|eng)(?![a-z0-9])", re.I), ("en",)),
    (re.compile(r"(?<![a-z0-9])(dutch|nl)(?![a-z0-9])", re.I), ("nl",)),
    (re.compile(r"(?<![a-z0-9])(french|vff|vf|truefrench)(?![a-z0-9])", re.I), ("fr",)),
    (re.compile(r"(?<![a-z0-9])(ita|italian)(?![a-z0-9])", re.I), ("it",)),
    (re.compile(r"(?<![a-z0-9])(spanish|castellano|latino)(?![a-z0-9])", re.I), ("es",)),
)


def name_languages(name):
    """Audio languages a release name announces, e.g. 'Movie.2020.German.DL.1080p' -> ['de', 'en']."""
    out = []
    for pattern, codes in _TAGS:
        if pattern.search(name or ""):
            for c in codes:
                if c not in out:
                    out.append(c)
    return out


def audio_score(languages, preferred):
    """Lower is better. Untagged releases are almost always English-only, so they count as ['en']."""
    langs = languages or ["en"]
    for index, code in enumerate(preferred):
        if code in langs:
            return index
    return len(preferred)


def pick_track(track_languages, preferred):
    """Index of the audio track to select: the first preferred language that exists, else None (keep the default)."""
    codes = [lang_code(t) for t in track_languages]
    for wanted in preferred:
        if wanted in codes:
            return codes.index(wanted)
    return None
