"""bot2: event-driven taker + diff-based market maker + ETF arb, on top of fair.compute_fair
and execution.OrderManager.

  - TAKE (every SSE book update, 0.5s cooldown/product): sweep levels beyond fair +/- take_edge
  - MM: 2-level ladder per side; L1 pennies best (excl. our own volume) but never closer than
        quote_edge to (skewed) fair; L2 = L1 -/+ ladder_step*sigma. Inventory skew + size shrink.
        Diff-based set_quotes (queue priority kept), 1/s per product on book updates + every 5s.
  - New Energinet minute with |dfair| > 0.3 sigma: pull stale side, requote immediately.
  - ETF arb: ETF bid > sum(component asks)+arb_edge (or reverse) -> 4 parallel takes, equal vol.
  - WIND_RANGE: never sells below range_floor + min_take_edge.
Run:  DRY=1 .venv/bin/python -u bot2.py   (dry: prints, sends nothing)
      .venv/bin/python -u bot2.py >> bot2.log 2>&1
"""
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import fair as F
from base_bot import BaseBot
from execution import OrderManager
from fair import TZ, compute_fair

URL = os.environ.get('CMI_URL', 'https://gamma.cmi-exch.com')
DRY = os.environ.get('DRY') == '1'
PRODUCTS = ['1_WIND', '2_CO2', '3_FLOW', '4_ETF', '5_WIND_RANGE']
LEGS = ['1_WIND', '2_CO2', '3_FLOW']
DEFAULTS = {'mm_enabled': True, 'quote_edge_k': 0.5, 'ladder_step': 0.25, 'skew_k': 0.5,
            'arb_edge': 6, 'arb_enabled': True, 'mm_size': 5, 'take_cooldown': 0.5,
            'mm_mode': 'spread', 'alpha_k': 0.5, 'spread_skew': 1.0,
            'mm_min_half': {'1_WIND': 2, '2_CO2': 4, '3_FLOW': 5, '4_ETF': 6, '5_WIND_RANGE': 2},
            'etf_max_pos': 40, 'etf_model_from': '17:30', 'etf_nav_sigma': 12,
            'nav_max_spread': {'1_WIND': 25, '2_CO2': 50, '3_FLOW': 60},
            'quote_throttle': 1.0, 'jump_k': 0.3, 'anchor_k': 0.1}


def ts():
    return datetime.now(TZ).strftime('%H:%M:%S')


_PL = threading.Lock()


def log(*a):
    line = ' '.join([ts(), *map(str, a)]) + '\n'
    with _PL:
        sys.stdout.write(line)
        sys.stdout.flush()


def load_env():
    f = Path(__file__).with_name('.env')
    if f.exists():
        for line in f.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


# Share Energinet data with any other process (bot.py writes data/live_rows.json): avoids 429s.
_orig_fetch = F._fetch_rows
_LIVE = Path(F.__file__).with_name('data') / 'live_rows.json'


def _shared_fetch(now):
    try:
        d = json.loads(_LIVE.read_text())
        age = (datetime.now(TZ) - datetime.fromisoformat(d['fetched_at'])).total_seconds()
        if age < 25:
            return [{**r, 't': datetime.fromisoformat(r['t'])} for r in d['rows']]
    except Exception:
        pass
    return _orig_fetch(now)


# Disabled: when bot2 runs alone, fair.fetch_rows rewrites live_rows.json with a fresh
# fetched_at, so this would feed stale rows back forever. Only one bot runs at a time.
# F._fetch_rows = _shared_fetch


