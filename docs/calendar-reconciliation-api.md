# Calendar reconciliation API

`/calendar/reconciliation/` uses the existing Calendar `X-API-KEY` authentication.
It is never accessible through a staff cookie alone, and responses are not cached.
Use it for the SecondState Lot Updater's public readback and reviewed Drouot-to-Invaluable duplicate suppression.

## Readback

`GET` returns `lots`, `next_cursor`, and `observed_at`. Each row contains source identity,
Calendar ID, sale and lot details, native bids/currency, source observation timestamps,
`active`, `superseded_by_id`, and a current review `fingerprint`. Saved research, purchase
flags and staff selections are omitted. Superseded records remain readable here.

- Follow `next_cursor` until null; default/max `page_size` is 500. All saved dates are
  available; unlike `/calendar/watchlist/`, this endpoint has no seven-day horizon.
- Optional `start=YYYY-MM-DD` and `end=YYYY-MM-DD` are inclusive Calendar dates in
  `CALENDAR_TIME_ZONE`. Omit them for a full public inventory, including undated rows.
- Optional `ids=1,2,3` selects up to 500 specific Calendar IDs.
- `mode=audit` returns the existing duplicate candidate audit. Supply `ids` or both
  dates spanning at most 90 inclusive days. More than 10,000 records requires a narrower
  window. Candidates are review aids, never automatic authorization to merge.
- `operation=RUN_ID` retrieves the durable receipt for a successful POST (404 if absent).

Only Invaluable and Drouot records are exposed by this endpoint.

The maintained local CLI loads existing `.env` Calendar credentials without printing them:

```powershell
.\.venv\Scripts\python.exe scripts\calendar_reconciliation.py --output RUN/calendar-before.json
.\.venv\Scripts\python.exe scripts\calendar_reconciliation.py --audit --start 2026-11-14 --end 2027-01-14 --output RUN/candidates.json
```

Snapshot files contain a `lots` array and page observation times. Pagination is a sequence
of reads, not a single database snapshot; keep the original source timestamps and compare
changed rows again immediately before applying. Output paths must be new files.

## Apply a reviewed plan

Confirm the same house, sale/session/date and lot number, corroborated by source links,
catalogue details or images. Inspect saved-work accessibility as described in the
[Calendar duplicate review](sched-tasks-codex/calendar-sched-task/calendar-worker.md#duplicate-lot-review).
Read fresh fingerprints immediately before preparing the plan.

```json
{
  "version": 1,
  "operation": "lot-updater-20261115T030840Z-part1",
  "reviewed": true,
  "pairs": [{
    "keep_id": 123,
    "remove_id": 456,
    "keep_fingerprint": "CURRENT_64_CHARACTER_SHA256",
    "remove_fingerprint": "CURRENT_64_CHARACTER_SHA256",
    "reason": "Specific evidence establishing this sale and lot identity."
  }]
}
```

POST 1–200 pairs, at most 1 MB. Operation IDs use letters, numbers, dots, underscores
and hyphens, at most 76 characters. The endpoint permits only an Invaluable survivor
and a Drouot redundant row. It rejects stale fingerprints, already-superseded rows,
repeated removals, chains, and removal of a row with retained children. A failed pair
rolls back the entire operation. No source fields or saved work move between records.

The successful response includes `receipt` and `replayed`. Store the receipt locally.
Retry an uncertain request with the identical operation ID and plan: the endpoint
returns the same stored receipt without another mutation. Reusing the ID for a different
plan returns 409. A replay confirms the original operation, not the present display
state; use GET to verify current records after every mutation or replay.

```powershell
.\.venv\Scripts\python.exe scripts\calendar_reconciliation.py --apply RUN/reviewed-plan.json --receipt RUN/receipt.json
.\.venv\Scripts\python.exe scripts\calendar_reconciliation.py --operation lot-updater-20261115T030840Z-part1 --output RUN/operation-readback.json
```

The CLI reserves the new receipt path and durably records the operation ID/hash before
sending one POST. A success file contains the reversible receipt plus attempt metadata.
On timeout, malformed response or server failure it instead saves an explicitly unknown
attempt; never treat that file as a rollback receipt. A known validation/authentication
rejection is labeled rejected. The CLI never automatically retries a POST. Read the
operation and current public rows first; if another POST is needed, retain the identical
plan and operation ID and use a new local receipt path.

The database transaction stores both the full receipt and per-lot supersession receipts.
The returned receipt uses the existing `secondstate-calendar-duplicate-receipt-v1`
format and supports the management command's reviewed rollback procedure. There is no
automatic rollback endpoint. For corrections, review current state and run the supported
rollback against the verified production database; preserve later source results.
