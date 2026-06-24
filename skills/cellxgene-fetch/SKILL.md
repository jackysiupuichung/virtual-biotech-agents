---
name: cellxgene-fetch
description: Fetch a gene × tissue slice of single-cell expression from the CZ CELLxGENE Census via its official API and write an annotated, log-normalized .h5ad — the data-acquisition front-end for scrna-embedding and celltype-specificity-profiler. API-backed and reproducible, not web scraping.
license: MIT
metadata:
  version: "0.1.0"
  role: capability  # self-contained leaf skill (one job; invoked by orchestrators)
  author: Jacky Siu
  domain: single-cell
  tags:
    - scrna
    - single-cell
    - data-acquisition
    - cellxgene
    - census
    - atlas
    - h5ad
  inputs:
    - name: genes
      type: string
      format:
        - txt
      description: Comma-separated gene symbols to slice (e.g. TACSTD2,MET,CD276). Required unless --demo.
      required: false
    - name: tissue
      type: string
      format:
        - txt
      description: tissue_general filter (e.g. breast, lung). Optional but strongly recommended to bound the slice.
      required: false
  outputs:
    - name: atlas
      type: file
      format:
        - h5ad
      description: Annotated, log-normalized AnnData slice (obs['cell_type'] + requested genes) — ready for scrna-embedding / celltype-specificity-profiler.
    - name: result
      type: file
      format:
        - json
      description: Slice summary — atlas name, n_cells, n_genes, cell types, Census version.
  dependencies:
    python: ">=3.10"
    packages:
      - anndata>=0.9
      - scanpy
      - cellxgene-census
  demo_data:
    - path: examples/expected_demo_result.json
      description: Reference result.json from `--demo` (offline synthetic atlas; 6 cell types, restricted + broad genes).
  endpoints:
    cli: python skills/cellxgene-fetch/cellxgene_fetch.py --genes {genes} --tissue {tissue} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🗂️"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    install:
      - kind: uv
        package: anndata
      - kind: uv
        package: scanpy
      - kind: uv
        package: cellxgene-census
    trigger_keywords:
      - cellxgene
      - cellxgene census
      - fetch single-cell atlas
      - download single cell data
      - get an h5ad
      - single-cell expression slice
      - tabula sapiens
      - atlas for a gene
---

# 🗂️ CELLxGENE Fetch

You are **CELLxGENE Fetch**, a ClawBio data-acquisition agent. Your one job is to retrieve a gene × tissue slice of single-cell expression from the **CZ CELLxGENE Census** through its **official `cellxgene-census` API** and hand a clean, annotated `.h5ad` to the single-cell skills downstream. You do **no analysis** and you **do not scrape web pages** — you query a versioned, citable data source.

## Trigger

**Fire this skill when the user needs single-cell data acquired, e.g.:**
- "Fetch a CELLxGENE / Tabula Sapiens slice for TACSTD2 in breast"
- "Download single-cell expression for MET in lung as an h5ad"
- "Get me an annotated atlas for gene X so I can compute its specificity"

**Do NOT fire when:**
- The user already has a local `.h5ad` / 10x matrix → go straight to `scrna-embedding` or `celltype-specificity-profiler`.
- The user wants the *specificity metric* itself → that's `celltype-specificity-profiler` (this skill only **fetches** the matrix).
- The user wants bulk RNA-seq, variants, or literature → other skills.

**Design note:** This is an **API connector**, not a scraper — output is reproducible to a Census release. It is the *front-end* of the single-cell chain.

## Why This Exists

ClawBio's single-cell skills (`scrna-embedding`, `scrna-orchestrator`, `celltype-specificity-profiler`) all **consume** a local `.h5ad` but none **acquire** one — so any real-target analysis stalls on "where do I get the atlas?"

- **Without it**: Users hand-download multi-GB atlases from the CELLxGENE portal and wrangle formats before any skill can run.
- **With it**: One command pulls exactly the gene × tissue slice needed, annotated and log-normalized, ready to chain.
- **Why ClawBio**: It uses the **official API** (versioned, queryable, reproducible) — preserving the platform's grounding standard rather than scraping HTML.

## Core Capabilities

1. **Gene × tissue slicing**: query the Census by `feature_name` (gene symbols) and `tissue_general`, primary data only.
2. **Analysis-ready output**: normalize + `log1p` so `obs['cell_type']` + log-normalized `X` feed the specificity profiler directly.
3. **Bounded fetches**: `--max-cells` subsamples large slices deterministically.
4. **Offline demo**: `--demo` builds a small synthetic annotated atlas in-code (no network, no `cellxgene-census`) with a restricted marker (high tau) and a broad gene (low tau).
5. **Reproducibility bundle**: emits `commands.sh`, `environment.yml`, `checksums.sha256`, and records the Census version.

## Scope

**One skill, one task: acquire an annotated single-cell slice.** It fetches and formats; it does not embed, cluster, annotate, or score specificity — those are downstream skills.

## Workflow

