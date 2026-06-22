#!/usr/bin/env python
"""opentargets-target-factors — a ClawBio data-acquisition skill.

For one target, fetch the Open Targets **prioritisation factors**, **tractability**,
and **safety liabilities** in a single GraphQL call, and map them to the Virtual-
Biotech divisions they inform:

  - Functional genomics  → geneEssentiality (DepMap-derived)
  - Modality selection   → tractability (ligand/pocket/small-molecule binder),
                           maxClinicalStage, membrane/secreted localisation
  - Target safety        → geneticConstraint, mouseKOScore, tissueSpecificity,
                           tissueDistribution, safetyLiabilities

API-backed and reproducible (Open Targets Platform GraphQL), **not web scraping**.
`--demo` returns a cached real OT response for CD276 offline (no network).

Prioritisation factor values run roughly −1 (unfavourable for a target) … +1
(favourable). They are *target-level* and *bulk/tissue-level* — complementary to,
not a substitute for, the single-cell cell-type specificity from
`celltype-specificity-profiler`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "opentargets-target-factors"
VERSION = "0.1.0"
OT_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)

# Which Virtual-Biotech division each prioritisation key informs.
FACTOR_DIVISION = {
    "geneEssentiality": "functional_genomics (DepMap)",
    "hasLigand": "modality",
    "hasPocket": "modality",
    "hasSmallMoleculeBinder": "modality",
    "isInMembrane": "modality",
    "isSecreted": "modality",
    "maxClinicalStage": "clinical/modality",
    "geneticConstraint": "target_safety",
    "mouseKOScore": "target_safety",
    "mouseOrthologMaxIdentityPercentage": "target_safety",
    "paralogMaxIdentityPercentage": "target_safety",
    "tissueSpecificity": "target_safety (bulk tissue)",
    "tissueDistribution": "target_safety (bulk tissue)",
}


# --------------------------------------------------------------------------- #
# Open Targets API (stdlib urllib — no extra dependency)
# --------------------------------------------------------------------------- #
def _ot_query(query: str, timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(
        OT_GRAPHQL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
        payload = json.loads(resp.read())
    if "errors" in payload and payload["errors"]:
        raise RuntimeError(f"Open Targets GraphQL error: {payload['errors'][:1]}")
    return payload["data"]


def resolve_ensembl_id(gene: str) -> str:
    """Resolve a gene symbol to an Ensembl gene ID via the OT search endpoint."""
    q = (
        '{search(queryString:"%s", entityNames:["target"]){hits{id entity name}}}'
        % gene
    )
    hits = _ot_query(q)["search"]["hits"]
    targets = [h for h in hits if h.get("entity") == "target"]
    if not targets:
        raise SystemExit(f"Open Targets: no target found for {gene!r}")
    for h in targets:  # prefer an exact symbol match
        if str(h.get("name", "")).upper() == gene.upper():
            return h["id"]
    return targets[0]["id"]


def fetch_target_factors(ensembl_id: str) -> dict[str, Any]:
    """Fetch prioritisation + tractability + safety liabilities for one target."""
    q = (
        '{target(ensemblId:"%s"){id approvedSymbol biotype '
        "prioritisation{items{key value}} "
        "tractability{modality label value} "
        "safetyLiabilities{event datasource}}}" % ensembl_id
    )
    t = _ot_query(q)["target"]
    if t is None:
        raise SystemExit(f"Open Targets: no target record for {ensembl_id!r}")
    return t


# --------------------------------------------------------------------------- #
# Demo (offline; cached real OT response for CD276 / B7-H3)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    """Cached real Open Targets response for CD276 (offline; no network)."""
    return {
        "id": "ENSG00000103855",
        "approvedSymbol": "CD276",
        "biotype": "protein_coding",
        "prioritisation": {"items": [
            {"key": "geneticConstraint", "value": "-0.14"},
            {"key": "hasLigand", "value": "0"},
            {"key": "hasPocket", "value": "0"},
            {"key": "hasSmallMoleculeBinder", "value": "0"},
            {"key": "isInMembrane", "value": "0"},
            {"key": "isSecreted", "value": "0"},
            {"key": "maxClinicalStage", "value": "0.5"},
            {"key": "mouseKOScore", "value": "-0.19"},
            {"key": "tissueSpecificity", "value": "-1"},
            {"key": "geneEssentiality", "value": "0"},
        ]},
        "tractability": [
            {"modality": "AB", "label": "Advanced Clinical", "value": True},
            {"modality": "SM", "label": "Has Pocket", "value": False},
        ],
        "safetyLiabilities": [],
        "_demo": True,
    }


# --------------------------------------------------------------------------- #
# Interpret → division-mapped factors
# --------------------------------------------------------------------------- #
def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def map_factors(target: dict[str, Any]) -> dict[str, Any]:
    """Group OT factors by the Virtual-Biotech division they inform."""
    items = (target.get("prioritisation") or {}).get("items", []) or []
    factors = []
    for it in items:
        factors.append({
            "key": it["key"],
            "value": _to_float(it.get("value")),
            "division": FACTOR_DIVISION.get(it["key"], "other"),
        })
    tract = [t for t in (target.get("tractability") or []) if t.get("value")]
    return {
        "ensembl_id": target.get("id"),
        "symbol": target.get("approvedSymbol"),
        "biotype": target.get("biotype"),
        "prioritisation_factors": factors,
        "tractability_positive": tract,
        "safety_liabilities": target.get("safetyLiabilities") or [],
    }


def write_report(mapped: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# Open Targets Target Factors — {mapped['symbol']} ({mapped['ensembl_id']})", ""]
    if demo:
        L.append("> **Demo:** cached real Open Targets response for CD276 (offline). Not a live query.")
        L.append("")
    L.append("Prioritisation factors run −1 (unfavourable) … +1 (favourable); they are "
             "*target/bulk-tissue level* — complementary to single-cell cell-type specificity.")
    L += ["", "## Prioritisation factors by division", "",
          "| Factor | Value | Division |", "|---|---|---|"]
    for f in mapped["prioritisation_factors"]:
        L.append(f"| {f['key']} | {f['value']} | {f['division']} |")
    L += ["", "## Tractability (positive)", ""]
    for t in mapped["tractability_positive"]:
        L.append(f"- {t['modality']}: {t['label']}")
    if not mapped["tractability_positive"]:
        L.append("- none reported")
    L += ["", "## Safety liabilities", ""]
    for s in mapped["safety_liabilities"]:
        L.append(f"- {s.get('event')} ({s.get('datasource')})")
    if not mapped["safety_liabilities"]:
        L.append("- none reported in Open Targets")
    L += ["", "---", f"*{DISCLAIMER}*", ""]
    path = out_dir / "report.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\n# Command used to produce these factors\n"
        "python opentargets_target_factors.py " + " ".join(argv) + "\n"
    )
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # network via stdlib urllib; no extra packages required\n"
    )
    lines = []
    for p in output_files:
        p = Path(p)
        if p.exists():
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (repro_dir / "checksums.sha256").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="opentargets_target_factors.py",
        description="Fetch Open Targets prioritisation factors + tractability + safety "
        "for a target (Functional / Modality / Safety divisions in one call).",
    )
    p.add_argument("--gene", type=str, default=None, help="Gene symbol, e.g. CD276")
    p.add_argument("--ensembl-id", type=str, default=None, help="Ensembl gene ID, e.g. ENSG00000103855")
    p.add_argument("--demo", action="store_true", help="Offline cached CD276 response (no network)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        target = build_demo()
    elif args.ensembl_id:
        target = fetch_target_factors(args.ensembl_id)
    elif args.gene:
        target = fetch_target_factors(resolve_ensembl_id(args.gene))
    else:
        raise SystemExit("provide --gene or --ensembl-id, or use --demo")

    mapped = map_factors(target)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    factors_path = out_dir / "factors.json"
    factors_path.write_text(json.dumps({"skill": SKILL_NAME, "version": VERSION,
                                        "demo": bool(args.demo), **mapped,
                                        "disclaimer": DISCLAIMER}, indent=2))
    report_path = write_report(mapped, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [factors_path, report_path])

    print(json.dumps({"skill": SKILL_NAME, "symbol": mapped["symbol"],
                      "ensembl_id": mapped["ensembl_id"],
                      "n_factors": len(mapped["prioritisation_factors"]),
                      "tractability": [t["label"] for t in mapped["tractability_positive"]],
                      "factors": factors_path.name, "report": report_path.name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
