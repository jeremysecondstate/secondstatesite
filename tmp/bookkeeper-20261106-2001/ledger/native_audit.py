from pathlib import Path
from datetime import datetime,timezone
import os,sys,hashlib,shutil,json,time,openpyxl
out=Path(__file__).parent
deps=Path('C:/Users/WS 7950X/.codex/automations/bookie-worker/run-20261104-1357/native-deps')
sys.path[:0]=[str(deps),str(deps/'win32'),str(deps/'win32/lib'),str(deps/'pythonwin')]
dll=os.add_dll_directory(str(deps/'pywin32_system32'))
import win32com.client
p=next(Path('J:/Shared drives/SECONDSTATE/THE BOOKS').glob('*General Ledger.xlsm'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
initial=sha(p);copy=out/'ledger-recalc-copy.xlsm';shutil.copy2(p,copy)
w=openpyxl.load_workbook(copy,read_only=True,data_only=False)
v=openpyxl.load_workbook(copy,read_only=True,data_only=True)
fs={s.title:[(c.coordinate,c.row,c.column) for rr in s for c in rr if c.data_type=='f'] for s in w}
cached={s.title:{c.coordinate:c.value for rr in s for c in rr if c.value is not None} for s in v}
w.close();v.close()
app=win32com.client.DispatchEx('Excel.Application');app.Visible=False;app.DisplayAlerts=False;app.EnableEvents=False;app.AutomationSecurity=3
book=None
res={'checked_utc':datetime.now(timezone.utc).isoformat(),'engine':'Microsoft Excel '+app.Version,'source_sha256':initial,'macros_disabled':True,'links_updated':False,'save_called':False,'formula_differences':[],'formula_errors':[]}
def same(a,b):
    if a in (None,'') and b in (None,''):return True
    return abs(a-b)<1e-6 if isinstance(a,(int,float)) and isinstance(b,(int,float)) else a==b
try:
    book=app.Workbooks.Open(str(copy),UpdateLinks=0,ReadOnly=True)
    assert book.ReadOnly and book.FileFormat==52
    res['read_only']=bool(book.ReadOnly);res['file_format']=book.FileFormat
    app.CalculateFullRebuild();deadline=time.monotonic()+60
    while app.CalculationState!=0:
        if time.monotonic()>deadline:raise RuntimeError('Recalculation timeout')
        time.sleep(.2)
    res['full_rebuild_completed']=True
    for sn,cells in fs.items():
        if not cells:continue
        s=book.Worksheets(sn);lastrow=max(r for a,r,c in cells);lastcol=max(c for a,r,c in cells)
        vals=s.Range(s.Cells(1,1),s.Cells(lastrow,lastcol)).Value2
        for a,r,c in cells:
            actual=vals[r-1][c-1];old=cached[sn].get(a)
            if not same(actual,old):res['formula_differences'].append({'sheet':sn,'cell':a,'cached':old,'calculated':actual})
            if isinstance(actual,int) and actual<=-2146826000:res['formula_errors'].append([sn,a,actual])
    targets={'Dashboard':['B6','B7','B8','B9','B10','B11','B13','B14','B18'],'Trial Balance':['E26'],'Financial Statements':['D16','B17','B20','B21','B22','B24','B25','B27','B28','B30','B37']}
    res['reports']={sn:{a:book.Worksheets(sn).Range(a).Value2 for a in addrs} for sn,addrs in targets.items()}
    assert abs(res['reports']['Trial Balance']['E26'])<1e-6 and abs(res['reports']['Financial Statements']['B37'])<1e-6
    book.Close(False);book=None
    book=app.Workbooks.Open(str(copy),UpdateLinks=0,ReadOnly=True)
    res['reopened_read_only']=bool(book.ReadOnly)
    res['reopened_check']={'trial_balance':book.Worksheets('Trial Balance').Range('E26').Value2,'balance_sheet':book.Worksheets('Financial Statements').Range('B37').Value2}
finally:
    if book is not None:book.Close(False)
    app.Quit()
res['source_unchanged']=sha(p)==initial;res['copy_unchanged']=sha(copy)==initial
res['status']='PASS' if res['source_unchanged'] and res['copy_unchanged'] and not res['formula_differences'] and not res['formula_errors'] else 'FAIL'
(out/'native-audit.json').write_text(json.dumps(res,indent=2,default=str),encoding='utf8')
print(json.dumps(res,indent=2,default=str))

