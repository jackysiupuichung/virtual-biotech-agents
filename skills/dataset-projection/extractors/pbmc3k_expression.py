#!/usr/bin/env python3
"""pbmc3k_expression.py — project a single-cell matrix into expression facts.

The worked example of the projection contract on a **real downloaded dataset**
(``data/pbmc3k_processed.h5ad`` — 2638 cells x 1838 genes, louvain cell-type
labels). It is the archetype for the "raw experimental matrix" case: the matrix
itself must NOT go to Prometheux, but its *conclusion* — which genes are
over-expressed in which cell type — projects cleanly into ``EXPRESSED_IN`` facts.

For each (gene, cell type) we compute the fraction of cells in that type that
express the gene and the mean expression among expressers, then emit a fact when
the gene is meaningfully present. ``confidence`` is the expressing fraction, so it
plugs straight into the engine's STRONG_CONF=0.8 gate. Only genes above a small
prevalence floor are emitted — the matrix has ~5M cells x genes, but the *facts*
worth reasoning over are a small, joinable set.

    python3 pbmc3k_expression.py              # writes ../out/pbmc3k_expression.facts.csv
    python3 pbmc3k_expression.py --min-frac 0.5 --genes CD8A,MS4A1,CD14
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from facts import Fact, node_id, write_facts  # noqa: E402

DATASET = "pbmc3k"
DEFAULT_H5AD = Path(__file__).resolve().parents[3] / "data" / "pbmc3k_processed.h5ad"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "out" / "pbmc3k_expression.facts.csv"


def extract(h5ad: Path, min_frac: float, genes: list[str] | None) -> list[Fact]:
    import scanpy as sc  # heavy optional dep; only needed at extraction time

    a = sc.read_h5ad(h5ad)
    if "louvain" not in a.obs:
        raise SystemExit("expected a 'louvain' cell-type label column in obs")
    X = a.raw.X if a.raw is not None else a.X            # raw counts/expr
    var_names = list(a.raw.var_names if a.raw is not None else a.var_names)
    name_to_col = {g: i for i, g in enumerate(var_names)}

    wanted = [g for g in (genes or var_names) if g in name_to_col]
    facts: list[Fact] = []
    for ct in map(str, a.obs["louvain"].cat.categories):
        mask = (a.obs["louvain"].astype(str) == ct).to_numpy()
        n_cells = int(mask.sum())
        if not n_cells:
            continue
        sub = X[mask]
        sub = sub.toarray() if hasattr(sub, "toarray") else np.asarray(sub)
        for g in wanted:
            col = sub[:, name_to_col[g]]
            expressing = col > 0
            frac = float(expressing.mean())
            if frac < min_frac:
                continue
            mean_expr = float(col[expressing].mean()) if expressing.any() else 0.0
            facts.append(Fact(
                subject=node_id("gene", g),
                relation="EXPRESSED_IN",
                object=node_id("celltype", ct),
                value=f"{frac*100:.0f}% expressing · mean {mean_expr:.1f} (n={n_cells})",
                confidence=round(frac, 3),
                source_dataset=DATASET,
                provenance=f"{h5ad.name}#louvain={ct};gene={g}",
            ))
    return facts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--h5ad", type=Path, default=DEFAULT_H5AD)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--min-frac", type=float, default=0.25,
                   help="prevalence floor: emit a fact only above this expressing fraction")
    p.add_argument("--genes", default="",
                   help="comma-separated gene symbols (default: all genes in the matrix)")
    args = p.parse_args(argv)

    genes = [g.strip() for g in args.genes.split(",") if g.strip()] or None
    facts = extract(args.h5ad, args.min_frac, genes)
    n = write_facts(facts, args.out)
    print(f"projected {n} expression facts from {args.h5ad.name} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
