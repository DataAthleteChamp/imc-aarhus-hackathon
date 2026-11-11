import json,bisect,datetime as dt,numpy as np,collections,sys
R='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/'
L=[json.loads(l) for l in open(R+'data/books.jsonl')]
rows=json.load(open(R+'data/live_rows.json'))['rows']
for r in rows:
    r['ts']=dt.datetime.fromisoformat(r['t']).timestamp()
    r['4_ETF']=r['1_WIND']+r['2_CO2']+r['3_FLOW']
P=['1_WIND','2_CO2','3_FLOW','4_ETF']
def mkt(lv):
    return [(p,v-o) for p,v,o in lv if v-o>0]
book={p:[] for p in P+['5_WIND_RANGE']}
for x in L:
    b=mkt(x['b']);a=mkt(x['a'])
    if not b or not a: continue
    bb=max(b)[0];ba=min(a)[0]
    if ba<=bb: continue
    bv=[sum(v for p,v in sorted(b,reverse=True)[:k]) for k in (1,2,3)]
    av=[sum(v for p,v in sorted(a)[:k]) for k in (1,2,3)]
    book[x['p']].append((x['ts'],bb,ba,(bb+ba)/2,bv,av))
def at(p,t):
    s=book[p];i=bisect.bisect_right([z[0] for z in s],t)-1
    return s[i] if i>=0 else None
def value(p,t,nowcast):
    pub=[r for r in rows if r['ts']+75<=t]
    if not pub: return None
    x=[r[p] for r in pub[-61:]]
    if not nowcast: return x[-1]
    d=np.diff(x)
    if len(d)<10: return x[-1]
    phi=np.corrcoef(d[:-1],d[1:])[0,1]; phi=max(min(phi,0.99),-0.99)
    # minutes elapsed beyond last published -> nowcast 2 steps
    return x[-1]+np.mean(d[-2:])*(phi+phi**2)
t0=L[0]['ts'];t1=L[-1]['ts']
grid=np.arange(t0+5,t1-125,2.0)  # sample every 2s
print('Q1 gap signal (sampled every 2s; N=samples, sig/min = samples*2/60 ~ fraction of time)')
for nc in (False,True):
  print('== nowcast' if nc else '== latest published')
  for p in P:
    rec=[]
    for t in grid:
        s=at(p,t); v=value(p,t,nc)
        if s is None or v is None: continue
        g=v-s[3]; f={}
        for h in (30,60,120):
            s2=at(p,t+h); f[h]=s2[3]
        v2=value(p,t+120,False)
        rec.append((g,s[1],s[2],s[3],f,v2))
    spr=np.median([r[2]-r[1] for r in rec])
    print(p,'median spread',spr,'n',len(rec),'median|g|',round(np.median([abs(r[0]) for r in rec]),1))
    for k in (0,5,10,20,30,50,80):
        sel=[r for r in rec if abs(r[0])>k]
        if len(sel)<5: continue
        out=[]
        for h in (30,60,120):
            hit=np.mean([np.sign(r[4][h]-r[3])==np.sign(r[0]) for r in sel if r[4][h]!=r[3]] or [np.nan])
            out.append(f'hit{h}={hit:.2f}')
        pnl60=np.mean([(r[4][60]-r[2]) if r[0]>0 else (r[1]-r[4][60]) for r in sel])
        pnl120=np.mean([(r[4][120]-r[2]) if r[0]>0 else (r[1]-r[4][120]) for r in sel])
        pnlv=np.mean([(r[5]-r[2]) if r[0]>0 else (r[1]-r[5]) for r in sel])
        print(f'  |g|>{k}: n={len(sel)} frac={len(sel)/len(rec):.2f}',*out,f'EV60={pnl60:.1f} EV120={pnl120:.1f} EVval={pnlv:.1f}')
print('\nQ2 imbalance -> next mid change (event-based, next mid change)')
for p in P+['5_WIND_RANGE']:
    s=book[p]; res={1:[],2:[],3:[]}
    for i,z in enumerate(s):
        nxt=next((w for w in s[i+1:] if w[3]!=z[3]),None)
        if nxt is None: continue
        for k in (1,2,3):
            imb=(z[4][k-1]-z[5][k-1])/(z[4][k-1]+z[5][k-1])
            if abs(imb)>0.33: res[k].append(np.sign(imb)==np.sign(nxt[3]-z[3]))
    print(p,{k:(len(v),round(np.mean(v),2) if v else None) for k,v in res.items()})
print('\nQ3 |mid change| over 30s: windows starting at publish (M+75s) vs other')
for p in P:
    pubt=[r['ts']+75 for r in rows if r['ts']+75>t0]
    a=[abs(at(p,t+30)[3]-at(p,t)[3]) for t in pubt if t+30<t1 and at(p,t)]
    o=[abs(at(p,t+30)[3]-at(p,t)[3]) for t in grid if min(abs(t-q) for q in pubt)>20 and at(p,t)]
    print(p,'publish',round(np.mean(a),1),len(a),'other',round(np.mean(o),1),len(o))
print('\nQ4 bias mid - latest value (mean, by 3 min block)')
for p in P:
    gs=[(t,at(p,t)[3]-value(p,t,False)) for t in grid if at(p,t)]
    blocks=collections.defaultdict(list)
    for t,g in gs: blocks[int((t-t0)//180)].append(g)
    print(p,'mean',round(np.mean([g for t,g in gs]),1),[round(np.mean(v)) for k,v in sorted(blocks.items())])
