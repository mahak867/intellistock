## Kronos-small on NSE: 49 stocks, 1176 forecasts
2024-11-14 to 2026-09-24, 30 paths each, 256 days of context. Origins 20 trading days apart, so every scored day is used once.

| Test | 5 days | 10 days |
|---|---|---|
| Real price inside the 10-90% range (target 80%) | 35.6% (history baseline 71.6%) | 30.6% (history baseline 71.1%) |
| Range width, average | 5.4% (baseline 8.1%) | 6.1% (baseline 11.4%) |
| Pinball loss better than the history baseline | 0 of 49 stocks | 1 of 49 stocks |
| Pinball loss, average (lower is better) | 0.0186 vs 0.0105 | 0.0271 vs 0.0146 |
| Middle forecast beats no change (error) | 1 of 49 stocks | 1 of 49 stocks |
| Direction hit rate (always-up baseline) | 53.5% (52.0%) | 52.6% (55.2%) |
| Stocks passing the edge test (luck gives about 1) | 0 of 49 | 0 of 49 |

**Verdict: does not pass the bar to show a Kronos range in the app** (10-day coverage 30.6%, needs 75-85%; better pinball on 1 of 49, needs more than half).
