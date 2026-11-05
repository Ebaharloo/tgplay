# tgplay UI audit — one window, seven states

Measured on the real `tp.gui_all.MainWindow` (2214 lines, `threading` search/load,
no network) with PySide6 `offscreen`; screenshots are pixel dumps of the live
widget tree, geometry is `widget.mapTo(window, QPoint(0,0))` + `width()/height()`.

- Harness: `tools/audit_states.py` (re-run after the redesign)
- Screenshots: `ui-audit/state1_cold.png` … `ui-audit/state7_wide.png`
- Raw numbers: `ui-audit/measure.json`
- Window: the code asks for 1180×820 (`MainWindow.__init__`), **the layout refuses
  anything narrower than 1223** and grows to 1223×886 as soon as the shelf fills
  (states 1–5 = 1223×820, 6–7 = 1223×886 / 1600×1000).

`—` in the map below = not visible (a hidden widget keeps its last geometry, so
its x/y/w/h in the per-state tables is stale and must be read as "n/a").

## Layout map: y / height per state

| element | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| search input | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 727 / 34 | 841 / 34 |
| results list | — | — | 10 / 260 | — | — | — | — |
| history table | — | — | — | 10 / 260 | 10 / 260 | 260 / 200 | 260 / 225 |
| results stack | — | — | 10 / 260 | 10 / 260 | 10 / 260 | 260 / 200 | 260 / 225 |
| shelf | — | — | — | — | — | 10 / 242 | 10 / 242 |
| title/head | 10 / 34 | 10 / 34 | 278 / 34 | 278 / 34 | 278 / 34 | 468 / 34 | 493 / 34 |
| link | 52 / 16 | 52 / 16 | 320 / 16 | 320 / 16 | 320 / 17 | 510 / 17 | 535 / 17 |
| Cast btn | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 727 / 34 | 841 / 34 |
| Simkl list btn | 10 / 34 | 10 / 34 | 278 / 34 | 278 / 34 | 278 / 34 | 468 / 34 | 493 / 34 |
| History btn | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 661 / 34 | 727 / 34 | 841 / 34 |
| episodes table | 106 / 489 | 106 / 489 | 374 / 221 | 374 / 221 | 375 / 220 | 565 / 96 | 590 / 185 |
| episodes box | 76 / 528 | 76 / 528 | 344 / 260 | 344 / 260 | 345 / 259 | 535 / 135 | 560 / 224 |
| options form | 612 / 131 | 612 / 131 | 612 / 131 | 612 / 131 | 612 / 131 | 678 / 131 | 792 / 131 |
| status | 751 / 17 | 751 / 17 | 751 / 17 | 751 / 17 | 751 / 17 | 817 / 17 | 931 / 17 |
| play from here | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| play only selected | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| play all | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| stop | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| close | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| feed table | 116 / 404 | 116 / 404 | 116 / 404 | 116 / 404 | 116 / 404 | 116 / 470 | 116 / 584 |
| history sidebar | 567 / 192 | 567 / 192 | 567 / 192 | 567 / 192 | 567 / 192 | 633 / 192 | 747 / 192 |
| refresh feed&hist | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 776 / 34 | 842 / 34 | 956 / 34 |
| status lights | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 |
| refresh (lights) | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 | 10 / 34 |

Vertical order of the main column, cold start: `Continue-watching shelf (hidden)`
→ `results/history stack (hidden)` → `title` → `link` → `Episodes (empty, 528 px)`
→ `options form` + `search field` (same band) → `status` → `play buttons`.
The search field is the 4th element from the bottom; the list it fills is the
1st from the top.

## (a) State tables

### State 1 — cold start (`ui-audit/state1_cold.png`)

