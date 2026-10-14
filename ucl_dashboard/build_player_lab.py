#!/usr/bin/env python3
"""Build per-team, per-SEASON player-event files for the Player Lab (ported from the
BCN dashboard, adapted to the whole league).

The Player Lab's stat cards / radar / head-to-head bars all read season aggregates
that already live in players.js. Only the ACTION MAPS (shots, take-ons, passes,
progressive passes) need per-player event locations. Those would be huge for all
600 players at once, so — like the match pages load matches_detail/<id>.js on
demand — we write ONE file per team and season (player_lab/<season>/<slug>.js)
that the Player Lab fetches when that team is picked.

Why per season: a team-only file makes a player's maps sum every scraped season
instead of the one on screen. Each matches_detail file carries no season field, so
season is derived from the match date the same way build_shots.season_of does.

Each file:  window.LL_PLAYERLAB[<season>][<Team>] = { "<player>": {shots, dribbles, passes} }
Event arrays are compact and ordered to match app.js `playerGraph`:
  shots    [x, y, gy, xg, goal, ontarget, min, opp]
  dribbles [x, y, -1, -1, ok, min, opp]        (WhoScored take-ons carry no end point)
  passes   [x, y, ex, ey, ok, prog, min, opp]  (progressive map = passes with prog=1)
Coords are raw WhoScored 0-100 (same as the match centre). No tackles map: the
league matches_detail doesn't carry tackle events.
"""
import glob, json, os, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DETAIL_DIR = os.path.join(HERE, "matches_detail")
OUT_DIR = os.path.join(HERE, "player_lab")


def slug(team):
    return re.sub(r"[^A-Za-z0-9]+", "_", team).strip("_")


def season_of(date_str):
    """'2024-08-16' -> '2024-25'  (a season starts in July). Matches build_shots.season_of."""
    try:
        y, m = int(date_str[:4]), int(date_str[5:7])
    except (ValueError, TypeError):
        return "unknown"
    start = y if m >= 7 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def _read(path):
    m = re.search(r"=\s*(\{.*\})\s*;?\s*$", open(path, encoding="utf-8").read(), re.S)
    return json.loads(m.group(1)) if m else None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    teams = {}   # team -> season -> {player -> {"shots":[], "dribbles":[], "passes":[]}}

    for f in sorted(glob.glob(os.path.join(DETAIL_DIR, "*.js"))):
        if os.path.basename(f).startswith("_"):
            continue
        d = _read(f)
        if not d:
            continue
        seas = season_of(d.get("date", ""))
        tn = {"home": d["home"]["name"], "away": d["away"]["name"]}
        opp = {"home": d["away"]["name"], "away": d["home"]["name"]}

        def rec(team, player):
            t = teams.setdefault(team, {}).setdefault(seas, {})
            return t.setdefault(player, {"shots": [], "dribbles": [], "passes": []})

        for s in d.get("shots", []):
            p = s.get("player")
            side = s.get("team")
            if not p or side not in tn:
                continue
            gy = s.get("gy")
            rec(tn[side], p)["shots"].append([
                round(s.get("x", 0) or 0, 1), round(s.get("y", 0) or 0, 1),
                round(gy if gy is not None else 50.0, 1),
                round(float(s.get("xg", 0) or 0), 3),
                1 if s.get("goal") else 0, 1 if s.get("onTarget") else 0,
                int(s.get("min", 0) or 0), opp[side],
            ])
        for dr in d.get("dribbles", []):
            p = dr.get("player")
            side = dr.get("team")
            if not p or side not in tn:
                continue
            rec(tn[side], p)["dribbles"].append([
                round(dr.get("x", 0) or 0, 1), round(dr.get("y", 0) or 0, 1),
                -1, -1, 1 if dr.get("ok") else 0, int(dr.get("min", 0) or 0), opp[side],
            ])
        for pa in d.get("passes", []):
            p = pa.get("player")
            side = pa.get("team")
            if not p or side not in tn:
                continue
            rec(tn[side], p)["passes"].append([
                round(pa.get("x", 0) or 0, 1), round(pa.get("y", 0) or 0, 1),
                round(pa.get("ex", 0) or 0, 1), round(pa.get("ey", 0) or 0, 1),
                1 if pa.get("ok") else 0, 1 if pa.get("prog") else 0,
                int(pa.get("min", 0) or 0), opp[side],
            ])

    # Rebuild the output tree from scratch so stale team-only files never linger, then
    # write one file per season+team: player_lab/<season>/<slug>.js.
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    idx = {}
    total = 0
    for team, by_season in teams.items():
        for seas, players in by_season.items():
            players = {p: v for p, v in players.items()
                       if v["shots"] or v["dribbles"] or v["passes"]}
            if not players:
                continue
            sdir = os.path.join(OUT_DIR, seas)
            os.makedirs(sdir, exist_ok=True)
            path = os.path.join(sdir, slug(team) + ".js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("window.LL_PLAYERLAB = window.LL_PLAYERLAB || {};\n")
                fh.write("window.LL_PLAYERLAB[" + json.dumps(seas) + "] = window.LL_PLAYERLAB[" + json.dumps(seas) + "] || {};\n")
                fh.write("window.LL_PLAYERLAB[" + json.dumps(seas) + "][" + json.dumps(team, ensure_ascii=False) + "] = ")
                json.dump(players, fh, ensure_ascii=False, separators=(",", ":"))
                fh.write(";\n")
            idx.setdefault(seas, {})[team] = {"slug": slug(team), "players": len(players)}
            total += len(players)

    with open(os.path.join(OUT_DIR, "_index.js"), "w", encoding="utf-8") as fh:
        fh.write("window.LL_PLAYERLAB_TEAMS = ")
        json.dump(idx, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    for seas in sorted(idx):
        print(f"  {seas}: {len(idx[seas])} team files")
    print(f"wrote player_lab/<season>/<team>.js for {len(idx)} seasons ({total} player-seasons total)")


if __name__ == "__main__":
    main()
