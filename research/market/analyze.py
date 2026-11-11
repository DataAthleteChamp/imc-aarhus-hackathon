import json, collections, statistics as st, datetime as dt, sys
B='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/'
L=[json.loads(l) for l in open(B+'research/market/stream.jsonl')]
rows=json.load(open(B+'data/live_rows.json'))['rows']
seen=[json.loads(l) for l in open(B+'research/market/rows_seen.jsonl')]
R={dt.datetime.fromisoformat(r['t']).timestamp():r for r in rows}
P=['1_WIND','2_CO2','3_FLOW','4_ETF','5_WIND_RANGE']
def fv(r,p): return r['1_WIND']+r['2_CO2']+r['3_FLOW'] if p=='4_ETF' else r.get(p)
t0=L[0]['rt']; print('events',len(L),'dur',round(L[-1]['rt']-t0))
book={}; hist=collections.defaultdict(list)  # p -> (rt,bb,ba,hb,ha,hbv,hav,bbv,bav)
for e in L:
    if e['ev']!='order': continue
    d=e['d']; p=d['productsymbol']
    b={float(k):v['marketVolume'] for k,v in d['buyOrders'].items() if v['marketVolume']>0}
    a={float(k):v['marketVolume'] for k,v in d['sellOrders'].items() if v['marketVolume']>0}
    hb=[float(k) for k in d['buyOrders'] if '.' in k]; ha=[float(k) for k in d['sellOrders'] if '.' in k]
    hist[p].append((e['rt'],max(b) if b else None,min(a) if a else None,max(hb) if hb else None,min(ha) if ha else None,
        [(k,d['buyOrders'][k]['marketVolume']) for k in d['buyOrders'] if '.' in k],[(k,d['sellOrders'][k]['marketVolume']) for k in d['sellOrders'] if '.' in k],b,a))
print('updates/product',{p:len(v) for p,v in hist.items()})
# Q1 house quotes
for p in P:
    h=hist[p]
    hs=[x for x in h if x[3] and x[4]]
    if not hs: print(p,'no house 2-sided'); continue
    sp=[x[4]-x[3] for x in hs]
    print(p,'house spread med',st.median(sp),'min',min(sp),'max',max(sp),'example levels',hs[-1][5],hs[-1][6])
    print('   overall spread med',st.median([x[2]-x[1] for x in h if x[1] and x[2]]),'nlevels med',st.median([len(x[7])+len(x[8]) for x in h]))
    # house mid vs energinet minute lag k
    if p=='5_WIND_RANGE': continue
    for lag in range(0,6):
        errs=[]
        for x in hs:
            m=(int(x[0]//60)-lag)*60
            r=R.get(m)
            if r: errs.append((x[3]+x[4])/2-fv(r,p))
        if errs: print('   lag',lag,'n',len(errs),'mean',round(st.mean(errs),2),'mad',round(st.mean(abs(e) for e in errs),2))
    # house mid change times
    ch=[]; prev=None
    for x in hs:
        mid=(x[3]+x[4])/2
        if prev is not None and mid!=prev: ch.append((round(x[0]-t0,1),time_s:=dt.datetime.fromtimestamp(x[0]).strftime('%H:%M:%S.%f')[:12],mid-prev))
        prev=mid
    print('   house mid changes',len(ch),ch[:25])
print('rows arrivals', [(dt.datetime.fromtimestamp(s['rt']).strftime('%H:%M:%S'),s['last']['t'][11:16],{k:round(v,1) for k,v in s['last'].items() if k!='t'}) for s in seen])
# Q3 ETF - components
ts=sorted(set(round(x[0],1) for p in P for x in hist[p]))
cur={}; diffs=[]
ev=sorted([(x[0],p,x) for p in P[:4] for x in hist[p]])
for rt,p,x in ev:
    cur[p]=x
    if all(q in cur and cur[q][1] and cur[q][2] for q in P[:4]):
        etf=cur['4_ETF']; comp=[cur[q] for q in P[:3]]
        buyetf=sum(c[1] for c in comp)-etf[2]   # buy ETF at ask, sell comps at bid
        selletf=etf[1]-sum(c[2] for c in comp)
        mid=(etf[1]+etf[2])/2-sum((c[1]+c[2])/2 for c in comp)
        diffs.append((rt,mid,buyetf,selletf))
if diffs:
    print('ETF-comp mid: med',st.median(d[1] for d in diffs),'min',min(d[1] for d in diffs),'max',max(d[1] for d in diffs))
    print('arb buyETF>0 frac',round(sum(d[2]>0 for d in diffs)/len(diffs),3),'max',max(d[2] for d in diffs),' sellETF>0 frac',round(sum(d[3]>0 for d in diffs)/len(diffs),3),'max',max(d[3] for d in diffs))
tr=[t for e in L if e['ev']=='trade' for t in e['d']]
print('stream trades',len(tr),collections.Counter(t['product'] for t in tr))
