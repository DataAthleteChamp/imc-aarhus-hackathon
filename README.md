# IMC Aarhus Trading Hackathon: team bot

Trading 15:00–17:45 CET. Settlement = average of 17:40–17:45 Energinet PowerSystemRightNow.

| Product | Formula |
|---|---|
| 1_WIND | (Onshore+Offshore wind MW)/3 |
| 2_CO2 | CO2Emission × 10 |
| 3_FLOW | 1000 + Exchange_Sum/3 |
| 4_ETF | WIND + CO2 + FLOW |
| 5_WIND_RANGE | (max−min wind MW 15:00–17:45)/3, can only go up |

## Setup (1 min)
```bash
bash setup_mac.sh            # creates .venv
cp .env.example .env         # put team login in .env (git-ignored, never commit it)
.venv/bin/python fair.py     # print fair values now
DRY=1 .venv/bin/python bot.py   # watch book vs fair, no orders
.venv/bin/python bot.py         # trade
```
Only ONE person runs the live bot (one login per team). Others: research drift, edit `params.json` (hot-reloaded every 15 s).

## Files
- `fair.py`: settlement prediction (latest 5-min avg + drift, Monte Carlo for range, locks known minutes inside the window)
- `bot.py`: takes mispriced orders, quotes around fair, skews by inventory, WIND_RANGE floor
- `params.json`: live knobs (`trading_enabled`, `max_pos`, `drift_per_hour`, `manual_adj`, `disabled_products`)
