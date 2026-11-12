# PLAN: replace PySide6 with an Astryx web UI

Owner decision (2026-11-13): the GUI moves from Qt to **Astryx** (React + StyleX
design system, soft knowledge already in `~/node_modules/@astryxdesign`).
Python keeps doing all the work: providers, sessions, proxy, skip, tracking,
library, recent. The window becomes a local web app.

## Architecture (one process, one port)

```
tgplay (python)
  └─ tp/web/server.py     stdlib ThreadingHTTPServer, 127.0.0.1:8799
       ├─ GET  /                     -> web/dist/index.html (built Astryx app)
       ├─ GET  /assets/...           -> built assets
       ├─ GET  /api/state            -> one snapshot the UI renders
       ├─ POST /api/search   {q}     -> [{title,source,url,ids,matched}]
       ├─ POST /api/open     {src,url}
       ├─ POST /api/play     {eps[], opts{}}   (session required)
       ├─ POST /api/stop
       ├─ POST /api/options  {}      -> normalized opts (shared tp.options)
       ├─ GET  /api/events           -> SSE: log lines + status
       └─ POST /api/settings {rails} -> ui.json window.rails
```

Rules:
- No new Python dependencies. stdlib `http.server` + `json` only.
- Every long operation runs on a worker thread; the HTTP handler returns the
  current state immediately after queuing (the UI polls `/api/state` or listens
  to SSE). Nothing blocks the request thread for more than ~2 s.
- `Session`/`SessionLoader` stay the only way a show is opened; the web layer
  calls exactly what `gui_all.py` calls today (`open_session`, `play`, `stop`).
- The Qt window stays in the repo and keeps working (`./tgplay`), the web UI is
  `./tgplay --web` until parity, then it becomes the default.

### `GET /api/state` shape

```json
{
  "lights": {"simkl": true, "gate": true, "anilist": false},
  "rails": {"continue": [Card], "recent": [Card]},
  "feed":  [{"date":"Thu 19 Nov","ep":21,"title":"…","days":0}],
  "history": [{"watched":"2026-11-05","prog":"110/110","title":"…"}],
  "session": {"src":"agp","title":"…","link":"…","mal":51289,
              "episodes":[{"num":163,"name":"…"}], "playing": false,
              "status":"idle"},
  "search": {"q":"one piece","results":[Result], "busy": false},
  "rails_settings": {"continue":{...},"recent":{...},"sidebar":{...}}
}
```

`Card` = what `tp/recent.py` / `tp/continuewatch.py` already return
(`title, next_ep, watched, total, pct, mal, simkl, image, air_date, days_ago,
behind, is_new_season`). `image` may be empty: the card then shows a token-coloured
placeholder, never a broken <img>.

## Front end (`web/`)

- Vite + React 19. **Astryx from the existing install**: `web/node_modules` is a
  symlink to `/home/user/node_modules`; only `vite` and
  `@vitejs/plugin-react` are added (no second copy of Astryx, no styleX build —
  use `@astryxdesign/core/dist/astryx.css` + `@astryxdesign/theme-neutral/dist/theme.css`
  as shipped).
- Layout = the five slots the owner approved, now real components:
  `Card` per slot, `TabList/Tab` for the two rails, `TextInput` for search,
  `Selector` for quality/audio/skip, `CheckboxInput` for the flags,
  `Badge` for source / new / +N, `Button` for actions, `Table`-shaped rows built
  from `Card` + grid rows (no plain <table>).
- Slot rules unchanged: nothing moves between states; results sit directly
  under the search field; sidebar has its own width, resizable by a drag handle
  persisted in `ui.json` (`window.split`).
- Right-click: episode rows get a `DropdownMenu` (Play from here / only selected
  / all, Copy episode link, Show pages: Simkl/AniList/MAL/Fandom). Result rows
  get Copy link / Open / Show pages.
- Keyboard: `/` focuses search, Enter searches, Esc clears; arrow keys move in
  the lists; the whole UI is reachable by Tab (Astryx gives focus rings).
- Dark by default (`Theme mode="dark"`), `mode` switch kept in settings.

## Launcher

`tp/web/run.py`: start the server, then open a chromeless window —
`chromium --app=http://127.0.0.1:8799` (fallback: `firefox --new-window`), and
stop the server when the window closes. `./tgplay --web` calls it.

## Milestone 1 (this build — read + play, no rewrite of the core)

1. `tp/web/server.py` with `/api/state`, `/api/search`, `/api/open`,
   `/api/play`, `/api/stop`, `/api/options`, `/api/settings`, SSE `/api/events`,
   static serving of `web/dist`.
2. `web/` app rendering state: rails (tabs), search + options, results, show +
   episodes, bottoms (Stop · status · Close), sidebar (lights, feed with Aired,
   history, refresh).
3. `web/build` script; the server serves the built bundle; a dev proxy for
   `npm run dev` is optional.
4. Launcher `--web`.
5. Tests (no network, no browser): `tests/test_web.py`
   - state shape from a fake library/session
   - search returns rows with source+url
   - open/play/stop reject when there is no session (400 with a message, not 500)
   - options round-trip equals `tp.options.form_result`
   - settings writes ui.json and the next state reflects it
   - SSE emits a line when `tp.log` is called
6. Visual proof: `chrome --headless --screenshot` of the built app against a
   fake backend state, saved to `web/shots/m1.png`.

## Out of scope for M1 (say so, don't half-build)

Cast dialog, Simkl PIN login, calendar day filters beyond `Recent`, prefetch
progress, mpv window embedding (mpv stays a separate process), packaging
(.deb/AppImage), light theme polish.

## Gate

Review team reads the diff; test team runs `tests/` (Qt tests stay green);
UX team screenshots the six states and checks the no-reflow invariant.
