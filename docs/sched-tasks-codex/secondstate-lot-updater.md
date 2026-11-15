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

Use $secondstate-lot-updater at C:/Users/7970X/.codex/skills/secondstate-lot-updater/SKILL.md to update the live SecondState Calendar from C:/dev/secondstatesite/docs/artist-links.html. Work in C:/dev/secondstatesite. Collect fresh Invaluable and Drouot lots, add newly listed eligible lots, and refresh observed public current bids and bid counts. Confirm cross-platform duplicates are the same underlying auction lot in the same sale and retain the Invaluable listing over its Drouot copy using reversible supersession while preserving both source records and access to saved work. Read and update the skill's durable state so this new chat can resume unfinished work, prevent overlapping writers, validate before syncing, and verify the live Calendar afterward. Report actual additions, changed bids, duplicate suppressions and any incomplete coverage concisely. Recording new bids does not authorize placing bids.
