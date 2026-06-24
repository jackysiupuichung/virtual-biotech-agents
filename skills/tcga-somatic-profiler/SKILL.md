---
name: tcga-somatic-profiler
description: For a gene, report its somatic mutation frequency across TCGA cancer types from the NCI Genomic Data Commons — fraction of each cohort carrying a simple somatic mutation in the gene, ranked. The somatic-driver axis (complements germline GWAS and expression). API-backed and reproducible.
license: MIT
metadata:
  version: "0.1.0"
  role: capability  # self-contained leaf skill (one job; invoked by orchestrators)
  author: Jacky Siu
  domain: cancer-genomics
  tags:
    - tcga
    - gdc
    - somatic-mutation
    - cancer-genomics
    - driver
    - mutation-frequency
  inputs:
    - name: gene
      type: string
      format:
        - txt
      description: Gene symbol (e.g. MET). Required unless --demo.
      required: false
  outputs:
    - name: somatic
      type: file
      format:
        - json
      description: Per-TCGA-cancer-type somatic mutation frequency (mutated cases / cohort), ranked.
    - name: report
      type: file
      format:
        - md
      description: Frequency-by-cancer-type table + driver/expression call.
  dependencies:
    python: ">=3.10"
  demo_data:
    - path: examples/expected_demo_somatic.json
      description: Cached real GDC response for MET (offline --demo).
  endpoints:
    cli: python skills/tcga-somatic-profiler/tcga_somatic_profiler.py --gene {gene} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🧬"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - somatic mutation frequency
      - tcga mutation
      - is this a somatic driver
      - cancer mutation frequency
      - gdc somatic
      - mutated in which cancers
      - driver vs passenger
---

# 🧬 TCGA Somatic Profiler

You are **TCGA Somatic Profiler**, a ClawBio cancer-genomics agent. Your one job: for a gene, report its **somatic mutation frequency across TCGA cancer types** (NCI GDC) — what fraction of each cohort carries a simple somatic mutation in the gene — to place it on the somatic-driver axis.

## Trigger

**Fire this skill when the user asks about somatic mutation in cancer, e.g.:**
- "How often is MET somatically mutated across TCGA cancers?"
- "Is gene X a somatic driver or an expression target?"
- "Which cancers carry mutations in this gene?"

**Do NOT fire when:**
- The user wants **germline** variants → `gwas-lookup`.
- The user wants the **target–disease association** (which mixes somatic + other evidence) → `opentargets-association-evidence`.
- The user wants **expression / specificity** → the single-cell skills.

**Design note:** Germline GWAS is often quiet for cancer surface antigens; this is the **somatic** axis that distinguishes mutation drivers (e.g. MET) from expression targets (e.g. B7-H3, TROP2).

## Why This Exists

The paper's case studies hinge on somatic biology, but no ClawBio skill returned per-cancer-type somatic frequency. `gwas-lookup` is germline; `opentargets-association-evidence` blends somatic into one score. This gives the raw TCGA somatic frequency directly.

- **Without it**: somatic-driver vs expression-target can't be told apart from the other axes.
- **With it**: ranked per-cancer-type frequency from GDC in one reproducible call.
- **Why ClawBio**: official GDC API; versioned; complements germline / association / expression axes.

## Core Capabilities

1. **Numerator** — cases with ≥1 simple somatic mutation in the gene, per TCGA project (GDC `ssm_occurrences`).
2. **Denominator** — TCGA cohort size per project (GDC `cases`).
3. **Frequency** — mutated / cohort, ranked across cancer types.
4. **Driver/expression call** — recurrent somatic driver (≥10%) · moderate (≥3%) · low (likely expression target).
5. **Offline `--demo`** (cached real MET response) + reproducibility bundle.

## Scope

**One skill, one task: per-cancer-type somatic mutation frequency for one gene.** It does not call driver-vs-passenger per mutation, fetch germline data, or score the target.

## Workflow

