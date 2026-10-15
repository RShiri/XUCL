#!/usr/bin/env python3
"""Seed ``ucl/schedules/SCHEDULE_<season>.json`` from openfootball when FotMob is out of reach.

``build_schedule.py`` (FotMob league 42) is the real spine, exactly like XEPL/XLALIGA, but FotMob
is blocked from sandboxed/cloud sessions. This importer writes the same schedule shape from the
public-domain openfootball/champions-league files kept in ``ucl/openfootball/``:

    cl_<season>.txt   football.txt format, complete seasons (openfootball, CC0)
    cl_<season>.csv   hand-kept results for a season openfootball has not published yet
                      (date,phase,md,home,home_cc,away,away_cc,hg,ag; blank score = not played)

Records get a synthetic ``fotmob_id`` (``of-<season>-NNN``) and ``"source": "openfootball"``.
They carry no FotMob team ids, so no crest/rich layer joins onto them. As soon as
``build_schedule.py --season <s> --full`` runs on a machine with network access it replaces the
file with real FotMob ids, and the WhoScored scrape can then layer xG/shots/players on top.

Usage:
    py ucl/import_openfootball.py                 # every season with a source file
    py ucl/import_openfootball.py --season 2026-27
    py ucl/import_openfootball.py --force         # also overwrite a FotMob-built schedule
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
from ucl.stages import SEASONS, assign_stages, format_of  # noqa: E402

SRC = _HERE / "openfootball"
SCHED_DIR = _HERE / "schedules"

# openfootball spells clubs in full ("FC Internazionale Milano") and changed spelling between
# seasons ("Atlético Madrid" vs "Club Atlético de Madrid"). Map to FotMob's spelling where known,
# so a later FotMob build keeps the same club names.
ALIAS = {
    "1. FC Union Berlin": "Union Berlin", "AC Sparta Praha": "Sparta Prague", "AFC Ajax": "Ajax",
    "AS Monaco FC": "Monaco", "Arsenal FC": "Arsenal", "Aston Villa FC": "Aston Villa", "Atalanta BC": "Atalanta",
    "Club Atlético de Madrid": "Atlético Madrid", "Atletico Madrid": "Atlético Madrid",
    "BSC Young Boys": "Young Boys", "Bayer 04 Leverkusen": "Bayer Leverkusen",
    "FC Bayern München": "Bayern München", "Bologna FC 1909": "Bologna", "Celtic FC": "Celtic",
    "Chelsea FC": "Chelsea", "Club Brugge KV": "Club Brugge", "GNK Dinamo Zagreb": "Dinamo Zagreb",
    "FC Barcelona": "Barcelona", "FC Internazionale Milano": "Inter", "FC Porto": "FC Porto", "Porto": "FC Porto", "PSV": "PSV Eindhoven", "PSV Eindhoven": "PSV Eindhoven",
    "FC Red Bull Salzburg": "RB Salzburg", "FK Bodø/Glimt": "Bodø/Glimt", "FK Crvena Zvezda": "Crvena Zvezda",
    "FK Kairat": "Kairat Almaty", "FK Shakhtar Donetsk": "Shakhtar Donetsk", "Feyenoord Rotterdam": "Feyenoord",
    "Galatasaray SK": "Galatasaray", "Girona FC": "Girona", "Juventus FC": "Juventus", "Lille OSC": "Lille",
    "Liverpool FC": "Liverpool", "Manchester City FC": "Manchester City", "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United", "Olympique Marseille": "Marseille", "Olympique de Marseille": "Marseille",
    "PAE Olympiakos SFP": "Olympiacos", "Paphos FC": "Pafos FC", "Paris Saint-Germain FC": "Paris Saint-Germain",
    "Qarabağ Ağdam FK": "Qarabag FK", "Racing Club de Lens": "Lens", "Rangers FC": "Rangers",
    "Real Madrid CF": "Real Madrid", "Real Sociedad de Fútbol": "Real Sociedad", "Royal Antwerp FC": "Antwerp",
    "Royale Union Saint-Gilloise": "Union Saint-Gilloise", "SK Slavia Praha": "Slavia Prague", "SK Sturm Graz": "Sturm Graz",
    "SL Benfica": "Benfica", "Sport Lisboa e Benfica": "Benfica", "SS Lazio": "Lazio", "SSC Napoli": "Napoli",
    "Sevilla FC": "Sevilla", "Sporting Clube de Portugal": "Sporting CP", "Sporting Clube de Braga": "Braga",
    "Stade Brestois 29": "Brest", "Tottenham Hotspur": "Tottenham Hotspur", "Tottenham Hotspur FC": "Tottenham Hotspur",
    "Villarreal CF": "Villarreal", "ŠK Slovan Bratislava": "Slovan Bratislava", "Viktoria Plzeň": "Viktoria Plzen",
    "FC København": "FC Copenhagen", "Borussia Dortmund": "Borussia Dortmund", "VfB Stuttgart": "VfB Stuttgart",
    "Eintracht Frankfurt": "Eintracht Frankfurt", "Athletic Club": "Athletic Club", "Inter": "Inter",
    "Juventus": "Juventus", "Manchester City": "Manchester City", "Paris Saint-Germain": "Paris Saint-Germain",
    "Real Madrid": "Real Madrid", "RB Salzburg": "RB Salzburg", "Bayer Leverkusen": "Bayer Leverkusen",
    # hand-kept CSV spellings
    "Slavia Praha": "Slavia Prague", "AEK Athens": "AEK Athens", "LASK": "LASK", "Sabah": "Sabah FK",
}

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
DATE_RE = re.compile(r"^\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3}) (\d{1,2})(?: (\d{4}))?\s*$")
MATCH_RE = re.compile(r"^\s+(?:(\d\d:\d\d)\s+)?(.+?) \(([A-Z]{3})\)\s+v\s+(.+?) \(([A-Z]{3})\)\s+(.+?)\s*$")
KO = {"round of 16": "R16", "quarterfinals": "QF", "semifinals": "SF", "final": "F"}


def club(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return ALIAS.get(name, name)


def _score(s: str) -> dict:
    """'2-1 (1-1)' | '0-0' | '3-2 a.e.t. (3-0, 1-0)' | '4-3 pen. 1-1 a.e.t. (1-1, 0-1)'."""
    m = re.match(r"(\d+)-(\d+) pen\. (\d+)-(\d+) a\.e\.t\.", s)
    if m:
        return {"home_score": int(m[3]), "away_score": int(m[4]), "aet": True, "pens": [int(m[1]), int(m[2])]}
    m = re.match(r"(\d+)-(\d+)( a\.e\.t\.)?", s)
    if not m:
        raise ValueError(f"unreadable score {s!r}")
    return {"home_score": int(m[1]), "away_score": int(m[2]), "aet": bool(m[3]), "pens": None}


def _section(header: str, fmt: str):
    h = header.lower()
    g = re.match(r"(?:group|gruppe) ([a-h])$", h)
    if g:
        return {"stage": "group", "group": g[1].upper()}
    md = re.search(r"matchday (\d+)", h)
    if h.startswith(("group", "league")):
        return {"stage": "group" if fmt == "groups" else "league", "matchday": int(md[1]) if md else None}
    if h.startswith("playoffs"):
        return {"stage": "PO"}
    ko = KO.get(h.replace("finals, ", "", 1) if h != "final" else h)
    if ko:
        return {"stage": ko}
    raise ValueError(f"unknown section {header!r}")


def _rec(season: str, n: int, day: str, kickoff: str, home: str, away: str, hcc: str, acc: str, **kw) -> dict:
    played = kw.get("home_score") is not None
    rec = {
        "fotmob_id": f"of-{season}-{n:03d}", "matchday": None, "date": day,
        "kickoff_utc": kickoff, "home": home, "away": away, "home_id": None, "away_id": None,
        "home_country": hcc, "away_country": acc,
        "home_score": None, "away_score": None, "status": "F" if played else "N", "finished": played,
        "source": "openfootball",
    }
    rec.update({k: v for k, v in kw.items() if v is not None or k in ("home_score", "away_score")})
    return rec


def parse_txt(path: Path, season: str) -> list:
    fmt, start_year = format_of(season), int(season[:4])
    out, ctx, cur = [], {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("▪"):
            ctx = _section(line[1:].strip(), fmt)
            continue
        d = DATE_RE.match(line)
        if d:
            mon, day = MONTHS[d[1]], int(d[2])
            cur = date(int(d[3]) if d[3] else (start_year if mon >= 7 else start_year + 1), mon, day)
            continue
        m = MATCH_RE.match(line)
        if not m:
            continue
        # openfootball times are CET/CEST local; keep the date, leave the UTC kickoff blank
        out.append(_rec(season, len(out) + 1, cur.isoformat(), "", club(m[2]), club(m[4]), m[3], m[5],
                        **ctx, **_score(m[6])))
    return out


def parse_csv(path: Path, season: str) -> list:
    out = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sc = {}
            if r["hg"].strip():
                sc = {"home_score": int(r["hg"]), "away_score": int(r["ag"]), "aet": False, "pens": None}
            stage = r["phase"] if r["phase"] not in ("first", "") else ("group" if format_of(season) == "groups" else "league")
            out.append(_rec(season, len(out) + 1, r["date"], "", club(r["home"]), club(r["away"]),
                            r["home_cc"], r["away_cc"], stage=stage, matchday=int(r["md"]) if r["md"] else None, **sc))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed UCL schedules from openfootball (no FotMob needed).")
    ap.add_argument("--season", help="one season, e.g. 2026-27 (default: all with a source file)")
    ap.add_argument("--force", action="store_true", help="overwrite a schedule that FotMob built")
    args = ap.parse_args()
    SCHED_DIR.mkdir(parents=True, exist_ok=True)
    for season in ([args.season] if args.season else SEASONS):
        txt, csvp = SRC / f"cl_{season}.txt", SRC / f"cl_{season}.csv"
        if txt.exists():
            recs = parse_txt(txt, season)
        elif csvp.exists():
            recs = parse_csv(csvp, season)
        else:
            print(f"{season}: no openfootball file, skipped")
            continue
        out = SCHED_DIR / f"SCHEDULE_{season}.json"
        if out.exists() and not args.force:
            try:
                old = json.loads(out.read_text(encoding="utf-8")).get("matches") or []
            except Exception:
                old = []
            if any(m.get("source") != "openfootball" for m in old):
                print(f"{season}: {out.name} was built from FotMob; left alone (use --force to replace)")
                continue
        assign_stages(recs, season, verbose=True)
        payload = {"season": season, "competition": "Champions League", "fotmob_league_id": "42",
                   "format": format_of(season), "source": "openfootball",
                   "generated_utc": datetime.now(timezone.utc).isoformat(), "matches": recs}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        played = sum(1 for r in recs if r["finished"])
        print(f"{season}: {played}/{len(recs)} played → {out.relative_to(_HERE.parent)}")


if __name__ == "__main__":
    main()
