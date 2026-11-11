"""Endgame fair value (17:20-17:45): persistence + damped short trend, locks known window minutes.

endgame_fair(rows, now, lag_min=1.5) -> {prod: (fair, sigma)}  (+ '_range_floor': float)
  rows: list of {'t': datetime(TZ), '1_WIND','2_CO2','3_FLOW'} ascending (fair.fetch_rows / live_rows.json)
  now : datetime (Europe/Copenhagen). Settlement = mean of rows 17:40..17:44.
Sigma = empirical RMSE on 47 hist days (research/endgame/fit.py) keyed by the last visible minute,
scaled by today's recent 1-min vol vs historical.
"""
import math
from datetime import datetime, timedelta
import numpy as np

WIN, CLOSE, OPEN = 17*60 + 40, 17*60 + 45, 15*60
SETTLE = list(range(WIN, WIN + 5))
RANGE_VOL_MULT = 1.0
BASE = ['1_WIND', '2_CO2', '3_FLOW']
PARAMS = {'1_WIND': (10, 0.0), '2_CO2': (10, 0.0), '3_FLOW': (10, 0.0)}  # (trend window, damping phi)
SIGMA_TAB = {}   # prod -> {last_visible_minute: rmse}; filled from research/endgame/sigma.json
HIST_VOL = {}    # prod -> median hist 1-min |diff| std at 17:00-17:40
try:
    import json
    from pathlib import Path
    _j = json.loads((Path(__file__).parent / 'research' / 'endgame' / 'sigma.json').read_text())
    SIGMA_TAB = {p: {int(k): v for k, v in d.items()} for p, d in _j['sigma'].items()}
    HIST_VOL = _j['hist_vol']
    PARAMS.update({p: tuple(v) for p, v in _j.get('params', {}).items()})
except Exception:
    pass


def forecast_path(t, x, W, phi, upto=CLOSE - 1):
    """Point forecasts for minutes last_t+1..upto: x_L + slope*sum_{j<=h} phi^j."""
    tl = int(t[-1]); xl = float(x[-1])
    n = min(W, len(x) - 1)
    slope = (xl - float(x[-1 - n])) / n if n > 0 else 0.0
    out = {}
    cum = 0.0
    for h, m in enumerate(range(tl + 1, upto + 1), 1):
        cum += phi ** h
        out[m] = xl + slope * cum
    return out


def forecast_settle(t, x, W, phi):
    t = np.asarray(t, int); x = np.asarray(x, float)
    known = {int(ti): xi for ti, xi in zip(t, x) if WIN <= ti < CLOSE}
    if known:  # inside window: pure persistence backtests better (trend adds noise)
        phi = 0.0
    path = forecast_path(t, x, W, phi) if len(known) < 5 else {}
    return float(np.mean([known.get(m, path.get(m, x[-1])) for m in SETTLE]))


def _sigma(prod, last_t, x):
    tab = SIGMA_TAB.get(prod)
    if not tab:
        return 5.0
    k = min(max(last_t, min(tab)), max(tab))
    s = tab[k]
    if prod in HIST_VOL and len(x) > 15:
        v = float(np.std(np.diff(x[-16:])))
        s *= float(np.clip(v / HIST_VOL[prod], 0.7, 2.0))
    return s


def _mod(d):
    return d.hour * 60 + d.minute


def endgame_fair(rows, now, lag_min=1.5):
    nowm = _mod(now) + now.second / 60
    vis = [r for r in rows if r['t'] <= now and r['t'].date() == now.date()]  # lag_min: info only
    t = np.array([_mod(r['t']) for r in vis], int)
    out = {}
    sig = {}
    for p in BASE:
        x = np.array([float(r[p]) for r in vis])
        W, phi = PARAMS[p]
        f = forecast_settle(t, x, W, phi)
        nk = sum(1 for ti in t if WIN <= ti < CLOSE)
        s = 0.0 if nk >= 5 else _sigma(p, int(t[-1]), x)
        out[p] = (f, s); sig[p] = s
    # ETF: use empirical ETF table if present, else sum in quadrature with mild negative corr
    x_etf = np.array([sum(float(r[p]) for p in BASE) for r in vis])
    s_etf = 0.0 if all(sig[p] == 0 for p in BASE) else _sigma('4_ETF', int(t[-1]), x_etf)
    out['4_ETF'] = (sum(out[p][0] for p in BASE), s_etf)
    # Range: exact floor + MC extension over unseen minutes up to 17:45 inclusive
    w = np.array([float(r['1_WIND']) for r in vis])
    sess = w[(t >= OPEN) & (t <= CLOSE)]
    hmax, hmin = float(sess.max()), float(sess.min())
    steps = CLOSE - int(t[-1])
    if steps <= 0:
        out['5_WIND_RANGE'] = (hmax - hmin, 0.0)
    else:
        vol = float(np.clip(np.std(np.diff(w[-31:])), 1.0, 15.0))
        rng = np.random.default_rng(0)
        vol *= RANGE_VOL_MULT * (1.0 + 0.8 * min(steps, 10) / 10)  # RW underestimates ramps; calibrated on hist 17:20-17:45
        paths = w[-1] + np.cumsum(rng.normal(0, vol, (3000, steps)), 1)
        rr = np.maximum(hmax, paths.max(1)) - np.minimum(hmin, paths.min(1))
        out['5_WIND_RANGE'] = (float(rr.mean()), max(float(rr.std()), 0.3))
    out['_range_floor'] = hmax - hmin
    return out


if __name__ == '__main__':
    import json as _j
    from pathlib import Path as _P
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('Europe/Copenhagen')
    d = _j.loads((_P(__file__).parent / 'data' / 'live_rows.json').read_text())
    rows = [{**r, 't': datetime.fromisoformat(r['t'])} for r in d['rows']]
    now = datetime.now(TZ)
    for k, v in endgame_fair(rows, now).items():
        print(k, v)
