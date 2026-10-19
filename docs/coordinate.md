# Coordinate: staff coordination and draft review

Coordinate is a staff-only conversation area at `/coordinate/`. The website database owns case history, pending work, claim leases, replies, and activity. The page refreshes conversation/status data while open. Browser messages and worker replies use HTTP and database writes; they do not require commits or deployments.

All active staff share the cases. Each case has its own history and bound worker claims; these are not private conversations scoped to one staff account. With the draft workflow enabled, staff can save a shipping plan, compare and select provider quotes, review email drafts, and read retrieved public source notes. The worker receives those saved records on every run. Staff controls change the plan and approvals; model replies do not silently change them.

**Coordinate prepares drafts for website review. It does not send shipping email, read an inbox, contact providers, book pickups, or make payments.** Selecting a quote, reviewing a draft, or acknowledging a price increase does not authorize payment. The original messaging-only mode remains the default until the draft-workflow flag is enabled. A separately authorized local Codex Scheduled task checks every ten minutes using GPT-6 Astra and Ultra reasoning. Existing internal auction notification email code is unrelated and is not used by Coordinate.

Observed local proof and test results are retained in the private local `docs/coordinate-verification.md` and associated screenshots. These files are ignored by Git and are not part of the public repository or release.

## Enable the draft workflow

Set `COORDINATE_DRAFT_WORKFLOW_ENABLED=true` in the Django server environment to enable the structured workspace, bounded public-page research, draft proposals, and recorded-deadline reviews. With the flag absent or false, Coordinate retains messaging-only test mode; the worker does not fetch public sources or produce email draft records.

Set `COORDINATE_PRICE_REVIEWER_USERNAME=<designated staff username>` to the exact Django username of the staff member authorized to acknowledge provider price increases. A blank or mismatched value leaves those pauses unresolved. This setting identifies a website account; it is not a Gmail address or permission to send mail. Configure it privately for each environment and restart/reload the service when changing environment settings.

Keep the runtime shipping playbook consistent with the enabled workflow: public research and draft preparation are permitted, while external actions remain disabled. Preserve the original packing source unchanged. Neither flag grants the Codex process access to Gmail, Drive, or other desktop connections.

## Plans, quotes, drafts, and trash

Save the case's destination, handling instructions, stage, pickup deadline, notes, and any tracking details in the shipping plan. Deadline inputs without an explicit offset use `America/New_York`. Tracking fields are staff-maintained records; saving a tracking link does not enable carrier monitoring.

Provider quotes currently use USD. Choose the destination and handling method before selecting a quote. The first accepted total is retained as an immutable baseline for that provider quote, including when it is selected again. The record also keeps the destination and handling selection. Changing the plan's destination or handling clears the current selection and draft reviews so staff can review the revised plan.

A later total **$50 or more above the accepted baseline** pauses draft review for that provider thread. The comparison is cumulative: a $100 accepted baseline followed by $130 and then $150 pauses at $150. The case shows the pause and records it in activity. The designated reviewer must acknowledge the current increase with a note before draft review can resume; other staff cannot clear it. The accepted baseline remains unchanged, and later unreviewed increases can pause the thread again. An increase below $50 is not payment authorization.

Email drafts stay on the website. Staff may edit, copy, and mark the wording reviewed; editing a reviewed draft requires review again. A matching paused provider blocks review even if the draft has no explicitly linked quote. Generated drafts require a recipient supported by staff-provided case information or successfully retrieved public evidence; the worker must not invent an address. No review or copy control sends email, and there is no Gmail send or inbox integration.

Cases and individual messages can be moved to trash and restored. This is reversible removal, not permanent erasure. Trashed cases are excluded from worker processing. Deleted message text and its derived worker artifacts are excluded from active context; a history change invalidates in-flight work so a later check reloads the current conversation. Restoring a case does not automatically restore messages that were individually deleted.

## Run a local roundtrip with draft review

