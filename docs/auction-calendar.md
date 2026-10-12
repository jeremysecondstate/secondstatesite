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

The desktop sync uploads normalized auction fields and the source's public primary-image URL. Saved Heritage imports can also upload the artwork image from the saved page's companion folder. It does not upload bookmark HTML, browser state, cookies, source page HTML, ambiguity flags, per-lot Artprice links, or Email Tray state. The API key is sent only in the authentication header. Existing Artprice links, analyses, and Email Tray selections survive later upserts of the same source lot.

Each optional `saved_image_base64` is validated independently by the website: JPEG, PNG, or WebP, at most 512 KiB decoded and 4 million pixels, with both dimensions exceeding 8 pixels. The website re-encodes it as a metadata-free JPEG with a maximum edge of 1600 pixels. It validates the entire sync batch before writing images or database rows. Images use content-derived names under `MEDIA_ROOT/calendar-lots/` on the persistent media disk; repeat uploads of the same image reuse the file. Later URL-only refreshes preserve saved images. Only the exact `/media/calendar-lots/<sha256>.jpg` path format and approved HTTPS auction/CDN hosts may appear as calendar images. Sync responses include `images_received`, allowing the desktop to detect older website versions that do not support saved images. The existing 2 MB request limit still applies, so the desktop sends bounded batches.

Each selected-day lot shows a separate current-bid line beneath its estimate/details. It renders the current amount and bid count when available, **No bids** when the source reports a zero bid count, and **N/A** when Invaluable omits bid data.

Selecting a calendar date shows **Selected date → Auctions Happening This Day → Suggested Lots**. Every distinct auction represented in the synced watchlist appears above the existing lot browser and lot cards, with its full title linked to the source auction page, auction house, local time, and watched-lot count. If the source omits a sale title, the house name is used; if it omits an auction URL, the entry stays visible with an unavailable-link note. Sales from the same house remain separate, while lots sharing an auction URL form a single entry. Calendar cells show up to three auction titles across multiple lines, with full names available on hover and a **+N more auctions** indicator for busy days. Selecting any date resets the selected-day panel to its auction list; when the panel is below the calendar, selection scrolls it into view. Adjacent-month dates and dates selected through Upcoming sales include their complete synced auctions and lots.

**View day as → Gallery Catalog** replaces the month grid and sidebar with an image-led catalog for the same selected date. **Calendar** returns to the existing layout with that date still selected. The catalog uses the same validated lot images, artist Artprice links, auction links, estimates, bids, and ended status as the sidebar and modal. Its house and Email Tray filters, artist/house sorting, and 24-at-a-time **Show more lots** control make large days easier to scan. Previous/next day moves between loaded watched dates, including upcoming dates outside the current month grid. **Quick look** opens the existing lot browser at the clicked work; **Browse one by one** starts at the first lot. The star on a card adds or removes a lot from the existing Email Tray when its lot-specific Artprice URL is saved. If it is missing, the star opens Quick look so the link can be saved first. The selected view and date appear in the page URL and survive a reload; month navigation retains the catalog view. Starting in catalog view defers the sidebar's Artprice controls until the user switches to Calendar.

A selected day with synced lots shows **Browse all N lots**. The button opens one modal rather than creating browser tabs: only the current lot card and primary image are rendered, while previous/next buttons or Left/Right move through the date's in-memory lot data. Navigation wraps at either end; Home and End jump to the first and last lot; Escape and the close button return focus to the launch button. Missing or failed images use a neutral fallback, and opening the external auction page remains a deliberate per-lot action.

The modal's **Artprice quick workflow** saves or removes the current lot's Artprice link and provides an immediately open HTML upload/analyzer. Default max-bid assumptions keep rapid lot-by-lot processing to a file choice and one click; an optional disclosure exposes every assumption when adjustments are needed. Link, Email Tray, and saved-analysis changes are synchronized with the selected-day panel without refreshing the page. Arrow, Home, and End keys continue to work for lot navigation except while focus is inside these workflow controls, where they retain their normal form behavior.

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