class Bot2(BaseBot):
    def __init__(self, user, pw):
        super().__init__(URL, user, pw)
        self.om = OrderManager.login(URL, user, pw, verbose=True)
        self.model = None
        self.books = {}
        self.last_take = {}
        self.last_quote = {}
        self.last_arb = 0.0
        self.busy = {p: threading.Lock() for p in PRODUCTS + ['ARB']}
        self.ex = ThreadPoolExecutor(max_workers=8, thread_name_prefix='b2')
        self.last_desired = {}
        self.anchor = {}
        self.n_takes = 0

    def _register_bot(self):
        pass  # never auto-register

    # ---------------------------------------------------------------- params
    def p(self):
        return {**DEFAULTS, **self.model['params']}

    def enabled(self, prod):
        p = self.p()
        return p['trading_enabled'] and prod not in p['disabled_products']

    def take_edge(self, prod):
        p = self.p()
        return max(p['min_take_edge'][prod], p['take_k'] * self.fair_sigma(prod)[1])

    # ---- ETF priced like an industry ETF market maker: off the LIVE component prices (iNAV),
    # not off our own view (our view is already expressed in the components; doubling it in ETF
    # is what lost money in the practice round). Model fair takes over in the endgame.
    def etf_nav(self):
        p = self.p()
        nav, half = 0.0, 0.0
        for leg in LEGS:
            ob = self.books.get(leg)
            if ob is None or not ob.buy_orders or not ob.sell_orders:
                return None
            b, a = ob.buy_orders[0].price, ob.sell_orders[0].price
            if a - b > p['nav_max_spread'][leg]:
                return None
            nav += (a + b) / 2
            half += (a - b) / 2
        return nav, half

    def fair_sigma(self, prod):
        f, s = self.model['fair'][prod], self.model['sigma'][prod]
        if prod != '4_ETF':
            return f, s
        p = self.p()
        hm = datetime.now(TZ).strftime('%H:%M')
        if hm >= p['etf_model_from']:
            return f, s
        nav = self.etf_nav()
        if nav is None:
            return f, max(s, 1e9)  # no reliable iNAV -> never take/quote ETF on model alone
        return nav[0], max(nav[1], p['etf_nav_sigma'])

    def lim(self, prod):
        p = self.p()
        return p['etf_max_pos'] if prod == '4_ETF' else p['max_pos']

    def sell_floor(self, prod):
        if prod == '5_WIND_RANGE':
            return self.model['range_floor'] + self.p()['min_take_edge'][prod]
        return -1e18

    # ----------------------------------------------------------- book events
    def on_orderbook(self, ob):
        self.books[ob.product] = ob
        try:  # record top-5 book for MM replay backtests (data/books.jsonl)
            if not hasattr(self, '_rec'):
                self._rec = (Path(__file__).with_name('data') / 'books.jsonl').open('a', buffering=1)
            self._rec.write(json.dumps({'ts': time.time(), 'p': ob.product,
                'b': [[o.price, o.volume, o.own_volume] for o in ob.buy_orders[:5]],
                'a': [[o.price, o.volume, o.own_volume] for o in ob.sell_orders[:5]]}) + '\n')
        except Exception:
            pass
        if self.model is None:
            return
        prod = ob.product
        self._submit(prod, self._on_book, prod)
        if prod in LEGS + ['4_ETF'] and self.p()['arb_enabled']:
            self._submit('ARB', self._arb)

    def _submit(self, key, fn, *a):
        lk = self.busy[key]
        if not lk.acquire(blocking=False):
            return  # previous handler for this product still in flight: skip (state is re-read next time)

        def run():
            try:
                fn(*a)
            except Exception as e:
                log(f'handler error {key}: {e!r}')
            finally:
                lk.release()
        self.ex.submit(run)

    def on_trades(self, trades):
        self.om.on_trades(trades)
        for t in trades:
            if self.username in (t.buyer, t.seller):
                side = 'BOUGHT' if t.buyer == self.username else 'SOLD'
                cp = t.seller if side == 'BOUGHT' else t.buyer
                log(f'FILL {side} {t.volume:g} {t.product} @ {t.price:g} vs {cp}')

    def _on_book(self, prod):
        if not self.enabled(prod):
            return
        now = time.time()
        if now - self.last_take.get(prod, 0) >= self.p()['take_cooldown']:
            if self._take(prod):
                self.last_take[prod] = now
                self.last_quote[prod] = 0  # force requote after a take
        if now - self.last_quote.get(prod, 0) >= self.p()['quote_throttle']:
            self.last_quote[prod] = now
            self.requote(prod)

    @staticmethod
    def _levels(ob):
        bids = [(o.price, o.volume - o.own_volume) for o in ob.buy_orders if o.volume - o.own_volume > 0]
        asks = [(o.price, o.volume - o.own_volume) for o in ob.sell_orders if o.volume - o.own_volume > 0]
        return bids, asks

    def _do_take(self, prod, side, px, vol, tag):
        px, vol = int(round(px)), int(vol)
        if vol <= 0:
            return 0
        if DRY:
            log(f'DRY {tag} {side} {vol} {prod} @ {px}')
            return 0
        filled = self.om.take(prod, side, px, vol)
        self.n_takes += 1
        log(f'{tag} {side} {vol} {prod} @ {px} filled {filled}')
        return filled

    def _take(self, prod):
        ob = self.books.get(prod)
        if ob is None:
            return False
        p, fair, edge = self.p(), self.fair_sigma(prod)[0], self.take_edge(prod)
        pos, lim = self.om.position(prod), self.lim(prod)
        bids, asks = self._levels(ob)
        if asks and asks[0][0] < fair - edge and pos < lim:
            vol, px = 0, asks[0][0]
            for pr, v in asks:
                if pr >= fair - edge:
                    break
                vol, px = vol + v, pr
            vol = min(vol, p['take_clip'], lim - pos)
            if vol > 0:
                self._do_take(prod, 'BUY', px, vol, f'TAKE(fair {fair:.1f} edge {edge:.1f})')
                return True
        if bids and bids[0][0] > max(fair + edge, self.sell_floor(prod)) and pos > -lim:
            vol, px = 0, bids[0][0]
            for pr, v in bids:
                if pr <= fair + edge or pr <= self.sell_floor(prod):
                    break
                vol, px = vol + v, pr
            vol = min(vol, p['take_clip'], lim + pos)
            if vol > 0:
                self._do_take(prod, 'SELL', px, vol, f'TAKE(fair {fair:.1f} edge {edge:.1f})')
                return True
        return False

    # -------------------------------------------------------------- ETF arb
    def _arb(self):
        p = self.p()
        if not p['trading_enabled'] or time.time() - self.last_arb < p['take_cooldown']:
            return
        if any(x in p['disabled_products'] for x in LEGS + ['4_ETF']):
            return
        lv = {}
        for prod in LEGS + ['4_ETF']:
            ob = self.books.get(prod)
            if ob is None:
                return
            lv[prod] = self._levels(ob)
        lim = p['max_pos']
        pos = {k: self.om.position(k) for k in lv}
        for etf_side, leg_side in (('SELL', 'BUY'), ('BUY', 'SELL')):
            if etf_side == 'SELL':   # ETF rich: sell ETF bid, buy legs at asks
                e, legs = lv['4_ETF'][0], [lv[k][1] for k in LEGS]
                room = [lim + pos['4_ETF']] + [lim - pos[k] for k in LEGS]
            else:                    # ETF cheap: buy ETF ask, sell legs at bids
                e, legs = lv['4_ETF'][1], [lv[k][0] for k in LEGS]
                room = [lim - pos['4_ETF']] + [lim + pos[k] for k in LEGS]
            if not e or not all(legs):
                continue
            basket = sum(l[0][0] for l in legs)
            gain = (e[0][0] - basket) if etf_side == 'SELL' else (basket - e[0][0])
            if gain <= p['arb_edge']:
                continue
            vol = int(min([e[0][1]] + [l[0][1] for l in legs] + room + [p['take_clip']]))
            if vol <= 0:
                continue
            self.last_arb = time.time()
            log(f'ARB {etf_side} ETF@{e[0][0]:.0f} vs basket {basket:.0f} gain {gain:.0f}/u vol {vol}')
            orders = [('4_ETF', etf_side, e[0][0])] + [(k, leg_side, l[0][0]) for k, l in zip(LEGS, legs)]
            futs = [self.om.pool.submit(self._do_take, k, s, px, vol, 'ARB-LEG') for k, s, px in orders]
            fills = [f.result() for f in futs]
            if not DRY and len(set(fills)) > 1:
                log(f'ARB legged unevenly fills={fills} (fair-based MM/takes will work it off)')
            return

    # ------------------------------------------------------------ quoting
    def desired_quotes(self, prod):
        p = self.p()
        ob = self.books.get(prod)
        if ob is None or not p['mm_enabled'] or not self.enabled(prod):
            return []
        fair, sig = self.fair_sigma(prod)
        if sig > 1e8:
            return []
        # hysteresis: model fair jitters each recompute; only move quotes when it moves > anchor_k*sigma
        a = self.anchor.get(prod)
        if a is None or abs(fair - a[0]) > p['anchor_k'] * sig or abs(sig - a[1]) > 0.1 * a[1]:
            self.anchor[prod] = a = (fair, sig)
        fair, sig = a
        tick = ob.tick_size or 1
        pos, lim = self.om.position(prod), self.lim(prod)
        edge = max(p['min_take_edge'][prod], p['quote_edge_k'] * sig)
        fs = fair - p['skew_k'] * sig * pos / lim       # long -> both sides lower
        step = max(tick, p['ladder_step'] * sig)
        bids, asks = self._levels(ob)
        size = p['mm_size']
        shrink = max(0.0, 1 - abs(pos) / lim)
        bsz = size if pos < 0 else int(round(size * shrink))   # side that adds inventory shrinks
        asz = size if pos > 0 else int(round(size * shrink))

        def rt(x, down):
            n = x / tick
            return (int(n) if down else -int(-n)) * tick

        if p.get('mm_mode') == 'spread':
            return self._spread_quotes(prod, ob, fair, sig, pos, lim, tick, rt)
        out = []
        # bids
        b1 = rt(fs - edge, True)
        if bids:
            b1 = min(b1, bids[0][0] + tick)
        if asks:
            b1 = min(b1, asks[0][0] - tick)
        room = lim - pos
        for px in (b1, b1 - rt(step, False)):
            v = min(bsz, room)
            if v > 0 and px > 0:
                out.append(('BUY', int(round(px)), int(v)))
                room -= v
        # asks
        a1 = rt(fs + edge, False)
        if asks:
            a1 = max(a1, asks[0][0] - tick)
        if bids:
            a1 = max(a1, bids[0][0] + tick)
        a1 = max(a1, rt(self.sell_floor(prod), False))
        room = lim + pos
        for px in (a1, a1 + rt(step, False)):
            v = min(asz, room)
            if v > 0:
                out.append(('SELL', int(round(px)), int(v)))
                room -= v
        # keep partially-filled resting orders (queue priority) unless < half size
        live = self.om.orders(prod)
        res = []
        for s, px, v in out:
            m = next((o for o in live if o.side == s and o.price == px and v / 2 <= o.volume <= v), None)
            res.append((s, px, m.volume if m else v))
        return res

    def _spread_quotes(self, prod, ob, fair, sig, pos, lim, tick, rt):
        """Industry two-layer MM: long-term model sets a TARGET inventory; quotes sit tight around
        the short-term reference (book mid / iNAV) to earn the spread; skew pulls pos toward target."""
        p = self.p()
        bids, asks = self._levels(ob)
        if not bids or not asks:
            return []
        bb, ba = bids[0][0], asks[0][0]
        mid = (bb + ba) / 2
        center = fair if prod == '4_ETF' and sig < 50 else mid     # ETF: iNAV-based fair
        mh = p['mm_min_half'][prod]
        target = max(-lim, min(lim, lim * p['alpha_k'] * (fair - center) / max(sig, 1)))
        dev = (pos - target) / lim                       # >0: too long vs target -> lean to sell
        c = center - p['spread_skew'] * max(mh, (ba - bb) / 2) * dev
        b1 = min(bb + tick, rt(c - mh, True), ba - tick)
        a1 = max(ba - tick, rt(c + mh, False), bb + tick)
        b1 = min(b1, rt(fair + 0.25 * sig, True))          # never pay well above long-term fair
        a1 = max(a1, rt(fair - 0.25 * sig, False), rt(self.sell_floor(prod), False))
        size = p['mm_size']
        bsz = size if pos < target else max(1, int(round(size * max(0.0, 1 - abs(dev)))))
        asz = size if pos > target else max(1, int(round(size * max(0.0, 1 - abs(dev)))))
        out = []
        if pos + bsz <= lim and b1 > 0:
            out.append(('BUY', int(b1), int(bsz)))
        if pos - asz >= -lim:
            out.append(('SELL', int(a1), int(asz)))
        live = self.om.orders(prod)
        res = []
        for s_, px, v in out:
            m = next((o for o in live if o.side == s_ and o.price == px and v / 2 <= o.volume <= v), None)
            res.append((s_, px, m.volume if m else v))
        return res

    def requote(self, prod, pull_side=None):
        want = self.desired_quotes(prod)
        if DRY:
            if want != self.last_desired.get(prod):
                log(f'DRY QUOTES {prod} fair {self.anchor.get(prod, (self.model["fair"][prod],))[0]:.1f} pos {self.om.position(prod)}: {want}')
            self.last_desired[prod] = want
            return
        self.last_desired[prod] = want
        if pull_side:   # adverse selection: kill the stale side before anything else
            stale = [o.id for o in self.om.orders(prod) if o.side == pull_side]
            list(self.om.pool.map(self.om.cancel, stale))
        r = self.om.set_quotes(prod, want)
        if r['cancelled'] or r['placed']:
            log(f'QUOTE {prod} {want} {r}')

    # ------------------------------------------------------------ fair loop
    def refresh_fair(self):
        old = self.model
        m = compute_fair()
        self.model = m
        if old is None or old['data_time'] == m['data_time']:
            return
        jk = self.p()['jump_k']
        for prod in PRODUCTS:
            d = m['fair'][prod] - old['fair'][prod]
            if abs(d) > jk * m['sigma'][prod] and self.enabled(prod):
                side = 'BUY' if d < 0 else 'SELL'   # fair fell -> our bids are stale
                log(f'JUMP {prod} fair {old["fair"][prod]:.1f}->{m["fair"][prod]:.1f}: pull {side}s, requote')
                self.last_quote[prod] = time.time()
                self.anchor.pop(prod, None)
                self._submit(prod, self.requote, prod, side)

    def periodic(self):
        for prod in PRODUCTS:
            if not self.enabled(prod):
                if not DRY and self.om.orders(prod):
                    self.om.set_quotes(prod, [])
                continue
            self.last_quote[prod] = time.time()
            self._submit(prod, self.requote, prod)

    def status(self):
        m = self.model
        log(f"--- data {m['data_time']} left {m['mins_left']:.0f}m range_floor {m['range_floor']:.1f} "
            f"live_orders {len(self.om.orders())} reqs {self.om.n_requests} errs {self.om.n_errors} "
            f"takes {self.n_takes}{'  [DRY]' if DRY else ''}")
        for prod in PRODUCTS:
            ob = self.books.get(prod)
            bb = ob.buy_orders[0].price if ob and ob.buy_orders else None
            ba = ob.sell_orders[0].price if ob and ob.sell_orders else None
            log(f"  {prod:13s} fair {m['fair'][prod]:7.1f} ±{m['sigma'][prod]:5.1f}  book {bb!s:>6} / {ba!s:<6} "
                  f"pos {self.om.position(prod):>4}  orders {len(self.om.orders(prod))}")
        # prediction tracker: one row per product per status tick -> data/predictions.csv
        try:
            f = Path(__file__).with_name('data') / 'predictions.csv'
            new = not f.exists()
            with f.open('a') as fh:
                if new:
                    fh.write('ts,data_time,product,actual,fair,sigma,bid,ask,pos\n')
                actual = m.get('actual', {})
                for prod in PRODUCTS:
                    ob = self.books.get(prod)
                    bb = ob.buy_orders[0].price if ob and ob.buy_orders else ''
                    ba = ob.sell_orders[0].price if ob and ob.sell_orders else ''
                    fh.write(f"{ts()},{m['data_time']},{prod},{actual.get(prod, '')},{m['fair'][prod]:.1f},"
                             f"{m['sigma'][prod]:.1f},{bb},{ba},{self.om.position(prod)}\n")
        except Exception as e:
            log('tracker error', repr(e))


def main():
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    load_env()
    bot = Bot2(os.environ['CMI_USER'], os.environ['CMI_PASS'])
    bot.refresh_fair()
    bot.om.reconcile()
    bot.om.start_reconcile(5)
    bot.start()
    log(f'bot2 started {"DRY" if DRY else "LIVE"}')
    t_per, t_stat = 0.0, 0.0
    try:
        while True:
            try:
                bot.refresh_fair()
                now = time.time()
                if now - t_per >= 5:
                    t_per = now
                    bot.periodic()
                if now - t_stat >= 15:
                    t_stat = now
                    bot.status()
            except Exception as e:
                log(f'loop error: {e!r}')
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        log('shutting down')
        try:
            bot.stop()
        except Exception:
            pass
        bot.ex.shutdown(wait=True)
        if not DRY:
            n = bot.om.cancel_all()
            log(f'cancelled {n} orders')
            bot.om.reconcile_positions()
        bot.om._stop.set()
        print('DONE positions:', bot.om.pos, flush=True)


if __name__ == '__main__':
    main()
