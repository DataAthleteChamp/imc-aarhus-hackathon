import json, sys, numpy as np, collections
d=json.load(open(sys.argv[1]))['records']
days=collections.defaultdict(dict)
for r in d:
    t=r['Minutes1DK']
    if r['OnshoreWindPower'] is None or r['OffshoreWindPower'] is None: continue
    days[t[:10]][int(t[11:13])*60+int(t[14:16])]=(r['OnshoreWindPower']+r['OffshoreWindPower'])/3
S=900;E=1065;SET=range(1060,1065)
ts=[900,930,960,990,1020,1050,1080-20-10,1050,1040,1060]
ts=[900,930,960,990,1020,1035,1050,1060]
E1=collections.defaultdict(list);E2=collections.defaultdict(list)
for day,w in sorted(days.items()):
    if not all(m in w for m in range(800,E+1)): continue
    tg=np.mean([w[m] for m in SET])
    for t in ts:
        x=np.array([w[m] for m in range(t-60,t+1)]); h=1062-t
        E1[t].append(x[-1]-tg)
        sl=np.polyfit(np.arange(61),x,1)[0]; E2[t].append(x[-1]+0.5*sl*h-tg)
for t in ts:
    a=np.array(E1[t]);b=np.array(E2[t])
    print(t//60,t%60,'h',1062-t,'last1 rmse %.0f mae %.0f p90abs %.0f | trend60d rmse %.0f mae %.0f'%(np.sqrt((a**2).mean()),np.median(abs(a)),np.percentile(abs(a),90),np.sqrt((b**2).mean()),np.median(abs(b))))
# per-minute diffs and 5-min block behavior
dd=[];
for day,w in days.items():
    for m in range(900,1065):
        if m in w and m+1 in w: dd.append(w[m+1]-w[m])
dd=np.array(dd);print('1min diff std %.1f mad*1.48 %.1f frac zero %.2f'%(dd.std(),1.4826*np.median(abs(dd)),(dd==0).mean()))
lv=[np.mean([w[m] for m in SET]) for w in days.values() if all(m in w for m in SET)];print('level 17:42 mean %.0f min %.0f max %.0f'%(np.mean(lv),min(lv),max(lv)))