Staff can expand **Resale Bid Analysis** beneath a lot's Artprice editor. **Add HTML files** accepts multiple saved USD Artprice `.html` or `.htm` results pages from related searches. New files join the lot's saved files, and the file list lets staff remove one source at a time. Up to 10 sources can be saved per lot, with a 5 MB limit per file and 25 MB per upload. An invalid file rejects the entire upload. Raw uploaded HTML is parsed in memory and is never stored or rendered. Saved normalized analysis remains attached during later watchlist syncs.

The Artprice estimate uses the combined unique sales across those files. Overlapping records are counted once, with all contributing filenames retained on the sale. Existing single-file analyses become one saved source. Removing a source recalculates the Artprice estimate and any saved resale bids; a sale found in another remaining file stays available. **Remove all Artprice files** clears the lot's Artprice history.

The same normalized sold records feed **Sold comps for resale bids**. USD Artprice hammer sales with a matching named artist are preselected up to the 25-sale limit, alongside any selected LiveArt sales. Staff can uncheck individual records, manually select rows whose artist is missing, and save updated bids. The saved resale analysis displays how many Artprice records were ingested, eligible for automatic selection, selected, and actually used, including any overlap counted once across sources. Each saved filename appears with its own counts. Unsaved resale selections, research, and costs survive file changes and remain pending until saved again.

## LiveArt word and phrase searches

All new LiveArt searches are restricted to **Prints & Multiples**. The server sends `category_id=2` on every artwork and sold-lot lookup, including default-title searches, each alternative term, chosen artwork sale history, and related-work fallbacks. This category was verified against [LiveArt's canonical taxonomy](https://api.liveart.ai/v1/categories) on October 12, 2026; both endpoints support the filter in the [OpenAPI specification](https://api.liveart.ai/openapi.json). Returned records must also explicitly report that category; missing, conflicting, or other categories are excluded without inferring category from a title or medium. The result summary reports any excluded records.

Fresh searches save the category filter with their search summary. Earlier saved LiveArt research remains identifiable as unfiltered and displays a notice to search again; it is not relabeled as Prints & Multiples research. This restriction applies to LiveArt lookups and does not change imported Artprice records.

**LiveArt search terms (optional)** searches each word separately and combines the returned sold records for the Calendar artist. For example, `Boomerangs Stabiles` searches both words. Double quotes keep a title or translation together: `"Very Gay Nose and Ears"`. Commas and semicolons can also separate alternatives. Duplicate terms are searched once. Leave the field blank to use the existing Calendar title and artwork-reference workflow.

Each term search accepts up to five distinct words or phrases, totaling at most 200 characters. It uses one artist lookup and one sold-lot lookup per term, sharing a maximum of 20 returned sale rows across those lookups. The response displays each term's returned count and flags additional available results; refine the terms when a result page is incomplete. Actual metered Data Units are displayed. There is no automatic pagination.

Term matches are review candidates because LiveArt searches both titles and catalogue text. They are not automatically selected for bids. Only eligible sold USD hammer prices can be selected. Duplicate sale records are counted once, retaining all terms that found them. The search summary, including terms with no results, and each candidate's search terms persist in the saved analysis. Saved Artprice sources continue to participate in the combined bids.

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

Migration `0018_auctionemailbatch_auctionemailbatchitem_and_more` adds the shared active-batch constraint, send history, item attribution, and immutable send-time snapshots. Migration `0019_auctionwatchlot_bid_count` preserves Invaluable's zero/positive/missing bid-count distinction on synced lots. Migration `0021_auctionwatchlot_image_url` stores the public primary image used by the lot browser. Historical reminder migrations remain untouched.

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
10. Select a date with several lots, open **Browse all N lots**, and verify the image/fallback, counter, wraparound arrows, Left/Right, Home/End, Escape, and mobile layout.

## Automated verification

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe manage.py test secondstateapp.tests_calendar
.\.venv\Scripts\python.exe manage.py test
```

Tests mock Gmail delivery and make no external Gmail, Twilio, Artprice, Invaluable, or production website calls.
