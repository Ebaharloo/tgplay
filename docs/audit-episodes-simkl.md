# Audit: episode lists, right-click menu, Simkl code

Read-only map of `~/coding/python/tgplay`.

**All line numbers below are for committed HEAD `39c2bd2`.** The working tree is
dirty right now (see §0) — line numbers there have already drifted.

## 0. Uncommitted work in the tree (as of this audit)

`git status` shows an in-flight change that is exactly the "mark watched +
Simkl" feature. Do not treat these as existing conventions; they are not
committed and may change under you:

- untracked `tp/watched.py` — local per-episode store, `~/.config/tgp/watched.json`,
  keyed `simkl:<id>` / `mal:<id>` / title, `{"eps": [1,2], "complete": false}`.
- untracked `tp/simkl_sync.py` — offline-first push queue
  (`pending_sync.json`) drained by a daemon worker.
- untracked `tests/test_simkl_sync.py`.
- modified `tp/gui_all.py` (+239 lines), `tp/config.py` (`Config.watched`,
  `Config.simkl_queue`), `tp/simkl_account.py`, `tp/providers/animex.py`,
  `tp/web/server.py` (imports `watched`, adds `AppState.on_watched_changed`),
  `tests/test_simkl_account.py`, `tests/test_animex.py`.

At HEAD none of that exists: there is no local watched store and no
mark-watched menu item (§3, §4). If a later task wants that feature, check
whether this work has landed first.

## 1. Stack

Two front ends, one Python core.

| Part | Stack | Entry |
|---|---|---|
| Desktop GUI (main) | Python + PySide6 (QtWidgets) | `tgplay` -> `tp/app.py:20` `run()` -> `tp/cli_all.py` -> `tp/gui_all.py` `MainWindow` |
| Web UI ("Astryx") | Python `http.server` + React/Vite in `web/` | `./tgplay --web` -> `tp/web/run.py` -> `tp/web/server.py`; `./tgplay --web-app` -> `tp/web/app_window.py` (Qt QWebEngineView) |
| CLI | plain Python | `tp/cli.py`, `tp/cli_animex.py`, `tp/cli_telegram.py` |

- GUI: `tp/gui_all.py` (2953 lines at HEAD) is the whole window; PySide6 import at line `17`.
- Web server: `tp/web/server.py` (718 lines), stdlib `http.server`, JSON API + built bundle.
- Web source: `web/src/app.jsx` (487 lines). Build: `cd web && npm run build` -> `web/dist/`.
  `web/dist/` is **not** tracked (`git ls-files web` lists only `web/src`, `web/index.html`, `web/package.json`, `web/vite.config.js`), so the `web/dist` on disk is a local build.
- No `requirements.txt`, no `pyproject.toml`. Deps live in `.venv/` (PySide6, PySide6-Addons, telethon).
- Tests: `tests/`, 36 pytest files. GUI tests run offscreen (`tests/test_gui_all.py:9` sets `QT_QPA_PLATFORM=offscreen`).

## 2. Every view that renders an episode list

### Qt (`tp/gui_all.py`, HEAD lines)

| View | Widget | Built at | Filled at |
|---|---|---|---|
| Show episode table (`#`, `Episode name`) | `W.QTableWidget(0,2)` `self.table` in group box `self.ebox` | `1394-1408` | `set_session()` `1699-1733`, rows from `sorted(s.labels)`; `_probe_sizes()` fills sizes in a worker |
| Search results list (row per source/link) | `W.QListWidget` `self.results` | `1330` | `_fill_results()` `1870`; menu `_results_menu` `1925` |
| Recent links table (`Date`,`Source`,`Link`) | `W.QTableWidget(0,4)` `self.hist_tbl` | `1333-1347` | `show_history()` `2027-2060` |
| Sidebar feed / calendar (`Date`,`Ep`,`Title`,`Aired`) | `SortableTable` `self.feed` | `1221` | `_refresh_library()` `2350`, rows set inline in that method |
| Sidebar history (`Watched`,`Prog`,`Title`) | `SortableTable` `self.hist` | `1230` | same `_refresh_library()` |
| Continue-watching poster shelf | `ContinueShelf` / `_ShelfCard` | `599`, `668`, held at `1240` | `set_items()` |

No season view and no separate library dialog exist. `self.feed` + `self.hist`
(Simkl-backed) are the library surfaces; `_refresh_library()` `2350` is their
single refresh path.

### Web (`web/src/app.jsx`, `tp/web/server.py`)

