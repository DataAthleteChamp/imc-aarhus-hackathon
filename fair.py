"""Fair-value model: predicts each product's settlement value (avg 17:40-17:45 CET).

fair = latest 5-min average + drift (from params.json) ; sigma shrinks as the close approaches.
Inside the settlement window, the already-known minutes are locked in.
"""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import sys

import numpy as np
import requests

TZ = ZoneInfo('Europe/Copenhagen')
API = 'https://api.energidataservice.dk/dataset/PowerSystemRightNow'
PARAMS_FILE = Path(__file__).with_name('params.json')
_HERE = Path(__file__).parent
sys.path[:0] = [str(_HERE / 'research' / 'wind'), str(_HERE / 'research' / 'flow_co2')]
import model_flow_co2 as MFC  # noqa: E402
import model_wind as MW  # noqa: E402
PRODUCTS = ['1_WIND', '2_CO2', '3_FLOW', '4_ETF', '5_WIND_RANGE']
# typical 15-min move per product (player guide)
TYPICAL_15 = {'1_WIND': 14, '2_CO2': 24, '3_FLOW': 31, '4_ETF': 41, '5_WIND_RANGE': 5.7}


# (start minute-of-day, take_k, max_pos, min_take_edge) - from research/endgame backtest
ENDGAME_SCHEDULE = [
    (17 * 60 + 20, 1.0, 90, {'1_WIND': 6, '2_CO2': 12, '3_FLOW': 10, '4_ETF': 15}),
    (17 * 60 + 30, 0.8, 98, {'1_WIND': 4, '2_CO2': 8, '3_FLOW': 6, '4_ETF': 10}),
    (17 * 60 + 38, 0.6, 98, {'1_WIND': 2, '2_CO2': 5, '3_FLOW': 4, '4_ETF': 6}),
    (17 * 60 + 42, 0.5, 98, {'1_WIND': 1.5, '2_CO2': 4, '3_FLOW': 3, '4_ETF': 5}),
]


def load_params():
    return json.loads(PARAMS_FILE.read_text())


def today_at(h, m, now=None):
    now = now or datetime.now(TZ)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


_CACHE = {'t': 0.0, 'rows': None}


def fetch_rows(now):
    """Energinet rate-limits (~1 req / 30 s, HTTP 429): cache and reuse on error."""
    import time
    if _CACHE['rows'] and time.time() - _CACHE['t'] < 15:
        return _CACHE['rows']
    try:
        rows = _fetch_rows(now)
        _CACHE.update(t=time.time(), rows=rows)
        try:  # share with research scripts so they don't hit Energinet's per-IP rate limit
            (_HERE / 'data' / 'live_rows.json').write_text(json.dumps(
                {'fetched_at': datetime.now(TZ).isoformat(),
                 'rows': [{**r, 't': r['t'].isoformat()} for r in rows]}))
        except Exception:
            pass
        return rows
    except Exception as e:
        if _CACHE['rows']:
            print('energinet error, using cache:', e)
            return _CACHE['rows']
        raise


def _fetch_rows(now):
    start = min(today_at(14, 0, now), now - timedelta(hours=1)).astimezone(ZoneInfo('UTC'))
    r = requests.get(API, timeout=20, params={
        'start': start.strftime('%Y-%m-%dT%H:%M'), 'limit': 0, 'sort': 'Minutes1UTC asc',
        'columns': 'Minutes1DK,CO2Emission,OffshoreWindPower,OnshoreWindPower,Exchange_Sum'})
    r.raise_for_status()
    rows = []
    for x in r.json()['records']:
        if None in x.values():
            continue
        t = datetime.fromisoformat(x['Minutes1DK']).replace(tzinfo=TZ)
        rows.append({'t': t,
                     '1_WIND': (x['OnshoreWindPower'] + x['OffshoreWindPower']) / 3,
                     '2_CO2': 10 * x['CO2Emission'],
                     '3_FLOW': 1000 + x['Exchange_Sum'] / 3})
    return rows


def range_mc(hist_max, hist_min, cur, minutes_left, sd_per_min, n=4000):
    """Expected final (max-min) of wind (product units) via Gaussian random walk."""
    steps = max(int(minutes_left), 0)
    if steps == 0:
        return hist_max - hist_min, 0.0
    rng = np.random.default_rng(0)
    paths = cur + np.cumsum(rng.normal(0, sd_per_min, (n, steps)), axis=1)
    mx = np.maximum(hist_max, paths.max(axis=1))
    mn = np.minimum(hist_min, paths.min(axis=1))
    rngs = mx - mn
    return float(rngs.mean()), float(rngs.std())


