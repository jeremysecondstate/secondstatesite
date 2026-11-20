---
name: secondstate-market-mismatch
description: "Review SecondState Auction Calendar lots for sales outside the established collecting market for the work. Use for the recurring market mismatch scan or a direct request to find and flag such lots."
---

# SecondState Market Mismatch

Review the lots in the live SecondState Auction Calendar. A market mismatch is a lot offered in a sale that appears unlikely to reach the established collecting audience for that particular work. A different city, a specialist sale, or both can be the better fit. The Calendar's day filter shows findings saved with `mismatch` status.

## Work from the live queue

Run from `C:\dev\secondstatesite` using the project's Python environment and existing Calendar credentials. The worker reads and writes the live Calendar's market reviews.

```powershell
$python = 'C:\dev\secondstatesite\.venv\Scripts\python.exe'
$worker = 'C:\dev\secondstatesite\scripts\calendar_market_review.py'
& $python $worker pending --limit 50
```

Start with November 20, 2026. On each run, review lots dated today in America/Los_Angeles first, then move forward in sale order. Include every dated, non-superseded Calendar lot at U.S., international and unconfirmed sale locations, across every source and house. Read the worker queue independently of anyone’s selected Catalog view or sale-location filter. The same lot has one shared assessment wherever it appears. The worker also picks up changed catalog facts.

Read the entire batch. Complete the earliest due day before advancing to a later day. Research groups with the same sale or artist together where their evidence applies, but make a decision for each lot. Work in successive batches and save completed assessments as you go so the next run advances. Use `oldest_pending_day`, `oldest_pending_day_count` and `pending_count` to check where coverage resumes.

## Decide whether the market fits

1. Identify the work and its actual sale. Use the lot description and catalog to establish attribution, medium, edition or series, venue and sale focus. Verify the specific venue of a multinational house. An online sale can reach collectors elsewhere. The watchlist name can describe a reproduction, a work after an artist, or one item in a group. Match comparisons to what is actually being offered.
2. Look for an established audience. Prefer the house's published results for the same edition, followed by repeated sales of close works by the artist in the same medium and market segment. Consider specialist print, regional art or other collecting markets that could explain the pattern. One unusually high result, an artist's birthplace, a low estimate or a sale in a small country is insufficient evidence on its own.
3. Test the proposed mismatch against the current sale. A regional house may have a well-established department, an artist-focused collection or comparable sales of its own. A widely collected artist can have several appropriate markets. For an older sale use evidence relevant to its date. When citing money, distinguish a realized price from an estimate and preserve currency and premium basis.
4. Save `mismatch` when there is positive evidence for both an atypical placement and a better-established audience. Name the actual and stronger markets in plain language. In one or two sentences explain the useful difference to someone browsing that day's lots. Link distinct, identified sources for the lot or sale context and comparable auction evidence. Prefer direct lot, catalog or results pages. A flag communicates a research lead. Price and resale claims require separate evidence.

Use `clear` for an examined lot where the sale fits the work, including a documented international market for comparable material. Use `uncertain` when attribution, sale setting or comparables leave the decision unresolved. Give the precise reason so a future review can resolve it. Retain the relevant sources for either decision when available. The queue retries uncertain cases after seven days or when their identifying facts change.

**Historical example.** Whyte's placed Rufino Tamayo's 1976 mixograph *Hombre en Negro* in its Irish & International Art auction in Dublin. Swann sold another impression of that edition in a specialist New York prints sale. Waddington's recorded another sale of the same edition in its Prints & Photography auction. The sale programs and comparable impressions give concrete grounds to investigate the Dublin placement. Apply a fresh assessment to each actual Calendar lot. [Whyte's sale and lot 80](https://www.whytes.ie/auction/irish-international-art/898/?artistid=20455) · [Swann, lot 310](https://www.swanngalleries.com/auction-lot/rufino-tamayo-hombre-en-negro._7ba4c46a54) · [Waddington's, lot 110](https://www.waddingtons.ca/auction/prints-photography-nov-19-2020/gallery/lot/110/)

## Save and verify

Prepare a temporary UTF-8 JSON file with a top-level `reviews` array. Each entry needs its numeric `id`, the exact `fingerprint` and numeric `revision` returned by the market-review worker, plus its `status` and factual `reason`. For a mismatch, supply `sale_market`, `stronger_market` and at least two distinct `sources` shaped as `{"label":"House, sale or lot","url":"https://…"}`. The API accepts up to 200 reviews at once. Use only public evidence URLs.

```powershell
& $python $worker apply $reviewFile
& $python $worker inspect --ids $reviewedIds
& $python $worker pending --limit 50
```

Set `$reviewFile` to the JSON path and `$reviewedIds` to the comma-separated Calendar IDs in the batch. Verify each saved assessment is current and the status matches. Each write is atomic. If a batch conflicts, inspect its IDs, set aside ineligible lots, and reevaluate changed facts or newer assessments before submitting the outstanding decisions. After an interrupted write, inspect first. An identical replay preserves an already accepted review.

Continue with the next due batch. A saved assessment remains available on its sale day after the auction. At the end, report verified counts for flagged, clear and uncertain lots, the earliest date still due, and its remaining lot count. For new flags, give the day, artist, house and a short market explanation. Limit persistent changes to market assessments.
