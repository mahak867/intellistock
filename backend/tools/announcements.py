"""Announcement digest: rule-based classification of exchange filings, with the source link kept.
No sentiment scores and no price calls: it only says what kind of filing this is and how
urgent it is to read. An LLM summariser can be added on top, but the rules below stay the
auditable floor."""
from __future__ import annotations

import re

RULES = [  # (category, importance, pattern)
    ("Auditor resignation", "high", r"resignation of (statutory )?auditor|auditor.{0,20}resign"),
    ("Pledge invocation", "high", r"invocation of (the )?pledge|pledge.{0,20}invok"),
    ("Fraud or default", "high", r"\bfraud\b|\bdefault\b|forensic audit|insolvency|nclt"),
    ("Key management exit", "high", r"resign.{0,40}(chief financial officer|cfo|managing director|ceo|chief executive)"),
    ("Credit rating change", "medium", r"credit rating|rating (downgrade|upgrade|reaffirm)"),
    ("Financial results", "medium", r"financial results|outcome of board meeting.{0,40}results|quarterly results"),
    ("Dividend", "medium", r"\bdividend\b"),
    ("Corporate action", "medium", r"\bbonus\b|stock split|sub-?division|\bbuy-?back\b|rights issue"),
    ("Acquisition or deal", "medium", r"acquisition|acquire|merger|amalgamation|order win|bagging|letter of award"),
    ("Regulatory action", "medium", r"sebi order|show cause|penalty|\bpenalised\b"),
    ("Insider or promoter trade", "low", r"insider trading|sast|promoter.{0,30}(acquir|sold|bought)"),
    ("Meeting or schedule", "low", r"board meeting|intimation|analyst|investor (meet|call)|earnings call"),
]
ORDER = {"high": 0, "medium": 1, "low": 2}


def classify(text: str) -> dict:
    t = text.lower()
    for cat, imp, pat in RULES:
        if re.search(pat, t):
            return {"category": cat, "importance": imp}
    return {"category": "Other", "importance": "low"}


def digest(items: list[dict], watch: set[str] | None = None) -> list[dict]:
    """items: {symbol, title, date, url}. Sorted by importance, then newest first."""
    out = []
    for it in items:
        c = classify(it["title"])
        out.append({**it, **c, "on_watchlist": (not watch) or it["symbol"].upper() in watch})
    return sorted(out, key=lambda x: (ORDER[x["importance"]], -(x["date"].toordinal() if hasattr(x["date"], "toordinal") else 0)))
