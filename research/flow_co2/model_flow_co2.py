"""Fair value + sigma for 2_CO2, 3_FLOW (and ETF sigma). Fitted on 47 days 2026-09-25..11-10
(fit.py / analyze.py). Model: settle = x_now + a_post(h) + b(h)*(x_now-1000); a_post = intercept
+ post-clock-change dummy, shrunk 25% toward 0. sigma = blend of post-regime LOO RMSE and robust sd.
Product units throughout. Settlement = mean of 17:40..17:44 rows."""
import math
from datetime import datetime

GRID = [15*60 + 10*i for i in range(17)]  # 15:00 .. 17:40
# CO2 (product units = g*10)
CO2_A = [11.4, 5.3, -29.5, -50.5, -72.2, -68.1, -74.5, -65.1, -71.2, -88.3, -101.1, -53.5, -38.0, -20.6, -31.1, -14.1, -5.0]
CO2_B = [-.308, -.321, -.281, -.268, -.269, -.266, -.220, -.177, -.125, -.096, -.079, -.066, -.027, -.013, .004, .009, -.010]
CO2_S = [140, 160, 150, 140, 135, 125, 115, 105, 100, 95, 95, 80, 72, 70, 62, 38, 18]
# FLOW (product units = 1000 + MW/3)
FLOW_A = [318.0, 299.4, 290.9, 290.0, 260.3, 227.1, 205.8, 202.3, 173.0, 139.6, 90.3, 49.5, 43.6, 46.1, 20.4, 7.4, -4.2]
FLOW_B = [-.326, -.322, -.317, -.311, -.290, -.233, -.196, -.186, -.156, -.122, -.081, -.046, -.031, -.032, -.005, .000, .001]
FLOW_S = [215, 210, 205, 200, 190, 160, 145, 130, 115, 105, 90, 72, 70, 62, 45, 36, 10]
SHRINK = 0.75
# empirical correlations of settle-minus-now drifts (wind/co2/flow), 47 days
RHO_CF, RHO_CW, RHO_FW = 0.55, -0.45, -0.80
SETTLE = [17*60 + 40 + i for i in range(5)]


def _interp(tab, m):
    if m <= GRID[0]:
        return tab[0]
    if m >= GRID[-1]:
        return tab[-1]
    i = int((m - GRID[0]) // 10)
    f = (m - GRID[i]) / 10
    return tab[i] * (1 - f) + tab[i + 1] * f


def _mins(now):
    return now.hour * 60 + now.minute + now.second / 60


def _fair(rows, now, key, A, B, S):
    rows = [r for r in rows if r.get(key) is not None]
    if not rows:
        return None, None
    m = _mins(now)
    known = [r[key] for r in rows if r['t'].hour * 60 + r['t'].minute in SETTLE]
    x = sum(r[key] for r in rows[-3:]) / len(rows[-3:])  # smooth last 3 minutes
    last = rows[-1][key]
    if m >= SETTLE[0] or known:
        n_rem = 5 - len(known)
        fair = (sum(known) + n_rem * last) / 5
        sig = (n_rem / 5) * S[-1] if n_rem else 0.5
        return fair, max(sig, 0.5)
    drift = SHRINK * _interp(A, m) + _interp(B, m) * (x - 1000)
    return x + drift, _interp(S, m)


def co2_fair(rows, now):
    """-> (fair, sigma) for 2_CO2."""
    return _fair(rows, now, '2_CO2', CO2_A, CO2_B, CO2_S)


def flow_fair(rows, now):
    """-> (fair, sigma) for 3_FLOW."""
    return _fair(rows, now, '3_FLOW', FLOW_A, FLOW_B, FLOW_S)


def etf_sigma(sig_wind, sig_co2, sig_flow, now=None):
    """ETF sigma using empirical drift correlations (wind falls -> imports and CO2 rise)."""
    v = (sig_wind**2 + sig_co2**2 + sig_flow**2
         + 2 * RHO_CF * sig_co2 * sig_flow
         + 2 * RHO_CW * sig_co2 * sig_wind
         + 2 * RHO_FW * sig_flow * sig_wind)
    return math.sqrt(max(v, 0.0))


if __name__ == '__main__':
    import json, sys
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Europe/Copenhagen')
    recs = sorted(json.load(open(sys.argv[1]))['records'], key=lambda r: r['Minutes1DK'])
    rows = [{'t': datetime.fromisoformat(r['Minutes1DK']).replace(tzinfo=tz),
             '2_CO2': r['CO2Emission'] * 10 if r['CO2Emission'] is not None else None,
             '3_FLOW': 1000 + r['Exchange_Sum'] / 3 if r['Exchange_Sum'] is not None else None,
             '1_WIND': ((r['OnshoreWindPower'] or 0) + (r['OffshoreWindPower'] or 0)) / 3} for r in recs]
    now = rows[-1]['t']
    c, f = co2_fair(rows, now), flow_fair(rows, now)
    print(now, 'CO2', c, 'FLOW', f, 'ETFsig(windsig=120)', etf_sigma(120, c[1], f[1], now))
