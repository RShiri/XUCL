#!/usr/bin/env python3
"""
Harvest Champions League rich match data from WhoScored and map it onto the FotMob schedule.

Why this exists: WhoScored ids are NOT contiguous or chronological, so we can't range-scrape.
Individual `/Matches/<id>/Live` pages DO load reliably (via plain Selenium), but the fixtures
*listing* is flaky and paginated by matchday. So we: (1) harvest match ids from the Premier
League fixtures page, retrying and clicking back through matchdays; (2) scrape each match's
`matchCentreData`; (3) map it to a fixture in `schedules/SCHEDULE_<season>.json` by team names
(ordered, so the right home/away leg) and save it as `matches/<season>/<fotmob_id>.json` via the
shared `build_match_json` — the exact shape the dashboard builders consume. Resumable (skips
matches already saved with events).

Usage:
    py ucl/scrape_whoscored.py --season 2025-26                 # full season
    py ucl/scrape_whoscored.py --season 2025-26 --max-back 20   # navigate more matchdays
    py ucl/scrape_whoscored.py --season 2025-26 --ids 1914252,1914253   # specific ids
"""
from __future__ import annotations

import os, re, sys, json, time, argparse, unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ucl.scraper import build_match_json, _fotmob_unavailable_stub, UCL_WS_BASES
from ucl.progress_log import log_scrape

SCHED_DIR = _REPO / "ucl" / "schedules"
MATCH_DIR = _REPO / "ucl" / "matches"


# WhoScored's matchCentre names are often SHORTER than FotMob's schedule names, and not
# always a substring of them, so plain contains-matching silently drops those fixtures:
# "Man City" ⊄ "manchestercity", "Man Utd" ⊄ "manchesterunited", "Spurs" ⊄ "tottenhamhotspur",
# "Wolves" ⊄ "wolverhamptonwanderers", "Nott'm Forest" → "nottmforest". Map each variant to the
# schedule's canonical key so both sides collapse to the same token. Crucially this keeps the two
# Manchester clubs (and the two Sheffield clubs) on DISTINCT canonicals — never collapse to a bare
# city — the UCL analogue of the two-Madrid rule.
_ALIASES = {
    "mancity": "manchestercity",
    "manutd": "manchesterunited", "manunited": "manchesterunited", "manchesterutd": "manchesterunited",
    "spurs": "tottenhamhotspur", "tottenham": "tottenhamhotspur",
    "wolves": "wolverhamptonwanderers", "wolverhampton": "wolverhamptonwanderers",
    "nottmforest": "nottinghamforest", "nottinghamforest": "nottinghamforest",
    "sheffutd": "sheffieldunited", "sheffieldutd": "sheffieldunited",
    "sheffwed": "sheffieldwednesday", "sheffieldwed": "sheffieldwednesday",
    "westbrom": "westbromwichalbion", "spursfc": "tottenhamhotspur",
    # Champions League: WhoScored short names / spellings vs FotMob's schedule names
    "psg": "parissaintgermain", "parissg": "parissaintgermain",
    "bodoeglimt": "bodoglimt", "fkbodoglimt": "bodoglimt",
    "redstarbelgrade": "crvenazvezda", "redstar": "crvenazvezda",
    "fckobenhavn": "fccopenhagen", "kobenhavn": "fccopenhagen", "copenhagen": "fccopenhagen",
    "olympiakos": "olympiacos", "olympiakospiraeus": "olympiacos",
    "athleticbilbao": "athleticclub",
    "unionstgilloise": "unionsaintgilloise", "usaintgilloise": "unionsaintgilloise",
    "bayern": "bayernmunchen", "bayernmunich": "bayernmunchen",
    "atletico": "atleticomadrid", "atleticodemadrid": "atleticomadrid",
}


