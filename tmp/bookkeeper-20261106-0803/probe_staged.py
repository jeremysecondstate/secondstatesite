import json,collections
from pathlib import Path
W=Path('C:/dev/secondstatesite/tmp/bookkeeper-20261106-0803');R=Path('J:/Shared drives/SECONDSTATE/THE BOOKS/_BOOKKEEPING')
def rd(p):return json.loads(p.read_text('utf-8-sig'))
def diff(a,b,p=''):
 if type(a)!=type(b):return [(p,a,b)]
 if isinstance(a,dict):
  out=[]
  for k in sorted(set(a)|set(b)):
   out += diff(a.get(k),b.get(k),p+'/'+k)
  return out
 if isinstance(a,list):
  if len(a)!=len(b):return [(p,a,b)]
  return sum([diff(x,y,p+'/'+str(i)) for i,(x,y) in enumerate(zip(a,b))],[])
 return [] if a==b else [(p,a,b)]
for name in ['source-register.json','drive-source-manifest.json','run-summary.json']:
 d=diff(rd(R/name),rd(W/'proposed-records'/name));print(name,'changes',len(d))
 if name!='run-summary.json':print(collections.Counter('/'.join(p.split('/')[2:]) for p,a,b in d))
 else:
  for p,a,b in d: print(p,repr(a)[:220],'=>',repr(b)[:220])
print('SUMMARY TOP KEYS',list(rd(W/'proposed-records/run-summary.json')))