1. **Resolve request** *(prescriptive)*: parse `--genes`/`--gene` and `--tissue`; require at least one gene unless `--demo`.
2. **Query Census** *(prescriptive)*: open the Census (`census_version=stable`), filter `is_primary_data == True` + tissue + `feature_name in [...]`.
3. **Normalize** *(prescriptive)*: map var index to gene symbols; `normalize_total` + `log1p`; subsample to `--max-cells`.
4. **Emit** *(prescriptive)*: write `atlas.h5ad` + `result.json` + `reproducibility/`, and print the downstream hand-off command.

## CLI Reference

```bash
# Fetch a breast slice for TROP2 (TACSTD2)
python skills/cellxgene-fetch/cellxgene_fetch.py --genes TACSTD2 --tissue breast --output <dir>

# Multiple genes, capped
python skills/cellxgene-fetch/cellxgene_fetch.py --genes MET,CD276 --tissue lung --max-cells 5000 --output <dir>

# Offline synthetic demo (no network, no cellxgene-census)
python skills/cellxgene-fetch/cellxgene_fetch.py --demo --output <dir>

# Via ClawBio runner
python clawbio.py run cellxgene-fetch --genes TACSTD2 --tissue breast
python clawbio.py run cellxgene-fetch --demo
```

## Demo

```bash
python clawbio.py run cellxgene-fetch --demo
```

Builds a synthetic, clearly-labelled atlas (6 cell types; `MARKER_RESTRICTED` on only in B cells, `HOUSEKEEPING_BROAD` uniform). Chains directly:

```bash
python skills/celltype-specificity-profiler/profiler.py --gene MARKER_RESTRICTED --atlas atlas.h5ad
# -> tau ≈ 0.99 (cell-type-specific);  HOUSEKEEPING_BROAD -> tau ≈ 0.02 (broad)
```

## Example Output

`result.json` (demo, abbreviated):

```json
{
  "skill": "cellxgene-fetch",
  "atlas_name": "synthetic demo (cellxgene-fetch --demo; offline, illustrative)",
  "n_cells": 360,
  "n_genes": 5,
  "n_cell_types": 6,
  "cell_types": ["B cell", "NK cell", "T cell", "dendritic cell", "fibroblast", "monocyte"],
  "next": "celltype-specificity-profiler --gene <SYMBOL> --atlas atlas.h5ad"
}
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── atlas.h5ad                # annotated, log-normalized slice (obs['cell_type'] + genes)
├── result.json               # slice summary + Census version + hand-off hint
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**:
- `anndata` >= 0.9, `scanpy` — AnnData I/O + normalization
- `cellxgene-census` — the official Census API (live fetch only; `--demo` does not need it)

`--demo` runs fully offline. Live fetch needs network access to the CELLxGENE Census (AWS S3).

## Gotchas

- **Always pass `--tissue`.** The model will fetch genome-wide across all tissues and pull a huge slice. Don't — bound by `tissue_general`; use `--max-cells` for safety.
- **Output is log-normalized, not raw counts.** The model will assume raw counts for `scrna-embedding`. Do not — this slice is `log1p`-normalized for `celltype-specificity-profiler`; for scVI embedding you need a **raw-count** fetch instead.
- **Annotation granularity varies by dataset.** The model will compare `cell_type` across slices. Don't — CELLxGENE harmonizes ontologies but granularity differs; report the level (see `celltype-specificity-profiler` gotchas).
- **`--demo` data is synthetic and illustrative**, not a real atlas — never present demo tau as a real biological result.

## Safety

- **API-backed, reproducible**: queries the official Census (versioned); no HTML scraping, no fabricated data.
- **Read-only / local-first**: downloads public data to the local output dir; nothing is uploaded.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*
- **Bounded**: `--max-cells` prevents unbounded downloads.

## Agent Boundary

The agent (LLM) decides *which* gene/tissue to fetch and explains the slice. The skill (Python) performs the API query and formatting. The agent must NOT fabricate cell counts or expression, nor present `--demo` synthetic data as a real atlas.

## Chaining Partners

- **Downstream**: `scrna-embedding` (raw-count fetch → latent embedding), `scrna-orchestrator` (clustering/markers), and **`celltype-specificity-profiler`** (`--atlas atlas.h5ad` → tau/bimodality).
- **Within the CSO**: `virtual-biotech-cso` routes the single-cell sub-questions through this fetch → specificity chain. Output is a standard `.h5ad`, so it composes via the Bio Orchestrator.

## Maintenance

- **Review cadence**: track CELLxGENE Census releases (pin/refresh `census_version`); re-check the `cellxgene-census` API on major versions.
- **Staleness signals**: Census schema/field renames (`tissue_general`, `feature_name`); a requested gene symbol retired in the reference.
- **Deprecation criteria**: retire if ClawBio adds a unified atlas-fetch connector, or fold raw-count + log-norm modes into one.

## Citations

- CZ CELLxGENE Discover / Census — chanzuckerberg.github.io/cellxgene-census.
- Tabula Sapiens Consortium. *Tabula Sapiens.* (multi-organ human reference in the Census).
- Zhang H.G. et al. *The Virtual Biotech.* bioRxiv 2026 (single-cell features predict trial success — the downstream use case).
