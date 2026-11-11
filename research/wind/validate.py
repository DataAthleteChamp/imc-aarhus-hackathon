import json, sys, collections, numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, sys.argv[2]); import model_wind as M
tz=ZoneInfo('Europe/Copenhagen')
d=json.load(open(sys.argv[1]))['records']
days=collections.defaultdict(dict)
for r in d:
    if r['OnshoreWindPower'] is None or r['OffshoreWindPower'] is None: continue
    days[r['Minutes1DK'][:10]][r['Minutes1DK']]=(r['OnshoreWindPower']+r['OffshoreWindPower'])/3
res=collections.defaultdict(list)
for day,w in sorted(days.items()):
    rows=[{'t':datetime.fromisoformat(k).replace(tzinfo=tz),'1_WIND':v} for k,v in sorted(w.items())]
    rows=[r for r in rows if 13<=r['t'].hour<18]
    tg=[r['1_WIND'] for r in rows if r['t'].hour==17 and 40<=r['t'].minute<45]
    se=[r['1_WIND'] for r in rows if (r['t'].hour,r['t'].minute)>=(15,0) and (r['t'].hour,r['t'].minute)<=(17,45)]
    if len(tg)<5 or len(se)<160: continue
    tg=np.mean(tg); FR=max(se)-min(se)
    for hm in [(15,0),(15,30),(16,0),(16,30),(17,0),(17,20),(17,30),(17,38)]:
        now=datetime(*map(int,day.split('-')),*hm,tzinfo=tz)
        f,s=M.wind_fair(rows,now); g,gs,fl=M.range_fair(rows,now)
        res[hm].append(((tg-f)/s,tg-f,(FR-g)/gs,FR-g,s,gs))
for hm,v in res.items():
    v=np.array(v)
    print('%02d:%02d wind z-sd %.2f rmse %.0f meansig %.0f | range z-sd %.2f bias %.0f rmse %.0f meansig %.0f'%(*hm,v[:,0].std(),np.sqrt((v[:,1]**2).mean()),v[:,4].mean(),v[:,2].std(),v[:,3].mean(),np.sqrt((v[:,3]**2).mean()),v[:,5].mean()))
