# Artist Watchlist

Issue #33 replaces broad Auction Search with a local, bookmark-driven agenda. The desktop app visits selected public auction URLs from an exported browser bookmark file. Invaluable artist searches and Heritage sale catalogs are supported; LiveAuctioneers and Drouot remain visible at import time but report that their adapters are not available yet.

## Studio workflow

Studio uses the approved dark appearance: charcoal workspace, slate panels,
pale blue actions, and light text across all four tabs.

1. Click **Import Bookmarks HTML…** and choose your updated `ARTIST-LINKZ.html`.
2. Click **Sync to Calendar**. This reloads the chosen file, refreshes the selected artists, and uploads the resulting lots to the website calendar in one operation.

The app remembers the last imported file. If it is unavailable, it tries the project's `docs/ARTIST-LINKZ.html`, then the legacy shared-drive bookmark location. The default is the **ARTISTS INVALUABLE** folder and a **30-day** look-ahead. **Review imported artists** opens optional folder, artist, and date-range choices in the main workspace; **Done reviewing artists** returns to the agenda. A sync preserves current selections and includes newly added artists in the selected folders. The normal **Sync to Calendar** action uses HTTP with no AI processing or browser session, including when legacy browser environment settings are present.

The flat upcoming-lots list remains visible below the two actions. Select a lot to see its sale, time, bid, and cached-data status, or double-click to open its source page. **Stop** appears while work is running. **More** contains the detailed grouped agenda, Calendar preview, saved-page imports, and Markdown, CSV, and ICS exports. Results, Details, Preview Text, and Artist Watchlist share the Studio rounded tabs, icon buttons, cards, and status banners; the Results search, editing, upload, deletion, and export actions retain their existing behavior and order.

Source retrieval and website upload are reported separately. A successful upload of cached lots does not mean the source was refreshed. A blocked artist with no cached lots is named in the warning, so a newly imported artist cannot silently appear to have synced.

If source access fails before any lots are retrieved, the status says **No lots were available to upload**, shows the source error, and offers the Invaluable browser and saved-page recovery actions. No upload runs in that case. This differs from a successful search with no matching upcoming lots. An HTTP 202 access response is a source-access problem; **no cached lots** means the app has no earlier results to fall back to for that artist.

If the search results load but an optional lot-detail page fails, lots with a readable title and verified auction date still reach the calendar. Sync details identifies the failed detail request; missing details are not invented. A source-wide access block stops further detail requests during that refresh, and the next sync can try again. Undated results still require a readable detail page before they can be added.

When cached lots reach the website but a source fails, the banner says **Calendar updated; source refresh incomplete** and includes the first source error. **Sync details** keeps the full report available after the compact warning is dismissed, including all affected-watch messages, import notes, and the earliest/latest observation times for retained cached lots (in UTC). Missing observation times are labeled unavailable. A later completed sync replaces this report. The website counts describe uploaded records: **updated** counts existing records received, and **ended** includes previously ended or sold lots; neither means those changes were freshly discovered. Invaluable HTTP 202 access pages cannot supply fresh auction data. The banner offers **Retry with browser** and **Import saved Invaluable pages…**; saved-page imports are also under **More**.

For Invaluable errors, **Retry with browser** rereads the bookmarks and opens a separate Chrome (or Edge) profile to retrieve the selected artists, then uploads the results through the usual calendar sync. It reads the catalog response produced by the loaded search page itself, including that page's filters, rather than sending a separate reconstructed request from the browser. It waits up to two minutes for readable search results, including a confirmed zero-item result, instead of rejecting an initial HTTP 202 before the site's JavaScript can load. If a verification screen appears, complete it yourself in that window; the app never solves it or copies your regular browser profile. **Stop** or closing the browser cancels the refresh before upload. A blocked or timed-out attempt retains cached lots and remains labeled incomplete. A later normal sync still uses HTTP; browser retry is never silently enabled.

