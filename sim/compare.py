"""Compare baseline fair vs research models in the backtest. Run: .venv/bin/python -I sim/compare.py"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'research' / 'wind'), str(ROOT / 'research' / 'flow_co2')]
import model_flow_co2 as MFC
import model_wind as MW
import sim as S

TZ = ZoneInfo('Europe/Copenhagen')
BASE_DAY = datetime(2026, 11, 4, tzinfo=TZ)


def _dt(m):
    return BASE_DAY + timedelta(minutes=float(m))


def research_fair(rows, now, p):
    out = S.baseline_fair(rows, now, p)  # range floor + window lock fallback
    rr = [{'t': _dt(t), '1_WIND': w, '2_CO2': c, '3_FLOW': f}
          for t, w, c, f in zip(rows['t'], rows['1_WIND'], rows['2_CO2'], rows['3_FLOW'])]
    n = _dt(now)
    sm, adj = p['sigma_mult'], p['manual_adj']
    fw, sw = MW.wind_fair(rr, n)
    fc, sc = MFC.co2_fair(rr, n)
    ff, sf = MFC.flow_fair(rr, n)
    rf, rs, floor = MW.range_fair(rr, n)
    out.update({'1_WIND': (fw, sw * sm), '2_CO2': (fc, sc * sm), '3_FLOW': (ff + adj.get('3_FLOW', 0), sf * sm),
                '4_ETF': (fw + fc + ff, MFC.etf_sigma(sw, sc, sf, n) * sm),
                '5_WIND_RANGE': (rf, max(rs, 1) * sm), '_range_floor': floor})
    return out


research_fair.param_keys = ['sigma_mult', 'manual_adj']

if __name__ == '__main__':
    base = json.loads((ROOT / 'params.json').read_text())
    days = S.load_days()
    recent = [d for d in days if d[0] >= '2026-10-25']
    for label, fn, disabled in [('baseline', S.baseline_fair, []),
                                ('research', research_fair, []),
                                ('research no range', research_fair, ['5_WIND_RANGE'])]:
        for sm in [0.5, 1.0]:
            p = json.loads(json.dumps(base)); p['disabled_products'] = disabled; p['sigma_mult'] = sm
            df = S.run(recent, lambda: S.BaselineStrategy(p, fair_fn=fn), S.SimConfig())
            sm_ = S.summary(df)
            print(f'\n=== {label}  sigma_mult={sm}  (since 25 Oct, n={len(df)})')
            print(sm_[['mean', 'std', 'pct_losing']].T.to_string())


def hybrid_fair(rows, now, p):
    """research for WIND/CO2/range, baseline drift for FLOW; ETF = sum."""
    r, b = research_fair(rows, now, p), S.baseline_fair(rows, now, p)
    r['3_FLOW'] = b['3_FLOW']
    r['4_ETF'] = (r['1_WIND'][0] + r['2_CO2'][0] + r['3_FLOW'][0], r['4_ETF'][1])
    return r


hybrid_fair.param_keys = ['sigma_mult', 'manual_adj', 'drift_per_hour']


def run_hybrid():
    base = json.loads((ROOT / 'params.json').read_text())
    recent = [d for d in S.load_days() if d[0] >= '2026-10-25']
    for fd in [60, 90, 120]:
        p = json.loads(json.dumps(base)); p['disabled_products'] = ['5_WIND_RANGE']; p['sigma_mult'] = 1.0
        p['drift_per_hour']['3_FLOW'] = fd
        df = S.run(recent, lambda: S.BaselineStrategy(p, fair_fn=hybrid_fair), S.SimConfig())
        print(f'\n=== hybrid flow_drift={fd}'); print(S.summary(df)[['mean', 'std', 'pct_losing']].T.to_string())
