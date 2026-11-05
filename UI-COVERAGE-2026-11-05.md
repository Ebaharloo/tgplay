# UI coverage audit - tgplay unified window

Date: 2026-11-05 · Window: `tp/gui_all.py` (`MainWindow`, five fixed slots + right sidebar)
Method: offscreen PySide6 (`QT_QPA_PLATFORM=offscreen`), real widget tree, real handlers.
Every verdict below comes from **firing the control** (`QMouseEvent` press/release on the widget,
`QKeyEvent` on the search box, header clicks on `QHeaderView`, `QMenu`/`QMessageBox`/`QDialog`
intercepted so nothing blocks) and then reading the resulting state: `state['msg']`, the status
label, list/table contents, the session object, `history.json`, and the arguments handed to
`Session.play()` / `Session.stop()`.

Stubs (only I/O is faked, no UI code is patched):

| stubbed | replaced with |
|---|---|
| `loader(src,target)` | `FakeSession` (12 episodes, resume at 5, 720p/1080p, optional audio) |
| `tp.finder.ShowFinder` | 2 canned candidates + a `pin()` recorder |
| `tp.simkl_account.SimklAccount` | logged-out account, `add_to_list` recorder |
| `tp.status.StatusProbe` | green Simkl / red AnimeGate / amber AniList |
| `tp.characters.CharactersService` | 3 canned cast rows |
| `tp.bangumi`, network, mpv | never touched |

Run: `cd /home/user/coding/python/tgplay && QT_QPA_PLATFORM=offscreen .venv/bin/python <harness>`
(harness kept out of the repo: `~/.hermes/cache/scratch/ui_coverage_audit.py`; 75 instrumented
observations, 24 screenshots).

## 1. Verdict counts

| Verdict | Count | Meaning |
|---|---|---|
| WORKS | 51 | control exists, is reachable in the state that needs it, handler runs and the result is visible |
| WORKS-BUT-HIDDEN | 3 | the function runs, but the result is invisible (tooltip/log only, or an automatic step with no control or receipt) |
| BROKEN | 16 | a control exists and is clickable, but the handler does nothing, does the wrong thing, or the label/state lies |
| MISSING | 3 | no control at all for the feature |
| UNREACHABLE | 0 | a control exists but only in a state the user cannot get to (none found) |
| **total** | **73** | |


## 2. Feature -> control -> state -> verdict -> evidence

### Search / input

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | Search by name | `box`, typing (350 ms debounce) | cold→results | **WORKS** | A1: `debounce.isActive()` 350 ms, finder called with `{"title":"one piece"}`, list shows 2 rows; `02-search-results.png` |
| 2 | Paste a link | `box` → single row → click or Enter | cold | **WORKS** | A2 `results=1` with `debounce_active=false`; A2b click → `load_target("agp", …dandadan-77)`; A2c Enter → `load_target("axp", …bleach-9)`; `04-paste-link.png` |
| 3 | @channel Telegram | `box` → `route()` → one tgp row | cold | **WORKS** | A3/A3b: click → `load_target("tgp", "@some_channel")` |
| 4 | Enter on results ("opens the source picker") | `box.returnPressed` → `_accept_typed` | results | **BROKEN** | A4: `loads=[["agp","…one-piece-1074"]]`, `DLGS=[]` — no picker, row 0 loaded blind; hint text says "Enter opens the source picker for the best match" |
| 5 | Source picker per result | result rows labelled `· agp` / `· axp`, click a row | results | **WORKS** | A5: clicking row 2 (`axp`) → `load_target("axp","axp:one-piece")`, session replaced in place (`03-session-loaded.png`) |
| 6 | Result right-click (copy / open link) | `results` context menu | results | **WORKS** | A6 menu = `⧉ Copy link`, `🔗 Open in browser`; A6b Copy → clipboard `https://animegate.ir/…one-piece-1074`, msg `link copied: …` |
| 7 | Pin ids per link | none — automatic in `_pick_result` | results | **WORKS-BUT-HIDDEN** | A5: `ShowFinder.pin({"url":"axp:one-piece","ids":{"mal":21}})` recorded; no control, no feedback anywhere |
| 8 | Search with no hits | `results` list emptied | results | **BROKEN** | A8: `results=0`, `results_visible=false`, `msg=""` — slot renders blank, no "nothing found"; `05-empty-results.png` |
| 9 | Enter before results exist | `box.returnPressed` | typing | **BROKEN** | A9: `loads=[]`, `msg=""` — nothing happens, no hint to wait |

