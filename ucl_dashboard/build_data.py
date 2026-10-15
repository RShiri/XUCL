#!/usr/bin/env python3
"""Build data.js for the Champions League dashboard — one payload per season, from the FotMob
schedule (spine: fixtures/results/standings) plus any rich per-match scrapes.

Unlike the WC2026 builder (whose primary source was the rich scraped match JSONs), a
league is driven by its **schedule**: ``ucl/schedules/SCHEDULE_<season>.json`` already
carries every fixture with real scores + matchday (built token-free from FotMob by
``ucl/build_schedule.py``). Rich per-match data (xG, shots, events) is *layered on*
when present in ``ucl/matches/<season>/<fotmob_id>.json`` — the same files the browser
scrapers (``ucl/run_match.py`` / ``ucl/backfill.py``) produce. Matches with no rich
file still appear with their score/standings contribution; the xG lab simply fills in as
matches get deep-scraped.

Output: one self-contained ``data.js`` →
    window.LL_DATA = { "2025-26": {...}, "2026-27": {...} };
so the static site works by just opening index.html (no build step at view time).
"""
from __future__ import annotations

import os
import sys
import json
import glob
import shutil
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xg_model import team_xg_from_events, team_ppda_from_events  # shared shot-extraction + xG (matches the PNGs)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ucl.stages import format_of, assign_stages, FIRST_PHASE  # noqa: E402  (groups vs league phase, KO rounds)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHED_DIR = os.path.join(ROOT, "ucl", "schedules")
TEAM_STATS_DIR = os.path.join(ROOT, "ucl", "team_stats")  # FotMob season team stats (fetch_team_stats.py)
MATCH_DIR = os.environ.get("UCL_MATCH_DIR") or os.path.join(ROOT, "ucl", "matches")  # rich scrapes: <season>/<id>.json
PNG_DIRS = [os.path.join(ROOT, "ucl_png"), os.path.join(ROOT, "ucl", "output")]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.js")

FOTMOB_CREST = "https://images.fotmob.com/image_resources/logo/teamlogo/{id}.png"
CREST_DIR = os.path.join(ROOT, "team_logos", "ucl")


def _crest(team, team_id):
    """Prefer a locally downloaded crest (self-contained site); fall back to the CDN."""
    fname = team.replace("/", "-")  # same file-name rule as ucl/download_crests.py
    local = os.path.join(CREST_DIR, f"{fname}.png")
    if os.path.exists(local):
        return f"../team_logos/ucl/{fname}.png"
    return FOTMOB_CREST.format(id=team_id) if team_id else ""

# Canonical stat keys we surface (same set the WC dashboard used), mapped to how the
# scraper stores them in a rich match JSON's ``match_stats`` (nested {home,away} or flat).
_STAT_KEYS = {
    "xg": "xg", "shots": "shots", "sot": "shots_on_target",
    "possession": "possession", "passes": "passes_total",
    "pass_acc": "passes_accuracy", "big_chances": "big_chances_created",
    "big_missed": "big_chances_missed", "saves": "saves", "fouls": "fouls",
    "duels_won": "duels_won", "corners": "corners",
}


def _pair(ms, canonical):
    v = ms.get(canonical)
    if isinstance(v, dict):
        return [v.get("home"), v.get("away")]
    return [ms.get(canonical + "_home"), ms.get(canonical + "_away")]


def _stat_line(ms):
    line = {dst: _pair(ms, canon) for dst, canon in _STAT_KEYS.items()}
    if line["pass_acc"] == [None, None]:
        line["pass_acc"] = _pair(ms, "pass_accuracy")
    return line


def _find_png(season, fotmob_id):
    """Link to the PUBLISHED copy (ucl_png/, tracked) — a PNG that only exists in the
    git-ignored ucl/output/ works on localhost but 404s on GitHub Pages, so copy it into
    ucl_png/ here and always emit that path."""
    published, output = (os.path.join(d, f"{fotmob_id}.png") for d in PNG_DIRS)
    if not os.path.exists(published) and os.path.exists(output):
        try:
            os.makedirs(os.path.dirname(published), exist_ok=True)
            shutil.copy2(output, published)
        except OSError:
            return os.path.relpath(output, os.path.dirname(OUT)).replace("\\", "/")
    if os.path.exists(published):
        return os.path.relpath(published, os.path.dirname(OUT)).replace("\\", "/")
    return None


# Box entries come from the derived matches_detail/<id>.js (build_match_details.py runs first),
# which keeps every pass and take-on with start/end coords, normalised so each side attacks x=100.
DETAIL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matches_detail")


