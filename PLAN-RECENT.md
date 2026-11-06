# PLAN — Recently-aired rail, sidebar options, Simkl state propagation

Owner ask (2026-11-05): a second poster rail for **recently aired** shows, not
just in-progress ones; must include shows whose earlier seasons he watched even
if unfinished, and new seasons of shows he follows. Sidebar option to show how
many days since an episode aired. Separate settings for the poster rail and for
the sidebar, behind a small gear. Simkl state changes (drop / add / complete)
must reach history, calendar and posters.

## Data already available

`tp/library.py:overview()` returns `cal` (calendar: upcoming + aired rows),
`rem` (watching, next_ep set) and `hist`. Each row from
`SimklAccount.library()` is normalised and carries: `title, simkl, mal, anilist,
status, air_date, next_ep, watched, total, last_watched, poster`.
`tp/continuewatch.py` already turns `rem` into poster items (Simkl poster →
AniList cover fallback, cached in `posters.json`).


## F0 — Real Simkl data (verified live against the API, 2026-11-05)

Probed with the project's own `SimklAccount` (token auto-refresh) — use these
instead of title guessing:

1. `GET /anime/{simkl_id}?extended=full` returns
   `relations: [{title, year, poster, relation_type, is_direct, ids:{simkl,mal,anilist}}]`
   with `relation_type` in `sequel | prequel | side_story | parent | ...`.
   **A show's seasons are its `sequel` / `is_direct` relations.** Cache this
   per show in `~/.config/tgp/relations.json`, TTL 7 days, keyed by simkl id.
2. `GET /anime/episodes/{simkl_id}` returns every episode with
   `{episode, date, aired, title, runtime}` — the exact air date of the newest
   aired episode. Cache in `~/.config/tgp/episodes.json`, TTL 1 day.
3. `GET /sync/all-items/anime?next_watch_info=yes` rows already carry
   `watched_episodes_count, total_episodes_count, last_watched_at, status,
   show.ids{simkl,mal,anilist}, show.poster, show.year`. Seasons appear as
   separate library entries (Konosuba 1/2/3 are three rows), so a relation hit
   usually maps to a row you already have.
4. `/anime/{id}` also has `first_aired, last_aired, total_episodes, status,
   airs{day,time,timezone}` — use `last_aired` when the episode list is empty.

F1 changes because of this:
- New-season detection: **relations first** (sequel/is_direct of a show that is
  in history or the shelf), base-title match only as a fallback when the
  relation fetch failed or is unavailable offline.
- `days_ago`: from the newest **aired episode date** (episodes cache); fall
  back to the library row's `air_date`, then `last_aired`.
- New field `behind`: `newest_aired_ep - watched` (0 or negative → 0), so a
  card can say "3 new" instead of just a date.
- All network stays off the GUI thread and off the test path: `items()` takes
  already-fetched `relations` / `episodes` maps (dicts) so the pure tests never
  touch HTTP; the window fetches them on a worker and passes them in.

## F1 — `tp/recent.py`, pure data (no Qt)

```python
class RecentlyAired:
    def __init__(self, cfg, http=None, art=None)          # art = CoverArt
    def items(self, rows, *, days=14, include_new_seasons=True,
              limit=20, known_titles=(), relations=None, episodes=None
              ) -> list[dict]
```

Rules (each one a test):

1. Window: keep rows whose `air_date` is inside `[today-days, today]`.
   `days=7/14/30` are the only values the UI offers; 0 or junk → 14.
2. Started-or-followed: keep a row when any of
   a. `watched > 0` or `last_watched` set (he watched it),
   b. `status in ('watching', 'plantowatch')` and `next_ep >= 1`,
   c. `include_new_seasons` and the row's *base title* matches a title in
      `known_titles` (history/shelf) — this is the "new season of a show I
      watched, previous season unfinished" case.
3. New-season flag: `is_new_season = base title in known_titles and
   row.base_title != row.title` **or** (`watched == 0` and base title matched).
4. Base title: lowercase, strip trailing `season N`, `part N`, `2nd season`,
   `(YYYY)`, `tv`, `-`/`:` tails. `One Piece (1999)` and `One Piece` collapse.
