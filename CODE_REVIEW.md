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

### 1. Duplicated "Options" across four UIs  (medium effort)
The same fields — quality/server, audio, skip, toggle, next, nowait, cut, extra,
fullscreen, sync — are built 4×: `tp/gui_all.py`, `tp/gui_qt.py`, `tp/gui.py` (Tk),
`tp/ui.py` (curses).
→ Extract a shared **options model** (list of field specs + `to_opts()/from_opts()`)
and render it per toolkit.

### 2. Duplicated provider/session setup in the CLIs  (medium effort)
`cli.main`, `cli_animex.main_axp`, `cli_telegram.main_tgp` each build a provider +
proxy + cache + skip + prefetch + player + playlist, and `session.open_session()` is a
4th copy.
→ Make every per-source CLI build a **`Session`** (`tp/session.open_session`) — one
setup path, and `agp`/`axp`/`tgp` shrink to arg-parse + pick + `session.play()`.

### 3. Two now-dead GUI controllers  (medium effort, big win)
`gui_qt.controller` and `gui.controller` are only used by **`agp`/`axp` direct**; the
unified app uses `gui_all`. They duplicate `gui_all`'s window.
→ Route `agp`/`axp` through `gui_all`/`session`, then retire `gui_qt.controller`
(keep `choose_url`/`launcher`/Tk fallback).

### 4. Large functions  (low risk, mechanical)
`gui_all.app` (784 lines), `gui_qt.controller` (303), `gui.controller` (268),
`cli.main` (218), `cli_animex.main_axp` (185), `ui._curses_form` (168), `playlist.run`
(118).
→ Split into small helpers / a window class (naturally solved by #2/#3).

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
2. Retire the duplicate GUI controllers (#3) — the biggest duplication win.
3. Extract the shared Options model (#1).
4. Collapse the CLIs onto `Session` (#2).
5. Delete/relocate the unused title helpers (#5).
