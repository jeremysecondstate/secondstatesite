---
name: liveart-research
description: "Research the current lots in SecondState's LiveArt Queue, including multi-work lots and unidentified pieces, and save comparable sales and Bid Boards. Invoking this skill or asking to process the queue starts research immediately."
---

# LiveArt Research

Work in `C:/dev/secondstatesite`. **Invoking this skill means start researching the current LiveArt Queue immediately.** Ordinary requests to process the queue work too; no exact wording, confirmation or separate launch step is required. Editing or configuring the skill does not start research.

## Start with the current queue

Open SecondState's live **LiveArt Queue**, read the currently queued lots and their instructions, and begin the first lot in queue order. Those selections are the work list. An empty queue means there is nothing to research. Finish the selected work and stop. Follow Jeremy's later instructions if he adds work or changes scope.

Routine access, research, evidence entry, Bid Board saves and focused repairs needed to complete this work are already authorized. Work quickly and resolve recoverable problems as they arise.

**No administrative preflight or wrap-up.** Do not inspect older chats, rollouts, previous runs, automation memory/settings, lifecycle registries, receipts or usage ledgers. Do not verify ownership or predecessor completion, reconcile historical operations, create audits, archive chats, or record/compare run times. Do not create schedules, poll for additions or restart automatically. Existing evidence on the current lot is useful research context; unrelated run history is not.

Use the live queue and research UI directly. Do not launch the legacy queue runner or follow its exact-message, history, ownership or receipt requirements. This guide is the complete workflow for this skill and supersedes the older worker brief and queue-administration instructions. No preliminary reading of those documents is required.

## Research each lot

1. Open the queued lot's research link. Check the physical work count and identify each work against its original auction listing: artist/attribution, title, medium, dimensions, edition, signature, condition and auction details. Distinguish hand signatures from printed signatures, originals from reproductions, and image/sheet/frame sizes. Apply Jeremy's lot-specific instructions. For a pair, group, portfolio, book or other lot containing multiple works, read the [multi-work lot workflow](liveart-multi-work-lots.md) before selecting comps or calculating a Board. Missing titles call for identification research, not an automatic skip.
2. Skip explicitly after-attribution reproductions and verified unsigned modern/contemporary works unless Jeremy directs otherwise. Apply these exclusions to the intended resale units in a mixed lot; do not discard eligible works because another piece is excluded. An intact book or suite may be signed on its colophon; that does not make its loose sheets individually hand-signed. Missing signature information alone does not mean unsigned; historical Old Masters from traditions where signing was not customary are exempt. Briefly assess lots above **USD 20,000** using the actual current/opening bid or otherwise the low estimate for the entire lot, then continue unless deeper research was requested. Explain any skip using the current listing.
3. Research signed-in LiveArt and original auction records found through substantive web searches. Artist bookmarks are in `C:/dev/secondstatesite/docs/artist-links.html`, folder `LIVEART`. Reuse relevant evidence already saved on this lot. Use a targeted **Find LiveArt sales** query when useful; use **Add a sale from LiveArt web** for eligible supplemental sales or when API allowance is exhausted. Do not use Artprice or repeat a paid query whose result is still uncertain.
4. Select defensible comparable sales, preferring the same work and edition. Check actual sold status, price basis and product identity; exclude estimates, asking prices, unsold records, premium-inclusive totals and unrelated products. Establish whether each price bought a single work or an entire group. Deduplicate sales and select at most **25 per lot**, including all components. Manual LiveArt entry requires source-displayed **USD hammer** and a supported category: **Prints & Multiples** or **Drawings / Works on paper**. Do not invent or relabel evidence to fit the form.
5. **Save selected evidence**, then build and **Save Bid Board** using the rules below. Reload to confirm the current lot's evidence and Board actually saved. Keep deliberate user choices and email settings intact. No separate receipt, screenshot, audit or bookkeeping package is required.
6. Continue through the selected lots. Report saved research/Board links, chosen bid and ceiling, and any actual unavailable valuation or blocker concisely. Do not call unfinished research complete or describe a queue status change that did not occur.

## Bid Board rules

- Use **USD 100 minimum net profit**, **10% minimum return on cost**, and **Working**. For single works or genuinely comparable whole groups, use the median eligible selected hammer and blank manual resale overrides. The [multi-work workflow](liveart-multi-work-lots.md) defines the exception for documented component-based whole-lot totals; never pool single-piece prices into a group valuation.
- Use the current auction's premium, taxes, fees, selling costs, bid increments and supported FX. Use **USD 300 provisional international shipping** unless a better quote or deliberate saved user value exists. Account for supported restoration costs and material condition differences. Keep assumptions visible and avoid double counting costs.
- Use the actual current bid, opening or next admissible bid. If none is available after reasonable checking, use **25% of the low estimate, rounded up to a valid house step**, explicitly labeled as an assumption. An already placed bid needs the next increment; an available opening does not.
- Between the lowest qualifying bid and the Working ceiling, choose the greatest valid qualifying bid at or below their midpoint. Preserve an intentional valid user choice. Report the chosen bid and walk-away ceiling separately.
- Save **no qualifying bid** when the targets cannot be met, or **valuation unavailable** with zero selected sales and blank overrides when defensible priced evidence is absent. If an empty lot has no evidence-save control, save the Board to initialize empty evidence. Do not manufacture resale values or evidence.

Preferred research models are **GPT-6.1 Sol Ultra** (`gpt-6.1-sol`, `ultra`) or **GPT-6 Astra Ultra** (`gpt-6-astra`, `ultra`), including delegated research. Use the chat's selection without a model/configuration preflight.

If a necessary application repair involves Render deployment, use **Jeremy's Workspace**.
