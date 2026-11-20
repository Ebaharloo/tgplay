# Tracking/sync matrix — tgplay

Baseline for the `tp/tracking/` object split (same pattern as `tp/features/`).
File:line refs verified on branch master at audit time (2026-11-20).

## Matrix

| # | Feature | Served by | Write/read site | UI/entry point |
|---|---------|-----------|-----------------|----------------|
| 1 | Mark episode watched (playback finish) | Simkl REST POST /sync/history + AniList SaveMediaListEntry | Simkl: `tp/simkl_account.py:800-817` -> `mark_watched` `:559-569` -> `_history` `:482-498`; AniList: `tp/tracking.py:155-163` -> `save_progress` `:78-84` | `tp/playlist.py:405-432` `_mark` -> `MultiTracker.mark_watched` `tp/tracking.py:319-332` (fan-out) -> `make_tracker` `tracking.py:379-395`, wired `tp/session.py:125-129` |
| 2 | Mark watched (GUI menu) | local watched.json first, then Simkl via offline queue | local: `tp/watched.py:65-77`; queue: `tp/simkl_sync.py:60-74`; push: `SimklPusher` `simkl_sync.py:105-124` -> `mark_episode_watched` `simkl_account.py:500-501` | `tp/gui_all.py:1864-1876` -> `_queue_watched` `:1889-1906`; Syncer thread `simkl_sync.py:127-192`, wired `gui_all.py:1340-1346` |
| 3 | Unwatch/remove episode | local toggle + Simkl /sync/history/remove (queued); AniList: none | `watched.py:65-77`; `simkl_sync.py:112` -> `unmark_episode_watched` `simkl_account.py:503-504` | same menu as #2 (`gui_all.py:1821-1824`) |
| 4 | Mark till-here / season / unwatch season | local + Simkl (queue fans out per-episode) | local `watched.py:80-91` `set_season`; queue loop `gui_all.py:1897-1903`; unused native `mark_season_watched` `simkl_account.py:506-507` | `watched.py:124-144` `rows()`; `gui_all.py:1897-1903` |
| 5 | Series complete / unmark | local flag + Simkl show-level history (queued) | `watched.py:94-100`; `simkl_sync.py:114-115` -> `simkl_account.py:512-516`; AniList COMPLETED hardcoded `tracking.py:79-82` | `watched.py:141-143`; `gui_all.py:1905` |
| 6 | Add to list (watching/plan/drop/hold/complete) | Simkl only POST /sync/add-to-list (direct, not queued) | `simkl_account.py:571-582` (`STATUSES :43`) | three hardcoded call sites: `gui_all.py:2635-2637`, `:2688-2712`, `:3096-3114` |
| 7 | Calendar feed | Simkl CDN JSON — TWO implementations: data.simkl.in/calendar/v2 (`tp/library.py:17,20-55`) and v1 (`tp/simkl_extra.py:164-180`) | both filtered client-side | `library.overview()` `library.py:58-83` (`gui_all.py:2822-2826`); `SimklExtra.calendar()` `gui_all.py:2729-2732` |
| 8 | Recently aired | Simkl library rows | `library.py:70-76`; parallel impl `tp/recent.py` | `gui_all.py:2825-2826` and `:2744-2746` |
| 9 | Future airing dates | Simkl next_watch_info (`simkl_account.py:416-432`) + /anime/episodes (`simkl_extra.py:144-153`) + AniList nextAiringEpisode (`tracking.py:87-90`) | read-only | playlist next-ep + sidebar feed |
| 10 | History rows | Simkl last_watched_at | `library.py:80-81`, `_norm` `simkl_account.py:432` | `gui_all.py:2825` -> history table `:3060-3064` |
| 11 | Scrobble start/pause/stop | Simkl only POST /scrobble/{start,pause,stop} | `simkl_account.py:622-647`; 409 swallow `:640-647` | `playlist.py:292,327,364-366` -> `_scrobble` `:386-403` -> `MultiTracker.scrobble` `tracking.py:335-349` |
| 12 | Ratings 1-10 | Simkl only POST /sync/ratings | `simkl_account.py:584-596`; `unrate` `:598-604` + `ratings()` `:606-620` never called | `gui_all.py:2622-2634` -> `_simkl_write` `:2654-2664` |
| 13 | Resume points (cross-device) | Simkl GET/DELETE /sync/playback | `simkl_account.py:657-686` read, `:688-700` clear; `SimklTracker.resume/forget` `:767-798` | `playlist.py:368-384` -> `MultiTracker.resume` `tracking.py:351-364`; cleared `playlist.py:428-432` |
| 14 | Local resume position | progress.json | `playlist.py:334,355` (`cfg.progress` `tp/config.py:66-67`) | playlist loop |
| 15 | Pull watched from Simkl | POST /sync/watched extended=episodes + /sync/activities gate | `simkl_sync.py:208-229` `remote_watched`, `:232-239` `pull_gate`, `:248-262` `reconcile` | `gui_all.py:2565-2611` `_simkl_pull` (auto `:2561`); stamp `cfg.simkl_activities` |
| 16 | Auth / login / revoke | Simkl device flow (`simkl_account.py:266-378`); AniList PIN (`tracking.py:220-267`); revoke Simkl only | | CLI + GUI light menu |
| 17 | Account stats | Simkl GET /users/{id}/stats | `simkl_account.py:389-400` | `cli_all.py:164-166` |
| 18 | Cast/covers/relations (read-only) | AniList GraphQL (`tp/characters.py:23,168-178`, `tp/continuewatch.py:20-23`, `tp/metadata.py:27,243-246`), Bangumi (`tp/bangumi.py`), Fandom (`tp/fandom.py`), Simkl records (`tp/simkl.py:188-211`, `tp/simkl_extra.py:124-142`) | cache-first | `gui_all.py:2666-2686`, `:2774-2775` |
| 19 | Title -> id resolution | Simkl fuzzy (`simkl_account.py:718-747`), AniList search+cache (`tracking.py:93-120`), MAL/AniList (`metadata.py:180,243-246`), playlist fallback `playlist.py:416-421` | | |