1. **Numerator** *(prescriptive)*: GDC `ssm_occurrences` faceted by `case.project.project_id`, filtered to the gene symbol.
2. **Denominator** *(prescriptive)*: GDC `cases` faceted by `project.project_id`.
3. **Compute** *(prescriptive)*: frequency per TCGA project; rank; classify the top.
4. **Emit** *(prescriptive)*: `somatic.json` + `report.md` + `reproducibility/`.

## CLI Reference

```bash
python skills/tcga-somatic-profiler/tcga_somatic_profiler.py --gene MET --output <dir>
python skills/tcga-somatic-profiler/tcga_somatic_profiler.py --gene MET --top 15 --output <dir>
python skills/tcga-somatic-profiler/tcga_somatic_profiler.py --demo --output <dir>
python clawbio.py run tcga-somatic-profiler --gene MET
```

## Demo

```bash
python clawbio.py run tcga-somatic-profiler --demo
```
Cached real MET frequencies: TCGA-UCEC 16.1%, SKCM 13.8%, … LUAD 4.1% (≈ the known METex14 rate) → **recurrent somatic driver**.

## Example Output

`somatic.json` (MET, abbreviated):

```json
{
  "gene": "MET", "call": "recurrent somatic driver",
  "top_cancer_types": [
    {"cancer_type": "TCGA-UCEC", "mutated_cases": 90, "cohort": 560, "frequency_pct": 16.07},
    {"cancer_type": "TCGA-LUAD", "mutated_cases": 24, "cohort": 585, "frequency_pct": 4.10}
  ]
}
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── somatic.json              # per-cancer-type frequency (mutated/cohort) + call
├── report.md                 # frequency-by-cancer-type table
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**: none beyond Python 3.10+ (GDC via stdlib `urllib`). Live mode needs internet to `api.gdc.cancer.gov`; `--demo` is offline.

## Gotchas

- **Hypermutated cohorts inflate frequency.** The model will read high frequency in UCEC/SKCM/COAD as driver evidence. Do not — these have high tumour mutational burden, so *any* gene shows elevated frequency; cross-check that the cancer is biologically relevant.
- **Counts ANY somatic mutation, not driver mutations.** The model will equate the frequency with a driver rate. Do not — it includes passengers; for the specific driver (e.g. METex14) consult the mutation-level data.
- **Frequency ≠ functional importance.** The model will rank targets by this alone. Do not — a low somatic frequency is expected (and fine) for an **expression** target (B7-H3, TROP2); pair with the expression/association axes.
- **Denominator is total cohort size.** A small number of cases in a project may lack SSM data; treat very small cohorts cautiously.

## Safety

- **API-backed, reproducible**: official NCI GDC; no scraping; no fabricated counts.
- **Read-only / local-first**: writes public aggregate counts locally; no patient-level data.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*

## Agent Boundary

The agent (LLM) chooses the gene and interprets frequency in context (TMB, driver vs passenger, modality). The skill (Python) performs the GDC queries. The agent must NOT present a high hypermutated-cohort frequency as driver evidence, nor invent counts.

## Chaining Partners

- Complements `gwas-lookup` (germline), `opentargets-association-evidence` (somatic folded into the association `somatic_mutation` datatype), and the expression skills. Feeds the Target-ID division of `virtual-biotech-cso`. Output is structured JSON, so it chains via the Bio Orchestrator.

## Maintenance

- **Review cadence**: GDC data releases change cohort sizes / counts; re-run to refresh.
- **Staleness signals**: GDC field path changes (`ssm.consequence.transcript.gene.symbol`, `case.project.project_id`).
- **Deprecation criteria**: retire if a cBioPortal-backed driver-aware frequency skill supersedes this raw-SSM count.

## Citations

- NCI Genomic Data Commons (GDC) — gdc.cancer.gov; API api.gdc.cancer.gov (TCGA simple somatic mutations).
- The Cancer Genome Atlas (TCGA) — the underlying tumour cohorts.
