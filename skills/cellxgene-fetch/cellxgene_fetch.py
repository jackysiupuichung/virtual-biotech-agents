#!/usr/bin/env python
"""cellxgene-fetch — a ClawBio data-acquisition skill.

Fetch a gene × tissue slice of single-cell expression from the CZ CELLxGENE
Census via its **official `cellxgene-census` API** and write an annotated,
log-normalized `.h5ad` ready to feed `scrna-embedding` / `celltype-specificity-
profiler`. This is an API-backed connector — **not web scraping**: results are
versioned (Census release), queryable, and reproducible.

`--demo` builds a small synthetic annotated atlas **offline** (no network, no
`cellxgene-census` dependency), so the chain is testable anywhere. The synthetic
atlas deliberately contains a cell-type-restricted marker (high tau) and a
ubiquitous gene (low tau) so the downstream specificity profiler returns a
meaningful, deterministic result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

SKILL_NAME = "cellxgene-fetch"
VERSION = "0.1.0"
CENSUS_VERSION = "stable"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)

# Genes present in the synthetic --demo atlas (offline, illustrative).
DEMO_GENES = ["MARKER_RESTRICTED", "HOUSEKEEPING_BROAD", "GENE_A", "GENE_B", "GENE_C"]
DEMO_CELL_TYPES = ["T cell", "B cell", "monocyte", "NK cell", "dendritic cell", "fibroblast"]


# --------------------------------------------------------------------------- #
# Demo atlas (offline, deterministic) — no network, no cellxgene-census needed
# --------------------------------------------------------------------------- #
def build_demo_adata(n_per_type: int = 60):
    """Small synthetic annotated atlas with log-normalized, non-negative X.

    `MARKER_RESTRICTED` is expressed (on) only in B cells -> high tau;
    `HOUSEKEEPING_BROAD` is ~uniform across all cell types -> low tau.
    """
    import anndata as ad
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    rows, labels = [], []
    for ct in DEMO_CELL_TYPES:
        for _ in range(n_per_type):
            expr = rng.gamma(shape=0.6, scale=0.15, size=len(DEMO_GENES))  # low baseline
            expr[0] = rng.normal(3.0, 0.3) if ct == "B cell" else rng.gamma(0.4, 0.05)
            expr[1] = rng.normal(2.0, 0.2)  # housekeeping: broad
            rows.append(np.clip(expr, 0.0, None))
            labels.append(ct)
    X = np.asarray(rows, dtype=float)
    obs = pd.DataFrame({"cell_type": labels}, index=[f"cell_{i}" for i in range(X.shape[0])])
    var = pd.DataFrame(index=DEMO_GENES)
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["atlas_name"] = "synthetic demo (cellxgene-fetch --demo; offline, illustrative)"
    adata.uns["cellxgene_fetch"] = {"source": "synthetic-demo", "census_version": None}
    return adata


# --------------------------------------------------------------------------- #
# Live fetch from CELLxGENE Census (official API; lazy import)
# --------------------------------------------------------------------------- #
def fetch_census(genes: Sequence[str], tissue: str | None, organism: str,
                 max_cells: int | None, disease: str | None = None):
    """Fetch a gene × tissue slice from the CELLxGENE Census and log-normalize it.

    Returns an AnnData with `obs['cell_type']` and log-normalized `X`, ready for
    the specificity profiler. Lazy-imports `cellxgene-census` so demo/tests need
    no heavy dependency.
    """
    import cellxgene_census
    import numpy as np
    import scanpy as sc

    obs_filter = "is_primary_data == True"
    if tissue:
        obs_filter += f" and tissue_general == '{tissue}'"
    if disease:
        obs_filter += f" and disease == '{disease}'"
    var_filter = "feature_name in [%s]" % ", ".join(f"'{g}'" for g in genes)

    with cellxgene_census.open_soma(census_version=CENSUS_VERSION) as census:
        # Query-level subsampling: pull only the matching cell IDs first (lightweight),
        # randomly sample, then fetch just those cells. Without this, large tissues
        # (e.g. lung) materialize millions of cells before any cap and exhaust memory.
        obs_coords = None
        if max_cells:
            try:
                ids = cellxgene_census.get_obs(
                    census, organism, value_filter=obs_filter, column_names=["soma_joinid"]
                )["soma_joinid"].to_numpy()
                if ids.size > max_cells:
                    ids = np.sort(
                        np.random.default_rng(0).choice(ids, size=max_cells, replace=False)
                    )
                obs_coords = ids
            except Exception:
                obs_coords = None  # fall back to filter + post-fetch subsample
        common = dict(
            organism=organism,
            X_name="normalized",  # server-side library normalization over ALL genes
            var_value_filter=var_filter,
            obs_column_names=["cell_type", "tissue_general", "assay", "disease"],
        )
        if obs_coords is not None:
            adata = cellxgene_census.get_anndata(census, obs_coords=obs_coords, **common)
        else:
            adata = cellxgene_census.get_anndata(census, obs_value_filter=obs_filter, **common)
    # Census var index is Ensembl ID; expose gene symbols as var_names.
    if "feature_name" in adata.var.columns:
        adata.var_names = adata.var["feature_name"].astype(str)
        adata.var_names_make_unique()
    # X is the Census 'normalized' layer (correct cross-gene library normalization);
    # log1p it for the specificity profiler. Do NOT call normalize_total on this gene
    # slice — renormalizing a single-/few-gene matrix flattens every expressing cell to
    # one value (zero variance), corrupting tau and breaking the bimodality coefficient.
    sc.pp.log1p(adata)
    if max_cells and adata.n_obs > max_cells:
        idx = np.random.default_rng(0).choice(adata.n_obs, size=max_cells, replace=False)
        adata = adata[idx].copy()
    adata.uns["atlas_name"] = (
        f"CELLxGENE Census {CENSUS_VERSION} ({tissue or 'all tissues'}, {organism})"
    )
    adata.uns["cellxgene_fetch"] = {
        "source": "cellxgene-census",
        "census_version": CENSUS_VERSION,
        "tissue": tissue,
        "organism": organism,
        "genes": list(genes),
    }
    return adata


# --------------------------------------------------------------------------- #
# Output contract
# --------------------------------------------------------------------------- #
def _summarize(adata) -> dict:
    cts = sorted(set(adata.obs["cell_type"].astype(str))) if "cell_type" in adata.obs else []
    return {
        "atlas_name": str(adata.uns.get("atlas_name", "")),
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "genes": list(map(str, adata.var_names)),
        "n_cell_types": len(cts),
        "cell_types": cts[:50],
    }


def _write_reproducibility(repro_dir: Path, argv: Sequence[str], output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\n# Command used to produce this atlas slice\n"
        "python cellxgene_fetch.py " + " ".join(argv) + "\n"
    )
    import platform

    deps = []
    for mod in ("anndata", "scanpy", "numpy", "cellxgene-census"):
        try:
            m = __import__(mod.replace("-", "_"))
            deps.append(f"      - {mod}=={getattr(m, '__version__', 'unknown')}")
        except Exception:
            deps.append(f"      - {mod}  # optional (live fetch only)")
    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n  - pip\n  - pip:\n"
        + "\n".join(deps) + "\n"
    )
    lines = []
    for path in output_files:
        path = Path(path)
        if path.exists():
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (repro_dir / "checksums.sha256").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cellxgene_fetch.py",
        description="Fetch an annotated single-cell atlas slice from CELLxGENE Census "
        "(API-backed; feeds scrna-embedding / celltype-specificity-profiler).",
    )
    p.add_argument("--genes", type=str, default=None,
                   help="Comma-separated gene symbols, e.g. TACSTD2,MET,CD276")
    p.add_argument("--gene", type=str, default=None, help="Single gene symbol (alias for --genes)")
    p.add_argument("--tissue", type=str, default=None,
                   help="tissue_general filter (e.g. breast, lung)")
    p.add_argument("--disease", type=str, default=None, help="disease filter (e.g. 'normal')")
    p.add_argument("--organism", type=str, default="Homo sapiens", help="Census organism")
    p.add_argument("--max-cells", type=int, default=20000, help="Cap cells (subsample if exceeded)")
    p.add_argument("--demo", action="store_true",
                   help="Build a small synthetic annotated atlas offline (no network)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        adata = build_demo_adata()
    else:
        genes = []
        if args.genes:
            genes += [g.strip() for g in args.genes.split(",") if g.strip()]
        if args.gene:
            genes.append(args.gene.strip())
        if not genes:
            raise SystemExit("provide --genes/--gene (and usually --tissue), or use --demo")
        adata = fetch_census(genes, args.tissue, args.organism, args.max_cells, args.disease)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    atlas_path = out_dir / "atlas.h5ad"
    adata.write_h5ad(atlas_path)

    summary = _summarize(adata)
    summary["skill"] = SKILL_NAME
    summary["disclaimer"] = DISCLAIMER
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(summary, indent=2))
    _write_reproducibility(out_dir / "reproducibility", argv, [atlas_path, result_path])

    # Hand-off hint for the chain.
    summary["next"] = (
        f"celltype-specificity-profiler --gene <SYMBOL> --atlas {atlas_path}"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
