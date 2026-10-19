# Artist Watchlist

Issue #33 replaces broad Auction Search with a local, bookmark-driven agenda. The desktop app visits selected public auction URLs from Chrome or Edge bookmarks or an exported bookmark file. Invaluable artist searches and Heritage sale catalogs are supported; LiveAuctioneers and Drouot remain visible at import time but report that their adapters are not available yet.

## Studio workflow

### Add or sync one artist

Use **Artists** beside **Upcoming lots** to see one row per artist and source, including artists with no saved lots. **Scan artists** rereads your connected bookmarks, loads saved Calendar records, and shows artists and known lots that still need to be added. It does not contact auction sites or upload lots. The comparison checks Calendar identities across all dates, including source lot IDs and canonical source URLs, so an older Calendar record or a different fallback ID does not appear new.

If you added an artist to a separate bookmark export, choose **Scan HTML…** in the Artists table or **More → Scan bookmarks HTML…** once. Studio remembers that file and merges its artist links into your saved watchlist while retaining your browser connection, folder choices, and exclusions. Subsequent **Scan artists** reads the same file again. A file inside the repository also has a relative path hint so it can be found in a clone at a different location. If the file moves, previously saved artists remain available. Choose the HTML file again to select its new location.

The two sync controls are **Sync all** and **Sync selected**. Select an artist with missing lots, or select one of their missing lots in Upcoming lots, then click **Sync selected**. Only that artist is checked, and only their lots absent from the Calendar are uploaded. The upload rechecks Calendar identities immediately beforehand; a failed comparison leaves the upload pending. Artists already represented by all their known lots are not eligible. A new artist with no local or Calendar lots remains available for an initial source check. Individual rows have no sync buttons.

If Invaluable blocks this artist, **Use my browser for artist…** opens the snapshot helper for that artist only. **More → Use my browser for Invaluable…** also provides the helper. An artist-scoped snapshot import adds only that artist's missing lots. Scanning bookmarks cannot bypass a source access failure; blocked searches remain distinct from confirmed empty searches.

### Use the watchlist on another PC

Git carries the application and tracked HTML files; each PC's browser profile, local settings, and SQLite cache stay on that PC. Configure the second clone's ignored `.env` with the same website `CATALOG_API_KEY` and `SECONDSTATE_BASE_URL=https://secondstate.art`, then start the updated app. Studio automatically loads the shared public artist registry, public Artprice links, saved source-check coverage, and recent Calendar lots. **More → Load from Calendar** repeats that read without contacting auction sites. The default project bookmark file is `docs/artist-links.html`.

The shared registry is additive: a smaller or older PC cannot remove another PC's artists. Existing local folder choices and artist exclusions remain local; previously unknown shared artists use their saved enabled state. Scans and completed syncs share the curated public registry. Source coverage keeps its original check time, and Calendar lots keep their original source observation times; a download is not a fresh source check. The download includes the previous seven Calendar days through the selected three- or seven-day horizon, plus undated lots, and excludes superseded listings. Local lots absent from the download are retained. A failed Calendar connection leaves local data available.

### Update the selected watchlist

Studio uses the approved dark appearance: charcoal workspace, slate panels,
pale blue actions, and light text across all four tabs.

1. Set up your watchlist once under **Manage artists → Use browser bookmarks…** and choose your Chrome or Edge profile. Studio reads that profile's bookmark file, keeps the artist list on this computer, and remembers your selections and folders. **Import Bookmarks HTML…** remains available for an exported file.
2. Click **Sync all** for a full refresh and website upload of the watches enabled in **Manage artists**. This can update existing Calendar lots. Studio rereads the selected browser's current bookmarks, adds new artists in selected folders, and updates matched Artprice research links. Browser additions merge into the saved list; artists absent from that browser stay saved and can be excluded in **Manage artists**. With an HTML source, Studio rereads that export, so browser changes require a fresh export. If a source moves or disappears, the saved list remains usable. If Invaluable returns an HTTP 202 access page, Studio automatically opens a visible recovery browser for the affected searches before uploading. Keep it open while the results load; complete any verification yourself, or use **Stop** to cancel.
3. Use **View artist coverage** to see each artist's last catalog check, known-lot count, and whether the search is verified, verified with no upcoming lots, partial, blocked, or still pending. Cached lots alone do not count as a verified search. A confirmed empty search is different from an access failure.
4. For an individual addition, use **Scan artists**, select an eligible artist, and choose **Sync selected**. Saved-page imports and the ordinary-browser snapshot helper remain under **More** when source retrieval fails. **Recover pending**, **Retry with browser**, and per-row sync buttons are not displayed; automatic HTTP 202 browser recovery remains active.

