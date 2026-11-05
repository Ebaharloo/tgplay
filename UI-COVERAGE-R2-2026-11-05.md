# UI coverage audit, round 2 - fixed build

Date: 2026-11-05 · Window: `tp/gui_all.py` (`MainWindow`)
Method: same offscreen harness as round 1, re-pointed at the fixed tree.
Every verdict comes from **firing the control** and reading the result: real `QMouseEvent` /
`QKeyEvent` on the widget, `state['msg']`, the status label, table/list contents, geometry via
`mapTo(window)`, and the arguments handed to `Session.play()` / `Session.stop()`.
No application code or tests were changed in this pass.

Harness (outside the repo):
- `~/.hermes/cache/scratch/ui_coverage_r2_base.py` - round-1 harness re-run against the fixed build
  (75 observations, 24 screenshots; some of its old labels are stale by design).
- `~/.hermes/cache/scratch/ui_coverage_r2_claims.py` - 21 focused observations for the 11 fix claims.
- Raw data: `~/.hermes/cache/scratch/uicov-r2/obs.json`, `.../claims.json`.
- Run: `env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/bin/python <harness>`.
- Screenshots: `ui-coverage-r2/` (`R2-*.png` are this pass; `01-24` are the full re-walk).

Stubs unchanged from round 1: `loader` -> `FakeSession` (12 episodes, resume 5), `ShowFinder`
(2 canned candidates + `pin()` recorder), logged-out `SimklAccount`, `StatusProbe`
(green Simkl / red AnimeGate / amber AniList), 3-row `CharactersService`. No network, no mpv.

## 1. Verdict counts now vs round 1

| Verdict | Round 1 | Now | Delta |
|---|---|---|---|
| WORKS | 51 | **60** | +9 |
| BROKEN | 16 | **7** | -9 |
| WORKS-BUT-HIDDEN | 3 | **3** | 0 |
| MISSING | 3 | **3** | 0 |
| UNREACHABLE | 0 | 0 | 0 |
| **total** | **73** | **73** | |

The nine repaired features: search-with-no-hits message, Enter-before-results starts a search,
`+ Simkl` play buttons cold (now disabled), history duplicate titles (one row per link),
extra mpv flags quoting, "stopped" expiry, Stop-with-no-session copy, lights refresh reloading
the calendar, sidebar auto-refresh after a sync.

Still BROKEN (7): Enter-on-results hint lie; cold-start shelf blank; `+ Simkl list` enabled with no
show; invalid `Cut last N s`; cut/extra placeholders read as values; long status clipped;
episode table clipped at the declared minimum size.

Still HIDDEN (3): pin ids, second-play guard, non-skip log lines. Still MISSING (3):
back from history to results, Simkl/MAL link for the loaded show, episode double-click.

## 2. The 11 claims

| # | Claim | Verdict | Measured evidence |
|---|---|---|---|
| 1 | Min window 1220x900: episode table + action bar fully inside, at min and 1360x1000 | **FAIL** | 1360x1000: table y 733-930, bar 956-990, viewport 161 px, last row 131-160 -> fits. 1220x900: table y 692-872 but its group box ends at 839 and the splitter at 848 (bar starts 856); only 114 of the 144 px viewport are visible, and after `scrollToBottom` rows 9-11 show while row 12 (viewport 114-143) is entirely clipped. Every named widget is inside the window rect, but the table is clipped by its parent group box. `R2-05-min-size.png` |
| 2 | Zero hits: head shows "no hits for …", status shows a message, no blank slot | **PARTIAL** | head = `Results · no hits for “zzzznothing”`; status = `no results for “zzzznothing” — try another spelling, or paste a link` (msg_until +8 s); list hidden, but the results stack is still visible at 191 px with nothing but the header above empty space. `R2-02-empty-results.png` |
| 3 | Enter with no results starts a search (status "searching …"), not load row 0 | **PASS**, new side effect | immediate: msg `searching “zzzznothing” …`, `debounce.isActive()=true`, `loads=[]`; 0.9 s later finder calls = 1, results = 2. But the message is never cleared when results arrive (see §3). |
| 4 | Play from here / Only selected / All / Stop disabled cold, enabled after session; Stop cold says "nothing playing", disappears ~5 s | **PASS** (Stop copy only reachable by direct call) | cold enabled = `[false,false,false,false]`; clicking all four: plays 0, stops 0, msg `""`. `_do_stop()` with no session -> msg/status `nothing playing`, `msg_until` +4.9 s. After `set_session`: all four true, Play all -> `chosen=[1..12]`. Stop -> `stopped`, +4.7 s; after 5.3 s status back to `ep 5   12:00`. The button itself cannot fire the "nothing playing" branch because it is disabled. `R2-03-cold-stop.png`, `R2-06-stopped.png`, `R2-07-stopped-expired.png` |
| 5a | "stopped" and skip receipts expire | **PASS** | stopped cleared after the real 5.3 s wait. Skip: status `skip[all]: chapters 12-90 (op) — resume where you left off`, `msg_until` +8.6 s after a 1.4 s pump (~10 s); with `msg_until` moved into the past and `_refresh_status()` the message clears to `ep 5   12:00` (expiry simulated, not a 10 s wall-clock wait). `R2-09-skip-receipt.png` |
| 5b | Status line elides instead of clipping a long message | **FAIL** | 247-char message: text is 1439 px, label is 573 px, `ends_with_ellipsis=false`, `wordWrap=false`, tooltip does not contain the message. Ends mid-word at the `Close` button (`…AnimeGate s`). `R2-08-status-long.png` |
| 6 | Sidebar auto-refresh after a sync reloads feed/history (`side_timer` -> `load_side`) | **PASS** | pushed `synced: ep 5 -> Simkl`: timer armed, feed `SENTINEL` -> `Simkl not connected — click the ● Simkl light above`, history `SENTINEL-HIST` -> same placeholder, timer single-shot and inactive afterwards. |
| 7 | Lights ↻ tooltip promise is true (probe + calendar reload) | **PASS** | feed `OLD-1/OLD-2` replaced by the reloaded placeholder within one pump; lights updated to `Simkl: connected as abe`, `AnimeGate: cookie expired`, `AniList: not linked (optional)`. `R2-10-lights-refresh.png` |
| 8 | One history row per link; same title from two sources = two rows | **PASS** | after adding `agp` and `axp` links both named "One Piece": exactly two rows, `[just now, axp, One Piece]`, `[just now, agp, One Piece]`. `R2-11-history-dup.png` |
| 9 | Quoted extra mpv flags survive as one argument | **PASS** | `--title="One Piece" --volume 80` -> `["--title=One Piece", "--volume", "80"]` from both `to_raw()` and the recorded `play()` call (shlex; quotes stripped, one argv item). |
| 10 | Skip receipt visible in the status line from the log queue | **PASS** | `_lq.put('skip[all]: chapters 12-90 (op)')` + 1.4 s -> status shows that exact line; `msg_until` ~10 s. |
| 11 | Anything still hidden | **CONFIRMED STILL HIDDEN** | pin: `pins=1`, no message/receipt. prefetch/mark lines: tooltip only, status text unchanged. Second play while playing: 0 plays, msg `""`. Double-click episode: 0 plays, msg `""`. `link_lbl` still source URL only. `hist_btn` twice stays on history (no way back). |

