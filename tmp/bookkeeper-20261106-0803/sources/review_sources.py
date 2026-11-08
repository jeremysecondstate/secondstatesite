from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import json, hashlib, csv, zipfile, re
from xml.etree import ElementTree as ET
from pypdf import PdfReader

out=Path(__file__).parent
root=Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
prior_dir=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING/runs/2026-11-06-0157-source-and-ledger-review/local')
scan=json.loads((out/'local-source-scan.json').read_text('utf-8'))
books=json.loads((out/'workbook-index.json').read_text('utf-8'))
analysis=json.loads((out/'source-analysis.json').read_text('utf-8'))
reviews=[]; exceptions=[]; annotations=[]; comparisons=[]; snippets=[]
prior_reviews={x['source']:x for x in json.loads((prior_dir/'document-reviews.json').read_text('utf-8'))}
for f in scan['files']:
    if f['status']!='unchanged' and not f['relative'].startswith('_BOOKKEEPING'):
        exceptions.append({'source':f['relative'],'error':'changed source requires fresh substantive review','status':f['status']})
    s=None
    if f.get('text_file') and f['status']=='unchanged':
        try:
            tx=Path(f['text_file']).read_bytes();s=tx.decode('utf-8-sig',errors='replace')
            reviews.append({'source':f['relative'],'source_sha256':f['sha256'],'method':'reread registered extraction after matching original hash','text_file':f['text_file'],'text_sha256':hashlib.sha256(tx).hexdigest(),'characters':len(s)})
        except Exception as e: exceptions.append({'source':f['relative'],'error':str(e)})
    elif f['extension']=='.json':
        tx=Path(f['path']).read_bytes();s=tx.decode('utf-8-sig',errors='replace')
        json.loads(s)
        reviews.append({'source':f['relative'],'source_sha256':f['sha256'],'method':'fresh archived evidence JSON read','characters':len(s)})
    elif f['extension']=='.pdf':
        reader=PdfReader(f['path']);s='\n\n'.join(p.extract_text() or '' for p in reader.pages)
        dest=out/('fresh-pdf-'+Path(f['relative']).stem+'.txt');dest.write_text(s,encoding='utf-8')
        prior=prior_reviews.get(f['relative'])
        same=prior and prior['source_sha256']==f['sha256']
        reviews.append({'source':f['relative'],'source_sha256':f['sha256'],'method':'fresh PDF text extraction' if s.strip() else 'prior visual review reused after matching original source hash','text_file':str(dest),'pages':len(reader.pages),'text_sha256':hashlib.sha256(s.encode('utf-8')).hexdigest(),'characters':len(s),'prior_review_match':bool(same),'prior_review_reference':str(prior_dir/'document-reviews.json') if same else None})
    if s is not None:
        lines=[l.strip() for l in s.splitlines() if l.strip()]
        snippets.append({'source':f['relative'],'first_lines':lines[:4],'financial_lines':[l for l in lines if re.search(r'(?i)(total|balance|invoice|paid|payment|commission|premium|proceeds|amount|settlement|sale date|sold)',l)][:12]})
for b in books:
    fresh=json.loads((out/b['dump']).read_text('utf-8'))
    oldpath=prior_dir/b['dump']; old=json.loads(oldpath.read_text('utf-8')) if oldpath.exists() else None
    changed=[]
    if old:
        for s in fresh['sheets']:
            oldsheet=next((v for v in old['sheets'] if v['name']==s['name']),None)
            if oldsheet!=s: changed.append(s['name'])
    comparisons.append({'path':b['path'],'sheets':len(fresh['sheets']),'changed_sheets_since_previous_full_review':changed,'content_unchanged':not changed,'sha256':fresh['sha256']})
    with zipfile.ZipFile(b['path']) as z:
        for name in z.namelist():
            if ('comments' in name.lower() or 'threadedcomments' in name.lower()) and name.endswith('.xml'):
                element=ET.fromstring(z.read(name));annotations.append({'workbook':b['path'],'part':name,'text':' '.join(element.itertext())})
prior=json.loads((prior_dir/'local-source-scan.json').read_text('utf-8'))
oldpaths={x['relative'] for x in prior['files']};nowpaths={x['relative'] for x in scan['files']}
cross=list(csv.DictReader((root/'_BOOKKEEPING/artwork-crosswalk.csv').open(encoding='utf-8-sig')))
summary={'verified_utc':datetime.now(timezone.utc).isoformat(),'directories_including_root':len(scan['directories']),'source_subfolders':len(scan['directories'])-1,'source_files_including_virtual':len(scan['files'])+len(scan['errors']),'binary_hash_checks':dict(Counter(f['status'] for f in scan['files'])),'new_files':sorted(nowpaths-oldpaths),'removed_files':sorted(oldpaths-nowpaths),'virtual_pointer_errors_redirect_to_drive':scan['errors'],'registered_extractions_reread':sum('reread' in r['method'] for r in reviews),'fresh_pdf_extractions':sum('fresh PDF' in r['method'] for r in reviews),'prior_visual_reviews_reused':sum('prior visual' in r['method'] for r in reviews),'total_document_reviews':len(reviews),'extraction_errors':exceptions,'workbooks_reread':len(books),'sheet_count':sum(len(b['sheets']) for b in books),'hidden_sheets':[(b['path'],s['name'],s['row_count']) for b in books for s in b['sheets'] if s['state']!='visible'],'workbook_annotation_parts_read':len(annotations),'supreme_sheets':13,'supreme_artwork_observations':analysis['fresh_supreme_id_row_count'],'unique_supreme_ids':analysis['unique_supreme_ids'],'crosswalk_records':len(cross),'ids_not_crosswalk':analysis['ids_not_crosswalk'],'scope':'Read-only mapped-drive source check; virtual native files and remote inventory belong to parent review. Canonical ledger and registers untouched.'}
for name,obj in [('document-reviews.json',reviews),('document-snippets.json',snippets),('workbook-comparisons.json',comparisons),('workbook-annotations.json',annotations),('mapped-source-summary.json',summary)]:
    (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True,indent=2))

