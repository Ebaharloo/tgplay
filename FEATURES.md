# tgplay — feature & method ledger

Living notes: what we built, how each thing is handled, and what is still
open. Update this whenever a feature lands. (`ARCHITECTURE.md` = design;
this file = behaviour + to-do.)

---

## Commands

**animegate (`agp`)**
- `agp <anime-url> [opts]` — stream/playlist; opts: `-e 1-12` `-a` `-q 720`
  `--skip[=all|names|auto]` `--skip-toggle` `--cut N` `--next[=P]` `--nowait`
  `--start N` + any mpv flag verbatim.
- `agp` / `agp --menu` — the interactive menu.
- `agp login <CLIENT_ID>` / `logout` / `sync [--dry]` / `new` / `tracking` —
  AniList progress + notices.
- `agp simkl <CLIENT_ID>` — set the Simkl key (episode titles for donghua).
- `agp cache` / `agp cache clean [--days N|--all] [--keep-partial]`.
- `agp icon` — install the app icon + a `tgplay` launcher entry (KDE/GNOME).
- `-h` / `--help` — full help.

**Telegram**
- `tg <t.me link>` / `tg <channel> <msg_id>` — one file.
- `tgp <channel>` — last-N mkv menu; `-e 2-5,9` `-a` `-f 720` `--window N`.
- `tg`/`tgp --menu`; `tg`/`tgp login` / `logout`.

**AnimeX (`axp`)**
- `axp <animex-url>` — stream animex.one with English **sub/dub**.
- `axp` / `axp --menu` — the same desktop/terminal menus; the option list is
  every audio type × every server AnimeX reports (dub pre-selected).
- `-e RANGE` / `-a`, `--dub` / `--sub` / `--auto`, plus the shared
  `--skip` / `--cut` / `--next` / mpv flags.

**Unified (`tgplay`)**
- `tgplay` — one window, **one field**: search AnimeGate + AnimeX together
  (results tagged `agp`/`axp`), or paste any link (animegate / animex / t.me),
  or `@channel`; the right source opens automatically.
- `tgplay agp|axp|tg|tgp …` — run one source directly. The **desktop icon
  launches `tgplay`**.

---

## Playback

- **Local range proxy** (one implementation for every source): RAM head (8MB)
  + RAM tail (2MB) + on-disk mirror window + live ranged reads for gaps.
- **Cache dir** `/tmp/agp-cache`; family LRU eviction is *manual*, not automatic.
- **Resume**: position saved per title/channel in `progress.json`; the menu
  opens on `<resume>` and seeks to the saved position when you start there.
- **Auto-advance** through the planned list.
- **Retry-on-open**: mpv rc==2 (failed to open) retries the same ep with a
  fresh signed link (up to 2) instead of silently skipping.
- **Quality**: `agp` from site groups; `tgp` derived from filenames
  (`480p/720p/1080p/2160p`), tolerant matching.
- **Skip**: file chapters first (named `Intro/Opening/Ending/Credits` win; a
  short leading/trailing chapter is a positional fallback), then **ani-skip**
  (aniskip.com). `--skip=names|auto|all`; `--skip-toggle` adds mpv key `T`.
- **`--cut N`** stop N s before the end; **`--start N`**; **gpu-context pinning**
  so `auto` can't fall through to DRM.
- **`--next[=P]` / `--nowait`**: background full download of the next ep
  (aria2 if present, else urllib), **cancellable** when playback starts.
- Terminal input is **flushed before mpv** (no stray-Enter `Ctrl+m` warning).

---

## Cache (the thing we must not lose)

- Unfinished downloads (`.part`) are **never auto-deleted** — you can continue
  another day.
- `agp cache` shows every entry: size, age (days), `done` vs `partial`.
- `agp cache clean --days 3` deletes families older than 3 days;
  `--all` wipes; `--keep-partial` spares unfinished ones even with `--all`.
- Geometry sidecars: `.done` (`lo/size/len`), `.win`; `is_full()` = whole-file.

---

## Menu (desktop GUI, curses terminal, or plain)

