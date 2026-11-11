"""Fast backtest simulator for the 15:00-17:45 session on historical Energinet days.

Usage:
  .venv/bin/python -I sim/sim.py                 # baseline (params.json) report
  .venv/bin/python -I sim/sim.py --grid          # grid search, prints best params
  .venv/bin/python -I sim/sim.py --lag 1 --noise 1.0 --mm-half 3 10

Plug in a new fair value model:
  def my_fair(rows, now, params) -> {product: (fair, sigma)}, plus optional '_range_floor' key
      rows : dict of numpy arrays {'t': minute-of-day, '1_WIND', '2_CO2', '3_FLOW'} (only rows visible
             to us, i.e. t <= now - lag, ascending; includes the hour before 15:00)
      now  : minute of day (float), e.g. 15:00 -> 900.0
  run(days, lambda: BaselineStrategy(params, fair_fn=my_fair), cfg)
  Fair outputs are memoised by (day, n_rows, now, params) -> keep fair_fn a pure function; set
  my_fair.param_keys = [...] (params it reads) so grid combos differing only in take_k etc. share cache.

Market model (see SimConfig): house_mm quotes around the live value it sees (lag mm_lag, avg of
mm_avg rows), half-spread uniform in [mm_half_lo, mm_half_hi], mm_levels levels mm_level_gap apart,
mm_size lots each, refreshed every step (does not move when lifted). Our TAKE orders sweep that book.
Our passive QUOTES fill only when they improve on the mm's best price: noise traders send
Poisson(noise_rate per minute) 1-lot orders per side, each hits our quote if it is inside the mm.
"""
import argparse
import itertools
import json
import math
import sys
from collections import namedtuple
from dataclasses import dataclass, replace
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ['1_WIND', '2_CO2', '3_FLOW', '4_ETF', '5_WIND_RANGE']
BASE = ['1_WIND', '2_CO2', '3_FLOW']
TYPICAL_15 = {'1_WIND': 14, '2_CO2': 24, '3_FLOW': 31, '4_ETF': 41, '5_WIND_RANGE': 5.7}
OPEN, WIN, CLOSE = 15 * 60, 17 * 60 + 40, 17 * 60 + 45

Order = namedtuple('Order', 'product side price vol kind')  # side 'B'/'S', kind 'take'/'quote'


# ---------------------------------------------------------------- data
def load_days(path=ROOT / 'data' / 'hist.json'):
    """-> list of (date_str, rows) with rows = dict of numpy arrays 14:00..17:45 ascending."""
    df = pd.DataFrame(json.loads(Path(path).read_text())['records']).dropna()
    df['ts'] = pd.to_datetime(df['Minutes1DK'])
    df = df.sort_values('ts')
    df['1_WIND'] = (df.OnshoreWindPower + df.OffshoreWindPower) / 3
    df['2_CO2'] = 10 * df.CO2Emission
    df['3_FLOW'] = 1000 + df.Exchange_Sum / 3
    df['t'] = df.ts.dt.hour * 60 + df.ts.dt.minute
    days = []
    for d, g in df.groupby(df.ts.dt.date):
        g = g[(g.t >= OPEN - 60) & (g.t <= CLOSE)]
        sess = g[(g.t >= OPEN) & (g.t <= CLOSE)]
        if len(sess) < 160 or (g.t.between(WIN, CLOSE - 1)).sum() < 5:
            continue
        days.append((str(d), {k: g[k].to_numpy(float) for k in ['t'] + BASE}))
    return days


def settlement(rows):
    t = rows['t']
    w = (t >= WIN) & (t < CLOSE)
    s = {p: float(rows[p][w].mean()) for p in BASE}
    s['4_ETF'] = sum(s[p] for p in BASE)
    sess = rows['1_WIND'][(t >= OPEN) & (t <= CLOSE)]
    s['5_WIND_RANGE'] = float(sess.max() - sess.min())
    return s


# ---------------------------------------------------------------- fair value
def _range_mc(hmax, hmin, cur, steps, sd, n=500):
    if steps <= 0:
        return hmax - hmin, 0.0
    paths = cur + np.cumsum(np.random.default_rng(0).normal(0, sd, (n, steps)), axis=1)
    r = np.maximum(hmax, paths.max(1)) - np.minimum(hmin, paths.min(1))
    return float(r.mean()), float(r.std())


_RANGE_CACHE = {}