**Two sync entry points that never meet**: (a) realtime playback
`playlist._mark/_scrobble` -> `MultiTracker` (direct network, title-based),
(b) GUI watched menu -> `watched.json` -> `SyncQueue`/`Syncer` (id-based,
Simkl only). All other stateful writes are one-shot `SimklAccount` calls
hardcoded inside gui_all.

## Duplicated logic

1. Two Simkl REST clients: `tp/simkl.py:23-74` (own client_id/auth, no
   refresh) vs `tp/simkl_account.py:37-155` (own client_id, refresh) — same
   base, same auth file, divergent 401 handling.
2. Two Simkl CDN calendar fetchers: `library.py:17-55` (v2) vs
   `simkl_extra.py:164-180` (v1) — the GUI hits both.
3. Four AniList GraphQL clients: `tracking.py:17-19`, `metadata.py:27-29`,
   `characters.py:23`, `continuewatch.py:20-23` — no shared runner; auth only
   in tracking's.
4. Two 'recently aired' derivations: `library.py:70-76` vs `recent.py`.
5. Two title->id resolvers for mark-watched (Simkl fuzzy vs AniList resolve)
   plus a third via `skip.meta` in `playlist._mark`.
6. Two library-pull-with-activities-gate implementations with TWO stamp files
   (`simkl_library` vs `simkl_activities`).
7. Mark-watched reaches Simkl through two write paths (realtime
   `MultiTracker` vs queued `SimklPusher`), no shared gate.
8. `SimklAccount.add_to_list` built ad hoc at three gui_all call sites.
9. Next-episode air dates from three services, three row shapes.
10. Two watched-state stores: watched.json vs progress.json — neither feeds
    the other.
11. Resume-forgetting implemented twice (SimklTracker.forget +
    `playlist._mark` re-invoke).
