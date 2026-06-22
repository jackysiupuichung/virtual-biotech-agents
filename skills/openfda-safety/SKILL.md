---
name: openfda-safety
description: For a drug, query openFDA and return a post-market safety snapshot — top FAERS adverse-event reaction terms with report counts, plus the label boxed warning if present. The FDA-Safety-Officer data front-end. API-backed and reproducible, not web scraping.
license: MIT
metadata:
  version: "0.1.0"
  author: Jacky Siu
  domain: pharmacovigilance
  tags:
    - openfda
    - faers
    - adverse-events
    - drug-safety
    - pharmacovigilance
    - boxed-warning
  inputs:
    - name: drug
      type: string
      format:
        - txt
      description: Drug name, generic or brand (e.g. capmatinib). Required unless --demo.
      required: false
  outputs:
    - name: safety
      type: file
      format:
        - json
      description: Top FAERS reaction terms with report counts + boxed warning.
    - name: report
      type: file
      format:
        - md
      description: Human-readable safety snapshot with the spontaneous-reporting caveat.
  dependencies:
    python: ">=3.10"
  demo_data:
    - path: examples/expected_demo_safety.json
      description: Cached real openFDA FAERS response for capmatinib (offline --demo).
  endpoints:
    cli: python skills/openfda-safety/openfda_safety.py --drug {drug} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
    always: false
    emoji: "💊"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - openfda
      - faers
      - adverse events
      - drug safety
      - pharmacovigilance
      - side effects
      - boxed warning
      - adverse event reports
---

# 💊 openFDA Safety

You are **openFDA Safety**, the ClawBio FDA-Safety-Officer data agent. Your one job: for a drug, pull a **post-market safety snapshot** from the official **openFDA** APIs — the top FAERS adverse-event reactions (with report counts) and the label boxed warning. You query a versioned public API, not web pages, and you do no analysis beyond assembling the snapshot.

## Trigger

**Fire this skill when the user wants real-world drug safety, e.g.:**
- "What adverse events are reported for capmatinib?"
- "FAERS / openFDA safety profile for drug X"
- "Does drug Y have a boxed warning?"

**Do NOT fire when:**
- The user wants **target-level / structural / genetic safety** (genetic constraint, mouse-KO, safety liabilities) → `opentargets-target-factors`.
- The user wants **clinical-trial** results → `clinical-trial-finder`.
- The query is a **gene with no drug** — this skill is drug-level; supply a drug that targets the gene.

