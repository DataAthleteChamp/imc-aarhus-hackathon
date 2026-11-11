"""Endgame calibration: z = (bot fair - settle)/sigma at 17:20..17:42 over recent days. |z| should be ~N(0,1):
sd(z) ~1, ~68% within 1. sd(z) >> 1 => sigma too small (overconfident)."""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import fair as F
recs = json.loads((ROOT / 'data/hist.json').read_text())['records']
days = sorted({x['Minutes1DK'][:10] for x in recs})[-13:-1]
Z = {}
for day in days:
    rows = []
    for x in recs:
        if x['Minutes1DK'].startswith(day) and None not in x.values():
            t = datetime.fromisoformat(x['Minutes1DK']).replace(tzinfo=F.TZ)
            rows.append({'t': t, '1_WIND': (x['OnshoreWindPower'] + x['OffshoreWindPower']) / 3,
                         '2_CO2': 10 * x['CO2Emission'], '3_FLOW': 1000 + x['Exchange_Sum'] / 3})
    rows.sort(key=lambda r: r['t'])
    d0 = rows[0]['t'].replace(hour=0, minute=0)
    w = [r for r in rows if d0.replace(hour=17, minute=40) <= r['t'] <= d0.replace(hour=17, minute=44)]
    if len(w) < 5:
        continue
    st = {p: np.mean([r[p] for r in w]) for p in ['1_WIND', '2_CO2', '3_FLOW']}
    st['4_ETF'] = sum(st.values())
    for hh, mm in [(17, 20), (17, 25), (17, 30), (17, 35), (17, 38), (17, 40), (17, 42)]:
        now = d0.replace(hour=hh, minute=mm, second=30)
        vis = [r for r in rows if r['t'] <= now - timedelta(seconds=75)]
        F.fetch_rows = lambda n, _v=vis: _v
        m = F.compute_fair(now)
        for p in st:
            Z.setdefault((p, f'{hh}:{mm:02d}'), []).append((m['fair'][p] - st[p]) / m['sigma'][p])
print('days', days[0], '..', days[-1], '\nsd(z) per product/time (1.0 = calibrated, >1.5 = overconfident):')
times = sorted({k[1] for k in Z})
print(f"{'product':8s} " + ' '.join(f'{t:>6s}' for t in times))
for p in ['1_WIND', '2_CO2', '3_FLOW', '4_ETF']:
    print(f"{p:8s} " + ' '.join(f"{np.std(Z[(p, t)]):6.2f}" for t in times))
