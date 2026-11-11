import json,bisect,datetime as dt,numpy as np
R='/Users/jakubpiotrowski/imc-hackathon-prep/team-repo/'
L=[json.loads(l) for l in open(R+'data/books.jsonl')]
rows=json.load(open(R+'data/live_rows.json'))['rows']
for r in rows:
    r['ts']=dt.datetime.fromisoformat(r['t']).timestamp(); r['4_ETF']=r['1_WIND']+r['2_CO2']+r['3_FLOW']
rts=[r['ts']+75 for r in rows]
P={'1_WIND':(6,40,False),'2_CO2':(10,80,True),'3_FLOW':(10,80,False),'4_ETF':(24,50,False)}
book={p:[] for p in P}
for x in L:
    if x['p'] not in P: continue
    b=[(p,v-o) for p,v,o in x['b'] if v-o>0];a=[(p,v-o) for p,v,o in x['a'] if v-o>0]
    if not b or not a: continue
    bb=max(b)[0];ba=min(a)[0]
    if ba<=bb: continue
    book[x['p']].append((x['ts'],bb,ba,(bb+ba)/2))
bt={p:[z[0] for z in book[p]] for p in P}
def at(p,t):
    i=bisect.bisect_right(bt[p],t)-1; return book[p][i] if i>=0 else None
def value(p,t,nc):
    n=bisect.bisect_right(rts,t)
    if n==0: return None
    x=[r[p] for r in rows[max(0,n-61):n]]
    if not nc: return x[-1]
    d=np.diff(x)
    if len(d)<10: return x[-1]
    phi=np.clip(np.corrcoef(d[:-1],d[1:])[0,1],-.99,.99)
    return x[-1]+np.mean(d[-2:])*(phi+phi**2)
day=dt.datetime(2026,11,11,tzinfo=dt.timezone(dt.timedelta(hours=1))).timestamp()
W={'16:11-16:58':(day+16*3600+11*60,day+16*3600+58*60),'16:58+':(day+16*3600+58*60,1e12)}
tend=min(L[-1]['ts'],rts[-1]-120)
for wn,(a,b) in W.items():
    print('=====',wn)
    for p,(thr,mx,nc) in P.items():
        bk=lambda g:None if g<=thr else 0 if g<=mx else 1 if g<=2*mx else 2
        prev=None; ep={0:[],1:[],2:[]}
        for t in np.arange(a,min(b,tend-125),2.0):
            s=at(p,t);v=value(p,t,nc)
            if s is None or v is None: prev=None;continue
            gb=v-s[2]; gs=s[1]-v
            side,g=(1,gb) if gb>=gs else (-1,gs)
            k=bk(g); key=(side,k) if k is not None else None
            if key and key!=prev:
                f60=at(p,t+60)[3];f120=at(p,t+120)[3];v2=value(p,t+120,False)
                px=s[2] if side>0 else s[1]
                ep[k].append([side*(f60-px),side*(f120-px),side*(v2-px)])
            prev=key
        for k,nm in ((0,f'({thr},{mx}]'),(1,f'({mx},{2*mx}]'),(2,f'>{2*mx}')):
            e=np.array(ep[k])
            if len(e)==0: print(p,nm,'n=0');continue
            m=e.mean(0);h=(e>0).mean(0)
            print(f'{p} {nm}: n={len(e)} EV60={m[0]:.1f} EV120={m[1]:.1f} EVval={m[2]:.1f} hit={h[0]:.2f}/{h[1]:.2f}/{h[2]:.2f}')
