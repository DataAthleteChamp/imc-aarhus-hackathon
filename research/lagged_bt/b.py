import sys; sys.path.insert(0,'.'); sys.path.insert(0,'../..')
import numpy as np, itertools
from datetime import datetime
from zoneinfo import ZoneInfo
from load import load, HS, P
from endgame import endgame_fair
TZ=ZoneInfo('Europe/Copenhagen')
D=load(); days=sorted(D)
# precompute fairs per day per minute T (info = rows up to T-2)
F={}
for dd in days:
    a=D[dd]; y,mo,da=map(int,dd.split('-'))
    rows=[{'t':datetime(y,mo,da,m//60,m%60,tzinfo=TZ),'1_WIND':a[m,0],'2_CO2':a[m,1],'3_FLOW':a[m,2]} for m in range(13*60,17*60+45)]
    for T in range(17*60+15,17*60+45):
        vis=rows[:T-2-13*60+1]; now=datetime(y,mo,da,T//60,T%60,tzinfo=TZ)
        F[dd,T]=endgame_fair(vis,now)
    F[dd,'S']=a[17*60+40:17*60+45].mean(0)
res={}
for t0,k,cap in itertools.product([17*60+20,17*60+30,17*60+35,17*60+38],[0.5,1,2],[50,100]):
    for pi,p in enumerate(P):
        hs=HS[p]; out=[]
        for dd in days:
            x=D[dd][:,pi]; pos=0; pnl=0; S=F[dd,'S'][pi]
            for T in range(t0,17*60+45):
                f,s=F[dd,T][p]; mid=x[T-2]
                for _ in range(4):  # up to 20 lots/min (4 levels-ish), crude
                    if f-(mid+hs)>k*s and pos+5<=cap: pos+=5; pnl+=5*(S-(mid+hs))
                    elif (mid-hs)-f>k*s and pos-5>=-cap: pos-=5; pnl+=5*((mid-hs)-S)
                    else: break
            out.append(pnl)
        res[t0,k,cap,p]=np.array(out)
for p in P:
    rs=sorted(((v.mean(),v.std(),(v<0).mean(),key[:3]) for key,v in res.items() if key[3]==p),key=lambda z:-z[0])
    print(p); [print('  mean %.0f sd %.0f lose %.2f'%r[:3], 't0=%d:%02d k=%s cap=%d'%(r[3][0]//60,r[3][0]%60,r[3][1],r[3][2])) for r in rs[:4]]
    for t0 in [17*60+20,17*60+30,17*60+35,17*60+38]:
        v=res[t0,1,50,p]; print('   t0 %d k1 cap50: mean %.0f lose %.2f'%(t0%60,v.mean(),(v<0).mean()))
