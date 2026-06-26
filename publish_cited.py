#!/usr/bin/env python3
"""publish_cited.py — publish the CSO agent's report as a cited, monetizable artifact.

Two jobs:

1. **Publish** the latest ``report.md`` the multi-agent loop produced into
   ``cited.md`` at the repo root, rewriting the trailing "References & data
   sources" block so every numbered ``[n]`` ref resolves to a real source URL
   (skill registry + any deep-link the step carried). The body is unchanged;
   only citations are normalized and a canonical front-matter header is stamped.

2. **Mint a payment manifest** (``cited.payment.json``) describing how an agent
   pays to fetch the full artifact over agent payment rails — x402 (HTTP 402),
   plus MPP / CDP / agentic.market listing metadata. ``server.py`` reads this
   manifest to enforce the 402 gate on ``/api/report``.

Run:  python3 publish_cited.py            # publish from the newest output/report.md
      python3 publish_cited.py --report path/to/report.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILL_OUT = ROOT / "skills" / "virtual-biotech-cso" / "output"

# Canonical source URL per leaf skill — used to backfill a citation that the
# report emitted without a deep link, so every [n] resolves to *something* real.
SKILL_SOURCE = {
    "gwas-lookup": ("GWAS Catalog / Open Targets", "https://www.ebi.ac.uk/gwas/"),
    "gwas": ("GWAS Catalog / Open Targets", "https://www.ebi.ac.uk/gwas/"),
    "scrna-embedding": ("CELLxGENE single-cell atlas", "https://cellxgene.cziscience.com/"),
    "scrna-orchestrator": ("CELLxGENE / Tabula Sapiens", "https://cellxgene.cziscience.com/"),
    "celltype-specificity-profiler": ("Derived (tau + bimodality)", "https://cellxgene.cziscience.com/"),
    "clinical-trial-finder": ("ClinicalTrials.gov", "https://clinicaltrials.gov/"),
    "opentargets-association-evidence": ("Open Targets Platform", "https://platform.opentargets.org/"),
}

_URL_RE = re.compile(r"https?://[^\s)]+")
_REF_LINE_RE = re.compile(r"^\s*(\d+)\.\s+\*\*(?P<skill>[^*]+)\*\*\s*(?P<rest>.*)$")


def _latest_report() -> Path:
    """The assembled report of record.

    Prefer the top-level ``output/report.md`` (the multi-agent loop's final
    assembled CSO assessment). Only fall back to the newest per-run leaf report
    if the top-level one is absent — a leaf report (e.g. a single GWAS lookup)
    is an input to the assessment, not the published artifact.
    """
    top = SKILL_OUT / "report.md"
    if top.exists():
        return top
    leaves = sorted(SKILL_OUT.glob("*/report.md"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not leaves:
        raise SystemExit(f"no report.md found under {SKILL_OUT}")
    return leaves[0]


def _normalize_references(body: str) -> tuple[str, list[dict]]:
    """Rewrite the References block so each [n] carries a resolvable URL.

    Returns the rewritten body and a structured citation list (for the manifest).
    Lines already carrying a URL keep it; lines without one get the skill's
    canonical source URL backfilled.
    """
    lines = body.splitlines()
    out: list[str] = []
    citations: list[dict] = []
    in_refs = False
    for line in lines:
        if line.strip().startswith("## References"):
            in_refs = True
            out.append(line)
            continue
        if in_refs and line.startswith("## "):  # next section ends the block
            in_refs = False
        m = _REF_LINE_RE.match(line) if in_refs else None
        if not m:
            out.append(line)
            continue
        n = int(m.group(1))
        skill = m.group("skill").strip()
        rest = m.group("rest")
        url_m = _URL_RE.search(rest)
        if url_m:
            url, source = url_m.group(0), rest
        else:
            source, url = SKILL_SOURCE.get(skill, (skill, ""))
            if url:  # append a resolvable link the report omitted
                line = f"{line.rstrip()} — {url}"
        citations.append({"n": n, "skill": skill, "url": url_m.group(0) if url_m else url})
        out.append(line)
    return "\n".join(out) + ("\n" if body.endswith("\n") else ""), citations


HEADER = """\
---
title: {title}
decision: {decision}
published_by: Virtual-Biotech CSO (multi-agent loop)
access: paid
payment_manifest: cited.payment.json
---