This public-search retry does not require a sold-price login. Its profile is `%LOCALAPPDATA%\SecondState\ArtistWatchlist\invaluable-public-browser`, separate from the older saved-login profile. Chrome or Edge and the optional packages in `requirements-watchlist-browser.txt` must be installed. A working search in your regular Chrome session does not guarantee that Invaluable will accept this separate session.

### Import saved Invaluable upcoming lots

Use **Import saved Invaluable pages…** in the status banner or under **More** to add upcoming lots from a readable local snapshot. Select the matching Invaluable artists in **Review imported artists**, then choose one or more `.html`, `.htm`, or supported `.json` files. The app rereads the bookmark file, preserves exclusions, and includes newly added artists in selected folders before importing. Imported lots are synced to the website calendar automatically, using the same settings as **Sync to Calendar**.

Saved HTML must contain the artist search's original URL and lot cards with full, verified sale dates. Save the loaded upcoming search results, not an access screen or an empty application shell. A normal **Ctrl+S** save is not sufficient if the page preserves only relative dates or dates without a year; the importer reports those limitations instead of inventing calendar dates. Use **Retry with browser** or the snapshot helper below for those pages. An HTML snapshot contains only the cards present when it was saved, so select every saved results page needed for the selected artists.

The advanced JSON format contains a public Invaluable artist-search `source_url`, the snapshot's `captured_at` time, and `results` objects containing catalog `hits`. These snapshots must originate from the corresponding loaded search page and match the selected artist filters. They contain public auction fields, without credentials or browser session exports; arbitrary API responses and access pages are not supported imports.

Saved snapshots reflect when they were captured. Importing them does not verify live access or mark absent lots ended. Other agenda lots and unobserved cached lots remain available, with cached labels retained. Source-access warnings remain in **Sync details** until a successful live refresh. Only the normalized lot fields and public artwork URLs are uploaded; the saved HTML/JSON, local filenames, cookies, and browser credentials stay local. For posted sold prices, use **Import saved sold results…** instead.

### Export a dated snapshot from your normal browser

If your regular browser loads the artist search but Studio's separate retry browser cannot, use [`invaluable_export_snapshot.js`](../scripts/invaluable_export_snapshot.js):

1. Open the bookmarked Invaluable artist search in your regular Chrome or Edge and wait for its lot cards.
2. Open **F12 → Console** and paste the complete helper file. A small snapshot panel appears.
3. Change **Sort By** once. When the panel confirms the artist and lot count, click **Download lot snapshot**.
4. Save each results page you need. After a full page navigation, paste the helper again; after an in-page change, wait for the new count before downloading.
5. In Studio, choose **Import saved Invaluable pages…** and select the downloaded `.json` files together. The import adds dated lots and syncs them to the calendar.

Each download covers the current results page, with its original total and exact source dates. The helper observes the page's own catalog responses and makes no auction-data requests. It exports only public lot fields, the artist-search URL, and the capture time; request parameters, account fields, and session tokens are excluded. A changed URL disables the previous download until matching results arrive. **Restore and close** removes the panel and restores the page's request handlers. Reloading the page also removes the helper.

## Heritage sales

1. Import your updated `ARTIST-LINKZ.html` with **Import Bookmarks HTML…**. The file stays on your computer.
2. Expand **Review imported artists** and enable the **HERITAGE** folder. **ARTISTS INVALUABLE** remains the default selection and can stay enabled.
3. Select the sale in **Artists / sales**. A bookmark such as **10-22 SALE** with `auction_name=8280` watches all lots returned by that catalog, including any non-print objects in the sale. The bookmark title identifies the sale selection; each lot keeps its own artist name.
4. Choose a look-ahead that includes the sale; the default is **30 days**.
5. Click **Sync to Calendar**. Results use the existing agenda, exports, cache, and website-calendar sync.