def _in_box(x, y):
    """Opponent's penalty area in WhoScored 0-100 coords (attacking toward x=100)."""
    return x is not None and y is not None and x >= 83 and 21.1 <= y <= 78.9


def _box_entries(fotmob_id):
    """[home, away] box entries for one match, or None without a detail file. An entry is a
    completed open-play pass or a successful take-on that starts outside the opponent's box and
    ends inside it. Corners (taken from the flag, x>=99 at a touchline) are left out: they're set
    pieces, not a way of working the ball into the area."""
    path = os.path.join(DETAIL_DIR, f"{fotmob_id}.js")
    if not os.path.exists(path):
        return None
    try:
        raw = open(path, encoding="utf-8").read()
        d = json.loads(raw[raw.index("{"):raw.rstrip().rstrip(";").rindex("}") + 1])
    except Exception:
        return None
    out = {"home": 0, "away": 0}
    for p in d.get("passes") or []:
        if not p.get("ok") or p.get("team") not in out:
            continue
        if p.get("x", 0) >= 99 and (p.get("y", 50) <= 5 or p.get("y", 50) >= 95):
            continue                                   # corner kick
        if not _in_box(p.get("x"), p.get("y")) and _in_box(p.get("ex"), p.get("ey")):
            out[p["team"]] += 1
    for t in d.get("dribbles") or []:
        if t.get("ok") and t.get("team") in out and not _in_box(t.get("x"), t.get("y")) \
                and _in_box(t.get("ex"), t.get("ey")):
            out[t["team"]] += 1
    if not (d.get("passes") or d.get("dribbles")):
        return None
    return [out["home"], out["away"]]


def _load_rich(season, fotmob_id):
    """Return the rich scraped match JSON for a fixture, or None."""
    for cand in (os.path.join(MATCH_DIR, season, f"{fotmob_id}.json"),
                 os.path.join(MATCH_DIR, f"{fotmob_id}.json")):
        if os.path.exists(cand):
            try:
                return json.load(open(cand, encoding="utf-8"))
            except Exception:
                return None
    return None


def build_matches(season, schedule):
    """Merge schedule fixtures with any rich scrape → the dashboard match list + crest map."""
    matches, crests, countries = [], {}, {}
    for f in schedule["matches"]:
        fid = f["fotmob_id"]
        home, away = f["home"], f["away"]
        for side in ("home", "away"):
            cc = f.get(side + "_country")
            if cc:
                countries[f[side]] = cc
        if home not in crests:
            crests[home] = _crest(home, f.get("home_id"))
        if away not in crests:
            crests[away] = _crest(away, f.get("away_id"))

        hs, as_ = f.get("home_score"), f.get("away_score")
        stats = {k: [None, None] for k in _STAT_KEYS}
        xg_home = xg_away = None
        xg_estimated = False
        has_events = False
        sources = []
        ppda_home = ppda_away = None

        rich = _load_rich(season, fid)
        if rich:
            ms = rich.get("match_stats") or {}
            stats = _stat_line(ms)
            xg_home, xg_away = stats["xg"][0], stats["xg"][1]
            sources = rich.get("_sources", [])
            has_events = bool(rich.get("events"))
            # WhoScored is authoritative for the score whenever we have its event data. FotMob's
            # schedule feed reports 0-0 for a chunk of older-season games (17 in 2022-23, 9 in
            # 2023-24, 1 in 2024-25) and null for fixtures still unplayed when the spine was built —
            # both wrong once the match is scraped. The rich fulltime score matches the event-derived
            # score for every match in every season, so trust it when events exist; else fall back
            # to the schedule (and fill a missing schedule score from the rich file if we have one).
            rhs, ras = rich.get("home", {}).get("score"), rich.get("away", {}).get("score")
            if rich.get("events"):
                if rhs is not None:
                    hs = rhs
                if ras is not None:
                    as_ = ras
            else:
                if hs is None:
                    hs = rhs
                if as_ is None:
                    as_ = ras
            if (xg_home is None or xg_away is None) and rich.get("events"):
                ch, ca = team_xg_from_events(rich)
                if ch is not None:
                    xg_home, xg_away, xg_estimated = ch, ca, True
                    stats["xg"] = [xg_home, xg_away]
            if rich.get("events"):
                ppda_home, ppda_away = team_ppda_from_events(rich)

        played = hs is not None and as_ is not None
        has_stats = stats["xg"][0] is not None or stats["shots"][0] is not None
        matches.append({
            "id": str(fid),
            "fotmob_id": fid,
            "date": f.get("date") or "",
            "matchday": f.get("matchday"),
            "stage": f.get("stage"), "group": f.get("group"), "leg": f.get("leg"),
            "aet": bool(f.get("aet")), "pens": f.get("pens"),
            "venue": (rich or {}).get("meta", {}).get("venue", "") if rich else "",
            "home": home, "away": away,
            "home_id": f.get("home_id"), "away_id": f.get("away_id"),
            "hs": hs, "as": as_,
            "played": played,
            "upcoming": not played,
            "kickoff": f.get("kickoff_utc") or "",
            "has_stats": bool(has_stats),
            "has_events": has_events,
            "xg_home": xg_home, "xg_away": xg_away,
            "xg_estimated": xg_estimated,
            "png": _find_png(season, fid),
            "stats": stats,
            "sources": sources,
            "ppda_home": ppda_home, "ppda_away": ppda_away,
            "box": _box_entries(fid) if (played and has_events) else None,
        })
    return matches, crests, countries


