"""Wind fair-value models (units: 1_WIND = (on+off)/3).
Backtested on 47 days (research/wind/backtest.py, bt2.py, bt_range.py, validate.py).
Model: path = x0 + 0.5*trend60*s + D*s + RW, D~N(0,DRIFT_SD) per path (ramp risk),
RW per-minute std = realized 30-min 1-min-diff std (clipped). Pure Brownian underestimates
both the settle error and range growth by ~2x because wind error is ramp (drift) dominated.
"""
from datetime import datetime, timedelta
import numpy as np

DRIFT_SD = 1.3     # MW(/3) per minute random drift sd, calibrated on hist
TREND_DAMP = 0.5   # weight on 60-min OLS slope
N_PATHS = 4000
_rng = np.random.default_rng(1)

def _prep(rows, now):
    rows = [r for r in rows if r['t'] <= now and r.get('1_WIND') is not None]
    t = [r['t'] for r in rows]; x = np.array([float(r['1_WIND']) for r in rows])
    return t, x

def _day_at(now, h, m):
    return now.replace(hour=h, minute=m, second=0, microsecond=0)

def _sim(x, now, end_min_from_now, n=N_PATHS):
    last = x[-61:] if len(x) >= 61 else x
    slope = np.polyfit(np.arange(len(last)), last, 1)[0] if len(last) >= 5 else 0.0
    d = np.diff(x[-31:]) if len(x) > 2 else np.array([5.0])
    vol = float(np.clip(np.std(d), 2.0, 15.0))
    T = max(int(end_min_from_now), 0)
    if T == 0:
        return np.full((n, 1), x[-1]), vol
    s = np.arange(1, T + 1)
    D = _rng.normal(0, DRIFT_SD, (n, 1))
    rw = np.cumsum(_rng.normal(0, vol, (n, T)), 1)
    return x[-1] + (TREND_DAMP * slope + D) * s + rw, vol

def wind_fair(rows, now, fc_delta=None):
    """fair, sigma for avg of 17:40..17:44 values. fc_delta (optional) = forecast(17:42)-forecast(now)
    in /3 units from Forecasts_5Min ForecastCurrent; blended 50/50 with trend (not backtested)."""
    t, x = _prep(rows, now)
    s0 = _day_at(now, 17, 40)
    known = [xi for ti, xi in zip(t, x) if s0 <= ti < s0 + timedelta(minutes=5)]
    rem = 5 - len(known)
    if rem <= 0:
        return float(np.mean(known[:5])), 0.0
    k0 = max(int((s0 - now).total_seconds() // 60), 0)  # minutes until first unknown settle minute
    k0 = max(k0, 1) if not known else 1
    paths, vol = _sim(x, now, k0 + rem - 1)
    fut = paths[:, k0 - 1:k0 - 1 + rem]
    est = (np.sum(known) + fut.sum(1)) / 5.0
    fair = float(est.mean()); sig = float(est.std()) * (1.12 if k0 > 40 else 1.0)  # fat-tail calib
    if fc_delta is not None:
        fair = 0.5 * fair + 0.5 * (x[-1] + fc_delta)
    return fair, sig

def range_fair(rows, now):
    """fair, sigma, floor for (max-min over 15:00..17:45)/... rows already in /3 units."""
    t, x = _prep(rows, now)
    a = _day_at(now, 15, 0); e = _day_at(now, 17, 45)
    sess = np.array([xi for ti, xi in zip(t, x) if a <= ti <= e])
    if len(sess) == 0:
        sess = x[-1:]
    hi, lo = sess.max(), sess.min(); floor = float(hi - lo)
    T = int((e - max(now, a)).total_seconds() // 60)
    if T <= 0:
        return floor, 0.0, floor
    paths, _ = _sim(x, now, T)
    fr = np.maximum(paths.max(1), hi) - np.minimum(paths.min(1), lo)
    if now < a:  # session not started: range will start from value at 15:00
        idx = int((a - now).total_seconds() // 60)
        sub = paths[:, max(idx - 1, 0):]
        fr = sub.max(1) - sub.min(1)
        floor = 0.0
    infl = 1.35 if T > 50 else 1.0  # calib: MC sd too small early (z-sd 1.2-1.46)
    return float(fr.mean()), float(fr.std()) * infl, floor
