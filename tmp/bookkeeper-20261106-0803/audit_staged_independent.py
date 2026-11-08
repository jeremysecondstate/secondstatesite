import json, hashlib, collections
from pathlib import Path
from datetime import datetime, timezone

W=Path(__file__).parent
R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING')
P=W/'proposed-records'
names=['source-register.json','drive-source-manifest.json','run-summary.json']
def rd(p): return json.loads(p.read_text('utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def diff(a,b,p=''):
    if type(a)!=type(b): return [(p,a,b)]
    if isinstance(a,dict):
        out=[]
        for k in sorted(set(a)|set(b)): out.extend(diff(a.get(k),b.get(k),p+'/'+k))
        return out
    if isinstance(a,list):
        if len(a)!=len(b): return [(p,a,b)]
        out=[]
        for i,(x,y) in enumerate(zip(a,b)): out.extend(diff(x,y,p+'/'+str(i)))
        return out
    return [] if a==b else [(p,a,b)]

errors=[]; checks=[]
def check(condition,label):
    checks.append({'check':label,'passed':bool(condition)})
    if not condition: errors.append(label)

baseline=rd(W/'baseline-register-hashes.json')
check(len(baseline)==8,'Eight canonical baseline records included')
for name,h in baseline.items(): check(sha(R/name)==h,'Baseline unchanged: '+name)
check(sorted(p.name for p in P.iterdir())==sorted(names),'Only the three authorized review records are staged')

source_allowed={'last_cloud_verified_utc','last_full_review_utc','last_local_verified_utc','last_verified_utc','latest_run_verification','verification_method','cloud_sync_verification/checked_utc'}
manifest_allowed={'last_cloud_verified_utc','availability_observation/checked_utc'}
summary_allowed={'/completed_utc','/latest_native_validation/checked_utc','/latest_scheduled_audit/completed_utc','/latest_scheduled_audit/run_directory','/ledger_cloud_sync_verification/checked_utc','/native_pointer_availability/checked_utc','/previous_full_review_run','/record_backup_directory','/run_directory','/run_local_date','/source_content_review'}
deltas={}; counts={}
for name in names:
    old,new=rd(R/name),rd(P/name); delta=diff(old,new); deltas[name]=delta
    paths=[p for p,a,b in delta]
    relative=['/'.join(p.split('/')[2:]) for p in paths] if name!='run-summary.json' else paths
    allowed=source_allowed if name=='source-register.json' else manifest_allowed if name=='drive-source-manifest.json' else summary_allowed
    check(set(relative)<=allowed,'Metadata-only changes: '+name)
    counts[name]=dict(collections.Counter(relative))

local=rd(W/'sources/mapped-source-summary.json')
cloud=rd(W/'cloud/review-summary.json')
audit=rd(W/'ledger/ledger-audit.json')
native=rd(W/'ledger/native-audit.json')
matches=rd(W/'ledger/match-audit.json')
sourcecheck=rd(W/'ledger/source-checks.json')
summary=rd(P/'run-summary.json')
check(len(rd(P/'source-register.json'))==236,'236 source identities retained')
check(len(rd(P/'drive-source-manifest.json'))==396,'396 manifest identities retained')
check(all(x['status']=='PASS' for x in [cloud,native,matches,sourcecheck]),'Current cloud/native/match/source audits pass')
check(local['binary_hash_checks']=={'unchanged':233} and not local['new_files'] and not local['removed_files'],'Local source versions all unchanged')
check(cloud['source_files_listed']==235 and cloud['source_directories_including_root']==161 and cloud['native_chase_directly_read'],'Cloud 235 source files plus direct native Chase covered')
check(cloud['additional_equipment_register_reviewed'],'Equipment facts additionally reviewed without transaction discovery')
check(summary['local_source_files_checked']==235 and summary['current_cloud_source_files_checked']==236 and summary['local_hashed_files']==233 and summary['local_source_subfolders_checked']==160,'Current summary source coverage agrees')
check(summary['total_journal_entries']==audit['journal']['count']==511 and summary['total_journal_lines']==audit['journal']['lines']==1029,'Current summary journal counts agree')
check(not audit['journal']['imbalanced'] and not audit['journal']['unknown_accounts'] and not audit['journal']['duplicate_line_keys'] and not audit['formula_errors'],'Current accounting audit has no introduced errors')
check(summary['latest_native_validation']==native,'Latest native validation is the exact fresh report')
check(summary['source_observations']==276 and summary['posted_source_observations']==271 and summary['raw_pending_observations']==5 and summary['native_chase_observations_last_read']==138,'Current bank observation counts agree')
check(summary['latest_review_queue_status_counts']==matches['queue']['statuses'] and summary['review_items']==20 and summary['unresolved_later_bank_movements']==5,'Queue counts and remaining matching counts agree')
check(summary['pending_user_question']['id']=='BW-20' and summary['current_run']['pending_question_reasked'] is False,'Existing sole pending question preserved and not reasked')
check(summary['ledger_cash']==131.8 and abs(native['reports']['Financial Statements']['B20']-summary['ledger_cash'])<0.000001,'Cash summary agrees with native recalculation')
check(summary['balances_debit_positive']['Bank Review Clearing']==-14822.08 and summary['balances_debit_positive']['Venmo Settlement Clearing']==2017.75,'Current clearing balances agree')
check(summary['ledger_saved_this_run'] is False and summary['ledger_modified'] is False and summary['new_journal_entries']==0 and summary['current_run']['new_financial_entries']==0,'Summary accurately records no workbook or financial mutation')
check(summary['run_local_date']=='2026-11-06' and summary['run_directory'].endswith('2026-11-06-0803-source-and-ledger-review'),'Current date and run directory set')
check(summary['previous_full_review_run']==rd(R/'run-summary.json')['run_directory'],'Previous run reference advances correctly')
now=datetime.now(timezone.utc)
stamp=datetime.fromisoformat(summary['completed_utc'])
check(stamp.date()==now.date() and 0<=(now-stamp).total_seconds()<3600,'Staged review timestamp is current')
ledger=R.parent/'Second State Books — General Ledger.xlsm'
check(sha(ledger)==summary['ledger_sha256']==audit['canonical_sha256']==native['source_sha256']==cloud['ledger_cloud_sha256'],'Canonical ledger unchanged and agrees with all audits')
for name,h in baseline.items(): check(sha(R/name)==h,'Final baseline recheck: '+name)

result={'checked_utc':now.isoformat(),'status':'FAIL' if errors else 'PASS','record_sha256':{name:sha(P/name) for name in names},'errors':errors,'checks':checks,'changed_leaf_counts':counts,'financial_or_queue_or_source_identity_changes':False if not errors else 'See errors','canonical_writes_performed':False,'notes':['Historical raw provenance and settled decisions are unchanged.','Only review timestamps, review descriptions, and current/prior run paths changed.','Dated backups and publication remain parent-controlled final steps; no canonical record was written by this audit.']}
(W/'staging-audit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n','utf-8')
print(json.dumps({'status':result['status'],'checks':len(checks),'errors':errors,'record_sha256':result['record_sha256']},indent=2))
