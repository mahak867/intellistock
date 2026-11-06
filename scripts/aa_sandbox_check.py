"""Run the Account Aggregator flow against Setu's SANDBOX with real keys, to see what Setu actually returns.

    SETU_AA_CLIENT_ID=... SETU_AA_CLIENT_SECRET=... SETU_AA_PRODUCT_INSTANCE_ID=... python scripts/aa_sandbox_check.py [mobile]

Step 1 creates a consent and prints its approval link. Approve it in a browser (sandbox: any OTP Setu's docs list),
then run again with CONSENT_ID=<id> to check the status, pull the data and print what IntelliStock would import.
"""
import json
import os
import sys

from backend.brokers import aa as AA

if not AA.configured():
    sys.exit("Set SETU_AA_CLIENT_ID, SETU_AA_CLIENT_SECRET and SETU_AA_PRODUCT_INSTANCE_ID first.")
s = AA.Setu()
cid = os.environ.get("CONSENT_ID")
if not cid:
    c = s.create_consent(sys.argv[1] if len(sys.argv) > 1 else "9999999999", "https://example.com/done")
    print("Consent created:", c["id"])
    print("Approve it here:", c["url"])
    sys.exit(0)
st = s.consent_status(cid)
print("Consent status:", st)
if st not in ("ACTIVE", "APPROVED"):
    sys.exit("Not approved yet.")
sid = s.create_session(cid)
import time
for _ in range(20):
    data = s.session(sid)
    if str(data.get("status", "")).upper() in ("COMPLETED", "PARTIAL", "FAILED", "EXPIRED"):
        break
    time.sleep(3)
print("Session status:", data.get("status"))
print(json.dumps(AA.parse_session(data), indent=2, default=str))
open("aa_session_raw.json", "w").write(json.dumps(data, indent=2))
print("Raw response saved to aa_session_raw.json (has personal data in production: do not share it).")
