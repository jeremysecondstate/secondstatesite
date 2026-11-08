from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict
from decimal import Decimal
import json, csv, hashlib, re, openpyxl

out=Path(__file__).parent
root=Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
prior=root/'_BOOKKEEPING/runs/2026-11-06-0157-source-and-ledger-review'
load=lambda p:json.loads(p.read_text('utf-8-sig'))
dc=lambda v:Decimal(str(v or 0).replace(',',''))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
errors=[]
def check(condition,message):
    if not condition: errors.append(message)
def readcsv(name):
    return list(csv.DictReader((root/'_BOOKKEEPING'/name).open(encoding='utf-8-sig',newline='')))
sources=[root/'CHASE ACTIVITY.xlsm',root/'SUPREME.xlsm',next(root.glob('*General Ledger.xlsm'))]
before={p.name:sha(p) for p in sources}
c=openpyxl.load_workbook(sources[0],read_only=True,data_only=True)
s=openpyxl.load_workbook(sources[1],read_only=True,data_only=True)
l=openpyxl.load_workbook(sources[2],read_only=False,data_only=True)
source_rows=[list(r) for r in c.active.iter_rows(min_row=2,values_only=True) if len(r)>5 and r[5]]
native_values=load(out.parent/'cloud/native-chase.json')['read']['values']
native_rows=[r for r in native_values[1:] if len(r)>6 and r[5]]
prior_values=load(Path('C:/dev/secondstatesite/tmp/bookkeeper-20261106-0803/cloud/native-chase.json'))['read']['values']
prior_rows=[r for r in prior_values[1:] if len(r)>6 and r[5]]
normalized=lambda row:tuple(dc(v) if i==2 else v for i,v in enumerate(row))
check([normalized(r) for r in native_rows]==[normalized(r) for r in prior_rows],'Native Chase content differs from prior run')
source={r[5]:r for r in source_rows};native={r[5]:r for r in native_rows}
check(len(source)==len(source_rows),'Duplicate source IDs')
check(len(native)==len(native_rows),'Duplicate native IDs')
overlap=set(source)&set(native)
for tid in overlap:
    check(normalized(source[tid])==normalized(native[tid]),'Local/native overlap mismatch '+tid)
union={**source,**native}
events=readcsv('chase-source-matches.csv'); eventids={r['transaction_id'] for r in events}
raw_rows=[list(r) for r in l['Chase Activity Raw'].iter_rows(min_row=9,values_only=True) if len(r)>6 and r[6]]
raw={r[6]:r for r in raw_rows}
check(len(raw)==len(raw_rows),'Duplicate raw IDs')
check(set(union)==eventids==set(raw),'Local/native/raw/register union mismatch')
raw_date_differences=[]
for tid,r in union.items():
    a=raw[tid]
    check(dc(a[18])==dc(r[2]),'Raw source amount mismatch '+tid)
    check(a[10]==r[6].lower(),'Raw source status mismatch '+tid)
    check(a[19]==r[3]=='USD','Source/raw currency mismatch '+tid)
    raw_last4=str(int(a[5])).zfill(4) if isinstance(a[5],(float,int)) else str(a[5]).zfill(4)
    check(raw_last4=='0076' and '0076' in r[4],'Source/raw account mismatch '+tid)
    if str(a[11])[:10]!=str(r[0])[:10]:raw_date_differences.append({'id':tid,'raw_date':a[11],'source_date':r[0]})
for e in events:
    r=union[e['transaction_id']]
    check(dc(e['source_amount'])==dc(r[2]) and dc(e['cash_change'])==-dc(r[2]),'Event amount/sign mismatch '+e['transaction_id'])
    check(e['source_status']==r[6],'Event status mismatch '+e['transaction_id'])
    check(e['account']=='0076' and e['currency']==r[3],'Event account/currency mismatch '+e['transaction_id'])
cross=readcsv('artwork-crosswalk.csv'); crossids={r['supreme_id'] for r in cross}
supids=set(); observations=[]
for sheet in s:
    for row in sheet:
        for cell in row:
            if isinstance(cell.value,str) and re.fullmatch(r'SS-[A-Z0-9]{8}',cell.value):
                supids.add(cell.value);observations.append({'sheet':sheet.title,'cell':cell.coordinate,'id':cell.value})
check(supids==crossids,'SUPREME crosswalk coverage mismatch')
inv={r[0]:r for r in l['Inventory Cost Basis'].iter_rows(min_row=2,values_only=True) if r[0]}
for cr in cross:
    check(cr['ledger_id'] in inv,'Crosswalk missing ledger ID '+cr['ledger_id'])
    check(abs(dc(cr['ledger_cost_basis_usd'])-dc(inv[cr['ledger_id']][11]))<dc('.000001'),'Crosswalk basis mismatch '+cr['supreme_id'])
sales=[r for r in l['Sales & COGS'].iter_rows(min_row=2,values_only=True) if r[0]]
check(len({r[1] for r in sales})==len(sales),'Duplicate sold artwork ID')
for r in sales:
    check(r[1] in inv and dc(r[7])==dc(inv[r[1]][11]),'Sale/inventory basis mismatch '+r[0])
bank=[r for r in l['Bank Transactions'].iter_rows(min_row=2,values_only=True) if len(r)>13 and r[13]]
for r in bank:
    if r[13] in union:
        check(dc(r[5])==-dc(union[r[13]][2]),'Bank/source cash sign mismatch '+r[13])
for row in [2,3,4]:check(dc(l['Monthly Reconciliation'][f'H{row}'].value)==0,'Closed statement difference')
balance_row=next(r for r in native_values if len(r)>1 and r[1]=='Current balance')
check(dc(balance_row[2])==dc('131.8'),'Native balance differs')
res={'checked_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':before,
 'local_chase':{'rows':len(source),'status_counts':dict(Counter(r[6] for r in source.values()))},
 'native_chase':{'rows':len(native),'status_counts':dict(Counter(r[6] for r in native.values())),'cutoff':max(r[0] for r in native.values()),'current_balance':balance_row[2],'unchanged_vs_prior':not any('Native Chase' in x for x in errors),'amount_normalization':'Prior unformatted numeric amounts versus current formatted numeric strings compared exactly using Decimal.'},
 'local_native_overlap':len(overlap),'native_only_ids':sorted(set(native)-set(source)),
 'union':{'rows':len(union),'status_counts':dict(Counter(r[6] for r in union.values())),'raw_rows':len(raw),'registered_rows':len(events)},
 'raw_original_date_differences_preserved':raw_date_differences,
 'account_normalization':'Numeric 76, 76.0 and text 0076 resolve to the same account; originals remain unchanged.',
 'crosswalk':{'unique_supreme_ids':len(supids),'observations':len(observations),'missing':sorted(supids-crossids),'basis_mismatches':[e for e in errors if 'basis mismatch' in e]},
 'statements':{'reconciled_through':'2026-05-29','later_period':'2026-05-30 through 2026-11-02','exact_later_difference':None},
 'sources_unchanged':all(sha(p)==before[p.name] for p in sources),'errors':errors}
res['status']='PASS' if not errors and res['sources_unchanged'] else 'FAIL'
(out/'source-checks.json').write_text(json.dumps(res,indent=2,ensure_ascii=False,default=str),'utf-8')
print(json.dumps({k:v for k,v in res.items() if k!='raw_original_date_differences_preserved'},indent=2))
raise SystemExit(0 if res['status']=='PASS' else 1)
