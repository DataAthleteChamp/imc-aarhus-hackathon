"""Regime / bot watcher. Polls /api/trade every 10s (read-only) and prints an alert line when:
  - a NEW participant name appears (bots joining),
  - trade rate in last 60s is > 3x the baseline,
  - trade prices deviate from the latest Energinet value by > 2 typical 15-min moves.
Also keeps a rolling summary. Log: data/watch.log.  Run: nohup .venv/bin/python -u watch.py >> data/watch.log &
"""
import json
import os
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

import requests

from bot import load_env

load_env()
U = 'https://gamma.cmi-exch.com'
ROOT = Path(__file__).parent
TYP = {'1_WIND': 14, '2_CO2': 24, '3_FLOW': 31, '4_ETF': 41, '5_WIND_RANGE': 5.7}
S = requests.Session()


def auth():
    r = S.post(U + '/api/user/authenticate', json={'username': os.environ['CMI_USER'], 'password': os.environ['CMI_PASS']})
    S.headers['Authorization'] = r.headers['Authorization']


def actual():
    try:
        rows = json.loads((ROOT / 'data/live_rows.json').read_text())['rows']
        r = rows[-1]
        a = {k: r[k] for k in ['1_WIND', '2_CO2', '3_FLOW']}
        a['4_ETF'] = sum(a.values())
        return a
    except Exception:
        return {}


def ts(t):
    return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()


def main():
    auth()
    seen_ids, names = set(), set()
    first = True
    rate = deque(maxlen=60)  # (time, n_trades) per poll
    while True:
        try:
            r = S.get(U + '/api/trade', timeout=5)
            if r.status_code == 401:
                auth(); continue
            trades = r.json()
            new = [t for t in trades if t.get('id') not in seen_ids]
            for t in new:
                seen_ids.add(t.get('id'))
            now = time.time()
            recent = [t for t in trades if now - ts(t['timestamp']) < 60]
            rate.append(len(recent))
            base = sorted(rate)[len(rate) // 2] if len(rate) > 6 else None
            stamp = datetime.now().strftime('%H:%M:%S')
            for t in new:
                for who in (t.get('buyer'), t.get('seller')):
                    if who and who not in names:
                        names.add(who)
                        if not first:
                            print(f'{stamp} ALERT NEW PARTICIPANT: {who} ({t["product"]} {t["price"]} x{t["volume"]})', flush=True)
            a = actual()
            dev_alerts = []
            for t in new:
                v = a.get(t['product'])
                if v is not None and abs(t['price'] - v) > 2 * TYP[t['product']]:
                    dev_alerts.append(f"{t['product']} {t['price']:.0f} vs value {v:.0f} ({t['aggressor']})")
            if dev_alerts and not first:
                print(f'{stamp} ALERT PRICE FAR FROM VALUE: ' + '; '.join(dev_alerts[:5]), flush=True)
            if base and len(recent) > 3 * max(base, 2) and not first:
                print(f'{stamp} ALERT TRADE RATE {len(recent)}/min vs baseline {base}/min', flush=True)
            if int(now) % 60 < 10:
                by = Counter(t['product'] for t in recent)
                agg = Counter(t['aggressor'] for t in recent)
                print(f'{stamp} rate {len(recent)}/min by product {dict(by)} top aggressors {agg.most_common(3)} '
                      f'participants {len(names)}', flush=True)
            first = False
        except Exception as e:
            print('watch error', repr(e), flush=True)
        time.sleep(10)


if __name__ == '__main__':
    main()