def baseline_fair(rows, now, p):
    """Replicates fair.py: last-5 avg + drift to 17:40, sigma ~ sqrt(time); range via MC."""
    t = rows['t']
    mins_left = max(CLOSE - now, 0)
    mins_to_win = max(WIN - now, 0)
    out = {}
    win = t >= WIN
    for prod in BASE:
        x = rows[prod]
        if win.any():
            known = int(win.sum())
            f = (x[win].sum() + x[-1] * max(5 - known, 0)) / 5
            s = TYPICAL_15[prod] * 0.15 * max(5 - known, 0) / 5 + 1
        else:
            f = x[-5:].mean() + p['drift_per_hour'].get(prod, 0.0) * mins_to_win / 60 \
                + p['manual_adj'].get(prod, 0.0)
            s = TYPICAL_15[prod] * math.sqrt(max(mins_to_win + 2.5, 1) / 15) * p['sigma_mult']
        out[prod] = (f, s)
    etf = sum(out[q][0] for q in BASE) + p['manual_adj'].get('4_ETF', 0.0)
    s1 = out['1_WIND'][1]
    out['4_ETF'] = (etf, TYPICAL_15['4_ETF'] / TYPICAL_15['1_WIND'] * s1 if mins_to_win > 0
                    else sum(out[q][1] for q in BASE))
    sess = rows['1_WIND'][t >= OPEN]
    if len(sess):
        hmax, hmin = sess.max(), sess.min()
        sd = TYPICAL_15['1_WIND'] / math.sqrt(15) * p['range_vol_mult']
        args = (float(hmax), float(hmin), float(rows['1_WIND'][-1]), int(mins_left), sd)
        if args not in _RANGE_CACHE:
            _RANGE_CACHE[args] = _range_mc(*args)
        m, s = _RANGE_CACHE[args]
        out['5_WIND_RANGE'] = (m + p['manual_adj'].get('5_WIND_RANGE', 0.0), max(s, 1.0))
        out['_range_floor'] = hmax - hmin
    else:
        out['5_WIND_RANGE'], out['_range_floor'] = (0.0, 99.0), 0.0
    return out


baseline_fair.param_keys = ['sigma_mult', 'drift_per_hour', 'manual_adj', 'range_vol_mult']


# ---------------------------------------------------------------- strategy
class Strategy:
    def on_tick(self, now, rows_visible, book, pos):
        """book: {prod: {'bids': [(px, vol)...best first], 'asks': [...]}}, pos: {prod: int}
        -> list[Order]. Quotes live until the next tick (old ones are cancelled)."""
        raise NotImplementedError


class BaselineStrategy(Strategy):
    def __init__(self, params, fair_fn=baseline_fair):
        self.p, self.fair_fn = params, fair_fn

    def on_tick(self, now, rows, book, pos):
        p = self.p
        model = self.fair_fn(rows, now, p)
        floor = model.get('_range_floor', -1e9)
        lim, orders = p['max_pos'], []
        for prod in PRODUCTS:
            if prod in p.get('disabled_products', []):
                continue
            fair, sig = model[prod]
            edge = max(p['min_take_edge'][prod], p['take_k'] * sig)
            ps = pos[prod]
            asks, bids = book[prod]['asks'], book[prod]['bids']
            # TAKE (sweep levels through fair -/+ edge)
            if asks and asks[0][0] < fair - edge and ps < lim:
                lv = [(px, v) for px, v in asks if px < fair - edge]
                vol = int(min(sum(v for _, v in lv), p['take_clip'], lim - ps))
                if vol > 0:
                    orders.append(Order(prod, 'B', lv[-1][0], vol, 'take'))
                    ps += vol
            elif bids and bids[0][0] > fair + edge and ps > -lim:
                lv = [(px, v) for px, v in bids if px > fair + edge]
                px = lv[-1][0]
                vol = int(min(sum(v for _, v in lv), p['take_clip'], lim + ps))
                if vol > 0 and not (prod == '5_WIND_RANGE' and px <= floor):
                    orders.append(Order(prod, 'S', px, vol, 'take'))
                    ps -= vol
            # QUOTE (bot.py requotes using position before this cycle's takes are known; use updated)
            half = max(p['quote_k'] * sig, p['min_take_edge'][prod] * 1.5)
            q = p['quote_size']
            skew = half * ps / lim
            bid, ask = round(fair - half - skew), round(fair + half - skew)
            if prod == '5_WIND_RANGE':
                ask = max(ask, round(floor + p['min_take_edge'][prod]))
            if ps + q <= lim and bid > 0:
                orders.append(Order(prod, 'B', bid, q, 'quote'))
            if ps - q >= -lim:
                orders.append(Order(prod, 'S', ask, q, 'quote'))
        return orders


