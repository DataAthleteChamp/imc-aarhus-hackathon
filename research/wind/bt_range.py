import json, numpy as np
R=json.load(open('/tmp/rng.json'))
rs=np.random.default_rng(0)
def mc(dmax,dmin,vol,T,n=4000):
    steps=rs.normal(0,vol,(n,T)); p=np.cumsum(steps,1)
    up=np.maximum(p.max(1)-dmax,0); dn=np.maximum(-p.min(1)-dmin,0)
    return up+dn
for k in (1.0,2.0,3.0):
  out=[]
  for t,rows in R.items():
    t=int(t)
    if t%30: continue
    inc=[];pred=[]
    for (r,f,dmax,dmin,rv,T) in rows:
        inc.append(f-r); pred.append(mc(dmax,dmin,k*rv*1.0,T,1000).mean() if T>0 else 0)
    inc=np.array(inc);pred=np.array(pred)
    out.append((t,T,inc.mean(),np.median(inc),inc.std(),pred.mean(),np.sqrt(((inc-pred)**2).mean())))
  print('k',k)
  for o in out: print('%d:%02d T=%3d inc mean %.0f med %.0f sd %.0f | MC mean %.0f rmse %.0f'%(o[0]//60,o[0]%60,*o[1:]))
