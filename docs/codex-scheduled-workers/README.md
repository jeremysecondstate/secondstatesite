# Worker chats

Keep each active chat and its associated scheduled task titled exactly as listed, including replacement chats. These chats are Jeremy's places for direct requests about their respective topics. Automatic scheduled checks retain the bounded workflows and safeguards in their descriptions; a broad topic assignment does not expand a scheduled check's authority. Calendar Worker remains open to any on-demand Calendar request and also checks design and code upkeep every four hours.

All five scheduled workers use GPT-6.1 Sol (`gpt-6.1-sol`) with Ultra reasoning (`ultra`), as requested on October 24, 2026. Authorized replacement chats explicitly retain these settings, and Coordinator's inner generator uses the same model and reasoning. Global defaults remain unchanged.

| Worker | Direct-request topic | Scheduled workflow |
| --- | --- | --- |
| [LiveArt Worker](Refresh-Artprice-Sales-Images-Sched-Task-Description.md) | LiveArt research and related lot questions | Periodic scheduling stays paused. On “Process my LiveArt queue,” process only one durable snapshot of explicitly selected Calendar lots, then stop. Preserve evidence, query accounting and Bid Boards. |
| [Invaluable Worker](Refresh-Invaluable-Calendar-Hourly-Sched-Task-Description.md) | Invaluable-related work | Collect and validate the named bulk searches, then update the Calendar. |
| [Coordinator Worker](Coordinate-Drafts-and-Follow-Ups-Sched-Task-Description.md) | Shipping, handling, and correspondence | Process the bounded Coordinate pipeline and authorized shipper-reply notices. |
| [Inventory Worker](SecondState-Inventory-Intake-Sched-Task-Description.md) | SUPREME and other documents in THE BOOKS | Process staff-requested inventory updates through the existing queue and workbook safeguards. |
| [Calendar Worker](Calendar-Worker-Chat-Description.md) | Any Calendar request, including design, layout, usability, organization, features and fixes | Every four hours, inspect for concrete issues and make at most one small tested local improvement when needed. |

Calendar Worker's scheduled upkeep leaves changes locally reviewable and does not authorize commits or deployment. The artist-name/per-day print-count example is a possible future direct request, not a scheduled feature implementation.

LiveArt now starts only from an explicit manual queue request, including in its on-demand chat while periodic scheduling is paused. Server snapshots, receipts and ledgers preserve progress; chat history is not its resume state. A Windows watchdog checks every ten minutes and archives verified finished LiveArt run chats after two hours of inactivity, including unread runs. It preserves active, uncertain, pinned and on-demand chats. See [LiveArt run lifecycle](LiveArt-Run-Lifecycle.md) for operations and recovery.

The saved automation remains the source of its current cadence, status and destination. Existing automation IDs and research state paths stay unchanged. The other four workers retain their chat schedules. Historical versions in these documents are reference material, not current scheduled instructions.
