import itertools, sys
sys.argv=['x']
exec(open(__file__.replace('rank2.py','grid.py')).read().split('days = sorted(C)')[0])
days = sorted(C)
p='2_CO2'
res=[]
for thr, size, hold, cap in itertools.product([6,8,10,14,20],[3,5,10],[1,2,3,0],[30,50]):
    r={lag:summ([gap_day(C[d],p,thr,size,hold,cap,lag) for d in days]) for lag in (1,2)}
    res.append(((thr,size,hold,cap),r))
res.sort(key=lambda x:(x[1][1][3]+x[1][2][3], -x[1][1][1]))
for cfg,r in res[:12]:
    print(cfg, ' '.join(f'{a:.2f} {b:7.0f} {c:6.0f} {e:.2f} |' for a,b,c,e in (r[1],r[2])))
for thr in [6,8,10]:
  print(thr, [round(gap_day(C[d],p,thr,10,3,30,1)) for d in days])
