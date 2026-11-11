import json, sys, numpy as np, collections
d=json.load(open(sys.argv[1]))['records']
days=collections.defaultdict(dict)
for r in d:
    t=r['Minutes1DK']; day,hm=t[:10],t[11:16]
    if r['OnshoreWindPower'] is None or r['OffshoreWindPower'] is None: continue
    h,m=int(hm[:2]),int(hm[3:5]); mi=h*60+m
    days[day][mi]=(r['OnshoreWindPower']+r['OffshoreWindPower'])/3
S=15*60; E=17*60+45; SET=[17*60+40+i for i in range(5)]
ts=list(range(15*60,17*60+41,10))
meths=collections.defaultdict(lambda: collections.defaultdict(list))
rng=collections.defaultdict(list)
vols=[]
for day,w in sorted(days.items()):
    if not all(m in w for m in range(14*60,E+1)): continue
    target=np.mean([w[m] for m in SET])
    full=[w[m] for m in range(S,E+1)]
    finalR=max(full)-min(full)
    dif=np.diff([w[m] for m in range(14*60,E+1)]); vols.append(np.std(dif))
    for t in ts:
        h=SET[2]-t
        x=np.array([w[m] for m in range(t-60,t+1)])
        p={}
        p['last1']=x[-1]; p['last5']=x[-5:].mean(); p['last15']=x[-15:].mean()
        for L in (15,30,60):
            sl=np.polyfit(np.arange(L+1),x[-L-1:],1)[0]
            p[f'trend{L}']=x[-1]+sl*h
            p[f'trend{L}_d']=x[-1]+sl*h*0.5
        dm=np.mean([w[m] for m in range(0,t+1) if m in w])
        p['mr_daymean']=x[-1]+0.1*(dm-x[-1])
        for k,v in p.items(): meths[t][k].append(v-target)
        so=[w[m] for m in range(S,t+1)]
        R=max(so)-min(so)
        rv=np.std(np.diff(x[-31:]))
        rng[t].append((R,finalR,max(so)-x[-1],x[-1]-min(so),rv,E-t))
print('days',len(vols),'median per-min vol',np.median(vols))
names=list(meths[ts[0]].keys())
print('t   '+' '.join(f'{n[:10]:>10}' for n in names))
for t in ts:
    print(f'{t//60}:{t%60:02d} '+' '.join(f'{np.sqrt(np.mean(np.square(meths[t][n]))):10.1f}' for n in names))
json.dump({str(t):rng[t] for t in ts},open('/tmp/rng.json','w'))
# std of last1 error vs horizon -> fit sigma = a*sqrt(h)+b
hs=[];ss=[]
for t in ts:
    h=SET[2]-t; e=np.array(meths[t]['last5']); hs.append(h); ss.append(np.sqrt(np.mean(e**2)))
hs=np.array(hs);ss=np.array(ss)
A=np.vstack([np.sqrt(hs),np.ones_like(hs)]).T; c=np.linalg.lstsq(A,ss,rcond=None)[0]; print('sigma_last5 ~ %.2f*sqrt(h)+%.2f'%tuple(c))
