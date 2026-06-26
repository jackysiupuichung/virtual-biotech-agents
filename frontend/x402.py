"""x402.py — minimal x402 (HTTP 402 "Payment Required") gate for the cited report.

Implements the x402 handshake without an external SDK so the gate works in any
environment:

  1. Agent GETs the paid resource with no payment      -> 402 + `accepts` block
     (the payment requirements: scheme, network, amount, payTo, resource).
  2. Agent retries with an `X-PAYMENT` header carrying a settlement payload     ->
     the gate verifies it and, if valid, serves the resource (and echoes an
     `X-PAYMENT-RESPONSE` settlement receipt).

Verification here is deliberately pluggable: by default it accepts any payment
payload whose declared amount/asset/payTo match the requirements (DEMO mode, so
the rail is exercisable end-to-end offline). Set ``X402_FACILITATOR_URL`` to
delegate real on-chain verification + settlement to an x402 facilitator
(Coinbase CDP / MPP-compatible), at which point the payload is forwarded there.

The payment requirements are loaded from ``cited.payment.json`` (minted by
``publish_cited.py``), so price/payTo/network are single-sourced with the
published manifest and the MPP / CDP / agentic.market listings.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "cited.payment.json"


def _load_requirements() -> dict:
    """Build the x402 `accepts` entry from the published payment manifest."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    x = m["rails"]["x402"]
    pay_to = os.environ.get("X402_PAY_TO", x["payTo"])
    return {
        "scheme": x["scheme"],
        "network": os.environ.get("X402_NETWORK", x["network"]),
        "maxAmountRequired": x["maxAmountRequired"],
        "asset": x["asset"],
        "payTo": pay_to,
        "resource": x["resource"],
        "description": x["description"],
        "mimeType": "text/markdown",
    }


def payment_required_body(extra: dict | None = None) -> dict:
    """The JSON body returned alongside a 402: x402 `accepts` + listing pointers."""
    req = _load_requirements()
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    body = {
        "x402Version": 1,
        "error": "payment required",
        "accepts": [req],
        # discovery pointers to the other rails the artifact is listed on
        "listings": {
            "mpp": m["rails"].get("mpp"),
            "cdp": m["rails"].get("cdp"),
            "agentic_market": m["rails"].get("agentic_market"),
        },
    }
    if extra:
        body.update(extra)
    return body


def _decode_payment(header: str) -> dict:
    """X-PAYMENT is base64(JSON) per x402; tolerate raw JSON too."""
    raw = header.strip()
    try:
        raw = base64.b64decode(raw).decode("utf-8")
    except Exception:  # noqa: BLE001 — not base64; assume raw JSON
        pass
    return json.loads(raw)


def verify_payment(header: str | None) -> tuple[bool, dict]:
    """Verify an X-PAYMENT header against the manifest requirements.

    Returns ``(ok, receipt)``. With ``X402_FACILITATOR_URL`` set, delegates to a
    real facilitator's /verify endpoint; otherwise runs DEMO verification that
    checks the declared amount/asset/payTo match — enough to exercise the rail
    end-to-end without a chain, never claiming a settlement that didn't happen.
    """
    if not header:
        return False, {"reason": "no X-PAYMENT header"}
    try:
        payload = _decode_payment(header)
    except Exception as exc:  # noqa: BLE001
        return False, {"reason": f"undecodable payment: {exc}"}

    req = _load_requirements()
    facilitator = os.environ.get("X402_FACILITATOR_URL")
    if facilitator:
        return _facilitator_verify(facilitator, payload, req)

    # DEMO verification: declared terms must match the requirements.
    declared = payload.get("payload", payload)
    amount_ok = str(declared.get("amount", req["maxAmountRequired"])) == req["maxAmountRequired"]
    asset_ok = declared.get("asset", req["asset"]) == req["asset"]
    payto_ok = declared.get("payTo", req["payTo"]).lower() == req["payTo"].lower()
    if amount_ok and asset_ok and payto_ok:
        return True, {"settlement": "demo", "network": req["network"],
                      "txHash": declared.get("txHash", "demo-unsettled"),
                      "note": "DEMO mode — no on-chain settlement; set "
                              "X402_FACILITATOR_URL to settle for real."}
    return False, {"reason": "payment terms do not match requirements",
                   "amount_ok": amount_ok, "asset_ok": asset_ok, "payto_ok": payto_ok}


def _facilitator_verify(url: str, payload: dict, req: dict) -> tuple[bool, dict]:
    """Delegate verify+settle to an x402 facilitator (CDP/MPP-compatible)."""
    body = json.dumps({"paymentPayload": payload, "paymentRequirements": req}).encode()
    rq = urlrequest.Request(url.rstrip("/") + "/verify", data=body,
                            headers={"Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(rq, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("isValid") or data.get("valid")), data
    except urlerror.URLError as exc:
        return False, {"reason": f"facilitator unreachable: {exc}"}
