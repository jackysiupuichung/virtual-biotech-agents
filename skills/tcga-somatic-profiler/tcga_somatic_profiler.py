#!/usr/bin/env python
"""tcga-somatic-profiler — a ClawBio skill.

For a gene, report the **somatic mutation frequency across TCGA cancer types**
from the NCI Genomic Data Commons (GDC): the fraction of each cohort carrying at
least one simple somatic mutation (SSM) in the gene, ranked by frequency. This is
the somatic-driver axis the paper's case studies rest on (B7-H3, MET) and that
single-cell / germline skills don't cover.

API-backed and reproducible (api.gdc.cancer.gov), **not web scraping**. `--demo`
returns a cached real MET response offline.

Note: counts cases with ANY somatic mutation in the gene (not driver-specific);
denominator is the TCGA cohort size per project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "tcga-somatic-profiler"
VERSION = "0.1.0"
GDC = "https://api.gdc.cancer.gov"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)
NOTE = ("Frequency = cases with >=1 simple somatic mutation in the gene / TCGA cohort size "
        "(any SSM, not driver-specific). Source: NCI GDC.")


# --------------------------------------------------------------------------- #
# GDC API (stdlib urllib; POST with JSON body)
# --------------------------------------------------------------------------- #
def _gdc_post(endpoint: str, body: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{GDC}/{endpoint}", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
        return json.loads(resp.read())


def _buckets(payload: dict[str, Any], facet: str) -> dict[str, int]:
    agg = payload.get("data", {}).get("aggregations", {}).get(facet, {})
    return {b["key"]: b["doc_count"] for b in agg.get("buckets", [])}


def fetch_mutation_counts(gene: str) -> dict[str, int]:
    """Cases with >=1 SSM in the gene, per project."""
    body = {"size": 0, "facets": "case.project.project_id",
            "filters": {"op": "in", "content": {
                "field": "ssm.consequence.transcript.gene.symbol", "value": [gene]}}}
    return _buckets(_gdc_post("ssm_occurrences", body), "case.project.project_id")


def fetch_cohort_sizes() -> dict[str, int]:
    """Total cases per project (cohort denominator)."""
    return _buckets(_gdc_post("cases", {"size": 0, "facets": "project.project_id"}),
                    "project.project_id")


def somatic_frequencies(gene: str, top: int = 10) -> dict[str, Any]:
    counts = fetch_mutation_counts(gene)
    sizes = fetch_cohort_sizes()
    rows = []
    for proj, n in counts.items():
        if not proj.startswith("TCGA"):
            continue
        total = sizes.get(proj)
        if not total:
            continue
        rows.append({"cancer_type": proj, "mutated_cases": n, "cohort": total,
                     "frequency_pct": round(100.0 * n / total, 2)})
    rows.sort(key=lambda r: r["frequency_pct"], reverse=True)
    return {"gene": gene, "n_tcga_types": len(rows), "top_cancer_types": rows[:top]}


# --------------------------------------------------------------------------- #
# Demo (offline; cached real MET response)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    return {
        "gene": "MET", "n_tcga_types": 32,
        "top_cancer_types": [
            {"cancer_type": "TCGA-UCEC", "mutated_cases": 90, "cohort": 560, "frequency_pct": 16.07},
            {"cancer_type": "TCGA-SKCM", "mutated_cases": 65, "cohort": 470, "frequency_pct": 13.83},
            {"cancer_type": "TCGA-KIRP", "mutated_cases": 21, "cohort": 291, "frequency_pct": 7.22},
            {"cancer_type": "TCGA-COAD", "mutated_cases": 27, "cohort": 461, "frequency_pct": 5.86},
            {"cancer_type": "TCGA-BLCA", "mutated_cases": 23, "cohort": 412, "frequency_pct": 5.58},
            {"cancer_type": "TCGA-LUAD", "mutated_cases": 24, "cohort": 585, "frequency_pct": 4.10},
        ],
        "_demo": True,
    }


def interpret(prof: dict[str, Any]) -> dict[str, Any]:
    top = prof.get("top_cancer_types", [])
    if not top:
        return {"call": "no somatic signal", "interpretation": "no TCGA somatic mutations found — likely an expression target, not a mutation driver"}
    hi = top[0]
    maxf = hi["frequency_pct"]
    call = ("recurrent somatic driver" if maxf >= 10 else
            "moderate somatic frequency" if maxf >= 3 else
            "low somatic frequency (likely expression target)")
    return {"call": call,
            "interpretation": f"top: {hi['cancer_type']} {maxf}% ({hi['mutated_cases']}/{hi['cohort']}); {call}"}


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_report(prof: dict[str, Any], interp: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# TCGA somatic frequency — {prof.get('gene')}", ""]
    if demo:
        L += ["> **Demo** — cached real GDC response for MET, offline.", ""]
    L += [f"> {NOTE}", "", f"- **Call:** {interp['call']}", f"- {interp['interpretation']}", "",
          "## Somatic mutation frequency by TCGA cancer type", "",
          "| Cancer type | Mutated | Cohort | Frequency |", "|---|---|---|---|"]
    for r in prof.get("top_cancer_types", []):
        L.append(f"| {r['cancer_type']} | {r['mutated_cases']} | {r['cohort']} | {r['frequency_pct']}% |")
    if not prof.get("top_cancer_types"):
        L.append("| (no somatic mutations in TCGA) | — | — | — |")
    L += ["", "---", f"*{DISCLAIMER}*", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\npython tcga_somatic_profiler.py " + " ".join(argv) + "\n")
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # NCI GDC via stdlib urllib; no extra packages required\n")
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
        prog="tcga_somatic_profiler.py",
        description="Somatic mutation frequency of a gene across TCGA cancer types (GDC).")
    p.add_argument("--gene", type=str, default=None, help="Gene symbol, e.g. MET")
    p.add_argument("--top", type=int, default=10, help="Top-N cancer types by frequency")
    p.add_argument("--demo", action="store_true", help="Offline cached MET response")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        prof = build_demo()
    elif args.gene:
        prof = somatic_frequencies(args.gene, args.top)
    else:
        raise SystemExit("provide --gene, or use --demo")

    interp = interpret(prof)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = out_dir / "somatic.json"
    sp.write_text(json.dumps({"skill": SKILL_NAME, "version": VERSION, "demo": bool(args.demo),
                              "note": NOTE, **prof, **interp, "disclaimer": DISCLAIMER}, indent=2))
    rp = write_report(prof, interp, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [sp, rp])
    print(json.dumps({"skill": SKILL_NAME, "gene": prof.get("gene"), "call": interp["call"],
                      "top": [(r["cancer_type"], r["frequency_pct"]) for r in prof.get("top_cancer_types", [])[:5]]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
