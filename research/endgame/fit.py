"""Grid-fit endgame forecaster params + sigma tables on hist.json (17:20..17:44, lag 2)."""
import sys, json, itertools
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sim')); sys.path.insert(0, str(ROOT))
from sim import load_days, settlement
import endgame as EG
from endgame import WIN, CLOSE

BASE = ['1_WIND', '2_CO2', '3_FLOW']
days = load_days()
LAG = 2
NOWS = range(17*60+20, 17*60+45)

def errs(W, phi):
    E = {p: {n: [] for n in NOWS} for p in BASE + ['4_ETF']}
    for d, r in days:
        s = settlement(r)
        for now in NOWS:
            m = r['t'] <= now - LAG
            f = {}
            for p in BASE:
                f[p] = EG.forecast_settle(r['t'][m], r[p][m], W, phi)
                E[p][now].append(f[p] - s[p])
            E['4_ETF'][now].append(sum(f.values()) - s['4_ETF'])
    return E

def rmse(E):
    return {p: float(np.sqrt(np.mean(np.concatenate([v for v in E[p].values()])**2))) for p in E}

if __name__ == "__main__" and "grid" in sys.argv:
    res = {}
    for W, phi in itertools.product([3, 5, 10, 20], [0.0, 0.5, 0.8, 0.9, 1.0]):
        res[(W, phi)] = rmse(errs(W, phi))
        print(W, phi, {k: round(v, 2) for k, v in res[(W, phi)].items()})

def final():
    from datetime import datetime, timedelta
    sys.path[:0] = [str(ROOT/'research'/'wind'), str(ROOT/'research'/'flow_co2')]
    import model_wind as MW, model_flow_co2 as MFC
    best = {}
    grid = list(itertools.product([10, 20, 30, 45, 60], [0.0, 0.8, 0.9, 0.95, 1.0]))
    for p in BASE:
        sc = {}
        for W, phi in grid:
            E = errs(W, phi)
            sc[(W, phi)] = float(np.sqrt(np.mean(np.concatenate(list(E[p].values()))**2)))
        best[p] = min(sc, key=sc.get); print(p, best[p], round(sc[best[p]], 2))
    EG.PARAMS.update(best)
    # per-minute errors by last-visible minute, plus comparisons
    E = {p: {n: [] for n in NOWS} for p in BASE + ['4_ETF']}
    C = {k: {p: {n: [] for n in NOWS} for p in BASE + ['4_ETF']} for k in ['research', 'baseline']}
    vols = {p: [] for p in BASE + ['4_ETF']}
    P = json.loads((ROOT/'params.json').read_text())
    base_d = datetime(2026, 11, 11)
    for d, r in days:
        s = settlement(r)
        g = (r['t'] >= 17*60) & (r['t'] < WIN)
        for p in BASE: vols[p].append(np.std(np.diff(r[p][g][-16:])))
        vols['4_ETF'].append(np.std(np.diff(sum(r[p] for p in BASE)[g][-16:])))
        for now in NOWS:
            m = r['t'] <= now - LAG
            f = {p: EG.forecast_settle(r['t'][m], r[p][m], *best[p]) for p in BASE}
            for p in BASE: E[p][now].append(f[p] - s[p])
            E['4_ETF'][now].append(sum(f.values()) - s['4_ETF'])
            # research models (datetime rows)
            rows = [{'t': base_d + timedelta(minutes=int(ti)), '1_WIND': a, '2_CO2': b, '3_FLOW': c}
                    for ti, a, b, c in zip(r['t'][m], r['1_WIND'][m], r['2_CO2'][m], r['3_FLOW'][m])]
            nd = base_d + timedelta(minutes=now)
            fr = {'1_WIND': MW.wind_fair(rows, nd)[0], '2_CO2': MFC.co2_fair(rows, nd)[0]}
            x = r['3_FLOW'][m]; tw = r['t'][m]; win = tw >= WIN
            fr['3_FLOW'] = ((x[win].sum() + x[-1]*(5-win.sum()))/5 if win.any()
                            else x[-5:].mean() + P['drift_per_hour']['3_FLOW']*max(WIN-now, 0)/60)
            fb = {}
            for p in BASE:
                xx = r[p][m]
                fb[p] = ((xx[win].sum() + xx[-1]*(5-win.sum()))/5 if win.any()
                         else xx[-5:].mean() + P['drift_per_hour'].get(p, 0)*max(WIN-now, 0)/60)
            for k, ff in [('research', fr), ('baseline', fb)]:
                for p in BASE: C[k][p][now].append(ff[p] - s[p])
                C[k]['4_ETF'][now].append(sum(ff.values()) - s['4_ETF'])
    rm = lambda L: float(np.sqrt(np.mean(np.array(L)**2)))
    print('now  ' + '  '.join(f'{p:>22s}' for p in BASE + ['4_ETF']) + '   (endgame/research/baseline)')
    for now in NOWS:
        print(f'{now//60}:{now%60:02d} ' + '  '.join(
            f'{rm(E[p][now]):6.1f}/{rm(C["research"][p][now]):6.1f}/{rm(C["baseline"][p][now]):6.1f}' for p in E))
    # sigma table keyed by last visible minute (= now - LAG); smooth with running max to be monotone
    sig = {}
    for p in E:
        tab = {now - LAG: max(rm(E[p][now]), 0.3) for now in NOWS}
        sig[p] = tab
    out = {'sigma': sig, 'hist_vol': {p: float(np.median(v)) for p, v in vols.items()},
           'params': {p: list(best[p]) for p in BASE}, 'lag_used': LAG}
    (ROOT/'research'/'endgame'/'sigma.json').write_text(json.dumps(out, indent=1))
    # 17:45 sensitivity
    dd = [float(np.mean(r[p][(r['t'] >= WIN+1) & (r['t'] <= CLOSE)]) - settlement(r)[p]) for d, r in days for p in ['1_WIND']]
    for p in BASE:
        dd = [float(np.mean(r[p][(r['t'] >= WIN+1) & (r['t'] <= CLOSE)]) - settlement(r)[p]) for d, r in days if (r['t'] == CLOSE).any()]
        print('17:41-45 minus 17:40-44', p, 'rms %.2f mean %.2f' % (rm(dd), np.mean(dd)))
if __name__ == "__main__" and "grid" not in sys.argv: final()
