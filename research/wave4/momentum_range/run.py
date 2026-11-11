import json, sys, numpy as np
from datetime import datetime, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'research/wind'))
import model_wind as MW
recs = json.loads((ROOT / 'data/hist.json').read_text())['records']
days = {}
for x in recs:
    if None in x.values(): continue
    t = datetime.fromisoformat(x['Minutes1DK']).replace(tzinfo=None)
    days.setdefault(t.date(), {})[t] = {'1_WIND': (x['OnshoreWindPower']+x['OffshoreWindPower'])/3, '3_FLOW': 1000+x['Exchange_Sum']/3}
D = sorted(d for d, v in days.items() if datetime.combine(d, datetime.min.time()).replace(hour=17, minute=45) in v and len(v) > 1000)[-14:]
print('days', D[0], D[-1], len(D))
HALF = {'1_WIND': 3, '3_FLOW': 6}; TYP = {'1_WIND': 8, '3_FLOW': 18}
def at(d, h, m): return datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)
print('\n== Momentum: entry 16:48..17:44-h, signal v[T-1]-v[T-6], mid=v[T-lag], size5 cap20')
for p in HALF:
  for lag in (1, 2):
    for c in (0.5, 1, 1.5):
      for H in (5, 10):
        pn = []; nt = 0
        for d in D:
            v = days[d]; tot = 0; opens = []
            T = at(d, 16, 48)
            while T + timedelta(minutes=H) <= at(d, 17, 44):
                opens = [o for o in opens if o > T]
                g = lambda k: (v.get(T + timedelta(minutes=k)) or {}).get(p)
                if None not in (g(-1), g(-6), g(-lag), g(H-lag)):
                    s = g(-1) - g(-6)
                    if abs(s) > c*TYP[p] and len(opens)*5 < 20:
                        dr = np.sign(s)
                        tot += 5*(dr*(g(H-lag)-g(-lag)) - 2*HALF[p]); nt += 1
                        opens.append(T + timedelta(minutes=H))
                T += timedelta(minutes=1)
            pn.append(tot)
        pn = np.array(pn)
        print(f'{p} lag{lag} c{c} H{H}: mean {pn.mean():7.1f} sd {pn.std():7.1f} pos {np.mean(pn>0)*100:4.0f}% trades/day {nt/len(D):.1f}')
print('\n== Range')
for (h, m) in [(16, 43), (16, 48), (17, 0), (17, 20), (17, 30)]:
    E = []; Fl = []; RF = []; SIG = []
    for d in D:
        v = days[d]
        sess = [v[t]['1_WIND'] for t in sorted(v) if at(d, 15, 0) <= t <= at(d, 17, 45)]
        final = max(sess) - min(sess)
        now = at(d, h, m)
        rows = [{'t': t, '1_WIND': v[t]['1_WIND']} for t in sorted(v) if t <= now - timedelta(minutes=1)]
        rf, sg, fl = MW.range_fair(rows, now)
        E.append(final); Fl.append(fl); RF.append(rf); SIG.append(sg)
    E, Fl, RF = map(np.array, (E, Fl, RF))
    ext = E - Fl
    print(f'{h}:{m:02d} floor bias {np.mean(Fl-E):6.1f} rmse {np.sqrt(np.mean((Fl-E)**2)):6.1f} | range_fair bias {np.mean(RF-E):6.1f} rmse {np.sqrt(np.mean((RF-E)**2)):6.1f} | ext(final-floor) mean {ext.mean():5.1f} med {np.median(ext):5.1f} p30 {np.percentile(ext,30):5.1f} | rf-floor mean {np.mean(RF-Fl):5.1f}')
    print('   ext sorted', np.round(np.sort(ext)).astype(int).tolist())
    for k in (0, 10, 20, 40):
        print(f'   price=floor+{k}: E[final-price] {np.mean(ext-k):6.1f}  P(final>=price) {np.mean(ext>=k)*100:4.0f}%')
    pr = RF - Fl
    for frac in (0.5, 0.75):
        print(f'   price=floor+{frac}*(rf-floor): E[final-price] {np.mean(ext-frac*pr):6.1f} P>= {np.mean(ext>=frac*pr)*100:3.0f}%')