12. Three id-key schemes for 'which show': `watched.key_for`, `show_key`,
    `_row_key`.
13. Three copies of 'call add_to_list on a thread + status message' in
    gui_all (`_simkl_write`, `add_current.work`, `_set_status.work`).

## Misplaced quirks / defects

1. `gui_all._wkey` keys the store by MAL only, so `watched.key_for`'s
   simkl-first preference is dead; Simkl-only donghua fall to a title key that
   breaks the queue's id mapping.
2. Season-wide marks queued as N per-episode calls although a native
   `mark_season_watched` exists (12 eps = 12 calls + Simkl's 20 s lock).
3. Ratings fire-and-forget from the menu while watched writes go through the
   durable queue — one service, two transports, chosen by which menu you used.
4. AniList save_progress hardcodes CURRENT/COMPLETED only; plan/drop/hold
   unreachable on AniList; 'series complete' never notifies AniList.
5. `unrate`/`ratings()` have zero callers — dead surface.
6. watched.json keeps no tombstones: a local unmark silently loses to any
   remote mark on the next pull.
7. library() delta never reports list removals — web-UI drops persist until
   the cache file is deleted.
8. `MultiTracker.scrobble` returns after the FIRST tracker while
   `mark_watched` fans out to all — inconsistent fan-out in one object.
9. SimklExtra reaches into `SimklAccount._api` (private), and `tp/simkl.py`
   duplicates endpoints `simkl_extra.py` also calls.
10. Offline realtime 'finish episode' is lost permanently for AniList (no
    queue on that path; raises swallowed).
11. Read-only services (Fandom/Bangumi/Jikan) and stateful (Simkl/AniList)
    interleaved in one pipeline with no 'tracker' marker.
12. Simkl's own mark-on-stop >=80% can race the app's history mark; the 409
    swallow hides it instead of reconciling.

## Proposed split: tp/tracking/ (same shape as tp/features/)

Service clients (thin, one HTTP surface, own auth file):
- `simkl_client.py` — merge `SimklAccount` + `tp/simkl.Simkl`: one client_id,
  one refresh, all /sync /scrobble /playback /anime + CDN feeds.
- `anilist_client.py` — one GraphQL runner (merge tracking/_gql,
  metadata._post, characters, continuewatch), optional Bearer.
- `local_store.py` — watched.json + progress.json as one facade, WITH
  tombstones.
- `wiki.py` — Fandom + Bangumi + cast cache (read-only).

Feature sync objects (own routing, queueing, dedupe):
- `watched.py` WatchedSync (episode/season/till-here/unwatch): local write
  first, then the offline queue for EVERY Simkl mutation; one entry point
  replaces `playlist._mark`'s direct MultiTracker call and gui's
  `_queue_watched`.
- `lists.py` ListStatusSync (add/drop/plan/hold/complete): Simkl native +
  AniList SaveMediaListEntry mapping; replaces the three gui call sites.
- `ratings.py` RatingSync (rate/unrate/read).
- `scrobble.py` ScrobbleSync (start/pause/stop) owning the >=80% auto-mark
  and 20 s lock pacing.
- `resume.py` ResumeSync (read/clear).
- `calendar.py` CalendarSync: ONE feed (v2 CDN) + recently-aired + future
  dates derived once (absorbs library.overview, recent.py,
  simkl_extra.calendar).
- `history.py` HistorySync.

Routing: `tp/tracking/__init__.py` REGISTRY =
`{'watched': {simkl, anilist, local}, 'lists': {...}, 'ratings': {...},
'scrobble': {...}, 'resume': {...}, 'calendar': {...}, 'cast': {...}}` +
`get(service, feature)`; a FanoutSync per feature with ONE policy per feature
(mark_watched -> all, scrobble -> first) decided in the registry, not a loop.

Hygiene folded in: tombstones (pull can unmark), ONE activities stamp,
_wkey extended to simkl ids, the offline queue as the single write path for
every Simkl mutation.
