"""Fast order execution for the CMI exchange.

    om = OrderManager.login(URL, user, pw)       # or OrderManager(URL, token, user=...)
    om.start_stream()                            # optional: own SSE thread for fills (or feed om.on_trades)
    om.start_reconcile(5)                        # optional: background reconcile of orders+positions
    om.set_quotes('1_WIND', [('BUY', 1000, 5), ('SELL', 1010, 5)])
    filled = om.take('1_WIND', 'BUY', 1012, 3)   # never rests: remainder cancelled at once
    om.position('1_WIND'); om.cancel_all()

Design notes
  - one keep-alive requests.Session (pool 20) + ThreadPoolExecutor: N orders cost ~1 RTT, not N.
  - set_quotes diffs against locally tracked resting orders: identical (side, price, remaining vol)
    orders are kept (queue priority preserved), only stale ones are cancelled, new ones placed.
    Cancels are sent (parallel) before places so the exchange's position-limit check does not
    silently shrink the new orders.
  - local state comes from POST responses + SSE fills; reconcile() resyncs from the exchange.
  - token-bucket rate guard (default 15 req/s), one retry on 5xx / connection error / timeout
    (POST is NOT retried on read timeout - it may have been placed; a reconcile is flagged instead),
    429 -> back off (Retry-After) and retry.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

JSON_H = {'Content-Type': 'application/json; charset=utf-8'}


@dataclass
class LiveOrder:
    id: str
    product: str
    side: str      # 'BUY' / 'SELL'
    price: int
    volume: int    # remaining (unfilled) volume


class RateGuard:
    """Token bucket: at most `rate` requests/sec, bursts up to `rate`."""

    def __init__(self, rate: float = 15):
        self.rate, self.tokens, self.t = float(rate), float(rate), time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.rate, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


class OrderManager:
    def __init__(self, url: str, token: str, user: str | None = None, max_rps: float = 15,
                 workers: int = 16, timeout=(1.0, 3.0), verbose: bool = True, order_filter=None):
        self.url = url.rstrip('/')
        self.user = user
        self.order_filter = order_filter   # reconcile/cancel_all only adopt exchange orders where f(dict) is True
        self.timeout = timeout
        self.verbose = verbose
        self.s = requests.Session()
        ad = HTTPAdapter(pool_connections=4, pool_maxsize=20, max_retries=0)
        self.s.mount('https://', ad)
        self.s.mount('http://', ad)
        self.s.headers.update({**JSON_H, 'Authorization': token})
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='om')
        self.guard = RateGuard(max_rps)
        self.lock = threading.RLock()
        self.prod_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self.live: dict[str, LiveOrder] = {}          # id -> order
        self.pos: dict[str, int] = {}
        self._seen_trades: set[str] = set()
        self.need_reconcile = False
        self.n_requests = 0
        self.n_errors = 0
        self._threads: list = []
        self._stop = threading.Event()

    @classmethod
    def login(cls, url: str, user: str, password: str, **kw) -> 'OrderManager':
        r = requests.post(f"{url.rstrip('/')}/api/user/authenticate", headers=JSON_H,
                          json={'username': user, 'password': password}, timeout=10)
        r.raise_for_status()
        return cls(url, r.headers['Authorization'], user=user, **kw)

    def _log(self, *a):
        if self.verbose:
            print(time.strftime('%H:%M:%S'), '[om]', *a, flush=True)

    # ------------------------------------------------------------------ http
    def _req(self, method: str, path: str, **kw) -> requests.Response | None:
        """Rate-guarded request with one retry. Returns Response (any status) or None on network failure."""
        retries_left, backoff_429 = 1, 3
        while True:
            self.guard.acquire()
            self.n_requests += 1
            try:
                r = self.s.request(method, self.url + path, timeout=self.timeout, **kw)
            except requests.exceptions.ReadTimeout:
                if method == 'POST':           # may have been accepted -> do not double-place
                    self.need_reconcile = True
                    self.n_errors += 1
                    self._log(f'{method} {path} read timeout (not retried)')
                    return None
                err = 'timeout'
            except requests.exceptions.RequestException as e:
                err = repr(e)
            else:
                if r.status_code == 429 and backoff_429 > 0:
                    backoff_429 -= 1
                    try:
                        wait = float(r.headers.get('Retry-After', 0.5))
                    except ValueError:
                        wait = 0.5
                    self._log(f'429 on {method} {path}, sleeping {wait}s')
                    time.sleep(min(wait, 2.0))
                    continue
                if r.status_code >= 500 and retries_left > 0:
                    retries_left -= 1
                    time.sleep(0.05)
                    continue
                return r
            if retries_left > 0:
                retries_left -= 1
                time.sleep(0.05)
                continue
            self.n_errors += 1
            self.need_reconcile = True
            self._log(f'{method} {path} failed: {err}')
            return None

    # ------------------------------------------------------------ primitives
    def _place(self, product: str, side: str, price, volume) -> dict | None:
        price, volume = int(round(price)), int(volume)
        if volume <= 0:
            return None
        r = self._req('POST', '/api/order',
                      json={'product': product, 'side': str(side), 'price': price, 'volume': volume})
        if r is None:
            return None
        if r.status_code != 200:
            self.n_errors += 1
            self._log(f'place {side} {volume} {product}@{price} rejected {r.status_code}: {r.text[:150]}')
            return None
        d = r.json()
        if self.user is None:
            self.user = d.get('user')
        return d

    def _track(self, d: dict):
        """Register a POST response as a resting order if it still has volume."""
        rem = int(d.get('volume', 0)) - int(d.get('filled', 0) or 0)
        if d.get('id') and rem > 0:
            with self.lock:
                self.live[d['id']] = LiveOrder(d['id'], d['product'], str(d['side']),
                                               int(round(float(d['price']))), rem)

    def _cancel(self, oid: str) -> bool:
        r = self._req('DELETE', f'/api/order/{oid}')
        if r is None:
            return False                       # unknown: keep tracking, reconcile will tell
        with self.lock:
            self.live.pop(oid, None)          # 200 -> cancelled; 4xx -> already gone (filled/cancelled)
        return r.status_code == 200

    def place(self, product, side, price, volume) -> dict | None:
        """Place a resting limit order (tracked). Returns the POST response dict."""
        d = self._place(product, side, price, volume)
        if d:
            self._track(d)
        return d

    def cancel(self, oid: str) -> bool:
        return self._cancel(oid)

    # ------------------------------------------------------------- quoting
    def orders(self, product: str | None = None) -> list[LiveOrder]:
        with self.lock:
            return [o for o in self.live.values() if product is None or o.product == product]

    def set_quotes(self, product: str, desired: list[tuple], parallel: bool = True,
                   cancel_first: bool = True) -> dict:
        """Make our resting orders on `product` equal `desired` [(side, price, vol), ...].

        Orders already resting at the same side/price with the same remaining volume are kept
        (queue priority). Everything else is cancelled; missing quotes are placed.
        Returns {'kept': n, 'cancelled': n, 'placed': n, 'ms': elapsed}.
        """
        t0 = time.perf_counter()
        want = [(str(s), int(round(p)), int(v)) for s, p, v in desired if int(v) > 0]
        with self.prod_locks[product]:
            current = self.orders(product)
            to_place, keep_ids = [], set()
            for w in want:
                match = next((o for o in current if o.id not in keep_ids
                              and (o.side, o.price, o.volume) == w), None)
                if match:
                    keep_ids.add(match.id)
                else:
                    to_place.append(w)
            to_cancel = [o.id for o in current if o.id not in keep_ids]

            if parallel:
                if cancel_first:
                    list(self.pool.map(self._cancel, to_cancel))
                    res = list(self.pool.map(lambda w: self._place(product, *w), to_place))
                else:
                    fc = [self.pool.submit(self._cancel, i) for i in to_cancel]
                    fp = [self.pool.submit(self._place, product, *w) for w in to_place]
                    [f.result() for f in fc]
                    res = [f.result() for f in fp]
            else:
                for i in to_cancel:
                    self._cancel(i)
                res = [self._place(product, *w) for w in to_place]
            placed = 0
            for d in res:
                if d:
                    self._track(d)
                    placed += 1
        return {'kept': len(keep_ids), 'cancelled': len(to_cancel), 'placed': placed,
                'ms': (time.perf_counter() - t0) * 1000}

    # --------------------------------------------------------------- taking
    def take(self, product: str, side: str, price, vol) -> int:
        """Aggressive order that never rests: place, and if not fully filled cancel the rest at once.
        Returns volume filled by the POST (position itself is updated from SSE fills / reconcile)."""
        d = self._place(product, side, price, vol)
        if not d:
            return 0
        filled = int(d.get('filled', 0) or 0)
        if filled < int(d.get('volume', vol)) and d.get('id'):
            r = self._req('DELETE', f"/api/order/{d['id']}")
            if r is None or r.status_code != 200:
                if r is None:                  # couldn't cancel -> track so set_quotes/cancel_all kill it
                    self._track(d)
        return filled

    # --------------------------------------------------------------- cancel
    def cancel_all(self, product: str | None = None, from_exchange: bool = True) -> int:
        """Cancel all our orders in parallel. from_exchange=True also asks the exchange
        (catches orders we don't know about). Returns number of cancel requests sent."""
        ids = {o.id for o in self.orders(product)}
        if from_exchange:
            r = self._req('GET', '/api/order/current-user')
            if r is not None and r.ok:
                ids |= {o['id'] for o in r.json() if (product is None or o.get('product') == product)
                        and (self.order_filter is None or self.order_filter(o))}
        list(self.pool.map(self._cancel, ids))
        return len(ids)

    # ------------------------------------------------------------ positions
    def on_trades(self, trades):
        """Feed SSE trade events (dicts or models.Trade). Updates position from our fills and
        decrements the remaining volume of the matching tracked order."""
        for t in trades:
            g = t.get if isinstance(t, dict) else (lambda k, _t=t: getattr(_t, k, None))
            buyer, seller = g('buyer'), g('seller')
            if self.user is None or self.user not in (buyer, seller):
                continue
            tid = g('id')
            if tid:
                if tid in self._seen_trades:
                    continue
                self._seen_trades.add(tid)
            prod, vol, px = g('product'), int(g('volume')), int(round(float(g('price'))))
            with self.lock:
                if buyer == self.user:
                    self.pos[prod] = self.pos.get(prod, 0) + vol
                if seller == self.user:
                    self.pos[prod] = self.pos.get(prod, 0) - vol
                # passive fill of one of our resting orders: shrink it
                for side, me in (('BUY', buyer), ('SELL', seller)):
                    if me != self.user:
                        continue
                    for o in self.live.values():
                        if o.product == prod and o.side == side and o.price == px:
                            o.volume -= vol
                            if o.volume <= 0:
                                self.live.pop(o.id, None)
                            break

    def position(self, product: str) -> int:
        with self.lock:
            return self.pos.get(product, 0)

    # ------------------------------------------------------------ reconcile
    def reconcile_orders(self) -> bool:
        with self.lock:
            locks = [self.prod_locks[p] for p in sorted(self.prod_locks)]
        for l in locks:                       # no set_quotes in flight while we resync
            l.acquire()
        try:
            r = self._req('GET', '/api/order/current-user')
            if r is None or not r.ok:
                return False
            new = {}
            for o in r.json():
                if self.order_filter and not self.order_filter(o):
                    continue
                vol = int(o.get('volume', 0)) - int(o.get('filled', 0) or 0)
                if vol > 0:
                    new[o['id']] = LiveOrder(o['id'], o['product'], str(o['side']),
                                             int(round(float(o['price']))), vol)
            with self.lock:
                diff = set(new) ^ set(self.live)
                if diff:
                    self._log(f'reconcile orders: {len(diff)} mismatched ids fixed')
                self.live = new
            self.need_reconcile = False
            return True
        finally:
            for l in locks:
                l.release()

    def reconcile_positions(self) -> dict | None:
        r = self._req('GET', '/api/position/current-user')
        if r is None or not r.ok:
            return None
        new = {p['product']: int(p.get('netPosition', p.get('net_position', 0))) for p in r.json()}  # API field is camelCase
        with self.lock:
            if any(self.pos.get(k, 0) != v for k, v in new.items()):
                self._log(f'reconcile positions {self.pos} -> {new}')
            self.pos = new
        return new

    def reconcile(self):
        self.reconcile_orders()
        self.reconcile_positions()

    def start_reconcile(self, interval: float = 5.0):
        def loop():
            while not self._stop.wait(interval):
                try:
                    self.reconcile()
                except Exception as e:
                    self._log('reconcile error', repr(e))
        th = threading.Thread(target=loop, daemon=True, name='om-reconcile')
        th.start()
        self._threads.append(th)

    def start_stream(self, on_orderbook=None, on_trades=None):
        """Own SSE connection; fills update positions. Optional extra callbacks receive raw dicts."""
        import sseclient

        def loop():
            while not self._stop.is_set():
                try:
                    h = {'Authorization': self.s.headers['Authorization'], 'Accept': 'text/event-stream'}
                    resp = requests.get(self.url + '/api/market/stream', stream=True, headers=h, timeout=30)
                    for ev in sseclient.SSEClient(resp).events():
                        if self._stop.is_set():
                            return
                        if ev.event == 'trade':
                            tr = json.loads(ev.data)
                            self.on_trades(tr)
                            if on_trades:
                                on_trades(tr)
                        elif ev.event == 'order' and on_orderbook:
                            on_orderbook(json.loads(ev.data))
                except Exception as e:
                    if not self._stop.is_set():
                        self._log('stream error, reconnecting', repr(e))
                        time.sleep(1)
        th = threading.Thread(target=loop, daemon=True, name='om-sse')
        th.start()
        self._threads.append(th)

    def close(self, cancel: bool = True):
        self._stop.set()
        if cancel:
            self.cancel_all()
        self.pool.shutdown(wait=True)
