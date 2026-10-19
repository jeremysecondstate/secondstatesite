# Initial shipping quote inquiries

Research and collecting quotes are one Preparing shipment activity. A complete lot fetch still triggers bounded shipping research: house policies/recommendations and nearby UPS, packers and art-capable options. The brief records conditional quote readiness, responsible party/stage for actions, cited provider contacts, scoped website checks and a labeled working currency. Working currency never replaces observed sale-price currency.

## Permission and test routing

The case's **Initial quote inquiry settings** page persists a staff-authorized mode and selected receiving address without saving a shipping plan or selecting a provider. Default is off: free-text drafts still need review and Send. Test mode sends only to `jeremy@secondstate.art`, with the intended provider identified in the message. There is no editable test recipient. The mail transport checks that route again.

Real-provider mode additionally requires `COORDINATE_LIVE_QUOTE_OUTREACH_ENABLED=true` and explicit case permission. This release keeps the production gate false pending successful testing and rollout authorization. Enabling the server gate alone does not change a case's mode. Booking, frame removal, quote acceptance, spending and payment are outside every mode.

The server builds initial quote packets from the validated brief and saved destination. Packets preserve artwork/framed measurements, medium/edition, seller condition and pickup terms, ask for itemized costs and capability/confidence, offer framed and conditional safely unframed alternatives, keep loose certificates with the works, and explicitly prohibit performing work. Invoice totals, private premiums/taxes and payment clearance are not prerequisites for initial inquiries.

## Scheduled dispatch and retries

Use the existing automation. After a saved research completion, and on otherwise idle runs, execute once with the ignored production environment loaded:

```powershell
.\.venv\Scripts\python.exe scripts/coordinate_quote_outreach.py --base-url https://secondstate.art --limit 2
```

The script cannot supply recipients, content or permissions. It requests at most two dispatches inside an 85-second outer budget; the server holds a case lock and commits an immutable delivery before calling Gmail. Limit is three initial inquiries per case/mode, one per provider. Existing provider threads/quotes, paused providers, pending research, changed destinations, hidden context and stale public contact evidence prevent new dispatch. Provider contact evidence must be opened public evidence, current within 24 hours and still visible. An uncertain result never permits resending.

Each request UUID is persisted before transport in ignored `private_data/coordinate-outreach-runs`. Ambiguous API failures retain that request for the next run; retries receive the saved result without another send. Gmail IDs are durably recorded before correspondence rendering, then the existing exact reconciliation can repair richer persistence. Do not delete pending records or manually recreate sends.

After dispatch, perform the existing bounded linked-mail sync. In test threads, Jeremy can reply as the intended provider. Only a reply referencing an observed message ID in that exact linked test thread is imported as mock inbound mail; ordinary self-mail and unrelated threads remain excluded. The generator receives `quote_test=true` and must never treat test prices as real quotes or permission to enable live outreach.

## Release checks

Verify the actual scheduled run performs public provider discovery, persists the brief and routes quote tests through the server. Read the exact returned Gmail thread with the authorized connector, verify actual To and full MIME content, then import through the scoped manifest. Confirm the site shows intended versus actual recipient and preserves one delivery on retry. A real reply test requires Jeremy's reply; never invent one or send another email to imitate it without authorization.
