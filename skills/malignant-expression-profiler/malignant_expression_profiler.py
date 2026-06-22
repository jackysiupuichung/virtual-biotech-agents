#!/usr/bin/env python
"""malignant-expression-profiler — a ClawBio skill.

Given a gene and a **tumour** single-cell atlas (with a malignant-cell annotation),
compute whether the target sits on the **malignant compartment** or on stroma/normal
cells: expression in malignant cells vs the rest, the malignant enrichment, and a
tumour-cell-target call. This closes the recurring evidence gap behind tumour-
targeting modalities (esp. ADCs): "is the antigen actually on the cancer cells?"

It is a pure analytic transform — it does not fetch data. Pair it with
`cellxgene-fetch` (a disease-annotated slice, e.g. lung adenocarcinoma / breast
carcinoma) upstream, and `celltype-specificity-profiler` alongside (tau answers
*how cell-type-specific*; this answers *is it on tumour cells*).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Sequence

import numpy as np

SKILL_NAME = "malignant-expression-profiler"
VERSION = "0.1.0"
MALIGNANT_KEYS = ("malign", "neoplas", "tumor", "tumour", "cancer")
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)


# --------------------------------------------------------------------------- #
# Pure function (the analysis) — importable, no I/O
# --------------------------------------------------------------------------- #
def malignant_contrast(expr: Sequence[float], cell_types: Sequence[str],
                       malignant_label: str) -> dict:
    """Contrast a gene's expression in malignant cells vs all other cells.

    Returns malignant/non-malignant stats, the malignant enrichment (ratio of
    mean expression), and a tumour-target call ('favourable' / 'mixed' /
    'liability').
    """
    e = np.asarray(expr, dtype=float)
    ct = np.asarray([str(c) for c in cell_types])
    mal = ct == malignant_label
    rest = ~mal

    def _stats(mask: np.ndarray) -> dict:
        v = e[mask]
        return {
            "n_cells": int(mask.sum()),
            "mean_expr": round(float(v.mean()), 4) if mask.any() else 0.0,
            "pct_expressing": round(float((v > 0).mean()), 4) if mask.any() else 0.0,
        }

    m, r = _stats(mal), _stats(rest)
    # Enrichment = malignant mean / non-malignant mean. None when non-malignant ≈ 0
    # (malignant-exclusive) — avoids an eps-divide artifact.
    if r["mean_expr"] <= 1e-6:
        enrichment = None
        enrich_note = "non-malignant expression ≈ 0 (malignant-exclusive)"
    else:
        enrichment = round(m["mean_expr"] / r["mean_expr"], 3)
        enrich_note = f"malignant mean is {enrichment}× non-malignant"

    mal_pct = m["pct_expressing"]
    if m["n_cells"] == 0:
        call, interp = "undetermined", (
            f"no cells labelled {malignant_label!r} — cannot assess the malignant compartment")
    elif mal_pct < 0.10:
        call, interp = "off-tumour (liability)", (
            "low malignant-cell expression — a direct tumour-targeting modality (e.g. ADC) would "
            "mostly hit stroma/normal, not tumour")
    elif mal_pct >= 0.25 and (enrichment is None or enrichment >= 1.2):
        call, interp = "on-tumour (favourable)", (
            "expressed on the malignant compartment and enriched/exclusive vs non-malignant")
    elif mal_pct >= 0.25 and enrichment is not None and enrichment < 0.8:
        call, interp = "on-tumour with normal-expression risk", (
            "on a substantial fraction of malignant cells, but non-malignant cells express it "
            "comparably or more — on-target/normal toxicity is the key liability (bulk tumour "
            "overexpression / biomarker selection may still enable an ADC)")
    else:
        call, interp = "mixed / partial", (
            "partial malignant-cell expression — confirm tumour-cell fraction and selection biomarker")

    return {
        "malignant_label": malignant_label,
        "malignant": m,
        "non_malignant": r,
        "malignant_enrichment": enrichment,
        "enrichment_note": enrich_note,
        "tumour_target_call": call,
        "interpretation": interp,
    }


def resolve_malignant_label(cell_types: Sequence[str], requested: str | None) -> str | None:
    labels = sorted({str(c) for c in cell_types})
    if requested:
        return requested if requested in labels else None
    for lab in labels:
        if any(k in lab.lower() for k in MALIGNANT_KEYS):
            return lab
    return None


# --------------------------------------------------------------------------- #
# Atlas handling + demo
# --------------------------------------------------------------------------- #
def _resolve_cell_type_key(adata, requested: str | None) -> str:
    if requested and requested in adata.obs:
        return requested
    for c in ("cell_type", "celltype", "cell_type_name", "louvain", "leiden"):
        if c in adata.obs:
            return c
    raise SystemExit(f"no cell-type column in obs ({list(adata.obs.columns)}); pass --cell-type-key")


def _gene_vector(adata, gene: str):
    col = adata[:, gene].X
    if hasattr(col, "toarray"):
        col = col.toarray()
    return np.asarray(col).ravel().astype(float)


def build_demo_adata(n_per: int = 60):
    """Synthetic tumour atlas: malignant + stroma/immune cell types, with a gene on
    the malignant compartment (favourable) and one on stroma (liability)."""
    import anndata as ad
    import pandas as pd

    rng = np.random.default_rng(0)
    cell_types = ["malignant cell", "fibroblast", "endothelial cell", "T cell", "macrophage"]
    genes = ["TUMOR_ANTIGEN", "STROMAL_ANTIGEN", "GENE_X"]
    rows, labels = [], []
    for ct in cell_types:
        for _ in range(n_per):
            v = rng.gamma(0.5, 0.1, size=len(genes))
            v[0] = rng.normal(3.0, 0.3) if ct == "malignant cell" else rng.gamma(0.4, 0.05)
            v[1] = rng.normal(2.5, 0.3) if ct == "fibroblast" else rng.gamma(0.4, 0.05)
            rows.append(np.clip(v, 0.0, None))
            labels.append(ct)
    X = np.asarray(rows)
    obs = pd.DataFrame({"cell_type": labels}, index=[f"c{i}" for i in range(X.shape[0])])
    var = pd.DataFrame(index=genes)
    a = ad.AnnData(X=X, obs=obs, var=var)
    a.uns["atlas_name"] = "synthetic tumour demo (offline, illustrative)"
    return a


def profile(adata, gene: str, cell_type_key: str, malignant_key: str | None) -> dict:
    labels = adata.obs[cell_type_key].astype(str).values
    mal = resolve_malignant_label(labels, malignant_key)
    if mal is None:
        return {
            "skill": SKILL_NAME, "gene": gene,
            "tumour_target_call": "undetermined",
            "interpretation": "no malignant-cell annotation found; provide a tumour slice "
            "or pass --malignant-key",
            "available_cell_types": sorted(set(labels))[:50],
        }
    expr = _gene_vector(adata, gene)
    out = malignant_contrast(expr, labels, mal)
    out["skill"] = SKILL_NAME
    out["gene"] = gene
    out["atlas"] = str(adata.uns.get("atlas_name", "atlas"))
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_report(prof: dict, out_dir, demo: bool):
    from pathlib import Path

    L = [f"# Malignant-cell expression — {prof.get('gene')} ", ""]
    if demo:
        L += ["> **Demo** — synthetic tumour atlas (offline, illustrative).", ""]
    L += [f"- **Tumour-target call:** {prof.get('tumour_target_call')}",
          f"- {prof.get('interpretation','')}", ""]
    if "malignant" in prof:
        m, r = prof["malignant"], prof["non_malignant"]
        L += ["| Compartment | n cells | mean expr | % expressing |",
              "|---|---|---|---|",
              f"| malignant ({prof['malignant_label']}) | {m['n_cells']} | {m['mean_expr']} | {m['pct_expressing']} |",
              f"| non-malignant | {r['n_cells']} | {r['mean_expr']} | {r['pct_expressing']} |",
              "", f"- **Malignant enrichment (mean ratio):** {prof['malignant_enrichment']}", ""]
    L += ["---", f"*{DISCLAIMER}*", ""]
    p = Path(out_dir) / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir, argv, output_files):
    from pathlib import Path
    import platform

    repro_dir = Path(repro_dir)
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\npython malignant_expression_profiler.py " + " ".join(argv) + "\n")
    deps = []
    for mod in ("scanpy", "anndata", "numpy", "pandas"):
        try:
            m = __import__(mod)
            deps.append(f"      - {mod}=={getattr(m, '__version__', 'unknown')}")
        except Exception:
            deps.append(f"      - {mod}")
    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n  - pip\n  - pip:\n"
        + "\n".join(deps) + "\n")
    lines = []
    for f in output_files:
        f = Path(f)
        if f.exists():
            lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (repro_dir / "checksums.sha256").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="malignant_expression_profiler.py",
        description="Profile a gene's expression on malignant cells vs the rest of a tumour atlas.")
    p.add_argument("--gene", type=str, default=None, help="Gene symbol present in the atlas var")
    p.add_argument("--atlas", type=str, default=None, help="Annotated tumour .h5ad (e.g. from cellxgene-fetch)")
    p.add_argument("--cell-type-key", type=str, default="cell_type", help="obs column with cell-type labels")
    p.add_argument("--malignant-key", type=str, default=None,
                   help="exact malignant cell_type label (default: auto-detect)")
    p.add_argument("--demo", action="store_true", help="Run on a synthetic tumour atlas (offline)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    import anndata as ad

    if args.demo:
        adata = build_demo_adata()
        gene = args.gene or "TUMOR_ANTIGEN"
    else:
        if not (args.atlas and args.gene):
            raise SystemExit("--atlas and --gene are required unless --demo")
        if not os.path.exists(args.atlas):
            raise SystemExit(f"atlas not found: {args.atlas}")
        adata = ad.read_h5ad(args.atlas)
        gene = args.gene

    ct_key = _resolve_cell_type_key(adata, args.cell_type_key)
    if gene not in list(adata.var_names):
        raise SystemExit(f"gene {gene!r} not in atlas var index")
    prof = profile(adata, gene, ct_key, args.malignant_key)

    from pathlib import Path
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    mp = out_dir / "malignant_profile.json"
    mp.write_text(json.dumps({**prof, "disclaimer": DISCLAIMER}, indent=2))
    rp = write_report(prof, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [mp, rp])
    print(json.dumps(prof, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
