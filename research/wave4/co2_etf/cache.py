"""Cache live-model outputs (fair.compute_fair) per minute 16:48-17:44 for last 14 days."""
import json, sys, pickle
from datetime import datetime, timedelta
from pathlib import Path
from multiprocessing import Pool
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import fair as F
recs = json.loads((ROOT / 'data/hist.json').read_text())['records']
days = sorted({x['Minutes1DK'][:10] for x in recs})

def run(DAY):
    rows = []
    for x in recs:
        if not x['Minutes1DK'].startswith(DAY) or None in x.values():
            continue
        t = datetime.fromisoformat(x['Minutes1DK']).replace(tzinfo=F.TZ)
        rows.append({'t': t, '1_WIND': (x['OnshoreWindPower'] + x['OffshoreWindPower']) / 3,
                     '2_CO2': 10 * x['CO2Emission'], '3_FLOW': 1000 + x['Exchange_Sum'] / 3})
    rows.sort(key=lambda r: r['t'])
    byt = {r['t']: r for r in rows}
    d0 = rows[0]['t'].replace(hour=0, minute=0)
    at = lambda h, m: d0.replace(hour=h, minute=m)
    try:
        win = [byt[at(17, 40) + timedelta(minutes=i)] for i in range(5)]
    except KeyError:
        return None
    val = lambda r, p: r[p] if p != '4_ETF' else r['1_WIND'] + r['2_CO2'] + r['3_FLOW']
    settle = {p: sum(val(r, p) for r in win) / 5 for p in ['2_CO2', '4_ETF']}
    mkt = {}
    for i in range(-5, 120):
        r = byt.get(at(16, 40) + timedelta(minutes=i))
        if r: mkt[r['t'].hour * 60 + r['t'].minute] = {p: val(r, p) for p in ['2_CO2', '4_ETF']}
    out = {}
    t = at(16, 48)
    while t <= at(17, 44):
        now = t + timedelta(seconds=20)
        cut = now - timedelta(seconds=75)
        vis = [r for r in rows if r['t'] <= cut]
        F.fetch_rows = lambda n, _v=vis: _v
        m = F.compute_fair(now)
        pp = m['params']
        out[t.hour * 60 + t.minute] = {p: dict(fair=m['fair'][p], sigma=m['sigma'][p],
            sig=(m['nowcast'] if p == '2_CO2' else m['actual'])[p],
            edge=pp['min_take_edge'][p], tk=pp['take_k']) for p in ['2_CO2', '4_ETF']}
        t += timedelta(minutes=1)
    return DAY, dict(settle=settle, mkt=mkt, model=out)

if __name__ == '__main__':
    with Pool(8) as pl:
        res = [r for r in pl.map(run, days[-16:]) if r]
    res = res[-14:]
    pickle.dump(dict(res), open(Path(__file__).parent / 'cache.pkl', 'wb'))
    print([d for d, _ in res])
