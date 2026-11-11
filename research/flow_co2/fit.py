import sys,statistics as st,math
sys.argv=[0,'../../data/hist.json']
exec(open('analyze.py').read().split("print('days'")[0])
import numpy as np
for k in ('CO2','FLOW'):
  print('==',k,'h  a  b(level)  postDummy  rmse_fit  rmse_persist  med_post')
  for h in range(15*60,17*60+41,10):
    R=[r for r in rows if r['h']==h]
    y=np.array([r[k+'S']-r[k+'0'] for r in R]); x=np.array([r[k+'0'] for r in R]); p=np.array([r['post'] for r in R],float)
    X=np.c_[np.ones(len(y)),x-1000,p]; c,*_=np.linalg.lstsq(X,y,rcond=None)
    # LOO rmse
    e=[]
    for i in range(len(y)):
      m=np.arange(len(y))!=i; ci,*_=np.linalg.lstsq(X[m],y[m],rcond=None); e.append(y[i]-X[i]@ci)
    e=np.array(e); ep=y[p==1]-np.median(y[p==1])
    print('  %02d:%02d %7.1f %6.3f %7.1f  %6.1f %6.1f %6.1f  postLOO %6.1f'%(h//60,h%60,*c,math.sqrt((e**2).mean()),math.sqrt((y**2).mean()),np.median(y[p==1]),math.sqrt((e[p==1]**2).mean())))