Use the repository's Python environment and its normal local Django configuration. Do not point a local test at a production `DATABASE_URL`.

1. Install dependencies and apply migrations as needed:

   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate
   ```

2. Set a strong `COORDINATE_WORKER_TOKEN` in the server process environment and the worker process environment. Generate it with `secrets.token_urlsafe(32)` or a secret manager. Keep it out of Git, screenshots, frontend code, URLs, and command-line arguments. The two processes must use the same value. An absent configured token disables the worker API. For local playbook context, preserve the existing private `docs/coordinate-playbook.md` and user-authored `docs/cardboardsandwich.md`; both are ignored by Git. The server can read these local fallback files, or use the private environment values described below. Enable the draft-workflow flag and designate the price-review staff account for this local test. Use an existing staff login or create a local staff user with `manage.py createsuperuser`.

3. Start Django locally:

   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765 --noreload
   ```

4. Open `http://127.0.0.1:8765/coordinate/`, sign in as staff, and confirm the page says draft coordination. Start a clearly labeled fictional case and send a message such as `local verification: prepare a draft to packer@example.com asking which pickup details are needed. this is a fictional provider; do not send. reference https://example.com/`. Confirm the saved message and waiting status appear immediately. The reserved example address is for this local verification only.

5. In the second terminal, confirm the Codex CLI is installed and authenticated, then invoke one job:

   ```powershell
   codex --version
   codex login status
   $env:COORDINATE_BASE_URL = 'http://127.0.0.1:8765'
   .\.venv\Scripts\python.exe scripts\coordinate_worker.py
   ```

   This uses the existing signed-in CLI account; no separate OpenAI API key is needed. The CLI uses its default available model and reasoning effort unless `--model` and `--reasoning-effort` are supplied. `--codex` can select an installed executable. The worker runs one claimed message and exits, or prints `status: idle` when there is no eligible work.

   To use the same model and reasoning effort as the scheduled messaging test:

   ```powershell
   .\.venv\Scripts\python.exe scripts\coordinate_worker.py --model gpt-6-astra --reasoning-effort ultra
   ```

6. Leave the page open and observe the actual generated response, source result, and proposed draft in that case. Review the draft's recipient and wording, edit it, save it, and mark it reviewed. Confirm no email is sent. Reload and verify the conversation, source notes, draft, and review state remain. Reply with a follow-up, invoke the worker again, and confirm it incorporates the saved history. The worker prints saved identifiers, research/draft counts, and a response SHA-256 digest without printing the token or conversation.

7. In the fictional case, save a destination and handling method, add a $100 quote, and select it. Record later totals of $130 and $150. Confirm the cumulative pause at $150, a blocked draft review, and that only the configured price-review account can acknowledge the increase. Confirm the accepted baseline remains $100. Move a message and the case to trash, restore them, and verify their history and processing status.

This is a verification procedure, not a claim that the draft workflow has already passed a live run. Record the actual result privately before reporting success. An actual generated reply and draft must be observed on the website; unit tests using a mocked model do not establish that roundtrip.

## Public source research

When the server explicitly enables the production draft workflow, the worker can retrieve up to eight distinct public HTTPS links from staff messages, prioritizing the latest message. It validates every DNS answer, pins the connection to a validated public IP while verifying the original TLS hostname, and revalidates redirect destinations. Requests carry no website token, login, cookies, or proxy configuration. Per-page and total time budgets, redirect limits, and body limits bound each run.

The worker extracts bounded HTML/plain-text excerpts and records the exact source URL, title, retrieval time, and any error. Retrieved text is untrusted evidence, never permission or instructions. It cannot inspect photos or infer unseen lot details. A blocked page, including HTTP 403, is reported as unavailable; the worker does not bypass access controls or invent the missing contents. PDF extraction and browser-rendered pages are not supported in this fetcher. Supply the relevant text through the case when a source cannot be read.

## Scheduled messaging test

