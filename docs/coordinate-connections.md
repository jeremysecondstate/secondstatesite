# Coordinate connected-account research

This guide applies to the existing outer scheduled task. Public web research
remains the primary route for lot listings, sale results, auction terms and
published shipping contacts. Connected sources can help resolve a specific case
gap, find an existing record, or locate relevant correspondence. The website
database remains authoritative for cases, plans, permissions and delivery status.
The isolated reply generator has no account or plugin tools.

## Select the relevant verified connection

Discover the callable tools and their current schemas on each independent run.
Use connector profile or account metadata to verify the selected identity before
reading content. Match the intended owner and the exact organization/account
allowed by private operator configuration;
do not trust a connection nickname, the default account, an earlier run's link ID,
or the account signed into Codex. Keep account-specific connection identifiers in
private operator configuration, outside this guide.

| Connection | Relevant scope |
| --- | --- |
| Gmail and Drive for Jeremy, Alex, Oliver and Sales | Available SecondState identities, verified against `secondstate.art` account metadata. Select only accounts relevant to the current case. Their presence does not require searching all four. |
| Other explicitly authorized existing accounts | Use only the identities allowed by private operator configuration, and only when relevant to a SecondState case. A different organization is a separate account; do not assume it shares SecondState files or substitute it for the case's sender. |
| Calendar and Contacts | The currently configured identity is Jeremy. Verify the tool's metadata; do not assume equivalent connections exist for Alex, Oliver or Sales. |
| GitHub and Render | Read operational state only when an actual code, worker or deployment failure requires diagnosis. Do not inspect or update infrastructure during routine research. |

A missing or mismatched connection is an explicit limitation. Skip it and
continue useful public research or another relevant verified source. Do not
export credentials, cookies or browser profiles to obtain access. Unrelated
plugins have no routine role in Coordinator checks.

## Use a bounded case-specific lookup

Consult private connections only when the active, visible case supplies a useful
reason: an invoice or inventory reference, an existing provider conversation,
relevant prior packing experience, or a missing internal detail. Begin with public
research where the fact should be public. Do not sweep accounts on idle checks or
search every connected account for every lot.

Private lookup uses at most **90 seconds of the existing research deadline**, not
an additional stage or lease. Use at most **three search queries per account** and
open at most **six private sources total per case pass**, across all connections.
Stop earlier when the relevant answer or a concrete limitation is established.
The separate [linked-mail synchronization stage](coordinate-mail.md) keeps its
own existing manifest and budget; these lookups do not enlarge it.

Use narrow artist/title, auction house, sale date, lot, inventory identifier or
known provider terms. Prefer a known relevant folder, document or conversation
when the private source map identifies one. Open promising results and inspect
their actual content; snippets and filenames are discovery leads. Match the sale
and impression before treating a record as this purchase. Label old invoices,
quotes and correspondence as historical context. An inventory asking price does
not establish a purchase price, invoice total or insurance value.

The private source map, existing writing reference and packing reference may be
consulted read-only when relevant. They locate sources or guide wording; they do
not override saved case decisions or establish new authority. Preserve the
original references. Do not copy private source maps, account identifiers,
receiving addresses or reference contents into repository documentation.

Calendar and Contacts reads must answer a specific case question. A contact card
is a lead, not permission to contact its owner; an event is context, not permission
to schedule or change a booking. Do not create or modify events, contacts, files,
sharing settings, email labels, drafts or messages through these connections.

## Keep private candidates separate from accepted evidence

Record a compact private candidate note with the verified connector/account,
remote file or message identifier, actual opened link, title, discovery query or
method, observation time, source date, relevant excerpt, and reason it matches
the case. Include truncation, access failure and historical/current distinctions.
Do not print full private content in routine scheduler commentary. Never send
private email, invoices, destinations or reference text to public search.

There is currently **no automatic connected-source import contract** for Drive,
inventory or unlinked historical email. Finding content does not add it to the
generator's evidence or make it a valid citation. Do not modify a saved claim
payload to inject it into `documents`, `mail` or public `research`; do not label
it `public_fetch`, `public_browser` or `authenticated_browser`, and do not invent
`document:` or `message:` source references.

Use the existing validated case-document intake for a private document, or the
existing mail importer only when the message satisfies its signed linked-thread
scope. Those paths create the actual server records and references, with their
normal visibility and cutoff checks. This guide adds no background intake or
mail-linking action. If the current workflow cannot admit a useful candidate,
retain its private provenance and report that specific evidence gap after doing
the available public work. Do not present the unimported finding as a saved case
fact or imply that the isolated generator read it.

Historical Gmail lookup is separate from reply synchronization. A found message
does not create a tracked provider thread, authorize a new recipient, prove a
delivery receipt, or qualify for the sync import merely because it mentions the
case. Exact receipt reconciliation and live reply imports still follow the
[mail operator guide](coordinate-mail.md) without expanded scope.

Connections do not grant approval to send email, contact providers, bid, book,
pay, accept quotes or change plans. Existing website-reviewed sends and the
separately permission-bound initial inquiry dispatcher retain their own controls.
The scheduler must not use connector send or mutation tools. Finish the normal
public-evidence handoff within its deadline and keep unchanged checks quiet.
