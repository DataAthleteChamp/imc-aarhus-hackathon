"""Replay backtester for bot2 'spread' market making.  READ-ONLY vs the exchange (GET /api/trade only).

Inputs : data/books.jsonl (bot2 book recorder; own volume subtracted -> market without us)
         GET /api/trade (cached+merged into research/mm/replay_trades_cache.json so history grows)
         data/predictions.csv (model fair/sigma per minute + Energinet 'actual'), data/live_rows.json
Fill   : aggressor sweep (same ts/aggressor/side) of volume V up to price P fills our resting order at
         our price px if px is at/better than P, after market volume at strictly better prices; at px we
         queue behind displayed market volume at placement ('cons', decays with trades/cancels) or
         are first in queue ('opt').  Quotes computed at book events, active after LATENCY s.
Usage  : .venv/bin/python -I research/mm/replay.py            # current live config, per product
         .venv/bin/python -I research/mm/replay.py --grid     # grid, top-10 + current
         flags: --no-fetch (use cache only) --throttle 1.0 --rank cons_mid|cons_en|opt_mid|opt_en
"""
import argparse, bisect, csv, itertools, json, math, os, sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
CACHE = Path(__file__).resolve().with_name('replay_trades_cache.json')
PRODUCTS = ['1_WIND', '2_CO2', '3_FLOW', '4_ETF', '5_WIND_RANGE']
LEGS = ['1_WIND', '2_CO2', '3_FLOW']
LATENCY = 0.2
# live values (bot2.DEFAULTS + params.json at 16:10)
MIN_HALF = {'1_WIND': 2, '2_CO2': 4, '3_FLOW': 5, '4_ETF': 6, '5_WIND_RANGE': 2}
NAV_MAX_SPREAD = {'1_WIND': 25, '2_CO2': 50, '3_FLOW': 60}
LIM = {p: 98 for p in PRODUCTS} | {'4_ETF': 40}
ETF_NAV_SIGMA = 12
LIVE = dict(mh_mult=1.0, mm_size=5, spread_skew=1.0, style='penny', vol_k=0.0, pull=False, alpha_k=0.0)


# ------------------------------------------------------------------ data
def fetch_trades(no_fetch):
    cache = {}
    if CACHE.exists():
        cache = {t['id']: t for t in json.loads(CACHE.read_text())}
    me = None
    if not no_fetch:
        sys.path.insert(0, str(ROOT))
        import requests
        from bot import load_env
        load_env()
        me = os.environ['CMI_USER']
        U = 'https://gamma.cmi-exch.com'
        r = requests.post(U + '/api/user/authenticate', json={'username': me, 'password': os.environ['CMI_PASS']})
        tr = requests.get(U + '/api/trade', headers={'Authorization': r.headers['Authorization']}).json()
        for t in tr:
            cache[t['id']] = t
        CACHE.write_text(json.dumps(list(cache.values())))
    else:
        envf = ROOT / '.env'
        for line in envf.read_text().splitlines() if envf.exists() else []:
            if line.startswith('CMI_USER='):
                me = line.split('=', 1)[1].strip()
    return list(cache.values()), me


def parse_ts(s):
    s = s.rstrip('Z')
    if '.' in s:
        a, b = s.split('.')
        s = a + '.' + b[:6]
    return datetime.fromisoformat(s + '+00:00').timestamp()


def load_books():
    ev = []
    for line in (DATA / 'books.jsonl').open():
        try:
            d = json.loads(line)
        except Exception:
            continue
        b = [(x[0], x[1] - x[2]) for x in d['b'] if x[1] - x[2] > 0]
        a = [(x[0], x[1] - x[2]) for x in d['a'] if x[1] - x[2] > 0]
        ev.append((d['ts'], d['p'], b, a))
    ev.sort(key=lambda e: e[0])
    return ev


def load_preds():
    """per product sorted [(epoch, fair, sigma, actual)] from predictions.csv (ts is local CET wall clock)."""
    out = defaultdict(list)
    f = DATA / 'predictions.csv'
    if not f.exists():
        return out
    day = datetime.now().astimezone()
    for r in csv.DictReader(f.open()):
        try:
            h, m, s = map(int, r['ts'].split(':'))
            t = day.replace(hour=h, minute=m, second=s, microsecond=0).timestamp()
            out[r['product']].append((t, float(r['fair']), float(r['sigma']), float(r['actual'])))
        except Exception:
            pass
    for v in out.values():
        v.sort()
    return out


def energinet_marks(preds):
    m = {p: v[-1][3] for p, v in preds.items() if v}
    try:
        rows = json.loads((DATA / 'live_rows.json').read_text())['rows']
        for p in LEGS:
            m[p] = rows[-1][p]
        m.setdefault('4_ETF', sum(rows[-1][p] for p in LEGS))
    except Exception:
        pass
    return m


