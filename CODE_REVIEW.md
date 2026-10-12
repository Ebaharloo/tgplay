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

### 4. Large functions  (low risk, mechanical)
`gui_all.app` (784 lines), `cli.main` (218 → ~180 after #3), `cli_animex.main_axp`
(185), `ui._curses_form` (168), `playlist.run` (118).
→ Split into small helpers / a window class (naturally solved by #1/#2).

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
3. Extract the shared Options model (#1).
4. Collapse the CLIs onto `Session` (#2 — the curses/direct paths still build
   providers manually).
5. Delete/relocate the unused title helpers (#5).
