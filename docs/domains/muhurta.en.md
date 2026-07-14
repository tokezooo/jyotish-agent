# Muhurta focused-work v1 — operational contract

Use the read-only `muhurta` tool with `general` or `focused_work_session_v1`, a regional IANA
place, strict aware start/exclusive end, 15–480 minute duration, explicit hard constraints, and
optional preferences. Omitted end means seven local civil days. No booking or calendar write occurs.

## Confidence matrix

| Input | Behavior |
|---|---|
| exact event range | Boundary-driven signed search. |
| approximate preference | Express as preferences; it never changes the exact search anchor. |
| unknown end | Deterministic seven-civil-day default, maximum range 31 days. |

Included: sunrise/sunset, tithi, nakshatra, yoga, karana, lagna and named daily boundary facts;
half-open partitioning; user-defined daylight/time/weekday exclusions; calendar-ready candidates
and near misses. Marriage, medical, contract recommendations, planetary-change requests,
doctrinal eligibility/soft ranking, tara-bala and candra-bala are omitted.

## Current state, limits, and errors

Boundary facts and explicit constraint filtering are available. Ranking and interpretation are
**unavailable** until sources, qualified review, and adjudications are admitted. Defaults are five
windows/five near misses; maxima are 20/20, 31 days, 5,000 candidates, and 512 KiB. No window is a
successful empty result. Oversized ranges narrow the range; cancellation/deadline returns incomplete;
high-stakes activity is unsupported.

## Privacy and inspection

No profile, coordinates, times, place labels, or traces enter operation metrics. No ResearchRun,
persistence, side effect, REST, or Pi surface is added. Inspection requires `include_trace=true`.
Migration/backup impact: none.
