# Feature matrix: the four sources

Why: each source grew its own way, and provider-specific behaviour is scattered
in playlist/session/gui (`src == 'axp'` checks). This matrix pins what exists
today, per source, with the exact code that owns it — the baseline for splitting
providers into objects with a declared capability surface.

Sources: `tg`/`tgp` (Telegram), `agp` (AnimeGate), `axp` (AnimeX),
`zoro` (HiAnime). File:line refs are as of commit `258e3a8`.

## Matrix

| Feature | tg / tgp (telegram.py) | agp (animegate.py) | axp (animex.py) | zoro (zoro.py) |
|---|---|---|---|---|
| Search / discovery by title | no — channel window only (`_pick` telegram.py:190-206) | yes — module `search()` animegate.py:271-298 | yes — module `search()` animex.py:500-528 | yes as a method `ZoroProvider.search` zoro.py:127-135, but NOT wired into `tp/search.search_all` (search.py:9-27 only calls agp+axp) |
| Open by link / paste target | yes — `_telegram_target` session.py:198-207 -> `SingleFileProvider` telegram.py:273-321 / `TelegramProvider` telegram.py:177 | yes — URL constructor animegate.py:175-192 | yes — `base_slug` accepts url / `axp:<slug>` / slug animex.py:37-47 | yes — slug extraction zoro.py:72-74 (+ `zoro:` route cli_all.py:48-51) |
| Episode list (`episodes()`) | yes — telegram.py:247-250, 304-307 | yes — animegate.py:234-238 (windowed `all_eps` animegate.py:109-121) | yes — animex.py:370-373 (API animex.py:352-368) | yes — zoro.py:178-183 (`episode_ids` zoro.py:137-142) |
| Per-episode title (real names) | yes — the .mkv file name is the label (telegram.py:250, `_doc_name` 324-328) | n-a — site label fallback animegate.py:237-238; real names painted from MAL in session.py:313 | yes — API titles animex.py:363-367, but 'Release: date' Bangumi junk stripped outside the provider (session.py:239-242) | no — always generic `Episode N` (zoro.py:183; `display_name` -> None zoro.py:185-186) |
| Stream type | proxy bytes — `TelegramSource.read` over RangeProxy telegram.py:133-149 | proxy bytes — `HttpSource` (sources.py:39-72) through RangeProxy | direct HLS — `DirectSource` animex.py:495-496 (sources.py:75-97, `direct=True` 84) | direct HLS — `DirectSource` zoro.py:215-216 |
| Subtitles (external tracks) | no | no (embedded in .mkv only) | yes — sub-audio only: `d.get('tracks')` -> `DirectSource.subs` animex.py:489-496, consumed playlist.py:102-103, 222-223 | yes — payload `subtitles` -> `DirectSource.subs` zoro.py:213-214 |
| Audio dub/sub choice | no — `audio=False` session.py:303 | no — `audio=False` session.py:341 | yes — `set_audio` animex.py:273-279, `_resolve_audio` 312-327, dead-dub fallback `_audio_dead` 395-417 + cross-audio walk animex.py:457-481 | yes — `set_audio` zoro.py:153-155, server rows carry audio zoro.py:164-165, audio-first walk zoro.py:192-200 |
| Server selection | no (quality variants only) | yes — `pick_group` animegate.py:66-78 via `select` 203-227; `NoServersYet` 208-211 | yes — servers -> groups animex.py:227-271, `_parse_server` 301-310, `rotate` 329-340 | yes — `fetch_groups` zoro.py:157-169, `select` 171-176; server fall-through in `stream` zoro.py:195-199 |
| Quality / rendition labels | yes — filename parse via `quality.group` telegram.py:212-213, `set_quality` telegram.py:227-245 (quality.py:31-49) | yes — site group labels are the qualities (animegate.py:71-75) | yes — HLS renditions `_m3u8_qualities` animex.py:201-221, `_size_pref` 287-289 + `_rendition_url` 419-449 | no — quality ladder left to mpv (zoro.py:13-15 docstring) |
| Size labels | yes — known from the message document telegram.py:257-264, 317-321 | yes — probes the signed CDN once, caches animegate.py:240-254 | no — `DirectSource.size` = 0 (sources.py:92-94); GUI skips probing (gui_all.py:2051) | no — same (gui_all.py:2051) |
| Headers / referer / cookie needs | none — Telethon session, no HTTP (telegram.py:155-174) | yes — Firefox cookies animegate.py:23-43 + `Referer: BASE` animegate.py:267 | yes — per-host referer cache `_HDRS`/`headers_for` animex.py:34, 177-199; `MEDIA_REFERER` 30 | yes — embed-origin Referer zoro.py:211-215, UA + XHR zoro.py:120-125; mirror pick `base` 101-118 |
| Rate limit / quota | yes — FloodWait retry rules telegram.py:82-83, 94-98, 127 | n-a in code — 150 links/day is a site-side quota (not enforced anywhere in tp/) | none | none |
| Chapters for skip (probe targets) | yes — origin + proxy fallback (playlist.py:111-115, 239; skip.py:65-79) | yes — same (playlist.py:239) | yes — origin only, no proxy for direct HLS (playlist.py:216-224, 239) | yes — origin only (same) |
| ani-skip mal_id availability | no — tg branch never sets mal (session.py:289-303); only the skip-service title fallback (skip.py:213-214, playlist.py:433-438) | no provider id — pinned/fuzzy resolve in session.py:312 | yes — provider carries exact `mal_id` animex.py:87, 125/141, read playlist.py:117-118, 249-250 | declared but never resolved — `self.mal_id = None` zoro.py:79 |
| Prefetch / warm | byte-mirror via `Prefetcher.prefetch` playlist.py:140-147 (prefetch.py:53-99) | byte-mirror (same) | HLS-to-disk via ffmpeg `hls_to_file` playlist.py:122-139 (prefetch.py:102-131) | HLS-to-disk (same) |
| Resume position | yes — `cfg.progress` keyed on `provider.title` (session.py:62-68, 355; playlist.py:71-75, 385-401) | yes (same) | yes (same) | yes (same) |
| Watched marking | yes — `Playlist._mark` playlist.py:422-448, MAL via fallback resolve playlist.py:433-438 | yes — same, mal pinned session.py:338-339 | yes — same, provider mal_id playlist.py:430-431 | yes — same, mal always None (zoro.py:79) -> fallback resolve |
| Scrobble / MAL id resolution | no session-level MAL; title-based only (playlist.py:415-416, session.py:289-303) | yes — `meta.link_mal / _safe_mal` session.py:312, pinned 338-339 | yes — provider `mal_id` first session.py:248-249, pinned 252 | yes — `meta.link_mal / _safe_mal` session.py:285, pinned 288 |
| Provider-level state (sessions/caches) | Telethon session file + client/loop (telegram.py:42-61, 155-174); lazy `_loaded` everywhere (e.g. 247-249) | Firefox cookies re-read per call animegate.py:195 + `_sizes` cache 188/248-252 + `_labels` 192/197-199; `GateAuth` state 125-172 | module-level per-host referer cache `_HDRS` animex.py:34 + `_resolved`/`_chosen`/`_loaded` flags 96-98 | per-instance `_base` mirror probe zoro.py:71, 101-118; FEED/MIRRORS constants 30-32 |

