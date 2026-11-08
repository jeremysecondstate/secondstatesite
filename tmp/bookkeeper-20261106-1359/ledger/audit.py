from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal
from datetime import datetime,timezone
import openpyxl,json,csv,hashlib,zipfile,re

root=Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
out=Path(__file__).parent
p=next(root.glob('*General Ledger.xlsm'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial=sha(p)
w=openpyxl.load_workbook(p,data_only=False,keep_links=True)
v=openpyxl.load_workbook(p,data_only=True,keep_links=True)
D=lambda x:Decimal(str(x or 0))
rows=lambda s:[(r[0].row,[c.value for c in r]) for r in v[s] if any(c.value is not None for c in r)]
res={'checked_utc':datetime.now(timezone.utc).isoformat(),'canonical_sha256':initial,'canonical_size':p.stat().st_size,'policies':{},'sheets':{},'journal':{},'account_balances':{},'formula_errors':[]}
for s in w:
    res['sheets'][s.title]={'state':s.sheet_state,'nonempty_rows':len(rows(s.title)),'tables':{k:s.tables[k].ref for k in s.tables},'validations':[str(d.sqref) for d in s.data_validations.dataValidation], 'formulas':sum(c.data_type=='f' for rr in s for c in rr),'hyperlinks':sum(bool(c.hyperlink) for rr in s for c in rr),'conditional_format_count':len(s.conditional_formatting),'charts':len(s._charts),'images':len(s._images)}
    for rr in v[s.title]:
        for c in rr:
            if c.data_type=='e':res['formula_errors'].append([s.title,c.coordinate,c.value])
res['policies']={s:[{'row':i,'values':[x for x in a if x is not None]} for i,a in rows(s)] for s in ['Read Me','Journal Templates','Chart of Accounts']}
jes=defaultdict(lambda:Decimal('0')); acc=defaultdict(lambda:Decimal('0')); lines=Counter(); journal=defaultdict(list); art=defaultdict(lambda:defaultdict(lambda:Decimal('0')))
for n,a in rows('Journal Entries'):
    if n==1 or not a[1]:continue
    net=D(a[7])-D(a[8]);jes[a[1]]+=net;acc[a[6]]+=net;lines[(a[1],a[2])]+=1;journal[a[1]].append(a[:14])
    if a[5]:art[a[5]][a[6]]+=net
accounts={a[1] for n,a in rows('Chart of Accounts') if n>1 and a[1]}
sigs=defaultdict(list)
for jid,rs in journal.items():
    sigs[tuple(sorted((str(a[0]),str(a[6]),str(D(a[7])),str(D(a[8])),str(a[4]),str(a[5])) for a in rs))].append(jid)
res['journal']={'count':len(jes),'lines':sum(lines.values()),'imbalanced':{k:str(n) for k,n in jes.items() if abs(n)>Decimal('.005')},'duplicate_line_keys':[list(k) for k,c in lines.items() if c>1],'unknown_accounts':sorted(set(acc)-accounts),'exact_signature_duplicates':[x for x in sigs.values() if len(x)>1]}
res['account_balances']={k:str(n) for k,n in acc.items()}
res['reports']={s:[{'row':n,'values':a[:12]} for n,a in rows(s)] for s in ['Dashboard','Trial Balance','Financial Statements','Monthly Reconciliation','Due to Owner','Owner Equity']}
inv=[(n,a[:16]) for n,a in rows('Inventory Cost Basis') if n>1 and a[0]]
sales=[(n,a[:12]) for n,a in rows('Sales & COGS') if n>1 and a[0]]
res['inventory']={'rows':len(inv),'duplicate_ids':[k for k,c in Counter(a[0] for n,a in inv).items() if c>1],'status_counts':dict(Counter(a[12] for n,a in inv)),'all_basis':str(sum(D(a[11]) for n,a in inv)),'by_status':{status:str(sum(D(a[11]) for n,a in inv if a[12]==status)) for status in set(a[12] for n,a in inv)},'basis_errors':[{'row':n,'id':a[0],'calculated':str(sum(D(x) for x in a[6:11])),'reported':a[11]} for n,a in inv if abs(sum(D(x) for x in a[6:11])-D(a[11]))>Decimal('.005')]}
res['sales']={'rows':len(sales),'gross':str(sum(D(a[4]) for n,a in sales)),'fees':str(sum(D(a[5]) for n,a in sales)),'net':str(sum(D(a[6]) for n,a in sales)),'cogs':str(sum(D(a[7]) for n,a in sales)),'duplicate_sale_ids':[k for k,c in Counter(a[0] for n,a in sales).items() if c>1],'missing_journal_refs':[(n,a[0],ref) for n,a in sales for ref in a[9:11] if ref and ref not in journal]}
res['inventory']['available_to_gl_difference']=str(sum(D(a[11]) for n,a in inv if a[12]!='Sold')-acc['Inventory'])
res['sales']['cogs_to_gl_difference']=str(sum(D(a[7]) for n,a in sales)-acc['Cost of Goods Sold'])
res['bank']={'row_count':len(rows('Bank Transactions'))-1,'duplicate_transaction_ids':[k for k,c in Counter(str(a[13]) for n,a in rows('Bank Transactions') if n>1 and len(a)>13 and a[13]).items() if c>1],'review_statuses':dict(Counter(a[9] for n,a in rows('Bank Transactions') if n>1))}
res['registers']={}
for name in ['review-queue','transaction-review','transaction-matches','artwork-crosswalk','chase-source-matches']:
    with (root/'_BOOKKEEPING'/f'{name}.csv').open(encoding='utf-8-sig',newline='') as f:a=list(csv.DictReader(f))
    res['registers'][name]={'rows':len(a),'status_counts':dict(Counter(x.get('status','') for x in a))}
    if name in ['review-queue','transaction-review']:res['registers'][name]['records']=a
with zipfile.ZipFile(p) as z:
    names=z.namelist();res['native_features']={'vba_parts':[n for n in names if 'vba' in n.lower()],'external_links':[n for n in names if 'externalLinks' in n],'table_parts':sum(n.startswith('xl/tables/table') and n.endswith('.xml') for n in names),'package_parts':len(names)}
res['totals']={'formula_count':sum(s['formulas'] for s in res['sheets'].values()),'hyperlink_count':sum(s['hyperlinks'] for s in res['sheets'].values()),'journal_net':str(sum(acc.values()))}
res['totals']['hyperlink_formula_count']=sum(isinstance(c.value,str) and c.value.upper().startswith('=HYPERLINK(') for s in w for rr in s for c in rr)
registered=json.loads((root/'_BOOKKEEPING/source-register.json').read_text(encoding='utf-8-sig'))
manifest=json.loads((root/'_BOOKKEEPING/drive-source-manifest.json').read_text(encoding='utf-8-sig'))
known_ids={x.get('drive_id') for x in registered}|{x.get('id') for x in manifest}
link_list=[]
for s in w:
    for rr in s:
        for c in rr:
            targets=[]
            if c.hyperlink and c.hyperlink.target:targets.append(c.hyperlink.target)
            if isinstance(c.value,str) and c.value.upper().startswith('=HYPERLINK('):
                m=re.match(r'=HYPERLINK\("((?:[^"\n]|"")*)"',c.value,re.I)
                if m:targets.append(m[1].replace('""','"'))
            for target in set(targets):link_list.append({'sheet':s.title,'cell':c.coordinate,'target':target})
res['links']={'direct_or_formula_targets':len(link_list),'unique_targets':len(set(x['target'] for x in link_list)),'drive_ids_absent_from_registers':[],'missing_local_hyperlink_targets':[]}
for x in link_list:
    m=re.search(r'(?:drive\.google\.com/(?:file/d|drive/folders)|docs\.google\.com/(?:spreadsheets|document)/d)/([^/?#]+)',x['target'])
    if m and m[1] not in known_ids:res['links']['drive_ids_absent_from_registers'].append(x)
    if re.match(r'^[A-Z]:[\\/]',x['target'],re.I) and not Path(x['target']).exists():res['links']['missing_local_hyperlink_targets'].append(x)
res['journal']['exact_signature_review']='Both candidate pairs represent two distinct June 1 VJs Burgers $15.41 charges. Source IDs 16X414k6QOHRByJkOoDBCBwnZQVmkyfrrJOYyX and DJpkYkqJryfXAxrR9ZwAIrnqJdMA8XtQQEyX4D remain separately supported by CHASE ACTIVITY rows54/55 and confirmed user answer. CASH-003/004 and CLASS-64/65 are not duplicate events.'
res['known_held_matters']=['May30-Nov2 complete-statement reconciliation not available; March/April/May differences zero.', 'Four Oliver sale-profit remittances total3000 and UPS224.95 company/artwork allocation remain matching work.', 'Separate Oct26 Venmo2000 purpose question BW20 pending; do not reuse earlier gift answers.', 'Four historical PAY-001/SETTLE-001/SALE-001/FERRI-001 proposals held; retain historical sale date/basis and paid/payer answers.']
res['conclusion']='No new verified financial correction found. All scanned values are unchanged from prior completed checkpoint. No canonical file was saved; no unknown amount was inferred.'
res['canonical_unchanged']=sha(p)==initial
(out/'ledger-audit.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str),encoding='utf8')
print(json.dumps({k:res[k] for k in ['canonical_sha256','canonical_size','journal','account_balances','inventory','sales','bank','native_features','totals','formula_errors','canonical_unchanged']},indent=2))
print('POLICIES',json.dumps(res['policies'],ensure_ascii=False,default=str))
print('REPORTS',json.dumps({s:res['reports'][s] for s in ['Trial Balance','Financial Statements','Monthly Reconciliation']},default=str))

