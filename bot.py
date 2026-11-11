"""Team bot: trades all 5 products against predicted settlement value.

  - TAKE: hit any resting order more than take_edge through fair (edge shrinks as the close nears)
  - QUOTE: rest two-sided quotes at fair +/- quote_k*sigma, skewed by inventory
  - WIND_RANGE: never sell below the range already realised (hard floor)
  - limits: |pos| <= max_pos (exchange limit 100)
Credentials:  export CMI_USER=... CMI_PASS=...   (or put them in .env, never commit)
Run:          .venv/bin/python bot.py            (DRY=1 to print only, no orders)
Tweak live:   edit params.json (reloaded every cycle)
"""
import os
import threading
import time
from dataclasses import asdict

import requests
from datetime import datetime
from pathlib import Path

from base_bot import BaseBot
from fair import TZ, compute_fair
from models import OrderBook, OrderRequest, OrderResponse, Side, Trade

URL = os.environ.get('CMI_URL', 'https://gamma.cmi-exch.com')
DRY = os.environ.get('DRY') == '1'
CYCLE_SEC = 15


def load_env():
    f = Path(__file__).with_name('.env')
    if f.exists():
        for line in f.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def ts():
    return datetime.now(TZ).strftime('%H:%M:%S')


class TeamBot(BaseBot):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.model = None
        self.pos = {}
        self.books = {}
        self.last_take = {}
        self.lock = threading.Lock()

    # keep-alive session: ~75ms per request instead of a new TLS handshake each time
    _S = requests.Session()

    def send_order(self, o: OrderRequest):
        payload = {k: v for k, v in asdict(o).items() if v is not None}
        r = self._S.post(f'{URL}/api/order', json=payload, headers=self._get_headers(), timeout=5)
        if r.status_code == 200:
            return OrderResponse(**r.json())
        print(f'{ts()} order rejected {o}: {r.text[:200]}', flush=True)

    def cancel_all_orders(self):
        r = self._S.get(f'{URL}/api/order/current-user', headers=self._get_headers(), timeout=5)
        for o in (r.json() if r.ok else []):
            self._S.delete(f"{URL}/api/order/{o['id']}", headers=self._get_headers(), timeout=5)

    def _register_bot(self):
        pass  # never auto-register a new account (rules: one login per team)

    # ---------- helpers ----------
    def p(self):
        return self.model['params']

    def take_edge(self, prod):
        p = self.p()
        return max(p['min_take_edge'][prod], p['take_k'] * self.model['sigma'][prod])

    # ---------- market data ----------
    def on_orderbook(self, ob: OrderBook):
        self.books[ob.product] = ob
        if self.model is None or DRY or not self.p()['trading_enabled']:
            return
        if ob.product in self.p()['disabled_products']:
            return
        if time.time() - self.last_take.get(ob.product, 0) < 1.0:
            return
        prod, p = ob.product, self.p()
        fair, edge = self.model['fair'][prod], self.take_edge(prod)
        pos, lim = self.pos.get(prod, 0), p['max_pos']
        asks = [o for o in ob.sell_orders if o.volume - o.own_volume > 0]
        bids = [o for o in ob.buy_orders if o.volume - o.own_volume > 0]
        # BUY everything cheap (sweep several levels)
        if asks and asks[0].price < fair - edge and pos < lim:
            vol = 0
            px = asks[0].price
            for o in asks:
                if o.price >= fair - edge:
                    break
                vol += o.volume - o.own_volume
                px = o.price
            vol = int(min(vol, p['take_clip'], lim - pos))
            self._take(prod, Side.BUY, px, vol, fair)
        elif bids and bids[0].price > fair + edge and pos > -lim:
            floor = self.model['range_floor'] if prod == '5_WIND_RANGE' else -1e9
            vol, px = 0, bids[0].price
            for o in bids:
                if o.price <= fair + edge:
                    break
                vol += o.volume - o.own_volume
                px = o.price
            if px <= floor:
                return
            vol = int(min(vol, p['take_clip'], lim + pos))
            self._take(prod, Side.SELL, px, vol, fair)

    def _take(self, prod, side, price, vol, fair):
        if vol <= 0:
            return
        self.last_take[prod] = time.time()
        r = self.send_order(OrderRequest(product=prod, side=side, price=int(price), volume=vol))
        filled = r.filled if r else 0
        with self.lock:
            self.pos[prod] = self.pos.get(prod, 0) + (filled if side == Side.BUY else -filled)
        print(f'{ts()} TAKE {side} {vol} {prod} @ {price:.0f} (fair {fair:.1f}) filled {filled}', flush=True)

    def on_trades(self, trades: list[Trade]):
        for t in trades:
            if self.username in (t.buyer, t.seller):
                side = 'BOUGHT' if t.buyer == self.username else 'SOLD'
                cp = t.seller if side == 'BOUGHT' else t.buyer
                print(f'{ts()} FILL {side} {t.volume:g} {t.product} @ {t.price:g} vs {cp}', flush=True)

    # ---------- periodic ----------
    def refresh_positions(self):
        r = self._S.get(f'{URL}/api/position/current-user', headers=self._get_headers(), timeout=5)
        pos = {x['product']: x['netPosition'] for x in r.json()} if r.ok else None
        if pos is not None:
            with self.lock:
                self.pos = pos

    def requote(self):
        self.cancel_all_orders()
        p = self.p()
        if not p['trading_enabled']:
            return
        for prod, fair in self.model['fair'].items():
            if prod in p['disabled_products']:
                continue
            half = max(p['quote_k'] * self.model['sigma'][prod], p['min_take_edge'][prod] * 1.5)
            pos, lim, q = self.pos.get(prod, 0), p['max_pos'], p['quote_size']
            skew = half * pos / lim  # long -> lower quotes to shed inventory
            bid, ask = round(fair - half - skew), round(fair + half - skew)
            if prod == '5_WIND_RANGE':
                ask = max(ask, round(self.model['range_floor'] + p['min_take_edge'][prod]))
            if pos + q <= lim and bid > 0:
                self.send_order(OrderRequest(product=prod, side=Side.BUY, price=bid, volume=q))
            if pos - q >= -lim:
                self.send_order(OrderRequest(product=prod, side=Side.SELL, price=ask, volume=q))

    def status(self):
        m = self.model
        print(f"--- {ts()} data {m['data_time']} left {m['mins_left']:.0f}m range_floor {m['range_floor']:.1f}"
              f"{'  [DRY]' if DRY else ''}")
        for prod in sorted(m['fair']):
            ob = self.books.get(prod)
            bb = ob.buy_orders[0].price if ob and ob.buy_orders else None
            ba = ob.sell_orders[0].price if ob and ob.sell_orders else None
            print(f"  {prod:13s} fair {m['fair'][prod]:7.1f} ±{m['sigma'][prod]:5.1f}  "
                  f"book {bb!s:>6} / {ba!s:<6} pos {self.pos.get(prod, 0):>4}", flush=True)

    def cycle(self):
        self.model = compute_fair()
        if not DRY:
            self.refresh_positions()
            self.requote()
        self.status()


def main():
    import signal
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # kill -TERM -> clean shutdown
    load_env()
    bot = TeamBot(URL, os.environ['CMI_USER'], os.environ['CMI_PASS'])
    bot.model = compute_fair()
    bot.start()
    try:
        while True:
            try:
                bot.cycle()
            except Exception as e:
                print(f'{ts()} cycle error: {e!r}', flush=True)
            time.sleep(CYCLE_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop()
        if not DRY:
            bot.cancel_all_orders()
            bot.refresh_positions()
        print('DONE positions:', bot.pos, flush=True)


if __name__ == '__main__':
    main()
