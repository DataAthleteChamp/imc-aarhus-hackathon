"""FLOW exit-policy backtest. Day path shifted so value(16:48)=V0. Market mid(T)=value(T-2), bid=mid-6."""
import json, statistics as st
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parents[3]
recs = json.loads((ROOT/'data/hist.json').read_text())['records']
days = defaultdict(dict)
for x in recs:
    if x.get('Exchange_Sum') is None: continue
    d, hm = x['Minutes1DK'][:10], x['Minutes1DK'][11:16]
    h, m = int(hm[:2]), int(hm[3:5])
    days[d][h*60+m] = 1000 + x['Exchange_Sum']/3
POS, COST, V0, HALF = 68, 1616, 1630, 6
T0 = 16*60+48
def M(h, m): return h*60+m
SET = [M(17,40+i) for i in range(5)]
EG = [(M(17,20),1.0,10),(M(17,30),0.8,6),(M(17,38),0.6,4),(M(17,42),0.5,3)]
res = defaultdict(list); meta = []
for d, p in sorted(days.items()):
    need = list(range(T0-22, M(17,45)))
    if any(t not in p for t in need): continue
    sh = V0 - p[T0]; v = {t: p[t]+sh for t in p}
    settle = sum(v[t] for t in SET)/5
    rise20 = p[T0] - p[T0-20]
    bid = lambda t: v[t-2] - HALF
    pnl = lambda q_sold, px: q_sold*(px-COST) + (POS-q_sold)*(settle-COST)
    pols = {'hold': pnl(0, 0)}
    for name, t in [('sell_now16:50', M(16,50)), ('sell_17:00', M(17,0)), ('sell_17:20', M(17,20)), ('sell_17:30', M(17,30)), ('sell_17:38', M(17,38))]:
        pols[name] = pnl(POS, bid(t))
        if name in ('sell_now16:50', 'sell_17:20', 'sell_17:30'): pols['half_'+name[5:]] = pnl(34, bid(t))
    # endgame approx: fair = last visible minute (T-1) ; sigma = rem-horizon sd est (~1.2*sqrt(min to 17:42))
    pos, cash = POS, 0.0
    for t in range(M(17,20), M(17,45)):
        k, edge = [(k, e) for s, k, e in EG if t >= s][-1]
        fair = v[t-1]; sig = 1.5*max(1, (M(17,42)-t))**0.5
        if pos > 50 and fair < bid(t) - max(k*sig, edge):
            q = pos-50; cash += q*(bid(t)-COST); pos = 50
    pols['endgame'] = cash + pos*(settle-COST)
    for k2, x in pols.items(): res[(k2, 'all')].append(x)
    meta.append((d, settle - V0, rise20, pols))
def summ(xs):
    return f"n={len(xs):2d} mean={st.mean(xs):+8.0f} sd={st.pstdev(xs):7.0f} P>0={sum(x>0 for x in xs)/len(xs):.2f} min={min(xs):+7.0f}"
for label, flt in [('ALL', lambda m: True), ('since 10-25', lambda m: m[0] >= '2026-10-25'), ('rise20>60', lambda m: m[2] > 60), ('rise20>30', lambda m: m[2] > 30)]:
    sub = [m for m in meta if flt(m)]
    if not sub: print(label, 'none'); continue
    mv = [m[1] for m in sub]
    print(f"\n== {label}: settle-V(16:48) mean={st.mean(mv):+.1f} sd={st.pstdev(mv):.1f} P(settle<{COST})={sum(V0+x<COST for x in mv)/len(mv):.2f}")
    for k2 in sub[0][3]: print(f"  {k2:16s} {summ([m[3][k2] for m in sub])}")
print('\nrise20 list:', sorted(round(m[2]) for m in meta))