def compute_standings(matches, h2h=False):
    """One table from finished results. League phase (and the old fork default) ranks
    Pts → GD → GF → away goals → wins → away wins → name (UCL league-phase order, minus the
    opponents'-points / disciplinary / coefficient steps). ``h2h=True`` is the old group-stage
    order: head-to-head points, GD, goals among the tied clubs first, then overall GD, GF."""
    T = {}
    for m in matches:
        if not m["played"]:
            continue
        h, a, hs, as_ = m["home"], m["away"], m["hs"], m["as"]
        for t in (h, a):
            T.setdefault(t, dict(team=t, P=0, W=0, D=0, L=0, GF=0, GA=0, GD=0, Pts=0, form=[],
                                 ppda_sum=0.0, ppda_n=0, AGF=0, AW=0))
        H, A = T[h], T[a]
        A["AGF"] += as_
        if as_ > hs:
            A["AW"] += 1
        if m.get("ppda_home") is not None:
            H["ppda_sum"] += m["ppda_home"]; H["ppda_n"] += 1
        if m.get("ppda_away") is not None:
            A["ppda_sum"] += m["ppda_away"]; A["ppda_n"] += 1
        H["P"] += 1; A["P"] += 1
        H["GF"] += hs; H["GA"] += as_; A["GF"] += as_; A["GA"] += hs
        if hs > as_:
            H["W"] += 1; H["Pts"] += 3; A["L"] += 1; H["form"].append(["W", m]); A["form"].append(["L", m])
        elif hs < as_:
            A["W"] += 1; A["Pts"] += 3; H["L"] += 1; A["form"].append(["W", m]); H["form"].append(["L", m])
        else:
            H["D"] += 1; A["D"] += 1; H["Pts"] += 1; A["Pts"] += 1
            H["form"].append(["D", m]); A["form"].append(["D", m])
    # Make sure every team that has a fixture appears, even with 0 played.
    for m in matches:
        for t in (m["home"], m["away"]):
            T.setdefault(t, dict(team=t, P=0, W=0, D=0, L=0, GF=0, GA=0, GD=0, Pts=0, form=[],
                                 ppda_sum=0.0, ppda_n=0, AGF=0, AW=0))
    rows = list(T.values())
    for r in rows:
        r["GD"] = r["GF"] - r["GA"]
        # last-5 form (most recent first), by kickoff order
        r["form"] = [fm[0] for fm in sorted(r["form"], key=lambda x: x[1].get("kickoff") or x[1]["date"])][-5:]
        # PPDA: season average of the per-match values (a rate stat, not a sum).
        r["ppda"] = round(r["ppda_sum"] / r["ppda_n"], 2) if r["ppda_n"] else None
        del r["ppda_sum"], r["ppda_n"]
    rows.sort(key=lambda r: (-r["Pts"], -r["GD"], -r["GF"], -r["AGF"], -r["W"], -r["AW"], r["team"]))
    if h2h:
        played = [m for m in matches if m["played"]]
        out, i = [], 0
        while i < len(rows):
            j = i
            while j < len(rows) and rows[j]["Pts"] == rows[i]["Pts"]:
                j += 1
            tied = rows[i:j]
            if len(tied) > 1:
                names = {r["team"] for r in tied}
                mini = {r["team"]: r for r in compute_standings(
                    [m for m in played if m["home"] in names and m["away"] in names])}
                key = lambda r: tuple(-mini[r["team"]][k] if r["team"] in mini else 0 for k in ("Pts", "GD", "GF")) + (-r["GD"], -r["GF"], r["team"])
                tied = sorted(tied, key=key)
            out += tied
            i = j
        rows = out
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("AGF", None); r.pop("AW", None)
    return rows