def _key(name: str) -> str:
    # Accent-fold + lowercase, strip SAFE club-suffix noise, alnum only, then canonicalise known
    # short/nickname variants (see _ALIASES above). Do NOT strip the DISCRIMINATING tokens
    # "united"/"city" that keep "Manchester United" vs "Manchester City" distinct.
    # ø/æ/ß don't decompose under NFKD and would just vanish ("Bodø" → "bod"); spell them out first
    s = (name or "").translate(str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss"}))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    for j in ("afc ", " afc", " fc", "f.c.", "association football club"):
        s = s.replace(j, " ")
    k = re.sub(r"[^a-z0-9]", "", s)
    return _ALIASES.get(k, k)


def _exact_match(ws_h, ws_a, sc_h, sc_a):
    return _key(ws_h) == _key(sc_h) and _key(ws_a) == _key(sc_a)


def _teams_match(ws_h, ws_a, sc_h, sc_a):
    kh, ka, sh, sa = _key(ws_h), _key(ws_a), _key(sc_h), _key(sc_a)
    def ov(x, y): return x and y and (x == y or x in y or y in x)
    return ov(kh, sh) and ov(ka, sa)


def _ws_date(mcd):
    """Kick-off date (YYYY-MM-DD) from WhoScored's matchCentreData, or None."""
    for k in ("startTime", "startDate", "timeStamp"):
        v = mcd.get(k)
        if isinstance(v, str):
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v) or re.search(r"(\d{2})/(\d{2})/(\d{4})", v)
            if m:
                g = m.groups()
                return f"{g[0]}-{g[1]}-{g[2]}" if len(g[0]) == 4 else f"{g[2]}-{g[1]}-{g[0]}"
    return None


def _fixture_ok(mcd, f, max_days=3):
    """Guard against pairing a WhoScored game with the same two clubs' fixture from ANOTHER
    season (the fixtures page only lists the live season, so a 2026-27 Liverpool v Atletico was
    once saved over 2025-26's). The kick-off dates must agree within a few days, and when the
    schedule already has a final score, WhoScored's must equal it."""
    from datetime import date
    wd, fd = _ws_date(mcd), (f.get("date") or f.get("kickoff_utc") or "")[:10]
    if wd and fd:
        try:
            if abs((date.fromisoformat(wd) - date.fromisoformat(fd)).days) > max_days:
                return False
        except ValueError:
            pass
    if f.get("home_score") is not None and f.get("away_score") is not None:
        want = (int(f["home_score"]), int(f["away_score"]))
        hsc = (mcd.get("home") or {}).get("scores") or {}
        asc = (mcd.get("away") or {}).get("scores") or {}
        # the schedule's score is the 120' one after extra time; WhoScored keeps 90' in "fulltime"
        # ("running" is the final total on some pages; skip anything that isn't a number)
        got = []
        for k in ("fulltime", "extratime", "running"):
            try:
                got.append((int(hsc.get(k)), int(asc.get(k))))
            except (TypeError, ValueError):
                pass
        # top-level strings: "score" (final), "ftScore", "etScore" as "5 : 0"
        for k in ("score", "ftScore", "etScore"):
            m = re.match(r"\s*(\d+)\s*:\s*(\d+)", str(mcd.get(k) or ""))
            if m:
                got.append((int(m.group(1)), int(m.group(2))))
        # after extra time the providers disagree on which score is "the" score; the date
        # check above already pins the game, so don't reject an aet match on score alone
        if got and want not in got and not f.get("aet"):
            return False
    return True


def find_fixture(mcd, schedule):
    """The schedule fixture this WhoScored game is: same teams (exact keys first, so "Real Madrid"
    never grabs an Atletico fixture, then contains-matching) AND the same date/score."""
    wh = (mcd.get("home") or {}).get("name", "")
    wa = (mcd.get("away") or {}).get("name", "")
    for test in (_exact_match, _teams_match):
        for f in schedule:
            if test(wh, wa, f["home"], f["away"]) and _fixture_ok(mcd, f):
                return f
    return None


def load_schedule(season):
    data = json.loads((SCHED_DIR / f"SCHEDULE_{season}.json").read_text(encoding="utf-8"))
    return data.get("matches", [])