# ------------------------------------------------------------ preprocess
def build_timeline(books, trades, me, preds):
    """per product: list of ('B', ts, bids, asks, ctx) and ('T', ts, side, maxP, vol, mine_passive)."""
    tl = defaultdict(list)
    last = {}
    mids = defaultdict(deque)
    for ts, p, b, a in books:
        last[p] = (b, a)
        if not b or not a:
            tl[p].append(('B', ts, b, a, None))
            continue
        mid = (b[0][0] + a[0][0]) / 2
        dq = mids[p]
        dq.append((ts, mid))
        while dq and dq[0][0] < ts - 60:
            dq.popleft()
        xs = [x for _, x in dq]
        mu = sum(xs) / len(xs)
        std = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))
        ctx = {'mid': mid, 'std': std, 'sec': datetime.fromtimestamp(ts).second}
        pv = preds.get(p, [])
        i = bisect.bisect_right(pv, (ts, 1e18)) - 1
        if i >= 0:
            ctx['fair'], ctx['sig'] = pv[i][1], pv[i][2]
        if p == '4_ETF':     # iNAV from leg books (live: etf fair = iNAV before etf_model_from 17:30)
            nav, half = 0.0, 0.0
            for leg in LEGS:
                lb = last.get(leg)
                if not lb or not lb[0] or not lb[1] or lb[1][0][0] - lb[0][0][0] > NAV_MAX_SPREAD[leg]:
                    nav = None
                    break
                nav += (lb[0][0][0] + lb[1][0][0]) / 2
                half += (lb[1][0][0] - lb[0][0][0]) / 2
            if nav is None:
                ctx['fair'], ctx['sig'] = None, 1e9
            else:
                ctx['fair'], ctx['sig'] = nav, max(half, ETF_NAV_SIGMA)
        tl[p].append(('B', ts, b, a, ctx))
    t0 = books[0][0] if books else 0
    sweeps = defaultdict(lambda: [0, None, 0, 0])
    for t in trades:
        if t['aggressor'] == me:
            continue                      # our own takes: not part of passive flow
        ts = parse_ts(t['timestamp'])
        if ts < t0:
            continue
        side = 'BUY' if t['aggressor'] == t['buyer'] else 'SELL'
        k = (round(ts, 3), t['product'], t['aggressor'], side)
        s = sweeps[k]
        s[0] += t['volume']
        s[1] = t['price'] if s[1] is None else (max(s[1], t['price']) if side == 'BUY' else min(s[1], t['price']))
        if me in (t['buyer'], t['seller']):
            s[2] += t['volume']
            s[3] += t['volume'] * t['price'] * (1 if t['buyer'] == me else -1)
    for (ts, p, _, side), (v, px, mv, mc) in sweeps.items():
        tl[p].append(('T', ts, side, px, v, (mv, mc)))
    for p in tl:
        tl[p].sort(key=lambda e: (e[1], e[0] == 'T'))
    return tl


# ---------------------------------------------------------------- quotes
def quotes(prod, bids, asks, pos, prm, ctx, tick=1):
    """Pure-function version of Bot2._spread_quotes (+ style / vol-widen / release-pull extensions)."""
    if not bids or not asks or ctx is None:
        return []
    if prm['pull'] and ctx['sec'] < 30:          # 60..90s after a minute's start = first 30s of next
        return []
    fair, sig = ctx.get('fair'), ctx.get('sig', 1e9)
    if prod == '4_ETF' and fair is None:
        return []
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    center = fair if prod == '4_ETF' and sig < 50 else mid
    mh = MIN_HALF[prod] * prm['mh_mult'] + prm['vol_k'] * ctx['std']
    lim = LIM[prod]
    target = 0.0
    if fair is not None and prm['alpha_k']:
        target = max(-lim, min(lim, lim * prm['alpha_k'] * (fair - center) / max(sig, 1)))
    dev = (pos - target) / lim
    c = center - prm['spread_skew'] * max(mh, (ba - bb) / 2) * dev
    imp = tick if prm['style'] in ('penny', 'ladder2') else 0
    b1 = min(bb + imp, math.floor(c - mh), ba - tick)
    a1 = max(ba - imp, math.ceil(c + mh), bb + tick)
    if fair is not None and sig < 1e8:
        b1 = min(b1, math.floor(fair + 0.25 * sig))
        a1 = max(a1, math.ceil(fair - 0.25 * sig))
    size = prm['mm_size']
    shr = max(1, int(round(size * max(0.0, 1 - abs(dev)))))
    bsz = size if pos < target else shr
    asz = size if pos > target else shr
    out = []
    if pos + bsz <= lim and b1 > 0:
        out.append(('BUY', int(b1), int(bsz)))
    if pos - asz >= -lim:
        out.append(('SELL', int(a1), int(asz)))
    if prm['style'] == 'ladder2':
        step = max(tick, math.ceil(mh))
        if pos + 2 * bsz <= lim and b1 - step > 0:
            out.append(('BUY', int(b1 - step), int(bsz)))
        if pos - 2 * asz >= -lim:
            out.append(('SELL', int(a1 + step), int(asz)))
    return out


