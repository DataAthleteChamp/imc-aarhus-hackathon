import json,collections,statistics as st,datetime as dt,os
D=os.path.dirname(os.path.abspath(__file__)); R=os.path.dirname(os.path.dirname(D))
T=json.load(open(D+'/trades.json'))
def ts(s): return dt.datetime.fromisoformat(s[:26].rstrip('Z')).replace(tzinfo=dt.timezone.utc).timestamp()
for t in T: t['ts']=ts(t['timestamp'])
T.sort(key=lambda t:t['ts'])
print('range',T[0]['timestamp'],T[-1]['timestamp'],len(T))
rows=json.load(open(R+'/data/live_rows.json'))['rows']
ev={}
for r in rows:
  k=dt.datetime.fromisoformat(r['t']).timestamp()
  ev[k]={p:r.get(p) for p in ['1_WIND','2_CO2','3_FLOW']}
  if None not in ev[k].values(): ev[k]['4_ETF']=sum(ev[k].values())
keys=sorted(ev)
def E(p,t):
  m=int(t//60*60); 
  while m not in ev and m>keys[0]: m-=60
  return ev.get(m,{}).get(p)
fair={'1_WIND':484,'2_CO2':611,'3_FLOW':1723,'4_ETF':2818,'5_WIND_RANGE':184}
last={p:E(p,keys[-1]+1) for p in fair}; last['5_WIND_RANGE']=175
print('now Energinet',last)
pos=collections.defaultdict(lambda:collections.defaultdict(lambda:[0,0.0,0,0,0]))  # net,cash,vol,aggr_vol,n
mk=collections.defaultdict(list); secs=collections.defaultdict(list)
lastpx={}
# trade-based markout: price 60s later (next trade >=60s)
byp=collections.defaultdict(list)
for t in T: byp[t['product']].append(t)
def fut(p,t0,h=120):
  for u in byp[p]:
    if u['ts']>=t0+h: return u['price']
  return byp[p][-1]['price']
for t in T:
  p,q,px=t['product'],t['volume'],t['price']
  for who,s in ((t['buyer'],1),(t['seller'],-1)):
    a=pos[who][p]; a[0]+=s*q; a[1]-=s*q*px; a[2]+=q; a[4]+=1
    if who==t['aggressor']:
      a[3]+=q; mk[who].append((s*(fut(p,t['ts'])-px)*q, s*((last[p] or px)-px)*q, q))
    secs[who].append(int(t['ts'])%60)
print('\n== NET POS (avg px) | PnL marked to fair(predict BOT FAIR)')
names=sorted(pos,key=lambda w:-sum(a[2] for a in pos[w].values()))
for w in names:
  line=[];pnl=0
  for p in fair:
    a=pos[w].get(p)
    if not a: continue
    pnl+=a[1]+a[0]*fair[p]
    avg=(-a[1]/a[0]) if a[0] else 0
    line.append(f"{p[:6]}:{a[0]:+d}@{avg:.0f}" if a[0] else f"{p[:6]}:0")
  vol=sum(a[2] for a in pos[w].values()); ag=sum(a[3] for a in pos[w].values())
  m=mk[w]; m1=sum(x[0] for x in m)/max(1,sum(x[2] for x in m)); m2=sum(x[1] for x in m)/max(1,sum(x[2] for x in m))
  first=min(t['ts'] for t in T if w in(t['buyer'],t['seller'])); 
  print(f"{w:18s} vol{vol:5d} aggr{ag/vol:4.0%} mk120/lot{m1:+6.1f} mkEnergi{m2:+6.1f} pnl@fair{pnl:+8.0f} first{dt.datetime.fromtimestamp(first).strftime('%H:%M')} secs-mode{collections.Counter(secs[w]).most_common(2)} | "+' '.join(line))
print('\n== regime per 5min (trades/min, std of px diffs, mean px - Energinet)')
for p in fair:
  b=collections.defaultdict(list)
  for t in byp[p]: b[int(t['ts']//300*300)].append(t)
  out=[]
  for k in sorted(b):
    px=[t['price'] for t in b[k]]; d=[abs(x-y) for x,y in zip(px,px[1:])]
    e=E(p,k+150); dev=st.mean(px)-e if e else float('nan')
    out.append(f"{dt.datetime.fromtimestamp(k).strftime('%H:%M')} n{len(px)/5:.1f} |dp|{(st.mean(d) if d else 0):.0f} dev{dev:+.0f}")
  print(p,' ; '.join(out))