The saved artist registry and selections live beside the cache under `%LOCALAPPDATA%\SecondState\ArtistWatchlist`. On first setup, Studio can use the remembered source, the project's `docs/artist-links.html`, or the legacy shared-drive location, then merge the shared Calendar data. The default is the **ARTISTS INVALUABLE** folder and a **seven-day** look-ahead, with a shorter three-day option. Older 14/30-day Studio settings migrate to seven days. **Manage artists** opens folder, artist, and date-range choices; **Done managing** returns to the agenda. Both sync controls start with HTTP and no AI processing. Only an Invaluable catalog HTTP 202 starts automatic browser recovery. Legacy browser environment settings remain ignored by Studio.

Add an artist's Invaluable search to **ARTISTS INVALUABLE** and their Artprice artist page to **ARTPRICE** in the selected browser profile. Allow the browser to finish saving, then click **Sync all**. An Artprice bookmark supplies a research link; an Invaluable search bookmark supplies the auction watch. Studio reads both Chrome's local and account bookmark stores when present, including profiles that migrate between the two. It does not modify browser bookmarks or read login sessions.

Studio connects to one browser profile at a time. Profile names come from the browser's existing profile metadata. The main panel shows the browser and readable profile name; the chooser also shows Chrome's internal folder identifier (such as `Profile 9`) to distinguish profiles with identical names. That number is not a count of connected profiles. **Manage artists → Use browser bookmarks…** changes the single selected connection. A profile-name change in Chrome is reflected when Studio next reads the source; the selected folder stays the same.

The Invaluable catalog request itself includes the look-ahead cutoff, so seven days reduces source data and pagination rather than only hiding later results. A completed seven-day search does not end cached lots outside that window. Coverage reports the checked window and becomes pending again on a later day or when the requested period expands. Newly added artists with no cached lots are checked first. Existing website records beyond the new window remain saved.

The flat upcoming-lots list remains visible below the saved-watchlist controls. Select a lot to see its sale, time, bid, and cached-data status, or double-click to open its source page. **Stop** appears while work is running. **More** contains the detailed grouped agenda, Calendar preview, artist coverage, saved-page imports, and Markdown, CSV, and ICS exports. Results, Details, Preview Text, and Artist Watchlist share the Studio rounded tabs, icon buttons, cards, and status banners; the Results search, editing, upload, deletion, and export actions retain their existing behavior and order.

Source retrieval and website upload are reported separately. A successful upload of cached lots does not mean the source was refreshed. A blocked artist with no cached lots is named in the warning, so a newly imported artist cannot silently appear to have synced.

Normal Invaluable updates use groups of at most eight artists, prioritizing unfinished watches. Each group or individual search has its own pagination allowance. If a later page fails, the readable pages already retrieved still reach the calendar. Unobserved cached lots keep their original observation times and remain labeled **Cached**. An incomplete search never marks missing lots ended or counts as a successful source refresh. An access block stops further Invaluable requests for that run; ordinary request failures affect only their search group. **Sync details** reports the partial coverage. **Sync all** checks all enabled watches again, including previous zero-result searches. Source access errors remain in the persistent report without opening a repeated warning dialog for every run.

If source access fails before any lots are retrieved, the status says **No lots were available to upload**, shows the source error, and offers the Invaluable browser and saved-page recovery actions. No upload runs in that case. This differs from a successful search with no matching upcoming lots. An HTTP 202 access response is a source-access problem; **no cached lots** means the app has no earlier results to fall back to for that artist.

If the search results load but an optional lot-detail page fails, lots with a readable title and verified auction date still reach the calendar. Sync details identifies the failed detail request; missing details are not invented. A source-wide access block stops further detail requests during that refresh, and the next sync can try again. Undated results still require a readable detail page before they can be added.