# -------------------------------------------------------------- simulate
def simulate(prod, tl, prm, queue, throttle, marks):
    pos, cash, fills, vol, edge = 0, 0.0, 0, 0, 0.0
    cur = []                 # [side, px, size, ahead]
    pend = None              # (t_active, desired list)
    last_q = -1e18
    book = ([], [])
    mid = None

    def lvl_vol(side, px):
        lv = book[0] if side == 'BUY' else book[1]
        return next((v for p, v in lv if p == px), 0)

    def activate():
        nonlocal cur
        new = []
        for s, px, v in pend[1]:
            m = next((o for o in cur if o[0] == s and o[1] == px and v / 2 <= o[2] <= v), None)
            if m:
                new.append(m)
                cur.remove(m)
            else:
                new.append([s, px, v, lvl_vol(s, px) if queue == 'cons' else 0])
        cur = new

    for e in tl:
        ts = e[1]
        if pend and pend[0] <= ts:
            activate()
            pend = None
        if e[0] == 'B':
            book = (e[2], e[3])
            if e[4] is not None:
                mid = e[4]['mid']
            if queue == 'cons':
                for o in cur:
                    o[3] = min(o[3], lvl_vol(o[0], o[1]))
            if ts - last_q >= throttle:
                last_q = ts
                pend = (ts + LATENCY, quotes(prod, e[2], e[3], pos, prm, e[4]))
        else:
            _, _, side, P, V, _ = e
            ours = 'SELL' if side == 'BUY' else 'BUY'      # aggressor buy hits our asks
            mkt = book[1] if side == 'BUY' else book[0]
            better = (lambda a, b: a < b) if side == 'BUY' else (lambda a, b: a > b)
            for o in sorted([o for o in cur if o[0] == ours], key=lambda o: o[1], reverse=(ours == 'BUY')):
                px = o[1]
                if better(P, px):                   # trade price not reaching our price
                    continue
                ahead_mkt = sum(v for p, v in mkt if better(p, px))
                rem = V - ahead_mkt
                if rem <= 0:
                    break
                q = min(o[3], rem)
                o[3] -= q
                rem -= q
                f = min(o[2], rem)
                if f <= 0:
                    continue
                o[2] -= f
                V -= f
                sg = 1 if ours == 'BUY' else -1
                pos += sg * f
                cash -= sg * f * px
                fills += 1
                vol += f
                if mid is not None:
                    edge += sg * f * (mid - px)
            cur = [o for o in cur if o[2] > 0]
    res = {'fills': fills, 'vol': vol, 'pos': pos, 'spread': edge}
    res['tot_mid'] = cash + pos * (mid or 0)
    res['tot_en'] = cash + pos * marks.get(prod, mid or 0)
    res['inv_mid'] = res['tot_mid'] - edge
    return res


def actual(prod, tl, marks, mid_end):
    pos = cash = n = 0
    for e in tl:
        if e[0] == 'T' and e[5][0]:
            mv, mc = e[5]
            n += 1
            cash -= mc
            pos += mv * (1 if mc > 0 else -1)
    return n, pos, cash + pos * (mid_end or 0), cash + pos * marks.get(prod, mid_end or 0)


def run_cfg(tls, prm, queue, throttle, marks):
    return {p: simulate(p, tls[p], prm, queue, throttle, marks) for p in PRODUCTS if p in tls}


def summ(r, k):
    return sum(x[k] for x in r.values())


def fmt(prm):
    return (f"mh x{prm['mh_mult']:<3} size {prm['mm_size']:<2} skew {prm['spread_skew']:<3} {prm['style']:<7} "
            f"volk {prm['vol_k']:<3} pull {'Y' if prm['pull'] else 'N'}")


