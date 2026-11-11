"""FLOW +72 decision: distribution of (settle - value at 16:20) historically, overall and conditional on
FLOW having FALLEN over the previous 30 min (today: 1659@15:54 -> 1549@16:19)."""
import json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
df = pd.DataFrame(json.loads((ROOT / 'data/hist.json').read_text())['records']).dropna()
df['ts'] = pd.to_datetime(df.Minutes1DK); df = df.sort_values('ts').set_index('ts')
F = 1000 + df.Exchange_Sum / 3
out = []
for day, g in F.groupby(F.index.date):
    g = g.between_time('15:30', '17:45')
    try:
        now = g.at_time('16:20').iloc[0]; prev = g.at_time('15:50').iloc[0]
        settle = g.between_time('17:40', '17:44').mean()
    except IndexError:
        continue
    out.append({'day': str(day), 'chg_prev30': now - prev, 'drift_to_settle': settle - now})
d = pd.DataFrame(out)
rec = d[d.day >= '2026-10-25']
def stats(x, lbl):
    x = x.drift_to_settle
    print(f"{lbl:38s} n={len(x):2d} mean {x.mean():+6.1f} median {x.median():+6.1f} sd {x.std():5.1f} P(up) {(x > 0).mean():.0%} p10 {x.quantile(.1):+.0f} p90 {x.quantile(.9):+.0f}")
stats(d, 'all days 16:20->settle')
stats(rec, 'since 25 Oct')
stats(d[d.chg_prev30 < -30], 'all days, FLOW fell >30 in prior 30m')
stats(rec[rec.chg_prev30 < -30], 'since 25 Oct, fell >30 in prior 30m')
print('corr(prior 30m change, drift to settle):', round(d.chg_prev30.corr(d.drift_to_settle), 2))
b = np.polyfit(d.chg_prev30, d.drift_to_settle, 1); print('regression drift = %.2f*chg_prev30 %+.1f -> today (chg=-110): %+.1f' % (b[0], b[1], b[0] * -110 + b[1]))
