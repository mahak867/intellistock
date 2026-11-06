"""RBI Account Aggregator through Setu (the same consent-based route the IDFC FIRST app uses to show all your accounts).

You consent once on the AA's page; the data then comes straight from your banks, depositories and fund houses:
savings and current accounts (DEPOSIT), fixed and recurring deposits (TERM_DEPOSIT, RECURRING_DEPOSIT),
mutual funds (MUTUAL_FUNDS), stocks (EQUITIES), NPS, bonds.

Using it needs a Setu FIU product (sandbox or production): SETU_AA_CLIENT_ID, SETU_AA_CLIENT_SECRET,
SETU_AA_PRODUCT_INSTANCE_ID. Built from Setu's public docs (consent: POST /consents, GET /consents/{id};
data: POST /sessions, GET /sessions/{id}); not yet run against Setu itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from backend.core.config import settings


class AAError(Exception):
    def __init__(self, msg: str, status: int = 502):
        super().__init__(msg)
        self.status = status


def configured() -> bool:
    return bool(settings.SETU_AA_CLIENT_ID and settings.SETU_AA_CLIENT_SECRET and settings.SETU_AA_PRODUCT_INSTANCE_ID)


class Setu:
    def __init__(self, client: httpx.Client | None = None):
        self.base = settings.SETU_AA_BASE.rstrip("/")
        self.client = client or httpx.Client(timeout=30)

    def _h(self) -> dict:
        return {"x-client-id": settings.SETU_AA_CLIENT_ID or "", "x-client-secret": settings.SETU_AA_CLIENT_SECRET or "",
                "x-product-instance-id": settings.SETU_AA_PRODUCT_INSTANCE_ID or "", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.client.request(method, self.base + path, headers=self._h(), **kw)
        except httpx.HTTPError as e:
            raise AAError(f"Could not reach the account aggregator ({type(e).__name__}).") from None
        try:
            body = r.json()
        except ValueError:
            raise AAError(f"Unreadable answer from the account aggregator (HTTP {r.status_code}).") from None
        if r.status_code >= 400:
            msg = body.get("errorMsg") or body.get("message") or body.get("error") or f"HTTP {r.status_code}"
            raise AAError(f"Account aggregator says: {msg}", 400 if r.status_code < 500 else 502)
        return body

    def create_consent(self, mobile: str, redirect_url: str, years_back: int = 2) -> dict:
        now = datetime.now(timezone.utc)
        body = {"consentDuration": {"unit": "MONTH", "value": "12"}, "vua": mobile,
                "dataRange": {"from": (now - timedelta(days=365 * years_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
                "context": [], "redirectUrl": redirect_url}
        r = self._call("POST", "/consents", json=body)
        if not r.get("id") or not r.get("url"):
            raise AAError("The account aggregator did not return a consent link.")
        return {"id": r["id"], "url": r["url"], "status": r.get("status", "PENDING")}

    def consent_status(self, consent_id: str) -> str:
        return str(self._call("GET", f"/consents/{consent_id}").get("status", "UNKNOWN")).upper()

    def create_session(self, consent_id: str, days_back: int = 30) -> str:
        now = datetime.now(timezone.utc)
        r = self._call("POST", "/sessions", json={"consentId": consent_id, "format": "json",
                                                  "dataRange": {"from": (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")}})
        if not r.get("id"):
            raise AAError("The account aggregator did not start a data session.")
        return r["id"]

    def session(self, session_id: str) -> dict:
        return self._call("GET", f"/sessions/{session_id}")


def _get(d: dict, *names):
    """Case-insensitive lookup: FIPs differ in capitalisation (currentBalance / CurrentBalance)."""
    if not isinstance(d, dict):
        return None
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _list(v):
    return v if isinstance(v, list) else [v] if isinstance(v, dict) else []


def parse_session(data: dict) -> dict:
    """Turn a data session into bank balances, deposits, funds and stocks."""
    out = {"bank": [], "deposits": [], "funds": [], "stocks": [], "other": [], "failed": []}
    for fip in data.get("fips") or []:
        fip_id = fip.get("fipID") or fip.get("fipId") or "FIP"
        for acc in fip.get("accounts") or []:
            masked = acc.get("maskedAccNumber") or ""
            d = (acc.get("data") or {}).get("account") if acc.get("data") else None
            if not d:
                out["failed"].append(f"{fip_id} {masked}".strip())
                continue
            kind = str(_get(d, "type") or "").lower()
            s = _get(d, "summary") or {}
            label = f"{fip_id} {masked[-4:]}".strip()
            if kind == "deposit":
                bal = _f(_get(s, "currentBalance"))
                if bal is not None:
                    out["bank"].append({"name": f"{label} {(_get(s, 'type') or 'account').title()}", "amount": bal,
                                        "as_of": str(_get(s, "balanceDateTime") or "")[:10] or None})
            elif kind in ("term_deposit", "term-deposit", "recurring_deposit", "recurring-deposit"):
                out["deposits"].append({"name": f"{label} {'RD' if 'recurring' in kind else 'FD'}", "kind": "rd" if "recurring" in kind else "fd",
                                        "principal": _f(_get(s, "principalAmount")), "value": _f(_get(s, "currentValue", "maturityAmount")),
                                        "rate": _f(_get(s, "interestRate")), "start": str(_get(s, "openingDate") or "")[:10] or None,
                                        "maturity": str(_get(s, "maturityDate") or "")[:10] or None})
            elif kind in ("mutual_funds", "mutual-funds", "mutualfunds"):
                hs = _get(_get(_get(s, "investment") or {}, "holdings") or {}, "holding")
                for h in _list(hs):
                    units = _f(_get(h, "closingUnits", "units"))
                    if units:
                        out["funds"].append({"scheme_code": str(_get(h, "amfiCode", "schemeCode") or "") or None, "isin": _get(h, "isin"),
                                             "scheme_name": str(_get(h, "schemeName", "isinDescription") or _get(h, "isin") or "Fund")[:200],
                                             "units": units, "nav": _f(_get(h, "nav")), "folio": str(_get(h, "folioNo") or masked)[:40]})
            elif kind == "equities":
                hs = _get(_get(_get(s, "investment") or {}, "holdings") or {}, "holding")
                for h in _list(hs):
                    units = _f(_get(h, "units"))
                    if units:
                        out["stocks"].append({"isin": _get(h, "isin"), "name": _get(h, "issuerName", "isinDescription"),
                                              "qty": units, "price": _f(_get(h, "lastTradedPrice"))})
            else:
                val = _f(_get(s, "currentValue", "currentBalance", "totalValue"))
                if val:
                    out["other"].append({"name": f"{label} {kind.upper() or 'ACCOUNT'}", "kind": "nps" if "nps" in kind else "bond" if "bond" in kind else "other", "amount": val})
    return out
