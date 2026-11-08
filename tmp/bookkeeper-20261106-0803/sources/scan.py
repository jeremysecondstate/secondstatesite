import csv, hashlib, json, os, zipfile, re
from pathlib import Path
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

ROOT=Path('J:/Shared drives/SECONDSTATE/THE BOOKS')
OUT=Path(__file__).parent
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
REGISTER=json.loads((ROOT/'_BOOKKEEPING/source-register.json').read_text('utf-8-sig'))
prior={str(Path(x['path'])).lower():x for x in REGISTER if x.get('path')}
now=datetime.now(timezone.utc).isoformat()
files=[];dirs=[];errors=[]
for cur,sub,names in os.walk(ROOT):
    if Path(cur)==ROOT/'_BOOKKEEPING':
        sub[:]=[d for d in sub if d=='evidence']
        names=[]
    dirs.append(str(Path(cur).relative_to(ROOT)))
    for name in sorted(names):
        p=Path(cur)/name
        if name.startswith('~$'): continue
        try:
            stat=p.stat(); h=hashlib.sha256(p.read_bytes()).hexdigest(); old=prior.get(str(p).lower())
            row={'path':str(p),'relative':str(p.relative_to(ROOT)),'size':stat.st_size,'modified_utc':datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),'sha256':h,'extension':p.suffix.lower(),'prior_match':bool(old),'status':('unchanged' if old.get('sha256')==h else 'changed') if old else 'new','verified_utc':now}
            if old:
                row.update({k:old.get(k) for k in ['review','method','text_file','visual_check','drive_id','drive_url']})
                row['prior_sha256']=old.get('sha256')
            files.append(row)
        except Exception as e: errors.append({'path':str(p),'error':str(e)})
(OUT/'local-source-scan.json').write_text(json.dumps({'verified_utc':now,'directories':dirs,'files':files,'errors':errors},indent=2),'utf-8')
print(json.dumps({'directories':len(dirs),'files':len(files),'statuses':{s:sum(r['status']==s for r in files) for s in ['unchanged','changed','new']},'errors':errors,'changed_new':[{k:r[k] for k in ['relative','status','size','sha256']} for r in files if r['status']!='unchanged'],'register_count':len(REGISTER)},indent=2))

def workbook(path):
    sheets=[]
    with zipfile.ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
        rels={e.attrib['Id']:e.attrib['Target'] for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        for s in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',NS):
            target=rels[s.attrib['{'+NS['r']+'}id']]
            target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            rows=[]
            for row in ET.fromstring(z.read(target)).findall('m:sheetData/m:row',NS):
                cells={}
                for c in row.findall('m:c',NS):
                    v=c.find('m:v',NS); value=v.text if v is not None else None
                    t=c.attrib.get('t')
                    if t=='s' and value is not None: value=strings[int(value)]
                    if t=='inlineStr':
                        inline=c.find('m:is',NS)
                        value=''.join(inline.itertext()) if inline is not None else None
                    f=c.find('m:f',NS)
                    if value is not None or f is not None: cells[c.attrib['r']]={'value':value,**({'formula':f.text} if f is not None else {})}
                if cells: rows.append({'row':int(row.attrib['r']),'cells':cells})
            sheets.append({'name':s.attrib['name'],'state':s.attrib.get('state','visible'),'row_count':len(rows),'rows':rows})
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'read_utc':now,'sheets':sheets}

books=[]
for row in files:
    if row['extension'] in ['.xlsx','.xlsm']:
        w=workbook(Path(row['path']))
        filename='workbook-'+re.sub(r'[^a-zA-Z0-9]+','-',row['relative'])+'.json'
        (OUT/filename).write_text(json.dumps(w,indent=2,ensure_ascii=False),'utf-8')
        books.append({'path':row['path'],'dump':filename,'sheets':[{k:s[k] for k in ['name','state','row_count']} for s in w['sheets']]})
(OUT/'workbook-index.json').write_text(json.dumps(books,indent=2,ensure_ascii=False),'utf-8')
print(json.dumps({'workbooks':books},indent=2))
