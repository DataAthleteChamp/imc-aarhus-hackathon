import sys; sys.path.insert(0,'.')
import numpy as np
from load import load
from a import nowc
D=load(); days=sorted(D)
err={h:{'dir':[],'bu':[],'pers':[]} for h in (1,2,3)}; B={h:[] for h in (1,2,3)}
for dd in days:
    a=D[dd]
    for i in range(15*60,17*60+40):
        for h in (1,2,3):
            y=a[i+h,3]; d=nowc(a[:,3],i,h); bu=sum(nowc(a[:,j],i,h) for j in range(3))
            err[h]['dir'].append(d-y); err[h]['bu'].append(bu-y); err[h]['pers'].append(a[i,3]-y)
for h in (1,2,3):
    e=err[h]; ed,eb=np.array(e['dir']),np.array(e['bu'])
    # MinT-ish: optimal combo weight w*dir+(1-w)*bu
    C=np.cov(ed,eb); w=(C[1,1]-C[0,1])/(C[0,0]+C[1,1]-2*C[0,1]); ec=w*ed+(1-w)*eb
    r=lambda v:np.sqrt(np.mean(np.square(v)))
    print('h%d RMSE pers %.2f direct %.2f bottomup %.2f combo(w_dir=%.2f) %.2f'%(h,r(e['pers']),r(ed),r(eb),w,r(ec)))
# settlement from 17:30 (info to 17:28): persistence vs direct vs bottom-up path
for name in ['pers','dir','bu']:
    es=[]
    for dd in days:
        a=D[dd]; i=17*60+28; S=a[17*60+40:17*60+45,3].mean()
        if name=='pers': f=a[i,3]
        elif name=='dir': f=np.mean([nowc(a[:,3],i,h) for h in range(12,17)])
        else: f=sum(np.mean([nowc(a[:,j],i,h) for h in range(12,17)]) for j in range(3))
        es.append(f-S)
    print('settle@17:30', name, 'RMSE %.1f'%np.sqrt(np.mean(np.square(es))))
