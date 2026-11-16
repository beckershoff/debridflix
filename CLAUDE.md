# DebridFlix - handoff notes

Enigma2 plugin for a satellite box running **OpenATV 7.6 (Python 3.13), FHD skin (1920x1080)**.
Netflix-style poster browser that finds torrents via Orion, shows which are cached on the user's
debrid services, plays them with the box's MoviePlayer, and can start a cloud download when a
stream is not cached. Version 0.3.0. Standard library only - no pip packages on the box.

## Status

- Installed and running on a real box (sf8008, MyMetrixLite skin). Home, setup and
  pairing screens verified by screenshot (2026-11-16); browsing/playback not yet tested (no keys entered).
- **Every `<screen>` needs `resolution="1920,1080"`**, otherwise OpenATV scales the skin 1.5x as if it were 720p
  (`common.screen()` and the player overlay set it).
- First start with setup missing opens the pairing (QR) screen automatically.
- 30 tests pass: `python3 -m unittest tests.test_core tests.test_ui_smoke`
  - `test_core`: service logic against a fake `http.request`.
  - `test_ui_smoke`: screens against stand-in Enigma2 classes (checks our logic, not Enigma2).
    The pairing test needs `opencv-python` + `numpy` to decode the QR code.
- Build: `python3 build.py` -> `dist/enigma2-plugin-extensions-debridflix_<ver>_all.ipk`
  (version comes from `DebridFlix/core/__init__.py`).

## Deploy / debug loop

