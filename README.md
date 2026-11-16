# DebridFlix

A Netflix-style poster browser for Enigma2 satellite receivers (OpenATV 7.6). Browse trending and
popular movies and series from TMDB, find torrents for a title, see at a glance which ones are
already cached on your debrid service, and play them in the box's own media player. Nothing is
downloaded to the box and it never joins a torrent swarm: your debrid service fetches the torrent
on its servers and the box streams the finished file over HTTPS.

- **Catalogue:** TMDB rows (trending, popular, by genre), search, details with seasons and episodes
- **Streams:** [Orion](https://orionoid.com), or the keyless Torrentio index as a fallback
- **Debrid services:** Premiumize, Real-Debrid, TorBox, AllDebrid, Debrid-Link
- **Trakt:** watchlist rows, add/remove with one key, titles marked watched after 80 %
- **Subtitles:** OpenSubtitles.com, rendered by the plugin itself (no extra plugin needed)
- **Phone setup:** scan a QR code on the TV and paste your keys on your phone
- **Fits your hardware:** hides streams your TV, chip or network can't play well
- **English and German:** the interface follows the box's menu language (or choose it in Setup);
  English audio preferred with German second, subtitles in German with English as fallback

Use it only for content you are allowed to stream. Rules differ per country: in the EU, streaming
or downloading from unlicensed sources is generally unlawful even if you don't upload.

## Requirements

- An Enigma2 receiver with **OpenATV 7.6** (Python 3.13). Developed on an Octagon SF8008
  (HiSilicon Hi3798MV200) with the MyMetrixLite skin; the skin is drawn for 1920x1080 and scales
  to boxes whose GUI runs at 1280x720.
- A **TMDB API key** (free) and an account with at least one **debrid service**.
- Optional: Orion app + user key, Trakt app, OpenSubtitles API key.
- Python standard library only; nothing to install with pip on the box.

## Install

There is no prebuilt release yet, so build the package from source on any computer with Python 3:

```sh
git clone https://github.com/beckershoff/debridflix.git
cd debridflix
python3 build.py      # -> dist/enigma2-plugin-extensions-debridflix_<version>_all.ipk
```

Copy it to the box and install it (replace `BOX` with your receiver's IP address):

```sh
scp dist/enigma2-plugin-extensions-debridflix_*_all.ipk root@BOX:/tmp/
ssh root@BOX 'opkg install --force-reinstall /tmp/enigma2-plugin-extensions-debridflix_*_all.ipk && init 4 && init 3'
```

DebridFlix then appears in the plugin browser and the Extensions menu.

## Set up

On first start DebridFlix opens a **QR code**. Scan it with a phone on the same network as the
box, paste your keys on the page that opens, and tap **Link** for Real-Debrid, AllDebrid or
Trakt. The page only exists while the QR screen is open, behind a random address that changes
every time. It is plain HTTP on your local network, so use it on a network you trust.

You can also enter everything with the remote (BLUE = Setup, YELLOW = pairing / link / test),
or write `/etc/enigma2/debridflix.json` over SSH:

```json
{"tmdb_key": "...", "rd_token": "...", "orion_app_key": "...", "orion_user_key": "..."}
```

| Key | Where to get it | Setting |
| --- | --- | --- |
| TMDB API key (v3) | themoviedb.org > Settings > API | `tmdb_key` |
| Orion app + user key (optional) | panel.orionoid.com > Developers / Account | `orion_app_key`, `orion_user_key` |
| Premiumize | premiumize.me/account | `pm_key` |
| Real-Debrid | Setup > YELLOW > Link, or real-debrid.com/apitoken | `rd_token` |
| TorBox | torbox.app/settings | `tb_key` |
| AllDebrid | Setup > YELLOW > Link, or alldebrid.com/apikeys | `ad_key` |
| Debrid-Link | debrid-link.com/webapp/apikey | `dl_key` |
| Trakt (optional) | trakt.tv/oauth/applications, redirect URI `urn:ietf:wg:oauth:2.0:oob`, then Setup > YELLOW > Link Trakt | `trakt_client_id` |
| OpenSubtitles (optional) | opensubtitles.com > API consumers | `os_api_key` (+ username/password) |

Trakt apps created since October 2026 get only a Client ID and no secret; that is all DebridFlix
needs. Older apps can still fill in `trakt_client_secret`.

## Languages

Everything DebridFlix shows, including the phone setup page and the plugin's entry in the plugin
list, is available in **English and German**. *Language / Sprache* in Setup is `auto` by default,
which follows the box's own menu language. TMDB titles, descriptions and posters follow it too
(*Metadata language*).

- **Audio** (*Preferred audio languages*, default `en,de`): streams are sorted so English releases
  come first and German second. Release tags such as `GERMAN`, `DL` (German + English) and `ENG`
  are recognised; untagged releases count as English. When a file has several audio tracks, the
  player switches to the first preferred language automatically.
- **Subtitles** (*Subtitle languages*, default `de,en`): BLUE in the player searches
  OpenSubtitles and lists German first, English if there is no German. Turn on *Load best subtitle
  automatically* to have them appear by themselves.

Other languages can be added as another dictionary next to `core/i18n_de.py`.

## Remote control

| Screen | Keys |
| --- | --- |
| Home | arrows move, OK details, RED search, GREEN watchlist add/remove, YELLOW only titles with a cached stream, BLUE/MENU setup |
| Streams | OK play, RED cached only, GREEN resolution, YELLOW audio, BLUE language, MENU send the torrent to a service |
| Player | BLUE subtitles (search, off, shift timing by 0.5 s) |

## How streams are found and played

**Search.** With Orion keys set, Orion is used. Without them (setting *Stream search* = auto),
DebridFlix asks the public Torrentio index, which needs no key. Both only supply torrent
infohashes; nothing is downloaded from them.

**Cached or not.**
- Premiumize and TorBox are asked directly.
- Real-Debrid, AllDebrid and Debrid-Link removed their cache-check APIs in late 2024. With Orion,
  their status comes from Orion's data ("Orion fresh cache lookup" refreshes it live, using Orion
  quota). With Torrentio their status is unknown and shown as **Maybe** in orange: pressing OK
  tries the service, which plays the file if cached, or queues the download if not.
- If nothing is cached, MENU (or OK) sends the torrent to your service to download in its cloud.

**Playback is HTTPS only.** The box plays only `https://` links handed out by your debrid
service and refuses anything else, so it never connects to other torrent users and the stream is
always encrypted. Certificates are verified, both for API calls and by the default player
(service type 4097, GStreamer). Your internet provider can see which services you use, not what
you watch.

**Hidden streams.** By default the list hides what your setup can't play well:
- resolutions above what your TV reports over HDMI (e.g. 4K on a Full HD TV),
- AV1 video and Dolby-Vision-only files on HiSilicon chips (which decode neither),
- files whose estimated bitrate (size / runtime) is above 15 Mbit/s, a safe limit for Wi-Fi.

The list says how many were hidden and why. Change this in Setup with *Hide streams this box/TV
cannot play well*, *Max resolution* and *Max bitrate* (e.g. 40 on a wired connection).

## Troubleshooting

- Turn on **Debug log** in Setup: every API request and reply goes to `/tmp/debridflix.log`.
- Enigma2 crash logs are in `/home/root/logs/` (or `/media/hdd/logs/`).
- Streams stall: try player type 5002 (exteplayer3) in Setup, or lower *Max bitrate*.
- Settings live in `/etc/enigma2/debridflix.json` (readable by root only); the poster and search
  cache lives in `/tmp/debridflix/`.
- Each play on Real-Debrid adds the torrent to your RD cloud list; DebridFlix does not clean
  these up.

## Development

```
DebridFlix/
  plugin.py      plugin entry (plugin browser + Extensions menu)
  core/          service logic, no Enigma2 imports, testable anywhere
    http.py        urllib wrapper (tests replace http.request)
    settings.py    JSON settings and the setup field list
    models.py      Stream model, Orion parser, filters, episode file picking
    orion.py torrentio.py debrid.py tmdb.py trakt.py subtitles.py
    device.py      what the box + TV can play (reads /proc/stb)
    i18n.py i18n_de.py   interface language, German texts, audio/subtitle language helpers
    service.py     App facade used by the screens
    qr.py pairing.py   QR encoder and the phone pairing web page
  ui/            Enigma2 screens (skins are generated in each file)
tests/           unittest suites
build.py         builds the .ipk
```

Run the tests off-box:

```sh
python3 -m unittest tests.test_core tests.test_ui_smoke
```

`test_core` runs the service logic against a fake HTTP layer; `test_ui_smoke` runs the screens
against stand-in Enigma2 classes. The pairing test also needs `opencv-python` and `numpy` to
decode the QR code.

For quick iteration, sync the source straight to the box and restart Enigma2:

```sh
rsync -a --delete --exclude __pycache__ DebridFlix/ root@BOX:/usr/lib/enigma2/python/Plugins/Extensions/DebridFlix/
ssh root@BOX 'init 4 && init 3'
```

Some notes for Enigma2 work, learned the hard way:
- Every `<screen>` needs `resolution="1920,1080"`, or OpenATV scales the skin as if it were 720p.
- Runtime `instance.move()` takes raw desktop pixels; use `ui.common.point()` to convert.
- Enigma2 `exec()`s anything in `onLayoutFinish` that isn't a bound method: no lambdas there.
- MultiContent list entries, `setFont()` and `setItemHeight()` are raw pixels too: use `ui.common.scale()`.
- Wrap every user-visible string in `_()`; a test fails when a German translation is missing.

## Status

Version 0.2.0. Browsing, Trakt linking, Torrentio search and playback through a debrid service
work on a real box. Orion support is written from its documentation but not yet tested against
live keys.