### History list

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | History button | `hist_btn` | any | **WORKS** | B1: stack → `hist_tbl`, 6 rows, head `Recent links & searches`; `06-history-list.png` |
| 2 | Open a recent link | cell click in the Date/Source/Link table | history | **WORKS** | B2: row 0 → `load_target("tgp","t.me/frieren_subs")` |
| 3 | Replay a past search | cell click on a `search` row | history | **WORKS** | B3: box text → `one piece`, no load (as designed) |
| 4 | Delete one row | `✕` tool button in column 4 | history | **WORKS** | B4: rows 9→8, `history.json` links 7→6; `08-history-after-delete.png` |
| 5 | Sort by header | header click (Source) | history | **WORKS** | B5: source column becomes `agp, agp, axp, axp, axp, search, search, tgp, tgp`; `07-history-sorted.png` |
| 6 | Back to the results list | none | history | **MISSING** | B8: `hist_btn` only calls `show_history(force=True)`; results stay in the stack but no control returns to them — only typing a new query |
| 7 | Duplicate titles | `_hist_rows` dedupe | history | **BROKEN** | B7: 6 links + 2 queries (8 entries) render as 7 rows: the second link for "One Piece" (the other source) is dropped with no marker |
| 8 | Empty history | placeholder row | history | **WORKS** | B6: single row `no history yet`; `09-history-empty.png` |

### Continue shelf

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | Cards + progress + count | `shelf` rail | shelf | **WORKS** | C1: 2 cards, `2 in progress`, progress bars from `pct`; `19-shelf.png` |
| 2 | Card click resumes | left click on a card | shelf | **WORKS** | C2: `load_target("agp","https://animegate.ir/watch/frieren-1")` via `history.last_link_for` |
| 3 | Card click with no link yet | left click | shelf | **WORKS** | C3: falls back to `load_entry` → finder called with `{"title":"Bleach","mal":269,"simkl":444}`, msg `2 result(s) for “Bleach” … click the one you want` |
| 4 | Right-click source menu | right click on a card | shelf | **WORKS** | C4: `▶ Resume (no link yet)` disabled, `🔎 Choose source…` enabled |
| 5 | Collapse / expand | `shelf.toggle` (▾) | shelf | **WORKS** | C5: `scroll.isVisible()` false, toggle ▸, header + count stay; `20-shelf-collapsed.png` |
| 6 | Empty state | `set_items([])` | shelf | **WORKS** | C6: `Nothing in progress yet - play a show and it appears here`; `21-shelf-empty.png` |
| 7 | Cold start (before any feed load) | `shelf` rail | cold | **BROKEN** | S0/`01-cold.png`: 242 px tall empty box with no placeholder — the empty label only appears after `set_items([])` runs |

### Show / episodes

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | Title + episode count | `head` + `ebox` title | session | **WORKS** | D1: head `One Piece`, `Episodes (12)`, 12 rows; `10-session.png` |
| 2 | Resume row preselected | `table` selection | session | **WORKS** | D1: `resume=(5,0)` → `currentRow=4` selected + scrolled into view |
| 3 | Simkl / MAL link for the loaded show | none | session | **MISSING** | D2: `link_lbl` only carries the source URL (`https://animegate.ir/watch/…`); `Open on Simkl/MAL` exists only in the feed/history context menus |
| 4 | Cast | `cast_btn` | session | **WORKS** | D3: enabled only after `set_session` (disabled at cold start, D3a); `CastDialog` built with mal 21 + title; `23-cast-dialog.png` (3 rows, detail pane, links) |
| 5 | + Simkl list (with a show) | `add_btn` | session | **WORKS** | D5: `add_to_list({"mal":21},"watching")`, status `added to Simkl list` |
| 6 | + Simkl list (no show) | `add_btn` | cold | **BROKEN** | D4b: enabled at cold start; click only posts `load a show first` (Cast is correctly disabled in the same state) |
| 7 | Only selected | `b_sel` + multi-row selection | session | **WORKS** | E1: rows 2 and 4 selected → `chosen=[2,4]` |
| 8 | Play from here | `b_from` + focused row | session | **WORKS** | E2: focus ep 7 → `chosen=[7,8,9,10,11,12]` |
| 9 | Play all | `b_all` | session | **WORKS** | E3: `chosen=[1..12]` |
| 10 | Double-click an episode | `table` double click | session | **MISSING** | E4: no `itemDoubleClicked` binding — `plays=0`, `msg=""` |
| 11 | Second play while one is running | `b_all` | playing | **WORKS-BUT-HIDDEN** | E5: `_do_play` returns early (`one video at a time`) with no message; nothing tells the user why |
| 12 | Play buttons with no session | `b_from` / `b_sel` / `b_all` | cold | **BROKEN** | F7: all three enabled; clicks → `plays=0`, `msg=""` (silent dead controls) |

