# DEV — Recently-aired rail, sidebar options, Simkl state propagation

Date: 2026-11-05 · Spec: `PLAN-RECENT.md` (F0..F6) · branch state: working tree

## Suite

```
cd /home/user/coding/python/tgplay && env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q
137 passed, 1 warning in 10.88s
```

Baseline was 119 passed; +18 new (14 in `tests/test_recent.py`, 4 in
`tests/test_ui_recent.py`). The one warning is the pre-existing
`QMouseEvent` deprecation in `tests/test_continue.py`.

## What was built

### F0 — real Simkl data

- **`tp/simkl_extra.py`** (new): `SimklExtra(cfg, http=None, acc=None)`
  - `relations(simkl_id)` → `GET /anime/{id}?extended=full` → `relations[]`,
    cached in `~/.config/tgp/relations.json`, TTL 7 days.
  - `episodes(simkl_id)` → `GET /anime/episodes/{id}` → episode list (accepts
    a bare list or `{"episodes": [...]}`), cached in `episodes.json`, TTL 1 day.
  - Both go through `SimklAccount._api` (so the 401 → token-refresh path
    applies). A failed fetch logs via `tp.log` and returns the stale cache,
    else `[]` — never raises into the GUI. Cache write failures are logged too.
- **`tp/config.py`**: `Config.relations` / `Config.episodes` paths.
- A show's seasons are resolved from the relation graph, not from titles:
  `RecentlyAired` accepts a `relations` map keyed by simkl id. Both live
  shapes are accepted: the new row carrying a direct `prequel` to a watched
  show (Simkl's per-show view) and a watched show carrying a direct `sequel`
  to the new row. `prequel`/`side_story`/non-direct links of a watched show
  never mark anything as new.
- `days_ago` now comes from the newest **aired** episode date (episodes map),
  falling back to the row's `air_date`; the day window is applied to the same
  effective date, so a show whose `next_to_watch` date is stale still lands in
  the window when a newer episode aired.
- New field `behind = max(0, newest_aired_episode - watched)`; the poster card
  appends `· +N new` when non-zero.

### F1 — `tp/recent.py` (new, pure, no Qt)

`RecentlyAired(cfg, http=None, art=None).items(rows, *, days=14,
include_new_seasons=True, limit=20, known_titles=(), relations=None,
episodes=None)` plus `base_title()`, `day_of()`, `clamp_days()`,
`clamp_limit()`, `load_rails()`, `save_rails()`, `DEFAULT_RAILS`.

Rules 1–9 implemented: window with clamp (0/junk → 14), started-or-followed
(watched/last_watched, watching+plan-to-watch with `next_ep>=1`, new season),
relation-first new-season flag with base-title fallback, base-title
normalisation, dedupe by base (newest air date wins), sort by air date then
`next_ep`, `days_ago`, the full output dict (+`behind`), and the
Simkl-poster → AniList-cover image path through `CoverArt` (no fetch for rows
that already have a poster). No HTTP inside `items()`.

### F2 — two rails in one slot

`ContinueShelf` header is now two exclusive checkable `QToolButton`s
(`▶ Continue watching`, `🆕 Recently aired`), a fixed-width count label (so
the mode never shifts the gear/chevron), the settings gear and the collapse
chevron. `set_items()` still draws whatever list it is given; `set_mode(mode)`
only changes which list the window feeds in (via `on_mode`). Scroll area stays
`setFixedHeight(206)`.

### F3 — gear settings

`RailsDialog` (QDialog, three groups: Continue / Recently aired / Sidebar),
OK applies + saves, Cancel discards. Values live in `ui.json` under
`window.rails` and are clamped on load and on save (days ∈ {7,14,30}, limit
1..50, booleans coerced). `save_rails` merges into `window` so `split` and any
older keys survive, and `_remember_window_state` now merges instead of
replacing the whole `window` dict (it would have wiped `rails`).

### F4 — sidebar

- Feed table has a 4th `Aired` column (`today`, `1d`, `2d`, …), shown only
  when `sidebar.show_days` (`setColumnHidden`), populated for every row that
  carries `days_ago`.
- Feed filter adds `Recent`, built from the F1 window with
  `sidebar.days` + `sidebar.include_new_seasons`; rows show `🆕 today/2d ago`
  and `· new season`, and keep their entry dict for the existing right-click
  Simkl/load menu.
- A gear next to the filter opens the same dialog.

### F5 — one refresh path

`MainWindow._refresh_library()` is the single path: one worker call to
`library.overview()` (which now also returns `rows`, so both rails come from
one fetch), then `_fetch_extra()` on the same worker fetches relations +
episodes for the shows inside the window (deduped by simkl id, hard cap 20
shows, cached), then `ContinueWatching.items(limit=continue.limit)` and
`RecentlyAired.items(...)`. The payload lands through `_libq` and re-renders
shelf (current rail), feed, history table and the Recent list; posters
download on the existing poster worker.

Called from: `add_current()` success (via `feed-refresh`), `_set_status`
success, a sync line in `_drain_log` (through the existing 1.5 s debounce
timer, now wired to `_refresh_library`), `show_history(force=True)`, the
sidebar `↻` button and the status-strip refresh. `load_side()` remains as a
one-line alias so every existing caller/test keeps working. Nothing blocks the
GUI thread.

### F6 — tests

## Tests added (`assertion` each)

`tests/test_recent.py` (14):

1. `test_1_window_keeps_three_of_five_rows` — 5 rows in 14 days → exactly
   `['A','B','C']`; the 20-day-old and the future row are dropped.
2. `test_2_junk_days_falls_back_to_fourteen` — `days=0`, `'junk'`, `99` give
   the same result as `days=14`.
3. `test_3_started_row_without_air_date_is_dropped` — `None` and
   `'not-a-date'` rows → `[]`.
4. `test_4_new_season_toggle` — with the flag the newest (S2, unwatched) row
   is the one card and `is_new_season is True`; without the flag only the
   watched S1 row remains.
5. `test_5_base_title_match_marks_new_season` — unwatched `Xian Ni 2nd
   Season` included via `known_titles`, `is_new_season is True`,
   `base == 'xian ni'`.
6. `test_6_dedupe_keeps_newest_air_date` — two rows, same base → one card,
   title/days_ago of the newer row.
7. `test_7_sort_order_and_limit` — order `TodayHigh, TodayLow, Mid` (date desc
   then `next_ep` desc) with `limit=3`.
8. `test_8_days_ago_today_and_n_days_back` — `days_ago == 0` and `== 5`.
9. `test_9_base_title_table` — `One Piece (1999)`, `One Piece Season 2`,
   `Xian Ni 2nd Season`, `Renegade Immortal Part 2`, blank → expected bases.
10. `test_10_poster_simkl_then_anilist` — Simkl poster URL wins; AniList
    cover used when the poster is missing; art called with only the missing
    MAL id.
11. `test_11_relations_mark_new_season_and_nothing_else` — direct `prequel`
    on the new row and direct `sequel` on the watched row both include it with
    `is_new_season True`; `include_new_seasons=False` drops it; a watched
    show's `prequel`/`side_story` links do not include or flag it.
12. `test_12_episodes_newest_air_and_behind` — without the episodes map the
    stale row is out of the 7-day window; with it `days_ago == 0`,
    `behind == 2`, `air_date` from the newest aired episode, unaired episode
    ignored.
13. `test_13_extra_cache_ttl_and_failures` — first read makes 2 API calls,
    second read 0; ageing only the episodes entry refetches only episodes;
    a raising `_api` returns `[]` without raising.
14. `test_settings_roundtrip_is_clamped` — junk days/limit clamp to 14/50,
    `show_days` false survives, `ui.json` matches, and `window.split` is kept
    next to `rails`.

`tests/test_ui_recent.py` (4, offscreen, stub loader, fake `library.overview`,
`_fetch_extra` stubbed so no test does HTTP):

11. `test_11_rail_switch_keeps_the_layout` — clicking the rails swaps
    `shelf._items` A/A2 ↔ B/B2 and the rendered first card title; geometry of
    `box`, `results`, `table` is byte-identical before/after; switching back
    restores A/A2.
12. `test_12_dialog_roundtrip_and_shelf_limit` — dialog shows the defaults,
    `recent_limit=2` + `show_days=False` written to `ui.json`, and after the
    refresh the rail holds exactly 2 items and the `Aired` column is hidden.
13. `test_13_aired_column_follows_show_days` — header is `Aired`; with
    `show_days=False` in `ui.json` the column is hidden, the dialog reads that
    value, ticking it and applying un-hides it and persists it.
14. `test_14_one_refresh_updates_every_view` — a fake overview that changes
    between calls updates `state['recent']`, the rail list, the shelf, the
    feed title column and the history table in one `_refresh_library()`; the
    extra fetch is called once on the worker with the window (14).

## Not done / deviations (read this)

- **`last_aired` fallback is not wired.** `SimklExtra.relations()` returns the
  relations list (the agreed shape), so the `last_aired` field of the same
  `/anime/{id}` response is discarded. `days_ago` therefore falls back
  episodes → row `air_date`, not → `last_aired`. Add it if shows start
  appearing with an empty episode list and no `next_to_watch` date.
- **Gear "scrolled to Sidebar"** is implemented as keyboard focus on the
  Sidebar group: the dialog is small enough that it has no scroll area
  (building one for three groups would be dead weight).
- The relations/episodes window filter uses the row's `air_date` (the data we
  have before the fetch); a row whose stored date is stale and whose newest
  episode is inside the window is still picked up if it is in the fetched set,
  but a row whose stored date is *outside* the window is not fetched at all.
  Accepted: `overview()`'s aired rows already come from Simkl's own dates.
- `library.overview()` gained a `rows` key (one line) so the rail does not need
  a second library fetch; the calendar's 7-day `aired_days` behaviour is
  unchanged.
- Plan gate items I cannot do alone: review/test teams reading the diff and the
  UX re-walk of rails/gear/sidebar. I did an offscreen startup + rail-switch
  smoke run (window opens, both rails switch, 4-column feed, close clean).

## Files

New: `tp/recent.py`, `tp/simkl_extra.py`, `tests/test_recent.py`,
`tests/test_ui_recent.py`, this file.
Changed: `tp/gui_all.py` (rails, dialog, feed column/filter, `_refresh_library`,
`_fetch_extra`, `behind` on cards), `tp/config.py` (cache paths),
`tp/library.py` (`rows` in the overview result).
