#!/usr/bin/env python3
"""
One weekly maintenance run: refresh fixtures/results, scrape whatever's newly
finished, rebuild the dashboard, and push — meant to be fired by a recurring
Windows Scheduled Task (see register_weekly_task.ps1) rather than the
per-match tasks in register_tasks.ps1.

Steps (season auto-detected as the newest SCHEDULE_*.json on disk, i.e.
whichever season is currently in progress):
    1. ucl/build_schedule.py --season <season>   (FotMob sweep, no browser)
       + ucl/fetch_team_stats.py --season <season> (FotMob team distance per match)
    2. ucl/backfill.py --season <season>         (WhoScored scrape of any
       newly-finished match + a full dashboard rebuild — see backfill.py)
    3. git add -A && git commit && git push          (only if something changed;
       plain git, NOT git_ops/XWORLDCUPTWIT_REPO — see CLAUDE.md gotchas on why)

Every run appends one line to PROGRESS.md (via log_platform) so a scheduled
run that silently failed doesn't go unnoticed forever.

Usage:
    py ucl/weekly_update.py                  # auto-detect season
    py ucl/weekly_update.py --season 2026-27  # force a season
    py ucl/weekly_update.py --no-push         # rebuild locally, skip git push
"""
from __future__ import annotations

import sys
import time
import argparse
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHED_DIR = REPO_ROOT / "ucl" / "schedules"

sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ucl.progress_log import log_platform  # noqa: E402

PY = sys.executable or "py"


def _newest_season() -> str:
    names = sorted(p.stem.replace("SCHEDULE_", "") for p in SCHED_DIR.glob("SCHEDULE_*.json"))
    if not names:
        raise SystemExit("No SCHEDULE_*.json found under ucl/schedules — nothing to update.")
    return names[-1]


def _run(argv: list[str]) -> int:
    print(f"\n$ {' '.join(argv)}")
    proc = subprocess.run(argv, cwd=REPO_ROOT)
    return proc.returncode


def _git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


# Files this run regenerates. If GitHub changed them too (code pushed from another
# machine or a cloud session rebuilds them), our freshly built copy wins on a merge
# conflict; build_split.py then rewrites the cache hashes in index.html/match.html.
_GENERATED = ("ucl_dashboard/data", "ucl_dashboard/players.js", "ucl_dashboard/shots.js",
              "ucl_dashboard/matches_detail/", "ucl_dashboard/player_lab/",
              "ucl_dashboard/database/", "ucl_dashboard/index.html",
              "ucl_dashboard/match.html", "ucl_png/", "ucl/schedules/", "ucl/team_stats/",
              "PROGRESS.md")


def _sync_and_push() -> tuple[int, str]:
    """Push; if GitHub has commits we don't (rejected "fetch first"), merge them and retry.

    Without this, one commit pushed from anywhere else blocks every scheduled push forever
    (the Team Lab commits pushed to main on 2026-09-23 did exactly that: XLALIGA's runs
    scraped fine but never reached the site until it got this same fix)."""
    rc, out = _git("push")
    if rc == 0:
        return rc, out
    print(f"! push rejected, merging GitHub's commits first:\n{out[:300]}")
    rc, out = _git("pull", "--no-rebase", "--no-edit", "--autostash")
    if rc != 0:
        _, conflicted = _git("diff", "--name-only", "--diff-filter=U")
        files = [f for f in conflicted.splitlines() if f.strip()]
        manual = [f for f in files if not f.startswith(_GENERATED)]
        if not files or manual:
            _git("merge", "--abort")
            return 1, f"merge with origin needs a manual fix ({', '.join(manual) or out[:150]})"
        # Data files: keep the copy this run just built. The two HTML pages are hand-edited
        # too (a design change can land on GitHub mid-run); for those take GitHub's version,
        # since the only thing this run changes in them is the ?v= cache hash, which
        # build_split.py rewrites below. "--ours" there would silently drop the other edits.
        pages = [f for f in files if f in ("ucl_dashboard/index.html", "ucl_dashboard/match.html")]
        data = [f for f in files if f not in pages]
        if data:
            _git("checkout", "--ours", "--", *data)
        if pages:
            _git("checkout", "--theirs", "--", *pages)
        _git("add", "--", *files)
        _run([PY, "ucl_dashboard/build_split.py"])  # re-hash index.html/match.html
        _git("add", "-A")
        rc, out = _git("commit", "--no-edit")
        if rc != 0:
            return rc, f"merge commit failed: {out}"
    return _git("push")


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly Champions League fixtures/results/scrape/push run.")
    ap.add_argument("--season", help="e.g. 2026-27; default = newest schedule on disk")
    ap.add_argument("--no-push", action="store_true", help="Rebuild only, skip git push.")
    args = ap.parse_args()

    season = args.season or _newest_season()
    started = time.time()
    print(f"── Weekly update — season {season} ──")

    rc1 = _run([PY, "ucl/build_schedule.py", "--season", season])
    # FotMob's "Total distance per match" team stat (tracking data the event scrape can't give).
    # Best-effort: a miss keeps the previous file and never fails the weekly run.
    _run([PY, "ucl/fetch_team_stats.py", "--season", season])
    rc2 = _run([PY, "ucl/backfill.py", "--season", season])

    pushed = False
    push_note = ""
    if not args.no_push:
        rc, status = _git("status", "--porcelain")
        if status.strip():
            _git("add", "-A")
            rc, msg = _git("commit", "-m", f"[UCL] weekly update ({season})")
            if rc == 0:
                rc, out = _sync_and_push()
                if rc == 0:
                    pushed = True
                    print("Pushed to GitHub.")
                else:
                    push_note = f"git push failed: {out[:200]}"
                    print(f"! {push_note}")
            else:
                push_note = f"git commit failed: {msg[:200]}"
                print(f"! {push_note}")
        else:
            print("Nothing changed — skipping commit/push.")
    else:
        print("--no-push given — skipping deploy.")

    took = time.time() - started
    ok = rc1 == 0 and rc2 == 0 and not push_note
    summary = (f"Weekly update ({season}): schedule rc={rc1}, backfill rc={rc2}, "
               f"pushed={pushed}" + (f", {push_note}" if push_note else "") +
               f", took {int(took)}s")
    print(f"\n{summary}")
    log_platform(summary)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
