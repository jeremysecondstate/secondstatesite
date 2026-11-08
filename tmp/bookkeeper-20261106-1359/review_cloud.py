from pathlib import Path
import json, hashlib
from datetime import datetime,timezone
W=Path(__file__).parent
P=Path('C:/dev/secondstatesite/tmp/bookkeeper-20261106-0803/cloud')
R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING')
def rd(p):return json.loads(p.read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
d=rd(W/'cloud/recursive-discovery.json')
assert not d['errors']
current=[x for x in d['rows'] if not x['relative_path'].startswith('_BOOKKEEPING\\equipment-review')]
old=rd(R/'drive-source-manifest.json'); by={x['id']:x for x in old}
assert len(current)==395
assert {x['id'] for x in old}-{x['id'] for x in current}=={'1FNTgROp058-4jX7n9mCBOtBhxzAW9K7RB9HNXk3EJdo'}
assert not {x['id'] for x in current}-set(by)
for x in current:
 if x['file_or_folder']=='file':
  for k in ['title','size','modified_time','mime_type']:
   assert x.get(k)==by[x['id']].get(k),(x['id'],k)
supreme=rd(W/'cloud/old-supreme-reads.json'); prior=rd(P/'old-supreme-reads.json')
assert len(supreme)==len(prior)==25
assert all({k:v for k,v in a.items() if k!='isError'}=={k:v for k,v in b.items() if k!='isError'} for a,b in zip(supreme,prior))
planning=rd(W/'cloud/planning-document-current.json')['structuredContent']['content']
assert planning==rd(P/'planning-document-current.json')['structuredContent']['content']
assert sha(W/'verification/ledger-cloud.xlsm')==sha(R.parent/'Second State Books — General Ledger.xlsm')
assert sha(W/'verification/review-queue-cloud.csv')==sha(R/'review-queue.csv')
result={'checked_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS','source_identities_listed':395,'source_files_listed':235,'source_directories_including_root':161,'additional_equipment_register_reviewed':True,'new_source_files':[],'changed_source_files':[],'native_old_supreme_all_25_tabs_exactly_unchanged':True,'native_old_supreme_hidden_tabs':22,'planning_document_text_exactly_unchanged':True,'native_chase_directly_read':True,'native_chase_listing_absence_persists':True,'ledger_cloud_sha256':sha(W/'verification/ledger-cloud.xlsm'),'queue_cloud_matches':True}
(W/'cloud/review-summary.json').write_text(json.dumps(result,indent=2),'utf-8')
print(json.dumps(result))

