---
name: opentargets-association-evidence
description: For a (target, disease) pair, fetch the Open Targets association score and its evidence breakdown by datatype — genetic association, somatic mutation, known drug, affected pathway, RNA expression, animal model, literature — in one GraphQL call. The target↔disease linkage-evidence axis, distinct from target-level prioritisation factors.
license: MIT
metadata:
  version: "0.1.0"
  author: Jacky Siu
  domain: target-discovery
  tags:
    - open-targets
    - target-disease-association
    - evidence
    - genetic-association
    - somatic-mutation
    - known-drug
  inputs:
    - name: gene
      type: string
      format:
        - txt
      description: Gene symbol (e.g. MET) or --ensembl-id. Required unless --demo.
      required: false
    - name: disease
      type: string
      format:
        - txt
      description: Disease name (e.g. "non-small cell lung carcinoma") or --efo-id. Required unless --demo.
      required: false
  outputs:
    - name: association
      type: file
      format:
        - json
      description: Overall association score + per-datatype evidence scores + strength band.
    - name: report
      type: file
      format:
        - md
      description: Association strength + evidence-by-datatype table.
  dependencies:
    python: ">=3.10"
  demo_data:
    - path: examples/expected_demo_association.json
      description: Cached real Open Targets response (CD276 × lung carcinoma), offline --demo.
  endpoints:
    cli: python skills/opentargets-association-evidence/opentargets_association_evidence.py --gene {gene} --disease {disease} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "🔗"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - target disease association
      - open targets association
      - association evidence
      - genetic association evidence
      - somatic mutation evidence
      - which evidence links target and disease
      - target-disease linkage
---

# 🔗 Open Targets Association Evidence

You are **Open Targets Association Evidence**, a ClawBio agent that answers: **what kinds of evidence link this target to this disease, and how strongly?** For a (target, disease) pair you return the Open Targets overall association score and its **datatype breakdown** — the linkage evidence between the two entities.

## Trigger

**Fire this skill when the user asks how a target and a disease are linked, e.g.:**
- "What's the Open Targets association between MET and NSCLC?"
- "Which evidence types link CD276 to lung cancer — genetic, somatic, drug?"
- "Is the target-disease link genetic or just literature?"

**Do NOT fire when:**
- The user wants **target-level** factors (tractability, DepMap, safety) → `opentargets-target-factors`.
- The user wants the **single-cell** expression/specificity → `celltype-specificity-profiler` / `malignant-expression-profiler`.
- The user wants **trials** → `clinical-trial-finder`.

**Design note:** This is the **two-entity (target↔disease)** evidence axis; `opentargets-target-factors` is the **one-entity (target)** axis. They are complementary OT views.

## Why This Exists

Open Targets decomposes each target–disease association into evidence **datatypes** (genetic, somatic, drug, pathway, expression, animal, literature), each scored. Nothing in ClawBio surfaced this: `omics-target-evidence-mapper` returns a flat disease match without the datatype breakdown, and `opentargets-target-factors` is target-only.

- **Without it**: you can't tell whether a target–disease link is genetics-backed or literature-only.
- **With it**: a scored, per-datatype evidence profile in one reproducible call.
- **Why ClawBio**: official OT GraphQL; versioned; complements the target-level and single-cell axes.

## Core Capabilities

1. **Resolve** gene → Ensembl ID and disease → EFO/MONDO ID via OT search.
2. **Fetch** the association (`associatedDiseases(Bs:[efo])`) with `datatypeScores`.
3. **Report** the overall score (strength band) + per-datatype evidence + which datatypes drive it.
4. **Flag literature-only links** (a target OT may undersell — e.g. somatic/expression-driven antigens).
5. **Offline `--demo`** (cached CD276 × lung carcinoma) + reproducibility bundle.

## Scope

**One skill, one task: the target–disease association evidence breakdown.** It does not fetch trials, compute specificity, or score the target overall.

