# tgplay

Any AI (or human) working in this repo MUST follow these rules. They are
ENFORCED by `tests/test_architecture.py` — if the suite fails there, your
change is wrong, not the test.

## Build / test

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q   # PYTHONPATH must be unset
make test                                                 # same, via Makefile
```

## Architecture law (enforced by tests/test_architecture.py)

1. **One class per feature, one subclass per source/service.** Provider
   capabilities live in `tp/features/` (search, audio, servers, quality,
   sizes, titles, warm, auth); tracking lives in `tp/tracking/` (simkl_client,
   anilist_client, local_store, wiki + watched, lists, ratings, scrobble,
   resume, calendar, history). Both have ONE REGISTRY in their `__init__.py`.
2. **No per-source literals in feature logic.** `== 'axp'`-style comparisons
   are legal ONLY in `cli_all.route` and the two REGISTRY tables. Consumers
   call `provider.<feature>` / the registry — never branch on the source id.
3. **Consumers never build clients directly.** No `SimklAccount(` in gui_all;
   no direct `simkl_client`/`anilist_client` imports outside `tp/tracking`.
4. **Every feature module ships its test file**
   (`tests/test_features_<name>.py` / `tests/test_tracking_<name>.py`) with a
   case per source/service that has the feature — a bug fixed in one source's
   object can never break another source's.
5. **A new feature = new feature class + registry entry + tests.** Do not
   stuff a new capability into an existing module or a `src==` branch.
6. **tp/web is deleted.** Nothing imports it; the Qt GUI is the only UI.
7. **Public repo: no credentials, no API keys, no `/home/...` paths** in any
   committed file. Secrets load from env or `~/.config/tgp/`.
8. **Skip probing is source-agnostic** (`tp/skip.py probe_targets`); add no
   per-source probe code elsewhere.

When a rule here blocks what you want to do, that is the signal to refactor
the change into the object pattern — not to bypass the test. If the change
genuinely needs a new rule, extend `tests/test_architecture.py` AND the
registry in the same commit, with tests.

## Workflow

- Dev change → suite green → independent adversarial review (a second agent
  re-runs the suite and attacks the diff) before "done".
- One concern per commit; push to `origin/master`; every push is public.
- User-visible behaviour changes get a live check with real playback/tracking
  before the card closes.

## Conventions

- Prefer small, focused changes; run tests before declaring done.
- Keep secrets in `.env`, not config.
- Update wiki (~/wiki) when a decision or non-obvious bug is resolved.
