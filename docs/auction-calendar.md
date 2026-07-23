# Private Auction Calendar and SMS Reminders

The desktop Artist Watchlist can now synchronize its normalized results to the staff-only calendar at `/calendar/`. The route uses the same Django staff login protection as `/capital-dashboard/`; ordinary and logged-out visitors are redirected to the admin login.

## Data flow

```text
Artist Watchlist refresh
  -> local normalized lots shown in the desktop Calendar tab
  -> POST /calendar/sync/ with X-API-KEY
  -> AuctionWatchLot upsert by source + source lot ID
  -> if reminder texts are active, run an immediate idempotent catch-up
  -> staff-only monthly calendar and selected-day detail panel
  -> hourly 3/2/1-day reminder safety-net job
  -> Twilio Messages API
```

Only normalized auction fields are uploaded. The bookmark HTML, browser state, cookies, local cache, source page HTML, image URLs, ambiguity flags, and API credentials are not included. A successful desktop refresh automatically attempts the sync; **Sync Website Calendar** retries the current result without fetching auction sites again.

Staff can paste a secure `artprice.com` URL into the **Artprice link** field beneath any lot in the selected-day panel. The saved link is attached to that calendar lot, can be opened or removed from the same panel, and is intentionally preserved when later Artist Watchlist syncs update the auction details.

## Website configuration

The desktop app and website must use the same `CATALOG_API_KEY`. Production sync requires HTTPS; plain HTTP is accepted only for a localhost development server. Older desktop code contained a fallback value, so rotate that key in Render and the ignored local `.env` before enabling sync-triggered texts; the desktop now refuses calendar sync when the environment value is missing.

```dotenv
# Website (Render) and desktop process
CATALOG_API_KEY='use-the-same-long-random-value-in-both-places'

# Desktop only; this defaults to the production URL
SECONDSTATE_BASE_URL='https://secondstate.art'

# Website calendar display and reminder date boundaries
DEBUG='false'
CALENDAR_TIME_ZONE='America/Los_Angeles'
SECONDSTATE_PUBLIC_URL='https://secondstate.art'
```

Run the database migration during deployment:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

The existing Render build/start scripts already run migrations, so a normal deploy applies migrations `0014` and `0015` automatically. Migration `0015` adds the persisted Start/Pause control and defaults it to paused.

## Twilio configuration

API-key authentication uses the account SID in the Messages endpoint and the API key SID/secret for HTTP Basic authentication. Sending also requires either a Twilio phone number or a Messaging Service SID, plus at least one opted-in recipient. Twilio documents these requirements in its [API key overview](https://www.twilio.com/docs/iam/api-keys) and [Messages resource reference](https://www.twilio.com/docs/messaging/api/message-resource).

```dotenv
TWILIO_ACCOUNT_SID='AC...'
TWILIO_API_KEY_SID='SK...'
TWILIO_API_KEY_SECRET='store-only-in-the-host-secret-manager'

# Choose one sender option. A Messaging Service takes precedence if both exist.
TWILIO_FROM_NUMBER='+12065550123'
TWILIO_MESSAGING_SERVICE_SID=''

# Comma-separated recipients in E.164 format. Every recipient must have opted in.
AUCTION_REMINDER_TO_NUMBERS='+12065550124,+12065550125'

# Leave false until the sender and recipients have been tested.
TWILIO_SMS_ENABLED='false'
```

Do not paste the API key secret into code, screenshots, Git, or the desktop UI. Twilio trial accounts can send only to verified recipient numbers. Follow Twilio's current [SMS compliance and consent guidance](https://www.twilio.com/docs/messaging/onboarding/sms-foundations) before adding a recipient.

For a U.S. `+1` local number, keep `TWILIO_SMS_ENABLED=false` while Twilio Console shows **Messaging disabled**. Complete A2P 10DLC Brand and Campaign registration, associate the number with the approved Messaging Service sender pool, and wait until the campaign is verified. Then copy the real `MG...` SID into the runtime environment. Leave `TWILIO_MESSAGING_SERVICE_SID` empty—not `???`—until that SID exists. Unregistered U.S. 10DLC traffic is blocked by Twilio with error 30034.

`.env.example` is committed documentation only. Keep real credentials and phone numbers in Render's secret environment settings. The desktop catalog entry point loads the ignored project `.env` without overriding variables already present in the process; it never loads `.env.example`.

## Reminder behavior

Run a preview after the calendar has data:

```powershell
.\.venv\Scripts\python.exe manage.py send_auction_reminders --dry-run
```

An explicit date is useful for verification without changing the system clock:

```powershell
.\.venv\Scripts\python.exe manage.py send_auction_reminders --dry-run --date 2026-07-20
```

Once Twilio approves the sender and the preview is correct, set `TWILIO_SMS_ENABLED=true`. Log in to `/calendar/` as staff and click **Start Reminder Texts**. Starting performs an immediate catch-up for currently due, previously unsent digests. **Pause Reminder Texts** blocks live delivery from the calendar, desktop sync, and scheduler; the Render flag remains the master emergency safety switch.

Configure the hosting scheduler to run this command hourly:

```text
python manage.py send_auction_reminders
```

The command exits successfully without sending while reminders are paused. When active, it uses `CALENDAR_TIME_ZONE` to decide which sales are exactly three, two, or one calendar day away. A sale first discovered two days before receives only the two- and one-day reminders; a sale first discovered one day before receives only the one-day reminder. Each run sends one compact digest per recipient and target date, even when a sale contains many watched lots.

Every successful non-empty desktop calendar sync also runs the same catch-up immediately when reminders are active. The sync response reports whether delivery sent, skipped, failed, was paused, or was blocked by the Render safety switch. The hourly scheduler remains a safety net for events that were already stored or for a missed sync response.

Delivery rows prevent repeated runs from sending the same digest twice. If a genuinely new sale is synced after that date's digest was sent, the next run sends one supplemental digest containing only the newly discovered sale or sales. Full recipient phone numbers are not stored in the database: only a keyed hash and masked last four digits are retained. Failed deliveries are recorded and may be retried; already-covered or still-pending deliveries are skipped. If a worker is interrupted and leaves a row pending, a staff administrator can change that row's status to **Failed** in Django admin to permit a deliberate retry.

## Operational checklist

1. Deploy and confirm `/calendar/` redirects a logged-out browser to the staff login.
2. Log in as a staff user and confirm the calendar loads.
3. Set the same `CATALOG_API_KEY` for the website and desktop process.
4. Refresh a small Artist Watchlist selection and confirm the desktop status says the website calendar synced.
5. Confirm the correct artist, title, auction house, estimate, lot number, and local sale time appear on the chosen day.
6. Configure a Twilio sender and one opted-in test recipient.
7. Run the reminder command with `--dry-run` and inspect the digest.
8. After Twilio approval, enable the Render safety switch and click **Start Reminder Texts** on the calendar.
9. Verify the immediate catch-up in Twilio, then enable the hourly scheduler as a safety net.
10. Sync the same lots again and confirm the desktop reports they were already covered rather than sending duplicates.
11. Add further opted-in recipients only after the single-recipient test succeeds.

## Automated verification

```powershell
.\.venv\Scripts\python.exe manage.py test secondstateapp.tests_calendar
.\.venv\Scripts\python.exe manage.py test
```

Tests use fake HTTP sessions; they do not contact Twilio, Invaluable, or the production website.
