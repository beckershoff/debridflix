# DebridFlix - handoff notes

Enigma2 plugin for a satellite box running **OpenATV 7.6 (Python 3.13), FHD skin (1920x1080)**.
Netflix-style poster browser that finds torrents via Orion, shows which are cached on the user's
debrid services, plays them with the box's MoviePlayer, and can start a cloud download when a
stream is not cached. Version 0.2.0. Standard library only - no pip packages on the box.

## Status

- Written entirely off-box. **Never run on a real receiver yet.** First job: install, start,
  read the crash log, fix.
- 16 tests pass: `python3 -m unittest tests.test_core tests.test_ui_smoke`
  - `test_core`: service logic against a fake `http.request`.
  - `test_ui_smoke`: screens against stand-in Enigma2 classes (checks our logic, not Enigma2).
    The pairing test needs `opencv-python` + `numpy` to decode the QR code.
- Build: `python3 build.py` -> `dist/enigma2-plugin-extensions-debridflix_<ver>_all.ipk`
  (version comes from `DebridFlix/core/__init__.py`).

## Deploy / debug loop

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
