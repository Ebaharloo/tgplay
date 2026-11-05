# tgplay test audit — 2026-11-05

Read-only audit. No production or existing test file was changed. Mutation probes were
run on a throwaway copy at `/tmp/tgmut`.

## 1. Suite health

```
cd /home/user/coding/python/tgplay
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q
→ 104 passed, 1 warning in 37.18s   (30.91s / 28.96s / 29.77s on repeat runs)
```

- 104 tests in 31 files, 3 436 lines of test code, 464 `assert` statements. Zero tests with no assert.
- 0 failures, 0 xfail, 0 `pytest.mark.skip`. **But 6 GUI tests return early and pass green** when
  PySide6 is missing (`print('SKIP …'); return`) — see §3.
- 1 warning: `QMouseEvent(...)` deprecation in `test_continue.py::test_shelf_widget`.
- No `conftest.py`, no `pytest.ini`/`pyproject` `[tool.pytest]`, no `pytest-randomly`
  (so `-p no:randomly` is a no-op here; order is always directory order).
- Order independence: every one of the 31 files passes standalone
  (verified file-by-file). Global run passes. No order coupling found.
  One hidden global leak: `test_cli_session._cfg()` sets `AGP_CONFIG_DIR` and never pops it
  (harmless today, it is a landmine for any future test that builds `Config()` without `home=`).
- Network: **the suite is not network-free.** Two live-network dependencies
  (`test_providers::test_two_line_titles`, `test_titles::test_metadata_title_merge` /
  `test_retry_missing_each_run`) and one real DNS lookup per AnimeX test
  (`cdn.example` via `_m3u8_quality`). They account for almost all of the 29–37 s runtime.
- Slowest 5 (`--durations=15`): 5.04 s `test_simkl_account::test_device_login_and_library`,
  4.79 s `test_animex::test_catalog_and_audio`, 4.64 s `test_animex::test_stream_and_rotate`,
  3.07 s `test_animex::test_audio_fallback_no_dub`, 2.67 s `test_titles::test_metadata_title_merge`.
  None of that time is logic; it is HTTP/DNS timeout.

Modules with **no behavioural test at all**: `tp/playlist.py` (only `_save`/`progress_for` touched),
`tp/session.py` (only mocked, plus the axp label-clean test), `tp/gui.py` (Tkinter fallback),
`tp/library.overview/_fetch_calendar`, `tp/continuewatch.CoverArt`, `tp/cli_telegram.main_tgp`
(arg dispatch only).

## 2. Coverage matrix

Legend: **real** = asserts observable behaviour and would fail if the feature broke;
**unit** = real assertions, but collaborators faked so the wiring is untested;
**smoke** = asserts "it ran / it was called".