| View | Where |
|---|---|
| Episode list of loaded show (`session.episodes`) | `web/src/app.jsx:221` `Show` component, rows mapped at `251-260` |
| One episode row + its `⋯` menu | `web/src/app.jsx:197-219` `EpisodeRow` (items array `198-207`; `onContextMenu` `211` only selects the row — the menu is the `DropdownMenu`) |
| Search results | `web/src/app.jsx:150` `Results` |
| Sidebar agenda (feed / upcoming) | `web/src/app.jsx:265` `Sidebar` |
| Continue-watching rail | `web/src/app.jsx:86` `Rail` |
| Episode payload served to the UI | `tp/web/server.py:440` `_session_view`, episodes at `449-451` (built from `session.labels`) |

## 3. The removed "mark watched" right-click handling

**It never existed in code.** Nothing was removed.

Results of the three requested commands:

- `git log --oneline -S contextMenu` -> no output (that string never appeared in a tracked file).
- `git log -S 'setContextMenuPolicy'` -> `a94aa27` (added), then `ce5f6eb`, `2c2dfbe`. The code is still at HEAD (`tp/gui_all.py:1515,1522,1530`); there is no removal commit.
- `git log --diff-filter=D --name-only | grep -i -E 'episode|watch|simkl'` -> **empty**. No file matching those words was ever deleted in the repo's history.

Cross-checks:

- `git log -p --all -S'mark watched' -- tp/` -> the string appears **only** in `a8585b3`, and only as `FEATURES.md:108` ("On episode finish -> mark watched (background)").
- `git log -S 'markWatched'`, `git log -S 'mark_episode'` -> no output.
- Every `watched` string ever added to `tp/gui_all.py` is display: sidebar `Watched`/`Prog` columns, progress fractions, `last_watched` sorting.

What exists at HEAD:

| Surface | File:line | Menu items |
|---|---|---|
| Show episode table right-click | `tp/gui_all.py:1530` (policy) -> `_ep_menu` `1597-1630` | Play from here to the end / Play only selected / Play all, Copy episode link, Show pages submenu (Simkl / AniList / MAL / Fandom). **No watched action.** |
| Search result right-click | `1522` -> `_results_menu` `1925-1955` | Copy link, Open in browser, Show pages |
| Sidebar feed/history right-click | `1522` (both tables) -> `_context` `2629-2660` | Search/load on our sources, `+ Simkl list` submenu (watching / plantowatch / completed / hold / dropped via `_set_status` `2609`), Open on Simkl, Open on MAL |
| Web episode row | `web/src/app.jsx:197-219` | Play from here / only selected / all, Copy episode link, Show pages |

Marking watched is **automatic only**: `tp/playlist.py:262-278` calls
`self.tracker.mark_watched(title, num, mal=..., anilist=...)` in a worker thread
when an episode finishes (log line `track: epN synced`). The manual
`+ Simkl list` button (`tp/gui_all.py:2258` `add_current`) only puts a show on a
Simkl *status*; it does not mark an episode.

So a right-click "mark watched" is **new code**, not a restoration. Hooks:
`_ep_menu` `1597` (Qt), `EpisodeRow` items `198` (web), and
`_context` `2629` for the sidebar rows.

## 4. Simkl code, watched state, auth

### Simkl modules (HEAD)

| File | Role |
|---|---|
| `tp/simkl.py` | Episode **titles** fallback (MAL/AniList id or title -> Simkl id -> `/anime/episodes/{id}`). Silent no-op without a client id. |
| `tp/simkl_account.py` | Account + API. Client id resolution `48-54` (env `AGP_SIMKL_CLIENT_ID`, `~/.config/tgp/simkl.json`, else `BUILTIN_CLIENT_ID` `35`). Token `65-77`. `_api()` `97` (client_id/app-name params, 401 refresh, 429/5xx retries, raises `SimklError(status, error)`). Device/PIN login `~140-200`. `_norm()` `259-281` -> `watched`, `total`, `next_ep`, `last_watched`, `status`, ids. `library()` `282-295` from `/sync/all-items`; `up_next()`. `mark_watched()` `297-312` -> POST `/sync/history`. `add_to_list()` `314-323` -> POST `/sync/add-to-list`. `SimklTracker` `326-386` (playlist adapter, fuzzy title match). |
| `tp/simkl_extra.py` | Cached relations (7 d TTL) + episode air dates (1 d TTL), per Simkl id; never raises into the UI. |
| `tp/library.py` | Simkl library + Simkl calendar -> `cal` / `rem` / `hist` rows for the sidebar; `find_source()`. |
| `tp/continuewatch.py`, `tp/recent.py` | Derive continue-watching and recent rails from Simkl rows. |
| `tp/status.py` | Connection lights (Simkl / AnimeGate / AniList) for the status strip. |
| `tp/tracking.py` | AniList tracker (`155` `mark_watched`), `Fanout` (`305`), `make_tracker()` (`335`) building Simkl + AniList. |