KO_ORDER = ["PO", "R16", "QF", "SF", "F"]


def build_ties(matches):
    """Knockout ties per round: legs, aggregate, extra time / penalties, winner. A level
    aggregate with no shoot-out score in the feed falls back to whichever club turns up in the
    next round (FotMob doesn't always carry the shoot-out score in its schedule feed)."""
    rounds = {}
    for rnd in KO_ORDER:
        games = sorted((m for m in matches if m.get("stage") == rnd), key=lambda m: m.get("kickoff") or m["date"])
        pairs = {}
        for m in games:
            pairs.setdefault(frozenset((m["home"], m["away"])), []).append(m)
        ties = []
        for legs in pairs.values():
            a, b = legs[0]["home"], legs[0]["away"]          # a hosts the first leg
            played = [m for m in legs if m["played"]]
            ga = sum(m["hs"] if m["home"] == a else m["as"] for m in played)
            gb = sum(m["hs"] if m["home"] == b else m["as"] for m in played)
            last = legs[-1]
            done = played and len(played) == len(legs) and (rnd == "F" or len(legs) == 2)
            winner, pens = None, None
            if last.get("pens"):
                pens = last["pens"] if last["home"] == a else last["pens"][::-1]
            if done:
                if ga != gb:
                    winner = a if ga > gb else b
                elif pens:
                    winner = a if pens[0] > pens[1] else b
            ties.append({"a": a, "b": b, "agg": [ga, gb], "winner": winner, "pens": pens,
                         "aet": any(m.get("aet") for m in played),
                         "legs": [m["id"] for m in legs], "done": bool(done)})
        if ties:
            rounds[rnd] = ties
    # fallback winners from the next round
    for i, rnd in enumerate(KO_ORDER[:-1]):
        nxt = {t for tie in rounds.get(KO_ORDER[i + 1], []) for t in (tie["a"], tie["b"])}
        for tie in rounds.get(rnd, []):
            if tie["done"] and not tie["winner"]:
                hit = [t for t in (tie["a"], tie["b"]) if t in nxt]
                if len(hit) == 1:
                    tie["winner"] = hit[0]
    return rounds


def reach_of(teams, rounds):
    """Furthest stage per club: 'first' (group / league phase), PO, R16, QF, SF, F, W."""
    reach = {t: "first" for t in teams}
    for rnd in KO_ORDER:
        for tie in rounds.get(rnd, []):
            for t in (tie["a"], tie["b"]):
                reach[t] = rnd
    fin = (rounds.get("F") or [None])[0]
    if fin and fin.get("winner"):
        reach[fin["winner"]] = "W"
    return reach


def build_xg_records(matches):
    recs = []
    for m in matches:
        if not m["played"] or m["xg_home"] is None or m["xg_away"] is None:
            continue
        recs.append(dict(team=m["home"], opp=m["away"], gf=m["hs"], ga=m["as"],
                         xgf=round(m["xg_home"], 2), xga=round(m["xg_away"], 2), home=True, date=m["date"]))
        recs.append(dict(team=m["away"], opp=m["home"], gf=m["as"], ga=m["hs"],
                         xgf=round(m["xg_away"], 2), xga=round(m["xg_home"], 2), home=False, date=m["date"]))
    return recs


def build_distance(season, schedule):
    """Avg km covered per match, per club, from ucl/team_stats/DISTANCE_<season>.json (FotMob's
    "Total distance per match" team stat — tracking data, so no event scrape can derive it).
    Rows are keyed back to the schedule's team names by FotMob team id, so a club FotMob
    spells differently in its stats feed still lines up with the standings. None if absent."""
    path = os.path.join(TEAM_STATS_DIR, f"DISTANCE_{season}.json")
    if not os.path.exists(path):
        return None
    raw = json.load(open(path, encoding="utf-8"))
    by_id = {}
    for f in schedule.get("matches", []):
        by_id[str(f.get("home_id"))] = f["home"]
        by_id[str(f.get("away_id"))] = f["away"]
    rows = [{"team": by_id.get(str(r.get("team_id")), r["team"]), "km": r["km"], "mp": r.get("matches")}
            for r in raw.get("teams", []) if r.get("km") is not None]
    rows.sort(key=lambda r: -r["km"])
    return {"stat": raw.get("stat"), "fetched": (raw.get("fetched_utc") or "")[:10], "teams": rows}