## Duplicated logic (refactor targets: same job written twice+)

1. slug -> pretty title: `animegate.slug_title` (animegate.py:60-63) ~
   `animex.pretty_title` (animex.py:50-52) ~ zoro slug fallback (zoro.py:97-98).
2. search result shape `{'title','url','source'}`: animegate.search vs
   animex.search vs `ZoroProvider.search` — same contract, different shapes,
   and zoro is missing from `tp/search.search_all` (search.py:9-27).
3. HTTP GET -> decoded text/json helper: `animex._json` (animex.py:101-107) ~
   animegate fetch helpers (animegate.py:81-106) ~ `zoro._get` (zoro.py:120-125).
4. `fetch_groups -> select -> load` lifecycle with lazy
   `if not self._loaded: self.load()` repeated in every accessor of all four
   providers.
5. chosen-audio-first, other-audio-next walk: animex `tried`
   (animex.py:457-462) ~ zoro `order` (zoro.py:192-193).
6. m3u8 fetch+regex parsing repeated inside animex five times
   (animex.py:177-199, 201-221, 381-393, 395-417, 419-449), including the
   token-preserving urljoin blocks 412-414 / 443-447.
7. groups -> label normalization duplicated across consumers:
   gui_all.py:1162-1184, web/server.py:549-551, options.py:307-333.