When cached lots reach the website but a source fails, the banner says **Calendar updated; source refresh incomplete** and includes the first source error. **Sync details** keeps the full report available after the compact warning is dismissed, including all affected-watch messages, import notes, and the earliest/latest observation times for retained cached lots (in UTC). Missing observation times are labeled unavailable. A later completed sync replaces this report. The website counts describe uploaded records: **updated** counts applied existing records, and **ended** includes previously ended or sold lots; neither means those changes were freshly discovered. An older cached observation from another PC cannot overwrite a newer saved source observation. Invaluable HTTP 202 access pages cannot supply fresh auction data. The ordinary-browser helper and saved-page imports remain under **More**.

Automatic browser recovery opens a separate Chrome (or Edge) profile once per run when an Invaluable catalog request returns HTTP 202. Searches already completed over HTTP retain their fresh observations, while affected searches continue in the browser. It reads the catalog response produced by the loaded search page itself, including that page's filters, rather than sending a separate reconstructed request from the browser. It waits up to two minutes for readable search results, including a confirmed zero-item result, instead of rejecting an initial HTTP 202 before the site's JavaScript can load. If a verification screen appears, complete it yourself in that window; the app never solves it or copies your regular browser profile. An **Access Denied** security-policy screen ends browser recovery promptly. Closing the retry window also ends browser recovery without cancelling the Calendar upload: available fresh and cached lots continue through the chosen sync's upload rules, with a source warning. Use the ordinary-browser helper under **More** for remaining searches. Only **Stop** cancels the whole sync before upload. A blocked or timed-out attempt retains cached lots and remains labeled incomplete. Each normal sync starts with HTTP again.

Browser recovery focuses on the calendar: search cards with a usable title and verified auction date are imported without optional lot-detail visits. Previously saved details and posted sold results are retained; recovery does not check historical sold-price pages. Undated or unreadable cards still require a usable detail page. This avoids a blocked optional detail request interrupting otherwise readable artist searches. A recovered complete search clears its original HTTP 202 warning; incomplete searches keep their warning and cached lots. Automatic recovery does not retry HTTP 401, 403, or 429 responses.

This public-search retry does not require a sold-price login. Its profile is `%LOCALAPPDATA%\SecondState\ArtistWatchlist\invaluable-public-browser`, separate from the older saved-login profile. Chrome or Edge and the optional packages in `requirements-watchlist-browser.txt` must be installed. A working search in your regular Chrome session does not guarantee that Invaluable will accept this separate session.

### Import saved Invaluable upcoming lots

Use **More → Use my browser for Invaluable…** for a guided snapshot workflow, or **More → Import saved Invaluable pages…** to add upcoming lots from existing local snapshots. Select the matching Invaluable artists in **Manage artists**, then choose one or more `.html`, `.htm`, or supported `.json` files. The app rereads the bookmark file, preserves exclusions, and includes newly added artists in selected folders before importing. Imported lots are synced to the website calendar automatically. Artist-scoped imports keep the selected artist's missing-lots-only upload rule.

Saved HTML must contain the artist search's original URL and lot cards with full, verified sale dates. Save the loaded upcoming search results, not an access screen or an empty application shell. A normal **Ctrl+S** save is not sufficient if the page preserves only relative dates or dates without a year; the importer reports those limitations instead of inventing calendar dates. Use the snapshot helper below for those pages. An HTML snapshot contains only the cards present when it was saved, so select every saved results page needed for the selected artists.

The advanced JSON format contains a public Invaluable artist-search `source_url`, the snapshot's `captured_at` time, and `results` objects containing catalog `hits`. These snapshots must originate from the corresponding loaded search page and match the selected artist filters. They contain public auction fields, without credentials or browser session exports; arbitrary API responses and access pages are not supported imports.

Saved snapshots reflect when they were captured. Importing them does not verify live access or mark absent lots ended. Other agenda lots and unobserved cached lots remain available, with cached labels retained. Source-access warnings remain in **Sync details** until a successful live refresh. Only the normalized lot fields and public artwork URLs are uploaded; the saved HTML/JSON, local filenames, cookies, and browser credentials stay local. For posted sold prices, use **Import saved sold results…** instead.

### Export a dated snapshot from your normal browser

If your regular browser loads the artist search but Studio's automatic recovery browser cannot, choose **More → Use my browser for Invaluable…**. It lists selected artist searches with unfinished ones first, opens or copies their links, and copies [`invaluable_export_snapshot.js`](../scripts/invaluable_export_snapshot.js) for you. **Open artist search** uses your default browser; use **Copy artist link** if you need a different browser profile. The steps are:

1. Open the bookmarked Invaluable artist search in your regular Chrome or Edge and wait for its lot cards.
2. Click **Copy snapshot helper** in Studio, then open **F12 → Console** in the loaded search tab, paste the helper and press Enter. A small snapshot panel appears.
3. Change **Sort By** once. When the panel confirms the artist and lot count, click **Download lot snapshot**.
4. Save each results page you need. After a full page navigation, paste the helper again; after an in-page change, wait for the new count before downloading.
5. In Studio, click **Import snapshots and update Calendar** and select the downloaded `.json` files together. The import adds dated lots and syncs them to the calendar. **More → Import saved Invaluable pages…** also remains available.

Each download covers the current results page, with its original total and exact source dates. The helper observes the page's own catalog responses and makes no auction-data requests. It exports only public lot fields, the artist-search URL, and the capture time; request parameters, account fields, and session tokens are excluded. A changed URL disables the previous download until matching results arrive. **Restore and close** removes the panel and restores the page's request handlers. Reloading the page also removes the helper.

## Heritage sales

1. Import your updated `artist-links.html` with **Import Bookmarks HTML…**. The file stays on your computer.
2. Expand **Manage artists** and enable the **HERITAGE** folder. **ARTISTS INVALUABLE** remains the default selection and can stay enabled.
3. Select the sale in **Artists / sales**. A bookmark such as **10-22 SALE** with `auction_name=8280` watches all lots returned by that catalog, including any non-print objects in the sale. The bookmark title identifies the sale selection; each lot keeps its own artist name.
4. Choose the **seven-day** or shorter **three-day** look-ahead. A later sale will enter the routine sync window when its date approaches.
5. Click **Sync all**. Results use the existing agenda, exports, cache, and website-calendar sync.

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

Saved pages are snapshots: their bids and availability reflect when you saved them. Pages from a different sale are rejected. A partial set of pages never marks missing lots ended. Retained cached lots can therefore show older bids and availability than the newly imported page; a successful calendar sync does not make those observations current. Save and import updated pages through **More → Import saved Heritage pages…** when you need newer bids. Re-import the same pages to retry their upload without a live refresh, or use **Sync all** to attempt a fresh source check and upload.

If the local import succeeds but website sync is not configured, the app explains the missing settings and leaves **Sync all** clickable. Put the website's existing `CATALOG_API_KEY` in the ignored project-root `.env` (alongside `SECONDSTATE_BASE_URL=https://secondstate.art` if needed). A sync retry reloads newly added settings. Live source-access warnings, such as Heritage HTTP 403, are separate from website-sync configuration.

## Doyle and Phillips sale catalogs

Doyle `/auction/search/?au=...` and Phillips `/auction/<code>/browse` bookmarks are whole-sale watches. Every catalog artist is included, even without a separate Invaluable or Artprice bookmark. **More → Import saved Doyle / Phillips pages…** imports the selected sale's saved HTML and artwork images from its matching `_files` directories. Select one sale at a time; multiple Doyle catalog pages can be selected together.

The Phillips adapter assigns each lot to its published session, including sales spanning multiple dates. Doyle saves that only show the auction date remain date-only; if the catalog omits artwork titles, the Calendar displays `Lot N`. Missing bids and sale times are not inferred. Saved files retain their embedded source timestamp where available, with file modification time as fallback. Partial imports never end missing lots or overwrite newer cached observations. Normal refreshes use the same adapters and report source-access or incomplete-catalog failures while keeping cached lots.

For a reproducible import, validate first with `python scripts/import_sale_catalogs.py --bookmarks docs/artist-links.html --source Doyle --pages docs/doyle/DOYLE-1020-1.html docs/doyle/DOYLE-1020-2.html`. Use `--source Phillips --pages docs/phillips/PHILLIPS-1022.html` for Phillips. Add `--sync` to upload through the existing authenticated Calendar API, `--cache <path>` to retain local normalized records, or `--report <path>` to save an audit without image pixels. The command prints exact counts, sessions, image coverage, and title availability before any upload.