Nothing typed, no session, no shelf. Visible: header label, link placeholder,
empty `Episodes` group (528 px of empty table), feed/history sidebar (both
empty), options form, search field, status, action bar.
`results`, `hist_tbl`, `res_stack`, `shelf` are hidden.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 661 | 240 | 34 | yes |
| results list | 0 | 0 | 640 | 480 | no |
| history table | 0 | 0 | 640 | 480 | no |
| results stack | 0 | 0 | 640 | 480 | no |
| shelf | 0 | 0 | 640 | 480 | no |
| title/head | 12 | 10 | 743 | 34 | yes |
| link | 12 | 52 | 831 | 16 | yes |
| Cast btn | 763 | 661 | 80 | 34 | yes |
| Simkl list btn | 763 | 10 | 80 | 34 | yes |
| History btn | 677 | 661 | 80 | 34 | yes |
| episodes table | 21 | 106 | 813 | 489 | yes |
| episodes box | 12 | 76 | 831 | 528 | yes |
| options form | 12 | 612 | 409 | 131 | yes |
| status | 12 | 751 | 831 | 17 | yes |
| play from here | 12 | 776 | 111 | 34 | yes |
| play only selected | 131 | 776 | 104 | 34 | yes |
| play all | 243 | 776 | 80 | 34 | yes |
| stop | 331 | 776 | 80 | 34 | yes |
| close | 763 | 776 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 404 | yes |
| history sidebar | 862 | 567 | 340 | 192 | yes |
| refresh feed&hist | 853 | 776 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 2 — typing a query (`ui-audit/state2_typing.png`)

`w.box.setText('one piece')`, debounce stopped before any search request.
**Geometry is byte-identical to state 1** (see the delta table) and the status
stays `idle`: typing produces no visual change whatsoever.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 661 | 240 | 34 | yes |
| results list | 0 | 0 | 640 | 480 | no |
| history table | 0 | 0 | 640 | 480 | no |
| results stack | 0 | 0 | 640 | 480 | no |
| shelf | 0 | 0 | 640 | 480 | no |
| title/head | 12 | 10 | 743 | 34 | yes |
| link | 12 | 52 | 831 | 16 | yes |
| Cast btn | 763 | 661 | 80 | 34 | yes |
| Simkl list btn | 763 | 10 | 80 | 34 | yes |
| History btn | 677 | 661 | 80 | 34 | yes |
| episodes table | 21 | 106 | 813 | 489 | yes |
| episodes box | 12 | 76 | 831 | 528 | yes |
| options form | 12 | 612 | 409 | 131 | yes |
| status | 12 | 751 | 831 | 17 | yes |
| play from here | 12 | 776 | 111 | 34 | yes |
| play only selected | 131 | 776 | 104 | 34 | yes |
| play all | 243 | 776 | 80 | 34 | yes |
| stop | 331 | 776 | 80 | 34 | yes |
| close | 763 | 776 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 404 | yes |
| history sidebar | 862 | 567 | 340 | 192 | yes |
| refresh feed&hist | 853 | 776 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 3 — 8 search results (`ui-audit/state3_results.png`)

`res_stack` shown at the top with the results list (8 rows, 260 px), shelf
suppressed. Everything below the list is pushed down 268 px.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 661 | 240 | 34 | yes |
| results list | 12 | 10 | 831 | 260 | yes |
| history table | 12 | 10 | 640 | 480 | no |
| results stack | 12 | 10 | 831 | 260 | yes |
| shelf | 0 | 0 | 640 | 480 | no |
| title/head | 12 | 278 | 743 | 34 | yes |
| link | 12 | 320 | 831 | 16 | yes |
| Cast btn | 763 | 661 | 80 | 34 | yes |
| Simkl list btn | 763 | 278 | 80 | 34 | yes |
| History btn | 677 | 661 | 80 | 34 | yes |
| episodes table | 21 | 374 | 813 | 221 | yes |
| episodes box | 12 | 344 | 831 | 260 | yes |
| options form | 12 | 612 | 409 | 131 | yes |
| status | 12 | 751 | 831 | 17 | yes |
| play from here | 12 | 776 | 111 | 34 | yes |
| play only selected | 131 | 776 | 104 | 34 | yes |
| play all | 243 | 776 | 80 | 34 | yes |
| stop | 331 | 776 | 80 | 34 | yes |
| close | 763 | 776 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 404 | yes |
| history sidebar | 862 | 567 | 340 | 192 | yes |
| refresh feed&hist | 853 | 776 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 4 — history picker (`ui-audit/state4_history.png`)