def build_season(season):
    path = os.path.join(SCHED_DIR, f"SCHEDULE_{season}.json")
    if not os.path.exists(path):
        return None
    schedule = json.load(open(path, encoding="utf-8"))
    if not schedule.get("matches"):
        # Empty (e.g. 26/27 before fixtures release) — render a "not started" shell.
        return {"season": season, "status": "not_started", "counts": {},
                "standings": [], "matches": [], "xgRecords": [], "crests": {}, "teams": []}

    if any(not f.get("stage") for f in schedule["matches"]):
        assign_stages(schedule["matches"], season, verbose=False)
    matches, crests, countries = build_matches(season, schedule)
    fmt = format_of(season)
    first = [m for m in matches if m.get("stage") in FIRST_PHASE]
    standings = compute_standings(first)          # league phase table / all group clubs
    groups = None
    if fmt == "groups":
        groups = {}
        for g in sorted({m["group"] for m in first if m.get("group")}):
            groups[g] = compute_standings([m for m in first if m.get("group") == g], h2h=True)
        # overall table keeps each club's group and group position for the views that list clubs
        pos = {r["team"]: (g, r["rank"]) for g, rows in groups.items() for r in rows}
        for r in standings:
            r["group"], r["grank"] = pos.get(r["team"], (None, None))
    rounds = build_ties(matches)
    reach = reach_of([r["team"] for r in standings], rounds)
    fin = (rounds.get("F") or [None])[0]
    champion = fin["winner"] if fin and fin.get("winner") else None
    xg_records = build_xg_records(matches)
    played = [m for m in matches if m["played"]]
    with_xg = [m for m in played if m["xg_home"] is not None]
    mds = [m["matchday"] for m in first if m["matchday"]]
    cur_md = max((m["matchday"] for m in played if m.get("stage") in FIRST_PHASE and m["matchday"]), default=0)
    stage_now = max((m["stage"] for m in played), key=lambda s: KO_ORDER.index(s) + 1 if s in KO_ORDER else 0, default=None)
    return {
        "season": season,
        "format": fmt,
        "groups": groups,
        "rounds": rounds,
        "reach": reach,
        "champion": champion,
        "runnerUp": next((t for t in (fin["a"], fin["b"]) if t != champion), None) if champion else None,
        "stageNow": stage_now,
        "countries": countries,
        "status": "in_progress" if played and len(played) < len(matches) else
                  ("finished" if played else "not_started"),
        "counts": {
            "total": len(matches), "played": len(played), "with_xg": len(with_xg),
            "teams": len(standings), "matchdays": max(mds) if mds else 0,
            "current_matchday": cur_md,
        },
        "standings": standings,
        "matches": matches,
        "xgRecords": xg_records,
        "crests": crests,
        "teams": sorted(r["team"] for r in standings),
        "distance": build_distance(season, schedule),
    }


def _default_season(seasons):
    """Newest season with at least one full matchday played (18 matches: every club of the
    36 has played once); else the newest we have. The floor keeps a season with only a
    handful of results from becoming the default and landing visitors on a near-empty table."""
    played = [s for s in sorted(seasons)
              if (seasons[s].get("counts") or {}).get("played", 0) >= 18]
    return (played or sorted(seasons))[-1]


def main():
    seasons = {}
    for season in ("2022-23", "2023-24", "2024-25", "2025-26", "2026-27"):
        s = build_season(season)
        if s is not None:
            seasons[season] = s
    if not seasons:
        raise SystemExit("No schedules found in " + SCHED_DIR + " — run ucl/build_schedule.py first.")

    payload = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        # Land on the newest season that has a played match — a new season takes over
        # the moment it kicks off, instead of the site sitting on last year forever.
        "defaultSeason": _default_season(seasons),
        "seasons": seasons,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// AUTO-GENERATED by build_data.py — do not edit by hand.\n")
        fh.write("window.LL_DATA = ")
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write(";\n")
    print(f"Wrote {OUT}")
    for season, s in seasons.items():
        c = s.get("counts", {})
        print(f"  {season}: {c.get('played',0)}/{c.get('total',0)} played, "
              f"{c.get('with_xg',0)} with xG, {c.get('teams',0)} teams, status={s['status']}")


if __name__ == "__main__":
    main()