## Workflow

1. **Resolve** *(prescriptive)*: `--gene`/`--ensembl-id` and `--disease`/`--efo-id` to OT ids (or `--demo`).
2. **Fetch** *(prescriptive)*: one GraphQL query for the association row + `datatypeScores`.
3. **Interpret** *(prescriptive)*: strength band (strong ≥0.5 / moderate ≥0.1 / weak >0 / none) + drivers; flag literature-only.
4. **Emit** *(prescriptive)*: `association.json` + `report.md` + `reproducibility/`.

## CLI Reference

```bash
python skills/opentargets-association-evidence/opentargets_association_evidence.py --gene MET --disease "non-small cell lung carcinoma" --output <dir>
python skills/opentargets-association-evidence/opentargets_association_evidence.py --ensembl-id ENSG00000105976 --efo-id EFO_0003060 --output <dir>
python skills/opentargets-association-evidence/opentargets_association_evidence.py --demo --output <dir>
python clawbio.py run opentargets-association-evidence --gene MET --disease "lung carcinoma"
```

## Demo

```bash
python clawbio.py run opentargets-association-evidence --demo
```
Cached real CD276 × lung carcinoma: overall **0.005 (weak), literature-only** — illustrating a somatic/expression-driven antigen that Open Targets' association undersells.

## Example Output

`association.json` (MET × NSCLC, abbreviated):

```json
{
  "symbol": "MET", "disease": "non-small cell lung carcinoma",
  "overall_score": 0.724, "strength": "strong",
  "datatype_scores": {"somatic_mutation": 0.6, "affected_pathway": 0.4, "animal_model": 0.3, "literature": 0.5},
  "interpretation": "association is strong (score 0.724); driven by somatic_mutation, ..."
}
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── association.json          # overall score + datatype_scores + strength + interpretation
├── report.md                 # strength + evidence-by-datatype table
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**: none beyond Python 3.10+ (OT GraphQL via stdlib `urllib`). Live mode needs internet; `--demo` is offline.

## Gotchas

- **A weak/literature-only association ≠ a bad target.** The model will gate on the OT score. Do not — OT under-weights somatic/expression-driven antigens (CD276 × lung is literature-only yet an active ADC target); corroborate with single-cell + clinical skills.
- **Datatype scores are not all present.** The model will assume all seven datatypes appear. Do not — only datatypes with evidence are returned; absence = no curated evidence, not a zero you can average.
- **Disease granularity matters.** "lung carcinoma" vs "non-small cell lung carcinoma" vs "small cell lung carcinoma" give different associations. Pass the precise term or `--efo-id`.
- **Scores are harmonic-sum aggregates (0–1), not probabilities.** Use the strength band, not the raw number, for conclusions.

## Safety

- **API-backed, reproducible**: official OT GraphQL; no scraping; no fabricated scores.
- **Read-only / local-first**: writes public data locally.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*

## Agent Boundary

The agent (LLM) picks the target+disease and interprets the evidence profile in context. The skill (Python) performs the API call. The agent must NOT invent datatype scores or treat a low OT association as disqualifying without the other axes.

## Chaining Partners

- Complements `opentargets-target-factors` (target-level) and feeds the Target-ID / Clinical divisions of `virtual-biotech-cso`. Pairs with `clinical-trial-finder` (the clinical evidence the OT `known_drug` datatype reflects). Output is structured JSON, so it chains via the Bio Orchestrator.

## Maintenance

- **Review cadence**: track Open Targets releases (association model + datatype set evolve).
- **Staleness signals**: `associatedDiseases` arg/`datatypeScores` schema changes; new datatypes.
- **Deprecation criteria**: retire if `omics-target-evidence-mapper` surfaces the datatype breakdown natively.

## Citations

- Open Targets Platform — platform.opentargets.org (target–disease associations, evidence datatypes). API: api.platform.opentargets.org/api/v4/graphql.
