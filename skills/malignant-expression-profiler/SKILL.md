---
name: malignant-expression-profiler
description: Given a gene and a tumour single-cell atlas (with a malignant-cell annotation), compute whether the target sits on the malignant compartment or on stroma/normal — expression in malignant vs non-malignant cells, malignant enrichment, and a tumour-cell-target call. Closes the "is the antigen on the cancer cells?" gap for tumour-targeting modalities (esp. ADCs).
license: MIT
metadata:
  version: "0.1.0"
  role: capability  # self-contained leaf skill (one job; invoked by orchestrators)
  author: Jacky Siu
  domain: single-cell
  tags:
    - scrna
    - single-cell
    - tumour
    - malignant-cell
    - target-localization
    - adc
    - h5ad
  inputs:
    - name: gene
      type: string
      format:
        - txt
      description: Gene symbol present in the atlas var index (e.g. CD276). Required unless --demo.
      required: false
    - name: atlas
      type: file
      format:
        - h5ad
      description: Tumour single-cell .h5ad with a malignant-cell annotation (e.g. a cellxgene-fetch disease slice).
      required: false
  outputs:
    - name: malignant_profile
      type: file
      format:
        - json
      description: malignant vs non-malignant stats, enrichment, and tumour-target call.
    - name: report
      type: file
      format:
        - md
      description: Compartment table + tumour-target call.
  dependencies:
    python: ">=3.10"
    packages:
      - scanpy
      - anndata
      - numpy
      - pandas
  demo_data:
    - path: examples/expected_demo_profile.json
      description: Reference output of --demo on a synthetic tumour atlas.
  endpoints:
    cli: python skills/malignant-expression-profiler/malignant_expression_profiler.py --gene {gene} --atlas {atlas} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🎗️"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    install:
      - kind: uv
        package: scanpy
      - kind: uv
        package: anndata
      - kind: uv
        package: numpy
      - kind: uv
        package: pandas
    trigger_keywords:
      - malignant cell expression
      - tumour cell target
      - tumor cell expression
      - on-tumour target
      - malignant vs stroma
      - is the antigen on cancer cells
      - ADC target localization
---

# 🎗️ Malignant-Expression Profiler

You are **Malignant-Expression Profiler**, a ClawBio single-cell agent that answers one question: **is the target expressed on the malignant cells, or on stroma/normal cells?** For tumour-targeting modalities — especially ADCs — an antigen on stroma instead of tumour is a direct efficacy liability.

## Trigger

**Fire this skill when the user asks whether a target is on tumour cells, e.g.:**
- "Is CD276 expressed on the malignant cells or the stroma?"
- "Tumour-cell vs normal expression of gene X for an ADC"
- "Does the antigen localise to cancer cells?"

**Do NOT fire when:**
- The user wants overall **cell-type specificity / tau** → `celltype-specificity-profiler` (complementary: tau = *how specific*; this = *is it on tumour cells*).
- The user has no tumour atlas / no malignant annotation → fetch a disease slice with `cellxgene-fetch` first.
- The user wants bulk tumour-vs-normal DE → `rnaseq-de`.

## Why This Exists

`celltype-specificity-profiler` shows a gene is cell-type-specific, but a *specific* antigen can still be on the wrong compartment (e.g. B7-H3 enriched on stromal/endothelial cells, not tumour). No skill answered "is it on the malignant cells?" — the efficacy-critical question for ADCs and CAR-T.

- **Without it**: users eyeball per-cell-type tables to guess the malignant fraction.
- **With it**: a direct malignant-vs-non-malignant contrast + enrichment + a tumour-target call.
- **Why ClawBio**: pure analytic transform on an annotated atlas; reproducible; chains after `cellxgene-fetch`.

## Core Capabilities

1. **Malignant compartment contrast**: mean expression + % expressing in malignant cells vs all others.
2. **Malignant enrichment**: ratio of malignant to non-malignant mean (or "malignant-exclusive" when non-malignant ≈ 0).
3. **Tumour-target call**: on-tumour (favourable) · on-tumour with normal-expression risk · mixed/partial · off-tumour (liability) · undetermined.
4. **Auto-detect** the malignant cell-type label (or pass `--malignant-key`).
5. **Offline `--demo`** on a synthetic tumour atlas + reproducibility bundle.

## Scope

