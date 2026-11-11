import json, sys
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import fair as F
base = F.load_params(); base['manual_adj'] = {}
P = ['1_WIND', '2_CO2', '3_FLOW', '4_ETF']
def mk(w):
    d = dict(base); d['endgame_blend'] = {p: w for p in P}; return lambda: dict(d)
recs = json.loads((ROOT / 'data/hist.json').read_text())['records']
days = sorted({x['Minutes1DK'][:10] for x in recs})[-15:-1]
E = {}
for day in days:
    rows = []
    for x in recs:
        if x['Minutes1DK'].startswith(day) and None not in x.values():
            t = datetime.fromisoformat(x['Minutes1DK']).replace(tzinfo=F.TZ)
            rows.append({'t': t, '1_WIND': (x['OnshoreWindPower'] + x['OffshoreWindPower']) / 3,
                         '2_CO2': 10 * x['CO2Emission'], '3_FLOW': 1000 + x['Exchange_Sum'] / 3})
    rows.sort(key=lambda r: r['t'])
    if not rows: continue
    d0 = rows[0]['t'].replace(hour=0, minute=0)
    w = [r for r in rows if d0.replace(hour=17, minute=40) <= r['t'] <= d0.replace(hour=17, minute=44)]
    if len(w) < 5: continue
    st = {p: np.mean([r[p] for r in w]) for p in P[:3]}; st['4_ETF'] = sum(st.values())
    for hh, mm in [(17, 20), (17, 25), (17, 30), (17, 35), (17, 38), (17, 40), (17, 42)]:
        now = d0.replace(hour=hh, minute=mm, second=30)
        vis = [r for r in rows if r['t'] <= now - timedelta(seconds=75)]
        F.fetch_rows = lambda n, _v=vis: _v
        F.load_params = mk(0.0); f0 = F.compute_fair(now)['fair']
        F.load_params = mk(1.0); f1 = F.compute_fair(now)['fair']
        last = dict(vis[-1]); last['4_ETF'] = sum(last[p] for p in P[:3])
        k = f'{hh}:{mm:02d}'
        for p in P:
            for name, v in [('eg', f0[p]), ('pre', f1[p]), ('w25', .75*f0[p]+.25*f1[p]), ('w50', .5*f0[p]+.5*f1[p]), ('naive', last[p])]:
                E.setdefault((p, k, name), []).append(v - st[p])
print('days', days[0], days[-1], 'n', len(E[('1_WIND','17:20','eg')]))
times = sorted({k[1] for k in E})
for p in P:
    print(p, 'method ' + ' '.join(f'{t:>6s}' for t in times))
    for m in ['eg', 'pre', 'w25', 'w50', 'naive']:
        print(f"  {m:6s} " + ' '.join(f"{np.sqrt(np.mean(np.square(E[(p,t,m)]))):6.2f}" for t in times))
