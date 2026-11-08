from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,shutil
W=Path(__file__).parent; R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING'); B=R.parent
def rd(p):return json.loads(p.read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n','utf-8')
s=rd(R/'run-summary.json'); out=Path(s['run_directory']); stage=rd(W/'staging-audit.json'); baseline=rd(W/'baseline-register-hashes.json')
assert stage['status']=='PASS' and rd(W/'verification/final-register-verification.json')['all_match']
for n,h in stage['record_sha256'].items():assert sha(R/n)==h
for n in s['unchanged_registers']:assert sha(R/n)==baseline[n]
assert sha(B/'Second State Books — General Ledger.xlsm')==s['ledger_sha256']
for x in rd(W/'sources/local-source-scan.json')['files']:
 if x.get('sha256'):assert sha(Path(x['path']))==x['sha256'],x['path']
assert rd(W/'ledger/source-checks.json')['status']=='PASS'
now=datetime.now(timezone.utc).isoformat()
final={'completed_utc':now,'status':'PASS','ledger_unchanged':True,'new_entries':0,'all_233_source_hashes_unchanged':True,'five_matching_queue_registers_unchanged':True,'fresh_cloud_register_bytes_match':True,'ledger_sha256':s['ledger_sha256']}
dump(W/'final-record-audit.json',final)
for name in ['sources','cloud','ledger','verification']:
 target=out/name;target.mkdir(exist_ok=True)
 for p in (W/name).iterdir():
  if p.is_file() and p.suffix in ['.json','.txt','.md']:shutil.copy2(p,target/p.name)
for n in ['baseline-register-hashes.json','staging-summary.json','staging-audit.json','publish-records.json','final-record-audit.json']:shutil.copy2(W/n,out/n)
report=f'''# Bookkeeper Worker — November 6, 2026 review

Completed {now}. Instructions read afresh. No new transaction, acquisition, sale or supported correction was found. Saved the source register, Drive manifest and run summary with current verification records. The ledger, SUPREME, Chase workbook, review queue and four matching/crosswalk registers remain unchanged. No financial entry, evidence link or closed-period change was made.

Coverage: 235 mapped source identities across 161 directories, including evidence archives; all 233 readable binaries unchanged. Drive confirmed all 235 source files plus directly accessible native Chase. Reviewed nine local workbooks/55 sheets, all 25 historical native SUPREME tabs including 22 hidden tabs, the planning document and prior bookkeeping decisions. Reread 146 hash-matched text/OCR extracts, freshly extracted 15 PDFs, retained the unchanged scanned UPS visual review and reread archived Venmo evidence. Also reviewed the existing equipment fact register, without treating it as a new transaction. Generated backups/reports were excluded. No changed or newly unclear fields required new visual inspection. All 68 SUPREME artwork IDs remain crosswalked.

Verification passed: 511 balanced journal entries/1,029 lines, valid accounts, no duplicate posting or artwork/sale keys, inventory $110,705.610977 and COGS $52,390 tied. Excel 16 performed full recalculation and read-only reopen on a disposable copy: all 2,221 formula results agreed, with zero trial-balance and balance-sheet differences. All 797 evidence-link instances have registered identities or existing local targets. The canonical ledger was never saved; SHA256 remains {s['ledger_sha256']}.

Chase has activity through November 2. Native Chase has 138 posted records and no current pending activity. Across sources, 271 posted observations and five superseded pending observations match 223 detailed cash entries and 48 aggregate-covered observations without double-counting. Cash remains $131.80. Complete statements reconcile through May 29; complete-statement reconciliation for May 30–November 2 remains unfinished and its exact difference is unknown. The accepted activity source is unchanged; no upload request was repeated.

Bank Review Clearing remains $14,822.08 credit. Venmo Settlement Clearing remains $2,017.75 debit: the October 26 $2,000 gross receipt awaiting classification plus the earlier $17.75 unmatched difference, not a verified wallet balance. Five bank movements still require exact documentary matches: four Oliver sale-profit receipts totaling $3,000 and the $224.95 UPS company/artwork allocation. Four historical proposals and other existing invoice, settlement, funding and historical-date items remain held. Private auction terms and original invoice currencies remain unchanged.

The review queue remains 20 items: nine Open, six Answered—matching pending and five Resolved. BW-20 remains the only unanswered user question: whether Omar's separate October 26 $2,000 Venmo payment labeled “Print service” was a gift or payment for services. The receipt is already posted as VENMO-002; any answer must reclassify the existing clearing credit without reposting cash or the gross receipt. No question was repeated. [Payment evidence](https://mail.google.com/mail/u/?authuser=jeremy%40secondstate.art#all/1a17b1cc36aed5a2).

Dated register backups, independent staged audit, exclusive concurrent-write guards, final source rehash and fresh cloud byte checks passed. The three saved records, unchanged ledger and queue match Drive. Native Chase remains absent from the mapped pointer/root listing but is directly readable. No source coverage remains unfinished beyond the reconciliation/evidence limitations above.

[General ledger](https://drive.google.com/file/d/1_MOhIuKfrvU6AHjA4RtKUq9QqqmwNYUe/view?usp=drivesdk) · [Review queue](https://drive.google.com/file/d/1lOMIyB8i_vxQYD6CaA4Lwjx_oaHXH1RJ/view?usp=drivesdk)
'''
(out/'report.md').write_text(report,'utf-8')
dump(out/'completion.json',{**final,'report_path':str(out/'report.md'),'pending_question':'BW-20 unchanged; not reasked','runtime_start_utc':'2026-11-06T08:03:34Z'})
memory=Path('C:/Users/WS 7950X/.codex/automations/bookie-worker/memory.md')
old=memory.read_text('utf-8-sig') if memory.exists() else ''
checkpoint=f'''# Bookkeeper Worker | current verified checkpoint
Completed {now}; run started 2026-11-06T08:03:34Z. November 6 scheduled review. Instructions read afresh. This supersedes prior run status; settled decisions remain below.

No new activity, acquisition, sale, evidence link or supported correction. All 233 binary hashes unchanged; 235 mapped identities/161 directories, same 235 cloud files plus direct native Chase. Nine workbooks/55 sheets, native historical SUPREME 25 tabs/22 hidden, planning document, 146 hash-matched extracts plus 15 fresh PDFs, retained UPS visual and Venmo archive reviewed. 68 SUPREME IDs all crosswalked. All SUPREME figures unchanged.

Ledger unchanged SHA256 {s['ledger_sha256']} (624298 bytes). 511 balanced JEs/1029 lines; Excel16 full rebuild/read-only reopen passed 2221 formulas and zero TB/BS differences. Inventory110705.610977; COGS52390; AR76887.8675; cash131.80; Bank Review Clearing credit14822.08; Venmo Settlement Clearing debit2017.75 = gross2000 + prior17.75 unmatched, NOT verified wallet balance. Native Chase138Posted/0Pending throughNov2; union271Posted+5supersededPending; 223detail cash entries+48aggregate observations. Statements reconcile throughMay29; May30–Nov2 exact difference unknown. No source/statement request.

Saved source-register, drive-source-manifest and run-summary review metadata only; 236source/396manifest identities retained. Five other registers unchanged. Dated backups, independent stage audit, exclusive concurrent guards, final source hashes and fresh Drive byte matches passed. Canonical ledger never edited/saved. Native Chase pointer/listing absence persists; direct metadata/content accessible.

ONE PENDING QUESTION BW-20 remains unanswered, not reasked: Omar separateOct26 USD2000 Venmo Print service—gift or services? https://mail.google.com/mail/u/?authuser=jeremy%40secondstate.art#all/1a17b1cc36aed5a2 . Already VENMO-002; reclassify clearing only after answer, never repost cash/gross. Earlier gifts do not classify it. Queue20:9Open/6Answered-matching pending/5Resolved. Five bank movements still require exact matching: Oliver998+2+1000+1000 and UPS224.95 companyClars4168/4197/4198 versus excluded7473. Purposes settled; four historical PAY/SETTLE/SALE/FERRI proposals held. Preserve all user answers/private terms.

Verified report/evidence: {out}
Ledger https://drive.google.com/file/d/1_MOhIuKfrvU6AHjA4RtKUq9QqqmwNYUe/view?usp=drivesdk
Queue https://drive.google.com/file/d/1lOMIyB8i_vxQYD6CaA4Lwjx_oaHXH1RJ/view?usp=drivesdk

# Earlier checkpoints retained for factual history

'''
memory.write_text(checkpoint+old,'utf-8')
print(json.dumps(final))