The separately authorized local Codex Scheduled task `coordinate-messaging-test` uses a ten-minute interval, GPT-6 Astra (`gpt-6-astra`), and Ultra reasoning in the local `secondstatez` project. Each run starts independently, loads the private worker configuration, and invokes the worker once with those same settings. Each invocation processes at most one eligible message or recorded-deadline review, retrieves the saved case context, and saves its response through the authenticated API. With the draft workflow enabled, that response may include public research and email draft proposals. An idle check adds no conversation message and should remain quiet. Confirm the task's current state in Scheduled; this document is not a live scheduler status feed.

The computer must remain on, the desktop app must remain running, and the local project, CLI login, and private worker configuration must remain available. Review runs and pause the test task from **Scheduled** in the desktop app. This follows the local execution requirements in the [official scheduled-task documentation](https://learn.chatgpt.com/docs/automations).

On a successful worker check, the enabled draft workflow can queue one review for a recorded pickup deadline that is within 48 hours or already overdue. This applies to active cases in the gathering, quotes, or ready stages, even when staff have not posted another message. Each recorded deadline is reviewed once; changing the deadline resets that reminder. The queued review still waits for an available worker and cannot guarantee a particular completion time.

This is a review of the website's saved deadline. It does not read provider emails, poll carriers, detect tracking changes, or perform shipment follow-through. The ten-minute cadence remains the authorized local schedule for this work; the separate weekday/weekend operational cadence below remains disabled.

The website records the last successful worker check and each message's processing state. It does not receive authoritative scheduler status from Codex, so it does not display an invented next check time or claim that the test task is still active after it has been paused. Use Scheduled to confirm the task's current status and cadence.

## Connection and recovery

The worker reads `COORDINATE_WORKER_TOKEN` only from its environment. It sends `Authorization: Bearer …` to these POST endpoints:

| Endpoint | Purpose |
| --- | --- |
| `/coordinate/api/claim/` | Check recorded deadlines, atomically claim eligible work, and retrieve saved conversation, plans, quotes, draft state, source notes, and current playbooks. |
| `/coordinate/api/jobs/<job-id>/complete/` | Save the generated reply and permitted research/draft records for the current claim, case and message. |
| `/coordinate/api/jobs/<job-id>/fail/` | Record a safe failure summary and make the claim eligible for a delayed retry. |

Claims use durable job/message identifiers and a 15-minute lease. Only one message in a case is processed at a time. A crashed process leaves the work reclaimable after lease expiry; an explicit generation failure allows retry after a short delay. A later scheduled or manual invocation can retrieve the work once eligible. Repeated completion of the same claim is idempotent for replies and associated artifacts. A stale claim, changed case context, or mismatched case/message is rejected. The worker retries transient completion transport failures with exactly the same reply, research, and drafts; it does not regenerate on those retries. If every completion attempt fails, leave the claim intact and check the page before retrying. Across a crash, generation may repeat after expiry, but the database prevents duplicate saved replies.

The last successful check means an authenticated claim request successfully loaded the playbooks and checked pending work, including an idle check. It does not mean generation succeeded; message status separately shows waiting, processing, retrying, or replied. A claim request itself is not automatically retried: if its response was lost after committing, its lease recovers the work after 15 minutes. A generation failure becomes eligible after 30 seconds. Neither mechanism starts a worker by itself.

The API requires HTTPS except for loopback local development in the worker. Redirects are refused so the bearer token cannot be forwarded to a different destination. HTTP 401 means a missing/incorrect token, 503 can mean the server token is unset, and 409 means the claim expired, changed, or does not match. API/model output is not dumped to logs. An unavailable CLI, expired login, unsupported CLI flags, or generation timeout produces an operator-safe error and leaves recoverable work.

## Model isolation and retained context

Every run starts a fresh ephemeral CLI session in a temporary directory, with the saved conversation, structured coordination state, source evidence, and both playbooks on standard input. Public fetching happens in the bounded Python wrapper before generation; the model receives excerpts rather than browser access. The CLI ignores user configuration and exec rules, disables bundled/user/plugin skills and memory, and does not load repository instructions. The child process receives an allowlisted environment without the website worker secret, OpenAI/Gmail API keys, desktop tool pipes, or inherited chat identifiers. Existing CLI authentication remains outside the repository.

The CLI runs without its shared daemon in a read-only sandbox. Shell execution, apps, plugins, MCP configuration, browser/computer access, image tools, hooks and subagents are disabled. Codex may retain internal orchestration, time and read-only infrastructure tool definitions; the worker requires a structured text result and rejects a result containing a tool-operation event. It exposes no email, provider, payment, or scheduling connection to the model. CLI authentication does not imply Gmail or Drive access.

The implementation was checked against installed Codex `0.163.0-alpha.10.2` and current official OpenAI documentation for [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI options](https://learn.chatgpt.com/docs/cli/reference), and [configuration](https://learn.chatgpt.com/docs/config-file/config-reference). Recheck CLI flags and isolation before upgrading this worker's execution environment.

The server loads the effective shipping and packing context for every claim and returns it only through the authenticated worker connection. Each Codex invocation receives that current context together with the saved case history. Context is not cached in an earlier Codex conversation, bundled into the frontend, or retrieved from a public repository.

## Private playbook configuration

The GitHub repository is public. Private receiving addresses, Drive references, user-authored packing instructions, conversation evidence, and screenshots must remain outside Git. Keep the original local `docs/coordinate-playbook.md` and `docs/cardboardsandwich.md` unchanged and ignored; preserve them as private reference sources. The website database remains authoritative for active cases.

Configure these **two multiline environment values** on the Render web service before deploying Coordinate:

| Private setting | Value |
| --- | --- |
| `COORDINATE_SHIPPING_PLAYBOOK` | The complete contents of the private local shipping playbook. |
| `COORDINATE_PACKING_PLAYBOOK` | The complete, unchanged contents of the original user-authored packing markdown. |

Use Render's protected environment settings or the existing secret-management workflow. Preserve actual line breaks and UTF-8 text. Do not put the values in a tracked `.env` file, Blueprint, test fixture, deployment log, or public documentation. These settings belong to the Django server; the worker receives their contents over its authenticated claim request and does not need separate copies in its environment.

Environment values take precedence over the local file fallbacks. A fresh production checkout will not contain the ignored originals, so both values are required on Render. If either effective playbook is unavailable, the worker API refuses to claim work. Update private context through the server's environment configuration and restart/reload the service as required by that configuration mechanism; subsequent claims receive the updated context.

## Before any production rollout

Review the private local evidence, apply the migrations to the intended database, configure the two private multiline playbook values and server/worker token outside source control, and provide a reachable HTTPS origin and a separately authenticated Codex execution host. For the draft workflow, also enable `COORDINATE_DRAFT_WORKFLOW_ENABLED=true` and configure `COORDINATE_PRICE_REVIEWER_USERNAME`. Verify PostgreSQL concurrency, staff access, and the designated reviewer's identity in that environment. The website does not automatically start a worker. A hosted worker does not inherit the desktop account, tools or connections.

Include migrations `0034_coordinate`, `0035_coordinate_soft_delete`, and `0036_coordinate_shipping_workspace`, application code, templates/static files, and both worker/source-fetcher scripts in the release. Keep private playbook originals, local verification records, and screenshots out of the commit and release. Run the usual static collection/build. The original messaging roundtrip does not verify the expanded draft workflow; perform and record the draft-review procedure and the deployed authenticated connection checks before reporting them as complete.

The later operational cadence remains disabled: Monday–Friday hourly and Saturday–Sunday every three hours in `America/New_York`. Before enabling it, verify execution-host availability and implement separately authorized inbox/carrier follow-through for ongoing cases. The current ten-minute Scheduled task and saved-deadline reviews do not provide that capability. Keep Drive references/exports subordinate to the website database, and do not show a next scheduled check without authoritative scheduler data.