def _plain_driver():
    import tempfile
    from selenium import webdriver
    o = webdriver.ChromeOptions()
    if os.environ.get("UCL_VISIBLE") != "1":
        o.add_argument("--headless=new")
    # A fresh --user-data-dir per launch: reusing Chrome's default profile means a run that
    # left orphaned chrome.exe processes behind (crash, killed task, etc.) holds the profile
    # lock, and the NEXT launch fails immediately with "connection refused" on the debugger
    # port — no driver ever actually starts. Isolating the profile makes each run independent.
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1600,1000",
              "--user-data-dir=" + tempfile.mkdtemp(prefix="ucl_chrome_"),
              # Stability + speed on WhoScored's ad/image-heavy pages: no GPU process to crash,
              # no images/extensions/background chatter. matchCentreData is server-rendered into
              # the HTML, so none of this affects what we extract — it just stops headless Chrome
              # from dying every ~minute (the connection-refused deaths that stalled the scrape).
              "--disable-gpu", "--disable-extensions", "--disable-crash-reporter",
              "--disable-background-networking", "--mute-audio",
              "--blink-settings=imagesEnabled=false",
              "--disable-features=Translate,MediaRouter,OptimizationHints",
              "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"):
        o.add_argument(a)
    d = webdriver.Chrome(options=o)
    d.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return d


def make_driver():
    # Plain Selenium (Selenium Manager auto-resolves the driver) is the default here —
    # undetected-chromedriver breaks on Chrome 149. Opt into uc with UCL_USE_UC=1.
    if os.environ.get("UCL_USE_UC") == "1":
        try:
            import undetected_chromedriver as uc
            o = uc.ChromeOptions()
            if os.environ.get("UCL_VISIBLE") != "1":
                o.add_argument("--headless=new")
            for a in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1600,1000"):
                o.add_argument(a)
            return uc.Chrome(options=o)
        except Exception as exc:
            print(f"  (undetected unavailable: {exc}; using plain selenium)")
    return _plain_driver()


_MCD = "matchCentreData:"


def extract_mcd(html):
    i = html.find(_MCD)
    if i < 0:
        return None
    seg = html[i + len(_MCD):].split("matchCentreEventTypeJson")[0].strip().rstrip(",")
    try:
        return json.loads(seg)
    except Exception:
        # brace-match fallback
        depth = 0
        for j, ch in enumerate(seg):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(seg[:j + 1])
                    except Exception:
                        return None
        return None


def season_fixtures_url(driver, season, base=None):
    """WhoScored fixtures URL for `season` ("2025-26"). The season-less tournament page only
    shows the live season, so for an older one pick it in the page's season dropdown
    (option text "2025/2026") and follow that season's Fixtures link. Returns the base URL
    unchanged when the season is the one already selected, None when it can't be found."""
    from selenium.webdriver.common.by import By
    base = base or UCL_WS_BASES[0]
    y1, y2 = season.split("-")
    label = f"{y1}/{int(y1[:2] + y2) if len(y2) == 2 else y2}"
    for attempt in range(4):
        driver.get(base)
        time.sleep(8)
        opts = driver.find_elements(By.CSS_SELECTOR, "select#seasons option, select[name='seasons'] option")
        if not opts:
            continue
        for o in opts:
            if (o.text or "").strip() == label:
                if o.get_attribute("selected"):
                    return base
                href = o.get_attribute("value") or ""
                if not href:
                    return None
                driver.get(href if href.startswith("http") else "https://www.whoscored.com" + href)
                time.sleep(8)
                for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/Fixtures/']"):
                    u = a.get_attribute("href") or ""
                    if "/Seasons/" in u:
                        return u
                return driver.current_url
        print(f"  season {label} not in WhoScored's season list")
        return None
    print("  WhoScored season list never loaded")
    return None


def stage_urls(driver, url):
    """Every stage page of a season (League Phase, Knockout Play-offs, Final Stage, or the
    old group stage). WhoScored's fixtures calendar only pages within ONE stage, so a sweep
    from the season page stops at the start of the knockouts and never reaches the league
    phase. Falls back to [url] when the page has no stage list."""
    from selenium.webdriver.common.by import By
    driver.get(url)
    time.sleep(8)
    out = []
    for o in driver.find_elements(By.CSS_SELECTOR, "select#stages option, select[name='stages'] option"):
        v = o.get_attribute("value") or ""
        if v:
            out.append(v if v.startswith("http") else "https://www.whoscored.com" + v)
    return list(dict.fromkeys(out)) or [url]