Heritage may reject direct requests with HTTP 403 even when a browser is logged in. The desktop app does not inherit your open browser session. If retrieval is blocked, save the sale's results pages using **Webpage, Complete** in that browser, select one Heritage sale in the watchlist, and click **Import Saved Heritage Pages…**. Keep the saved HTML and its matching companion folder together: for example, `10-22-HS.html` beside `10-22-HS_files`. Select all saved results pages for that sale together. This reads the saved HTML locally, retains other current agenda lots, and runs the same website-calendar sync. No login cookies or saved HTML are uploaded.

For the 151-lot catalog, switch to **List** view and choose **200** results per page before saving to capture it in one file, or save each results page in Gallery view. Wait until the lot cards and their images have loaded. A saved gallery page with 72 cards contains only those 72 lots; the importer reports partial coverage so the remaining pages can be added. Both layouts are supported. Gallery cards without their own date use the selected sale heading's single-day date. Dates without session times remain all-day / time unverified; the importer does not invent a closing time. Starting bids are displayed as **No bids**, separately from actual current bids.

Saved artwork thumbnails are matched to each Heritage lot number and read only from that HTML file's companion folder. They are converted to JPEG with metadata removed, at most 1600 pixels per side and 512 KiB each, before the normalized image pixels are cached and synced. Local file paths are never sent as auction URLs. Public lazy-image URLs remain a fallback where the saved HTML preserves them. Missing, unreadable, or placeholder thumbnails produce an import notice; save the complete page again to supply the missing images. The website must run the matching calendar-image update before it can accept these saved thumbnails. Re-import the saved page and sync again after updating both the desktop app and website.

### Save larger Heritage images

The optional [`heritage_prepare_images.js`](../scripts/heritage_prepare_images.js) helper prepares larger primary images before saving a catalog. Run it in your browser's DevTools console on the live Heritage sale results page, such as the page whose URL contains `auction_name=8280`. It works on the lot cards currently loaded in that page.

1. Choose **List** and **200** results per page, or prepare and save each results page separately. Wait for the catalog to load.
2. Open DevTools with **F12**, select **Console**, and run the complete contents of `scripts/heritage_prepare_images.js`.
3. Wait for the on-page banner to finish. It reports **X/Y images ready**, failures, and any larger originals retained. The helper requests Heritage's own product images at up to **612 × 600**, with four loads at a time, and checks decoded pixel dimensions. Sources may provide smaller originals; a request succeeds only if it actually increases the available pixels without reducing either dimension.
4. Once ready, press **Ctrl+S** and select **Webpage, Complete**. Keep the resulting HTML and its matching `_files` folder together. In Artist Watchlist, select the Heritage sale and use **Import Saved Heritage Pages…**, then check the website-sync result.
5. Use **Restore originals** when you are done. During loading, **Stop and restore originals** cancels preparation and restores the original image attributes. Save the prepared page before restoring.

The helper updates the existing catalog images so the browser can include them in the saved page. A separate image wall or preview in a shadow DOM is not a reliable substitute for **Webpage, Complete**. Failed images retain their original source; restore and rerun to retry them. The helper leaves larger images in place and does not change bids, bid forms, or navigation. It does not read cookies, browser storage, or account details; it uses ordinary image loads from recognized Heritage CDN URLs, without `fetch`, canvas extraction, or CORS workarounds. If an image request is refused, it reports that image as failed.

Saved pages are snapshots: their bids and availability reflect when you saved them. Pages from a different sale are rejected. A partial set of pages never marks missing lots ended. Retained cached lots can therefore show older bids and availability than the newly imported page; a successful calendar sync does not make those observations current. Save and import updated pages through **More → Import saved Heritage pages…** when you need newer bids. Re-import the same pages to retry their upload without a live refresh, or use **Sync to Calendar** to attempt a fresh source check and upload.

If the local import succeeds but website sync is not configured, the app explains the missing settings and leaves **Sync to Calendar** clickable. Put the website's existing `CATALOG_API_KEY` in the ignored project-root `.env` (alongside `SECONDSTATE_BASE_URL=https://secondstate.art` if needed). A sync retry reloads newly added settings. Live source-access warnings, such as Heritage HTTP 403, are separate from website-sync configuration.

