## Kronos-small on NSE: 10 stocks, 240 forecasts
2024-11-14 to 2026-09-24, 30 paths each, 512 days of context, temperature 1.0, top-p 0.9. Origins 20 trading days apart, so every scored day is used once.

| Test | 5 days | 10 days |
|---|---|---|
| Real price inside the 10-90% range (target 80%) | 54.6% (history baseline 72.9%) | 50.8% (history baseline 70.8%) |
| Range width, average | 6.8% (baseline 7.3%) | 9.5% (baseline 10.3%) |
| Pinball loss better than the history baseline | 0 of 10 stocks | 0 of 10 stocks |
| Pinball loss, average (lower is better) | 0.0125 vs 0.0093 | 0.0202 vs 0.0136 |
| Middle forecast beats no change (error) | 1 of 10 stocks | 0 of 10 stocks |
| Direction hit rate (always-up baseline) | 55.0% (53.7%) | 51.2% (52.9%) |
| Stocks passing the edge test (luck gives about 1) | 0 of 10 | 0 of 10 |

Diagnostics: middle path moves 0.76% on day 1 (real prices moved 1.06%); 10-day middle move 4.11%; correlation of that move with the gap to the window's average price +0.51 (near +1 means it reverts to the average).

**Verdict: does not pass the bar to show a Kronos range in the app** (10-day coverage 50.8%, needs 75-85%; better pinball on 0 of 10, needs more than half).
