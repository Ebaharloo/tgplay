# tg_playlist — target architecture (OOP / services)

Status: **in progress.** Phase 1 (this change) extracts the pure, highest-risk
pieces into a package. The `agp` / `tg` / `tgp` scripts stay the user-facing
CLIs and progressively become thin wrappers.

## Why

Today the logic lives in big module-level functions with global mutable state
(`PREFETCH_STOP`, `RAM`, `LOCAL`, `URLS`, `STATE`, `_T0`). Two HTTP range
servers (`tg_server.py` and the `tg`/`tgp` handlers) are near-duplicates, and
`play()` silently assumed its input shape — which is how a bare-link list
reached it and crashed. Each concern should be one small object with an
explicit interface, injected where needed, individually testable.

## Layers

```
 tp/
   log.py         Logger            (colour/emoji; one import point)
   config.py      Config            (paths + tunables; no globals)
   http.py        HttpClient        (retries, exact range fetches)
   model.py       Episode, Chapter, Media, Progress   (value objects)
   episodes.py    episode selection / resume (the ONLY place that builds
                  the play() list -> shape bugs become impossible)
   chapters.py    SkipResolver      (mkv chapters + ani-skip -> script-opts)

   sources/
     base.py      MediaSource (ABC)  get_meta() / episodes() / link(num)
     animegate.py AnimeGateSource    (site + signed CDN links)
     telegram.py  TelegramSource     (telethon messages)

   cache.py       Mirror / Cache     (RAM head/tail + disk window, eviction)
   proxy.py       RangeProxy         (one server; source-agnostic)
   prefetch.py    Prefetcher         (aria2 lifecycle + stop events)
   player.py      Player             (mpv command builder + IPC watcher)
   playlist.py    Playlist           (episode loop: retry, resume, next/prefetch)
   tracking.py    Tracker            (AniList progress + notices)
   ui.py          MenuUI             (curses form)
   cli.py         arg parsing        (opts)

 agp, tg, tgp   -> argparse/opts + construct Config/Context + run Playlist
```

### Key interfaces

- **`MediaSource`** — the thing that turns a request into playable bytes:
  `meta(identifier)`, `episodes()`, `range(identifier, lo, hi)`. AniGate and
  Telegram both implement it, so `RangeProxy`/`Playlist` never special-case a
  backend again.
- **`RangeProxy`** — one implementation of the RAM-head/tail + disk-mirror +
  live-fetch range server, parameterised by a `MediaSource`. Replaces
  `tg_server.py` *and* the two inline handlers in `tg`/`tgp`.
- **`SkipResolver`** — chapters and ani-skip behind one call:
  `flags(url, mode, toggle) -> [mpv args]`.
- **`Episode`** — a `NamedTuple(num, link)`. `play()` accepts `list[Episode]`;
  selection/resume live in `episodes.py`, so no caller can pass bare links.
- **`Player`** — builds the mpv argv and owns the IPC watcher (progress +
  `--next` trigger). No globals; state is per-instance.
- **`Prefetcher`** — aria2 `Popen` lifecycle, cancellable via a per-entry
  `threading.Event`, so "keeps downloading" can't happen.

### Dependency injection

A single `Context` (or explicit constructor args) carries `Config`, `Logger`,
`HttpClient`, `MediaSource`, `Cache`. Tests build a `Context` with fakes; the
CLIs build the real one. No module-level singletons.

## Migration phases

1. **Pure core** (done): `tp/log`, `tp/config`, `tp/http`, `tp/chapters`,
   `tp/episodes` + tests.
2. **Unified range server** (done): `tp/sources` (MediaSource + BytesSource +
   HttpSource), `tp/cache.Cache` (mirror geometry + LRU eviction) and
   `tp/proxy.RangeProxy` — one source-agnostic server with a RAM head/tail, an
   on-disk mirror window and live gap reads. Tested with an in-memory source.
   This is the single implementation that replaces `tg_server.py` and the two
   inline Telegram handlers.
3. **`MediaSource`**: `AnimeGateSource` + `TelegramSource`; `RangeProxy` and
   `Playlist` become source-agnostic.
4. **`Prefetcher` + `Player` + `Playlist`** classes replace `agp.play()`'s body
   and its globals; thin `cli.main()` entry points.
5. **Tracking + UI** as injectable services.

Each phase keeps every `tests/test_*.py` green; no phase changes user-visible
behaviour on its own.
