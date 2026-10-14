# XUCL — UEFA Champions League match analytics

Multi-source analytics for the **UEFA Champions League**, built exactly like XEPL / XLALIGA: a
standings + results dashboard, a knockout bracket, an xG efficiency lab, a per-match "Match Centre"
(shot/pass/dribble maps, all-goals reconstruction), a player leaderboard, and a Poisson
**league-phase projection**. Cloned from the Premier League system (XEPL); shares the same
`xg_core/` model, so numbers compare across all three sites.

**Live dashboard:** `ucl_dashboard/index.html` (root `index.html` redirects there).

**Seasons:** 2022/23, 2023/24, 2024/25, 2025/26 complete, plus 2026/27 in progress.

## The format changed in the middle
| Seasons | Clubs | First phase | Then |
|---|---|---|---|
| 2022/23, 2023/24 | 32 | 8 groups of 4, 6 matchdays (head-to-head tiebreak) | top 2 → round of 16, 3rd → Europa League |
| 2024/25 onward | 36 | one league table, 8 matchdays (GD, GF, away GF, W, away W) | 1-8 → round of 16, 9-24 → knockout playoff, 25-36 out |

Every schedule record carries a `stage` (`group` / `league`, `PO`, `R16`, `QF`, `SF`, `F`), plus
`group` (old format), `matchday` (first phase) and `leg` (two-legged ties). `ucl/stages.py` derives
them from the fixtures themselves (dates, who-played-whom components, round sizes), so a FotMob pull
and an openfootball import end up labelled the same way. The dashboard switches the table (8 group
tables vs one 36-club table), zones, bracket and projection by `format`.

## How it works
Two data layers:
1. **Schedule spine (token-free):** `ucl/build_schedule.py` sweeps FotMob's public feed for the
   Champions League (league 42) → `ucl/schedules/SCHEDULE_<season>.json` with every fixture's real
   score, stage and matchday. Drives **standings, bracket, results and projection**.
   *Fallback:* `ucl/import_openfootball.py` writes the same files from the public-domain
   openfootball/champions-league data in `ucl/openfootball/` (used where FotMob is unreachable, e.g.
   cloud sessions). 2026/27 lives in a hand-kept `cl_2026-27.csv` until FotMob replaces it.
   A FotMob build always replaces an openfootball-seeded file.
2. **Rich per-match layer:** `ucl/scrape_whoscored.py` / `ucl/run_match.py` / `ucl/backfill.py`
   deep-scrape individual games (WhoScored + FotMob) into `ucl/matches/<season>/<id>.json`, adding
   xG (our own model, never another provider's), shot/pass/dribble maps and player stats. Understat
   does not cover the Champions League. The dashboard degrades gracefully: a match shows its
   result/table contribution immediately, its rich views once deep-scraped.

## Quick start (on the PC, where FotMob and WhoScored are reachable)
```bash
pip install -r requirements.txt
py ucl/build_schedule.py --season 2026-27 --full   # real fixtures + FotMob ids (replaces the seed)
py ucl/download_crests.py                          # club badges
py ucl/scrape_whoscored.py --season 2026-27        # events → xG/shots/players
py ucl_dashboard/build_match_details.py && py ucl_dashboard/build_players.py \
  && py ucl_dashboard/build_database.py && py ucl_dashboard/build_shots.py \
  && py ucl_dashboard/build_player_lab.py && py ucl_dashboard/build_data.py \
  && py ucl_dashboard/build_split.py               # build_split always last
py -m http.server 8778                             # → http://localhost:8778/ucl_dashboard/index.html
```
Without FotMob (results only):
```bash
py ucl/import_openfootball.py && py ucl_dashboard/build_data.py && py ucl_dashboard/build_split.py
```

## Layout
`ucl/` pipeline · `ucl_dashboard/` static site + builders · `ucl_png/` published PNGs ·
`team_logos/ucl/` crests · `xg_core/` shared xG/xA model.
