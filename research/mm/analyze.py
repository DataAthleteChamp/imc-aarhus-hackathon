import json, collections, statistics as st
from datetime import datetime
B='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/'
T=json.load(open('trades.json'))
def pt(s): return datetime.fromisoformat(s[:26]+'+00:00').timestamp()
for t in T: t['ts']=pt(t['timestamp'])
T.sort(key=lambda t:t['ts'])
rows=json.load(open(B+'data/live_rows.json'))['rows']
ev={}
for r in rows:
    tm=datetime.fromisoformat(r['t']).timestamp()
    for k in ('1_WIND','2_CO2','3_FLOW'): ev.setdefault(k,[]).append((tm,r[k]))
for r in rows:
    if all(k in r for k in ('1_WIND','2_CO2','3_FLOW')): pass
books=collections.defaultdict(list)
for l in open(B+'data/books.jsonl'):
    try: d=json.loads(l)
    except: continue
    if d['b'] and d['a']: books[d['p']].append((d['ts'],(d['b'][0][0]+d['a'][0][0])/2,d['a'][0][0]-d['b'][0][0]))
print('trades',len(T),'span',datetime.fromtimestamp(T[0]['ts']),datetime.fromtimestamp(T[-1]['ts']))
print('sessions',collections.Counter(t['sessionId'] for t in T))
print('books span', {p:(len(v),datetime.fromtimestamp(v[0][0]).strftime('%H:%M:%S'),datetime.fromtimestamp(v[-1][0]).strftime('%H:%M:%S'), st.median(x[2] for x in v)) for p,v in books.items()})
def ref(p,ts):
    # next trade price or book mid at/after ts
    bm=[m for (t,m,s) in books.get(p,[]) if t>=ts]
    if bm: return bm[0],'book'
    later=[t['price'] for t in T if t['product']==p and t['ts']>=ts]
    if later: return later[0],'trade'
    # last trade
    return None,None
def val(p,ts):
    if p not in ev: return None
    xs=[v for (t,v) in ev[p] if t<=ts-60]  # minute value known approx
    return xs[-1] if xs else None
H=[30,60,180,300]
agg=collections.defaultdict(lambda: collections.defaultdict(list))
print('\nproduct counts',collections.Counter(t['product'] for t in T))
print('aggressor counts',collections.Counter(t['aggressor'] for t in T).most_common())
print('passive counts',collections.Counter((t['seller'] if t['aggressor']==t['buyer'] else t['buyer']) for t in T).most_common())
for t in T:
    p=t['product']; sgn=1 if t['aggressor']==t['buyer'] else -1
    pas=t['seller'] if sgn==1 else t['buyer']
    for h in H:
        r,src=ref(p,t['ts']+h)
        if r is None: continue
        mk=sgn*(r-t['price'])  # aggressor gain per unit = passive loss
        agg[('AGG',t['aggressor'])][h].append(mk); agg[('PAS',pas)][h].append(-mk); agg[('PROD',p)][h].append(mk)
    v=val(p,t['ts'])
    if v is not None:
        f=sgn*(v-t['price']); agg[('AGG',t['aggressor'])]['val'].append(f); agg[('PROD',p)]['val'].append(f)
print('\nmarkout = aggressor gain/unit (PAS rows = passive gain)')
for k in sorted(agg):
    d=agg[k]; print(k, {h:(len(v),round(st.mean(v),1)) for h,v in d.items()})
# flow stats
print('\nper product stats')
for p in sorted(set(t['product'] for t in T)):
    xs=[t for t in T if t['product']==p]
    span=(T[-1]['ts']-T[0]['ts'])/60
    buys=sum(1 for t in xs if t['aggressor']==t['buyer'])
    secs=[int(t['ts'])%60 for t in xs]
    print(p,'n',len(xs),'per_min',round(len(xs)/span,2),'sizes',collections.Counter(t['volume'] for t in xs).most_common(5),'buyagg',buys,'sell',len(xs)-buys,
      'sec_of_min',sorted(secs))
# inter-trade gaps
gaps=[b['ts']-a['ts'] for a,b in zip(T,T[1:])]
print('median gap s',st.median(gaps),'sec in minute hist',collections.Counter((int(t['ts'])%60)//10*10 for t in T))
# best bid/ask change rate
for p,v in books.items():
    ch=sum(1 for a,b in zip(v,v[1:]) if a[1]!=b[1]); dur=(v[-1][0]-v[0][0])/60
    print(p,'mid changes',ch,'over min',round(dur,1),'spreads',collections.Counter(x[2] for x in v).most_common(4))
for t in T[-25:]:
    print(datetime.fromtimestamp(t['ts']).strftime('%H:%M:%S'),t['product'],t['price'],t['volume'],t['buyer'],t['seller'],'agg',t['aggressor'])
