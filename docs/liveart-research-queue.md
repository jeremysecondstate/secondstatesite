# LiveArt Research Queue

Calendar's **Add to research** checkbox saves a shared staff selection against the existing lot ID. It is independent of Email Tray membership and does not require saved research or an Artprice/LiveArt link. **LiveArt Queue · N** opens the selected works across all dates. Staff can reorder, add instructions, remove selections, and explicitly queue a completed/blocked work again with a reason.

Checking a box never starts research. Tell LiveArt Worker **“Process my LiveArt queue.”** The first manual start captures only currently Queued selections, in their saved order, with their instructions. Later additions and edits wait for the next start. There is no three-lot cap, automatic catalog scan, polling, or website launch button. The `artprice-worker` automation remains PAUSED.

## State and ownership

Migration `0048_research_queue` adds selection, run, immutable run-item and operation-receipt tables. Existing lot IDs are protected references; auction synchronization does not replace selections. A locked singleton serializes queue changes and snapshot creation. A durable request UUID makes an interrupted start idempotent. The local pointer is `private_data/liveart-worker-runs/manual-queue.json`.

One coordinator owns a run. A timeout never transfers ownership. The existing lifecycle registry, Codex history/rollout checks, descendant checks and historical business-operation guards still apply. Old catalog priorities never populate this queue. Manual claims are recorded in the new queue; do not create a legacy catalog `active_batch` or advance its cursor.

The UI shows Queued, Researching, Done and Needs attention. Done also identifies the actual disposition: researched, valuation unavailable, triaged or skipped. Research completion requires current saved evidence and Board proof; skips/triage require their actual source evidence. Completion does not make a valuation reliable by assertion or alter financial rules.

Removing an unclaimed snapshot item records a staff-removal receipt. Removing a claimed item preserves its operation and eventual result, even when the item is no longer selected. Rechecking a completed or blocked item does not retry it. **Research again → Queue again** requires a reason and creates a new generation; old results remain retained. Unknown operations continue to prevent unsafe retry.

## Supported worker commands

Run from `C:/dev/secondstatesite`. The client reads the existing `CATALOG_API_KEY` internally and sends it only to SecondState's dedicated `/calendar/research-queue/worker/` endpoint using `X-API-KEY`. `SECONDSTATE_BASE_URL` defaults to `https://secondstate.art`; only HTTPS origins are accepted and redirects are rejected. Never print the key. This is coordination only: the client does not query LiveArt or save evidence/Boards.

```powershell
.\.venv\Scripts\python.exe scripts\liveart_research_queue.py start --thread-id $env:CODEX_THREAD_ID
.\.venv\Scripts\python.exe scripts\liveart_research_queue.py status --thread-id $env:CODEX_THREAD_ID
.\.venv\Scripts\python.exe scripts\liveart_research_queue.py claim --thread-id $env:CODEX_THREAD_ID
```

`start` validates the latest actual human message in the active root chat: `Process my LiveArt queue` (case, whitespace, a final period/exclamation mark and an initial `Please` are accepted). The chat must belong to the configured root workspace/project; an older on-demand chat may qualify without the historical first-message marker. Do not forge an authorization item ID. The optional `--authorization-item-id UUID` pins the real current message. On a later explicit manual request, `resume` recovers the existing snapshot after verifying prior execution is terminal. An empty snapshot performs no research. A completed snapshot cannot restart itself. `--help` lists command arguments; the payload and audit schemas are specified below. Optional global `--config PATH` precedes the command.

During an ongoing snapshot the original verified authorization remains valid through harmless status questions or other steering. Such messages do not create another snapshot. Join supporting descendants before a mutating helper command: these commands require an active coordinator root and terminal descendants. New `claim` and genuinely new `intent` commands also require the historical business guards to be clear. Do not create a legacy `active_batch` or lot claim for this pass; queue claims and intents provide its operation ownership. Preserve historical locks and reconcile their actual outcomes when required.

For `intent`, `settle`, `outcome` and `block`, pass `--payload PATH` pointing to a private JSON file. `item_id` is the frozen run-item ID, not the Calendar lot ID.

| Command | Required payload / behavior |
| --- | --- |
| `intent` | `item_id`, `kind` (`search`, `save_evidence`, `save_board`, `other`), `details` object; optional stable `operation_id`. The client journals an ID before the request. Execute the actual operation only if the first confirmed response says `operation_execution_allowed: true`. A replay says false even if the original response was lost; reconcile rather than repeat. |
| `settle` | `item_id`, `operation_id`, nonempty `result` containing the actual observed receipt, and `units_spent` as a known nonnegative decimal. For unknown usage use null plus `result.usage_unknown: true`; never invent zero. Retrying the exact receipt is safe; rewriting it is rejected. |
| `outcome` | `item_id`, `disposition`, `reason`, and applicable `checks`/`proof` or `source_proof` described below. All operations must be settled. |
| `block` | `item_id`, `reason`, `reopening_condition`, `source_proof`. Other actionable items continue. Only a demonstrated common obstruction justifies `shared_block: true`; this requires source proof and marks remaining work Needs attention. |