## 3. Newly broken by the fixes

1. **`searching “q” …` never clears after a successful Enter search.** `_accept_typed` sets
   `state['msg']`/status for the no-results case and starts the debounce; `_fill_results(items)`
   does not clear `msg` (and no `msg_until` was set). With the stub finder returning 2 hits:
   status/msg still `searching “zzzq” …` immediately after results arrive **and 8.7 s later**,
   while the head correctly says `Results · 2 for “zzzq”`. The typing path (`A1`) is unaffected.
   Repro: type in a cold box with no results, press Enter, wait.
2. Not a break but an incomplete fix: **the new 1220x900 minimum does not give the episode table
   enough height**. The table widget still runs 33 px past its group box and 24 px past the
   splitter; the last episode row is invisible at the declared minimum (claim 1).
3. Cosmetic overlap of messages: the zero-hit status message duplicates the header text and
   leaves the 191 px blank slot the claim said was gone (claim 2).

No regression found in the core paths re-driven after the fixes: search -> result click loads
(`axp:one-piece`), play all sends 12 episodes, history renders/loads, close stops all five timers.

## 4. Remaining top defects, ranked

1. **Episode table clipped at the window's own minimum (1220x900).** Table 692-872, group box ends
   839, splitter 848, bar 856: the bottom 33 px of the table (and the last episode row) are cut.
   At 1360x1000 it fits. Fix: raise the minimum height to ~950 or let the splitter shrink the table
   (`R2-05-min-size.png`).
2. **Enter on a populated result list still loads row 0 blind**, while the hint still says
   "Enter opens the source picker for the best match" (A4: `loads=[["agp", "...one-piece-1074"]]`,
   no dialog). Claim 3 fixed only the empty-list half.
3. **Long status messages are hard-clipped**, no ellipsis and no full-text tooltip - the only
   message surface in the window (`R2-08-status-long.png`).
4. **New: stale "searching …" status** after the Enter-initiated search succeeds (§3).
5. **Cold-start continue-watching shelf is a blank 242 px box**: count text `""`, only the
   `▶ Continue watching` header, no placeholder until `set_items([])` runs.
6. **No Simkl/MAL link for the loaded show** (MISSING): `link_lbl` carries only the source URL.
7. **`Cut last N s` accepts junk** (`abc` -> `cut=null`, no message/red border) and the empty
   cut/extra fields still display `0` / `--volume 80` as placeholders, reading as set values.
8. **`+ Simkl list` is enabled with no show**; click only posts `load a show first` (Cast is
   correctly disabled in the same state).
9. **No way back from the recent-links table to the previous results** (MISSING): `hist_btn`
   calls `show_history(force=True)` every time; two clicks stay on history.
10. **Double-click an episode does nothing** (MISSING); **a second Play while one video runs is
    silent** (`one video at a time` only in a comment).

## 5. What is still unverified

- Real mpv playback, streaming, and real Simkl / AniList / AnimeGate calls: no network or mpv in
  this harness. `Session.play()` arguments and `Session.stop()` calls were inspected instead of a
  playing video.
- Quoted-flag handling was verified at `to_raw()` / `Session.play()`; mpv itself was never invoked,
  so "mpv accepts the argv" is inferred, not observed.
- Sidebar reloads were observed through the stubbed (logged-out) Simkl path; a real connected
  calendar was not fetched.
- Skip-receipt expiry used a simulated elapsed `msg_until`, not a 10 s wall-clock wait; "stopped"
  expiry used a real 5.3 s wait.
- Offscreen platform plugin: fonts differ and emoji can render as boxes; single palette, no
  HiDPI, no window manager. Popup menus/dialogs were intercepted rather than clicked in a native
  popup.
