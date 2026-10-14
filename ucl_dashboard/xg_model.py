"""Shot extraction + xG/xA scoring, routed through the shared models.

xG: the v3 artifact in <repo root>/xg_core_v3 (23 features — the base-14 geometry plus
9 shot-/assist-context extras; LR + monotone-GBM + market blend, isotonic map; trained
on La Liga + EPL 4 seasons each + the World Cup). FIVE of the extras come from the
shot's ASSISTING PASS, so xG must be scored with the whole match's events in hand: call
match_xg_map(match_data) ONCE per match, then look each shot's xG up via
shot_xg(ev, xg_by_event). There is deliberately no per-shot scalar path in this module —
scoring a shot in isolation would silently zero the 9 extras and return degraded xG.

xA: unchanged code — the pass-level xA artifact in <repo root>/xg_core (P(pass becomes
an assist), two-stage + isotonic). Only the trained file improved, so it is a drop-in.

Scoring is pure python (stdlib); if lightgbm is installed the scorers silently upgrade
to the full blends — both paths are calibrated. renderer.build_shot_df routes xG through
the same v3 scorer, so the site and the PNGs still agree. Retrain xG with the XG V3
trainer; xA with xg_core/train_xa.py.
"""
import math
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xg_core_v3.score import XGScorer   # v3: 23-feature, event-based (needs the whole match)
from xg_core.xa_score import XAScorer   # xA unchanged (new artifact is a drop-in)
from xgot_core.score import XGOTScorer  # placement-based xGOT (on-target shots only)

_LEAGUE = "EPL"           # per-league calibration shift inside the artifacts
_XG = XGScorer()          # loads xg_core_v3/xg_artifact.json
_XA = XAScorer()
_XGOT = XGOTScorer()

SCALE_Y = 0.80
SHOT_TYPES = {"MissedShots", "SavedShot", "ShotOnPost", "BlockedShot", "Goal"}


def _shot_angle(x_sb, y_sb):
    """Angle (radians) the goal mouth subtends from the shot location; posts at
    (120, 36) and (120, 44) in StatsBomb coords. Bigger angle = better chance."""
    a = math.hypot(120.0 - x_sb, 36.0 - y_sb)
    b = math.hypot(120.0 - x_sb, 44.0 - y_sb)
    if a <= 0.0 or b <= 0.0:
        return math.pi
    c = max(-1.0, min(1.0, (a * a + b * b - 64.0) / (2.0 * a * b)))
    return math.acos(c)


def is_shootout(ev):
    """True for penalty-SHOOTOUT events (WhoScored period 5 / "PenaltyShootout").

    A shootout decides a drawn knockout tie but its kicks are NOT match shots: they
    must be excluded from xG, shot counts, shot maps, the goals timeline and player
    stats, or a 1-1 tie balloons to ~6 xG and ~9 "goals". The match score stays the
    post-extra-time result; the shootout is reported separately as a penalty score.
    Extra-time shots (periods 3/4) ARE real and stay in."""
    p = ev.get("period", {})
    if isinstance(p, dict):
        return p.get("value") == 5 or "Shoot" in (p.get("displayName") or "")
    return "Shoot" in str(p or "")


def ws_to_sb_x(ws_x):
    if ws_x <= 50:
        return ws_x * (60.0 / 50.0)
    elif ws_x <= 89:
        return 60.0 + (ws_x - 50) * (48.0 / 39.0)
    else:
        return 108.0 + (ws_x - 89) * (12.0 / 11.0)


def match_xg_map(match_data):
    """id(event) -> calibrated v3 xG for every real shot in this match.

    Score the whole match at once — the v3 model reads each shot's assisting pass, so xG
    cannot be computed from isolated coordinates — then look each shot up by id(ev) via
    shot_xg(ev, xg_by_event). Penalties get the artifact's flat constant; own goals and
    penalty-shootout kicks are excluded (absent from the map).

    Delegates to XGScorer.match_xg_by_id, which keys the map by object identity, NOT
    WhoScored eventId: eventIds are unique only within a possession chain and DO collide
    within a match (~15% of EPL matches have two shots sharing one), so an eventId-keyed
    dict would hand colliding shots each other's xG. Every caller builds this map and
    iterates shots from the SAME match_data, so the id(ev) identities line up."""
    return _XG.match_xg_by_id(match_data, league=_LEAGUE)


def match_xgot_by_event(match_data):
    """id(event) -> calibrated xGOT for every on-target shot (Goal/SavedShot,
    non-penalty) in the match. Same id(event)-not-eventId reasoning as
    match_xg_map (eventId collides across ~15% of matches) — xgot_core needs the
    assisting pass in hand too. Off-target shots and penalties are absent from
    the map (xGOT isn't defined for them); look up with .get(id(ev))."""
    evs = match_data.get("events", [])
    byid = {e.get("eventId"): e for e in evs}
    prev_pass = None
    out = {}
    for ev in evs:
        t = ev.get("type", {})
        dn = t.get("displayName") if isinstance(t, dict) else None
        if dn == "Pass":
            prev_pass = ev
        xgot = _XGOT.xgot_from_shot_event(ev, byid, prev_pass, league=_LEAGUE)
        if xgot is not None:
            out[id(ev)] = xgot
    return out


def ascii_name(name):
    return unicodedata.normalize("NFKD", name or "").encode("ASCII", "ignore").decode("ASCII").strip()


def player_full_name(match_data, player_id):
    for side in ("home", "away"):
        for p in match_data.get(side, {}).get("players", []):
            if p.get("playerId") == player_id:
                return ascii_name(p.get("name", str(player_id)))
    return str(player_id) if player_id is not None else "—"