Preferred on a desktop: a **native Qt window** (`tp/gui_qt.py`, PySide6) —
this follows the desktop's own theme automatically (on KDE Plasma: Breeze
colours, widget style and icons; no hand-picked colours). It shows the episode
list with names, resume marker, quality, all options, a **live log panel**, a
clickable anime link, and **Play from here / Only selected / All / Stop /
Close**; the window stays open while playback runs in the background. When Qt
isn't available it falls back to the **Tkinter** window (`tp/gui.py`, which
paints itself from `kdeglobals`/GTK settings), then the **curses** terminal
form, then plain prompts. `--gui` / `--curses` force one (auto = GUI when a
display exists). All menus remember the last setup (`ui.json`) and share the
title cache.

1. **Link picker / search** — type to **search** the source live (debounced,
   in the background) and pick a result; or use a recent link / paste a URL.
   Results show their source (`agp` = animegate, `axp` = animex).
2. **Episodes page** — whole playlist with titles, count, `<resume>` marker.
   Keys: `Enter`=play from here, `o`=only this, `a`=all, `q`=cancel.
3. **Options form** — Quality, Episodes, Skip mode, Skip-toggle, `--next`,
   `--nowait`, Cut, Fullscreen, Extra mpv flags. A help panel explains the
   highlighted option; a footer line shows the keys.
- **Remembers the last setup** (`ui.json`); CLI flags always win.
- **App icon** (`tp/assets/tgplay.svg` + PNGs 16–512). `agp icon` installs it
  into the hicolor theme plus a `tgplay.desktop` launcher entry;
  `StartupWMClass=tgplay` + `setDesktopFileName('tgplay')` keep the taskbar
  icon grouped correctly on Wayland. Both windows show the icon.
- **No terminal needed** — started from the desktop icon, every CLI goes through
  the shared `tp/app.run()`: our log is appended to
  `~/.config/tgp/<name>.log` (path shown in the in-app **Log** panel) and any
  crash pops a dialog with the last error + log path, instead of vanishing.
- Stale typeahead flushed at each screen (no accidental auto-advance).
- Non-TTY falls back to plain prompts; scripts never prompt.

---

## Search (in-app)

- The desktop link picker doubles as a **search box**: `tp/search.search_all()`
  fans out to each provider's `search()` and returns `[{'title','url','source'}]`
  (`source` = `agp`/`axp`).
- The unified **`tgplay`** window uses **one field** and searches **both at
  once**, tagging each result with its source; picking one dispatches to that
  source's CLI (`tp/cli_all.route()` handles pasted links and `@channel` too).
- **animegate**: `GET /global-search?s=<q>` (grouped results, title + url).
- **animex**: GraphQL `searchAnime(query:)` → the internal slug, handed back as
  an `axp:<slug>` id the provider resolves directly (no page scrape).
- Runs debounced in a background thread, so typing never blocks the window.

---

## Titles / metadata (offline-resilient)

- Titles are **cosmetic and never on the critical path**: read instantly from
  cache; missing ones filled by a **background thread**.