`show_history(force=True)` with 5 rows. The stack stays at y=10/h=260 and swaps
its page: `results` hides, `hist_tbl` shows. No other element moves.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 661 | 240 | 34 | yes |
| results list | 12 | 10 | 831 | 260 | no |
| history table | 12 | 10 | 831 | 260 | yes |
| results stack | 12 | 10 | 831 | 260 | yes |
| shelf | 0 | 0 | 640 | 480 | no |
| title/head | 12 | 278 | 743 | 34 | yes |
| link | 12 | 320 | 831 | 16 | yes |
| Cast btn | 763 | 661 | 80 | 34 | yes |
| Simkl list btn | 763 | 278 | 80 | 34 | yes |
| History btn | 677 | 661 | 80 | 34 | yes |
| episodes table | 21 | 374 | 813 | 221 | yes |
| episodes box | 12 | 344 | 831 | 260 | yes |
| options form | 12 | 612 | 409 | 131 | yes |
| status | 12 | 751 | 831 | 17 | yes |
| play from here | 12 | 776 | 111 | 34 | yes |
| play only selected | 131 | 776 | 104 | 34 | yes |
| play all | 243 | 776 | 80 | 34 | yes |
| stop | 331 | 776 | 80 | 34 | yes |
| close | 763 | 776 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 404 | yes |
| history sidebar | 862 | 567 | 340 | 192 | yes |
| refresh feed&hist | 853 | 776 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 5 — session loaded, 12 episodes (`ui-audit/state5_session.png`)

Title, link, options filled, 12 episodes in the table. **The history table is
still on screen at the top** (the stack was never collapsed), so the show title
sits at y=278 and the episode table gets 220 px for 12 rows.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 661 | 240 | 34 | yes |
| results list | 12 | 10 | 831 | 260 | no |
| history table | 12 | 10 | 831 | 260 | yes |
| results stack | 12 | 10 | 831 | 260 | yes |
| shelf | 0 | 0 | 640 | 480 | no |
| title/head | 12 | 278 | 743 | 34 | yes |
| link | 12 | 320 | 831 | 17 | yes |
| Cast btn | 763 | 661 | 80 | 34 | yes |
| Simkl list btn | 763 | 278 | 80 | 34 | yes |
| History btn | 677 | 661 | 80 | 34 | yes |
| episodes table | 21 | 375 | 813 | 220 | yes |
| episodes box | 12 | 345 | 831 | 259 | yes |
| options form | 12 | 612 | 409 | 131 | yes |
| status | 12 | 751 | 831 | 17 | yes |
| play from here | 12 | 776 | 111 | 34 | yes |
| play only selected | 131 | 776 | 104 | 34 | yes |
| play all | 243 | 776 | 80 | 34 | yes |
| stop | 331 | 776 | 80 | 34 | yes |
| close | 763 | 776 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 404 | yes |
| history sidebar | 862 | 567 | 340 | 192 | yes |
| refresh feed&hist | 853 | 776 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 6 — shelf with 3 cards + episodes (`ui-audit/state6_shelf.png`)

Shelf appears (242 px) and the window is forced from 820 to **886 px tall**;
the stack moves to y=260 and keeps 200 px. Episode table drops to 96 px: **2 of
12 rows visible**.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 727 | 240 | 34 | yes |
| results list | 12 | 260 | 831 | 260 | no |
| history table | 12 | 260 | 831 | 200 | yes |
| results stack | 12 | 260 | 831 | 200 | yes |
| shelf | 12 | 10 | 831 | 242 | yes |
| title/head | 12 | 468 | 743 | 34 | yes |
| link | 12 | 510 | 831 | 17 | yes |
| Cast btn | 763 | 727 | 80 | 34 | yes |
| Simkl list btn | 763 | 468 | 80 | 34 | yes |
| History btn | 677 | 727 | 80 | 34 | yes |
| episodes table | 21 | 565 | 813 | 96 | yes |
| episodes box | 12 | 535 | 831 | 135 | yes |
| options form | 12 | 678 | 409 | 131 | yes |
| status | 12 | 817 | 831 | 17 | yes |
| play from here | 12 | 842 | 111 | 34 | yes |
| play only selected | 131 | 842 | 104 | 34 | yes |
| play all | 243 | 842 | 80 | 34 | yes |
| stop | 331 | 842 | 80 | 34 | yes |
| close | 763 | 842 | 80 | 34 | yes |
| feed table | 862 | 116 | 340 | 470 | yes |
| history sidebar | 862 | 633 | 340 | 192 | yes |
| refresh feed&hist | 853 | 842 | 358 | 34 | yes |
| status lights | 853 | 10 | 358 | 34 | yes |
| refresh (lights) | 1179 | 10 | 32 | 34 | yes |