# ---------------------------------------------------------------- simulator
@dataclass(frozen=True)
class SimConfig:
    lag: int = 2              # minutes of publication lag for us
    mm_lag: int = 2           # ... and for house_mm
    mm_avg: int = 1           # house_mm centres on avg of last mm_avg visible rows
    mm_half_lo: int = 3
    mm_half_hi: int = 10
    mm_levels: int = 3
    mm_level_gap: int = 2
    mm_size: int = 5
    noise_rate: float = 0.5   # 1-lot noise orders per side per minute
    steps_per_min: int = 1    # 4 -> 15-second cycle like bot.py (slower)
    seed: int = 1


_FAIR_CACHE = {}


def _cached_fair(fair_fn, day, n):
    def f(rows, now, p):
        keys = getattr(fair_fn, 'param_keys', None)  # params the fair_fn depends on (None = all)
        sub = p if keys is None else {k: p.get(k) for k in keys}
        key = (id(fair_fn), day, n, now, json.dumps(sub, sort_keys=True))
        if key not in _FAIR_CACHE:
            _FAIR_CACHE[key] = fair_fn(rows, now, p)
        return _FAIR_CACHE[key]
    return f


def _mm_mid(rows, n, cfg):
    mids = {p: float(rows[p][n - cfg.mm_avg:n].mean()) for p in BASE}
    mids['4_ETF'] = sum(mids.values())
    t = rows['t'][:n]
    w = rows['1_WIND'][:n][t >= OPEN]
    mids['5_WIND_RANGE'] = float(w.max() - w.min()) if len(w) else 0.0
    return mids


def sim_day(day, rows, strategy, cfg=SimConfig()):
    """-> {prod: pnl} at settlement."""
    rng = np.random.default_rng(cfg.seed + int(day.replace("-", "")))
    settle = settlement(rows)
    pos = {p: 0 for p in PRODUCTS}
    cash = {p: 0.0 for p in PRODUCTS}
    t = rows['t']
    orig_fair = getattr(strategy, 'fair_fn', None)
    dt = 1.0 / cfg.steps_per_min
    for k in range(int((CLOSE - OPEN) * cfg.steps_per_min)):
        now = OPEN + k * dt
        n_us = int(np.searchsorted(t, now - cfg.lag, side='right'))
        n_mm = int(np.searchsorted(t, now - cfg.mm_lag, side='right'))
        mids = _mm_mid(rows, n_mm, cfg)
        book, half = {}, {}
        for p in PRODUCTS:
            h = rng.integers(cfg.mm_half_lo, cfg.mm_half_hi + 1)
            m = mids[p]
            book[p] = {'bids': [(math.floor(m - h - i * cfg.mm_level_gap), cfg.mm_size) for i in range(cfg.mm_levels)],
                       'asks': [(math.ceil(m + h + i * cfg.mm_level_gap), cfg.mm_size) for i in range(cfg.mm_levels)]}
        visible = {c: rows[c][:n_us] for c in rows}
        if orig_fair is not None:
            strategy.fair_fn = _cached_fair(orig_fair, day, n_us)
        orders = strategy.on_tick(now, visible, book, dict(pos))
        if orig_fair is not None:
            strategy.fair_fn = orig_fair
        for o in orders:
            p, b = o.product, book[o.product]
            if o.kind == 'take' or (o.side == 'B' and o.price >= b['asks'][0][0]) or \
                    (o.side == 'S' and o.price <= b['bids'][0][0]):
                # marketable: fill against mm levels at mm prices
                lv = b['asks'] if o.side == 'B' else b['bids']
                left = o.vol
                for px, v in lv:
                    if left <= 0 or (o.side == 'B' and px > o.price) or (o.side == 'S' and px < o.price):
                        break
                    f = min(v, left)
                    left -= f
                    sgn = 1 if o.side == 'B' else -1
                    pos[p] += sgn * f
                    cash[p] -= sgn * f * px
            else:
                inside = o.price > b['bids'][0][0] if o.side == 'B' else o.price < b['asks'][0][0]
                if inside:
                    f = min(rng.poisson(cfg.noise_rate * dt), o.vol)
                    sgn = 1 if o.side == 'B' else -1
                    pos[p] += sgn * f
                    cash[p] -= sgn * f * o.price
    return {p: cash[p] + pos[p] * settle[p] for p in PRODUCTS}