Calendar research controls reuse `artpricelinkgen.url_builder.ArtpriceURLBuilder`. Existing Artprice artist bookmarks and the generated public artist registry scope artwork searches to a known numeric artist ID, including whole-sale imports. Saved Invaluable artist searches are available alongside them. Artists without a known ID get an artist-name search and a clearly labeled title-only search; `Lot N` placeholders do not create a meaningless title search. These are research suggestions, not verified lot matches, and do not replace staff-saved URLs or enable email selection automatically. The `backfill_artprice_artist_links` management command reuses the generator's conservative resolver to fill missing artist links; see [Calendar backfill instructions](auction-calendar.md#fill-missing-artprice-artist-links).

## Architecture

```text
local Chrome/Edge bookmarks or bookmark HTML
  -> selected folders + explicit domain allowlist
  -> Invaluable public catalog JSON / Heritage, Doyle, Phillips catalog adapters
  -> normalized lot records
  -> local SQLite content-hash cache and diff
  -> optional compact ambiguous-record enrichment
  -> date/artist agenda + Markdown/CSV/ICS exports
  -> private website calendar sync
```

The implementation is split by responsibility:

- `catalogapp/bookmark_watchlist.py`: Netscape bookmark parsing, nested URL decoding, folder/domain filtering, artist/sale labels, and URL deduplication.
- `catalogapp/watchlist_bookmark_source.py`: read-only Chrome/Edge profile discovery and bookmark JSON loading, plus shared public-URL validation and Artprice matching for browser and HTML sources.
- `catalogapp/watchlist_registry.py`: validated, atomic storage of the normalized artist list and public research links, independent of the original bookmark export.
- `catalogapp/watchlist_paths.py`: safe repository-relative HTML hints that work when another clone has a different local path.
- `catalogapp/watchlist_shared.py`: authenticated sharing of public watch configuration and download of Calendar lots and source coverage, preserving observation times and newer local records.
- `secondstateapp/watchlist_shared_views.py`: shared watchlist merge and paginated recent-lot download, plus all-date source-ID and canonical-URL identities for missing-lot comparison.
- `catalogapp/watchlist_coverage.py`: per-artist catalog coverage, distinct from cached lot counts and optional detail-page results.
- `catalogapp/watchlist_adapters.py`: adapter interface plus deterministic Invaluable catalog-result, card, embedded JSON, detail, and pagination parsing. Invaluable's `/search` page is a JavaScript shell, so live refreshes use the same public `/catResults` JSON request as the page itself. Compatible selected artists are combined into bounded OR-facet groups and split back into their individual bookmark memberships locally. Successfully retrieved pages survive later-page failures, with incomplete coverage and source errors carried alongside the records.
- `catalogapp/watchlist_fetch.py`: conservative HTTP retries/rate limiting and an explicit opt-in Playwright profile fallback.
- `catalogapp/watchlist_browser.py`: visible browser catalog recovery, matching response validation, and cancellation, plus the dormant signed-in result workflow.
- `catalogapp/watchlist_browser_helper.py`: guided snapshot capture from the user's ordinary browser and handoff to the existing local import.
- `catalogapp/watchlist_models.py`: stable normalized lot schema and local duplicate markers.
- `catalogapp/watchlist_cache.py`: SQLite lot, membership, source-run, and AI-enrichment caches.
- `catalogapp/watchlist_service.py`: incremental refresh, lazy HTTP 202 browser recovery, detail-fetch decisions, ended-item detection, horizons, and efficiency metrics.
- `catalogapp/watchlist_saved_pages.py`: local saved Heritage results import, sale validation, and cache updates without treating partial snapshots as complete catalogs.
- `catalogapp/doyle.py`, `catalogapp/phillips.py`, and `catalogapp/watchlist_sale_pages.py`: whole-sale catalogs, source/session dates, saved artwork images, and snapshot imports for Doyle and Phillips.
- `catalogapp/watchlist_invaluable_pages.py`: local Invaluable upcoming search snapshots, selected-artist validation, verified date checks, and cache updates that retain unobserved lots.
- `catalogapp/watchlist_images.py`: lot-to-thumbnail matching, companion-folder confinement, and bounded JPEG normalization without source image metadata.
- `catalogapp/watchlist_enrichment.py`: optional strict structured-output batching for ambiguous compact records.
- `catalogapp/watchlist_exports.py`: agenda Markdown, CSV, and RFC 5545 ICS generation.
- `catalogapp/watchlist_sync.py`: authenticated upload of normalized results to the staff-only website calendar.
- `catalogapp/watchlist_ui.py`: the saved Studio watchlist workflow, artist coverage and recovery, optional folder/artist/sale review, saved-page imports, agenda/calendar views, and exports. Legacy browser handlers remain in this module but have no visible controls.
- `catalogapp/studio_palette.py`: the approved dark Studio colors shared by widgets and drawn assets.
- `catalogapp/studio_theme.py`: shared Studio fonts, table styles, and button styles for the desktop app.
- `catalogapp/studio_assets.py`: locally drawn, antialiased line icons and stretchable rounded surfaces. Uses the existing Pillow dependency; no external asset downloads.