### State 7 — same content at 1600×1000 (`ui-audit/state7_wide.png`)

Main column 1208 px wide, sidebar pinned at 340. Search field grows to 617 px,
options form stays 409, feed table gains 180 px of height while the episode
table gains 89 and the stack 25.

| element | x | y | w | h | visible |
|---|---|---|---|---|---|
| search input | 431 | 841 | 617 | 34 | yes |
| results list | 12 | 260 | 831 | 260 | no |
| history table | 12 | 260 | 1208 | 225 | yes |
| results stack | 12 | 260 | 1208 | 225 | yes |
| shelf | 12 | 10 | 1208 | 242 | yes |
| title/head | 12 | 493 | 1120 | 34 | yes |
| link | 12 | 535 | 1208 | 17 | yes |
| Cast btn | 1140 | 841 | 80 | 34 | yes |
| Simkl list btn | 1140 | 493 | 80 | 34 | yes |
| History btn | 1054 | 841 | 80 | 34 | yes |
| episodes table | 21 | 590 | 1190 | 185 | yes |
| episodes box | 12 | 560 | 1208 | 224 | yes |
| options form | 12 | 792 | 409 | 131 | yes |
| status | 12 | 931 | 1208 | 17 | yes |
| play from here | 12 | 956 | 111 | 34 | yes |
| play only selected | 131 | 956 | 104 | 34 | yes |
| play all | 243 | 956 | 80 | 34 | yes |
| stop | 331 | 956 | 80 | 34 | yes |
| close | 1140 | 956 | 80 | 34 | yes |
| feed table | 1239 | 116 | 340 | 584 | yes |
| history sidebar | 1239 | 747 | 340 | 192 | yes |
| refresh feed&hist | 1230 | 956 | 358 | 34 | yes |
| status lights | 1230 | 10 | 358 | 34 | yes |
| refresh (lights) | 1556 | 10 | 32 | 34 | yes |

## What changes between consecutive states

- **1 cold start → 2 typing**: no geometry change
- **2 typing → 3 results**: title/head (y+268); link (y+268); Simkl list btn (y+268); episodes table (y+268, h-268); episodes box (y+268, h-268)
- **3 results → 4 history**: no geometry change
- **4 history → 5 session**: link (h+1); episodes table (y+1, h-1); episodes box (y+1, h-1)
- **5 session → 6 shelf**: search input (y+66); history table (y+250, h-60); results stack (y+250, h-60); title/head (y+190); link (y+190); Cast btn (y+66); Simkl list btn (y+190); History btn (y+66); episodes table (y+190, h-124); episodes box (y+190, h-124); options form (y+66); status (y+66); play from here (y+66); play only selected (y+66); play all (y+66); stop (y+66); close (y+66); feed table (h+66); history sidebar (y+66); refresh feed&hist (y+66)
- **6 shelf → 7 1600x1000**: search input (y+114); history table (h+25); results stack (h+25); title/head (y+25); link (y+25); Cast btn (y+114); Simkl list btn (y+25); History btn (y+114); episodes table (y+25, h+89); episodes box (y+25, h+89); options form (y+114); status (y+114); play from here (y+114); play only selected (y+114); play all (y+114); stop (y+114); close (y+114); feed table (h+114); history sidebar (y+114); refresh feed&hist (y+114)

Read that as: **two actions move the main column by 190–270 px** (results appear:
+268; shelf returns: +190) and **one action moves nothing at all** (typing). The
elements that never move relative to each other are the options form and the
action bar — the parts that carry no state.

## (b) Defects