- **Primary = MyAnimeList directly** (Jikan's API is often down):
  - title → MAL id via `myanimelist.net/search/prefix.json` (fuzzy over names)
  - MAL id → episode names by scraping `/anime/<id>/<slug>/episode` (slug from
    the search URL / canonical link; paginated)
- **Bangumi (bgm.tv)** for donghua: its public v0 API (`/v0/search/subjects`,
  `/v0/episodes`) has Chinese episode names (e.g. Mushen Ji → 天黑别出门 …).
  Search matches CJK only, so we get the Chinese title from the **Simkl**
  record's `alt_titles` (牧神记/遮天) and pass it in.
- Fallbacks order per episode: **MAL → Bangumi → Simkl** (AniList for the MAL id
  itself). Existing names are never overwritten.
- Generic `"Episode N"` titles are dropped (plain label fallback).
- **Circuit breakers** per source (mal/anilist/simkl): after a failure the
  source is skipped ~30 min (persisted in `meta_down.json`).
- **Log line at load, always** (found or not):
  `🅼 mal:  https://myanimelist.net/anime/<id>` /
  `📺 show: https://simkl.com/anime/<id>/<slug>` / `show: not found`.
  Cached in `mal_ids.json`, `mal_slugs.json`, `links.json`.
- Simkl: **keyless** `/redirect` (MAL → Simkl id) and `/anime/{id}` record.
  NOTE: this account's client_id requires a user token for `/search`, so we do
  not rely on Simkl search.
- Known: a few titles still have no episode names on any source.

---

## AniList tracking (opt-in)

- `agp login <id>` (Auth Pin flow), `sync`, `new`, `tracking`.
- On episode finish → mark watched (background). On start → new-episode notice.
- No token = complete no-op; `AGP_NO_TRACK` disables.

---

## AnimeX (English dub) — `axp`

- A **separate provider** (`tp/providers/animex.py`) with its own entry point
  `axp`; `agp` (animegate) stays untouched. Everything else — proxy, player,
  skip, menus, resume, GUI — is the shared machinery.
- Chain (plain JSON, no obfuscation): the anime page's SvelteKit `__data.json`
  gives the internal slug + AniList/MAL ids; then `pp.animex.one/rest/api/`
  `episodes` · `servers` · `sources` gives the episode list, the **sub/dub
  server list**, and a fresh **HLS** url + subtitle tracks.
- The menu has an **Audio** row (dub / sub / auto) and a **Server** row listing
  every server AnimeX reports (dynamic, tagged `dub`/`sub` — nothing hardcoded).
  If the picked audio isn't available for a title, it logs a warning and starts
  in the other one (e.g. no dub → sub); `auto` = dub when present, else sub.
- HLS is played by **mpv directly** (`tp.sources.DirectSource`) with
  `Referer: https://megaplay.buzz/`; the range proxy/cache is bypassed (HLS is
  segmented and tokens are short-lived).
- `stream()` **probes** each candidate server and skips ones that won't serve
  us; on an mpv open failure the Playlist calls `provider.rotate()` to try the
  next server. The MAL id (from the API) drives ani-skip intro/outro skipping.

---

## Telegram specifics

- Session at `~/.config/tgp/tg.session` (base name must NOT end in `.session`;
  telethon appends it). `TG_SESSION` overrides.
- `login` is **single-shot** (no retry); auth errors are **never** retried in
  the byte-pump (avoid rate-limit/block). `logout` removes the session.
- `--window N` (default 50) / `--all` to scan more files.
- Same proxy/playlist/player/skip/cache/tracking as `agp`.

---

## Architecture (services)

```
tp/config  tp/http  tp/sources  tp/cache  tp/proxy
tp/providers/{base,animegate,telegram,animex}
tp/chapters  tp/skip  tp/metadata  tp/simkl  tp/titles
tp/prefetch  tp/player  tp/playlist  tp/setup  tp/ui  tp/tracking
tp/episodes  tp/log  tp/cli  tp/cli_telegram  tp/cli_animex  tp/cli_all  tp/gui_qt  tp/gui  tp/icon  tp/search  tp/app
```
Thin entry points: `agp`, `tg`, `tgp` (symlinked into `~/.local/bin`; scripts use
`realpath(__file__)` so symlinks work). Tests: `tests/test_*.py`.
`tp/cli._pick_gui()` prefers `tp/gui_qt` (PySide6, native theming) then
`tp/gui` (Tkinter). The venv has `include-system-site-packages = true` in
`.venv/pyvenv.cfg` so it can use the system PySide6 + KDE integration.

---

## TODO / known gaps

- `tgp` window default 50 (raise with `--window`/`--all`); quality is guesswork.
- Some donghua have no episode titles on any public source.
- Simkl uses AniDB numbering → per-series offset not implemented yet.
- AniList key not configured on this machine yet (`agp tracking` → not logged in).
- No `--json`/scriptable mode yet.
- tgplay is newer than the original `tg_playlist`; keep testing side-by-side.
- Not yet ported from the old project: `tgp`'s `login` helper script name,
  any niche flags — verify parity over the next days.
