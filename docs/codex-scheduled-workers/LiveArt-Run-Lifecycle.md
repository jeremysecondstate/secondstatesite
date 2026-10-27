# LiveArt manual queue lifecycle

The active [worker instructions](../sched-tasks-codex/liveart-sched-tasks/liveart-sched-task-description.md) match the saved `artprice-worker` prompt. Keep scheduling **PAUSED**. No catalog scan or fixed lot quota is part of this workflow.

## Manual entry

Jeremy selects Calendar lots with **Add to research**, reviews order and optional instructions in **LiveArt Queue**, then tells LiveArt Worker **“Process my LiveArt queue.”** The worker runs:

```powershell
.\.venv\Scripts\python.exe scripts\liveart_research_queue.py start --thread-id $env:CODEX_THREAD_ID
```

The client verifies the actual current human request and root workspace, checks execution ownership and persists the request identity before calling the server. The server snapshots only Queued selections, with their current order and notes. It never imports historical control priorities. Empty/completed selections do not launch research. Entries added afterward wait for another manual request.

`status` and `claim` inspect/claim only the frozen snapshot. `intent` and `settle` journal existing query/save operations; they never execute provider requests or website saves. `outcome` publishes verified research/skip/triage/unavailable results; `block` preserves a specific obstruction. `finish` requires the full snapshot audit and settled operations. Use the helper's `--help` and [queue implementation guide](../liveart-research-queue.md) for payloads and tests.

The client uses the existing local CATALOG_API_KEY only for the dedicated SecondState queue endpoint. It rejects redirects and does not log credentials. Browser research, evidence and Board saves keep their supported visible workflow. No browser cookies or hidden state are read.

## Recovery and user stops

The private pointer is `private_data/liveart-worker-runs/manual-queue.json`. Preserve it and the registry, receipts and historical operation guards. After a new explicit manual request, `resume` verifies terminal prior root/descendant execution before resuming the same snapshot. No lease expires automatically; uncertain outcomes remain guarded. `reconcile` can record a freshly verified existing operation receipt without rerunning the operation. `stop` handles an actual explicit human stop while preserving settled outcomes and uncertain operations.

Completed and Needs attention items do not automatically repeat. Staff must use **Research again → Queue again**, with a reason, before a later manual run. Removing unclaimed work cancels that selection; removing a researching item does not discard or retry its in-flight outcome. Never clear a guard just because it is old.

Manual queue claims and intents belong to the server snapshot/client pointer. Historical catalog-control state is retained for operation recovery and usage, not used to select new work. Only verified bookkeeping may clear settled historical execution guards. A missing or stale Codex history projection fails closed.

## Windows archive watchdog

The Windows task **SecondState LiveArt Run Archive Watchdog** runs every ten minutes while the user is logged in. It invokes the helper with `watchdog --apply` and does not call a model. Reinstall its definition with:

```powershell
.\scripts\install_liveart_archive_watchdog.ps1
```

Only historical scheduled run chats whose saved prompt begins with `LIVEART_STANDALONE_RUN_V1`, whose workspace matches the configured project, and whose creation follows the migration are eligible. Codex's native automation header is accepted only with the exact LiveArt Worker name, automation ID and memory path before that marker. A matching title or a marker quoted elsewhere is insufficient. Finished runs become eligible after two hours of inactivity whether read or unread. Pinned chats, active or uncertain turns, stale history projections and active descendants prevent archival. On-demand chats and earlier worker conversations do not carry this opt-in marker and remain outside this cleanup scope.

The watchdog reads Codex metadata and history, then archives through `codex archive <UUID>`. It does not edit Codex databases, move transcripts or permanently delete chats. Archived chats remain recoverable. Queue files, receipts and research ledgers are retained. The helper logs decisions and archival outcomes in its private lifecycle directory.

Preview cleanup without archiving:

```powershell
.\.venv\Scripts\python.exe scripts\liveart_run_lifecycle.py watchdog
```


Manual/on-demand registrations are explicitly excluded from watchdog discovery, even if their older first message happens to contain the historical marker. This feature does not alter the Windows watchdog schedule or another worker. Archival is not proof of research completion.