## Architecture

```text
local bookmark HTML
  -> selected folders + explicit domain allowlist
  -> Invaluable public catalog JSON / Heritage catalog HTML adapters
  -> normalized lot records
  -> local SQLite content-hash cache and diff
  -> optional compact ambiguous-record enrichment
  -> date/artist agenda + Markdown/CSV/ICS exports
  -> private website calendar sync
```

The implementation is split by responsibility:

- `catalogapp/bookmark_watchlist.py`: Netscape bookmark parsing, nested URL decoding, folder/domain filtering, artist/sale labels, and URL deduplication.
- `catalogapp/watchlist_adapters.py`: adapter interface plus deterministic Invaluable catalog-result, card, embedded JSON, detail, and pagination parsing. Invaluable's `/search` page is a JavaScript shell, so live refreshes use the same public `/catResults` JSON request as the page itself. Compatible selected artists are combined into an OR-facet request and split back into their individual bookmark memberships locally.
- `catalogapp/watchlist_fetch.py`: conservative HTTP retries/rate limiting and an explicit opt-in Playwright profile fallback.
- `catalogapp/watchlist_models.py`: stable normalized lot schema and local duplicate markers.
- `catalogapp/watchlist_cache.py`: SQLite lot, membership, source-run, and AI-enrichment caches.
- `catalogapp/watchlist_service.py`: incremental refresh, detail-fetch decisions, ended-item detection, horizons, and efficiency metrics.
- `catalogapp/watchlist_saved_pages.py`: local saved Heritage results import, sale validation, and cache updates without treating partial snapshots as complete catalogs.
- `catalogapp/watchlist_invaluable_pages.py`: local Invaluable upcoming search snapshots, selected-artist validation, verified date checks, and cache updates that retain unobserved lots.
- `catalogapp/watchlist_images.py`: lot-to-thumbnail matching, companion-folder confinement, and bounded JPEG normalization without source image metadata.
- `catalogapp/watchlist_enrichment.py`: optional strict structured-output batching for ambiguous compact records.
- `catalogapp/watchlist_exports.py`: agenda Markdown, CSV, and RFC 5545 ICS generation.
- `catalogapp/watchlist_sync.py`: authenticated upload of normalized results to the staff-only website calendar.
- `catalogapp/watchlist_ui.py`: the Studio import/sync workflow, optional folder/artist/sale review, saved-page imports, agenda/calendar views, and exports. Legacy browser handlers remain in this module but have no visible controls.
- `catalogapp/studio_palette.py`: the approved dark Studio colors shared by widgets and drawn assets.
- `catalogapp/studio_theme.py`: shared Studio fonts, table styles, and button styles for the desktop app.
- `catalogapp/studio_assets.py`: locally drawn, antialiased line icons and stretchable rounded surfaces. Uses the existing Pillow dependency; no external asset downloads.

## Local data and privacy

- The bookmark file is read locally and is never copied into the repository or website database.
- The complete bookmark HTML and full scraped pages are never sent to OpenAI.
- Only entries in a user-selected folder and the explicit `invaluable.com`, `liveauctioneers.com`, `drouot.com`, or `ha.com` allowlist are imported. Private Google Drive and unrelated URLs are rejected.
- Normal HTTP retrieval is the default. Only **Retry with browser** launches the separate public-search browser. The dormant login connection implementation and its local profile under `%LOCALAPPDATA%\SecondState\ArtistWatchlist\invaluable-browser` are retained; browser credentials are never uploaded. The older environment-based Playwright implementation also remains in the codebase.
- The fetchers do not enter credentials, solve CAPTCHAs, bypass paywalls, or work around HTTP 401/403/429 controls.
- Local settings and cache data live under `%LOCALAPPDATA%\SecondState\ArtistWatchlist`, outside the repository.
- Studio sync always uses zero-AI mode. The retained enrichment implementation also requires `OPENAI_WATCHLIST_ENRICHMENT_ENABLED=1` when used separately.
- Enrichment sends only allowlisted normalized fields. URLs, bookmark data, page HTML, cookies, and credentials are excluded.
- Website calendar sync sends normalized sale/lot fields, the source's public primary-image URL when available, and sanitized artwork thumbnails imported from a saved catalog. Original image metadata, local paths, bookmark files, page HTML, cookies, cache internals, and browser credentials are excluded from the uploaded records. The configured catalog API key is used only to authenticate the sync request.
- The Responses API request has no tools and uses a strict JSON schema. Ambiguous records are batched and cached by deterministic content hash.