## Local data and privacy

- The bookmark file is read locally and is never copied into the repository or website database.
- The complete bookmark HTML and full scraped pages are never sent to OpenAI.
- Only entries in a user-selected folder and the explicit `invaluable.com`, `liveauctioneers.com`, `drouot.com`, `ha.com`, `doyle.com`, or `phillips.com` allowlist are imported. Private Google Drive and unrelated URLs are rejected.
- Normal HTTP retrieval is the default. Automatic Invaluable catalog HTTP 202 recovery launches the separate public-search browser. The dormant login connection implementation and its local profile under `%LOCALAPPDATA%\SecondState\ArtistWatchlist\invaluable-browser` are retained; browser credentials are never uploaded. The older environment-based Playwright implementation also remains in the codebase.
- The fetchers do not enter credentials, solve CAPTCHAs, bypass paywalls, or work around HTTP 401/403/429 controls.
- Local settings and cache data live under `%LOCALAPPDATA%\SecondState\ArtistWatchlist`, outside the repository.
- The authenticated `/calendar/watchlist/` endpoint stores only curated public bookmark fields, public Artprice links, and dated source-check coverage. Browser profiles, source file paths, API keys, cookies, original bookmark files, and raw source-error details are excluded. Each PC supplies its own ignored `.env` and local browser connection.
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

When adding an artist to the connected browser, use **Sync all** after the browser has saved the bookmark. Studio rereads the current file, preserving exclusions and selecting newly added artists in the chosen folders. For an HTML source, first export the updated bookmarks to the chosen file. If Invaluable returns an access page (HTTP 202/403), existing artists can still have cached lots to upload while a new artist has none. The source report names watches with no cached lots and remains available after an upload or saved-page import. Automatic HTTP 202 recovery can retrieve the data produced by a readable search page; **More → Import saved Invaluable pages…** can add verified lots from a saved snapshot even while automatic HTTP refresh is unavailable. Neither action treats an access page as auction data.

The controller retains these metrics for diagnostics:

- pages fetched;
- cache hits;
- new, changed, and ended lots;
- AI-enriched records;
- input, output, and total token usage.

Invaluable's `currentBid` and `bidCount` values are normalized separately so the desktop agenda can distinguish a live current bid from **No bids** and an unavailable bid field from **N/A**. Bid-count changes participate in the content hash and therefore appear as changed lots on refresh.

## Calendar behavior

### Posted sold prices

After an auction, **Sync all** rechecks previously watched Invaluable lot detail pages for up to 30 days after their source date/time, including lots that have disappeared from upcoming searches or were already marked ended. A publicly visible posted result such as **Sold: $11,000 USD** is stored separately from the estimate and current bid, appears in the desktop **Current bid / sold** column and Markdown/CSV exports, and is uploaded by calendar sync. The website displays the result in the catalog, day list, lot browser, and research view. A missing lot or its last bid alone never counts as a sold price. Confirmed sold lots remain in calendar history and are excluded from upcoming ICS events and reminders. Later syncs that omit the result preserve the saved price.

Some Invaluable pages show **Sold: Log in to view** to public requests. Studio reports that these prices are unavailable and retains existing estimates and results. Ended lots without a verified price display **Sale ended · Sold price unavailable**. Access challenges stop further result requests for that refresh. Previously ended and sold lots remain available when the upcoming catalog fails, and an independent detail check may still update previously ended lots when the source permits access.

