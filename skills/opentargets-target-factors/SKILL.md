---
name: opentargets-target-factors
description: For one target, fetch the Open Targets prioritisation factors, tractability, and safety liabilities in a single GraphQL call and map them to the drug-discovery divisions they inform — DepMap essentiality (functional), tractability/clinical stage (modality), genetic constraint / mouse-KO / tissue specificity / safety liabilities (target safety). API-backed and reproducible.
license: MIT
metadata:
  version: "0.1.0"
  role: capability  # self-contained leaf skill (one job; invoked by orchestrators)
  author: Jacky Siu
  domain: target-discovery
  tags:
    - open-targets
    - target-prioritisation
    - tractability
    - depmap
    - target-safety
    - druggability
  inputs:
    - name: gene
      type: string
      format:
        - txt
      description: Gene symbol (e.g. CD276) or --ensembl-id. Required unless --demo.
      required: false
  outputs:
    - name: factors
      type: file
      format:
        - json
      description: Prioritisation factors (division-mapped), positive tractability modalities, and safety liabilities.
    - name: report
      type: file
      format:
        - md
      description: Human-readable factor table grouped by Virtual-Biotech division.
  dependencies:
    python: ">=3.10"
  demo_data:
    - path: examples/expected_demo_factors.json
      description: Cached real Open Targets response for CD276 (offline --demo).
  endpoints:
    cli: python skills/opentargets-target-factors/opentargets_target_factors.py --gene {gene} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🎯"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - open targets
      - target prioritisation
      - prioritisation factors
      - tractability
      - druggability
      - depmap essentiality
      - target safety factors
      - genetic constraint
---

# 🎯 Open Targets Target Factors

You are **Open Targets Target Factors**, a ClawBio data-acquisition agent. Your one job: pull a target's **Open Targets prioritisation factors**, **tractability**, and **safety liabilities** in a single GraphQL call, and map them to the divisions they inform. You do no analysis beyond the mapping, and you query the **official Open Targets Platform API** — not web scraping.

## Trigger

**Fire this skill when the user wants target-level prioritisation / druggability / safety factors, e.g.:**
- "What are the Open Targets prioritisation factors for CD276?"
- "Is gene X tractable / druggable? Antibody or small molecule?"
- "DepMap essentiality / genetic constraint / mouse-KO / safety liabilities for target Y"

**Do NOT fire when:**
- The user wants **cell-type specificity** → `celltype-specificity-profiler` (single-cell; complementary, not the same as OT bulk `tissueSpecificity`).
- The user wants **disease associations or trials** → `omics-target-evidence-mapper` / `clinical-trial-finder`.
- The user wants the **variant-level** germline picture → `gwas-lookup`.

**Design note:** One OT call covers Functional (DepMap), Modality (tractability), and Target-Safety factors at once — an efficient front-end for those divisions.

## Why This Exists

Open Targets aggregates DepMap essentiality, tractability, genetic constraint, mouse-KO, tissue specificity, and safety liabilities into one **prioritisation** object — but no ClawBio skill surfaces it (`omics-target-evidence-mapper` returns only protein summary + literature + trials).

- **Without it**: The Functional / Modality / Target-Safety divisions fall back to web search or separate per-source skills.
- **With it**: One reproducible call returns all of those factors, division-mapped.
- **Why ClawBio**: API-backed, versioned to the OT release, no scraping; complements (does not replace) the single-cell specificity skill.

## Core Capabilities

1. **Resolve** a gene symbol → Ensembl ID via the OT search endpoint (or take `--ensembl-id`).
2. **Fetch** `target.prioritisation` (factor set, −1…+1), `tractability` (modalities), and `safetyLiabilities` in one query.
3. **Map** each factor to its Virtual-Biotech division (functional / modality / target-safety).
4. **Offline `--demo`**: cached real CD276 response (no network).
5. **Reproducibility bundle** with the OT endpoint recorded.

## Scope

**One skill, one task: retrieve and division-map a target's Open Targets factors.** It does not compute specificity, fetch trials, or score the target — those are other skills.

## Workflow