| # | Feature (FEATURES.md) | Test(s) | Kind | What is NOT covered |
|---|---|---|---|---|
| 1 | Search (both sources, tagged), debounce | `test_search.py::test_animegate_search`, `::test_animex_search`, `::test_search_all_sources`; `test_gui_all.py::test_sidebar_click_shows_source_choices` | real | Per-source failure isolation in `search.search_all` (each provider is wrapped in `except: pass` — never tested); debounce timing; empty/whitespace already covered |
| 2 | Paste link / `@channel` routing | `test_cli_all.py::test_route`, `::test_dispatch_calls_right_main` | real | `route()` for a bare `t.me/c/5`, trailing whitespace; `dispatch('search', …)` fallback only asserted by first element |
| 3 | Source pinning per link (MAL id) | `test_finder.py::test_pin_id_to_link`, `::test_entry_ids_are_trusted_and_pinned`, `::test_fuzzy_record_must_match_the_title` | unit | Pin → `Session.mal_id` → `Playlist(mal_id=…)` → `SkipService(mal_id=…)` chain. **UNCOVERED** (the just-shipped bug) |
| 4 | Session load per source `agp` | — | **UNCOVERED** | No test calls `open_session('agp', …)`; `test_cli_session` patches it out |
| 5 | Session load per source `axp` | `test_session_loader.py::test_axp_episode_labels_cleaned`; `test_animex.py` (provider) | unit | Audio selection reaching session, groups/labels from a real `axp` open, missing-MAL path |
| 6 | Session load per source `tg` / `tgp` | — | **UNCOVERED** | `_telegram_target` parsing, `window`/`matcher` knobs, `SingleFileProvider` vs `TelegramProvider` choice |
| 7 | Episode list + episode names (MAL→Bangumi→Simkl) | `test_core.py::test_episodes`; `test_titles.py` (6 tests); `test_bangumi.py` (3); `test_simkl.py::test_resolve_episodes`, `::test_metadata_fallback`; `test_translate.py` (2) | real | Paint-guard inside `open_session` (only `TitleService` directly); circuit breaker `meta_down.json` (never exercised); generic-"Episode N" drop via session |
| 8 | Resume position (`progress.json`) | `test_progress.py::test_progress_roundtrip` | real (storage only) | `Session.play` → `start` → `Playlist` → `mpv --start`. Killed by mutation, suite stayed green |
| 9 | Continue-watching shelf (data) | `test_continue.py::test_items` | real | `CoverArt._fetch` (network + `posters.json` TTL) never tested; `limit=10` boundary; `next_ep`/`total` None handling partly |
| 10 | Shelf widget (cards, click, collapse) | `test_continue.py::test_shelf_widget` | real | Click → resume path in `MainWindow`; right-click "Choose source…"; poster download worker; **doc says the shelf hides while search results are open, code/tests say it never hides** (see §3) |
| 11 | Cast dialog | `test_characters.py` (6 tests) | real | Portrait download thread (`_referer_for` tested, actual fetch not); favourites/detail fields beyond name+VA; worker cancellation on dialog close |
| 12 | Simkl auth (device/PIN) | `test_simkl_account.py::test_device_login_and_library` | real | `start_device`/`poll_device` directly; pending/expired/`slow_down` errors; `login()` poll loop |
| 13 | Simkl token refresh on 401 | — | **UNCOVERED** | `SimklAccount._api` 401 → `refresh()` → one retry; refresh failure path. No fake ever returns 401 |
| 14 | Simkl calendar / feed / remaining | — | **UNCOVERED** | `library.overview()`, `_fetch_calendar()` (id filter, date window, sort), aired/remaining split, `+ Simkl list` (`add_to_list`) |
| 15 | Simkl watch sync (finish / ≥70 %) | `test_simkl_account.py::test_device_login_and_library` (POST body); `test_tracking.py::test` (AniList side) | unit | `Playlist._mark` wiring, `WATCHED_FRAC` = 0.70 branch, `--no-sync`/`sync:'off'` short-circuit, rc==4 quit-then-sync |
| 16 | History / recent links + searches | `test_history.py` (2); `test_ui.py::test_recent` | real | History picker widget, cap of 20 for queries (only links asserted), `last_link_for` name-normalisation beyond casefold |
| 17 | Playback options normalisation | `test_options.py` (4); `test_setup.py` (3) | real (strong) | Legacy `skip: False` → `'all'` at play time (session code) not asserted end-to-end; `sync` tri-state through the form |
| 18 | Skip via mkv chapters + ani-skip | `test_skip.py::test_order`, `::test_notes`; `test_core.py::test_chapters`, `::test_chapters_flags` | unit | **Everything downstream**: direct/HLS probing, `headers=` to ffprobe, pinned `mal_id`, flags landing in the mpv argv. Fully faked |
| 19 | Next-episode prefetch trigger | `test_prefetch.py::test_full`, `::test_window`, `::test_cancel` | unit | `Playlist._trigger`, `PosWatcher.fire_when/on_fire`, "no prefetch for direct streams", cancel on playback start |
| 20 | Prefetch resume (`.part` continues) | — | **UNCOVERED** | `Prefetcher.prefetch` `got = os.path.getsize(part)` append path never exercised (only "already complete" idempotency) |
| 21 | Cut / start | `test_player.py::test_command` | unit | `Session.play` computing `start` from resume and passing `cut`; `--start` in `extra` winning |
| 22 | mpv command building | `test_player.py::test_command`, `::test_gpu_context` | real | Malformed-flag filter (`=…`), `--sub-file` extras, `--referrer` for axp, `--end=-N`, ipc position |
| 23 | Retry-on-open (rc==2) + rotate | `test_animex.py::test_stream_and_rotate` | unit | `Playlist` retry loop (max 2), proxy `streams.pop`, give-up after 2 |
| 24 | Auto-advance through the list | `test_core.py::test_episodes` (planning only) | unit | `Playlist.run` looping over >1 episode; progress pointer after each |
| 25 | Range proxy | `test_proxy.py::test_proxy_ranges`, `::test_local_mirror`, `::test_port_fallback` | real | Client disconnect mid-stream; `HEAD`; concurrent readers |
| 26 | Cache (report/clean/evict/geometry) | `test_proxy.py::test_cache`; `test_quality_cache.py::test_cache_report_clean` | real | Family LRU under `budget` (evict called manually); `.done`/`.win` sidecar corruption |
| 27 | Quality from filenames | `test_quality_cache.py::test_quality` | real | `tgp` provider wiring of groups |
| 28 | Telegram byte source | `test_providers.py::test_telegram_source`, `::test_retry_and_logout` | real | `TelegramProvider.load()` file scan/`--window`; session build (`open_session('tgp')`) |
| 29 | Connection lights + fix hints | `test_status.py` (5 tests) | real | Strip colours are hardcoded hex (brittle); Simkl connect dialog itself untested |
| 30 | Log / crash wrapper | `test_app.py` (3) | real | Crash **dialog** (`AGP_NO_DIALOG=1` disables the thing under test) |
| 31 | Icon install | `test_icon.py` (2) | real | — |