def compute_fair(now=None):
    p = load_params()
    now = now or datetime.now(TZ)
    rows = fetch_rows(now)
    open_, close = today_at(15, 0, now), today_at(17, 45, now)
    win_start = today_at(17, 40, now)
    mins_left = max((close - now).total_seconds() / 60, 0)
    mins_to_win = max((win_start - now).total_seconds() / 60, 0)

    last = rows[-5:]
    fair, sigma = {}, {}
    for prod in ['1_WIND', '2_CO2', '3_FLOW']:
        cur = mean(r[prod] for r in last)
        drift = p['drift_per_hour'].get(prod, 0.0) * mins_to_win / 60 + p['manual_adj'].get(prod, 0.0)
        in_win = [r[prod] for r in rows if r['t'] >= win_start]
        if in_win:  # inside settlement window: lock known minutes
            known = len(in_win)
            fair[prod] = (sum(in_win) + rows[-1][prod] * max(5 - known, 0)) / 5
            sigma[prod] = TYPICAL_15[prod] * 0.15 * max(5 - known, 0) / 5 + 1
        else:
            fair[prod] = cur + drift
            sigma[prod] = TYPICAL_15[prod] * math.sqrt(max(mins_to_win + 2.5, 1) / 15) * p['sigma_mult']
    fair['4_ETF'] = fair['1_WIND'] + fair['2_CO2'] + fair['3_FLOW'] + p['manual_adj'].get('4_ETF', 0.0)
    sigma['4_ETF'] = TYPICAL_15['4_ETF'] / TYPICAL_15['1_WIND'] * sigma['1_WIND'] if mins_to_win > 0 else \
        sigma['1_WIND'] + sigma['2_CO2'] + sigma['3_FLOW']

    sess = [r['1_WIND'] for r in rows if open_ <= r['t'] <= close]
    if sess:
        hmax, hmin = max(sess), min(sess)
        sd_min = TYPICAL_15['1_WIND'] / math.sqrt(15) * p['range_vol_mult']
        m, s = range_mc(hmax, hmin, rows[-1]['1_WIND'], mins_left, sd_min)
        fair['5_WIND_RANGE'] = m + p['manual_adj'].get('5_WIND_RANGE', 0.0)
        sigma['5_WIND_RANGE'] = max(s, 1.0)
        floor = hmax - hmin
    else:
        fair['5_WIND_RANGE'], sigma['5_WIND_RANGE'], floor = 0.0, 99.0, 0.0
    if p.get('model', 'research') == 'research':
        try:
            adj = p['manual_adj']
            fw, sw = MW.wind_fair(rows, now)
            fc, sc = MFC.co2_fair(rows, now)
            ff, sf = MFC.flow_fair(rows, now)
            rf, rs, rfloor = MW.range_fair(rows, now)
            fair.update({'1_WIND': fw + adj['1_WIND'], '2_CO2': fc + adj['2_CO2'],
                         '5_WIND_RANGE': rf + adj['5_WIND_RANGE']})
            # 3_FLOW: blend baseline time-of-day drift (won backtest) with research mean-reversion
            # model (reacts to today's level). Disagreement between them widens sigma.
            wb = p.get('flow_blend', 0.5)
            fb, sb = fair['3_FLOW'], sigma['3_FLOW']
            fair['3_FLOW'] = wb * fb + (1 - wb) * (ff + adj['3_FLOW'])
            sigma['3_FLOW'] = max(sb, sf * p['sigma_mult']) + abs(fb - ff) * 0.25
            fair['4_ETF'] = fair['1_WIND'] + fair['2_CO2'] + fair['3_FLOW'] + adj['4_ETF']
            sm = p['sigma_mult']
            sigma.update({'1_WIND': sw * sm, '2_CO2': sc * sm,
                          '4_ETF': MFC.etf_sigma(sw, sc, sf, now) * sm, '5_WIND_RANGE': max(rs, 1.0) * sm})
            floor = rfloor
        except Exception as e:
            print('research model failed, using baseline:', repr(e))
    # ---- endgame (from 17:20): minute-level model + aggressive schedule ----
    if now >= today_at(17, 20, now) and p.get('endgame_enabled', True):
        try:
            import endgame
            eg = endgame.endgame_fair(rows, now)
            adj = p['manual_adj']
            for prod in PRODUCTS:
                if prod in eg:
                    fair[prod] = eg[prod][0] + adj.get(prod, 0.0)
                    sigma[prod] = max(eg[prod][1], 0.5)
            floor = eg.get('_range_floor', floor)
            p = dict(p)
            hm = now.hour * 60 + now.minute
            for start, tk, mp, me in ENDGAME_SCHEDULE:
                if hm >= start:
                    p['take_k'], p['max_pos'] = tk, mp
                    p['min_take_edge'] = {**p['min_take_edge'], **me}
        except Exception as e:
            print('endgame model failed:', repr(e))
    lr = rows[-1]
    actual = {'1_WIND': lr['1_WIND'], '2_CO2': lr['2_CO2'], '3_FLOW': lr['3_FLOW'],
              '4_ETF': lr['1_WIND'] + lr['2_CO2'] + lr['3_FLOW'], '5_WIND_RANGE': floor}
    return {'fair': fair, 'sigma': sigma, 'range_floor': floor, 'actual': actual,
            'data_time': rows[-1]['t'].strftime('%H:%M'), 'mins_left': mins_left, 'params': p}


if __name__ == '__main__':
    r = compute_fair()
    print('data', r['data_time'], 'mins_left %.0f' % r['mins_left'], 'range_floor %.1f' % r['range_floor'])
    for k in PRODUCTS:
        print(f"{k:14s} fair {r['fair'][k]:8.1f}  sigma {r['sigma'][k]:6.1f}")