OpenWebif drives the box remotely: `curl http://BOX/api/remotecontrol?command=N`
(OK 352, EXIT 174, up 103, down 108, left 105, right 106, RED 398, GREEN 399, YELLOW 400, BLUE 401)
and `curl -o shot.jpg 'http://BOX/grab?format=jpg&mode=osd'` for a screenshot. From live TV: BLUE -> 7x down -> OK -> OK
opens the plugin browser; DebridFlix is the first entry.

    scp dist/*.ipk root@BOX:/tmp/ && ssh root@BOX 'opkg install --force-reinstall /tmp/enigma2-plugin-extensions-debridflix_*.ipk && init 4 && init 3'
    # faster while iterating:
    rsync -a --delete --exclude __pycache__ DebridFlix/ root@BOX:/usr/lib/enigma2/python/Plugins/Extensions/DebridFlix/ && ssh root@BOX 'init 4 && init 3'

- Enigma2 crash logs: `/home/root/logs/` (or `/media/hdd/logs/`), live: `journalctl -f` / `/tmp/enigma2.log` depending on image settings.
- Plugin debug log (enable "Debug log" in setup, or `"debug": true` in the JSON): `/tmp/debridflix.log` - every API request/reply.
- Settings: `/etc/enigma2/debridflix.json` (chmod 600). Cache: `/tmp/debridflix/`.

## Layout

    DebridFlix/
      plugin.py            PluginDescriptor (plugin menu + extensions menu), icon plugin.png
      plugin.png logo.png  100x40 menu icon, 200x200 logo (home screen + pairing page)
      core/                NO Enigma2 imports - testable anywhere
        http.py            urllib wrapper; everything calls http.request (tests patch it)
        settings.py        JSON settings, DEFAULTS, SETUP_FIELDS (drives TV setup + phone page)
        models.py          Stream, parse_orion_stream, StreamFilter, pick_file (SxxEyy matching)
        orion.py           Orion search (mode=stream action=retrieve) + debrid lookup
        debrid.py          Premiumize, RealDebrid, TorBox, AllDebrid, DebridLink
                           interface: configured / check_cached / add / resolve / account
                           resolve() raises NotReady if not downloaded (torrent stays queued)
        tmdb.py trakt.py subtitles.py   catalogue, watchlist+history, OpenSubtitles + SRT parser
        service.py         App facade used by the UI (rows, find_streams, play, send, posters)
        qr.py              pure-Python QR encoder (byte mode, level L, v1-5) + PNG writer
        pairing.py         PairingServer: http.server page on port 8765 behind a random token
      ui/                  Enigma2 screens; skins are generated strings in each file
        common.py          Async mixin (deferToThread, callbacks only while screen is open)
        home.py            hero + 2 poster rows x 9, selection frame, search, watchlist toggle
        detail.py          poster, seasons -> episodes, watchlist
        streams.py         MultiContent list; RED cached / GREEN resolution / YELLOW audio / BLUE language; MENU send
        player.py          MoviePlayer subclass, SRT overlay (BLUE), Trakt watched at >=80%
        setup.py           ConfigListScreen + DeviceAuthScreen (RD / AllDebrid / Trakt codes)
        pair.py            QR screen for phone pairing
    tests/  build.py  CLAUDE.md

## Decisions already made (with the user)

- Watchlist sync: Trakt. Services: Orion + Premiumize, Real-Debrid, TorBox, AllDebrid, Debrid-Link.
  Offcloud / EasyDebrid not included.
- Subtitles: OpenSubtitles.com REST API, rendered by our own overlay (no SubsSupport dependency).
- User supplies own keys: TMDB v3, Orion app key + user key, Trakt client id/secret, OpenSubtitles key.
- Real-Debrid device flow uses RD's public open-source client id `X245A4XAIBGVM`.
- Phone pairing: plain HTTP on LAN, only while the pairing screen is open, random token per open.
  Secret fields are never echoed back; empty field = keep value.
- Cached status: Premiumize + TorBox asked directly. RD / AllDebrid / Debrid-Link removed their
  cache-check endpoints (late 2024), so their flags come from Orion (`stream.access.<service>`),
  optionally refreshed with Orion `mode=debrid action=lookup` ("Orion fresh cache lookup").
- Without Orion keys (Setup "Stream search" = auto) streams come from the keyless Torrentio API
  (`core/torrentio.py`). Cache state unknown for RD/AD/DL there -> `None` = "Maybe", Play tries them.
- Device limits (`core/device.py`): max resolution from the TV EDID (`/proc/stb/video/videomode_preferred`), no AV1 /
  DV-only on HiSilicon, max est. bitrate (default 15 Mbit/s: user box is on Wi-Fi, ~17 measured). Applied in
  `find_streams` before Torrentio balancing. User box: Hi3798MV200 + Full HD TV.
- i18n: `core/i18n.py` + `i18n_de.py` (EN/DE). `ui_language` auto = Enigma2 `config.osd.language` (user's box: German).
  Every user string in `_()`; `test_german_translation_complete` enforces DE coverage + matching %-specs.
  Translate module-level tables at render time, never at import. Rows use flags (`watchlist`, `search`), not titles.
- Audio pref `en,de` (sort + player picks track via `pick_track`), subtitles `de,en`. "DL" tag = German+English,
  but not "WEB-DL". Verified on box: 6-track file (RU/UK/EN) switched to EN.
- Subtitles: `core/subtitles.Subtitles` = OpenSubtitles.com (key) + keyless backup `StremioSubtitles`
  (opensubtitles-v3.strem.io, used when no key / error / nothing in wanted langs; fewer DE subs). Player also lists
  embedded tracks via MoviePlayer `enableSubtitle()` (InfoBarSubtitleSupport). Podnapisi offline since 2026,
  SubDL/SubSource need keys. Embedded tracks not yet verified on the box (needs playback).
- Settings file stores only non-default values; `LEGACY_DEFAULTS` drops old written-out defaults on load.
- Pairing test needs opencv: `python3 -m venv /tmp/v && /tmp/v/bin/pip install opencv-python-headless numpy`.
- Playback is HTTPS-only from the debrid service (`App.play` refuses anything else): the box never does P2P.
- GUI may run at 1280x720: skins scale (resolution=), but runtime `move()`, MultiContent, setFont, setItemHeight
  do not -> use `ui.common.point()` / `scale()`.
- Enigma2 exec()s non-bound-method entries in `onLayoutFinish`: never append a lambda there.
- Trakt apps made since Oct 2026 have no client secret; the device flow sends it only if set.
- Home "cached only" = one Orion search per title (first 18 per row, 12 h disk cache).

## Known risks - check these first on the box

1. **Orion field names are from memory** (docs are behind login at panel.orionoid.com > Developers > API Docs):
   request params `idimdb`, `numberseason`, `numberepisode`, `limitcount`, `streamtype`; reply
   `data.streams[].{links, file.hash/name/size, video.quality, audio.channels/languages, stream.seeds, access.*}`;
   "no results" detected via `result.type` containing "missing". `Orion.lookup()` reply shape is a guess,
   parsed defensively. Verify with the debug log.
2. **Enigma2 API assumptions** (untested): `ConfigListScreen.__init__(list, session=)`, MoviePlayer overrides
   (`leavePlayer`, `leavePlayerOnExit`, `doEofInternal`, `showMovies`), `LoadPixmap` on JPEG posters +
   `ePixmap.setScale(1)`, `font`/`itemHeight` skin attributes on MenuList, transparent overlay screen
   (`backgroundColor="#ff000000"`), `alphatest="blend"` for the logo.
3. Debrid reply shapes written from API knowledge, not live calls: AllDebrid `/v4/magnet/files`,
   TorBox `mylist` / `requestdl`, Debrid-Link `/seedbox/add`, RD `selectFiles` flow.
4. Playback uses service type 4097 (gstreamer); 5002 (exteplayer3) selectable in setup if HTTPS streams stall.
5. QR uses fixed mask 0 (decodes fine with OpenCV); menu icon is only 40 px high.
6. Each "play" on RD adds a torrent to the cloud list; nothing cleans those up.

## Ideas not done

Continue-watching / resume points, Trakt scrobble progress, backdrop art in the hero, Orion
device-code login, HTTPS or PIN on the pairing page, OpenATV feed packaging, localisation (NL/DE).
