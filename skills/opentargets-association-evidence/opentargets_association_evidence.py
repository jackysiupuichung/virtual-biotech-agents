#!/usr/bin/env python
"""opentargets-association-evidence — a ClawBio skill.

For a **(target, disease) pair**, fetch the Open Targets association and its
**evidence breakdown by datatype** — genetic association, somatic mutation, known
drug, affected pathway, RNA expression, animal model, literature — in one GraphQL
call. This is the target↔disease *linkage* evidence (which kinds of evidence link
the two entities, and how strongly), distinct from the target-level factors in
`opentargets-target-factors`.

API-backed and reproducible (Open Targets Platform GraphQL), **not web scraping**.
`--demo` returns a cached real response (CD276 × lung carcinoma) offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "opentargets-association-evidence"
VERSION = "0.1.0"
OT_GRAPHQL = "https://api.platform.opentargets.org/api/v4/graphql"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)
# Open Targets evidence datatypes (for a complete, ordered breakdown).
DATATYPES = [
    "genetic_association", "somatic_mutation", "known_drug", "affected_pathway",
    "rna_expression", "animal_model", "literature",
]


# --------------------------------------------------------------------------- #
# Open Targets API (stdlib urllib)
# --------------------------------------------------------------------------- #
def _ot_query(query: str, timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(
        OT_GRAPHQL, data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
        payload = json.loads(resp.read())
    if payload.get("errors"):
        raise RuntimeError(f"Open Targets GraphQL error: {payload['errors'][:1]}")
    return payload["data"]


def _resolve(entity: str, query_string: str) -> tuple[str, str]:
    """Resolve a free-text name to an OT id for entity in {'target','disease'}."""
    q = '{search(queryString:"%s", entityNames:["%s"]){hits{id name entity}}}' % (
        query_string, entity)
    hits = [h for h in _ot_query(q)["search"]["hits"] if h.get("entity") == entity]
    if not hits:
        raise SystemExit(f"Open Targets: no {entity} found for {query_string!r}")
    for h in hits:
        if str(h.get("name", "")).lower() == query_string.lower():
            return h["id"], h["name"]
    return hits[0]["id"], hits[0]["name"]


def fetch_association(ensembl_id: str, efo_id: str) -> dict[str, Any]:
    q = ('{target(ensemblId:"%s"){approvedSymbol associatedDiseases(Bs:["%s"]){rows{'
         "disease{id name} score datatypeScores{id score}}}}}" % (ensembl_id, efo_id))
    t = _ot_query(q)["target"]
    rows = (t.get("associatedDiseases") or {}).get("rows", []) if t else []
    row = rows[0] if rows else None
    return {
        "symbol": t.get("approvedSymbol") if t else None,
        "ensembl_id": ensembl_id,
        "efo_id": efo_id,
        "disease": (row["disease"]["name"] if row else None),
        "overall_score": (round(row["score"], 4) if row else 0.0),
        "datatype_scores": ({d["id"]: round(d["score"], 4) for d in row["datatypeScores"]}
                            if row else {}),
    }


# --------------------------------------------------------------------------- #
# Demo (offline; cached real CD276 × lung carcinoma)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    return {
        "symbol": "CD276", "ensembl_id": "ENSG00000103855",
        "efo_id": "EFO_0001071", "disease": "lung carcinoma",
        "overall_score": 0.005,
        "datatype_scores": {"literature": 0.0424},
        "_demo": True,
    }


def interpret(assoc: dict[str, Any]) -> dict[str, Any]:
    s = assoc.get("overall_score", 0.0)
    band = ("strong" if s >= 0.5 else "moderate" if s >= 0.1 else
            "weak" if s > 0 else "no association")
    present = [dt for dt in DATATYPES if dt in assoc.get("datatype_scores", {})]
    drivers = sorted(assoc.get("datatype_scores", {}).items(), key=lambda kv: -kv[1])
    note = (f"association is {band} (score {s}); "
            + (f"driven by {', '.join(k for k, _ in drivers[:3])}" if drivers
               else "no datatype evidence in Open Targets for this pair"))
    if present == ["literature"]:
        note += " — literature-only (no genetic/somatic/known-drug evidence; OT may undersell a somatic/expression-driven target)"
    return {"strength": band, "evidence_datatypes_present": present, "interpretation": note}


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_report(assoc: dict[str, Any], interp: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# Target–Disease Association — {assoc.get('symbol')} × {assoc.get('disease')}", ""]
    if demo:
        L += ["> **Demo** — cached real Open Targets response (CD276 × lung carcinoma), offline.", ""]
    L += [f"- **Overall association score:** {assoc.get('overall_score')} ({interp['strength']})",
          f"- {interp['interpretation']}", "",
          "## Evidence by datatype", "", "| Datatype | Score |", "|---|---|"]
    ds = assoc.get("datatype_scores", {})
    for dt in DATATYPES:
        if dt in ds:
            L.append(f"| {dt} | {ds[dt]} |")
    if not ds:
        L.append("| (no datatype evidence) | — |")
    L += ["", "---", f"*{DISCLAIMER}*", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\npython opentargets_association_evidence.py " + " ".join(argv) + "\n")
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # Open Targets via stdlib urllib; no extra packages required\n")
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
        prog="opentargets_association_evidence.py",
        description="Open Targets target–disease association evidence breakdown by datatype.")
    p.add_argument("--gene", type=str, default=None, help="Gene symbol, e.g. CD276")
    p.add_argument("--ensembl-id", type=str, default=None, help="Ensembl gene ID")
    p.add_argument("--disease", type=str, default=None, help="Disease name, e.g. 'lung carcinoma'")
    p.add_argument("--efo-id", type=str, default=None, help="EFO/MONDO disease id, e.g. EFO_0001071")
    p.add_argument("--demo", action="store_true", help="Offline cached CD276 × lung carcinoma")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        assoc = build_demo()
    else:
        if not (args.gene or args.ensembl_id) or not (args.disease or args.efo_id):
            raise SystemExit("provide --gene/--ensembl-id AND --disease/--efo-id, or --demo")
        tid = args.ensembl_id or _resolve("target", args.gene)[0]
        did = args.efo_id or _resolve("disease", args.disease)[0]
        assoc = fetch_association(tid, did)

    interp = interpret(assoc)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ap = out_dir / "association.json"
    ap.write_text(json.dumps({"skill": SKILL_NAME, "version": VERSION, "demo": bool(args.demo),
                              **assoc, **interp, "disclaimer": DISCLAIMER}, indent=2))
    rp = write_report(assoc, interp, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [ap, rp])
    print(json.dumps({"skill": SKILL_NAME, "symbol": assoc.get("symbol"),
                      "disease": assoc.get("disease"), "overall_score": assoc.get("overall_score"),
                      "strength": interp["strength"],
                      "datatypes": interp["evidence_datatypes_present"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
