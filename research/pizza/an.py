import json,collections,bisect
from datetime import datetime
R='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/'
T=json.load(open(R+'research/opponents/trades.json'))
rows=json.load(open(R+'data/live_rows.json'))['rows']
def ts(s):
    s=s.replace('Z','+00:00'); 
    if '.' in s:
        a,b=s.split('.'); frac,tz=b[:-6],b[-6:]; s=a+'.'+frac[:6]+tz
    return datetime.fromisoformat(s).timestamp()
V={}
for r in rows:
    m=ts(r['t'])
    for k,v in r.items():
        if k!='t' and v is not None: V.setdefault(k,{})[m]=v
for k in V: V[k]=sorted(V[k].items())
pz=[t for t in T if 'pizzatrading' in (t['buyer'],t['seller'])]
print('pizza trades',len(pz),'of',len(T), 'span',min(t['timestamp'] for t in pz),max(t['timestamp'] for t in pz))
agg=[t for t in pz if t['aggressor']=='pizzatrading']; pas=[t for t in pz if t['aggressor']!='pizzatrading']
print('agg',len(agg),'passive',len(pas))
print('by prod agg',collections.Counter(t['product'] for t in agg),'passive',collections.Counter(t['product'] for t in pas))
print('counterparties',collections.Counter((t['seller'] if t['buyer']=='pizzatrading' else t['buyer']) for t in pz).most_common(8))
sec=collections.Counter(int(ts(t['timestamp'])%60)//5*5 for t in agg); print('agg sec-of-min 5s bins',sorted(sec.items()))
sec=collections.Counter(int(ts(t['timestamp'])%60)//5*5 for t in pas); print('pas sec-of-min',sorted(sec.items()))
pos=collections.defaultdict(float)
for t in pz: pos[t['product']]+= t['volume']*(1 if t['buyer']=='pizzatrading' else -1)
print('net pos',dict(pos))
print('sizes',collections.Counter(t['volume'] for t in agg).most_common(8))
# signal analysis: last published at trade time assumes minute M public at M+75s
def val(p,tt,lag=75):
    s=V.get(p); 
    if not s: return None,None,None
    keys=[k for k,_ in s]; i=bisect.bisect_right(keys,tt-lag)-1
    if i<1: return None,None,None
    nxt=s[i+1][1] if i+1<len(s) else None
    return s[i][1],s[i-1][1],nxt
out=collections.defaultdict(list)
for t in sorted(agg,key=lambda t:t['timestamp']):
    tt=ts(t['timestamp']); d=1 if t['buyer']=='pizzatrading' else -1
    v,pv,nv=val(t['product'],tt)
    if v is None: continue
    out[t['product']].append((d,(v-t['price'])*d,(v-pv)*d,None if nv is None else (nv-v)*d,t['volume'],int(tt%60)))
for p,l in out.items():
    l2=sorted(x[1] for x in l); n=len(l2)
    print(p,n,'d*(last-price) pct10/50/90',l2[n//10],l2[n//2],l2[9*n//10],
      'lastchg agree',sum(x[2]>0 for x in l)/n,'nextchg agree',sum(1 for x in l if x[3] and x[3]>0)/max(1,sum(1 for x in l if x[3] is not None)))
print('--- agreement of dir with change of minute public at lag L (L small = future info)')
for p in ['1_WIND','2_CO2','3_FLOW']:
    s=V[p]; keys=[k for k,_ in s]
    # base autocorr of changes
    ch=[s[i][1]-s[i-1][1] for i in range(1,len(s))]
    ac=sum((a>0)==(b>0) for a,b in zip(ch,ch[1:]))/(len(ch)-1)
    res=[]
    for L in [-60,0,30,60,75,90,120,180]:
        ok=n=0
        for t in agg:
            if t['product']!=p: continue
            tt=ts(t['timestamp']); d=1 if t['buyer']=='pizzatrading' else -1
            i=bisect.bisect_right(keys,tt-L)-1
            if i<1 or i>=len(s): continue
            c=s[i][1]-s[i-1][1]
            if c==0: continue
            n+=1; ok+= (c*d>0)
        res.append((L,round(ok/max(n,1),2),n))
    print(p,'chg autocorr',round(ac,2),res)
# edge vs mid 120s later using books
import collections as C
mids=C.defaultdict(list)
for line in open(R+'data/books.jsonl'):
    try: b=json.loads(line)
    except: continue
    if b['b'] and b['a']: mids[b['p']].append((b['ts'],(b['b'][0][0]+b['a'][0][0])/2))
for p in mids: mids[p].sort()
for p in ['1_WIND','2_CO2','3_FLOW','4_ETF','5_WIND_RANGE']:
    m=mids[p]; k=[x for x,_ in m]
    for H in [0,30,120]:
        e=[]
        for t in agg:
            if t['product']!=p: continue
            tt=ts(t['timestamp']); d=1 if t['buyer']=='pizzatrading' else -1
            i=bisect.bisect_right(k,tt+H)-1
            if i<0 or abs(k[i]-tt-H)>10: continue
            e.append((m[i][1]-t['price'])*d)
        if e: print(p,'H',H,'markout',round(sum(e)/len(e),1),len(e))
    # passive markout
    e=[]
    for t in pas:
        if t['product']!=p: continue
        tt=ts(t['timestamp']); d=1 if t['buyer']=='pizzatrading' else -1
        i=bisect.bisect_right(k,tt+120)-1
        if i<0 or abs(k[i]-tt-120)>10: continue
        e.append((m[i][1]-t['price'])*d)
    if e: print(p,'passive H120',round(sum(e)/len(e),1),len(e))
    # spread crossing at trade: price vs mid at trade
    e=[]
    for t in agg:
        if t['product']!=p: continue
        tt=ts(t['timestamp']); d=1 if t['buyer']=='pizzatrading' else -1
        i=bisect.bisect_right(k,tt-0.5)-1
        if i>=0 and tt-k[i]<5: e.append((t['price']-m[i][1])*d)
    if e: print(p,'agg paid vs pre-mid',round(sum(e)/len(e),1))
# bursts / cooldown
ag=sorted(agg,key=lambda t:t['timestamp']); gaps=C.defaultdict(list); last={}
for t in ag:
    tt=ts(t['timestamp']); 
    if t['product'] in last: gaps[t['product']].append(round(tt-last[t['product']],1))
    last[t['product']]=tt
for p,g in gaps.items(): g.sort(); print(p,'inter-agg gap s pct10/50',g[len(g)//10],g[len(g)//2])