8. selectable-group parsing per provider shape: telegram filename quality
   (quality.py:31-49), agp site group dicts (animegate.py:66-78), axp server
   dicts+renditions (animex.py:227-271), zoro server rows (zoro.py:157-169) —
   four shapes the GUI then re-parses.

## Provider quirks hardcoded outside the provider (the real breakage source)

1. Default player Referer per src literal in session
   (session.py:96-97 `'megaplay.buzz' if src=='axp' else 'animegate.ir'`),
   duplicating `animex.MEDIA_REFERER` and the animegate base; player.py:39
   hardcodes animegate too.
2. Audio-capable flag from src literals: `audio=True` only in the axp/zoro
   branches (session.py:243, 284), False for tg/agp (303, 341); web server
   repeats it as `audio=bool(session.src=='axp')` (server.py:553) — so zoro
   LOSES the audio field in the web UI; gui_all.py:1163 and options.py:325,
   330-333 key off the same bool.
3. GUI parses axp label strings to rebuild server/size menus
   (gui_all.py:1166-1181, 1274-1297) although the provider already carries
   structured `groups[].qualities` (animex.py:268-269).
4. Size-column support as src list: `'—' if s.src=='axp'` (gui_all.py:2036)
   and `s.src not in ('agp','tg','tgp')` (gui_all.py:2051).
5. AnimeGate session-dead marker regexes live in the GUI
   (gui_all.py:2121-2132) instead of `GateAuth` (animegate.py:150-164).
6. MAL pinning + title-painting sequence copy-pasted per branch in
   `open_session` (session.py:248-275 axp, 285-288 zoro, 312-339 agp); provider
   mal_id read via `getattr` strings across playlist.py.
7. Bangumi `'Release: date'` marker strip for axp titles lives in session
   (session.py:239-242), not in animex.py.
8. Play-time branches per source: skip `select()` for tg (renumbers),
   `set_audio` called only for axp at play time (session.py:114-117) — zoro's
   `set_audio` is never called there.
9. Link routing duplicated outside providers: `cli_all.route` (cli_all.py:32-74)
   re-implements what `base_slug` and `_telegram_target` already own.
10. axp couples quality INTO the server label string (`'… · 1080p'`,
    animex.py:258-261) and re-derives the size preference from that string by
    regex (`_size_pref` animex.py:287-289).

## Proposed object split

1. **Provider capability surface** on `base.Provider`: class caps
   `has_audio`, `has_sizes`, `search(query)`, and structured
   `groups() -> [{id, label, audio, qualities}]` — kills every src-literal
   check (session.py:96-97/243/284/303/341, gui_all.py:1163/2051,
   server.py:553) and gives zoro its audio field back in the web UI.
2. **StreamHeaders/Auth object per provider**: agp Firefox cookies+Referer,
   axp per-host referer cache, zoro origin-referer + mirror probe, tg Telethon
   session lifecycle — consumers ask `provider.headers_for(url)` /
   `provider.default_referer()` instead of session.py:96-97 and player.py:39.
3. **Catalog/names object per provider**: episodes + real titles + MAL
   painting — one shared flow replaces the three open_session copies and
   fixes zoro's generic `Episode N`.
4. **StreamOptions object**: server x rendition x audio as structured fields,
   `to_quality()/from_quality()` on the provider — replaces the label-string
   coupling (animex.py:246-269, 287-289) and the GUI re-parsing
   (gui_all.py:1166-1297, options.py:307-333).
5. **AuthHealth object** (generalize `GateAuth`): `alive() -> (ok, reason)`
   + `open_login()` per provider — moves the GUI marker regexes into the
   provider; tg gains login health, zoro gains mirror health.
