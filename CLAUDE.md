# CLAUDE.md — XUCL project guide (read this first)

**UEFA Champions League match analytics.** Two outputs from one scraped dataset: an interactive
**web dashboard** (`ucl_dashboard/`, static site) and a per-match **PNG infographic**
(`ucl/renderer.py`). Cloned from the Premier League system (XEPL, itself built on XLALIGA);
`xg_core/` is the shared model. Keep the structure identical to XEPL/XLALIGA and port fixes from
XLALIGA, which is usually ahead.

- **Live site:** root `index.html` redirects to `ucl_dashboard/`. (Enable GitHub Pages on `main`.)
- This repo is self-contained: `ucl/` pipeline, `ucl_dashboard/` site, `xg_core/` model,
  `team_logos/ucl/` crests, `ucl_png/` published PNGs.

## The format change (read before touching standings or projection)
- **2022-23, 2023-24 (`format: "groups"`):** 32 clubs, 8 groups of 4, 6 matchdays, 125 matches.
  Group ties break on head-to-head first. Top 2 → R16, 3rd → Europa League.
- **2024-25 onward (`format: "league"`):** 36 clubs, one league-phase table, 8 matchdays, 189
  matches. Ties: GD, GF, away GF, wins, away wins. 1-8 → R16, 9-24 → knockout playoff (PO), 25-36 out.