Optional local environment settings:

```dotenv
OPENAI_WATCHLIST_ENRICHMENT_ENABLED=0
OPENAI_WATCHLIST_MODEL=gpt-5-mini
OPENAI_WATCHLIST_MAX_RECORDS_PER_BATCH=50
WATCHLIST_USE_PLAYWRIGHT=0
WATCHLIST_PLAYWRIGHT_PROFILE=
```

## Incremental behavior and metrics

Each lot is keyed by source plus source lot ID, falling back to its canonical URL. The cache stores a search-card hash and a normalized visible-content hash. An unchanged complete card is served from cache without fetching its detail page. New, changed, or still-incomplete cards may retrieve details. Successfully refreshed bookmark memberships that disappear are marked ended.

If a source is temporarily unavailable, the refresh keeps the last known active lots for that bookmark in the agenda and reports that cached data is being shown. It never marks lots ended from an incomplete or failed source refresh.

When adding an artist, import the updated bookmark HTML and use **Sync to Calendar**. Subsequent syncs reread that file, preserving exclusions and selecting newly added artists in the chosen folders. If Invaluable returns an access page (HTTP 202/403), existing artists can still have cached lots to upload while a new artist has none. The source report names watches with no cached lots and remains available after an upload or saved-page import. **Retry with browser** can retrieve the data produced by a readable search page; **Import saved Invaluable pages…** can add verified lots from a saved snapshot even while automatic HTTP refresh is unavailable. Neither action treats an access page as auction data.

The controller retains these metrics for diagnostics:

- pages fetched;
- cache hits;
- new, changed, and ended lots;
- AI-enriched records;
- input, output, and total token usage.

Invaluable's `currentBid` and `bidCount` values are normalized separately so the desktop agenda can distinguish a live current bid from **No bids** and an unavailable bid field from **N/A**. Bid-count changes participate in the content hash and therefore appear as changed lots on refresh.

## Calendar behavior

### Posted sold prices

After an auction, **Sync to Calendar** rechecks previously watched Invaluable lot detail pages for up to 30 days after their source date/time, including lots that have disappeared from upcoming searches or were already marked ended. A publicly visible posted result such as **Sold: $11,000 USD** is stored separately from the estimate and current bid, appears in the desktop **Current bid / sold** column and Markdown/CSV exports, and is uploaded by calendar sync. The website displays the result in the catalog, day list, lot browser, and research view. A missing lot or its last bid alone never counts as a sold price. Confirmed sold lots remain in calendar history and are excluded from upcoming ICS events and reminders. Later syncs that omit the result preserve the saved price.

Some Invaluable pages show **Sold: Log in to view** to public requests. Studio reports that these prices are unavailable and retains existing estimates and results. Ended lots without a verified price display **Sale ended · Sold price unavailable**. Access challenges stop further result requests for that refresh. Previously ended and sold lots remain available when the upcoming catalog fails, and an independent detail check may still update previously ended lots when the source permits access.

The old **Connect Invaluable**, Chrome profile picker, and **Use saved login** controls have been removed. Their implementation remains in `watchlist_ui.py`, `watchlist_browser.py`, and `watchlist_chrome.py`, along with `requirements-watchlist-browser.txt`, for possible future development. The two-step Studio workflow does not invoke these handlers or enumerate Chrome profiles.