**D1 — the results/history pane never collapses when a show is loaded.**
State 5. The 260 px stack (showing the *history* table, 5 rows, unrelated to the
loaded show) stays above the title: title y=278 instead of ~10, episodes table
220 px for 12 rows.
Fix: hide `res_stack` (or collapse it to a "← search" chip) in `set_session`.

**D2 — shelf visibility is coupled to the results stack, so the whole page jumps.**
States 5→6 (`shelf.sync(True/False)` at lines 1479–1481, 1623). Title 278→468
(+190), link 320→510, episodes box 344→535, episode table 375→565 and 220→96 px,
options 612→678, status 751→817, buttons 776→842 (+66, the window also grew).
The reverse jump happens when a search starts and the shelf hides; the same
insert/remove repeats every time results clear after a pick.
Fix: reserve the shelf band at a fixed height and swap only its contents.

**D3 — the window cannot be 1180×820, and it resizes itself after being shown.**
States 1–5. `minimumSizeHint` = 1223×427 idle, 1223×635 with results, **1223×886
with the shelf**; the shelf appearing grows the window from 820 to 886 px (66 px
taller than the coded `resize`). Width 1223 comes from the sidebar tables'
`setMinimumWidth(340)` plus the options band (409 options + 240 field + 80
History + 80 Cast).
Fix: drop the 340 px table minimum, let the options form wrap, cap the shelf at a
height that fits 820 (shelf 242 + stack 200 + Episodes minimum is what pushes the
min height to 886).

**D4 — the episode table gets whatever is left, not the most.**
Episodes table height: 489 (state 1, empty) → 221 (state 5, 12 eps) → **96
(state 6, 2 rows of 12)** → 185 (state 7, 1600×1000). `root.addWidget(ebox, 1)`
competes with `res_stack, 1` (line 1087) and the sidebar `fbox, 1` (line 1025).
Fix: make `ebox` the only stretch=1 child; give the stack and the sidebar fixed
heights.

**D5 — the search field and the list it fills are at opposite ends of the window.**
States 1–5. Field at y=661 (x=431, inside the *Playback options* band, right of
the `Cut / Extra mpv flags` row); results list at y=10…270. Distance field-top →
list-top = **651 px** at 1180×820 (581 px at 1600×1000: field y=841, stack top
y=260). Placeholder text and layout read as if the search belongs to the options
panel.
Fix: one search row above the stack (field + History + Cast); options band only
options.

**D6 — search field width is stretch-driven, everything else fixed.**
State 7. Field 240 px (1180) → 617 px (1600) while `opts_form` stays 409 px and
the shelf cards stay left; at 1600 there are ~800 px of empty shelf row right of
three cards and a 1208 px-wide episode table row that only ever shows 5 rows.
Fix: cap the field (≈520 px) and push surplus width into the episodes/results
area.

**D7 — vertical resize feeds the sidebar, not the content.**
States 6→7 (820→1000 px): feed table +180, sidebar history +0, episode table
**+89**, results/history stack +25, shelf +0.
Fix: stretch factors (episodes 2, feed 1, stack 0) or a max height on the feed.

**D8 — typed search has no feedback at all.**
State 2 → 3. No geometry change, status stays `idle` through debounce (350 ms) +
network; `_run_search` (line 1443) writes no message and `_drain_search` (1519)
none either. Only the sidebar-click path reports (`N result(s) for "…"`, line
2019). A failed typed search is also silent (`_rq.put([])` on exception).
Fix: `state['msg'] = 'searching …'` in `_run_search`, `'N results'` /
`'nothing found'` in `_drain_search`.

**D9 — results and history are one stack, so one always hides the other.**
States 3/4. `results` visible only when the stack page is 0, `hist_tbl` only on
page 1; the shelf is hidden in both. After results appear, the history you were
browsing is gone and the only way back is the `🕘 History` button 391 px below
the list.
Fix: two tabs over the stack, or keep both as fixed sections.