## 3. Weak / misleading tests

1. **`test_providers.py::test_two_line_titles` — secretly hits the live network.**
   Lines 192-199 define `fake_search(...)` but never install it (dead code); `lib.find_source`
   then calls the real `search_all` against animegate/animex. Proof: with
   `http_proxy=https_proxy=http://127.0.0.1:9` it fails (`AssertionError: None`) while 99 others pass.
   The test passes today only because the real sites answer.
2. **`test_animex.py` (3 tests) — header lies: "Network-free: a fake backend".**
   `Fake` overrides `_json` and `_probe`, but not `_m3u8_quality`, which uses the real
   `HttpClient` on `https://cdn.example/x/master.m3u8`. That is 4.8 / 4.6 / 3.1 s of DNS
   timeout per test — the entire "why is the suite 30 s" answer.
3. **`test_titles.py::test_metadata_title_merge`, `::test_retry_missing_each_run` — real HTTP.**
   `Metadata._mal_title` → `refresh_titles` → `bangumi_titles` + `simkl_titles` with the real
   client (only `_mal_titles` and `_cjk_title` are stubbed). 2.7 s / 1.9 s.
4. **6 GUI tests silently pass without PySide6** (`test_continue::test_shelf_widget`,
   `test_gui_all::test_load_and_play`, `::test_sidebar_click_shows_source_choices`,
   `test_session_loader::test_unified_window`, `test_characters::test_dialog_headless`,
   `test_status::test_strip_widget`). On a headless CI box the whole GUI layer "passes" having
   executed nothing. `pytest.importorskip('PySide6')` would at least mark them skipped.
5. **`test_session_loader.py::test_unified_window` — smoke.** One assert: the loader was called with
   `('agp','u1')`. A window that renders nothing and closes instantly passes.
   Depends on the `AGP_GUI_TEST='close'` production hook.
6. **`test_prefetch.py::test_cancel` — tests the easy half.** It calls `cancel()` *before* any
   download starts. The documented feature is "cancellable when playback starts" (mid-flight);
   `prefetch()` could delete the cancel check inside its write loop and this still passes.
7. **`test_options.py::test_saved_shape_and_merge_matches_setup` — fake comparison.**
   `saved = setup.load(p) if False else {...}` (line 63): the `setup.load` branch is dead and the
   "matches setup" claim compares against a hand-written dict. Real `setup.save` output is only
   compared in `test_setup.py`, and not for the `audio`/`sync` keys.
8. **`test_skip.py` — pure self-fulfilment.** Both collaborators are fakes
   (`FakeResolver`, `FakeAni`); it never touches ffprobe, ani-skip, mpv or `Playlist`.
   Proven: deleting the direct-stream probe *and* the flags argument from the mpv command keeps
   all 104 green.
9. **`test_cli_session.py` — `FakeSession` shadows the real `Session`.** It proves the CLI picks
   episode numbers and calls `close()`. It cannot see proxy start/stop, resume, skip or tracking.
   Proven: forcing `skip_mode='off'` and `start=None` in `Session.play` keeps all 104 green.
