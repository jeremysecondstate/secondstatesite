# Coordinate: local manual worker

Coordinate is a staff-only conversation area at `/coordinate/`. The website database owns case history, pending work, claim leases, replies, and activity. The page refreshes conversation/status data while open. Browser messages and worker replies use HTTP and database writes; they do not require commits or deployments.

All active staff share the cases. Each case has its own history and bound worker claims; these are not private conversations scoped to one staff account. Structured quote/decision controls, attachments, and external correspondence are later milestones. For now, staff decisions are retained as conversation messages and processing events are retained in the activity history.

**This milestone is test mode only. Shipping emails, provider contact, bookings, charge approvals, payments, and recurring schedules remain disabled.** Existing internal auction notification email code is unrelated and is not used by Coordinate.

Observed local proof and test results are retained in the private local `docs/coordinate-verification.md` and associated screenshots. These files are ignored by Git and are not part of the public repository or release.

## Run a local roundtrip

Use the repository's Python environment and its normal local Django configuration. Do not point a local test at a production `DATABASE_URL`.

1. Install dependencies and apply migrations as needed:

   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate
   ```

2. Set a strong `COORDINATE_WORKER_TOKEN` in the server process environment and the worker process environment. Generate it with `secrets.token_urlsafe(32)` or a secret manager. Keep it out of Git, screenshots, frontend code, URLs, and command-line arguments. The two processes must use the same value. An absent configured token disables the worker API. For local playbook context, preserve the existing private `docs/coordinate-playbook.md` and user-authored `docs/cardboardsandwich.md`; both are ignored by Git. The server can read these local fallback files, or use the private environment values described below. Use an existing staff login or create a local staff user with `manage.py createsuperuser`.

3. Start Django locally:

   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765 --noreload
   ```

4. Open `http://127.0.0.1:8765/coordinate/`, sign in as staff, start a case, and send a distinctive test message such as `we won these lots!! https://example.com/auction/lot-17 — local test only`. Confirm the saved message and waiting status appear immediately.

5. In the second terminal, confirm the Codex CLI is installed and authenticated, then invoke one job:

   ```powershell
   codex --version
   codex login status
   $env:COORDINATE_BASE_URL = 'http://127.0.0.1:8765'
   .\.venv\Scripts\python.exe scripts\coordinate_worker.py
   ```

   This uses the local CLI's login; no separate website OpenAI key is needed when that login is available. The CLI uses its default available model unless `--model` is supplied. `--codex` can select an installed executable. The worker runs one claimed message and exits, or prints `status: idle` when there is no eligible work.

6. Leave the page open and observe the generated response appear in the correct conversation. Reload and verify both messages remain. Reply with a follow-up, invoke the worker again, and confirm it incorporates the saved history. The worker prints saved job, message, reply and case identifiers and a response SHA-256 digest, without printing the token or conversation.

An actual model reply must be observed on the website to claim integration success. Unit tests using a mocked model do not establish a live roundtrip.

## Connection and recovery

The worker reads `COORDINATE_WORKER_TOKEN` only from its environment. It sends `Authorization: Bearer …` to these POST endpoints:

| Endpoint | Purpose |
| --- | --- |
| `/coordinate/api/claim/` | Atomically claim an eligible message; retrieve its saved case conversation and current shipping/packing playbooks. |
| `/coordinate/api/jobs/<job-id>/complete/` | Save a real generated reply for the current claim, case and message. |
| `/coordinate/api/jobs/<job-id>/fail/` | Record a safe failure summary and make the claim eligible for a delayed retry. |

Claims use durable job/message identifiers and a 15-minute lease. Only one message in a case is processed at a time. A crashed process leaves the work reclaimable after lease expiry; an explicit generation failure allows retry after a short delay. Invoke the worker manually again when eligible. Repeated completion of the same claim is idempotent. A stale claim or mismatched case/message is rejected. The worker retries transient completion transport failures with exactly the same generated body; it does not regenerate on those retries. If every completion attempt fails, leave the claim intact and check the page before retrying. Across a crash, generation may repeat after expiry, but the database prevents duplicate saved replies.

The last successful check means an authenticated claim request successfully loaded the playbooks and checked pending work, including an idle check. It does not mean generation succeeded; message status separately shows waiting, processing, retrying, or replied. A claim request itself is not automatically retried: if its response was lost after committing, its lease recovers the work after 15 minutes. A generation failure becomes eligible after 30 seconds. Neither mechanism starts a worker by itself.

