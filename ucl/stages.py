"""Champions League stage logic shared by the schedule builders and the dashboard builder.

The Premier League forks get away with one shape: 20 clubs, 38 matchdays, one table. The
Champions League changed shape in the middle of our window:

    2022-23, 2023-24   32 clubs, 8 groups of 4, 6 matchdays; top two to the round of 16.
    2024-25 onward     36 clubs, one league phase table, 8 matchdays; 1-8 to the round of 16,
                       9-24 to a two-legged knockout playoff, 25-36 out.

Every fixture in ``ucl/schedules/SCHEDULE_<season>.json`` therefore carries a ``stage``:
``group`` / ``league`` for the first phase (with ``matchday`` 1-6 / 1-8, and ``group`` A-H in
the old format), then ``PO`` (new format only), ``R16``, ``QF``, ``SF``, ``F`` for the knockouts
(with ``leg`` 1/2 for two-legged ties).

FotMob does not label these consistently across seasons, so ``assign_stages`` derives them
from the fixtures themselves rather than from feed labels:
  * first phase vs knockouts by date (the first phase always ends before the knockouts start),
  * the old-format groups as the connected components of who played whom, lettered by one
    known club per group (``GROUP_SEEDS``),
  * knockout rounds by slicing the knockout fixtures in date order by the size of each round
    (16 / 16 / 8 / 4 / 1 matches), which works because each round finishes before the next.
Fields a source already set (the openfootball importer sets them all) are kept.
"""
from __future__ import annotations

import re
import unicodedata

SEASONS = ("2022-23", "2023-24", "2024-25", "2025-26", "2026-27")


def format_of(season: str) -> str:
    """'groups' (32 clubs, 8x4) up to 2023-24, 'league' (36-club league phase) after."""
    return "groups" if season < "2024-25" else "league"


# Last day a first-phase match can be played. Old format: group stage over by mid-December.
# New format: league phase ends in the last week of January; the playoff starts in February.
FIRST_PHASE_END = {
    "2022-23": "2022-12-31", "2023-24": "2023-12-31",
    "2024-25": "2025-01-31", "2025-26": "2026-01-31", "2026-27": "2027-01-31",
}
KO_ROUNDS = {
    "groups": [("R16", 16), ("QF", 8), ("SF", 4), ("F", 1)],
    "league": [("PO", 16), ("R16", 16), ("QF", 8), ("SF", 4), ("F", 1)],
}
STAGE_ORDER = {"group": 0, "league": 0, "PO": 1, "R16": 2, "QF": 3, "SF": 4, "F": 5}
FIRST_PHASE = ("group", "league")

# One club per group pins UEFA's letter (folded-name keywords, so FotMob's and openfootball's
# spellings both match: "FC Bayern München" / "Bayern Munich" both contain "bayern").
GROUP_SEEDS = {
    "2022-23": {"napoli": "A", "porto": "B", "bayern": "C", "tottenham": "D",
                "chelsea": "E", "real madrid": "F", "manchester city": "G", "benfica": "H"},
    "2023-24": {"bayern": "A", "arsenal": "B", "real madrid": "C", "real sociedad": "D",
                "atletico": "E", "dortmund": "F", "manchester city": "G", "barcelona": "H"},
}


def fold(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def is_first_phase(rec: dict) -> bool:
    return rec.get("stage") in FIRST_PHASE


def _components(recs):
    adj: dict[str, set] = {}
    for r in recs:
        adj.setdefault(r["home"], set()).add(r["away"])
        adj.setdefault(r["away"], set()).add(r["home"])
    seen, comps = set(), []
    for t in adj:
        if t in seen:
            continue
        stack, comp = [t], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj[x] - seen)
        comps.append(comp)
    return comps