**Design note:** This is the *post-market* safety front-end (what's been reported in patients), complementing the *pre-clinical/structural* safety in `opentargets-target-factors`.

## Why This Exists

The paper's FDA-Safety-Officer agent relies on openFDA adverse-event reports, but no ClawBio skill queries FAERS.

- **Without it**: post-market safety falls back to web search or is skipped.
- **With it**: one reproducible call returns the top reported reactions + boxed warning for a drug.
- **Why ClawBio**: official openFDA API (versioned, no key at low volume), no scraping, honest about reporting caveats.

## Core Capabilities

1. **FAERS adverse events**: top reaction terms by report count (`drug/event`, MedDRA preferred terms).
2. **Boxed warning**: from the structured drug label (`drug/label`) when present.
3. **Robust drug matching**: structured `openfda.generic_name` first, free-text `medicinalproduct` fallback.
4. **Offline `--demo`**: cached real FAERS snapshot for capmatinib (no network, no key).
5. **Reproducibility bundle** with the spontaneous-reporting caveat recorded.

## Scope

**One skill, one task: retrieve a drug's openFDA post-market safety snapshot.** It does not compute disproportionality statistics, infer causality, or score targets.

## Workflow

1. **Resolve** *(prescriptive)*: take `--drug` (or `--demo`).
2. **Query FAERS** *(prescriptive)*: count `patient.reaction.reactionmeddrapt.exact` for the drug; fall back from `openfda.generic_name` to `medicinalproduct`.
3. **Query label** *(prescriptive)*: fetch the boxed warning if present.
4. **Emit** *(prescriptive)*: write `safety.json` + `report.md` + `reproducibility/`, always carrying the spontaneous-reporting caveat.

## CLI Reference

```bash
python skills/openfda-safety/openfda_safety.py --drug capmatinib --output <dir>
python skills/openfda-safety/openfda_safety.py --drug capmatinib --limit 20 --output <dir>
python skills/openfda-safety/openfda_safety.py --demo --output <dir>
python clawbio.py run openfda-safety --drug capmatinib
```

## Demo

```bash
python clawbio.py run openfda-safety --demo
```
Cached real FAERS snapshot for **capmatinib** (offline): top reactions are DEATH, PERIPHERAL SWELLING, FATIGUE, OEDEMA PERIPHERAL, NAUSEA, MALIGNANT NEOPLASM PROGRESSION… (no boxed warning).

## Example Output

`report.md` (capmatinib, abbreviated):

```markdown
> FAERS counts are spontaneous reports — reporting frequency, not incidence or causation.

## Top adverse-event reactions (FAERS)
| Reaction | Reports |
|---|---|
| DEATH | 411 |
| PERIPHERAL SWELLING | 288 |
| FATIGUE | 260 |

## Boxed warning
_None on the openFDA label._
```

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses.*

## Output Structure

```text
output_directory/
├── safety.json               # reactions + counts + boxed warning + caveat
├── report.md                 # snapshot table with the reporting caveat
└── reproducibility/
    ├── commands.sh
    ├── environment.yml
    └── checksums.sha256
```

## Dependencies

**Required**: none beyond Python 3.10+ (openFDA via stdlib `urllib`). Live mode needs internet to `api.fda.gov`; `--demo` is offline. No API key required at low volume.

## Gotchas

- **FAERS counts ≠ incidence or causation.** The model will rank "most dangerous" by count. Do not — counts are spontaneous-report frequencies, confounded by indication, drug popularity, and reporting bias. The report states this every time.
- **"DEATH" / "DISEASE PROGRESSION" dominate oncology drugs.** The model will read these as drug toxicity. Do not — for cancer drugs these largely reflect the underlying disease, not the agent.
- **Empty results ≠ safe.** The model will infer safety from no reports. Do not — it usually means the name didn't match FAERS or the drug is new; try the brand/generic alternative.
- **Drug-level, not gene-level.** The model will pass a gene. Do not — supply a drug that targets the gene (from `clinical-trial-finder` / Open Targets known drugs).

## Safety

- **API-backed, reproducible**: official openFDA endpoints; no scraping; no fabricated counts.
- **Honest caveat**: every output carries the spontaneous-reporting disclaimer.
- **Read-only / local-first**: writes public data locally; nothing uploaded.
- **Disclaimer**: *ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*

## Agent Boundary

The agent (LLM) chooses the drug and interprets the snapshot with the reporting caveat. The skill (Python) performs the API calls and assembly. The agent must NOT invent counts, present FAERS frequency as incidence, or attribute disease-progression terms to the drug.

## Chaining Partners

- Fills the **FDA Safety Officer** role in `virtual-biotech-cso` routing (Target Safety + Clinical), complementing `opentargets-target-factors` (structural/genetic safety) and `clinical-trial-finder` (trial outcomes). Drug names come from those skills. Output is structured JSON, so it composes via the Bio Orchestrator.

## Maintenance

- **Review cadence**: openFDA refreshes FAERS quarterly; counts drift over time (cache the date in provenance).
- **Staleness signals**: openFDA field/endpoint changes; MedDRA version updates.
- **Deprecation criteria**: retire if a disproportionality-statistics skill (PRR/ROR) supersedes this raw-count snapshot.

## Citations

- openFDA — open.fda.gov (FAERS `drug/event`, `drug/label`). API: api.fda.gov.
- FDA Adverse Event Reporting System (FAERS) — spontaneous post-market safety reports.