The API requires HTTPS except for loopback local development in the worker. Redirects are refused so the bearer token cannot be forwarded to a different destination. HTTP 401 means a missing/incorrect token, 503 can mean the server token is unset, and 409 means the claim expired, changed, or does not match. API/model output is not dumped to logs. An unavailable CLI, expired login, unsupported CLI flags, or generation timeout produces an operator-safe error and leaves recoverable work.

## Model isolation and retained context

Every run starts a fresh ephemeral CLI session in a temporary directory, with the saved conversation and both playbooks on standard input. It ignores user configuration and exec rules, disables bundled/user/plugin skills and memory, and does not load repository instructions. The child process receives an allowlisted environment without the website worker secret, OpenAI/Gmail API keys, desktop tool pipes, or inherited chat identifiers. Existing CLI authentication remains outside the repository.

The CLI runs without its shared daemon in a read-only sandbox. Shell execution, apps, plugins, MCP configuration, browser/computer access, image tools, hooks and subagents are disabled. Codex may retain internal orchestration, time and read-only infrastructure tool definitions; the worker requires a text-only result and rejects a result containing a tool-operation event. It exposes no email, provider, payment, or scheduling connection to the model. CLI authentication does not imply Gmail or Drive access.

The implementation was checked against installed Codex `0.163.0-alpha.10.2` and current official OpenAI documentation for [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI options](https://learn.chatgpt.com/docs/cli/reference), and [configuration](https://learn.chatgpt.com/docs/config-file/config-reference). Recheck CLI flags and isolation before upgrading this worker's execution environment.

The server loads the effective shipping and packing context for every claim and returns it only through the authenticated worker connection. Each Codex invocation receives that current context together with the saved case history. Context is not cached in an earlier Codex conversation, bundled into the frontend, or retrieved from a public repository.

## Private playbook configuration

The GitHub repository is public. Private receiving addresses, Drive references, user-authored packing instructions, conversation evidence, and screenshots must remain outside Git. Keep the original local `docs/coordinate-playbook.md` and `docs/cardboardsandwich.md` unchanged and ignored; preserve them as private reference sources. The website database remains authoritative for active cases.

Configure these **two multiline environment values** on the Render web service before deploying Coordinate:

| Private setting | Value |
| --- | --- |
| `COORDINATE_SHIPPING_PLAYBOOK` | The complete contents of the private local shipping playbook. |
| `COORDINATE_PACKING_PLAYBOOK` | The complete, unchanged contents of the original user-authored packing markdown. |

Use Render's protected environment settings or the existing secret-management workflow. Preserve actual line breaks and UTF-8 text. Do not put the values in a tracked `.env` file, Blueprint, test fixture, deployment log, or public documentation. These settings belong to the Django server; the manual worker receives their contents over its authenticated claim request and does not need separate copies in its environment.

Environment values take precedence over the local file fallbacks. A fresh production checkout will not contain the ignored originals, so both values are required on Render. If either effective playbook is unavailable, the worker API refuses to claim work. Update private context through the server's environment configuration and restart/reload the service as required by that configuration mechanism; subsequent claims receive the updated context.

## Before any production rollout

Review the private local evidence, apply the migration to the intended database, configure the two private multiline playbook values and server/worker token outside source control, and provide a reachable HTTPS origin and a separately authenticated Codex execution host. Verify PostgreSQL concurrency and staff access in that environment. The website does not automatically start a worker. A hosted worker does not inherit the desktop account, tools or connections.

Include migration `0034_coordinate`, application code, templates/static files, and the worker script in the release. Keep the private playbook originals, local verification document, and screenshots out of the commit and release. Run the usual static collection/build. Local roundtrip evidence does not by itself verify production configuration; check the deployed authenticated connection and staff page after rollout while retaining test mode.

No recurring task is installed. The later agreed cadence is weekdays hourly and weekends every three hours in `America/New_York`; before enabling it, verify execution-host availability and add email/deadline follow-through for ongoing cases. Local desktop scheduling requires the computer and app to remain available. Show a next scheduled check only after a real schedule exists. Keep Drive references/exports subordinate to the website database.
