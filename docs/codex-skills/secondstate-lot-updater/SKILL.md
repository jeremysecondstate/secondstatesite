---
name: secondstate-lot-updater
description: Update SecondState Calendar lots and observed bids from the maintained Invaluable and Drouot artist bookmarks, and reconcile verified duplicate sale lots in favor of Invaluable. Use for SecondState Lot Updater runs and direct requests for this workflow.
---

# SecondState Lot Updater

Work in `C:/dev/secondstatesite`. Use `docs/artist-links.html` as the current collection scope and `https://secondstate.art/calendar/` as the intended Calendar. This workflow adds newly listed lots, refreshes public current bids and bid counts, and leaves one visible Invaluable listing when both providers carry the same verified auction lot. Updating a bid means recording an observed auction value; never place a bid or change the user's bidding instructions.

Jeremy has explicitly authorized full access to his one Render workspace and asked not to be asked again. Use confirmed workspace `tea-d4ttfuumcj7s7387dap0` (Jeremy's workspace) and production Postgres `dpg-d58sue6r433s73ffqn6g-a` (`secondstate-db`) for this task, passing the workspace ID on connector calls. This standing workspace choice does not need reconfirmation on new chats. Keep mutations within this updater's requested lot/bid/deduplication scope.

The scheduled task is **SecondState Lot Updater**, every **two hours**, with **GPT-6 Astra**, reasoning effort **ultra**, starting a **new chat per run**. Those settings belong to the native Codex automation; invoking this skill does not modify them. Ignore the obsolete hourly/99-minute schedules, old PC paths, worker chat names and source-preference instructions in the older single-source briefs where they conflict with this combined task. Preserve unrelated schedules.

## Start and durable state

Read applicable `AGENTS.md`, the current bookmarks, and `private_data/secondstate-lot-updater/state.json` if present. Read and update automation memory at `<CODEX_HOME>/automations/<actual invocation ID>/memory.md`, using nonempty `CODEX_HOME` or falling back to `C:/Users/7970X/.codex`. Load previously verified house-alias evidence from task state and [the public reference](references/verified-house-aliases.json); reuse house identity for candidate discovery while independently proving each new sale/session and individual lot. Do not assume a new chat retains browser handles or in-memory collectors.

Use timestamped run directories beneath `private_data/secondstate-lot-updater/`, with separate `invaluable` and `drouot` evidence directories. Save the exact bookmark manifest and its hash, date window, completed/pending/failed/zero-result searches, original observation times, page progress, preview reports, sync receipts, duplicate review and readback. Preserve older attempts; do not relabel them fresh. Read old per-source checkpoints only when needed for recovery and leave unrelated workers' state intact.

Prevent overlapping writers using an exclusively created `private_data/secondstate-lot-updater/run.lock` containing the owning chat/run ID and start time. If it exists, inspect its owner and saved progress before work. Continue only when the earlier owner is demonstrably finished; do not clear another live owner's lock or infer abandonment from elapsed time alone. If a prior single-source collector is active, defer conflicting collection/synchronization. Release only this run's lock after saving progress, including on an incomplete exit.

## Collect both sources

Read [Invaluable collector](C:/dev/secondstatesite/docs/invaluable-collector.md) and [Drouot collector](C:/dev/secondstatesite/docs/drouot-collector.md) for the maintained formats, collection helpers, validation and recovery. These are technical references; this skill defines the combined task's scope, cadence and pair preference.

- Invaluable: select exactly **BULK-1A, BULK-1B, BULK-2A, BULK-2B**, with all current artists and categories from their URLs. Derive counts each run; exclude archived `OLD` links and redundant individual searches. Preserve encoded artist/category parameters. Use `scripts/invaluable_browser_collection.cjs`, `scripts/invaluable_export_snapshot.js` and `scripts/build_invaluable_browser_bundle.cjs` for evidence and validation.
- Drouot: select every current artist bookmark under **DROUOT — PRINTS**, independently of Invaluable's scope. Use `catalogapp.watchlist_drouot_pages.select_drouot_entries` and `scripts/drouot_browser_collection.mjs`. Derive counts from the current file. Keyword/category matches do not prove artist credit or print medium: retain the normalizer's primary-credit and explicit-technique checks, including visible `after`/`attributed to` qualifiers.

For new-lot discovery, start with today's date in **America/New_York** and collect every page of the current source searches. Include all newly captured dated future lots through the latest real source date, as well as later active Calendar dates needing refresh; the former next-Sunday window must not silently exclude newly listed future sales. Both formats permit at most **90 inclusive days** per capture window, so use separate complete validated windows when needed. If the browser capture began with a shorter window, retain that original file unchanged and derive the wider-window import from the same public pages with unchanged source timestamps and recorded provenance. Save actual UTC observation instants and original sale timezone evidence. Calendar display uses **America/Los_Angeles**; source-card browser timezone may differ from the New York eligibility window, and a differing date label is not automatically a different sale.

Also inventory existing active Invaluable/Drouot Calendar lots for bid refresh. A search capture may omit an active saved lot even within its date window. Extend complete validated windows through later active dates or use the verified direct-lot fallback below. There is no established bid-only CLI: do not invent one or bypass capture validation. Record every active lot not freshly observed and why; do not report all bids current while later or missing lots remain unchecked. Expired lots with an actual posted result may be updated under existing result rules, but a past date alone is not a sold result.

Use the currently available supported browser tool and read its returned documentation before collection. The legacy helpers require a supported tab with DOM and network-response capabilities; verify those capabilities instead of assuming an old API still exists. Observe responses generated by normal page navigation and visible pagination controls, with actual lot cards and matching scope/IDs. Collect all pages, since sort order does not prove a date cutoff. Never substitute a blank, denied, loading or challenged page for a zero-result search. Keep public fields only; do not retain cookies, tokens, private account/watch/bid metadata, or replay source requests through another transport.

If the supported runtime only imports `.js`/`.mjs` and reports CJS `module` unavailable, prepare run-local ESM adapters with [scripts/prepare_browser_modules.py](scripts/prepare_browser_modules.py) using `--run-dir` set to a fresh attempt directory. It changes only the collector's sole `module.exports = (` to `export default (`; the snapshot core gets a local `const module = { exports: {} };` prefix and `export default module.exports;` suffix around unchanged source. The helper records original and prepared SHA-256 hashes. Dynamically import the resulting `.mjs` file paths through the supported runtime; do not evaluate source strings. Use the current maintained Drouot `.mjs` directly, or an exact run-local copy when a fresh path is needed after a module-cache reload.

Keep collectors, tab handles and attempt directories together. Persist a page before advancing. Recover a failed scope independently while continuing other valid scopes. Use a supported alternative browser when it resolves an evidenced capability failure. After a second unsuccessful retry of the same persistent failure, checkpoint the specific recovery action and complete independent work; do not spin indefinitely.

## Preview, synchronize and verify bids

Use the repository Python environment when functional: `C:/dev/secondstatesite/.venv/Scripts/python.exe`. Inspect each script's current `--help` if its interface differs. Keep credentials in existing local configuration, never tool output or reports.

With `RUN` standing for this run's source directory, the maintained commands are:

```powershell
# Build the Invaluable bundle after complete verified browser collection.
node scripts/build_invaluable_browser_bundle.cjs START END RUN/capture.json ENVELOPES...
.\.venv\Scripts\python.exe scripts\import_invaluable_capture.py RUN/capture.json --bookmarks docs\artist-links.html --report RUN/preview-report.json

# Drouot's collector writes its own capture format.
.\.venv\Scripts\python.exe scripts\import_drouot_capture.py RUN/capture.json --bookmarks docs\artist-links.html --report RUN/preview-report.json
```

Resolve preview errors before repeating that source's command with `--sync` and `--report RUN/sync-report.json`. Invaluable's bundle validator establishes complete pagination; the importer alone is not proof of full search coverage. Drouot sync requires the complete current bookmark scope and pagination; `--artist` is a read-only pilot, never a reduced production upload. Do not sync partial Drouot captures or weaken validation to finish a run. A complete validated source can progress while the other remains incomplete. If a complete preview has zero eligible observations, record a validated no-op: the importers return successfully without uploading or producing a sync receipt. Do not manufacture a synced report or run a receipt-dependent comparison for that no-op.

Fresh accepted observations already carry `current_bid`, `bid_count`, native `currency`, status and `last_seen_at` through `catalogapp/watchlist_sync.py`. Preserve their original provider and lot IDs, source timestamps and monetary currency. A Drouot zero placeholder is an absent bid; missing bid counts remain unknown. The existing schema can store a verified opening amount in `current_bid` with `bid_count=0`; preserve that valid observation and its opening/no-bids distinction rather than reporting it as a placed bid. Do not substitute estimates for bids, guess amounts or counts, copy one provider's bid into another provider's row, or mark cached data freshly checked. Preserve newer Calendar observations, existing sold results, absent lots, purchase flags, research, saved Bid Boards, Email Tray selections and supersession links.

For an active saved lot absent from complete search captures, inspect its exact stored lot URL and lot number through the supported browser. Invaluable detail pages can display a total including buyer premium: use the explicit native-currency **current bid + buyer premium** breakdown's hammer amount, and the public **N bid(s)** count. Never substitute an account's maximum bid. Save the visible evidence and original observation time. If bid fields changed, reread that exact live public row, merge only the verified bid fields into its existing public sync record, and upload through the existing sync function with the new observation timestamp. Preserve source identity, title, credit, status, provenance and the exact original first-seen timestamp, and obey the newer-observation guard. Record unchanged values as a fresh check without a redundant upload. A 404 or inaccessible page is unavailable evidence, not proof that the lot ended or sold; retain its saved values and report the exception.

Save a before-sync Calendar snapshot and compare after-sync values with both the preview and the receipt.

Prefer the deployed [Calendar reconciliation API and CLI](C:/dev/secondstatesite/docs/calendar-reconciliation-api.md) for complete public readback, including all future dates and superseded rows. Use `scripts/calendar_reconciliation.py --output RUN/calendar-public-before.json` before writes and another new output path afterward. It loads the existing `CATALOG_API_KEY` locally and validates every page. Its `lots` include public Calendar/source IDs, bids, source timestamps, supersession and current review fingerprints; compare both sources' accepted observations and report actual bid changes. The older Drouot auditor below remains useful for its source-specific checks but its watchlist/DOM coverage limits do not apply to the new endpoint:

```powershell
.\.venv\Scripts\python.exe scripts\audit_drouot_calendar.py --run-dir RUN --calendar-time-zone America/Los_Angeles before
.\.venv\Scripts\python.exe scripts\audit_drouot_calendar.py --run-dir RUN --calendar-time-zone America/Los_Angeles after
.\.venv\Scripts\python.exe scripts\audit_drouot_calendar.py --run-dir RUN --dom RUN/calendar-dom-after.json compare
```

The legacy auditor's comparison expects Drouot's preview/sync reports and a bare DOM row array for `--dom`, not the new CLI's snapshot object. Do not mislabel a Drouot-only audit as verification of both sources. Only the legacy watchlist API has a short horizon: when using that auditor, supplement with the guide's public monthly Calendar projection or verified public database projection for every updated lot outside its horizon, and explicit database evidence for hidden supersessions it omits. The new reconciliation CLI already reads all dates and hidden rows and needs no DOM supplement. Do not infer an ended auction from a hidden row.

Count actual bid-value/count changes from before/after fields separately from the API's generic `updated` count, which includes unchanged records and timestamp refreshes. Verify new Calendar IDs and all changed public values. Preserve partial-sync receipts and reconcile remote state before retrying uncertain writes.

## Reconcile cross-source duplicates

Read the [Calendar duplicate-lot review](C:/dev/secondstatesite/docs/sched-tasks-codex/calendar-sched-task/calendar-worker.md#duplicate-lot-review) and `secondstateapp/calendar_duplicates.py` before applying a new pair. Audit the full underlying sale/day, including lots hidden by display filters.

Combine the full live API audit with comparisons of both fresh captures and all visible live rows. Review **every new cross-source candidate**, including `confidence: review` and differing house names; an empty exact-house/title match is not a duplicate-free result. The existing audit can omit valid pairs when canonical artist names differ or estimates differ/miss an upper bound. Group by verified house aliases, sale/date and meaningful lot number independently of artist/estimate equality, then corroborate each individual work. Check plausible house-name variants among remaining same-date/lot/artist candidates rather than dismissing them because `_house_key` differs. Preserve artist typos/aliases in raw observations while resolving identity from actual catalogue details. Re-run this broader comparison after suppression and account for every remaining candidate as a distinct sale/lot, a preexisting same-source issue, or a specific unresolved case.

Confirm **the same auction lot in the same sale/session** using a shared underlying identifier/link, or verified house aliases, sale/date and lot number corroborated by catalogue details or artwork images. Retain meaningful lot suffixes, different editions/impressions and later resales. Normalized artist/title similarity, estimates, stock images or candidate confidence alone are not identity proof.

For each confirmed Drouot/Invaluable pair, retain **Invaluable** as the visible survivor and reversibly set the Drouot row's `superseded_by` to that Invaluable row. Keep both provider records and raw observations. Inspect saved research, queue/history, source/Artprice links, Email Tray, Bid Boards, purchase and sold state first; all saved work must remain accessible. Do not delete rows, rewrite identities, move/overwrite saved work or create supersession chains. Preserve existing verified supersessions. If identity or saved-state conflicts remain, retain both and record the exact unresolved pair.

The maintained Django command supports an audit, a reviewed plan with fingerprints, and a reversible receipt:

```powershell
.\.venv\Scripts\python.exe manage.py reconcile_calendar_duplicates --report RUN/duplicate-audit.json
.\.venv\Scripts\python.exe manage.py reconcile_calendar_duplicates --apply RUN/reviewed-pairs.json --receipt RUN/duplicate-receipt.json --report RUN/duplicate-after.json
```

For production, prefer the deployed `/calendar/reconciliation/` API through `scripts/calendar_reconciliation.py`; read [its contract](C:/dev/secondstatesite/docs/calendar-reconciliation-api.md) before use. Fetch current rows/fingerprints with `--ids` and `--output`, then save a reviewed version-1 plan with a unique `operation`, `reviewed: true`, and at most 200 pairs containing IDs, fingerprints and concrete reasons. Apply once with `--apply RUN/reviewed-pairs.json --receipt RUN/duplicate-receipt.json`. The endpoint only permits Drouot-to-Invaluable suppression and records atomic, reversible, idempotent receipts. For uncertain writes, use `--operation RUN_ID --output RUN/operation-readback.json` before retrying the identical operation and plan; do not invent another operation ID. Read current rows again after application or replay.

**Verify the database target before using the management command.** Local settings default to `db.sqlite3` without a configured `DATABASE_URL`; changing that file does not change the live Calendar. The command remains a production alternative only with a verified production database binding, including for reviewed rollback. Do not claim a local audit or local write updated production. Reread fingerprints immediately before applying, and let a changed record require a fresh review.

Verify the survivor and suppressed original on the actual Calendar, affected sale/day counts and preserved saved-work links. Confirm future syncs preserve the direct supersession and cannot resurrect the Drouot card. Record provider IDs, Calendar IDs, source URLs, sale/lot proof, chosen survivor and before/after counts.

## Finish

Atomically update this task's durable state and automation memory with coverage, actual new-lot and changed-bid counts, confirmed duplicate suppressions, unresolved pairs, verification gaps and concrete next actions. Persist verified house aliases with source house/catalogue URLs, address evidence, observation times and exact sale scope so the next new chat can reuse them. For unavailable lots, retain Calendar/source IDs, stored URLs, last observation, preserved bid values and a concrete retry action. End a bounded run with recoverable unfinished work saved; do not reset successful stages or invent completeness. Report meaningful changes and material failures concisely, distinguishing source collection, upload and live readback. An unchanged successful run can finish quietly. This task does not send email, alter other schedules, redesign the Calendar or modify purchase/research decisions.
