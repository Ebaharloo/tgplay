# tgplay

Anime/episode player for the desktop. It finds an episode on a source you pick,
resolves the real stream, and hands it to **mpv** — with episode advance, skip
intro/outro, sub/dub choice, Simkl tracking and a Qt UI.

Sources:

| id | source | notes |
|----|--------|-------|
| `axp` | AnimeX | per-show servers from the site's own API; per-episode sub/dub with automatic fallback |
| `agp` | AnimeGate | link-quota limited by the site (150/day) |
| `zoro` | HiAnime | mirror taken from a validated domain feed, plain HTTP, no browser |
| `tg` / `tgp` | Telegram | one file / a channel playlist (needs your own api id + a login) |

## Requirements

- Python 3.10+, `mpv` on `PATH` (`ffmpeg` for HLS pre-downloads)
- `pip install PySide6` for the desktop UI, `pip install telethon` for Telegram
- optional: [ani-skip](https://github.com/synacktraa/ani-skip) for intro skipping

## Run

```bash
./tgplay                                   # GUI, pick a source and a show
./tgplay https://animex.one/watch/<slug>   # a link routes to its source
./tgplay axp                               # CLI, search/choose in the terminal
./tgplay zoro:<hianime watch url>
make test                                  # full suite, no network required
```

## Configuration

Nothing secret ships in the repo. It all lives in `~/.config/tgp/`:

- `~/.config/tgp/env` — `KEY=VALUE` lines, mode 600: `AGP_TG_API_ID`,
  `AGP_TG_API_HASH` (your own app from https://my.telegram.org), optionally
  `AGP_SIMKL_CLIENT_ID`.
- `tgplay simkl <client_id>` — stores a Simkl client id (register your own at
  https://simkl.com/settings/developer/); `tgplay simkl login` then authorizes
  your account. Without it, tracking is a no-op.
- `TGP_ZORO_BASE` — pin a HiAnime mirror instead of the automatic probe.

AnimeGate reads your Firefox cookies for `animegate.ir` (log in there first) and
is rate limited per account: `agp` stops with a clear message once the daily
quota is gone, the other sources keep working.

## Layout

`tp/` is the engine (sources, providers, playlist, options model) and `tests/` the
suite. `ARCHITECTURE.md` and `DESIGN.md` explain the seams; `FEATURES.md` lists
what exists.

## Tests

```bash
make test     # or: env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q
```

## License

No license file yet — all rights reserved until one is added.
