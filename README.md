# tgplay — OOP rewrite of tg_playlist

A clean-room, object-oriented rewrite of the `agp` / `tg` / `tgp` streaming
player, developed **separately** from the original working project at
`../tg_playlist` (which stays untouched as the reference/stable version).

Goal: each concern is one small class with an explicit interface, injected
where needed — no module-level globals, no duplicated range servers — so the
player is easy to test, reuse and tune. See `ARCHITECTURE.md`.

## Status

Phases 1–4 are in `tp/`, with a working `agp` entry point:

```
tp/log.py        colour/emoji logging
tp/config.py     Config: paths + tunables (injectable)
tp/http.py       HttpClient: retries + exact byte-range fetches + parallel chunk
tp/chapters.py   SkipResolver: mkv chapters -> skip flags
tp/episodes.py   Episode + select()/resume()  (the only place the play list is built)
tp/sources.py    MediaSource ABC + BytesSource + HttpSource
tp/cache.py      Cache: mirror geometry + LRU eviction
tp/proxy.py      RangeProxy: one source-agnostic range server
tp/providers/    Provider + AnimeGateProvider + TelegramProvider/TelegramSource
tp/metadata.py   AniList -> MAL id, Jikan -> episode titles
tp/skip.py       SkipService: file chapters, then ani-skip
tp/prefetch.py   Prefetcher: cancellable mirroring into the Cache
tp/player.py     Player: mpv command + IPC PosWatcher
tp/playlist.py   Playlist: resume / retry / skip / cut / --next
tp/cli.py        arg parsing + wiring
agp              thin entry point (AniGate)
```

Run:

```
./agp -h
python3 tests/test_core.py
python3 tests/test_proxy.py
python3 tests/test_providers.py
python3 tests/test_player.py
python3 tests/test_prefetch.py
python3 tests/test_skip.py
```

Not yet ported (Phase 5): AniList progress sync, the curses menu, and separate
`tg`/`tgp` CLIs (the `TelegramProvider` exists; wire it to a CLI next).

## Tests

Stdlib only:

```
python3 tests/test_core.py
```

## Reference

The original implementation lives in `../tg_playlist` (`agp`, `tg`, `tgp`,
`tg_server.py`, `opts.py`, `tracking.py`, `ui.py`, `malq.py`, `eptitle.py`,
plus its test suite). Behaviour should match it; this repo just reorganises it.
