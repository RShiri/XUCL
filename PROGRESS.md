# PROGRESS — XUCL

Running log of the Champions League pipeline: every scrape, every platform change, and the
lessons behind both. Newest entries first in each section. Rows under **Scrape log** are
appended automatically by `ucl/progress_log.py` (called from `run_match.py`,
`scrape_whoscored.py`, `backfill.py` and the dashboard's Scraper button) — write the
Platform and Lessons sections by hand, or with:

```
py ucl/progress_log.py platform "what changed"
py ucl/progress_log.py lesson --worked "what to keep doing"
py ucl/progress_log.py lesson --failed "what not to repeat"
```

## Platform updates & changes

<!-- progress:platform -->

## Lessons — what worked / what didn't

<!-- progress:lessons -->

## Scrape log

<!-- progress:scrapes -->
| When | Season | Trigger | Target | Result | Took | Notes |
|---|---|---|---|---|---|---|
| 2026-10-15 03:30 | 2026-27 | scrape_whoscored.py | fixtures sweep | ✅ 4 saved, 32 already had data | 7m 09s | — |
| 2026-10-15 03:04 | 2026-27 | scrape_whoscored.py | fixtures sweep | ✅ 32 saved | 7m 05s | 4 id(s) not in the schedule |