5. Dedupe by base title, keep the newest `air_date`; one card per show.
6. Sort by `air_date` desc, then `next_ep` desc. Truncate to `limit`.
7. `days_ago = max(0, (today - air_date).days)`; a missing/bad date → drop the row.
8. Output dict: `title, base, next_ep, watched, total, pct, mal, simkl,
   image, air_date, days_ago, is_new_season, status` — `image` uses the same
   Simkl-poster → AniList-cover path as `ContinueWatching.items`.
9. No network in `items()`: posters come from `CoverArt` cache, fetch happens
   only for ids missing from the cache (same as continuewatch).

## F2 — Poster slot gets two rails

`ContinueShelf` header becomes: `▶ Continue watching | 🆕 Recently aired` as two
checkable tool buttons (exclusive), a count label, a gear, and the collapse
chevron. `set_items()` keeps drawing whatever list it is given; a new
`set_mode(mode)` only changes which list the window feeds it. Nothing else in
the layout moves (slot stays fixed height 206).

## F3 — Settings (gear), per rail

Stored in `ui.json` under `window.rails`:

```json
{"continue": {"limit": 10},
 "recent":   {"days": 14, "include_new_seasons": true, "limit": 20},
 "sidebar":  {"show_days": true, "include_new_seasons": true, "days": 14}}
```

A small `QDialog` (not a modal page) with three groups; OK applies + saves via
`config.save_json`, Cancel leaves everything. Values are validated by F1's
clamps (days ∈ {7,14,30}, limit 1..50).

## F4 — Sidebar

- Feed table gains a `Aired` column (`2d`, `today`) when `sidebar.show_days`.
- Feed filter combo gains `Recent` (uses the F1 window) next to
  Calendar / Remaining / All.
- `sidebar.include_new_seasons` filters the Recent view the same way F1 does.
- A gear next to the feed filter opens the same dialog, scrolled to Sidebar.

## F5 — Simkl state propagation (must be one path)

Add `MainWindow._refresh_library()`: one worker call to
`library.overview()` → re-render `shelf` (current mode), `feed`, `hist`, and the
Recent view. Call it after: `add_current()` success, a sync line in
`_drain_log`, `show_history(force=True)`, and the sidebar ↻. Test: a fake
overview whose rows change between calls must change all three views after one
`_refresh_library()`.

## F6 — Tests (all must pass, `env -u PYTHONPATH .venv/bin/python -m pytest`)

`tests/test_recent.py` (pure, no Qt):
1. window keeps 3 of 5 rows for days=14; drops future + older.
2. junk/0 days → 14.
3. started row without air_date is dropped.
4. new season of a watched show is included when `include_new_seasons=True`
   and excluded when False (same fixture).
5. unfinished previous season: base title match via `known_titles`, flag set.
6. dedupe: two rows same base title → one card, newest air_date wins.
7. sort order + limit.
8. `days_ago` 0 for today, N for N days back.
9. base-title normalisation table: `One Piece (1999)`, `One Piece Season 2`,
   `Xian Ni 2nd Season`, `Renegade Immortal Part 2` → `one piece`, `xian ni`,
   `renegade immortal`.
10. poster: Simkl poster path wins; AniList cover used when poster missing.

`tests/test_ui_recent.py` (offscreen Qt, same fake-loader harness as
`tests/test_regressions.py`):
11. the two rail buttons switch the shelf's data (fake items A/B) without
    moving any other widget (compare rects of search/results/episodes before
    and after).
12. gear dialog round-trips settings into `ui.json` and the shelf respects
    the new `limit`.
13. sidebar `Aired` column appears/disappears with `show_days`.
14. `_refresh_library()` with a fake overview updates shelf + feed + hist +
    recent in one call.

Gate: review + test teams read the diff; UX team re-walks rails/gear/sidebar.

## Out of scope (say so, do not build)

- Per-show "ignore" list, notifications for new episodes, AniList-only
  tracking source, poster rail sorting UI, day-window custom values.