def harvest_ids(driver, max_back, want=None, season=None):
    """Collect Champions League match ids from the fixtures page, paging back through matchdays.
    With `season`, start from that season's fixtures page (unless UCL_WHOSCORED_URLS pins one)."""
    from selenium.webdriver.common.by import By
    ids = []
    bases = UCL_WS_BASES
    if season and not os.environ.get("UCL_WHOSCORED_URLS") and not os.environ.get("UCL_WHOSCORED_URL"):
        url = season_fixtures_url(driver, season)
        if not url:
            print(f"  could not open WhoScored's {season} fixtures; pass --url with that season's "
                  f"Fixtures page. Not harvesting the live season instead.")
            return []
        bases = stage_urls(driver, url)
        print(f"  {season} fixtures: {url} ({len(bases)} stage(s))")
    for base in bases:
        got_page = False
        for attempt in range(6):
            driver.get(base)
            time.sleep(9)
            found = re.findall(r"/[Mm]atches/(\d+)/", driver.page_source)
            if found:
                got_page = True
                break
            print(f"  fixtures load attempt {attempt+1} empty, retrying…")
        if not got_page:
            print("  fixtures page never yielded ids on", base)
            continue
        seen = set()
        empty_streak = stuck = 0
        last_label = None
        # The calendar is a WEEKLY view; #dayChangeBtn-prev steps back one week. The UCL
        # plays ~1 round/week, so page back across the whole season (~40+ weeks).
        for step in range(max_back + 1):
            page_ids = list(dict.fromkeys(re.findall(r"/[Mm]atches/(\d+)/", driver.page_source)))
            new = [i for i in page_ids if i not in seen]
            for i in new:
                seen.add(i); ids.append(i)
            label = _cal_label(driver)
            print(f"  week {step} ({label}): +{len(new)} ids (total {len(ids)})")
            empty_streak = empty_streak + 1 if not new else 0
            stuck = stuck + 1 if (label and label == last_label and not new) else 0
            last_label = label
            if empty_streak >= 6:
                print("  6 empty weeks in a row — reached the start of this stage, stopping.")
                break
            if stuck >= 2:
                print("  the calendar stopped moving — start of this stage, stopping.")
                break
            if want and len(ids) >= want:
                break
            clicked = False
            for sel in ["#dayChangeBtn-prev", "button.Calendar-module_dayChangeBtn__sEvC8",
                        "[id='dayChangeBtn-prev']", "a.previous"]:
                try:
                    for e in driver.find_elements(By.CSS_SELECTOR, sel):
                        if e.is_displayed():
                            driver.execute_script("arguments[0].click();", e)
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    continue
            if not clicked:
                print("  previous-week control not found; stopping pagination.")
                break
            time.sleep(5)
    return list(dict.fromkeys(ids))


def _cal_label(driver):
    from selenium.webdriver.common.by import By
    try:
        e = driver.find_elements(By.CSS_SELECTOR, "#toggleCalendar, .Calendar-module_controller__Ke8vm")
        return (e[0].text or "").strip()[:16] if e else ""
    except Exception:
        return ""


def scrape_one(driver, wsid, tries=2):
    for t in range(tries):
        driver.get(f"https://www.whoscored.com/Matches/{wsid}/Live")
        time.sleep(9 + 3 * t)
        mcd = extract_mcd(driver.page_source)
        if mcd and mcd.get("events"):
            return mcd
    return None


def _add_fotmob_player_ids(mj, fid):
    """FotMob player ids for the headshots (build_players matches them by team + surname).
    The events come from WhoScored, but only FotMob has the photos, so fetch its lineup
    once per match. Best-effort: no photo is better than a failed save."""
    if not str(fid).isdigit():
        return
    try:
        from ucl.scraper import fotmob_fetch_match_details, _fotmob_player_ids
        fm = fotmob_fetch_match_details(int(fid))
        ids = [] if fm.get("_fotmob_unavailable") else _fotmob_player_ids(fm)
        if ids:
            mj["_fotmob_player_ids"] = ids
    except Exception as e:
        print(f"  (no FotMob player ids for {fid}: {str(e)[:60]})")