**D10 — tab order follows reparenting order, not the screen.**
State 3, from the search field: 1 `🕘 History`, 2 `▶ Play from here`, 3 `▶ Only
selected`, 4 `▶ All`, 5 `■ Stop`, 6 `Close`, 7–9 status lights, 10 `↻`,
11 feed filter, 12 feed table, 13 sidebar history, 14 `↻ refresh`, **15 results
list**, 16 `＋ Simkl list`, 17 link, 18 episode table, 19–28 options widgets.
The list you must click after typing is 15 Tab presses away, the episode table
18; at 1600×1000 the walk still has not returned to the field after 30 presses.
`setTabOrder` is never called.
Fix: one explicit chain search → results → episodes → options → actions.

**D11 — cold start focus is not the search field.**
`show()` alone leaves focus on `● Simkl` (first widget created). `run()` does
call `box.setFocus()` before `show()` and that does land on the field, but after
any Tab or dialog there is no shortcut back (no `Ctrl+F`, no `/`), and the field
is a bottom-band widget.
Fix: focus after `show()`, add a `Ctrl+F` shortcut, wire `Esc` to clear.

**D12 — the status line is the only output channel and it erases itself.**
States 1–7. `status` is 17 px tall at y=751 (y=931 at 1600), holds the last 8 log
lines only in its tooltip (line 2105–2107, the log pane is gone), and every
success path resets `state['msg']` to `''` (1256, 1370) so a message survives at
most until the next 1 s tick (2111–2118).
Fix: keep the last message until replaced; put the log lines behind a click.

**D13 — empty states are dead space with no cue.**
State 1. Empty `Episodes` group takes 528 px (65% of the main column); both
sidebar tables are blank with no placeholder text; the header label
`Search or paste a link to start` looks like an input but is a `QLabel` and
nothing points at the real field 650 px below it.
Fix: hide/collapse `ebox` and the sidebar groups when empty, and make the header
a hint that highlights the field.

Harness caveats: state 5–7 were produced by calling `set_session` directly, so
the query text stays in the field (the real `_apply_loaded` clears it); shelf
posters show `…` because downloads are disabled (no network).

## (c) Status messages and busy indicators a user can see

Per state:

| state | status line | other visible text | busy indicator |
|---|---|---|---|
| 1 cold | `idle` | header `Search or paste a link to start`; light tooltips `not checked yet` (×3) | none |
| 2 typing | `idle` | unchanged | **none** (no searching state) |
| 3 results | `idle` | 8 rows; no hit count | none |
| 4 history | `idle` | 5 rows; `no history yet` row when empty | none |
| 5 session | `idle` → `session.status()` after next 1 s tick (e.g. `playing ep 5`) | title, link, `Episodes (12)` | none |
| 6 shelf | same | `▶ Continue watching` + `3 in progress` | none |
| 7 wide | same | same | none |

Every message string reachable in this window (from `state['msg']`, rendered by
`_refresh_status`):

- load: `loading  <name> …` (also written into the header), `starting…`, `stopped`
- errors: `error: <ex>`, `AnimeGate session dead (<reason>) - links need a new login; …`,
  `cast: <ex>`, `add failed: <ex>`, `Simkl update failed: <ex>`
- search: `searching “<title>” on our sources…` (history row click only),
  `not found on our sources: <title>`, `<N> result(s) for “<title>” — best match: XS  ·  click the one you want`
  (sidebar click only)
- Simkl: `adding “<title>” to Simkl…`, `added to Simkl list`, `Simkl connected`,
  `Simkl → <status>`, `setting Simkl → <status>…`, `no id to update on Simkl`,
  `load a show first`, `AnimeGate auth: <reason>`
- misc: `link copied: <url>` (context menu)
- default: `idle` whenever `msg` is empty

Modal-only strings (not part of the main window): `SimklConnectDialog.status`
(`starting Simkl sign-in…`, `Approve this code on the Simkl page - …`,
`code copied - …`, `Simkl said: <res> - start again`).

There is **no progress bar, spinner or disabled-while-busy state** anywhere in
the window: the only activity feedback is the 17 px status string, which is
reset to `idle` by the same timer that would show it.

## Reproduce

```bash
cd /home/user/coding/python/tgplay
env -u PYTHONPATH .venv/bin/python tools/audit_states.py   # rewrites ui-audit/
```

The script builds the real `MainWindow`, stubs the loader and history only,
stops the debounce timer before any request, and prints every element rect plus
the tab order.