### Playback options

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | Quality / server | `opts_form.server` | session | **WORKS** | P0: filled with `720p/1080p`, `1080p` preselected, label `Server` for audio sources; P3 disabled + tooltip for a source with no groups |
| 2 | Audio dub/sub/auto | `opts_form.audio_cb` | session | **WORKS** | P1 `audio:"dub"` reaches the session; P3 disabled + `Only AnimeX offers dub / sub.` |
| 3 | Skip mode incl. `off` | `opts_form.skip` | session | **WORKS** | P1 `opts["skip"]="off"` (string survives `to_opts`); P3b same on a source with no quality; `session.py:139` maps it to `skip_mode="off"` → `skip.flags()` returns `[], "off"` |
| 4 | T toggle | `opts_form.toggle` | session | **WORKS** | P1 `opts["skip_toggle"]=true` |
| 5 | Fullscreen | `opts_form.full` | session | **WORKS** | P1 `mpv=["--volume","80","--fullscreen"]` |
| 6 | Simkl sync | `opts_form.sync_cb` | session | **WORKS** | P1 unchecked → `opts["sync"]="off"` |
| 7 | Next-ep prefetch | `opts_form.nxt` | session | **WORKS** | P1 `opts["next"]=0.6` |
| 8 | At cut | `opts_form.nowait` | session | **WORKS** | P1 `opts["nowait"]=true` (with cut 45 → `nf="cut"` in `session.play`) |
| 9 | Cut seconds | `opts_form.cut` | session | **BROKEN** | P2: `abc` → `opts["cut"]=null`, no message, no red border — any text is accepted and silently dropped |
| 10 | Extra mpv flags | `opts_form.extra` | session | **BROKEN** | P2: `--title="One Piece" --volume 80` → `["--title=\"One","Piece\"","--volume","80"]` (naive `split()`, 4 args, mpv errors) |
| 11 | Options a source cannot use | `server` + `audio_cb` after `load()` | session | **WORKS** | P3: both visible but disabled, tooltips explain why; `12-options-disabled.png` |
| 12 | Placeholder text honesty | `cut` / `extra` placeholders | session | **BROKEN** | P0 `cut=""`, `extra=""`, yet the fields render `0` and `--volume 80` — they read as set values; `11-options.png` |

### Status line

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | idle / session status | `status` label (1 s timer) | any | **WORKS** | S1: `ep 5   12:00` from `Session.status()` |
| 2 | Loading feedback | `head` + `status` | loading | **WORKS** | S3: during `loading  https://…bleach-9 …`, after `Bleach 9` / `ep 5   12:00` (≤1 s lag from the 1 s timer) |
| 3 | Skip receipt | `status` label | playing | **WORKS** | S4: `skip[all]: chapters 12-90 (op)` shown, `msg_until` = +10 s; `14-status-skip-receipt.png` |
| 4 | Long status messages | `status` label width | playing | **BROKEN** | screenshot S4: the receipt is clipped to `skip[all]; chapters 12-90 (op` - no elide, no wrap, and the tooltip only holds log lines, not this message; `14-status-skip-receipt.png` |
| 5 | Stop | `b_stop` | session | **WORKS** | S2: `Session.stop()` called once, msg `stopped` |
| 6 | Stop message lifetime | `status` label | after stop | **BROKEN** | S2b: still `stopped` 3 s later — `msg_until` is never set for this message, so it survives until the next message; `13-status-stopped.png` |
| 7 | Stop with no session | `b_stop` | cold | **BROKEN** | F5b: `stops=0` but msg/status `stopped` — claims a stop that never happened |
| 8 | Other log lines | `status` tooltip (last 8) | playing | **WORKS-BUT-HIDDEN** | S5: `next: prefetching ep7`, `mark ep 5 watched` land in `status.toolTip()` only (2 lines), status text unchanged |
| 9 | Close | `b_close` | any | **WORKS** | F6: window hidden, `closing=true`, all five timers stopped, session closed |

