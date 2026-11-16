# DebridFlix 0.2.0 (Enigma2 / OpenATV 7.6, FHD skin)

Poster-row browser for your set-top box. Finds torrents through Orion, shows which are
cached on your debrid services, plays them in the box's own media player, and can start a
cloud download when something is not cached yet.

Services: Orion (search), Premiumize, Real-Debrid, TorBox, AllDebrid, Debrid-Link,
Trakt (watchlist + watched), TMDB (catalogue), OpenSubtitles.com (subtitles).

Use it only for content you are allowed to download or stream.

## Install

    opkg install /tmp/enigma2-plugin-extensions-debridflix_0.2.0_all.ipk
    init 4 && init 3        # restart Enigma2

or unpack `DebridFlix-0.2.0.tar.gz` into `/usr/lib/enigma2/python/Plugins/Extensions/`.
Python standard library only, no extra packages.

## Keys you need

| What | Where | Setting |
| --- | --- | --- |
| TMDB API key (v3) | themoviedb.org > Settings > API | `tmdb_key` |
| Orion app key | panel.orionoid.com > Developers (register an app) | `orion_app_key` |
| Orion user key | panel.orionoid.com > Account | `orion_user_key` |
| Premiumize | premiumize.me/account | `pm_key` |
| Real-Debrid | Setup > YELLOW > Link, or real-debrid.com/apitoken | `rd_token` |
| TorBox | torbox.app/settings | `tb_key` |
| AllDebrid | Setup > YELLOW > Link, or alldebrid.com/apikeys | `ad_key` |
| Debrid-Link | debrid-link.com/webapp/apikey | `dl_key` |
| Trakt | trakt.tv/oauth/applications (redirect `urn:ietf:wg:oauth:2.0:oob`), then Setup > YELLOW > Link | `trakt_client_id`, `trakt_client_secret` |
| OpenSubtitles | opensubtitles.com > API consumers | `os_api_key` (+ username/password) |

## Pair with your phone (easiest)

BLUE (Setup) > YELLOW > "Set up from your phone". The TV shows a QR code; scan it with a phone
on the same network. The page lets you paste keys and tap Link for Real-Debrid, AllDebrid and
Trakt (for Trakt, save the client ID and secret first). The page is served by the box on port
8765, over plain HTTP on your LAN, only while that screen is open, behind a random address
that changes every time.

Everything lives in
`/etc/enigma2/debridflix.json`, so you can also create that file over SSH:

    {"tmdb_key": "...", "orion_app_key": "...", "orion_user_key": "...", "pm_key": "..."}

## Remote control

Home: arrows move, OK details, RED search, GREEN Trakt watchlist add/remove,
YELLOW show only titles with a cached stream, BLUE/MENU setup.

Streams: OK play, RED cached only, GREEN resolution, YELLOW audio, BLUE language,
MENU send the torrent to a service (starts the download there).

Player: BLUE subtitles (search, off, shift 0.5 s). A title watched for 80 % or to the end
is marked as watched on Trakt.

## How "cached" is decided

- Premiumize and TorBox are asked directly.
- Real-Debrid, AllDebrid and Debrid-Link removed their cache-check endpoints in late 2024, so
  their status comes from Orion's stream data. Turn on "Orion fresh cache lookup" for a live
  check (this uses Orion quota). If Orion was wrong, pressing OK simply starts the download.
- "Cached only" on the home screen runs one Orion search per title (first 18 of a row, results
  kept 12 hours). It costs Orion quota and makes rows load slower.

## Troubleshooting

Turn on "Debug log" in Setup; requests and replies go to `/tmp/debridflix.log`.
Enigma2 crashes are in `/home/root/logs/`.

Tests (off-box): `python3 -m unittest tests.test_core tests.test_ui_smoke`
