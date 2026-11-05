# tgplay — layout plan (the fixed flow)

Status: spec only. No code change. Target file `tp/gui_all.py` (`MainWindow`, 1180×820 now).

Complaint → rule it breaks:

| Complaint | Rule it breaks |
|---|---|
| search field bottom-centre, results at very top | proximity + Fitts (`better-layout` › Group with space) |
| buttons badly placed | one primary action per view (`better-layout` › One primary action) |
| everything reflows on every action | no layout change without a user action (this doc's invariant) |
| wide areas wasted | content stretches, chrome does not (`better-layout` › Hold structure) |
| no obvious flow | reading order = task order (`better-layout` › Order by importance) |

Rule sources used: `better-interface`, `better-layout`, `better-typography`,
`better-colors`, `apple-design` (Lens 1–2, macOS), `pyside6-desktop-gui`.
`native-feel-cross-platform-desktop` not used: it targets WebView shells; this is
native Qt (Tauri/Electron advice does not apply).

---

## 1. Primary flow (7 steps, 10 states)

The window has exactly one path; every path is a state of the same three panes.

1. **Cold start (S0)** — focus in the search field, recents listed right below it,
   show pane in its empty state, library loading. No dialog, no modal picker.
2. **Type (S1)** — 1 char → status `searching …`; results stack shows a placeholder
   inside the *same* rect the recents used. Nothing moves.
3. **Pick a source result (S2→S3)** — click or ↓ + Enter. `route()` also turns a pasted
   link / `@channel` / `axp:<slug>` into a one-row result, so the same picker serves
   links and searches.
4. **Load (S4)** — status `loading "title"`; previous show stays on screen until the new
   one is ready; results stay listed (a dead cookie lets you re-pick from the same list).
5. **Episodes (S5)** — title, count, Simkl link, Cast and `＋ Simkl list` enable; episodes
   fill; options enable only where the source supports them; field clears; results page
   shows `Type to search` again.
6. **Select + play (S6→S7)** — row selection → Enter / `Play from here` / `Only selected` /
   `All`. Exactly one video: play buttons disable, Stop enables, status names the episode.
7. **Back to browsing (S8→S9)** — Stop or episode end returns to S5 (same show, same
   scroll); typing returns to S2. The show pane is never blanked on the way.

Transitions are content + enabled-flag changes only. No zone is created, destroyed,
moved or resized between S0 and S9.

---

## 2. Zones

| Zone | Permanent content | Width / height rule |
|---|---|---|
| **A App bar** | app name, status line (elided, stretch), 3 connection lights + ↻ | height **44 fixed**, full width |
| **B Search rail** | search field (36) + Recents toggle, results/recents stack (stretch, min 220), Continue-watching shelf (fixed 200, 28 when collapsed) | width **340 fixed** (min 320, max 360) |
| **C Show pane** | show header (title/count/link/Cast/`＋ Simkl list`), Episodes table, Playback options, transport bar | width **stretch 1**, min **464**; header **84 fixed**, options **118 fixed**, transport **40 fixed**, episodes stretch (min 200) |
| **D Library rail** | Feed · calendar (+ filter), Recently watched | width **320 fixed** (min 300, max 380); feed stretch (min 220), watched **260 fixed** |

Window: `setMinimumSize(1180, 760)`, default `1180×820`. Gutters 16 between zones,
8 inside a zone, panel padding 8. Only the two stretch lists (results, episodes, feed)
ever change size — and only on window resize.

### 1180 × 820

```
+----------------------------------------------------------------------------------------------+
| A  tgplay  ·  playing ep 3 · 42%      [Simkl][AnimeGate][AniList] R   44px                   |
| B 340                  | C stretch 464                                | D 320                |
| [Search...] [H]        | Mushoku Tensei - 24 eps     [Cast]           | Continue watch v 3   |
|                        |                [+ Simkl list]                | [p][p][p] 4th peeks  |
| +--------+             | simkl.com/anime/1234/mushoku                 | 200 / 28 coll.       |
| |results |             |--------------------------------------        |----------------------|
| |stretch |             | Episodes               (stretch 480)         | Feed  [Calendar v]   |
| | 494    |             |  #   Episode name                            | Date      Ep   Title |
| |        |             |   1  ...                                     | 05 Nov    07   ...   |
| +--------+             |   2  ...  <- resume                          | ...  (stretch 478)   |
|                        |   3  ...                                     |                      |
| Continue               |--------------------------------------        |----------------------|
| watch v                | OPTIONS  (118)                               | Recently watched     |
| +------+               | Quality[1080v] Audio[auto] Skip[a]           | Watched  Prog Title  |
| |p|p|p |               | [T][fullscr][next ep][Simkl sync]            | 04 Nov   09   ...    |
| +------+               | Cut[N]s [at cut] Extra mpv [.....]           | (260)                |
|                        |--------------------------------------        |                      |
|                        | [Play from here][Only sel.][All]  Stop  Close|                      |
+----------------------------------------------------------------------------------------------+
```

### 1600 × 1000

```
+----------------------------------------------------------------------------------------------------------------+
| A  tgplay  ·  playing ep 3 · 42%                        [Simkl][AnimeGate][AniList] R  44px                    |
| B 340                  | C stretch 884                                                | D 320                  |
| [Search...] [H]        | Mushoku Tensei - 24 episodes      [Cast][+ Simkl]            | Continue watch v       |
|                        | simkl.com/anime/1234/mushoku                                 | [p][p][p]              |
| +--------+             |------------------------------------------------              | 200 / 28               |
| |results |             | Episodes                             (660)                   |------------------      |
| |stretch |             |  #   Episode name                   |  status                | Feed [Calendar]        |
| | 674    |             |   1  ...                            |                        | Date   Ep  Title       |
| |        |             |   2  ...                            |                        | ... (stretch)          |
| +--------+             |------------------------------------------------              |------------------      |
|                        | OPTIONS  (118)  full width                                   | Recently watched       |
| Continue               | Quality[1080v] Audio[auto] Skip[all]                         | (260)                  |
| watch v                |------------------------------------------------              |                        |
| (200)                  | [Play from here][Only selected][All] Stop  Close             |                        |
+----------------------------------------------------------------------------------------------------------------+
```

`R` = refresh lights · `[H]` = Recents toggle · `[p]` = poster card · `v` = dropdown.

Widths are identical in both; only C widens and the three stretch lists grow. Same
zone count, same order, same control positions.

---

## 3. State table + the no-reflow invariant

**Invariant (the rule to enforce in code):** *for a given window size, every zone and
every permanently placed control has an identical rect in all states. Only four things
may change: list/table contents, label text, `setEnabled()` flags, and the page inside
the search rail's results stack. Geometry changes only from an explicit user action —
window resize, or the shelf's own ▾ toggle. `setVisible(True/False)` on a zone in
response to app state is forbidden.*

| State | B Search rail | C Show pane | D Library | Enabled set |
|---|---|---|---|---|
| S0 cold start | recents page | empty state text + placeholder title; table empty | feed/history loading rows | play/stop/Cast/Simkl off, search on |
| S1 typing | results page, `searching …` | unchanged | unchanged | unchanged |
| S2 results | result rows (title + source tag) | unchanged | unchanged | unchanged |
| S3 routed link | one target row | unchanged | unchanged | unchanged |
| S4 loading | same rows, picked row marked | header `loading "x"`; old table stays | unchanged | play off, stop off |
| S5 loaded | `Type to search` page | title, count, link; episodes; options per source | unchanged | play on, stop off, Cast/Simkl on |
| S6 selected | unchanged | selection highlight | unchanged | `Only selected` on |
| S7 playing | unchanged | status in A only | unchanged | play off, stop on |
| S8 error | results page kept | previous show kept; status text + icon | unchanged | play on (re-pick allowed) |
| S9 recents open | recents page | unchanged | unchanged | unchanged |
| shelf collapsed | results +170 (user action) | unchanged | unchanged | unchanged |

---

## 4. Placement of every existing element

| Element | Home (fixed) | One-line reason |
|---|---|---|
| Search input | B, top, 36 px, full rail width, always focused at start | results sit 8 px under it (proximity); leading top edge = shortest pointer travel (Fitts); `/` refocuses it. |
| Results list | B, directly under the field, stretch | picks stay in the field/result pair users already watch while typing. |
| Per-row source (agp/axp/tg/tgp) | right-aligned 34 px text chip inside each row | text, never colour only (state must survive a colour-blind user). |
| History picker | one 36 px toggle at the field's trailing edge; its table opens as the stack's second page in the same rect | it is a finder, so it lives in the finder; a page swap moves nothing. Rename to **Recents**. |
| Continue watched shelf | B bottom, 200 fixed (28 collapsed) | resume is the second way to find a show; 4th poster peeks 16 px so hidden cards are cued. |
| Title + episode count | C header line 1, elided, stretch | first thing read after a load; count answers "how long is this". |
| Simkl link | C header line 2 | metadata trails the title, stays out of the action row. |
| Cast | C header trailing, next to `＋ Simkl list` | acts on the show named beside it; disabled until S5. |
| `＋ Simkl list` | C header trailing, left of Cast | same object as Cast, same row, secondary weight (outline button). |
| Episodes table | C, stretch, min 200 | largest area = most-used object; columns `#`, name, status. |
| Playback options (quality/server, audio, skip, T toggle, fullscreen, Simkl sync, next ep, at cut, cut seconds, extra flags) | C, 118 fixed band directly above transport | they modify the play action, so they sit beside it (proximity); 3 compact rows, same shape in every state and every source. |
| Play from here | transport left, **primary** (filled accent, first) | Enter on the table = the same action; proximity to the rows it plays. |
| Only selected / All | transport, right of primary, neutral | peers of the primary, not competitors (one filled action per view). |
| Stop | transport, 24 px clear of the play group, enabled only while playing | destructive-ish, must not be adjacent to a mis-aimed Play click. |
| Close | transport trailing edge | platform duplicate kept per owner request; far from Play so a miss never closes the window. |
| Connection lights (Simkl/AnimeGate/AniList) + ↻ | A trailing | ambient health, true for every state, out of the work area; each light gets a text label + glyph (state not carried by colour alone). |
| Status line | A, middle, elided, stretch | feedback visible in every state without a bottom information bar (macOS: no critical info in a bottom bar). |
| Feed · calendar + filter | D top, stretch | reference data, scan mode, sorted; `Calendar/Remaining/All` stays in its own header row. |
| Recently watched | D bottom, 260 | second reference table; rename to avoid two panels called *History*. |
| Log (`LogView`) | not reintroduced — last 8 lines stay in the status tooltip | no owner requirement; keeps the sync-refresh drain intact. |

---

## 5. Remove / merge / hide (with reason)

| Item | Action | Why |
|---|---|---|
| Bottom band holding a **second** search field + History + Cast | delete; those widgets move to B / C header | one search field, next to its results; the band was the whole complaint. |
| `↻ refresh feed & history` button | merge into the app-bar ↻ | two refresh controls for one job double the doubt about which to press. |
| `QGroupBox` × 4 (Feed, History, Episodes, Playback) | replace with a plain section header label + 4 px rule | ~39 px each and a nested border draws a box around content that space already groups. |
| State-driven `setVisible` (7 sites: shelf auto-hide, `res_stack`, empty results) | delete; page swaps and enabled flags instead | the reflow root cause; shelf hides only when *the user* presses ▾. |
| Empty search area | always shown, page with `Type to search` | a zone that vanishes is what makes the layout feel unstable. |
| Hardcoded `#212832/#4a6b8a` search stylesheet, shelf hover `#2a2e32` | palette/Breeze roles + `QFrame.StyledPanel` | app must follow the desktop theme (no hex literal where a role exists). |
| Source picker as popup/dialog | never; it is B's permanent list | a modal chooser loses the field, the list and the query at once. |
| Secondary actions: shelf "Choose source…", feed row → Simkl list, result copy/open | keep as right-click context menus | more than 3 secondary actions → behind a menu (not a toolbar of 8 icons). |
| `Extra mpv flags` | keep as a text field in options row 3 | power-user affordance; hiding it costs a discoverability step and saves no space. |
| Duplicate names "History" (recents picker) vs "History" (Simkl watched) | rename to **Recents** and **Recently watched** | two identical labels for different data is a naming bug, not taste. |

Nothing else is deleted: every listed feature keeps a permanent, always-visible home.

---

## 6. Qt implementation notes (PySide6)

| Concern | Setting |
|---|---|
| Root | `QWidget` + `QHBoxLayout`: B widget (`setFixedWidth(340)`), C widget (`stretch=1`, `setMinimumWidth(464)`), D widget (`setFixedWidth(320)`). No `QSplitter` — a splitter re-introduces user drift and a persisted sizes file. |
| Can't collapse | `setMinimumSize(1180, 760)`; each stretch list keeps `setMinimumHeight(200/220)`; rails use min==max width; never `setMaximumHeight` on a table (it starves the pane) — fixed heights only on chrome (44/118/40/200/260). |
| Options band | Own full-width band, no taller sibling in the same row, so no `sizeHint` stretch coupling. Longest child is a fixed 118. |
| Labels | 1–2 words (`Quality`, `Audio`, `Skip`, `Cut`, `at cut`); the sentence goes in `setToolTip()`. Long labels set a panel minimum width and starve C. Set `server.setMaximumWidth(150)`, `audio 62`, `skip 80`, `cut 70`, and `setMinimumWidth(100)` on the search field. |
| Union options | Keep `isEnabled()` gating in `OptionsForm.to_raw()` (already correct). Never hide a row: a source that offers no server leaves the combo visible, greyed, with the tooltip. |
| Episodes/feed/history tables | `setMinimumHeight()` + stretch argument; `QHeaderView.Stretch` on the name/title column; `ElideRight` + tooltip so narrowing never clips silently. |
| Shelf | `setFixedHeight(200)` on the whole shelf widget (28 when collapsed), internally header 24 + `QScrollArea` 168 — fixes the size-hint see-saw the current 206 `setFixedHeight` on the scroll area produces. |
| Tab order | `setTabOrder` chain: search → Recents toggle → results → shelf → Cast → `＋ Simkl list` → episodes → Quality → Audio → Skip → T toggle → fullscreen → next ep → Simkl sync → Cut → Extra flags → Play from here → Only selected → All → Stop → Close → feed → watched. |
| Shortcuts | `/` or `Ctrl+F` → focus + select search (`Qt.WidgetWithChildrenShortcut`); `↓` from the field → results; `Enter` on a result → load; `Esc` → clear query, else close dialogs; `H` → Recents; `F5` → refresh lights + feed; `Ctrl+Q` → close; on the episode table only: `Enter` play from here, `O` only selected, `A` all (widget-scoped, so typing never triggers them). |
| Focus | keep the platform focus ring; no `outline: none`, no custom painted focus. Search keeps focus after a load so the next search is zero clicks. |
| Dialogs | Cast and Simkl connect stay separate windows (they never change main-window geometry). Centre them on the main window; non-modal, one task each. |
| Status | one `QLabel`, elided middle, `setToolTip` carries the last 8 log lines (keeps `_drain_log`'s sync trigger). |
| Typography | one scale from the app font: title `+3 pt` semibold, section headers `base` semibold with `letter-spacing 0.05em`, table/body `base`, meta/count/status `base-1 pt` (≥10 pt floor). Tabular figures (`QFont.setStyleHint` + `font.setFixedPitch` off but `QFontMetrics` alignment right on `#`, `%`, dates). |
| Colour | no hex literals; `QPalette` roles only. Lights = glyph + label: `● Simkl` green/`◐ Simkl` amber/`✕ Simkl` red, tooltip carries the fix. Error text prefixed `✕`, success `✓`, so meaning survives greyscale. |
| Verification | new `tests/test_layout_geometry.py`: drive S0→S7 offscreen (`QT_QPA_PLATFORM=offscreen`), assert `QWidget.geometry()` of A/B/C/D, shelf, options, transport and each button is equal across states, and equal again after shelf collapse except the results rect. Run `env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q`. |

### Departures from the skills (and why)

| Rule | Departure | Reason |
|---|---|---|
| `better-layout` › group with space: inter-group gap ≥ 2× intra | 16 px between zones vs 8 px inside | a 340 rail at 1180 cannot afford 2× margins twice; 2× holds at the zone boundary, which is the boundary that carries meaning. |
| `pyside6-desktop-gui` step 4: put the options panel in one band with the search input | options band sits alone above transport | search moved to its own rail; keeping the old band is exactly the split-attention bug. Options now share the row's job (play) instead. |
| `apple-design` › no critical actions at a sidebar bottom | Continue-watching shelf at the rail's bottom | it is a list, not an action; the two actions it exposes (resume, choose source) are the shelf's own content, and no other control sits below it. |
| `better-layout` › short view links deeper | Recents and Library tables stay on the page | they are the cold-start content; a menu would add a click to the first screen a user sees. |
| `better-typography` › 13 pt minimum UI text | `base-1` for meta rows | Qt `base` is 10–11 pt on Breeze; meta never goes under 10 pt and is never the only copy of a value (tooltip has the full string). |