### Sidebar

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | Connection lights | `status_strip` (● Simkl / ● AnimeGate / ● AniList) | any | **WORKS** | G8: 3 buttons + ↻, tooltips `not checked yet` → G8b `Simkl: as abe` / `AnimeGate: cookie expired`; `18-lights.png` |
| 2 | Simkl light | click | lights | **WORKS** | G9: `SimklConnectDialog(SimklAccount)` constructed; no client id → `24-simkl-connect-unavailable.png` (message, Open/Copy disabled) |
| 3 | AnimeGate light | click | lights | **WORKS** | G10: `QMessageBox "AnimeGate"` = `AnimeGate session: cookie expired`, buttons `🌐 Open login page` / `Close` |
| 4 | AniList light | click | lights | **WORKS** | G11: `QMessageBox.information` explains `tgplay login` / `AGP_ANILIST_TOKEN` |
| 5 | Lights ↻ | `status_strip.refresh_btn` | lights | **BROKEN** | G12: tooltip `check connections + reload calendar`; with `state["cal"]=[]` the feed keeps its 4 old rows — only `_probe_status()` runs |
| 6 | Refresh feed & history | `side_btn` | any | **WORKS** | G0: `load_side()` runs; table shows `Simkl not connected — click the ● Simkl light above`; `15-sidebar-not-connected.png` |
| 7 | Feed filter Calendar / Remaining / All | `feed_filter` | feed | **WORKS** | G2: 2 calendar rows / 2 remaining rows / 4 de-duplicated rows; `16-feed-all.png` |
| 8 | Feed sort | header click | feed | **WORKS** | G3: Title column re-ordered (`Dandadan · Ep 7`, `Frieren`, `KonoSuba`, `One Piece`) |
| 9 | Feed double-click to load | `feed.itemDoubleClicked` | feed | **WORKS** | G5: finder called for that entry, 2 results in the results slot, msg `2 result(s) for “Dandadan” — best match: AGP · click the one you want`; `17-feed-double-click.png` |
| 10 | Feed context menu | right click | feed | **WORKS** | G4: load / `➕ Simkl list` (5 statuses) / `🔗 Open on Simkl` / `🔗 Open on MAL`; G4b `Watching` → `add_to_list({"mal":21,"simkl":111},"watching")`, msg `Simkl → watching` |
| 11 | History table sort / double-click | header click / double click | feed | **WORKS** | G6 titles sorted (`KonoSuba`, `One Piece`); G7 double-click → finder with `{"title":"KonoSuba","mal":31,"simkl":901}` |
| 12 | Auto-refresh after a sync | `side_timer` (1.5 s) | playing | **BROKEN** | S6: `synced: ep 5 -> Simkl` pushed; `side_timer` fires but `timeout` has no receiver — `load_side()` calls = 0 |

### Keyboard / layout

| # | Feature | Control(s) | State | Verdict | Evidence |
|---|---|---|---|---|---|
| 1 | `/` and `Ctrl+F` focus search | `QShortcut`s | any | **WORKS** | L3: shortcuts `/`, `Ctrl+F`; focus after activation = `QLineEdit` |
| 2 | Tab order | tab chain from `box` | any | **WORKS** | L2: History → results → history table → episodes → server → audio → skip → 5 checkboxes → cut → extra → … |
| 3 | Layout at the default size (1360×1000) | five fixed slots | any | **WORKS** | L0: shelf 10–252, options 260–391, lists 429–597, episodes 710–930, bottom bar 956–990 — no overlap |
| 4 | Layout at the declared minimum (1220×820) | five fixed slots | any | **BROKEN** | L1: episode table y 684 → bottom 904 while the bottom bar sits at 776 and the window ends at 820 — ~94 px of the table is clipped/overlapped; `22-min-size.png` |

## 3. Top 10 UX defects (ranked by what the user hits)

1. **The episode panel is clipped at the window's own minimum size.**
   `setMinimumSize(1220, 820)`, but at that size the episode table is laid out at y=684 with
   h=220 (bottom = 904) while the bottom bar starts at 776 and the window ends at 820: the last
   rows sit under the action bar / off-window. At 1360x1000 it fits (table 710-930, bar 956-990).
   Evidence: `22-min-size.png`, observation L1/L0. Fix: raise the minimum height (~950) or let
   the splitter shrink the episode table.
2. **A search with no hits leaves the results slot blank and says nothing.**
   `_fill_results([])` hides the list, keeps the "Results" header, sets no message. Looks like
   the app ignored the query. Evidence: `05-empty-results.png` (A8: `results=0`,
   `results_visible=false`, `msg=""`).
3. **"Play from here" / "Only selected" / "All" are enabled with no show loaded and do nothing.**
   `_do_play` returns on `session is None` before touching `state['msg']`; three clicks produced
   zero plays and zero feedback. Evidence: `01-cold.png` (F7).