def save_match(mcd, fixture, season):
    fid = fixture["fotmob_id"]
    ws_h = (mcd.get("home") or {}).get("name", "")
    ws_a = (mcd.get("away") or {}).get("name", "")
    hs = (mcd.get("home") or {}).get("scores", {}).get("fulltime")
    as_ = (mcd.get("away") or {}).get("scores", {}).get("fulltime")
    score = f"{hs} - {as_}" if hs is not None and as_ is not None else "0 - 0"
    xml_stub = {"id": fid, "home": {"name": fixture["home"], "id": fixture.get("home_id")},
                "away": {"name": fixture["away"], "id": fixture.get("away_id")},
                "status": {"scoreStr": score, "utcTime": (fixture.get("kickoff_utc") or ""), "finished": True}}
    mj = build_match_json(_fotmob_unavailable_stub(), mcd, xml_match=xml_stub)
    _add_fotmob_player_ids(mj, fid)
    meta = mj.setdefault("meta", {})
    meta["season"] = season
    meta["competition"] = "Champions League"
    if fixture.get("matchday"):
        meta["matchday"] = fixture["matchday"]
    out = MATCH_DIR / season / f"{fid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mj, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def already_done(season, fid):
    p = MATCH_DIR / season / f"{fid}.json"
    if not p.exists():
        return False
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("events"))
    except Exception:
        return False


def _newest_season() -> str:
    """Default season for the CLI: the newest SCHEDULE_*.json on disk."""
    try:
        names = sorted(p.stem.replace("SCHEDULE_", "") for p in SCHED_DIR.glob("SCHEDULE_*.json"))
        return names[-1] if names else "2025-26"
    except Exception:
        return "2025-26"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=_newest_season())
    ap.add_argument("--ids", help="comma-separated WhoScored ids (skip fixtures harvest)")
    ap.add_argument("--url", help="WhoScored Fixtures page for the season (default: found from the season list)")
    ap.add_argument("--max-back", type=int, default=40, help="matchday pages to navigate back")
    ap.add_argument("--limit", type=int, help="stop after saving N matches")
    args = ap.parse_args()
    if args.url:
        global UCL_WS_BASES
        os.environ["UCL_WHOSCORED_URLS"] = args.url
        UCL_WS_BASES = [args.url]

    schedule = load_schedule(args.season)
    print(f"Season {args.season}: {len(schedule)} fixtures in schedule.")
    started = time.time()
    driver = make_driver()
    saved = skipped = unmatched = failed = 0
    try:
        if args.ids:
            ids = [x.strip() for x in args.ids.split(",") if x.strip()]
        else:
            print("Harvesting match ids from WhoScored fixtures…")
            ids = harvest_ids(driver, args.max_back, season=args.season)
        print(f"Got {len(ids)} candidate WhoScored ids. Scraping…")
        for n, wsid in enumerate(ids, 1):
            mcd = scrape_one(driver, wsid)
            if not mcd:
                failed += 1
                print(f"[{n}/{len(ids)}] {wsid}: no data")
                continue
            wh = (mcd.get("home") or {}).get("name", "")
            wa = (mcd.get("away") or {}).get("name", "")
            fixture = find_fixture(mcd, schedule)
            if not fixture:
                unmatched += 1
                print(f"[{n}/{len(ids)}] {wsid}: {wh} vs {wa} ({_ws_date(mcd)}) — not in {args.season} schedule, skip")
                continue
            if already_done(args.season, fixture["fotmob_id"]):
                skipped += 1
                continue
            out = save_match(mcd, fixture, args.season)
            saved += 1
            print(f"[{n}/{len(ids)}] {wsid}: {wh} {(mcd.get('home') or {}).get('scores',{}).get('fulltime')}-"
                  f"{(mcd.get('away') or {}).get('scores',{}).get('fulltime')} {wa} -> {out.name} (MD{fixture.get('matchday')})")
            if args.limit and saved >= args.limit:
                break
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    print(f"\nDone: {saved} saved, {skipped} already had data, {unmatched} unmatched, {failed} failed.")
    # Journal the run so PROGRESS.md always reflects what was actually scraped.
    log_scrape(
        season=args.season,
        target=(f"WhoScored ids {args.ids}" if args.ids else "fixtures sweep"),
        saved=saved, failed=failed, skipped=skipped,
        duration_s=time.time() - started, trigger="scrape_whoscored.py",
        note=(f"{unmatched} id(s) not in the schedule" if unmatched else ""),
    )


if __name__ == "__main__":
    main()
