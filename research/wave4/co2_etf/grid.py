import pickle, itertools, statistics as st
from pathlib import Path
C = pickle.load(open(Path(__file__).parent / 'cache.pkl', 'rb'))
HALF = {'2_CO2': 5, '4_ETF': 12}
GMAX = {'2_CO2': 80, '4_ETF': 50}
T0, T1 = 16 * 60 + 48, 17 * 60 + 44

def gap_day(D, p, thr, size, hold, cap, lag):
    h = HALF[p]; pos = 0; pnl = 0.0; lots = []  # (exit_minute, qty signed, entry px)
    S = D['settle'][p]
    def close(lot, t):
        nonlocal pnl
        e, q, px = lot
        if t is None:
            pnl += q * (S - px)
        else:
            mid = D['mkt'][t - lag][p]
            pnl += q * ((mid - h) - px) if q > 0 else q * ((mid + h) - px)
    for t in range(T0, T1 + 1):
        for lot in [l for l in lots if l[0] == t]:
            close(lot, t); lots.remove(lot); pos -= lot[1]
        m = D['model'][t][p]; mid = D['mkt'][t - lag][p]; bid, ask = mid - h, mid + h
        v = m['sig']; q = 0
        if thr < v - ask < GMAX[p] and pos < cap: q = min(size, cap - pos); px = ask
        elif thr < bid - v < GMAX[p] and pos > -cap: q = -min(size, cap + pos); px = bid
        if q:
            pos += q
            lots.append((t + hold if hold else 10**9, q, px))
    for lot in lots:
        close(lot, lot[0] if lot[0] <= T1 else None)
    return pnl

def eg_day(D, p, k, cap, lag):
    h = HALF[p]; pos = 0; cash = 0.0
    for t in range(17 * 60 + 20, T1 + 1):
        m = D['model'][t][p]; mid = D['mkt'][t - lag][p]; bid, ask = mid - h, mid + h
        edge = max(m['edge'], m['tk'] * k * m['sigma']); f = m['fair']
        if ask < f - edge and pos < cap: q = min(10, cap - pos); pos += q; cash -= q * ask
        elif bid > f + edge and pos > -cap: q = min(10, cap + pos); pos -= q; cash += q * bid
    return cash + pos * D['settle'][p]

def summ(x):
    return (sum(v > 0 for v in x) / len(x), st.mean(x), st.pstdev(x), sum(v < 0 for v in x) / len(x))

days = sorted(C)
if __name__ != "__main__": raise SystemExit
for p, thrs in [('2_CO2', [6, 8, 10, 14, 20]), ('4_ETF', [16, 20, 24, 30])]:
    res = []
    for thr, size, hold, cap in itertools.product(thrs, [3, 5, 10], [1, 2, 3, 0], [30, 50]):
        r = {lag: summ([gap_day(C[d], p, thr, size, hold, cap, lag) for d in days]) for lag in (1, 2)}
        res.append(((thr, size, hold, cap), r))
    res.sort(key=lambda x: (-x[1][1][0], -x[1][1][1]))
    print(f'\n{p} GAP top (rank by lag1 P>0, mean)  cfg=(thr,size,hold[0=settle],cap): lag1 Ppos mean sd Pneg | lag2')
    for cfg, r in res[:10]:
        print(cfg, ' '.join(f'{a:.2f} {b:7.0f} {c:6.0f} {e:.2f} |' for a, b, c, e in (r[1], r[2])))
    print('live (10/24,3,0,30):', [r for c, r in res if c == ((10 if p == '2_CO2' else 24), 3, 0, 30)])
    res = []
    for k, cap in itertools.product([0.75, 1, 1.5], [30, 50, 100]):
        r = {lag: summ([eg_day(C[d], p, k, cap, lag) for d in days]) for lag in (1, 2)}
        res.append(((k, cap), r))
    res.sort(key=lambda x: (-x[1][1][0], -x[1][1][1]))
    print(f'{p} ENDGAME (k,cap):')
    for cfg, r in res:
        print(cfg, ' '.join(f'{a:.2f} {b:7.0f} {c:6.0f} {e:.2f} |' for a, b, c, e in (r[1], r[2])))