- `ucl/stages.py` is the single source of truth: `format_of(season)`, `assign_stages()` (stage /
  group / matchday / leg derived from the fixtures; verified to reproduce openfootball's labels for
  all four complete seasons), `GROUP_SEEDS` (one club per group pins UEFA's letter).
- `ucl_dashboard/build_data.py` builds per-season `format`, `groups`, `rounds` (two-legged ties with
  aggregate, aet, pens, winner), `reach`, `champion`; `app.js` switches table/zones/bracket/projection on it.

## CURRENT STATE
- **Schedules only, rich layer not scraped yet.** `ucl/schedules/` is seeded from openfootball
  (`ucl/import_openfootball.py`, files in `ucl/openfootball/`): 2022-23 to 2025-26 complete
  (125/125/189/189), 2026-27 entered by hand from news reports in `cl_2026-27.csv` (matchday 1 and
  part of matchday 2 as of 2026-10-14; verify against FotMob). Seeded records have synthetic
  `fotmob_id`s (`of-<season>-NNN`) and no team ids, so crests and the rich layer stay empty.
- **To fill in for real** — on Ram's PC (FotMob/WhoScored are firewalled from cloud sessions):
  ```bash
  py ucl/build_schedule.py --season 2026-27 --full     # FotMob 42 → replaces the openfootball seed
  py ucl/download_crests.py                             # crests → team_logos/ucl/
  py ucl/scrape_whoscored.py --season 2026-27           # Chrome; rich xG/shot/player layer
  py ucl/render_missing.py --season 2026-27              # PNGs → ucl_png/
  py ucl_dashboard/build_site.py                         # all builders, build_split last
  git add -A && git commit -m "UCL 2026/27 data" && git push
  ```
  Repeat per season. **`build_split.py` must be the LAST step of every rebuild.** For a routine
  refresh `py ucl/build_schedule.py --season 2026-27` (no `--full`) or `py ucl/weekly_update.py`.
- **xG is always ours** (`xg_core`), computed from WhoScored shots. Never copy another provider's xG.

## Config
FotMob league **42** (`UCL_FOTMOB_LEAGUE_ID`); WhoScored
`Regions/250/Tournaments/12/Europe-Champions-League` (`UCL_WHOSCORED_URLS`, check the URL on the
first run); no Understat coverage (`UNDERSTAT_FALLBACK=0`); crests `team_logos/ucl/`; PNGs
`ucl_png/` (`UCL_PNG_SUBDIR`); raw scrapes `ucl/matches/` (`UCL_MATCH_DIR` for rebuilds in a clean clone).

## Zones (format-aware)
Groups: 1-2 qualify (`z-ucl`), 3 → Europa (`z-uel`), 4 out. League phase: 1-8 → R16, 9-24 →
playoff, 25-36 out. Lives in `ucl_dashboard/app.js` `zoneOf()` AND the projection — edit both.

## Design system — "Broadcast Kinetic"
The dashboard skin (`ucl_dashboard/styles.css`, `match.css`) is a live-sport broadcast-graphics
identity: carbon ground, ONE signal accent colour (`--accent: #3b82f6`, "Champions League blue" —
UEFA blue, so it differs from XEPL purple and XLALIGA lime), chamfered plates
(`clip-path: var(--plate-cut)`), slanted tabs/buttons/chips (`--slant`/`--slant-sm`), condensed
italic display type (Barlow Condensed/Barlow), and hatched diagonal-stripe comparison bars
(`--hatch-accent`) instead of flat fills. `--brand-red: #ff2a4d` is the only other semantic colour
(negative/relegation) and is shared with La Liga on purpose — it's sport-neutral. No
`border-radius` anywhere in this skin. Ported from `XLALIGA`'s `feat/dashboard-beta` branch —
re-derive the accent per fork rather than copying another sport's colour blindly.

## Gotchas
- **Header is two rows at every width, the same in XLALIGA and XUCL** — brand + season picker on row 1,
  `nav.tabs` takes the whole of row 2 (`order: 3; flex: 1 0 100%`). Don't bring back a one-row header
  breakpoint: nine tabs next to the wordmark got clipped behind the season picker on wide screens.
  Tab strips and the Match Centre section bar fade only on the side that hides more (`wireScrollFade` in
  `app.js`/`match.js`, `.scroll-fade` in `styles.css`).
- **"Season story" above the table is written client-side** (`app.js renderInsights`) from standings,
  `teamPoints()`/`AGG` and players — leader, best xG difference, over/under-achiever vs expected points,
  top scorer — each tile naming a different club where it can. Hebrew comes from `data-he-html` on
  each tile, so new sentences need both languages.
- **Player Lab URLs carry the player**: `#<season>/playerlab/<Team @@ Player>` is kept in the address bar
  and the "Copy link" button copies it; opening that link selects the player.
- **Past seasons on WhoScored**: the season-less fixtures page only lists the live season, so
  `scrape_whoscored.py --season <old>` picks that season in WhoScored's season dropdown
  (`season_fixtures_url`) or takes `--url <that season's Fixtures page>`, then sweeps each stage in its stage dropdown (`stage_urls`): the calendar only pages within one stage, so a single sweep stopped at the knockout playoff and missed the league phase. `find_fixture` also
  requires the kick-off date (±3 days) and, when the schedule has one, the final score to agree,
  because the same two clubs can meet in several seasons (a 2026-27 Liverpool v Atletico was once
  saved over 2025-26's).
- **Team-matcher must NOT strip "united"/"city"** — `ucl/scrape_whoscored._key` keeps them so the
  two Manchester clubs never collide (the analogue of La Liga's "don't strip real" rule).
- **xG/xA come from `xg_core/`** (shared, league-agnostic; UCL passed as the league key, falls
  back to the `_global` shift until an UCL corpus is trained).
- **Raw match JSONs are gitignored** (`ucl/matches/20*/*.json`, ~2 MB each). The dashboard ships
  the derived `ucl_dashboard/matches_detail/*.js` instead.
- **players.js fields are `g`/`a`/`xg`/`mp`** (not `goals`/`assists`); `app.js` reads those.
- **Scores come from WhoScored, not the FotMob schedule** — FotMob's historical/mid-season feed
  reports `0-0` for some games (17 in 2022-23, 9 in 2023-24, 1 in 2024-25) and null for unplayed
  fixtures. `build_data` prefers the rich WhoScored score whenever a match has scraped events (it
  matches the event-derived score for every match, every season); the schedule is only the fallback.
- **The site loads per-season bundles, not the monolithic files.** `index.html`/`match.html` load
  `ucl_dashboard/data/index.js` (`window.LL_INDEX`: season list + a content-hash `v` cache-buster +
  `teamColors`) statically; `app.js`/`match.js` fetch `data/<season>.js` on demand
  (`loadSeason()`/`loadSeasonData()`) instead of the old monolithic `data.js`/`players.js`/
  `shots.js` (those three still get written by their builders and stay in git — `build_split.py`
  slices them into `data/`). **`build_split.py` must run LAST**, after `build_data.py` — it reads
  `data.js` off disk. Forgetting it (or running it before `build_data.py`) means the site silently
  keeps serving the previous build's `data/*.js` bundles.
- **Player Lab event files are keyed by SEASON, not just team** —
  `player_lab/<season>/<team-slug>.js` (`window.LL_PLAYERLAB[season][team]`), rebuilt from scratch
  every run by `build_player_lab.py` so a stale team-only file never lingers. `app.js`'s
  `plLoadTeam()`/`plEvents()` read `[season][team]`; a naive `[team]`-only key would sum a
  player's shot/pass maps across every scraped season instead of the one on screen.
- **Match Centre team-colour collision guard** — `match.js` `teamColours()` measures the CIE76 ΔE
  between the home/away primaries (from `ucl/team_colors.py` via `LL_INDEX.teamColors`); two clubs
  whose primaries are near-identical (e.g. Liverpool vs Nottingham Forest, both red) fall back the
  away side to its secondary kit colour, then to a neutral. Every downstream mark (shot map, pass
  network, stat bars) reads `D.home.color`/`D.away.color` **after** this runs, so add new
  colour-coded marks after `boot()` sets them, not before.
- **In-browser PNG export** (`match_export.js`, `window.LL_EXPORT.render/download`) draws the match
  board straight to a `<canvas>` in the Broadcast Kinetic skin and downloads it client-side — no
  server, works on the deployed GitHub Pages site. It's the "Download image" button next to the
  pipeline-rendered "Pipeline PNG" link in the Match Centre header; the pipeline PNG is still
  needed for anything that posts a pre-rendered image (e.g. social automation), so both stay.
- **`ucl/render_missing.py`** renders PNGs from raw match JSONs for matches scraped in bulk
  (`scrape_whoscored.py` only saves JSON, no image) and publishes them to `ucl_png/` — a PNG that
  only exists in the git-ignored `ucl/output/` 404s on GitHub Pages. It's the first step of every
  rebuild (`build_site.py`, `renderer._refresh_web_dashboard_db`); `build_data.py`'s `_find_png()`
  also self-heals by copying an `ucl/output/`-only PNG into `ucl_png/` the next time it runs.
- **FotMob's fixture feed moved twice** — `api.fotmob.com/matches?date=` (the original token-free
  XML feed) went LIVE-ONLY in 2026: root `<live>/<exmatches>`, `?date` is ignored, so it rarely has
  anything for a past or future date any more. `build_schedule.py` and `scraper.fotmob_fetch_wc_matches`
  now try `www.fotmob.com/api/data/leagues?id=47&season=` (whole season, one request, carries the
  round number) and `www.fotmob.com/api/data/matches?date=` (site API, every league that day)
  first, falling back to the legacy XML endpoint only if those come back empty. Every one of these
  is blocked from this sandboxed session's network policy (403 via the proxy) — the openfootball
  static mirror (`raw.githubusercontent.com/openfootball/football.json`) is reachable here but its
  future-season files can be placeholder/template data, not confirmed fixtures — don't trust it for
  real team names. Run the scrapers on a machine with real network access.
- **"Champions League" is not a unique league name on FotMob** — at least a dozen countries (Russia,
  Egypt, Wales, Canada, Kazakhstan, Ukraine, Belarus, Azerbaijan, …) run a division literally named
  "Champions League". `_is_ucl`/`_is_our_league` (`build_schedule.py`, `scraper.py`) always accept an
  exact FotMob league id match, but gate the *name* fallback on the England country code (`ccode`)
  — matching by name alone would occasionally pull in a foreign league's fixtures on a day-sweep.
- **Matchday isn't always in FotMob's feed.** `build_schedule.py`'s `_fill_missing_rounds` tries,
  in order: the round field the payload already carries; the fixture order; kickoff order; then
  earliest-fit packing (each fixture in date order drops into the earliest round with a free slot
  and neither team in it — robust to postponed/rearranged games, unlike a naive "new round when a
  team recurs" split, which fragments the season). If nothing validates, matchday is left empty
  rather than published wrong.
- **`build_schedule.py` is incremental by default** — with a schedule already on disk it sweeps
  from a few days before the last finished match to a fortnight ahead and merges in
  (`sweep_window`/`merge_matches`); `--full` forces the whole season window (needed once, when a
  season is brand new). `--debug-day YYYY-MM-DD` dumps what a date's feed actually contains and
  `--probe-endpoints YYYY-MM-DD` tries every known fixture source — reach for these before assuming
  "no matches" means the season hasn't started.
- **`UCL_SKIP_DASHBOARD_REFRESH=1`** skips `renderer._refresh_web_dashboard_db()` entirely —
  `backfill.py` sets it for the whole batch and rebuilds once at the end instead, because the
  per-match refresh re-reads every season and rewrites every derived file (fourteen full rebuilds
  racing a live Chrome, for a fourteen-match batch, is how you crash the machine). **`build_site.py`
  does NOT set this env var before its own `render_missing.main()` step** — if a season has a
  backlog of bulk-scraped matches that were never rendered (e.g. `scrape_whoscored.py` ran for
  weeks without anyone running the renderer), plain `py ucl_dashboard/build_site.py` hits the exact
  same cascade on that whole backlog even though it's not `backfill.py`: 33 unrendered matches took
  over 2 hours and was still going. Clear any backlog first with
  `UCL_SKIP_DASHBOARD_REFRESH=1 py ucl/render_missing.py --season <season>` (seconds per match
  instead of minutes), *then* run `build_site.py` (or the remaining seven builders directly) — don't
  reach for plain `build_site.py` as the first move on a season that hasn't been rendered in a while.
- **Box entries (Team Lab "Box entries · per game") are derived, not scraped** — `build_data._box_entries`
  reads `ucl_dashboard/matches_detail/<id>.js` and counts completed open-play passes + successful
  take-ons that start outside the opponent's box (x≥83, 21.1≤y≤78.9) and end inside it; corners are
  excluded. Stored per match as `m.box = [home, away]`; `app.js renderBoxTable` averages made/allowed per
  team. WhoScored has no carry events, so dribble-free carries into the box aren't counted — the
  numbers run below Opta's "box entries". Needs `build_match_details.py` before `build_data.py`.
- **Distance covered (Team Lab "avg km per game") is FotMob's team stat, not the scrape** — it's
  tracking data, so no WhoScored/Opta event ever carries it. `ucl/fetch_team_stats.py --season <s>`
  finds the "distance" entry among the team stats in FotMob's league payload (falls back to guessed
  `data.fotmob.com/stats/47/season/<id>/<name>.json` URLs) and writes the tracked
  `ucl/team_stats/DISTANCE_<season>.json`; `build_data.build_distance` maps it onto schedule names by
  FotMob team id → `LL_DATA.seasons[s].distance`. `weekly_update.py` runs it before `backfill.py`.
  If FotMob renames the stat, `--dump` lists what the payload offers. FotMob only has it for recent
  seasons — older seasons show the empty state.
- **A WhoScored failure used to be invisible and permanent** — the match still saved (FotMob shots
  only, no event stream), so a plain "already scraped" check counted it done and no later run
  would ever fill in the maps/lineups/pass network. `backfill.py` now classifies each match
  none/partial/full (`_scrape_state`) and `--redo-partial` retries only the partials.
- **`PROGRESS.md` is an append-only journal, not hand-maintained prose** — `ucl/progress_log.py`
  (`log_scrape`/`log_platform`/`log_lesson`) is called automatically from `run_match.py`,
  `scrape_whoscored.py` and `backfill.py`, so every scrape — scheduled task, bulk backfill, or a
  manual run — leaves a row in the Scrape log table whether it succeeded or not. Write the Platform
  and Lessons sections by hand or with `py ucl/progress_log.py platform "..."` /
  `... lesson --worked/--failed "..."`. `ucl/check_data.py --season <season> [--detail]` reports
  what each scraped match's raw JSON actually contains (sources, event count, xG, player count) —
  reach for it before assuming a thin dashboard page means a scrape bug rather than a partial scrape.
- **Two ways to automate scraping on a Windows machine**: `ucl/register_tasks.ps1` registers one
  Scheduled Task per fixture that runs `run_match.py --fotmob-id <id>` directly (needs `GIT_TOKEN`
  in `.env` for `git_ops.py`'s auto-push). `ucl/register_fixture_tasks.ps1` is the newer,
  token-free alternative: one Scheduled Task per fixture that instead runs
  `ucl/weekly_update.py --season <season>` at kick-off+3h, which re-sweeps the whole season
  (fixtures refresh + `backfill.py` for anything newly finished) and pushes with plain `git push`
  against the local clone's own already-authenticated remote — no token needed. Both can coexist;
  `weekly_update.py` is also runnable on its own fixed weekly schedule via
  `ucl/register_weekly_task.ps1` as a safety net that catches whatever a missed per-fixture run did.
