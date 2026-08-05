# Private Auction Calendar and Email Tray

The desktop Artist Watchlist synchronizes normalized auction results to the staff-only calendar at `/calendar/`. The calendar and every Email Tray route use Django staff-login protection; ordinary and logged-out users are redirected to the staff login.

## Data flow

```text
Artist Watchlist refresh
  -> POST /calendar/sync/ with X-API-KEY
  -> AuctionWatchLot upsert by source + source lot ID
  -> staff saves an Artprice URL and explicitly selects a lot
  -> one shared database-backed Email Tray
  -> staff reviews ordered lots and fixed recipient choices
  -> one multipart message through Gmail API users.messages.send
```

The desktop sync uploads only normalized auction fields. It does not upload bookmark HTML, browser state, cookies, local cache data, source page HTML, image URLs, ambiguity flags, Artprice URLs, Email Tray state, or API credentials. Existing Artprice links, analyses, and Email Tray selections survive later upserts of the same source lot.

## Email Tray behavior

Under each lot's Artprice editor, **Include in next email** is disabled until a secure `artprice.com` URL has been saved. Saving a link enables the checkbox but does not select it. Selection is explicit and shared by all staff users; the selecting staff account is stored with the item.

Selection persists across sessions, month navigation, and desktop syncs. Removing the Artprice URL removes that lot from the active tray. A successful send archives the batch and its send-time snapshots, so all calendar checkboxes become unchecked without deleting sent history.

The review page:

- orders lots by sale time, auction house, artist, and lot number or source identifier;
- groups the preview by local sale date and auction house;
- offers only the fixed `jeremy`, `oliver`, and `alex` recipient keys;
- lets staff remove one lot or clear the active tray;
- requires at least one recipient and a final browser confirmation;
- disables repeat submission after confirmation;
- preserves a failed batch and its items for deliberate retry.

The database permits only one active `draft`, `sending`, or `failed` batch. A send transaction changes an eligible batch to `sending` before the Gmail call, preventing a second request from dispatching the same batch. Success archives it as `sent`; failure returns the same active batch to `failed`. Sent recipient, subject, HTML, plain-text, and per-lot snapshots remain unchanged when live lots change later.

## Artprice max-bid analysis

Staff can expand **Artprice Max-Bid Analysis** beneath a lot's Artprice editor. Upload a saved USD Artprice `.html` or `.htm` results page (maximum 5 MB), review the normalized comparable records and assumptions, and calculate maximum hammer bids. Raw uploaded HTML is parsed in memory and is never stored or rendered. Saved normalized analysis remains attached during later watchlist syncs.

## Website and desktop sync configuration

The website and desktop process must use the same `CATALOG_API_KEY`. Production sync requires HTTPS; plain HTTP is accepted only for localhost testing.

```dotenv
# Website and desktop process
CATALOG_API_KEY='<same-long-random-value>'

# Desktop process
SECONDSTATE_BASE_URL='https://secondstate.art'

# Website
DEBUG='false'
CALENDAR_TIME_ZONE='America/Los_Angeles'
SECONDSTATE_PUBLIC_URL='https://secondstate.art'
```

Run migrations during deployment:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Migration `0018_auctionemailbatch_auctionemailbatchitem_and_more` adds the shared active-batch constraint, send history, item attribution, and immutable send-time snapshots. Historical reminder migrations remain untouched.

## Gmail configuration

Keep delivery disabled while configuring and previewing:

```dotenv
AUCTION_EMAIL_SENDING_ENABLED='false'
AUCTION_EMAIL_SENDER='jeremy@secondstate.art'
AUCTION_EMAIL_RECIPIENT_JEREMY='jeremy@secondstate.art'
AUCTION_EMAIL_RECIPIENT_OLIVER='oliver@secondstate.art'
AUCTION_EMAIL_RECIPIENT_ALEX='alex@secondstate.art'
GOOGLE_GMAIL_CLIENT_ID='<desktop-oauth-client-id>.apps.googleusercontent.com'
GOOGLE_GMAIL_CLIENT_SECRET='<desktop-oauth-client-secret>'
GOOGLE_GMAIL_REFRESH_TOKEN='<refresh-token-created-locally>'
```