For `researched` and `valuation_unavailable`, truthful checks are required: `google_original_researched`, `liveart_browser_researched`, `evidence_saved_reloaded`, `board_saved_reloaded`, `costs_verified`, `selection_verified`, `email_flags_verified`. An unobservable email flag must instead have an explicit `proof.verification_gaps.email_flags` explanation. Preserve the established zero-evidence unavailable workflow.

After the existing visible save/reload workflow, `status` and `claim` expose `run.items[*].current_saved_proof`: actual `liveart_analysis_id`, `liveart_updated_at`, `bid_board_analysis_id`, `bid_board_updated_at`. Use these values in `proof`; never infer analysis IDs from a lot ID. The server verifies current revisions and that the Board matches saved selected evidence, candidate records and source summary. A stale Board must be reconciled/resaved before completion. These metadata supplement the required rendered save/reload proof; they do not replace research checks.

For `triaged` or `skipped`, preserve the actual gate, reason and source proof. Do not manufacture a Board or report completed valuation research. Full research standards and financial rules remain in the [canonical worker instructions](sched-tasks-codex/liveart-sched-tasks/liveart-sched-task-description.md).

## Finish, interruptions and unknown outcomes

`finish --audit PATH` requires an audit inside the configured business-control directory. Its version-1 JSON contains:

- `schema_version: 1`, actual `thread_id`, frozen `run_id`;
- `lot_ids`: every frozen Calendar lot ID; `completed`: exactly Done IDs; `pending`: exactly Needs attention IDs;
- `bookkeeping_complete`, `usage_accounted`, `operations_settled`, `cleanup_complete`, each `true` only after verification;
- `lot_receipts`: a mapping from lot-ID strings to existing private receipt paths;
- `external_blockers`: for pending lots, actual `kind` (`external_site_failure`, `access_denied`, `evidence_unavailable`, `tool_restriction` or `deployment_restriction`), nonempty `required_step`, `observed_failure`, `reopening_condition`, at least one `recovery_attempts` entry with nonempty `action`/`result`, and `no_authorized_useful_action_remaining: true`.

Only unclaimed staff removals, shared blocks or explicit stops may use `server_receipts` instead of a private lot receipt: map a lot-ID string to the real `{run_id, item_id}` receipt. Both client and server validate the entire snapshot, even when historical control has no touched lots. A separate genuine legacy recovery retains its original audit requirements; historical work is not added to the new snapshot. An unresolved queue operation prevents finish even if a blocker is documented. Do not change flags just to pass the audit.

If the server finished but its response was lost, a later explicit request followed by `resume --audit PATH` reconciles local completion without transferring the completed run or researching again. A `completion_pending`/`checkpoint_pending` result requires the reported bookkeeping; it does not authorize a fresh snapshot.

For an actual explicit user stop, such as `Stop` or `Please stop for now`, use `stop --thread-id $env:CODEX_THREAD_ID --audit PATH`. The first stop requires an actual current human message beginning with Stop, Pause or Cancel, optionally preceded by Please. The audit additionally includes `human_stop: true` and the original real stop message's `authorization_item_id`; do not invent external blockers for a user stop. If the audit is not yet ready, `stop --thread-id $env:CODEX_THREAD_ID` records the stop and retains a pending checkpoint; its returned stop receipt identifies the actual message. Settle known outcomes and complete the audit, then retry stop or finish with that audit. Retries preserve the exact original stop receipt and verify its human message in history, even after harmless later steering. New research stops, but existing uncertain outcomes remain protected and can be settled. Harmless later user steering does not invalidate an ongoing authorized snapshot, and does not override a prior explicit stop.

If an interrupted predecessor left an unknown operation, `reconcile --payload PATH --receipt PATH` is a narrow settlement path after terminal-owner/descendant verification. The receipt must match the actual payload's `item_id`, `operation_id`, `result`, `units_spent`, include `outcome_verified: true`, and include nonempty `verification.source`, `verification.observed_at`, `verification.observed_result`. This does not authorize new queries or clear unrelated guards. Finish the old verified accounting before a fresh manual resume. Never expire an unknown operation by age.

## Verification and release

Tests use isolated Django test databases and synthetic lifecycle/history fixtures; no real research or paid provider queries are needed. Run the queue Django tests, existing Calendar/manual-evidence/Board regressions, frontend Node tests, and `python -m unittest scripts.test_liveart_run_lifecycle scripts.test_liveart_research_queue`. Inspect desktop and narrow rendered layouts. Migration deploys through the existing Render build workflow.

The actual automation prompt must exactly match `docs/sched-tasks-codex/liveart-sched-tasks/liveart-sched-task-description.md`. Update it through the supported automation tool, keep it PAUSED, and verify model, reasoning, schedule and destination are unchanged. Calendar Worker and unrelated schedules are outside this change.
