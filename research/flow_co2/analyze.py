import json,sys,math,statistics as st
from datetime import datetime,date
from collections import defaultdict
d=json.load(open(sys.argv[1]))['records']
days=defaultdict(dict)
for r in d:
    t=datetime.fromisoformat(r['Minutes1DK']); 
    days[t.date()][t.hour*60+t.minute]=r
SET=[17*60+40+i for i in range(5)]
def val(r,k):
    if k=='CO2': return r['CO2Emission']*10
    if k=='FLOW': return 1000+r['Exchange_Sum']/3
    if k=='WIND': return ((r['OnshoreWindPower'] or 0)+(r['OffshoreWindPower'] or 0))/3
rows=[]
for dd,m in sorted(days.items()):
    if not all(s in m for s in SET): continue
    try: S={k:st.mean(val(m[s],k) for s in SET) for k in ('CO2','FLOW','WIND')}
    except TypeError: continue
    for h in range(15*60,17*60+41,10):
        if h not in m: continue
        try: rows.append(dict(day=dd,wd=dd.weekday(),h=h,post=dd>=date(2025,10,26) if dd.year==2025 else dd>=date(2026,10,25),
            **{k+'0':val(m[h],k) for k in S},**{k+'S':S[k] for k in S}))
        except TypeError: pass
print('days',sorted({r['day'] for r in rows})[0],sorted({r['day'] for r in rows})[-1],len({r['day'] for r in rows}))
def rob(x): 
    x=sorted(x); return (x[int(.75*len(x))]-x[int(.25*len(x))])/1.349
for k in ('CO2','FLOW','WIND'):
  print('==',k)
  for sub in ('all','post'):
    print(' ',sub,'h  n  meanDrift  sd  rmsePersist  robsd')
    for h in range(15*60,17*60+41,20):
      R=[r for r in rows if r['h']==h and (sub=='all' or r['post'])]
      dr=[r[k+'S']-r[k+'0'] for r in R]
      if len(dr)<3: continue
      print('  %02d:%02d %3d %8.1f %7.1f %7.1f %7.1f'%(h//60,h%60,len(dr),st.mean(dr),st.stdev(dr),math.sqrt(st.mean([x*x for x in dr])),rob(dr)))
# correlations of drifts at 15:30 and 16:30 
for h in (15*60+30,16*60+30,17*60):
  R=[r for r in rows if r['h']==h]
  D={k:[r[k+'S']-r[k+'0'] for r in R] for k in ('CO2','FLOW','WIND')}
  c=lambda a,b: st.correlation(D[a],D[b])
  E=[D['CO2'][i]+D['FLOW'][i]+D['WIND'][i] for i in range(len(R))]
  print('h',h//60,h%60,'corr co2-flow %.2f co2-wind %.2f flow-wind %.2f'%(c('CO2','FLOW'),c('CO2','WIND'),c('FLOW','WIND')),'sdETF %.1f sumsd %.1f rss %.1f'%(st.stdev(E),sum(st.stdev(D[k]) for k in D),math.sqrt(sum(st.variance(D[k]) for k in D))))
  # regress flow drift on wind level, flow level, co2 level
  for k in ('FLOW','CO2'):
    for x in ('WIND0','FLOW0','CO20'):
      print('   drift',k,'vs',x,'corr %.2f'%st.correlation([r[x] for r in R],D[k]))
# per day post listing at 15:30
print('per-day 15:30 post:')
for r in rows:
  if r['h']==15*60+30 and r['post']: print(' ',r['day'],r['wd'],'wind %.0f co2 %.0f->%.0f flow %.0f->%.0f'%(r['WIND0'],r['CO20'],r['CO2S'],r['FLOW0'],r['FLOWS']))
