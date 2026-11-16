# tgplay — OOP rewrite of tg_playlist

A clean-room, object-oriented rewrite of the `agp` / `tg` / `tgp` streaming
player, developed **separately** from the original working project at
`../tg_playlist` (which stays untouched as the reference/stable version).

Goal: each concern is one small class with an explicit interface, injected
where needed — no module-level globals, no duplicated range servers — so the
player is easy to test, reuse and tune. See `ARCHITECTURE.md`.

## Status

Phases 1–5 are done. Entry points: `agp` (animegate), `tg` (one Telegram
file), `tgp` (Telegram channel playlist).

```
tp/log.py         colour/emoji logging
tp/config.py      Config: paths + tunables (injectable)
tp/http.py        HttpClient: retries + exact byte-range fetches + parallel chunk
tp/chapters.py    SkipResolver: mkv chapters -> skip flags
tp/episodes.py    Episode + select()/resume()  (the only place the play list is built)
tp/sources.py     MediaSource ABC + BytesSource + HttpSource
tp/cache.py       Cache: mirror geometry + LRU eviction
tp/proxy.py       RangeProxy: one source-agnostic range server (port fallback)
tp/providers/     Provider + AnimeGateProvider + TelegramProvider/SingleFileProvider
tp/metadata.py    AniList -> MAL id, Jikan -> episode titles
tp/skip.py        SkipService: file chapters, then ani-skip
tp/prefetch.py    Prefetcher: cancellable mirroring into the Cache
tp/player.py      Player: mpv command + IPC PosWatcher
tp/playlist.py    Playlist: resume / retry / skip / cut / --next
tp/setup.py       MenuUI: remembers last setup        tp/ui.py  terminal form
tp/gui.py         desktop window (Tkinter): playlist + options + Play
tp/tracking.py    Tracker: AniList progress sync + new-episode notices
tp/ui.py          MenuUI: curses option form + recent-link picker
tp/cli.py         agp wiring        tp/cli_telegram.py  tg/tgp wiring
agp  tg  tgp      thin entry points
```

## Auth (same as before)
- **AnimeGate**: reads your Firefox cookies for `animegate.ir` (log in there).
- **Telegram**: real-phone login once with `./tgp login` (or `./tg login`);
  the session file is `~/.config/tgp/tg.session` (base name `tg`, override with
  `$TG_SESSION`). An existing session from the old project is reused by copying
  it there: `cp ../tg_playlist/.tg_session.session ~/.config/tgp/tg.session`.

## Run
```
./agp -h
./agp --menu
./agp <anime-url> -e 1-12 -q 720 --skip --cut 30 --next
./agp login <CLIENT_ID>   # AniList; sync | new | tracking
./agp simkl <CLIENT_ID>   # Simkl key for episode titles (donghua)
./agp info <anime-url>    # cross-site links: MAL / AniList / Simkl / AniDB / ...
./tgp login && ./tgp <channel> -a
./tg "https://t.me/<channel>/<id>"

python3 tests/test_core.py tests/test_proxy.py tests/test_providers.py \
        tests/test_player.py tests/test_prefetch.py tests/test_skip.py \
        tests/test_tracking.py tests/test_ui.py
```

## Tests

Every feature has its own model, `tests/test_<feature>.py`. Finalize gate (all tests, non-zero on any failure):

```
make finalize
```

One feature model: `env -u PYTHONPATH .venv/bin/python -m pytest tests/test_<feature>.py -q`

## Reference

The original implementation lives in `../tg_playlist` (`agp`, `tg`, `tgp`,
`tg_server.py`, `opts.py`, `tracking.py`, `ui.py`, `malq.py`, `eptitle.py`,
plus its test suite). Behaviour should match it; this repo just reorganises it.