1. **Resolve** *(prescriptive)*: `--gene` → Ensembl ID via OT `search`; or use `--ensembl-id`; or `--demo`.
2. **Fetch** *(prescriptive)*: one GraphQL query for `prioritisation` + `tractability` + `safetyLiabilities`.
3. **Map** *(prescriptive)*: group factors by division; keep positive tractability modalities.
4. **Emit** *(prescriptive)*: write `factors.json` + `report.md` + `reproducibility/`.

## CLI Reference

```bash
python skills/opentargets-target-factors/opentargets_target_factors.py --gene CD276 --output <dir>
python skills/opentargets-target-factors/opentargets_target_factors.py --ensembl-id ENSG00000103855 --output <dir>
python skills/opentargets-target-factors/opentargets_target_factors.py --demo --output <dir>
python clawbio.py run opentargets-target-factors --gene CD276
```

## Demo

```bash
python clawbio.py run opentargets-target-factors --demo
```
Returns the cached real CD276 factor set offline: not small-molecule tractable, antibody **"Advanced Clinical"**, `geneEssentiality 0`, `geneticConstraint −0.14`, `tissueSpecificity −1`.

## Example Output

`report.md` (CD276, abbreviated):

```markdown
## Prioritisation factors by division
| Factor | Value | Division |
|---|---|---|
| geneEssentiality | 0.0 | functional_genomics (DepMap) |
| hasSmallMoleculeBinder | 0.0 | modality |
| maxClinicalStage | 0.5 | clinical/modality |
| geneticConstraint | -0.14 | target_safety |
| tissueSpecificity | -1.0 | target_safety (bulk tissue) |

## Tractability (positive)
- AB: Advanced Clinical
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── factors.json              # division-mapped prioritisation factors + tractability + safety
├── report.md                 # factor table grouped by division
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**: none beyond Python 3.10+ (network via stdlib `urllib`). Live mode needs internet to the Open Targets Platform GraphQL API; `--demo` is offline.

## Gotchas

- **OT `tissueSpecificity` is bulk/tissue-level, NOT cell-type.** The model will equate it with our single-cell tau. Do not — they differ (B7-H3: OT `tissueSpecificity −1` "broadly expressed" vs single-cell `tau 0.93` "cell-type-specific"). Report both; they are complementary.
- **Prioritisation values are −1…+1, not raw measurements.** The model will read `0` as "zero expression/essentiality". Do not — `0` is a neutral/scaled score, not an absolute.
- **Empty `safetyLiabilities` ≠ safe.** The model will infer safety from an empty list. Do not — it means OT has no curated liability, not that none exist.
- **Gene→Ensembl resolution can be ambiguous.** The skill prefers an exact symbol match from OT `search`; pass `--ensembl-id` to be unambiguous.

## Safety

- **API-backed, reproducible**: queries the official Open Targets Platform GraphQL; no scraping; no fabricated values.
- **Read-only / local-first**: writes public factor data locally; nothing uploaded.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*

## Agent Boundary

The agent (LLM) decides which target to query and interprets the division-mapped factors. The skill (Python) performs the API call and mapping. The agent must NOT invent factor values or read OT bulk `tissueSpecificity` as cell-type specificity.

## Chaining Partners

- Fills **Functional / Modality / Target-Safety** in the `virtual-biotech-cso` routing, alongside `celltype-specificity-profiler` (single-cell specificity), `clinical-trial-finder` (trials), and `gwas-lookup` (germline). Output is structured JSON, so it composes via the Bio Orchestrator.

## Maintenance

- **Review cadence**: track Open Targets Platform releases (factor keys / schema can change); the prioritisation key set evolves.
- **Staleness signals**: a `prioritisation.items` key renamed; the GraphQL endpoint version bumped.
- **Deprecation criteria**: retire if `omics-target-evidence-mapper` is extended to surface prioritisation factors natively.

## Citations

- Open Targets Platform — platform.opentargets.org (target prioritisation, tractability, safety liabilities). API: api.platform.opentargets.org/api/v4/graphql.
- DepMap (Broad Institute) — gene essentiality, surfaced via the Open Targets prioritisation factor.