def detail(tls, prm, throttle, marks):
    for q in ('cons', 'opt'):
        r = run_cfg(tls, prm, q, throttle, marks)
        print(f'  [{q}] {"product":13s} {"fills":>5} {"vol":>5} {"pos":>5} {"spread":>8} {"inv@mid":>8} {"tot@mid":>8} {"tot@En":>8}')
        for p, x in r.items():
            print(f'  [{q}] {p:13s} {x["fills"]:>5} {x["vol"]:>5} {x["pos"]:>5} {x["spread"]:>8.0f} '
                  f'{x["inv_mid"]:>8.0f} {x["tot_mid"]:>8.0f} {x["tot_en"]:>8.0f}')
        print(f'  [{q}] {"TOTAL":13s} {summ(r,"fills"):>5} {summ(r,"vol"):>5} {"":>5} {summ(r,"spread"):>8.0f} '
              f'{summ(r,"inv_mid"):>8.0f} {summ(r,"tot_mid"):>8.0f} {summ(r,"tot_en"):>8.0f}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', action='store_true')
    ap.add_argument('--no-fetch', action='store_true')
    ap.add_argument('--throttle', type=float, default=1.0)   # live quote_throttle
    ap.add_argument('--rank', default='cons_mid', choices=['cons_mid', 'cons_en', 'opt_mid', 'opt_en'])
    ap.add_argument('--top', type=int, default=10)
    a = ap.parse_args()
    trades, me = fetch_trades(a.no_fetch)
    books = load_books()
    preds = load_preds()
    marks = energinet_marks(preds)
    tls = build_timeline(books, trades, me, preds)
    t0, t1 = books[0][0], books[-1][0]
    ntr = sum(1 for p in tls for e in tls[p] if e[0] == 'T')
    print(f'window {datetime.fromtimestamp(t0):%H:%M:%S}-{datetime.fromtimestamp(t1):%H:%M:%S} '
          f'({(t1-t0)/60:.1f} min)  book events {len(books)}  market sweeps in window {ntr}  '
          f'Energinet marks {", ".join(f"{k[:6]}={v:.0f}" for k, v in sorted(marks.items()))}')

    print('\nCURRENT LIVE CONFIG:', fmt(LIVE))
    detail(tls, LIVE, a.throttle, marks)
    print('  ACTUAL our passive fills in window (pure MM part, from /api/trade):')
    for p in PRODUCTS:
        if p in tls:
            mids = [e[4]['mid'] for e in tls[p] if e[0] == 'B' and e[4]]
            n, pos, tm, te = actual(p, tls[p], marks, mids[-1] if mids else None)
            print(f'   {p:13s} sweeps {n:>3} pos {pos:>4} tot@mid {tm:>8.0f} tot@En {te:>8.0f}')

    if not a.grid:
        return
    grid = [dict(mh_mult=m, mm_size=s, spread_skew=k, style=st, vol_k=v, pull=pl, alpha_k=0.0)
            for m, s, k, st, v, pl in itertools.product([0.5, 1, 2, 3], [1, 3, 5, 10], [0.5, 1, 2],
                                                         ['penny', 'join', 'ladder2'], [0, 0.5, 1], [False, True])]
    rows = []
    for prm in grid:
        rc = run_cfg(tls, prm, 'cons', a.throttle, marks)
        ro = run_cfg(tls, prm, 'opt', a.throttle, marks)
        rows.append((prm, {'cons_mid': summ(rc, 'tot_mid'), 'cons_en': summ(rc, 'tot_en'),
                           'opt_mid': summ(ro, 'tot_mid'), 'opt_en': summ(ro, 'tot_en'),
                           'cf': summ(rc, 'fills'), 'of': summ(ro, 'fills'), 'csp': summ(rc, 'spread')}, rc))
    rows.sort(key=lambda r: (-r[1][a.rank], -r[1]["opt_mid"], -r[1]["cf"]))
    hdr = f'{"rank":>4} {"config":60s} {"consMid":>8} {"consEn":>8} {"optMid":>8} {"optEn":>8} {"cFill":>5} {"oFill":>5} {"cSprd":>7}'

    def line(i, prm, s):
        return (f'{i:>4} {fmt(prm):60s} {s["cons_mid"]:>8.0f} {s["cons_en"]:>8.0f} {s["opt_mid"]:>8.0f} '
                f'{s["opt_en"]:>8.0f} {s["cf"]:>5} {s["of"]:>5} {s["csp"]:>7.0f}')
    print(f'\nGRID ({len(grid)} configs) ranked by {a.rank}:\n' + hdr)
    for i, (prm, s, _) in enumerate(rows[:a.top], 1):
        print(line(i, prm, s))
    li = next(i for i, r in enumerate(rows, 1) if all(r[0][k] == LIVE[k] for k in LIVE))
    print(line(li, rows[li - 1][0], rows[li - 1][1]) + '   <- CURRENT LIVE')
    # per-product best (products are independent; can set different params per product)
    print('\nper-product best (cons_mid):')
    for p in PRODUCTS:
        if p in tls:
            b = max(rows, key=lambda r: r[2][p]['tot_mid'])
            lv = rows[li - 1][2][p]['tot_mid']
            print(f'   {p:13s} {fmt(b[0])}  {b[2][p]["tot_mid"]:>7.0f}  (live {lv:.0f})')
    print('\nBEST CONFIG detail:', fmt(rows[0][0]))
    detail(tls, rows[0][0], a.throttle, marks)


if __name__ == '__main__':
    main()