def extract_qualifiers(ev):
    qual_list = ev.get("qualifiers", [])
    quals = {q.get("type", {}).get("displayName", "") for q in qual_list}
    body = ("Right Foot" if "RightFoot" in quals else
            "Left Foot" if "LeftFoot" in quals else
            "Header" if "Head" in quals else "Unknown")
    situation = ("Penalty" if "Penalty" in quals else
                 "Free Kick" if "DirectFreekick" in quals else
                 "Fast Break" if "FastBreak" in quals else
                 "Set Piece" if "SetPiece" in quals else
                 "Corner" if "FromCorner" in quals else "Open Play")
    if any(z in quals for z in ("SmallBoxCentre", "SmallBoxLeft", "SmallBoxRight",
                                "DeepBoxCentre", "DeepBoxLeft", "DeepBoxRight")):
        zone = "6-Yard Box"
    elif any(z in quals for z in ("BoxCentre", "BoxLeft", "BoxRight")):
        zone = "Inside Box"
    elif any(z in quals for z in ("OutOfBoxCentre", "OutOfBoxLeft", "OutOfBoxRight")):
        zone = "Outside Box"
    else:
        zone = "Unknown"
    big_chance = "BigChance" in quals
    return body, situation, zone, big_chance, quals


def shot_xg(ev, xg_by_event):
    """Return (xg, meta) for a single shot event.

    xg_by_event MUST be match_xg_map(match_data) for THIS shot's match — v3 xG needs the
    whole-match context; there is no correct per-shot scalar path. `ev` must be the same
    event object the map was built from (lookup is by id(ev)). Events absent from the map
    (own goals, shootout kicks) score 0.0. `meta` (body/situation/zone/big_chance/penalty)
    is unchanged and still drives the shot maps and tooltips."""
    body, situation, zone, big_chance, quals = extract_qualifiers(ev)
    xg = xg_by_event.get(id(ev), 0.0)
    return xg, dict(body=body, situation=situation, zone=zone,
                    big_chance=big_chance, penalty=situation == "Penalty")


def player_xa_from_events(match_data):
    """playerId -> summed xA (expected assists), from the pass-level xA model.

    xA(pass) = calibrated P(this successful pass becomes a goal assist), summed
    over every successful pass a player attempts — so a killer ball the striker
    wastes still earns credit, and no shot is required. Sums are calibrated so
    league-wide xA == actual assists. (The old version credited the passer with
    the xG of the shot that followed, which required a shot and ran ~11% hot.)"""
    return _XA.player_xa_from_events(match_data, league=_LEAGUE)


def team_ppda_from_events(match_data):
    """PPDA (passes allowed per defensive action) per side: the opponent's completed
    passes in YOUR defensive two-thirds, divided by your own tackles + interceptions
    + fouls-committed in that same zone. Lower = more intense pressing. Standard
    definition, direct arithmetic (no model).

    WhoScored's x/y are stored per-event in the ACTING team's own attacking
    direction (x=100 = that team's own attacking goal), so a fixed physical zone
    maps to opposite x-ranges depending on whose event it is: "team T's defensive
    two-thirds" is x<=66.67 in T's own events, but x>=33.33 in the opponent's
    events (they're facing the opposite way on the same pitch).

    Returns (home_ppda, away_ppda); either is None if that side recorded zero
    defensive actions in its own defensive two-thirds (nothing to divide by)."""
    events = match_data.get("events") or []
    home_id = match_data.get("home", {}).get("teamId")
    away_id = match_data.get("away", {}).get("teamId")
    DEF_ACTIONS = {"Tackle", "Interception"}

    def _t(e):
        return e.get("type", {}).get("displayName", "")

    def _o(e):
        return e.get("outcomeType", {}).get("displayName", "")

    def defensive_actions(tid):
        n = 0
        for e in events:
            if e.get("teamId") != tid or is_shootout(e):
                continue
            tn = _t(e)
            in_own_defensive_zone = (e.get("x", 0) or 0) <= 66.67
            if tn in DEF_ACTIONS and in_own_defensive_zone:
                n += 1
            elif tn == "Foul" and _o(e) == "Unsuccessful" and in_own_defensive_zone:
                n += 1  # fouls COMMITTED (see scraper.py's _compute_ws_stats)
        return n

    def opponent_passes(opp_tid):
        return sum(1 for e in events
                   if e.get("teamId") == opp_tid and not is_shootout(e)
                   and _t(e) == "Pass" and _o(e) == "Successful"
                   and (e.get("x", 0) or 0) >= 33.33)

    def ppda(tid, opp_tid):
        da = defensive_actions(tid)
        return round(opponent_passes(opp_tid) / da, 2) if da else None

    return ppda(home_id, away_id), ppda(away_id, home_id)


def team_xg_from_events(match_data):
    """Sum shot xG per side from WhoScored events. Returns (home_xg, away_xg) or
    (None, None) when there are no shot events to work with."""
    events = match_data.get("events") or []
    home_id = match_data.get("home", {}).get("teamId")
    away_id = match_data.get("away", {}).get("teamId")
    xg_by_event = match_xg_map(match_data)
    totals = {home_id: 0.0, away_id: 0.0}
    n = 0
    for ev in events:
        tname = ev.get("type", {})
        if not isinstance(tname, dict) or tname.get("displayName") not in SHOT_TYPES:
            continue
        if is_shootout(ev):
            continue  # penalty-shootout kicks are not match shots
        tid = ev.get("teamId")
        if tid not in totals:
            continue
        xg, _ = shot_xg(ev, xg_by_event)
        totals[tid] += xg
        n += 1
    if n == 0:
        return None, None
    return round(totals[home_id], 2), round(totals[away_id], 2)
