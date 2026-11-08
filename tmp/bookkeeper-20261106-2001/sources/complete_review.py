from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import json, csv, hashlib

OUT = Path(__file__).parent
PRIOR = Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING/runs/2026-11-06-1359-source-and-ledger-review/sources')
ROOT = Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
def rd(p): return json.loads(p.read_text('utf-8-sig'))
def dump(p,x): p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n','utf-8')
scan = rd(OUT/'local-source-scan.json')
summary = rd(OUT/'mapped-source-summary.json')
reviews = rd(OUT/'document-reviews.json')
oldreviews = {x['source']:x for x in rd(PRIOR/'document-reviews.json')}
comparisons = rd(OUT/'workbook-comparisons.json')
assert len(scan['files']) == 233
assert all(x['status']=='unchanged' for x in scan['files'])
assert all(x['content_unchanged'] for x in comparisons)
review_comparisons=[]
for cur in reviews:
    old=oldreviews.get(cur['source'])
    same_source = bool(old and old['source_sha256']==cur['source_sha256'])
    same_text = bool(old and old.get('text_sha256')==cur.get('text_sha256'))
    review_comparisons.append({'source':cur['source'],'source_unchanged':same_source,'text_unchanged':same_text,'method':cur['method']})
assert all(x['source_unchanged'] for x in review_comparisons)
assert all(x['text_unchanged'] for x in review_comparisons)
queue=list(csv.DictReader((ROOT/'_BOOKKEEPING/review-queue.csv').open(encoding='utf-8-sig')))
pending=list(csv.DictReader((ROOT/'_BOOKKEEPING/transaction-review.csv').open(encoding='utf-8-sig')))
assert len(pending)==5
assert len(queue)==20
sup=rd(OUT/'workbook-SUPREME-xlsm.json')
allrows=[]
for sheet in sup['sheets']:
    for row in sheet['rows']:
        if any('SS-' in str(c.get('value','')) for c in row['cells'].values()):
            allrows.append({'sheet':sheet['name'],**row})
dump(OUT/'supreme-artwork-observations.json',allrows)
fresh_checks=[]
for r in scan['files']:
    current=hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()
    assert current==r['sha256'],r['path']
    fresh_checks.append({'path':r['path'],'sha256':current})
now=datetime.now(timezone.utc).isoformat()
summary.update({
    'completed_utc':now,
    'previous_review_reference':str(PRIOR),
    'source_versions_unchanged':233,
    'all_nine_workbooks_content_unchanged':True,
    'all_163_document_extractions_match_previous_source_and_text':True,
    'fresh_image_visual_reviews':0,
    'visual_review_method':'No new or changed financial image and no newly unclear financial field. Prior source-hash-matched visual conclusions retained, including IHOP archive and scanned UPS invoice.',
    'ancillary_nontransaction_assets':60,
    'registered_evidence_archives':2,
    'queue_status_counts':dict(Counter(q['status'] for q in queue)),
    'remaining_unmatched_bank_movements':5,
    'pending_question_id':'BW-20',
    'financial_delta':'No new or changed source activity, acquisition or sale; no newly supported accounting entry or monetary correction. SUPREME source figures unchanged.',
    'preserved_unresolved_items':[
       'Omar October 26 gross USD2000 payment memo Print service is already posted to clearing; earlier gifts do not classify it. BW-20 remains unanswered.',
       'Four Oliver sale-profit remittances total USD3000; purposes are settled, exact earlier settlement/receivable allocations unresolved.',
       'UPS USD224.95 combined pickup/packing includes company lots4168/4197/4198 and excluded7473; company share/allocation not established.',
       'May Clars invoice USD7104 versus recorded acquisition USD6993 is a separate USD111 discrepancy from Simpson invoice USD13764 versus recorded USD13875.',
       'Ferri original EUR20323.56 and separate USD23406.64 conversion preserved; held proposal is not a posted event.',
       'Complete statement coverage ends May29; later activity cutoff November2 retains an unknown complete-statement reconciliation difference.',
       'Ownership/funding, equipment opening-basis and prior sales dates require transaction-specific evidence; no new facts in current unchanged sources.'
    ],
    'policy':'Current source hash equality and exact workbook/extraction content equality support reuse of prior transaction reviews. No financial rate, private term, cash posting, allocation or tax treatment was inferred.',
    'final_source_hash_recheck':{'checked_utc':now,'files':len(fresh_checks),'all_unchanged':True},
    'canonical_files_changed':[]
})
dump(OUT/'document-review-comparisons.json',review_comparisons)
dump(OUT/'final-source-hash-recheck.json',fresh_checks)
dump(OUT/'mapped-source-summary.json',summary)
print(json.dumps({k:summary[k] for k in ['completed_utc','source_versions_unchanged','all_nine_workbooks_content_unchanged','all_163_document_extractions_match_previous_source_and_text','queue_status_counts','financial_delta','final_source_hash_recheck']},indent=2))


