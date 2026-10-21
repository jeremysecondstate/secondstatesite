# Invaluable browser collector

Use the Chrome or Edge profile where Invaluable already displays your artist searches. The collector opens the artists from `docs/artist-links.html` in one tab and saves the public lot data returned to those pages. It can collect multiple artists and pages into one Calendar import.

## Install once

1. In your working Chrome profile, open `chrome://extensions` (Edge: `edge://extensions`). Enable **Developer mode**, choose **Load unpacked**, and select `C:\dev\secondstatesite\private_data\invaluable-collector`. This folder is already built and ready. Select the folder containing `manifest.json`, not the ZIP file.
2. Open **SECONDSTATE Invaluable Collector** from the browser's Extensions menu.

The collector runs on HTTPS Invaluable search pages and keeps its captures in this browser profile. It has no Calendar credentials and does not read cookies, passwords, browsing history, or other websites. Installing the extension is a user action; the build command does not install it or change browser settings.

## Capture and update the Calendar

1. Choose `docs/artist-links.html` in the collector. Only Invaluable artist searches enter the queue; Artprice and other bookmarks are ignored.
2. Choose inclusive start/end dates and the timezone used to interpret those dates. For the current request, use **October 21–November 1, 2026**, **America/New_York**.
3. Start the capture. Keep the collector's auction tab open. It visits one artist at a time and follows results pages. Progress distinguishes captured pages, missing pages, and searches needing attention.
4. If a page fails, inspect it in your normal browser. The collector pauses instead of inventing an empty result. Use Resume when ready, or Skip to retain that artist as incomplete. You can export the pages collected so far.
5. Download the capture file. Restart Studio after updating this code, then choose **Artist Watchlist → More → Import browser capture and update Calendar…** and select that JSON file.

The import uses the capture's date window even when Studio's ordinary agenda is set to three or seven days. It adds missing lots and updates existing lots actually captured in that window. Unobserved lots, saved research, Email Tray selections, and purchase flags remain intact. Original observation times are retained, and older captures cannot overwrite newer observations. Captured pages are partial evidence; an import does not prove that every artist search was complete or that direct HTTP access is restored.

If Studio does not yet know the artists in the file, use **More → Scan bookmarks HTML…** with the same `artist-links.html` first. The dedicated browser-capture import considers all saved Invaluable artists, including those excluded from routine Sync all. It does not inherit a previous single-artist selection.

## Command-line alternative

Preview the saved capture locally:

```powershell
.\.venv\Scripts\python.exe scripts\import_invaluable_capture.py --bookmarks docs\artist-links.html "C:\path\to\capture.json"
```

Add `--sync` to upload through the existing authenticated Calendar API. The API key remains in the ignored local `.env`. Check the preview's errors and counts before uploading. The command never fetches auction data. See `--help` for cache and report options.

## Limits and troubleshooting

- A normal-browser search must load usable catalog results. The collector cannot make a denied or blank page readable, solve a challenge, or recover uncaptured pages.
- The queue uses the ordinary artist search with Ending Soon sorting. It removes saved source date filters, including the expired date on the Jim Dine bookmark, and uses your chosen import window. Artist, category, and query filters remain in place. Other extra filters can prevent exact matching.
- The collector observes only the site's own catalog responses. It does not replay requests, use private endpoints, or move your browser session to another browser.
- Captures have size and page limits. Export a partial run if a limit is reached, then collect the remaining artists in another run. Keep the exported files until the Calendar import succeeds.
- After rebuilding for an update, click **Reload** on the extension's browser settings card. Existing browser-capture JSON files and the older individual snapshot format remain importable.

To rebuild the unpacked folder and ZIP after a code update, run this from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\build_invaluable_collector.py
```

The extension uses Chrome's documented [content-script execution worlds](https://developer.chrome.com/docs/extensions/reference/manifest/content-scripts), [local extension storage](https://developer.chrome.com/docs/extensions/reference/api/storage), and [tab navigation](https://developer.chrome.com/docs/extensions/reference/api/tabs).
