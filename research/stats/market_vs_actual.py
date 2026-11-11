"""Market mid vs live Energinet value, per product; ETF vs component mids vs actual sum.
Run: .venv/bin/python -I research/stats/market_vs_actual.py"""
import json
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
rows = json.loads((ROOT / 'data/live_rows.json').read_text())['rows']
act = pd.DataFrame(rows)
act['t'] = pd.to_datetime(act['t']).dt.tz_localize(None)
act = act.set_index('t').sort_index()
act['4_ETF'] = act['1_WIND'] + act['2_CO2'] + act['3_FLOW']

recs = []
for line in (ROOT / 'data/books.jsonl').read_text().splitlines():
    d = json.loads(line)
    b = [x for x in d['b'] if x[1] - x[2] > 0]
    a = [x for x in d['a'] if x[1] - x[2] > 0]
    if b and a:
        recs.append((datetime.fromtimestamp(d['ts']), d['p'], (b[0][0] + a[0][0]) / 2, a[0][0] - b[0][0]))
bk = pd.DataFrame(recs, columns=['ts', 'p', 'mid', 'spr'])
mids = bk.pivot_table(index=pd.Grouper(key='ts', freq='15s'), columns='p', values='mid', aggfunc='last').ffill()
sprs = bk.groupby('p')['spr'].median()
print('window', mids.index.min(), '->', mids.index.max(), 'n', len(mids))
# Energinet value for minute M becomes visible ~M+1:15; compare mid at time T with actual of minute T-lag
for prod in ['1_WIND', '2_CO2', '3_FLOW', '4_ETF', '5_WIND_RANGE']:
    if prod not in mids or prod == '5_WIND_RANGE':
        continue
    m = mids[prod].dropna()
    res = {}
    for lag in [0, 1, 2, 3, 5]:
        a = act[prod].reindex(m.index.floor('min') - pd.Timedelta(minutes=lag), method='ffill').to_numpy()
        diff = m.to_numpy() - a
        ok = ~np.isnan(diff)
        res[lag] = (np.nanmean(diff), np.sqrt(np.nanmean(diff[ok] ** 2)))
    best = min(res, key=lambda k: res[k][1])
    print(f"{prod:7s} median spread {sprs.get(prod, np.nan):5.1f} | mid-actual by lag(min): " +
          ' '.join(f"{k}:{v[0]:+.0f}/{v[1]:.0f}" for k, v in res.items()) + f"  -> best-tracking lag {best}")
if all(c in mids for c in ['1_WIND', '2_CO2', '3_FLOW', '4_ETF']):
    basket = mids['1_WIND'] + mids['2_CO2'] + mids['3_FLOW']
    gap = (mids['4_ETF'] - basket).dropna()
    print(f"ETF mid - basket of mids: mean {gap.mean():+.1f} sd {gap.std():.1f} min {gap.min():+.0f} max {gap.max():+.0f}")
    print('last 8 (15s):'); print(pd.DataFrame({'etf': mids['4_ETF'], 'basket': basket, 'gap': gap}).tail(8).round(0).to_string())
# 1-min changes of actual: volatility and autocorrelation (momentum vs mean reversion)
d = act[['1_WIND', '2_CO2', '3_FLOW', '4_ETF']].diff().dropna().iloc[-90:]
print('\nEnerginet 1-min changes (last 90 min): sd', d.std().round(1).to_dict())
print('lag-1 autocorr (>0 momentum, <0 mean-reversion):', {c: round(d[c].autocorr(1), 2) for c in d})
print('corr of 1-min changes:\n', d.corr().round(2).to_string())
d5 = act[['1_WIND', '2_CO2', '3_FLOW']].diff(5).dropna().iloc[-90:]
print('5-min change autocorr (lag 5):', {c: round(d5[c].autocorr(5), 2) for c in d5})
