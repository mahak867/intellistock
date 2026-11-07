## Kronos-small on NSE: 50 stocks, 1200 forecasts
2024-11-14 to 2026-09-24, 30 paths each, 256 days of context, temperature 1.0, top-p 0.9. Origins 20 trading days apart, so every scored day is used once.

| Test | 5 days | 10 days |
|---|---|---|
| Real price inside the 10-90% range (target 80%) | 35.5% (history baseline 71.6%) | 30.9% (history baseline 71.0%) |
| Range width, average | 5.4% (baseline 8.2%) | 6.2% (baseline 11.5%) |
| Pinball loss better than the history baseline | 0 of 50 stocks | 1 of 50 stocks |
| Pinball loss, average (lower is better) | 0.0188 vs 0.0105 | 0.0277 vs 0.0150 |
| Middle forecast beats no change (error) | 1 of 50 stocks | 1 of 50 stocks |
| Direction hit rate (always-up baseline) | 53.3% (51.9%) | 52.4% (55.0%) |
| Stocks passing the edge test (luck gives about 1) | 0 of 50 | 0 of 50 |

Diagnostics: middle path moves 1.41% on day 1 (real prices moved 1.20%); 10-day middle move 5.35%; correlation of that move with the gap to the window's average price +0.79 (near +1 means it reverts to the average).

**Verdict: does not pass the bar to show a Kronos range in the app** (10-day coverage 30.9%, needs 75-85%; better pinball on 1 of 50, needs more than half).
