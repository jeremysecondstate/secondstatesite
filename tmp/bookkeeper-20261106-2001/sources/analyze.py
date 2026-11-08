import csv,json,re
from pathlib import Path
from collections import Counter
P=Path(__file__).parent
R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING')
w=json.loads((P/'workbook-SUPREME-xlsm.json').read_text('utf-8'))
cross=list(csv.DictReader((R/'artwork-crosswalk.csv').open(encoding='utf-8-sig')))
ids={x['supreme_id'] for x in cross}
matches=[];unknown=[]
for s in w['sheets']:
    for row in s['rows']:
        vals={re.sub(r'\d+','',k):v['value'] for k,v in row['cells'].items()}
        found=[v for v in vals.values() if v and re.fullmatch(r'SS-[A-Z0-9]{8}',str(v))]
        if found:
            obj={'sheet':s['name'],'row':row['row'],'ids':found,'values':vals}
            matches.append(obj)
            if any(x not in ids for x in found): unknown.append(obj)
old=json.loads((P/'workbook-MISC-old-SUPREME-EXCEL-xlsx.json').read_text('utf-8'))
hidden=[s for s in old['sheets'] if s['state']!='visible']
q=list(csv.DictReader((R/'review-queue.csv').open(encoding='utf-8-sig')))
out={'fresh_supreme_id_row_count':len(matches),'unique_supreme_ids':len({v for x in matches for v in x['ids']}),'crosswalk_records':len(cross),'ids_not_crosswalk':unknown,'substantive_hidden_sheets':hidden,'queue_status_counts':dict(Counter(x['status'] for x in q)),'queue_open':[{k:x[k] for k in ['id','record','amount','information_needed','status']} for x in q if x['status']!='Resolved']}
(P/'source-analysis.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),'utf-8')
print(json.dumps(out,indent=2,ensure_ascii=True))