def run(days, make_strategy, cfg=SimConfig()):
    """-> DataFrame index=date, columns=products + TOTAL."""
    res = {d: sim_day(d, rows, make_strategy(), cfg) for d, rows in days}
    df = pd.DataFrame(res).T
    df['TOTAL'] = df.sum(axis=1)
    return df


def summary(df):
    return pd.DataFrame({'mean': df.mean(), 'std': df.std(), 'pct_losing': (df < 0).mean() * 100,
                         'sharpe': df.mean() / df.std().replace(0, np.nan)}).round(1)


# ---------------------------------------------------------------- grid
GRID = {'sigma_mult': [1.0, 1.5, 2.0], 'take_k': [0.5, 1.0, 1.5],
        'flow_drift': [0, 30, 60, 90], 'quote_k': [1.0, 1.5, 2.5]}


def with_combo(base, combo):
    p = json.loads(json.dumps(base))
    p['sigma_mult'], p['take_k'], p['quote_k'] = combo['sigma_mult'], combo['take_k'], combo['quote_k']
    p['drift_per_hour']['3_FLOW'] = combo['flow_drift']
    return p


def _grid_job(args):
    combo, base, days, cfg = args
    p = with_combo(base, combo)
    df = run(days, lambda: BaselineStrategy(p), cfg)
    return combo, df


def grid(base, days, cfg, procs=10):
    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    # group by fair-relevant params so each worker reuses its fair cache
    combos.sort(key=lambda c: (c['sigma_mult'], c['flow_drift']))
    with Pool(procs) as pool:
        return pool.map(_grid_job, [(c, base, days, cfg) for c in combos], chunksize=9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', action='store_true')
    ap.add_argument('--since', default='2026-10-25')
    ap.add_argument('--lag', type=int, default=2)
    ap.add_argument('--mm-lag', type=int, default=2)
    ap.add_argument('--noise', type=float, default=0.5)
    ap.add_argument('--mm-half', type=int, nargs=2, default=[3, 10])
    ap.add_argument('--steps-per-min', type=int, default=1)
    ap.add_argument('--params', default=str(ROOT / 'params.json'))
    a = ap.parse_args()
    cfg = SimConfig(lag=a.lag, mm_lag=a.mm_lag, noise_rate=a.noise, mm_half_lo=a.mm_half[0],
                    mm_half_hi=a.mm_half[1], steps_per_min=a.steps_per_min)
    base = json.loads(Path(a.params).read_text())
    days = load_days()
    main_days = [d for d in days if d[0] >= a.since]
    print(f'{len(days)} days total, {len(main_days)} since {a.since}; {cfg}')
    pd.set_option('display.width', 200)

    if not a.grid:
        for name, ds in [(f'MAIN (since {a.since})', main_days), ('ALL days', days)]:
            df = run(ds, lambda: BaselineStrategy(base), cfg)
            print(f'\n=== baseline params.json, {name} ===')
            print(summary(df))
        return

    rows = []
    for c, da in grid(base, days, cfg):  # run once on all days, slice the main sample
        df = da[da.index >= a.since]
        rows.append({**c, 'mean': df.TOTAL.mean(), 'std': df.TOTAL.std(), 'pct_lose': (df.TOTAL < 0).mean() * 100,
                     'flow': df['3_FLOW'].mean(), 'all_mean': da.TOTAL.mean(), 'all_lose': (da.TOTAL < 0).mean() * 100})
    g = pd.DataFrame(rows).sort_values('mean', ascending=False).round(1)
    print('\n=== grid top 15 (main sample, TOTAL PnL/day) ===')
    print(g.head(15).to_string(index=False))
    print('\n=== bottom 5 ===')
    print(g.tail(5).to_string(index=False))
    best = g.iloc[0].to_dict()
    bp = with_combo(base, {k: best[k] for k in GRID})
    print('\nBEST:', {k: best[k] for k in GRID})
    print(summary(run(main_days, lambda: BaselineStrategy(bp), cfg)))


if __name__ == '__main__':
    main()