10. **`test_continue.py::test_shelf_widget` locks behaviour that contradicts FEATURES.md.**
    It asserts `shelf.sync(results_visible=True)` must NOT hide the shelf ("app state must never
    hide the shelf"), while FEATURES.md §Continue watching says "it hides by itself while search
    results are open". One of the two is wrong; the test currently defines the truth.
11. **`test_status.py::test_strip_widget` — brittle.** Asserts `'#98c379'` / `'#e06c75'` in the
    stylesheet, i.e. the palette, not the state→colour mapping. Any theme tweak breaks it without
    a behavioural regression.
12. **`test_core.py::test_config` — odd assertion.** `Config(home=tmp)` yet asserts `progress`
    ends with `/.config/tgp/progress.json` (home ignored for that path). It is a real assertion,
    but it locks in a surprising behaviour nobody documented.
13. **Flaky-by-construction timing loops**: `test_gui_all::test_sidebar_click_shows_source_choices`
    (2 s and 3 s `time.sleep` deadlines), `test_characters::test_dialog_headless` (2 s deadline).
    They pass at 0.5–3 s today; a loaded CI box can flip them.
14. **`test_simkl.py::test_dig`** — three passthrough asserts on a private helper; near-zero value.

## 4. Missing assertions, ranked (not written — for the next pass)

1. **`Playlist.run` with a direct/HLS stream**: fake `SkipService` recording its kwargs; assert
   `url == stream.url`, `headers == stream.headers`, and that the returned flags appear in
   `player.command(...)`'s argv. Catches the shipped bug class.
2. **Pinned MAL id end-to-end**: `finder.pin()` → `open_session('agp', …)` → `Session.mal_id` →
   `Playlist(..., mal_id=…)` → `SkipService.flags(mal_id=41219)` for a provider that has **no**
   `mal_id` attribute (AnimeGate). This is the second half of the bug.
3. **Resume → mpv**: save `{'ep': 64, 'pos': 207}`; `Session.play([64], …)` must yield
   `--start=207`; `Session.play([65], …)` must not.
4. **Skip flags reach mpv at all**: `skip_mode='all'` + a chapter-based fake must produce
   `--script-opts=skip-op_start=…` inside the built command (not merely returned by `SkipService`).
5. **`SimklAccount._api` 401 → refresh once → retry**: fake `refresh()` returns a token, assert
   two calls total; fake returns `None`, assert one call and `None`/error surfacing (red light).
6. **`library.overview`**: given watch ids + a calendar payload, assert only the user's ids,
   only `now <= air <= now+14d`, soonest-first, and aired merged with `kind='aired'`.
7. **`open_session('tgp', '@chan')`**: labels built, `window`/`matcher` forwarded, and
   `open_session('tg', 'chan 5')` picks `SingleFileProvider`; these four source branches are
   currently all-or-nothing untested.
8. **`Playlist` retry-on-open**: `player.play` returns 2 twice then 0 → `provider.rotate()` called
   twice, third attempt plays; returns 2 three times → loop exits, progress untouched.
9. **`Playlist` watched fraction**: `rc=4`, `last=1400`, `duration=1800` (77 %) → progress moves
   to ep+1 and `tracker.mark_watched` called; 60 % → neither.
10. **Prefetch trigger**: `PosWatcher.fire_when/on_fire` via a fake IPC socket, or drive
    `Playlist._trigger(30, 0.6)` directly: fires once past 60 % of `(d-cut)`; direct stream → no fire.
11. **`Prefetcher` resume**: truncate a `.part`, call again, assert the byte range appended
    (not restarted) and `.win` `lo` preserved.
12. **`search_all` failure isolation**: `animex.search` raises → agp results still returned.
13. **One-video-at-a-time**: two `play()` calls while `state['playing']` → the second is ignored
    (FEATURES.md promise, zero coverage).
14. **`CoverArt.covers`**: two MAL ids, one cached fresh → one batched AniList request, merged into
    `posters.json`; HTTP failure → empty dict, no crash (shelf posters).
15. **Network-free AnimeX**: stub `_m3u8_quality` (or `http.open`) and assert the `· 1080p` label
    suffix from an `#EXT-X-STREAM-INF RESOLUTION=1920x1080` body — also removes 12 s of runtime.

## 5. Would any current test have caught the skip bug?

**No.**

The bug chain is: `Playlist.run` computed a probe URL only for proxied streams
(`url if (not direct and head_warm) else None`), so HLS/direct streams were never chapter-probed;
the MAL id resolved/pinned at session level was never handed to `Playlist`, so ani-skip had nothing
to call for `agp` (whose provider has no `mal_id`); and the resulting `flags` were concatenated into
the mpv command without any test observing that argv.

Why nothing catches it:

- `tests/test_skip.py` exercises only `SkipService.flags()` with a fake resolver/ani-skip and
  asserts the *return value*. It never imports `tp.playlist`.
- `tests/test_player.py` exercises `Player.command()` in isolation; it never sees skip flags.
- `tests/test_progress.py` is the only file importing `Playlist`, and it calls `_save` / `progress_for`
  only — `Playlist.run` is never executed by the suite.
- `tests/test_cli_session.py` replaces the whole `Session` with `FakeSession`, so
  `Session.play → Playlist.run` is short-circuited.

Empirical proof (throwaway copy, `/tmp/tgmut`, real suite run against it):

| Mutation | Result |
|---|---|
| Revert `probe_url, probe_hdr = stream.url, (stream.headers or {})` → `None, None` | 104 passed |
| Drop `mal_id=self.mal_id or …` (provider-only) | 104 passed |
| Remove `+ flags` from `player.command(extra=…)` | 104 passed |
| Force `skip_mode='off'` and `start=None` in `Session.play` | 104 passed |

Three independent regressions of the exact shipped bug, plus a total loss of resume and skip,
all invisible to the suite. Until a test drives `Playlist.run` with a fake player and inspects the
argv, the skip/resume/prefetch/tracker wiring has no regression net at all.