The old **Connect Invaluable**, Chrome profile picker, and **Use saved login** controls have been removed. Their implementation remains in `watchlist_ui.py`, `watchlist_browser.py`, and `watchlist_chrome.py`, along with `requirements-watchlist-browser.txt`, for possible future development. The two-step Studio workflow does not invoke these handlers or enumerate Chrome profiles.

As a manual fallback, save the individual sold lot page as HTML from your signed-in browser and use **More → Import saved sold results…** with its Invaluable artist selected. The importer matches the saved page to an existing watched lot and automatically syncs its posted result; it also works for older tracked lots outside the 30-day live recheck period. Only normalized result fields are imported. Page HTML, login cookies, and local filenames are not uploaded. Pages without an explicit visible sold amount or without a matching selected watch are reported and leave existing data intact.

The bookmark file supplies artist searches, while each lot's detail page supplies its final result.

ICS output defaults to one event per auction sale. Matched artists and lots are grouped in the description. A timezone-aware source time is converted to UTC. A source date without a time becomes an all-day event and the description marks the time as unverified. Event-per-lot and reminders are supported by the export function but are intentionally not the noisy UI default.

The private web calendar at `/calendar/` is populated by **Sync all** or a saved-page import. A selected date with lots exposes **Browse all N lots**, which opens a single modal viewer with the current lot's primary image, details, counter, progress, wraparound previous/next controls, and keyboard navigation. Website staff can explicitly select lots with saved Artprice links for the shared Email Tray; sync never selects, deselects, or sends them. See [`auction-calendar.md`](auction-calendar.md) for authentication, deployment, and Gmail setup.

## Migration note

Historical migration `0012_auctionsearchjob.py` is retained because it may already be applied. New migration `0013_delete_auctionsearchjob.py` safely removes that deployed model. The runtime model, imports, routes, views, polling helpers, environment constants, and broad-search tests are deleted.

## Manual verification

1. Run `python manage.py migrate` and confirm migration `0032_sharedartistwatchlist` applies.
2. Start the catalog desktop app and confirm the notebook shows **Artist Watchlist**, with no **Auction Search** tab.
3. Export a small synthetic or test browser bookmark HTML file. Do not add a real bookmark export to Git.
4. Click **Import Bookmarks HTML…** and confirm `ARTISTS INVALUABLE` is selected by default.
5. Confirm private/unrelated domains do not appear and source/artist/sale counts are shown before refresh. Enable a synthetic **HERITAGE** folder and confirm its sale title appears separately from artist names.
6. Expand **Manage artists**, select a small artist subset and look-ahead, then click **Sync all**.
7. Confirm status distinguishes website upload from any source failures; use **Stop** during a refresh once. Add an artist to the chosen HTML file, choose **Scan artists**, select the new artist, and use **Sync selected**. Verify only missing lots are uploaded, while artists already on the Calendar are ineligible.
8. Refresh the same fixture again and confirm unchanged complete lots produce cache hits and no repeated detail or AI request.
9. Inspect Agenda and Calendar views, then export Markdown, CSV, and ICS. Import the ICS into a temporary calendar and confirm one event per sale.
10. Verify upload, website listing edit/delete/reorder, gallery rendering, and artwork description generation still work.
11. Start with an empty local Watchlist cache and the same Calendar connection. Verify automatic startup restores shared artists and recent lots with their original source times, then repeat with **More → Load from Calendar**. Check local exclusions, unavailable HTML sources, and a website connection failure preserve usable local data.

## Automated verification

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe -m compileall -q catalogapp secondstateapp
node --test scripts/invaluable_export_snapshot.test.js
```

The synthetic tests cover bookmark safety, repeated decoding, adapters, pagination, retries, caching/diffs, duplicate marking, timezone/all-day ICS behavior, zero-AI mode, strict compact batching, enrichment caching, legacy removal, and preserved website regressions. No test contacts an auction site or OpenAI.

## Invaluable troubleshooting

A successful `GET /search` is not proof that auction data was returned: Invaluable currently responds with HTTP 200 and an empty JavaScript application shell. The live adapter therefore posts only the bookmarks' public artist/category/search filters to `/catResults`, combines compatible artist facets to reduce request volume, validates the JSON schema, and reports a source error if the endpoint returns HTML or an unexpected response. This prevents an empty shell from being recorded as a successful zero-result refresh. A temporary 401/403/429 is not bypassed; the agenda retains last-known cached lots and the user can retry later.
