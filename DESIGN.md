# tgplay — design & requirements traceability

*What this document is:* a **design document** with a **requirements
traceability matrix**. For every need we had, it records the **rule/method**
that satisfies it and **where** it lives, plus the invariants the code must
keep. If you change behaviour, update the row.

Companion docs: `ARCHITECTURE.md` (module map), `FEATURES.md` (behaviour +
to-do). This file is the *why* and the *how*, end to end.

---

## 1. The one idea: layers

```
entry scripts (agp axp tg tgp tgplay)
        │  tp/app.run()        logfile + crash dialog
        ▼
CLIs        tp/cli · tp/cli_animex · tp/cli_telegram · tp/cli_all
        │  build a Provider, choose episodes, run the Playlist
        ▼
Providers   tp/providers/{animegate,animex,telegram}
        │  catalog + a fresh byte/HLS source per play
        ▼
Sources     tp/sources (HttpSource ranged · DirectSource HLS · TelegramSource)
        │
        ▼
Playback    tp/proxy (local range proxy) · tp/playlist (loop) · tp/player (mpv)
Side        tp/metadata · tp/titles · tp/simkl · tp/bangumi · tp/translate
            tp/skip · tp/chapters · tp/cache · tp/prefetch · tp/tracking
            tp/library · tp/simkl_account (Simkl watch-list hub)
UI          tp/ui (curses) · tp/gui_qt / tp/gui (single-session) · tp/gui_all (unified)
Front       tp/search · tp/history · tp/session · tp/icon · tp/setup · tp/config
```

Rule of the design: **one concern per module**, and *shared machinery never
knows which source it is serving*. A provider answers three questions only:
"what episodes?", "what is the byte source for episode N?", "what is the title?"
Everything else (proxy, cache, skip, resume, menus, player) is source-agnostic.

---

## 2. Source model — the central abstraction

There are two shapes of source, and that is the only real fork:

| shape | example | how it plays | source class |
|---|---|---|---|
| **Ranged file** (mkv/mp4 with HTTP Range) | animegate, Telegram | through the **local range proxy** (seek = range read) | `HttpSource` / `TelegramSource` |
| **Direct stream** (HLS/m3u8) | animex | mpv plays the URL itself | `DirectSource` (`direct = True`) |

The Playlist asks `getattr(source, 'direct', False)`. If direct it hands the
URL + headers (`Referer`) + subtitle tracks straight to mpv and **skips the
proxy/cache**; otherwise it registers the source with the proxy and plays the
proxy URL. This is why adding animex did not touch the cache or proxy.

---

## 3. Entry points & routing

| command | module | what it does |
|---|---|---|
| `agp` | `tp/cli.main` | animegate catalogue (sub) |
| `axp` | `tp/cli_animex.main_axp` | animex (sub/dub servers, HLS) |
| `tg` | `tp/cli_telegram.main_tg` | one Telegram file |
| `tgp` | `tp/cli_telegram.main_tgp` | last-N files of a Telegram channel |
| `tgplay` | `tp/cli_all.main_all` | **unified** one-page app (search + links + all sources) |

Every script is thin: `sys.exit(run(main, name))` → `tp/app.run()` installs the
log file and a crash dialog, then calls the CLI.

`tp/cli_all.route(text)` maps one input to `(source, target)`:
`axp:<slug>`→axp · contains `animegate`→agp · contains `animex`→axp ·
`t.me/<c>/<id>`→tg · `t.me/<c>`→tgp · `@channel`→tgp · otherwise *a search query*.
`dispatch()` runs the per-source CLI for non-interactive/URL cases; the unified
window (`tp/gui_all`) uses `tp/session.open_session()` instead.

---

## 4. Requirements → method → where (traceability)

### Playback

| Need | Rule / method | Where |
|---|---|---|
| Stream without downloading | local **range proxy** (RAM head/tail + on-disk window) so mpv seeks like a file | `tp/proxy.py` |
| One code path for all backends | `MediaSource` interface (size + ranged `read`) | `tp/sources.py` |
| Resume where you left off | position saved per title in `progress.json`; seek on start | `tp/playlist.py` (`_save`, `PosWatcher`) |
| Retry a failed open | mpv rc==2 → re-resolve a fresh link (≤2), rotate server for animex | `tp/playlist.py` |
| Skip intro/outro | file **chapters** first, then **ani-skip** by MAL id; `--skip-toggle` adds mpv key `T` | `tp/skip.py`, `tp/chapters.py` |
| Pre-download next episode | background prefetch (cancellable) triggered by `PosWatcher` at N% | `tp/prefetch.py`, `tp/playlist.py` |
| Cut / start offsets | `--cut N` (stop early), `--start N`, `--next`/`--nowait` | `tp/player.py` (`command`) |
| Quality choice | animegate: site groups; Telegram: parsed from filenames; animex: server list | providers + `tp/quality.py` |