**One skill, one task: malignant-vs-non-malignant expression for one gene.** It does not fetch data, compute tau, or do differential expression.

## Workflow

1. **Resolve** *(prescriptive)*: read the atlas (or `--demo`); resolve the cell-type column and the malignant label (auto-detect `malign/neoplas/tumor/cancer`, or `--malignant-key`).
2. **Contrast** *(prescriptive)*: split cells into malignant vs rest; compute mean/%-expressing for each; compute enrichment.
3. **Call** *(prescriptive)*: classify by malignant %-expressing and enrichment.
4. **Emit** *(prescriptive)*: write `malignant_profile.json` + `report.md` + `reproducibility/`.

## CLI Reference

```bash
python skills/malignant-expression-profiler/malignant_expression_profiler.py --gene CD276 --atlas tumour.h5ad --output <dir>
python skills/malignant-expression-profiler/malignant_expression_profiler.py --gene MET --atlas luad.h5ad --malignant-key "malignant cell" --output <dir>
python skills/malignant-expression-profiler/malignant_expression_profiler.py --demo --output <dir>
python clawbio.py run malignant-expression-profiler --demo
```

## Demo

```bash
python clawbio.py run malignant-expression-profiler --demo
```
Synthetic tumour atlas (malignant + fibroblast/endothelial/T/macrophage); `TUMOR_ANTIGEN` is on the malignant compartment → **on-tumour (favourable)**.

## Example Output

`malignant_profile.json` (abbreviated):

```json
{
  "gene": "MET",
  "malignant_label": "malignant cell",
  "malignant": {"n_cells": 410, "mean_expr": 0.31, "pct_expressing": 0.47},
  "non_malignant": {"n_cells": 2590, "mean_expr": 0.0, "pct_expressing": 0.03},
  "malignant_enrichment": null,
  "enrichment_note": "non-malignant expression ≈ 0 (malignant-exclusive)",
  "tumour_target_call": "on-tumour (favourable)"
}
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── malignant_profile.json    # malignant vs non-malignant stats, enrichment, call
├── report.md                 # compartment table + call
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**: `scanpy`, `anndata`, `numpy`, `pandas`. No network (operates on a local atlas).

## Gotchas

- **The call is atlas- and annotation-dependent.** The model will treat it as a verdict. Do not — it reflects *this* slice's malignant annotation; a bulk-overexpressed antigen (e.g. TROP2) can still be an ADC target via IHC-high selection even when single-cell enrichment is <1.
- **No malignant annotation → undetermined, not negative.** The model will read a missing malignant label as "not on tumour". Do not — it means the atlas lacks the annotation; use a tumour slice.
- **"non-malignant" pools stroma + immune + normal-epithelium.** The model will call low enrichment "stromal". Do not — distinguish normal-epithelium (on-target toxicity) from stroma (off-target); inspect the per-cell-type table if needed.
- **% expressing depends on sequencing depth / dropout.** Sparse genes under-report; corroborate with `celltype-specificity-profiler`.

## Safety

- **Local-first**: pure computation on a provided atlas; no upload, no fabricated values.
- **Honest calls**: missing malignant annotation → `undetermined`, never a false negative.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*

## Agent Boundary

The agent (LLM) supplies the gene/atlas and interprets the call in context (modality, biomarker strategy). The skill (Python) computes the contrast. The agent must NOT present the heuristic call as a clinical verdict or invent expression values.

## Chaining Partners

- **Upstream**: `cellxgene-fetch` (a disease/tumour `.h5ad` slice with malignant annotation).
- **Alongside**: `celltype-specificity-profiler` (tau / bimodality) — together they answer *how specific* and *on which compartment*.
- Within `virtual-biotech-cso` it serves Target ID & Target Safety (the malignant-vs-stromal/normal question). Output is structured JSON, so it chains via the Bio Orchestrator.

## Maintenance

- **Review cadence**: track CELLxGENE cell-type ontology terms for "malignant cell" / "neoplastic cell" naming.
- **Staleness signals**: atlases adopting a different malignant label not covered by the auto-detect keywords.
- **Deprecation criteria**: fold into `celltype-specificity-profiler` if it gains a native malignant-compartment mode.

## Citations

- CZ CELLxGENE — disease-annotated single-cell atlases with malignant-cell labels.
- Zhang H.G. et al. *The Virtual Biotech.* bioRxiv 2026 (single-cell features for target assessment).
