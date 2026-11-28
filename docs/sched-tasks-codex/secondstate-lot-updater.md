# SecondState Lot Updater

Installed Codex automation: `secondstate-lot-updater`.

- Status: active.
- Schedule: every two hours, at minute zero.
- Execution: local, in the `secondstatesite` project, with a new chat for every run.
- Model: GPT-6 Astra (`gpt-6-astra`), reasoning effort `ultra`.
- Skill: `C:/Users/7970X/.codex/skills/secondstate-lot-updater/SKILL.md`.
- Maintained skill copy: [secondstate-lot-updater](../codex-skills/secondstate-lot-updater/SKILL.md).
- State and evidence: `private_data/secondstate-lot-updater/`.

## Installed prompt

Use $secondstate-lot-updater at C:/Users/7970X/.codex/skills/secondstate-lot-updater/SKILL.md to update the live SecondState Calendar from C:/dev/secondstatesite/docs/artist-links.html. Work in C:/dev/secondstatesite. Maintain lots in the regular Catalog. The regular Catalog takes precedence if a previously saved Random Lot qualifies for it. Use the regular Catalog's tracked-artist view to select existing lots for bid checks, updates, duplicate review, retries and coverage counts. Check the maintained Invaluable and Drouot bookmarks in docs/artist-links.html for new eligible Catalog lots. Validate complete captures and reconcile eligible finds against existing Calendar records. The SecondState Fine Art Print Audit manages Random Lots placement and handles verified prints outside the regular Catalog. Confirm cross-platform duplicates are the same underlying auction lot in the same sale and retain the Invaluable listing over its Drouot copy using reversible supersession while preserving both source records and access to saved work. Read and update the skill's durable state so this new chat can resume unfinished work, prevent overlapping writers, validate before syncing, and verify the live Calendar afterward. Report actual additions, changed bids, duplicate suppressions and any incomplete coverage concisely. Recording new bids does not authorize placing bids.