def _assign_groups(first: list, season: str, verbose: bool) -> None:
    if all(r.get("group") for r in first):
        return
    comps = _components(first)
    seeds = GROUP_SEEDS.get(season, {})
    letters, spare = {}, iter("ABCDEFGH")
    for comp in comps:
        hit = sorted({g for t in comp for k, g in seeds.items() if k in fold(t)})
        letter = hit[0] if len(hit) == 1 else None
        if letter is None:
            letter = next(spare)
            if verbose:
                print(f"  ! no single seed club for group {sorted(comp)}; lettered {letter} by order")
        for t in comp:
            letters[t] = letter
    if verbose and len(comps) != 8:
        print(f"  ! expected 8 groups, found {len(comps)} (fixture list incomplete?)")
    for r in first:
        r.setdefault("group", None)
        if not r["group"]:
            r["group"] = letters.get(r["home"])


def _pack_matchdays(first: list, verbose: bool) -> None:
    """Earliest-fit packing in date order: each fixture drops into the earliest round with a
    free slot and neither club already in it (same method as the league forks)."""
    if all(r.get("matchday") for r in first):
        return
    teams = {t for r in first for t in (r["home"], r["away"])}
    per_round = max(len(teams) // 2, 1)
    ordered = sorted(first, key=lambda r: (r.get("date") or "9999", r.get("kickoff_utc") or "", str(r.get("fotmob_id"))))
    rounds: list = []
    for r in ordered:
        for rd in rounds:
            if len(rd["m"]) < per_round and r["home"] not in rd["t"] and r["away"] not in rd["t"]:
                rd["m"].append(r)
                rd["t"].update((r["home"], r["away"]))
                break
        else:
            rounds.append({"m": [r], "t": {r["home"], r["away"]}})
    rounds.sort(key=lambda rd: min(m.get("date") or "9999" for m in rd["m"]))
    for n, rd in enumerate(rounds, 1):
        for m in rd["m"]:
            if not m.get("matchday"):
                m["matchday"] = n
    if verbose:
        print(f"  first-phase matchdays rebuilt by date: {len(rounds)} rounds of up to {per_round}")


def _assign_ko(ko: list, fmt: str, verbose: bool) -> None:
    todo = sorted((r for r in ko if not r.get("stage")),
                  key=lambda r: (r.get("date") or "9999", r.get("kickoff_utc") or "", str(r.get("fotmob_id"))))
    if todo:
        done = {}
        for r in ko:
            if r.get("stage"):
                done[r["stage"]] = done.get(r["stage"], 0) + 1
        i = 0
        for stage, n in KO_ROUNDS[fmt]:
            take = n - done.get(stage, 0)
            for r in todo[i:i + max(take, 0)]:
                r["stage"] = stage
            i += max(take, 0)
        if i < len(todo) and verbose:
            print(f"  ! {len(todo) - i} knockout fixture(s) beyond the final; left unlabelled")
    # legs, by date within each tie
    ties: dict = {}
    for r in ko:
        if r.get("stage") and r["stage"] != "F":
            ties.setdefault((r["stage"], frozenset((r["home"], r["away"]))), []).append(r)
    for legs in ties.values():
        legs.sort(key=lambda r: r.get("date") or "9999")
        for n, r in enumerate(legs, 1):
            r.setdefault("leg", n)
    for r in ko:
        r["matchday"] = None


def assign_stages(records: list, season: str, verbose: bool = True) -> list:
    """Fill stage / group / matchday / leg on a season's fixtures (in place; returns them)."""
    fmt = format_of(season)
    cut = FIRST_PHASE_END.get(season, f"{int(season[:4]) + 1}-01-31")
    first_label = "group" if fmt == "groups" else "league"
    for r in records:
        if r.get("stage"):
            continue
        r["stage"] = first_label if (r.get("date") or "9999") <= cut else None
    first = [r for r in records if r.get("stage") in FIRST_PHASE]
    ko = [r for r in records if r.get("stage") not in FIRST_PHASE]
    _pack_matchdays(first, verbose)
    if fmt == "groups":
        _assign_groups(first, season, verbose)
    _assign_ko(ko, fmt, verbose)
    return records
