from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,shutil,sys,os
W=Path(__file__).parent; R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING'); B=R.parent
OUT=R/'runs/2026-11-06-1359-source-and-ledger-review'; P=W/'proposed-records'
def rd(p):return json.loads(p.read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False,default=str)+'\n','utf-8')
baseline=rd(W/'baseline-register-hashes.json')
for n,h in baseline.items():assert sha(R/n)==h,'Concurrent register change: '+n
ledger=B/'Second State Books — General Ledger.xlsm'
native=rd(W/'ledger/native-audit.json'); audit=rd(W/'ledger/ledger-audit.json'); local=rd(W/'sources/mapped-source-summary.json'); cloud=rd(W/'cloud/review-summary.json')
assert native['status']==cloud['status']=='PASS' and native['source_unchanged']
assert not audit['journal']['imbalanced'] and not audit['journal']['unknown_accounts'] and not audit['journal']['duplicate_line_keys'] and not audit['formula_errors']
assert local['binary_hash_checks']=={'unchanged':233} and not local['new_files'] and not local['removed_files']
assert sha(ledger)==native['source_sha256']==sha(W/'verification/ledger-cloud.xlsm')
assert sha(R/'review-queue.csv')==sha(W/'verification/review-queue-cloud.csv')
if '--publish' not in sys.argv:
 now=datetime.now(timezone.utc).isoformat()
 sources=rd(R/'source-register.json'); manifest=rd(R/'drive-source-manifest.json'); summary=rd(R/'run-summary.json')
 assert len(sources)==236 and len(manifest)==396
 method='Fresh mapped-file hashes and recursive Drive versions; nine workbooks/55 sheets, native Chase, all 25 historical native SUPREME tabs including 22 hidden tabs and planning document reviewed. 146 hash-matched extracts reread and 15 PDFs freshly extracted; unchanged visual conclusions retained.'
 for x in sources:
  for k in ['last_verified_utc','last_full_review_utc','last_cloud_verified_utc']:x[k]=now
  if x.get('last_local_verified_utc'):x['last_local_verified_utc']=now
  x['verification_method']=method
  x['latest_run_verification']='No changed source activity or newly supported transaction/correction; current review evidence is in runs/2026-11-06-1359-source-and-ledger-review.'
  if x.get('drive_id')=='1_MOhIuKfrvU6AHjA4RtKUq9QqqmwNYUe':x['cloud_sync_verification'].update(checked_utc=now,local_sha256=sha(ledger),remote_sha256=sha(ledger))
 for x in manifest:
  x['last_cloud_verified_utc']=now
  if x['id']=='1FNTgROp058-4jX7n9mCBOtBhxzAW9K7RB9HNXk3EJdo':x['availability_observation']['checked_utc']=now
 previous=summary['run_directory']
 summary.update(completed_utc=now,run_local_date='2026-11-06',run_directory=str(OUT),previous_full_review_run=previous,
  source_content_review=method,ledger_sha256=sha(ledger),ledger_before_sha256=sha(ledger),ledger_saved_this_run=False,ledger_modified=False,
  record_backup_directory=str(OUT/'before-records'),latest_native_validation=native,
  latest_scheduled_audit={'completed_utc':now,'run_directory':str(OUT),'ledger_sha256':sha(ledger),'passed':True,'new_journal_entries':0},
  ledger_cloud_sync_verification={'checked_utc':now,'sha256':sha(ledger),'size':ledger.stat().st_size,'matches_local':True,'method':'Fresh Drive download SHA256 matches canonical ledger'},
  current_run={'evidence_registered':0,'manifest_identities_added':0,'canonical_workbook_unchanged':True,'native_read_only_recalculation_passed':True,'new_financial_entries':0,'pending_question_reasked':False},
  saved_registers=['source-register.json','drive-source-manifest.json','run-summary.json'],
  unchanged_registers=['review-queue.csv','artwork-crosswalk.csv','transaction-matches.csv','chase-source-matches.csv','transaction-review.csv'])
 summary['native_pointer_availability']['checked_utc']=now
 P.mkdir(exist_ok=True)
 for n,x in [('source-register.json',sources),('drive-source-manifest.json',manifest),('run-summary.json',summary)]:dump(P/n,x)
 dump(W/'staging-summary.json',{'prepared_utc':now,'sources':236,'manifest':396,'changed_records':summary['saved_registers'],'ledger_sha256':sha(ledger),'canonical_workbook_changed':False})
 print('Three review metadata records staged; no ledger or queue changes.')
 sys.exit(0)
stage=rd(W/'staging-audit.json'); assert stage['status']=='PASS'
for n,h in stage['record_sha256'].items():assert sha(P/n)==h
deps=Path('C:/Users/WS 7950X/.codex/automations/bookie-worker/run-20261104-1357/native-deps')
sys.path[:0]=[str(deps),str(deps/'win32'),str(deps/'win32/lib')]
dll=os.add_dll_directory(str(deps/'pywin32_system32'))
import win32file,win32con
OUT.mkdir(parents=True,exist_ok=False); (OUT/'before-records').mkdir()
for n in baseline:shutil.copy2(R/n,OUT/'before-records'/n)
written=[]
for n,expected in stage['record_sha256'].items():
 data=(P/n).read_bytes(); h=win32file.CreateFile(str(R/n),win32con.GENERIC_READ|win32con.GENERIC_WRITE,0,None,win32con.OPEN_EXISTING,win32con.FILE_ATTRIBUTE_NORMAL,None)
 started=False; old=None
 try:
  _,old=win32file.ReadFile(h,win32file.GetFileSize(h)); assert hashlib.sha256(old).hexdigest()==baseline[n]
  started=True; win32file.SetFilePointer(h,0,win32con.FILE_BEGIN);win32file.WriteFile(h,data);win32file.SetEndOfFile(h);win32file.FlushFileBuffers(h)
 except Exception:
  if started and old is not None:
   win32file.SetFilePointer(h,0,win32con.FILE_BEGIN);win32file.WriteFile(h,old);win32file.SetEndOfFile(h);win32file.FlushFileBuffers(h)
  raise
 finally:h.Close()
 assert sha(R/n)==expected
 written.append({'name':n,'sha256':expected})
for n in baseline:
 if n not in stage['record_sha256']:assert sha(R/n)==baseline[n]
assert sha(ledger)==native['source_sha256']
dump(W/'publish-records.json',{'published_utc':datetime.now(timezone.utc).isoformat(),'run_directory':str(OUT),'exclusive_concurrent_guards':True,'written':written,'ledger_unchanged':True})
print('Three reviewed records published with dated backups and exclusive concurrency checks.')
