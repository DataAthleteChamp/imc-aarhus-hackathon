"""Backtest the nowcast: predict value k min ahead (k=1..3) from data up to t. 15:00-17:45, all 47 days.
Compares persistence vs AR(1)-on-changes (phi fitted on trailing 60 min) vs fixed phi."""
import json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
df = pd.DataFrame(json.loads((ROOT / 'data/hist.json').read_text())['records']).dropna()
df['ts'] = pd.to_datetime(df.Minutes1DK); df = df.sort_values('ts').set_index('ts')
X = pd.DataFrame({'1_WIND': (df.OnshoreWindPower + df.OffshoreWindPower) / 3, '2_CO2': 10 * df.CO2Emission,
                  '3_FLOW': 1000 + df.Exchange_Sum / 3})
X['4_ETF'] = X.sum(axis=1)
res = {}
for prod in X:
    errs = {('persist', k): [] for k in (1, 2, 3)}
    errs.update({('ar_live', k): [] for k in (1, 2, 3)})
    for day, g in X[prod].groupby(X.index.date):
        g = g.between_time('14:00', '17:45').to_numpy()
        if len(g) < 200: continue
        for i in range(61, len(g) - 3):
            x = g[:i + 1]; d = np.diff(x[-61:])
            phi = np.clip(np.corrcoef(d[:-1], d[1:])[0, 1], -0.5, 0.9); last = d[-2:].mean()
            for k in (1, 2, 3):
                errs[('persist', k)].append(g[i + k] - x[-1])
                errs[('ar_live', k)].append(g[i + k] - (x[-1] + last * sum(phi ** j for j in range(1, k + 1))))
    res[prod] = {f'{m}{k}': round(float(np.sqrt(np.mean(np.square(v)))), 2) for (m, k), v in errs.items()}
print(pd.DataFrame(res).T.to_string())
