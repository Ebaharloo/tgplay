# Simkl API → TGPlay map

Source: https://api.simkl.org/all-endpoints (48 endpoints, 14 categories), fetched 2026-11-17.
Base URL `https://api.simkl.com`. Every call needs `client_id`, `app-name`, `app-version`, `User-Agent`.

Verdict per endpoint for this app (anime playlist player). Effort = rough, one dev.

## Already wired

| Endpoint | Where |
|---|---|
| POST `/oauth2/device`, POST `/oauth2/token` | `tp/simkl_account.py` start_device/poll_device/refresh |
| GET `/users/settings` | `SimklAccount.user()` |
| GET `/sync/activities` | `activities()` — change gate |
| GET `/sync/all-items/anime` | `library()`, `up_next()` |
| POST `/sync/history`, `/sync/history/remove` | mark/unmark ep, season, show |
| POST `/sync/add-to-list` | `add_to_list()` |
| POST `/sync/ratings` | `rate()` |
| POST `/scrobble/checkin|start|stop` | `scrobble()` |
| POST `/scrobble/pause` | `scrobble('pause', ...)` — Playlist pushes it every 60 s of playback |
| GET `/search/anime` | `tp/simkl.py` title match |
| GET `/search/id` | legacy resolver (replace, see below) |
| GET `/anime/{id}`, `/anime/episodes/{id}` | `tp/simkl_extra.py` relations + air dates |

## Done — playback resume

| Endpoint | Where |
|---|---|
| POST `/scrobble/pause` | `Playlist._on_pos` — every `AGP_PAUSE_EVERY` (60 s) of playback, percent of episode |
| GET `/sync/playback/episodes` | `SimklAccount.playback()`; `SimklTracker.resume()` picks the row for the playing ep |
| DELETE `/sync/playback/{id}` | `SimklAccount.clear_playback()`; `SimklTracker.forget()` after local mark-watched |

Gate refetches on the `playback` stamp from `/sync/activities`; do not poll
`/sync/playback` on a timer. Today `resume()` fetches the list once per run.

## Add — bulk state (kills N calls)

| Endpoint | Use | Effort |
|---|---|---|
| POST `/sync/watched` | "have I watched these eps?" for a whole show/season in one call; replaces per-episode history probing | M |
| GET `/sync/all-items/{type}/{status}?date_from=` | delta fetch after the activities gate instead of full library | S |
| GET `/sync/ratings/{type}/{rating}` | "my 9s and 10s" list | S |
| POST `/sync/ratings/remove` | clear a rating (no way today) | S |

## Add — schedule & discover (no auth for CDN files)

| Endpoint | Use | Effort |
|---|---|---|
| GET `/calendar/anime.json`, `/calendar/{y}/{m}/anime.json` | new-episode agenda without scraping anime sites | S |
| GET `/anime/airing` | today / tomorrow airing | S |
| GET `/anime/premieres/soon` | upcoming season panel | S |
| GET `/discover/trending/anime.json` | trending strip | S |
| GET `/search/random` | "surprise me" button | S |

## Add — matching

| Endpoint | Use | Effort |
|---|---|---|
| GET `/redirect` | canonical id from MAL/IMDB/TMDB; header-only + cached, replaces `/search/id` | S |
| POST `/search/file` | identify a local mkv by filename/path → Simkl title (local library import) | M |
| GET `/anime/{id}?extended=full_anime_seasons` | clean season split, better than relations walk | S |

## Hygiene

| Item | Why |
|---|---|
| POST `/oauth2/revoke` on logout | today `logout()` only deletes `simkl_auth.json`; token stays valid server-side |
| GET `/users/{user_id}/stats` | profile numbers, free |
| expose `activities` staleness | after 429/wait, refresh gate instead of trusting old timestamps |

## Skip

- `/lists/*` — PRO/VIP only (403 on writes for free accounts).
- `/tv/*`, `/movies/*`, `/discover/dvd`, `/changes` — anime-only app.
- `/search/id` kept only as fallback while `/redirect` is validated.

## Notes

- V1 auth (`/oauth/pin`) retires ~April 2027; this app already uses V2 device flow. Nothing to do.
- Free tier ~1000 requests/day: `/sync/watched` and delta sync are the two calls that keep the app inside that budget.
