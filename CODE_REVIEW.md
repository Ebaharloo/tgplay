# tgplay — code review

Whole-project pass (linters, dead-code scan, complexity, duplication).

## Health snapshot
- ~8.3k lines across 40 modules; **no import cycles** (`importlib` walk of `tp.*` all clean).
- **25 test files, all green**; run headless, no network.
- **Lint:** only 4 minor `B`-rules (2 are benign `lambda` default captures), plus ~69
  long-line/style (`E501`/`E7`) — no unused imports/vars left (`F` clean).

## Fixed in this pass
- **Redundant Simkl fetches** — the sidebar did **5 sequential** `/sync/all-items`
  status calls *plus* the calendar on every refresh (~20 s). Simkl returns the whole
  library in **one** call, so `SimklAccount.library()` now fetches once and filters in
  memory, and `tp/library.overview()` does **one library fetch + one calendar fetch**:
  **20 s → 4.3 s**.
- **Consolidated `tp/library.py`** — removed `entries/up_next/_all/calendar/
  recently_aired/remaining/recent` (only `overview()` + `find_source()` are used).
- **`tp/cache.py`** — unused loop variable (`B007`).

## Remaining findings (prioritised)

### 1. Duplicated "Options" across four UIs  (done)
The options inventory now lives in **`tp/options.py`**: `PlaybackOptions`
(the normalizing read/write view over the legacy opts dict + mpv list) plus
`form_fields()`/`form_result()` — the render/collect spec every UI shares:
- Qt window: `tp/gui_all.OptionsForm` (rows mirror the old grid exactly)
- curses form: `tp/ui._curses_form` renders the same spec (test_ui still green)
- remembered setup: `tp/setup.py` save/apply delegate to the model
  (`saved_shape` / `merge_saved` — test_setup stays byte-identical)
- locked by `tests/test_options.py` (field inventory == setup.save keys ==
  parse keys; full round-trips)
- one improvement out of it: an explicit `--next=N` fraction now survives an
  untouched UI checkbox instead of silently resetting to 0.60.

### 2. Duplicated provider/session setup in the CLIs  (done)
`agp`, `axp`, `tg`, `tgp` no longer hand-wire provider + proxy + cache + skip +
prefetch + player + playlist. Every path builds **one `Session`**
(`tp/session.open_session`, extended with `wait_titles` for the curses menu
and `window`/`matcher` for tgp) and plays/closes it. Args keep their exact
behavior: `-a/-e` prompts, audio flags, `--window/-f`, sub/dub, resume
prompts. The old `_run` service zoo is gone from all three modules
(`tests/test_cli_session.py` pins the wiring).

### 3. Two now-dead GUI controllers  (done)
`gui_qt.controller` (303 LN) and `gui.controller` (268 LN) are retired. Every
GUI now goes through the unified window via the OOP seams:
- `tp.session.SessionLoader` — loader(src, target) → Session, with option
  precedence CLI base > remembered (`setup.load(cfg.ui, src)`) > defaults.
- `tp.gui_all.UnifiedWindow` — the one window object, opened by `tgplay`
  AND the `agp`/`axp` CLIs (unified branch before the provider pre-load, so
  the catalogue isn't fetched twice; falls back to the curses menu if Qt
  fails). `cli`/`cli_animex` no longer carry their own window code.
- `Session.play` now remembers the last used setup (`setup.save`, per source)
  — the old controllers did this and the unified window had silently lost it.
- Kept from the old modules: `choose_url` (Qt + Tk pickers) and the Tk
  `launcher` (no-PySide6 fallback) in `tp/gui.py`.

### 4. Large functions  (done — the window is a class now)
`gui_all.app` was a 784-line closure; it is a `MainWindow` class (widget
builders `_build_*`, behavior methods, `UnloadOptionsForm`) with a thin
`app()` wrapper kept for compatibility. `cli.main`/`main_axp` shrunk to
arg-parse + Session; `ui._curses_form` now renders the shared spec instead of
hand-rolling its fields.
Remaining sizable: `playlist.run` (118) — cohesive loop, left as is.

### 5. Tested-but-unused code  (low effort)
`metadata.ep_title` + `simkl.episode_title` — covered by tests but not used at runtime
(the app uses `TitleService`/`refresh_titles`).
→ Delete, or wire into `refresh_titles`.

### 6. Robustness / style  (cosmetic)
- 204 × `except Exception` (mostly intentional for a media app); a few could log a
  debug line instead of a bare `pass`.
- Long lines / `a=X(); b=Y()` one-liners — harmless.

## Suggested order
1. ✅ single-fetch overview (done).
2. ✅ retire the duplicate GUI controllers (#3, done).
3. ✅ shared Options model (#1, done — tp/options.py).
4. ✅ collapse the CLIs onto `Session` (#2, done — all four sources).
5. ✅ MainWindow class (#4, done — gui_all rewritten OO).
6. Delete/relocate the unused title helpers (#5).
