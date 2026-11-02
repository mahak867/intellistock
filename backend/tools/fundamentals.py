"""Transparent quality score from fundamentals you supply (vendor feed or manual entry).
Every component is a linear scale between a 'bad' and a 'good' level; missing inputs are left
out and the rest reweighted, and the output says which were missing."""
from __future__ import annotations

import numpy as np

# name: (weight, bad, good). For 'lower is better' items bad > good.
COMPONENTS = {
    "roe": (20, 5.0, 20.0),                 # %
    "roce": (20, 6.0, 25.0),                # %
    "debt_equity": (15, 2.0, 0.1),          # ratio, lower better
    "profit_cagr_3y": (15, 0.0, 20.0),      # %
    "cfo_to_pat": (15, 0.4, 1.0),           # earnings quality: cash profit / reported profit
    "promoter_holding": (5, 20.0, 60.0),    # %
    "pledge_pct": (10, 30.0, 0.0),          # % of promoter holding pledged, lower better
}


def _scale(x: float, bad: float, good: float) -> float:
    return float(np.clip((x - bad) / (good - bad), 0.0, 1.0))


def quality_score(f: dict) -> dict:
    got, missing, parts = 0.0, [], {}
    wsum = 0.0
    for k, (w, bad, good) in COMPONENTS.items():
        v = f.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            missing.append(k)
            continue
        s = _scale(float(v), bad, good)
        parts[k] = round(s * 100, 1)
        got += w * s
        wsum += w
    if wsum == 0:
        return {"score": None, "components": {}, "missing": missing, "grade": None}
    score = got / wsum * 100
    grade = "strong" if score >= 70 else "average" if score >= 45 else "weak"
    return {"score": round(score, 1), "components": parts, "missing": missing, "grade": grade,
            "coverage_pct": round(wsum / sum(w for w, _, _ in COMPONENTS.values()) * 100, 0)}


def valuation_percentile(current: float, history: list[float]) -> dict:
    """Where today's multiple sits in its own history (0% = cheapest it has been)."""
    h = np.array([x for x in history if x is not None and x > 0])
    if len(h) < 20:
        return {"percentile": None, "label": "not enough history"}
    p = float((h <= current).mean())
    label = "cheap vs own history" if p <= 0.25 else "expensive vs own history" if p >= 0.75 else "mid-range vs own history"
    return {"percentile": p, "median": float(np.median(h)), "label": label,
            "note": "Cheap or expensive versus its own past only: businesses change."}


def holding_trend(quarters: list[dict]) -> dict:
    """quarters oldest->newest: {promoter: %, pledge: % of promoter holding}."""
    if len(quarters) < 2:
        return {"flags": []}
    a, b = quarters[0], quarters[-1]
    flags = []
    if b["promoter"] - a["promoter"] <= -2:
        flags.append(f"Promoter holding fell {a['promoter'] - b['promoter']:.1f} points")
    if b["pledge"] - a["pledge"] >= 5:
        flags.append(f"Pledged share rose {b['pledge'] - a['pledge']:.1f} points")
    if b["pledge"] >= 25:
        flags.append(f"{b['pledge']:.0f}% of promoter holding is pledged")
    return {"promoter_change": b["promoter"] - a["promoter"], "pledge_change": b["pledge"] - a["pledge"], "flags": flags}