### Watched state: no local store at HEAD

- **No SQLite, no schema, no tables.** The only sqlite in the repo reads Firefox cookies (`tp/providers/animegate.py:10,25,28`).
- Watched truth lives **on Simkl**: `watched_episodes_count`, `next_to_watch_info`, `last_watched_at`, `status` (`tp/simkl_account.py:259-281`).
- Local files are caches + resume only, JSON in `~/.config/tgp/`:
  - `progress.json` — per-title resume `{title: {"ep": n, "pos": seconds}}` (`tp/playlist.py:49-62`, `tp/session.py:64,168`). **Not** a watched flag.
  - `history.json` — recent links + queries (`tp/history.py`).
  - `episodes.json`, `ep_titles.json`, `relations.json`, `characters.json`, `posters.json` — caches (`tp/config.py:66-124`).
  - `ui.json` — window/rails/options state (`tp/config.py:86`).
- There is **no per-episode-watched and no season-complete column anywhere local**. Any such feature must either write through to Simkl (`/sync/history`) or introduce a new store (the untracked `tp/watched.py` in §0 does the latter).

### Auth / token storage

- Simkl token: `~/.config/tgp/simkl_auth.json` (`tp/config.py:94`, written by `SimklAccount._save` `69-73`); env override `AGP_SIMKL_TOKEN` (`74-75`).
- Simkl client id: see above (public, may be committed).
- AniList token: `~/.config/tgp/anilist.json` (`tp/config.py:90`), used in `tp/tracking.py`.
- AnimeGate: Firefox cookie DB, read-only (`tp/providers/animegate.py:25-28`).
- Telegram: telethon session path from `Config.tg_session` (`tp/config.py` ~113), env `TG_SESSION`.
- All writes go through `tp/config.py:13 save_json` (atomic, unique temp file per writer) / `:41 load_json`.

## 5. Existing conventions

- **Config**: one injectable `Config` object, no module globals; tests build `Config(home=..., cache_dir=...)` to sandbox it (`tp/config.py:52-133`). Do not hardcode `~/.config/tgp` outside `Config` (legacy `tp/simkl.py` and `tp/history.py` still derive paths from `cfg.progress`).
- **State files**: JSON via `save_json` (atomic) and `load_json` (tolerant, returns `{}`).
- **Network**: synchronous `urllib` wrapped in `tp/http.py:28 HttpClient` (`request()` `38`, `open()` `44` with retries on transient errors only — a real 403/404 is raised to the caller, `range_bytes()` `60`). No `requests`, no web framework. Telethon is the only async client and marshals into its own loop thread (`tp/providers/telegram.py:104-145`).
- **Threading**: background work is `threading.Thread(..., daemon=True)`; the Qt UI gets results through `queue.Queue` (`self._libq`, `tp/gui_all.py` ~1270, drained by a `QTimer`) — never touch widgets from a worker. Web: `AppState` in `tp/web/server.py`, UI polls `GET /api/state` plus SSE `/api/events`.
- **Logging**: `tp/log.py` only. `log.cprint()` with a known prefix (`search:`, `simkl:`, `track:`, `watched:`, `error:` ...) gets emoji + colour (`tp/log.py:14-40`). The GUI mirrors lines into `LogView` through `log.SINK` / `log.HISTORY`; file log via `log.open_logfile()` `52`.
- **Error display**:
  - Qt: short text in `self.state['msg']` / status label; detail in `LogView`; crashes go to `tp/app.py:47 _show_error` (Qt dialog, then Tk, then stderr).
  - Web: JSON `{"error": msg}` + HTTP code (`tp/web/server.py:526,535`); UI shows it in its status line.
  - Simkl/AniList failures in background paths are logged, not raised into the UI (`SimklAccount._api` raises `SimklError`; callers catch and log).
- **Options**: `PlaybackOptions` (`tp/options.py`), rendered by `OptionsForm` (Qt) and `form_fields()` (web); the `sync` flag (`tp/options.py:23,327`) enables pushing progress to Simkl per run.