4. **The search hint promises a source picker on Enter; Enter loads the first row blind.**
   Hint: "Enter opens the source picker for the best match". `_accept_typed` → `_pick_result(row 0)`
   → `load_target`, no dialog (`DLGS=[]`). Evidence: `02-search-results.png` (A4).
5. **"stopped" sticks in the status line forever - and Stop claims it even with nothing playing.**
   `_do_stop` sets `msg='stopped'` without `msg_until`; `_refresh_status` keeps any non-empty msg,
   so it is still there 3 s later (the skip receipt, by contrast, expires after 10 s). With no
   session, Stop calls nothing but still reports "stopped". Evidence: `13-status-stopped.png`
   (S2/S2b/F5b).
6. **The lights refresh button lies about what it does.**
   Tooltip: "check connections + reload calendar". It only calls `_probe_status()`; with
   `state['cal']=[]` the feed still shows its 4 old rows. Evidence: `18-lights.png` (G12).
7. **The "refresh the sidebar after a sync" path is dead code.**
   `_drain_log` starts `side_timer` on a `synced:` / `marked ep` line, but `side_timer.timeout`
   is never connected: pushing `synced: ep 5 -> Simkl` gives `load_side()` calls = 0 and the
   timer simply expires. Evidence: `16-feed-all.png` (S6).
8. **History silently hides the second source for the same show.**
   `_hist_rows` drops any row whose title was already seen: 6 links + 2 queries render as 7 rows,
   and the dropped row is the axp link for a title you also opened on agp - the one thing the
   list is for (pick another source). No marker, no count. Evidence: `06-history-list.png` (B7).
9. **Extra mpv flags are split on whitespace, so quoted values break.**
   `--title="One Piece" --volume 80` → `["--title=\"One","Piece\"","--volume","80"]` (4 args).
   mpv rejects the pair silently. Evidence: `11-options.png` (P2).
10. **No Simkl (or MAL) link for the show you have loaded.**
    `link_lbl` carries only the source URL; the ids are known (`session.mal_id`) but "Open on
    Simkl/MAL" exists only inside feed/history row menus. Evidence: `10-session.png` (D2).

Also: the status line clips anything longer than the bar (skip receipts, `error: …`, the
AnimeGate-dead message) with no ellipsis and no full-text tooltip - the only message surface the
window has (`14-status-skip-receipt.png`).

Runners-up (not in the top 10): no way back from the recent-links table to the previous results
(B8); `+ Simkl list` enabled with no show (D4b); `Cut last N s` / `Extra mpv flags` placeholders
render as `0` / `--volume 80` and read as set values (P0); double-clicking an episode does
nothing (E4).

## 4. Features whose result is silent (log-only, tooltip-only, or nothing)

These are the ones that feel "dead" even when the code ran:

| Feature | Where the result goes | Evidence |
|---|---|---|
| Pin ids onto a link | nowhere - automatic, no control, no receipt | A5 `ShowFinder.pin(...)` recorded, UI unchanged |
| Next-ep prefetch / `mark ep` / Simkl push | `status.toolTip()` only (last 8 lines); the log pane was removed | S5: tooltip 2 lines, status text unchanged |
| Play buttons with no session | nothing at all (early return, no msg) | F7 |
| A second Play while one video runs | nothing ("one video at a time" is only a comment) | E5 |
| Enter with no results yet | nothing | A9 |
| Search with no hits | blank slot | A8 |
| Bad `Cut last N s` input (`abc`) | silently becomes no cut | P2 |
| Duplicate history titles | row omitted silently | B7 |
| Auto-refresh after a Simkl sync | timer fires into the void | S6 |
| Lights ↻ for the calendar | nothing (only the probe runs) | G12 |
| Double-click an episode | nothing | E4 |
| Skip receipt | **is** visible (status, 10 s) - the one log line with a designed surface | S4 |

## 5. What was not checked

- Real mpv playback, streaming, real Simkl/AniList/AnimeGate calls (no network in this harness);
  `Session.play()` arguments were inspected instead of a playing video.
- "Open in browser" was left un-fired on purpose (it would launch `xdg-open`); only the menu entry
  and its enabled state were verified.
- Popup menus were captured through an intercepted `exec` (full action list + enabled flags), not
  by hunting pixels in a native popup; the chosen action was then returned to the handler.
- `/` and `Ctrl+F` were verified by activating the `QShortcut`, not by a real key press.
- Fonts/glyphs differ in the offscreen platform plugin (emoji show as boxes in some shots).
- Single display, default palette/theme; no HiDPI, no light theme, no window manager.
