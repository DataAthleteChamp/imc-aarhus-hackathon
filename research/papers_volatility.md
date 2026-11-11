# Noise-bot regime: parameter rules (ranked)

Key insight: we know the fundamental and the terminal value is a mechanical average. So noise is mostly something to trade against, not a risk. Kyle (1985): more noise trading means more depth and less adverse selection. Glosten-Milgrom: the spread only needs to cover the informed share of order flow.

1. **Detect (vol_ratio)**: track the 3-min realized std of (mid - fundamental) and compare it to the pre-bot baseline. Regime is ON when ratio > 1.5 **or** trades/min > 14 (2x the baseline of 7) **or** any print >= 2x the usual size. It goes OFF only when ratio < 1.2 for 2 min (hysteresis). [standard vol-regime MM practice]
2. **gap_thr**: do NOT raise it. Express it in sigma units: thr = max(base, 1.5*sigma_resid). Bigger noise deviations from a known value are mean-reversion edge. [DSSW 1990; Kyle 1985]
3. **gap_size / gap_cap**: scale in, with size = gap_size * min(3, dev/thr) and cap unchanged at 30. Keep spare capacity, because noise-trader deviations can widen before they revert. [DSSW noise-trader risk; Shleifer-Vishny limits of arbitrage]
4. **Momentum bots**: if 3 or more same-side aggressive trades come in within 10 s, skip the first push. Enter on the next tick only if dev is still > thr, or on the overshoot. [Cartea-Jaimungal ch. 10 order-flow toxicity]
5. **mm_min_half**: half = max(base, 0.8*sigma_resid_1min). This tracks the Avellaneda-Stoikov term gamma*sigma^2*tau/2 + ln(1+gamma/k)/gamma. Widen roughly linearly in sigma, not more. [AS 2008; GLFT 2013]
6. **mm_size**: keep size*sigma constant, i.e. mm_size = base/vol_ratio (minimum 2). max_pos for MM stays at 10. Increase the inventory skew by vol_ratio^2 (GLFT skew is proportional to gamma*sigma^2*q). [GLFT 2013]
7. **release_widen**: keep 2x, plus 1.5x while the regime is ON. Lagged publishes are when real information arrives. [Glosten-Milgrom]
8. **take_k / max_pos (endgame)**: settlement uncertainty shrinks with the unknown share of the averaging window (sigma_settle ∝ remaining fraction * sigma). Use that sigma so k 1→0.5 stays valid. Noise bots bring more mispricings, so use cap 50. Build the position in 17:20-17:38, because liquidity thins near expiry. Hold to settlement and don't plan to exit. Stop passive quotes that add inventory after 17:40. [Cartea-Jaimungal terminal-penalty; pinning-near-expiry literature]
