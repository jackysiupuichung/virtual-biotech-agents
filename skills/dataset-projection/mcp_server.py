#!/usr/bin/env python3
"""mcp_server.py — a local stdio MCP server that projects single-cell data into facts.

This is the one place the raw single-cell matrix enters the agent loop. Per the
projection contract (see facts.py), the ``.h5ad`` itself never leaves the machine
and never goes to Prometheux — the agent calls a tool here, the matrix is read
*in-process*, and only its **conclusion** (which genes are over-expressed in which
cell type, as ``EXPRESSED_IN`` facts) is returned. The agent then binds those
facts alongside PrimeKG for reasoning.

It wraps the existing extractor (``extractors/pbmc3k_expression.py``) so the tool
and the CLI stay one codepath — no logic is duplicated here.

Run standalone for a smoke test::

    .venv/bin/python skills/dataset-projection/mcp_server.py     # serves on stdio

Wired into the loop via ``.mcp.json`` at the repo root.
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "extractors"))

from facts import write_facts  # noqa: E402
import pbmc3k_expression as pbmc  # noqa: E402

mcp = FastMCP("dataset-projection")

# Canonical PBMC lineage markers. A bare call projects THESE, not all ~1,838 genes —
# a bare full projection returns ~64k facts, far too large to hand back into the loop.
# Pass genes="" explicitly to override with the whole matrix (use write_csv for that).
DEFAULT_MARKERS = ["CD3D", "CD8A", "CD4", "CD14", "MS4A1", "NKG7", "FCGR3A",
                   "LYZ", "PPBP", "CST3", "GNLY", "IL7R"]


@mcp.tool()
def project_single_cell_facts(
    min_frac: float = 0.25,
    genes: str = ",".join(DEFAULT_MARKERS),
    h5ad: str = "",
    write_csv: bool = True,
    top_n: int = 50,
) -> dict:
    """Project the single-cell matrix into EXPRESSED_IN facts for the reasoning loop.

    Reads the raw single-cell ``.h5ad`` matrix locally and, for each (gene, cell
    type), computes the expressing fraction + mean expression, emitting a fact only
    above the prevalence floor. The raw matrix is NOT returned or uploaded — only
    the small, joinable set of conclusion facts.

    Args:
        min_frac: prevalence floor in [0,1]; emit a fact only above this expressing
            fraction (also the fact's confidence, which the engine gates on).
        genes: comma-separated gene symbols to restrict to. Defaults to the PBMC
            lineage markers; pass "" to project the whole matrix (~64k facts — only
            sensible with write_csv, since that won't fit back in the loop).
        h5ad: path to the matrix (default: the bundled data/pbmc3k_processed.h5ad).
        write_csv: also write out/pbmc3k_expression.facts.csv (the bind input).
        top_n: cap on facts returned inline (highest-confidence first). The CSV,
            when written, always holds the full projection.

    Returns:
        dict with the projected facts (canonical 7-column schema), the returned and
        total counts, and the output CSV path when written.
    """
    if not 0.0 <= min_frac <= 1.0:
        raise ValueError(f"min_frac must be in [0,1], got {min_frac!r}")

    h5ad_path = Path(h5ad).expanduser() if h5ad else pbmc.DEFAULT_H5AD
    if not h5ad_path.exists():
        raise FileNotFoundError(f"single-cell matrix not found: {h5ad_path}")

    gene_list = [g.strip() for g in genes.split(",") if g.strip()] or None
    facts = pbmc.extract(h5ad_path, min_frac, gene_list)
    facts.sort(key=lambda f: f.confidence, reverse=True)

    returned = facts[:top_n] if top_n and top_n > 0 else facts
    out = {
        "source_dataset": pbmc.DATASET,
        "h5ad": str(h5ad_path),
        "min_frac": min_frac,
        "total_count": len(facts),
        "returned_count": len(returned),
        "truncated": len(returned) < len(facts),
        "facts": [asdict(f) for f in returned],
    }
    if write_csv:
        n = write_facts(facts, pbmc.DEFAULT_OUT)   # CSV gets the FULL projection
        out["csv"] = str(pbmc.DEFAULT_OUT)
        out["csv_rows"] = n
    return out


if __name__ == "__main__":
    mcp.run()
