# tgplay — OOP rewrite of tg_playlist

A clean-room, object-oriented rewrite of the `agp` / `tg` / `tgp` streaming
player, developed **separately** from the original working project at
`../tg_playlist` (which stays untouched as the reference/stable version).

Goal: each concern is one small class with an explicit interface, injected
where needed — no module-level globals, no duplicated range servers — so the
player is easy to test, reuse and tune. See `ARCHITECTURE.md`.

## Status

Early. Phases 1–2 (pure core + unified range server) are in `tp/`:

```
tp/log.py        colour/emoji logging
tp/config.py     Config: paths + tunables (injectable)
tp/http.py       HttpClient: retries + exact byte-range fetches + parallel chunk
tp/chapters.py   SkipResolver: mkv chapters -> skip flags
tp/episodes.py   Episode + select()/resume()  (the only place the play list is built)
tp/sources.py    MediaSource ABC + BytesSource + HttpSource
tp/cache.py      Cache: mirror geometry + LRU eviction
tp/proxy.py      RangeProxy: one source-agnostic range server (RAM head/tail +
                 disk mirror + live gaps)
```

Tests:

```
python3 tests/test_core.py     # config/http/chapters/episodes
python3 tests/test_proxy.py    # proxy + cache (in-memory source)
```

Later phases (`ARCHITECTURE.md`): `AnimeGateSource`/`TelegramSource`,
`Prefetcher`, `Player`, `Playlist`, `Tracker`, `MenuUI`, then thin CLIs.

## Tests

Stdlib only:

```
python3 tests/test_core.py
```

## Reference

The original implementation lives in `../tg_playlist` (`agp`, `tg`, `tgp`,
`tg_server.py`, `opts.py`, `tracking.py`, `ui.py`, `malq.py`, `eptitle.py`,
plus its test suite). Behaviour should match it; this repo just reorganises it.
