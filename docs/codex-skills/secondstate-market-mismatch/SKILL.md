---
name: secondstate-market-mismatch
description: "Flag SecondState Auction Calendar lots offered far from a place central to the work or outside a market with documented stronger collecting activity. Use for the recurring market mismatch scan or a direct request to find these lots."
---

# SecondState Market Mismatch

Review the lots in the live SecondState Auction Calendar. Flag a lot worth a closer look when its auction venue contrasts with a documented cultural or geographic connection, or when comparable works demonstrably attract stronger collector interest elsewhere. Either finding is sufficient. The Calendar's day filter shows findings saved with `mismatch` status.

## Work from the live queue

Run from `C:\dev\secondstatesite` using the project's Python environment and existing Calendar credentials. The worker reads and writes the live Calendar's market reviews.

```powershell
$python = 'C:\dev\secondstatesite\.venv\Scripts\python.exe'
$worker = 'C:\dev\secondstatesite\scripts\calendar_market_review.py'
& $python $worker pending --limit 50
```

Start with November 21, 2026, in America/Los_Angeles. For the complete recheck, enumerate every dated, non-superseded Calendar lot from that date across all houses, sources and locations, including unconfirmed locations. Include existing mismatches, clears, uncertain cases and unreviewed lots. The ordinary pending feed omits current decisions. Use the full inventory and progress ledger in the automation’s `recheck` directory. Refresh it at each run. Inspect and apply in sale-date order with `--recheck-from 2026-11-21` so a prior sale can still be corrected. Verify saved decisions by ID and fingerprint before recording progress. Resume incomplete dates and reevaluate changed facts. After the full recheck, continue with new, changed and retry-due lots.

Read the entire batch. Complete the earliest due day before advancing to a later day. Research groups with the same sale or artist together where their evidence applies, but make a decision for each lot. Work in successive batches and save completed assessments as you go so the next run advances. Use `oldest_pending_day`, `oldest_pending_day_count` and `pending_count` to check where coverage resumes.

## Decide which lots to flag

Identify the work and where this auction takes place. Verify attribution, medium and, when relevant, the subject, signer, edition or series against the lot description and photographs. A watchlist match can refer to an original, a reproduction, a work after the artist or one item in a group. Verify the specific venue when a house operates in multiple cities.

Investigate each conclusion yourself. Open the actual listing and photographs and compare the relevant details against independent evidence. Check the selling region’s own exhibitions, collectors, editions or comparable sales where relevant. A publisher’s address, an artist’s biography or a museum that owns unrelated examples can suggest a line of inquiry. Determine how the specific object or a recognizable feature of the practice matters to a particular place or audience, and what makes this venue noteworthy in light of that evidence. Keep image identification, physical edition and signature authentication distinct. If the surviving evidence supplies only general context, save a clear assessment. Reserve uncertain for a specific unresolved fact that could change the decision. No target flag rate applies.

- **Cultural or geographic connection.** Look for a place that helps explain the work or the artist's practice. A representative work can carry the regional identity of that practice even if its title and imagery name no particular place. The person portrayed, a verified signer, or an institution or event depicted can also connect the work to a distinct local audience. Compare cities and regions within a country as well as across borders. Use the catalog and a reliable source on the relevant person, subject or tradition to explain why encountering this work at this venue is noteworthy. A birthplace, nationality, different auction address, overseas printer or depicted site is a clue. Several regions can be natural markets for the same work. Consider the selling region's own ties before flagging it.
- **Comparative collecting evidence.** Look for realized sales of the same edition, then close works in the same medium and market segment. Research the selling market as well as the proposed stronger market, using local spellings and nearby auction venues. Consider frequency, geographic coverage, contrary examples, and other documented evidence of collector activity. Flag when the evidence supports a meaningful difference. One high result or an empty local search is insufficient. If quoting prices, preserve currency and premium basis and distinguish results from estimates.

Online bidders can search by artist and medium around the world. An established local trade or international distribution can temper the wording of a cultural flag. A grounded connection qualifies even when there are local sales, no bidder demographics, or no evidence of weak demand, a discount or a majority of transactions elsewhere. Exclude sale titles and themes, auction-house prestige, generalist or specialist labels, differences in catalogue labeling, and speculation about discovery in a differently named sale.

Save `mismatch` when either basis applies. Write the card in one or two plain-language sentences. Name the actual sale place and the relevant image, process, artistic practice or collecting evidence. Explain why that combination makes this lot worth a look there. Make claims about bidder location, weaker demand or pricing only when supported by separate evidence. Use `clear` when the resolved facts support neither basis. Use `uncertain` when a relevant fact such as the identity, image, venue or evidence for a possible connection is still unresolved. Explain the gap and retain relevant links. The queue retries uncertain cases after seven days or when identifying facts change.

## Save and verify

Prepare a temporary UTF-8 JSON file with a top-level `reviews` array. Each entry needs its numeric `id`, the exact `fingerprint` and numeric `revision` returned by the market-review worker, plus its `status` and factual `reason`. For a mismatch, put the verified sale location in `sale_market`. Put the place connected to the work or the evidenced stronger collecting market in `stronger_market`. Supply at least two distinct public `sources` shaped as `{"label":"Source name","url":"https://…"}`. Cite the actual lot or auction and a source documenting the cultural connection or the comparative collecting evidence. The API accepts up to 200 reviews at once.

```powershell
& $python $worker apply $reviewFile
& $python $worker inspect --ids $reviewedIds
& $python $worker pending --limit 50
```

Set `$reviewFile` to the JSON path and `$reviewedIds` to the comma-separated Calendar IDs in the batch. Verify each saved assessment is current and the status matches. Each write is atomic. If a batch conflicts, inspect its IDs, set aside ineligible lots, and reevaluate changed facts or newer assessments before submitting the outstanding decisions. After an interrupted write, inspect first. An identical replay preserves an already accepted review.

Continue with the next due batch. Report the verified conclusion with the day, artist, house and sources for each finding. For a recheck, distinguish added, retained and removed flags, show full unfiltered day totals and reviewed counts, and state the earliest unfinished day and number remaining. Keep unresolved cases in the retry queue. Limit live edits to market assessments.