### Titles & metadata

| Need | Rule / method | Where |
|---|---|---|
| English episode names | **MAL-direct → Bangumi → Simkl** chain; AniList only to resolve the MAL id | `tp/metadata.py` |
| Names never block playback | menu reads **cache only**; missing names filled by a **background thread** (≤5 s bound) | `tp/titles.py`, `tp/cli.py` |
| Names never overwritten / never auto-deleted | cache is written once per (series, ep); generic `Episode N` dropped | `tp/titles.py` |
| Chinese → English | batched MyMemory translation, cached | `tp/translate.py` |
| Donghua without MAL | Bangumi search by CJK title (from Simkl `alt_titles`), seasons stitched by offset | `tp/bangumi.py` |
| Show page link | Simkl preferred, else MAL; cached in `links.json`; logged before the menu | `tp/simkl.py`, `tp/cli.py` (`_log_show`) |
| Don't hammer a dead API | **circuit breaker** per source (~30 min, persisted) | `tp/metadata.py` (`meta_down.json`) |

### Cache & storage

| Need | Rule / method | Where |
|---|---|---|
| Don't lose unfinished downloads | `.part` files are **never auto-deleted** | `tp/cache.py`, `tp/prefetch.py` |
| Report & manual cleanup | `agp cache` report; `cache clean --days N [--all] [--keep-partial]` | `tp/cli.cache_command` |
| Know geometry without re-reading | `.done`/`.win` sidecars; `is_full()` | `tp/cache.py` |

### Sources

| Need | Rule / method | Where |
|---|---|---|
| animegate catalogue | parse `:links=` JSON + CSRF; download-links API; signed CDN | `tp/providers/animegate.py` |
| **English dub** | animex `/rest/api/servers` (sub+dub) → `/rest/api/sources` (HLS) | `tp/providers/animex.py` |
| Dub missing → warn + sub | `_resolve_audio()` logs a warning and falls back to the other audio | `tp/providers/animex.py` |
| Dead server → next one | `_probe()` checks the URL serves `#EXTM3U`; `rotate()` on mpv failure | `tp/providers/animex.py`, `tp/playlist.py` |
| Telegram file/channel | telethon messages as `TelegramSource`; auth errors never retried | `tp/providers/telegram.py` |
| Quality from filenames | tolerant `quality.group()` | `tp/quality.py` |

### Menus & app

| Need | Rule / method | Where |
|---|---|---|
| Terminal menu | curses form (options + episode picker), plain-text fallback | `tp/ui.py` |
| Desktop window | Qt (PySide6) preferred, Tk fallback | `tp/gui_qt.py`, `tp/gui.py` |
| Persistent window + Stop + live status | playback in a background thread; window stays open | `tp/gui_qt.controller` |
| Follow the OS theme | Qt inherits KDE/Breeze automatically; Tk paints from `kdeglobals`/GTK | `tp/gui_qt._app`, `tp/gui._apply_theme` |
| In-app log | `log.SINK` mirrors `tp.log` lines into a panel, pre-filled from `log.HISTORY` | `tp/log.py`, GUIs |
| **One page** (search + episodes + options + log) | unified window loads a **Session** in place | `tp/gui_all.py`, `tp/session.py` |
| Search without a link | animegate `/global-search?s=`; animex GraphQL `searchAnime` | `tp/providers/*.search`, `tp/search.py` |
| Remember recent links/searches | `history.json`; shown when the field is empty | `tp/history.py` |
| Enter with no result doesn't quit | keep window open + hint; only Cancel closes | `tp/gui_all.py`, `tp/gui_qt.choose_url` |
| Launcher icon | SVG→PNG assets, hicolor install, `tgplay.desktop` | `tp/icon.py` |
| No terminal on launch | log to `~/.config/tgp/<name>.log`; crash dialog; window raises | `tp/app.py`, `tp/log.py` |
| Remember last setup | `ui.json`, **namespaced per source** (`{agp,axp,tgp}`) | `tp/setup.py` |
| English-only UI | all user-facing strings in English | everywhere |

### Library / tracking (Simkl hub)