> 🔓 **Paywalled artifact.** This report is published behind agent payment rails.
> Agents fetch the full text by paying over **x402** (HTTP 402) — see
> [`cited.payment.json`](cited.payment.json) for the price, pay-to address, and
> the MPP / CDP / agentic.market listings. The text below is the published copy
> of record; the live gate is enforced by `server.py` at `GET /api/report`.

"""


def publish(report_path: Path) -> dict:
    raw = report_path.read_text(encoding="utf-8")
    title_m = re.search(r"^#\s+(.+)$", raw, re.M)
    title = title_m.group(1).strip() if title_m else "Target Assessment"
    decision_m = re.search(r"\*\*Decision:\*\*\s*([A-Z_]+)", raw)
    decision = decision_m.group(1) if decision_m else "UNKNOWN"

    body, citations = _normalize_references(raw)
    cited = HEADER.format(title=title, decision=decision) + body
    (ROOT / "cited.md").write_text(cited, encoding="utf-8")
    return {"title": title, "decision": decision, "citations": citations,
            "source_report": str(report_path.relative_to(ROOT))}


# ---- payment manifest (the monetization side) ---------------------------- #

# Pay-to address: overridable via env in server.py; this is the published default.
PAY_TO = "0x000000000000000000000000000000000000dEaD"
PRICE_USDC = "0.50"  # one full-report fetch


def mint_manifest(meta: dict) -> dict:
    manifest = {
        "asset": "cited.md",
        "title": meta["title"],
        "decision": meta["decision"],
        "description": "Full Virtual-Biotech CSO target-assessment report with cited evidence.",
        "price": {"amount": PRICE_USDC, "currency": "USDC", "network": "base"},
        "rails": {
            # x402 — the primary rail: an HTTP 402 on GET /api/report, settled
            # per-fetch. server.py serves this accepts block in the 402 body.
            "x402": {
                "version": 1,
                "scheme": "exact",
                "network": "base",
                "maxAmountRequired": PRICE_USDC,
                "asset": "USDC",
                "payTo": PAY_TO,
                "resource": "/api/report",
                "description": "Pay-per-fetch for the full cited report.",
            },
            # MPP — Machine Payment Protocol listing (discovery + settlement).
            "mpp": {"listing": "vbcso/cited-report", "payTo": PAY_TO,
                    "price": PRICE_USDC, "currency": "USDC"},
            # CDP — Coinbase Developer Platform wallet that receives settlement.
            "cdp": {"network": "base", "receiver": PAY_TO, "token": "USDC"},
            # agentic.market — public marketplace listing for agent discovery.
            "agentic_market": {
                "listing_url": "https://agentic.market/listings/vbcso-cited-report",
                "seller": "virtual-biotech-cso",
                "price": PRICE_USDC, "currency": "USDC",
            },
        },
        "citations": meta["citations"],
        "source_report": meta["source_report"],
    }
    (ROOT / "cited.payment.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, default=None,
                    help="report.md to publish (default: newest under output/)")
    args = ap.parse_args()
    report = args.report or _latest_report()
    meta = publish(report)
    manifest = mint_manifest(meta)
    print(f"published  cited.md            from {meta['source_report']}")
    print(f"minted     cited.payment.json  ({len(meta['citations'])} citations, "
          f"price {manifest['price']['amount']} {manifest['price']['currency']})")
    print(f"decision:  {meta['decision']}")


if __name__ == "__main__":
    main()