As a manual fallback, save the individual sold lot page as HTML from your signed-in browser and use **More → Import saved sold results…** with its Invaluable artist selected. The importer matches the saved page to an existing watched lot and automatically syncs its posted result; it also works for older tracked lots outside the 30-day live recheck period. Only normalized result fields are imported. Page HTML, login cookies, and local filenames are not uploaded. Pages without an explicit visible sold amount or without a matching selected watch are reported and leave existing data intact.

The bookmark file supplies artist searches, while each lot's detail page supplies its final result.

ICS output defaults to one event per auction sale. Matched artists and lots are grouped in the description. A timezone-aware source time is converted to UTC. A source date without a time becomes an all-day event and the description marks the time as unverified. Event-per-lot and reminders are supported by the export function but are intentionally not the noisy UI default.

The private web calendar at `/calendar/` is populated by **Sync to Calendar** or a saved-page import. A selected date with lots exposes **Browse all N lots**, which opens a single modal viewer with the current lot's primary image, details, counter, progress, wraparound previous/next controls, and keyboard navigation. Website staff can explicitly select lots with saved Artprice links for the shared Email Tray; sync never selects, deselects, or sends them. See [`auction-calendar.md`](auction-calendar.md) for authentication, deployment, and Gmail setup.

## Migration note

Historical migration `0012_auctionsearchjob.py` is retained because it may already be applied. New migration `0013_delete_auctionsearchjob.py` safely removes that deployed model. The runtime model, imports, routes, views, polling helpers, environment constants, and broad-search tests are deleted.

## Manual verification

1. Run `python manage.py migrate` and confirm migration `0013_delete_auctionsearchjob` applies.
2. Start the catalog desktop app and confirm the notebook shows **Artist Watchlist**, with no **Auction Search** tab.
3. Export a small synthetic or test browser bookmark HTML file. Do not add a real bookmark export to Git.
4. Click **Import Bookmarks HTML…** and confirm `ARTISTS INVALUABLE` is selected by default.
5. Confirm private/unrelated domains do not appear and source/artist/sale counts are shown before refresh. Enable a synthetic **HERITAGE** folder and confirm its sale title appears separately from artist names.
6. Expand **Review imported artists**, select a small artist subset and look-ahead, then click **Sync to Calendar**.
7. Confirm status distinguishes website upload from any source failures; use **Stop** during a refresh once. Add an artist to the chosen HTML file and confirm the next sync includes it while preserving earlier exclusions.
8. Refresh the same fixture again and confirm unchanged complete lots produce cache hits and no repeated detail or AI request.
9. Inspect Agenda and Calendar views, then export Markdown, CSV, and ICS. Import the ICS into a temporary calendar and confirm one event per sale.
10. Verify upload, website listing edit/delete/reorder, gallery rendering, and artwork description generation still work.

## Automated verification

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe -m compileall -q catalogapp secondstateapp
node --test scripts/invaluable_export_snapshot.test.js
```

The synthetic tests cover bookmark safety, repeated decoding, adapters, pagination, retries, caching/diffs, duplicate marking, timezone/all-day ICS behavior, zero-AI mode, strict compact batching, enrichment caching, legacy removal, and preserved website regressions. No test contacts an auction site or OpenAI.

## Invaluable troubleshooting

A successful `GET /search` is not proof that auction data was returned: Invaluable currently responds with HTTP 200 and an empty JavaScript application shell. The live adapter therefore posts only the bookmarks' public artist/category/search filters to `/catResults`, combines compatible artist facets to reduce request volume, validates the JSON schema, and reports a source error if the endpoint returns HTML or an unexpected response. This prevents an empty shell from being recorded as a successful zero-result refresh. A temporary 401/403/429 is not bypassed; the agenda retains last-known cached lots and the user can retry later.