| Need | Rule / method | Where |
|---|---|---|
| Login to a tracker | Simkl **AUTH V2 device / PIN** flow (no redirect); tokens in `simkl_auth.json`; refresh on demand | `tp/simkl_account.py` |
| Watch list / create / sync lists | `GET /sync/all-items/anime/{watching,plantowatch}` — Simkl two-way-syncs MAL/AniList/Kitsu/Trakt, so one account covers them | `tp/simkl_account.py`, `tp/library.py` |
| Feed of new episodes | watching entries with `next_to_watch` | `tp/library.py` (`up_next`) |
| Feed / calendar + history rails | `next_to_watch_info.date` → **Feed · calendar** (right sidebar, top); `last_watched_at` → **History** (bottom) | `tp/library.py` (`upcoming`/`recent`), `tp/gui_all.py` |
| Play straight from the list | `find_source()` resolves the title on our sources → `session.open_session` → player at the next episode | `tp/library.py`, `tp/gui_all.py` |
| Sync progress back | on episode finish, `POST /sync/history` via a Playlist-compatible `SimklTracker` | `tp/simkl_account.py`, `tp/session.py` |
| (legacy) AniList tracking | Auth-Pin login + save/sync + notices | `tp/tracking.py` |

### Safety / correctness rules (invariants)

1. Titles are **cosmetic and never on the critical path** (cache-only in menus).
2. **Never overwrite** a stored title; never auto-delete cache partials.
3. A dead metadata source is **skipped** for a cooldown, not retried per call.
4. A provider returns a **fresh source each play** (links/tokens expire).
5. Playback is **one at a time** (`player.stop()` before each start).
6. The saved setup is **per source** — one source's values never leak into another.
7. A **search result** already carries animex's *internal* slug → trust it and
   read metadata from GraphQL, **never** the page endpoint (that mis-resolves).
8. Unified input: a link/`@channel` routes; anything else is a search.

---

## 5. State & config (all under `~/.config/tgp/`)

| file | holds |
|---|---|
| `progress.json` | resume position per title |
| `ep_titles.json` | episode names (never overwritten) |
| `translations.json` | zh→en cache |
| `mal_ids.json` / `mal_slugs.json` / `links.json` | metadata resolution + page links |
| `meta_down.json` | circuit-breaker cooldowns |
| `ui.json` | remembered menu setup, **per source** |
| `history.json` | recent links + searches |
| `simkl.json` | Simkl client id |
| `tg.session` | Telegram session |
| `<name>.log` | launch log (agp/axp/tgplay/…) |

---

## 6. How to add a source (extension point)

1. Write `tp/providers/<name>.py`: a `Provider` with `episodes()` and
   `stream(n)` (return `HttpSource` for ranged, `DirectSource` for HLS), plus an
   optional `search()`.
2. Add an entry point (thin script + `run(main, name)`), or register it in
   `tp/cli_all.route()` / `SOURCES` for the unified app.
3. Nothing else changes — proxy, cache, skip, resume, menus, player are shared.

---

## 7. Code audit (this pass)

**Removed (orphans / dead):**
- `tp/prefetch.kill_all` (+ its `_procs`/`_lock`) — never called.
- `tp/sources.HttpSource.refresh_size` — never called.
- `tp/episodes.first_start_for`, `tp/quality.strip_quality` — test-only, superseded.
- `tp/gui_qt.launcher` — superseded by the unified `tp/gui_all` window.
- Unused imports/vars in `chapters`, `cli_animex`, `cli_telegram`, `metadata`,
  `prefetch`, `session`, `tracking`, `gui_all`, `gui_qt`.
- Fixed `tgplay --curses` falling through to a GUI picker (now the terminal chooser).

**Known duplication / complexity (kept, flagged):**
- `tp/cli.main`, `tp/cli_animex.main_axp` and `tp/session.open_session` each set
  up a provider (groups/labels/link). *Recommendation:* make the per-source
  CLIs build a `Session` too, so there is exactly one setup path.
- `tp/gui_qt.controller` and `tp/gui_all` both build options/episodes/log.
  *Recommendation:* once agp/axp direct also route through `gui_all`, retire
  `gui_qt.controller`.
- `tp/metadata.ep_title` + `tp/simkl.episode_title` are a tested but **unused**
  fallback chain (the runtime uses `TitleService`/`refresh_titles`).
  *Recommendation:* delete or wire into `refresh_titles` if wanted.

**Style:** the code uses occasional `a = X(); b = Y()` one-liners (ruff E702) and
short names (`l`) — intentional for compactness; no functional impact.

---

## 8. Tests

`tests/test_*.py` (24 files) cover: core types, proxy, providers, player,
prefetch, skip, tracking, curses menu, quality/cache, simkl, titles, setup
(namespaced), progress, bangumi, translate, both GUIs, the unified window, icon,
animex provider, search, history, launcher routing, and the app wrapper. They
run headless (`QT_QPA_PLATFORM=offscreen`) and never need the network.
