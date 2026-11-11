"""Replay a past day through the LIVE models (fair.compute_fair incl. endgame + nowcast).
Usage: .venv/bin/python -I research/yesterday/replay_day.py 2026-11-10
Part 1: prediction accuracy vs actual settlement through the afternoon.
Part 2: strategy PnL in a lagged market (mid = value at T-2 min, half-spreads below):
        gap taker (live params) + endgame taker from 17:20 (live schedule, cap 50), all held to settle."""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import fair as F

DAY = sys.argv[1] if len(sys.argv) > 1 else '2026-11-10'
HALF = {'1_WIND': 3, '2_CO2': 5, '3_FLOW': 6, '4_ETF': 12, '5_WIND_RANGE': 2}
recs = json.loads((ROOT / 'data/hist.json').read_text())['records']
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
win = [byt[at(17, 40) + timedelta(minutes=i)] for i in range(5)]
settle = {p: sum(r[p] for r in win) / 5 for p in ['1_WIND', '2_CO2', '3_FLOW']}
settle['4_ETF'] = sum(settle.values())
sess = [r['1_WIND'] for r in rows if at(15, 0) <= r['t'] <= at(17, 45)]
settle['5_WIND_RANGE'] = max(sess) - min(sess)

def visible(now):  # Energinet minute M is public at ~M+1:15
    cut = now - timedelta(seconds=75)
    return [r for r in rows if r['t'] + timedelta(minutes=1) <= cut + timedelta(minutes=1) and r['t'] <= cut - timedelta(seconds=0)]

def val(r, p):
    return r[p] if p != '4_ETF' else r['1_WIND'] + r['2_CO2'] + r['3_FLOW']

print(f'DAY {DAY}  settlement:', {k: round(v, 1) for k, v in settle.items()})
print('\nPart 1: prediction error (bot fair - settle) and sigma')
print(f"{'time':6s} " + ' '.join(f'{p:>18s}' for p in F.PRODUCTS))
models = {}
for hh, mm in [(15, 0), (15, 30), (16, 0), (16, 30), (17, 0), (17, 20), (17, 30), (17, 35), (17, 40), (17, 42), (17, 44)]:
    now = at(hh, mm) + timedelta(seconds=30)
    F.fetch_rows = lambda n, _now=now: visible(_now)
    m = F.compute_fair(now)
    models[(hh, mm)] = m
    print(f'{hh:02d}:{mm:02d}  ' + ' '.join(f"{m['fair'][p] - settle[p]:+8.1f} ±{m['sigma'][p]:6.1f}  " for p in F.PRODUCTS))

# Part 2: minute-by-minute strategy sim
params = F.load_params()
pos = {p: 0 for p in F.PRODUCTS}; cash = {p: 0.0 for p in F.PRODUCTS}; ntr = {p: 0 for p in F.PRODUCTS}
gap_pnl = {p: 0.0 for p in F.PRODUCTS}
t = at(15, 2)
while t <= at(17, 44):
    now = t + timedelta(seconds=20)
    vis = visible(now)
    mkt_row = byt.get(t - timedelta(minutes=2))
    if not vis or mkt_row is None:
        t += timedelta(minutes=1); continue
    F.fetch_rows = lambda n, _v=vis: _v
    m = F.compute_fair(now)
    p_ = m['params']
    for p in ['1_WIND', '2_CO2', '3_FLOW', '4_ETF']:
        mid = val(mkt_row, p); bid, ask = mid - HALF[p], mid + HALF[p]
        # endgame taker (from 17:20 via schedule: take_k lowers from 99)
        edge = max(p_['min_take_edge'][p], p_['take_k'] * m['sigma'][p])
        lim = p_['max_pos']
        f = m['fair'][p]
        q = 0
        if ask < f - edge and pos[p] < lim:
            q = min(10, lim - pos[p]); pos[p] += q; cash[p] -= q * ask
        elif bid > f + edge and pos[p] > -lim:
            q = min(10, lim + pos[p]); pos[p] -= q; cash[p] += q * bid
        if q:
            ntr[p] += 1
            continue
        # gap taker toward latest published value (nowcast for CO2), exit 2 min later at touch
        thr = params['gap_thr'].get(p)
        if thr is None:
            continue
        v = (m['nowcast'] if p == '2_CO2' else m['actual'])[p]
        later = byt.get(t)  # market 2 min later = value now
        if later is None:
            continue
        mid2 = val(later, p)
        if thr < v - ask < params['gap_max'].get(p, 1e9):
            gap_pnl[p] += 3 * ((mid2 - HALF[p]) - ask); ntr[p] += 1
        elif thr < bid - v < params['gap_max'].get(p, 1e9):
            gap_pnl[p] += 3 * (bid - (mid2 + HALF[p])); ntr[p] += 1
    t += timedelta(minutes=1)
print('\nPart 2: strategy PnL on', DAY, '(endgame positions held to settlement; gap trades 3 lots, exit after 2 min)')
tot = 0
for p in ['1_WIND', '2_CO2', '3_FLOW', '4_ETF']:
    eg = cash[p] + pos[p] * settle[p]
    tot += eg + gap_pnl[p]
    print(f"{p:8s} endgame pos {pos[p]:>4} pnl {eg:>8.0f} | gap pnl {gap_pnl[p]:>7.0f} | signals {ntr[p]}")
print('TOTAL', round(tot))