Local Django commands and the development server load the repository-root `.env` without overriding variables already present in the process. Render does not receive that local file; configure the same names in the Render service environment for deployment.

The sender must resolve to `jeremy@secondstate.art`. Every selected recipient must be configured and use the `@secondstate.art` domain. Browser requests submit only fixed recipient keys; addresses are resolved from the server environment. OAuth credentials are never stored in the database, page, fixtures, or logs.

### Google Cloud and Workspace setup

1. In a Google Cloud project controlled by SecondState, enable the **Gmail API**.
2. Configure the Google Auth consent screen. For a Google Workspace-only deployment, use an internal audience when the organization permits it; otherwise complete the required test-user or publishing configuration.
3. Configure the single requested scope: `https://www.googleapis.com/auth/gmail.send`. Do not add read, modify, full-mail, Drive, or contacts scopes.
4. Create an OAuth 2.0 client with application type **Desktop app**. Put its client ID and client secret in the local environment and later in Render's secret environment.
5. If Workspace API controls restrict OAuth apps, have the Workspace administrator allow or trust this OAuth client for the `gmail.send` scope.
6. From a trusted local machine, authorize the sender:

   ```powershell
   .\.venv\Scripts\python.exe manage.py authorize_auction_gmail
   ```

   Sign in as `jeremy@secondstate.art`. The command opens a localhost OAuth callback, requests only `gmail.send`, prints the refresh token to the terminal, and does not write it to a file or edit `.env`.

7. Add the printed refresh token and the other Gmail variables to Render. Keep `AUCTION_EMAIL_SENDING_ENABLED=false`, deploy, migrate, and verify tray selection plus the complete review preview.
8. Set `AUCTION_EMAIL_SENDING_ENABLED=true`, deploy the environment change, and send a small test batch to Jeremy only before selecting additional recipients.

If Google does not return a refresh token, revoke the existing app grant for `jeremy@secondstate.art` and rerun the command so the consent prompt can issue a fresh offline token.

## Twilio retirement and Render cutover

The website no longer reads Twilio settings, exposes SMS pages, dispatches reminders after desktop sync, or provides the `send_auction_reminders` command. Historical Twilio migrations and audit models remain only for database compatibility.

After the new deployment is healthy:

1. Delete any Render cron/scheduled job that runs `python manage.py send_auction_reminders`.
2. Remove `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`, `TWILIO_FROM_NUMBER`, `TWILIO_MESSAGING_SERVICE_SID`, `TWILIO_SMS_ENABLED`, and `AUCTION_REMINDER_TO_NUMBERS` from Render.
3. Revoke or delete the unused Twilio API key and Messaging Service in Twilio if they serve no other system.
4. Keep the Gmail switch false until its OAuth setup and preview have been verified.

Removing obsolete Render variables before the code deployment is safe for the new code, but the ordered cutover above avoids affecting the currently deployed reminder code before it has been replaced.

## Operational verification

1. Confirm `/calendar/` and `/calendar/email-tray/` redirect logged-out and non-staff browsers.
2. Save an Artprice link and confirm the checkbox becomes enabled but remains unchecked.
3. Select a lot as one staff user and confirm another staff user sees the same selection and its attribution.
4. Sync the same lot again from the desktop and confirm the Artprice link and selection remain.
5. Remove the Artprice link and confirm the lot leaves the tray.
6. Review ordering, grouping, Unicode text, estimates, local time, and both saved links.
7. With sending disabled, confirm the warning appears and the preview remains usable.
8. After OAuth configuration, send a small batch to Jeremy and confirm the provider message ID, sending staff account, and sent time are stored.
9. Confirm the sent lots are unchecked and the calendar panel shows the last successful email.

## Automated verification

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe manage.py test secondstateapp.tests_calendar
.\.venv\Scripts\python.exe manage.py test
```

Tests mock Gmail delivery and make no external Gmail, Twilio, Artprice, Invaluable, or production website calls.
