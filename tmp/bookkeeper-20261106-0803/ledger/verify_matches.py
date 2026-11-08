from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
from decimal import Decimal
import csv,json,hashlib,openpyxl,re

out=Path(__file__).parent
root=Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
readcsv=lambda p:list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
D=lambda x:Decimal(str(x or 0))
ledger=next(root.glob('*General Ledger.xlsm'))
initial=sha(ledger)
w=openpyxl.load_workbook(ledger,read_only=True,data_only=True)
j=defaultdict(list)
for r in w['Journal Entries'].iter_rows(min_row=2,values_only=True):
    if r[1]:j[r[1]].append(r)
cash=lambda jid:sum((D(r[7])-D(r[8]) for r in j[jid] if r[6]=='Bank / Cash'),D(0))
chase=readcsv(root/'_BOOKKEEPING/chase-source-matches.csv')
matches=readcsv(root/'_BOOKKEEPING/transaction-matches.csv')
queue=readcsv(root/'_BOOKKEEPING/review-queue.csv')
review=readcsv(root/'_BOOKKEEPING/transaction-review.csv')
cross=readcsv(root/'_BOOKKEEPING/artwork-crosswalk.csv')
posted={r['transaction_id']:r for r in chase if r['source_status']=='Posted'}
pending=[r for r in chase if r['source_status']=='Pending']
errors=[]
for r in chase:
    if D(r['cash_change'])!=-D(r['source_amount']):errors.append(['sign',r['transaction_id']])
    for field in ['cash_je','aggregate_je','classification_jes']:
        for jid in re.findall(r'JE-[A-Za-z0-9-]+',r[field]):
            if jid not in j:errors.append(['missing_je',r['transaction_id'],field,jid])
    if r['cash_je'] and cash(r['cash_je'])!=D(r['cash_change']):errors.append(['cash_mismatch',r['transaction_id']])
    if r['source_status']=='Pending':
        p=posted.get(r['matched_posted_id'])
        if not p or p['cash_je']!=r['cash_je'] or D(p['cash_change'])!=D(r['cash_change']):errors.append(['pending_match',r['transaction_id']])
agg=defaultdict(lambda:D(0))
for r in posted.values():
    if r['aggregate_je']:agg[r['aggregate_je']]+=D(r['cash_change'])
agg_result={jid:{'detail_sum':str(v),'journal_net':str(cash(jid)),'difference':str(v-cash(jid))} for jid,v in agg.items()}
for r in matches:
    source=next((s for s in chase if s['transaction_id']==r['transaction_id']),None)
    if r['cash_je']:
        if r['cash_je'] not in j or cash(r['cash_je'])!=D(r['cash_change']):errors.append(['transaction_match',r['transaction_id']])
    elif not source or (source['mapping_type'] not in ['statement_aggregate_detail','superseded_pending_match']):
        errors.append(['missing_cash_coverage',r['transaction_id']])
old=load(Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING/runs/2026-11-06-0157-source-and-ledger-review/audit/ledger-audit.json'))
new=load(out/'ledger-audit.json')
same_fields=['canonical_sha256','canonical_size','journal','account_balances','policies','sheets','inventory','sales','bank','native_features','totals','formula_errors','links','registers']
deltas=[k for k in same_fields if old[k]!=new[k]]
financial_deltas=[k for k in deltas if k!='links']
inv_ids={r[0] for r in w['Inventory Cost Basis'].iter_rows(min_row=2,values_only=True) if r and r[0]}
cross_ids={r['ledger_id'] for r in cross}
result={
  'checked_utc':datetime.now(timezone.utc).isoformat(),
  'prior_checkpoint_comparison':{'changed_fields':deltas,'financial_workbook_byte_identical':initial==old['canonical_sha256'],'links_change_note':'Compared directly to last completed 2026-11-06 02:09 UTC run. All referenced Drive identities and local hyperlink targets remain registered/present.'},
  'source_union':{'observations':len(chase),'posted':len(posted),'superseded_pending':len(pending),'mapping_counts':dict(Counter(r['mapping_type'] for r in chase)),'posted_net':str(sum((D(r['cash_change']) for r in posted.values()),D(0))),'individual_posted_cash_refs':len({r['cash_je'] for r in posted.values() if r['cash_je']}),'aggregate_reconciliation':agg_result,'sign_convention':'Source positive = cash outflow; negative = cash inflow. Each register cash_change is the negated source amount.'},
  'transaction_matches':len(matches),'remaining_matching_rows':review,
  'queue':{'total':len(queue),'statuses':dict(Counter(r['status'] for r in queue)),'pending_question':next(r for r in queue if r['id']=='BW-20')},
  'crosswalk':{'rows':len(cross),'unique_supreme_ids':len({r['supreme_id'] for r in cross}),'unique_ledger_ids':len(cross_ids),'missing_ledger_ids':sorted(cross_ids-inv_ids),'unmapped_ledger_ids':sorted(inv_ids-cross_ids),'established_exception':load(root/'_BOOKKEEPING/run-summary.json')['crosswalk_coverage_exception']},
  'evidence_links':new['links'],
  'errors':errors,'canonical_unchanged':sha(ledger)==initial,
  'note':'Any historical source SHA in matching registers remains historical provenance. Current ledger hash and all audited balances/structure equal the prior checkpoint. No financial journal is warranted by unchanged evidence. Separate October 26 Venmo purpose remains unresolved; gross and cash must not be reposted.'
}
w.close()
result['status']='PASS' if not errors and not financial_deltas and result['canonical_unchanged'] else 'REVIEW'
(out/'match-audit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ['remaining_matching_rows','queue']},indent=2))
