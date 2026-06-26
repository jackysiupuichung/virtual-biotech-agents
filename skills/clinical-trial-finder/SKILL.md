---
name: clinical-trial-finder
description: For a therapeutic target (optionally + disease), query the live ClinicalTrials.gov API v2 (public, no key) and return a deduplicated list of registered trials, each carrying its NCT id and a deep link to the actual study record (clinicaltrials.gov/study/NCT…) — not the registry homepage. The clinical-precedent front-end. API-backed and reproducible, not page scraping.
license: MIT
metadata:
  version: "0.1.0"
  role: capability  # self-contained leaf skill (one job; invoked by orchestrators)
  author: Jacky Siu
  domain: clinical-trials
  tags:
    - clinicaltrials-gov
    - clinical-trials
    - nct
    - trial-precedent
    - deep-link
  inputs:
    - name: target
      type: string
      format:
        - txt
      description: Target, optionally with disease (e.g. "B7-H3 in lung cancer"). Required unless --demo.
      required: false
  outputs:
    - name: result
      type: file
      format:
        - json
      description: Deduplicated trials, each with nct, title, status, phase, and a deep-link study url.
    - name: report
      type: file
      format:
        - md
      description: Human-readable trial list with every trial linked to its actual study record.
  dependencies:
    python: ">=3.10"
  demo_data:
    - path: (built-in build_demo)
      description: Cached illustrative trial list for B7-H3 with real NCT ids (offline --demo).
  endpoints:
    cli: python skills/clinical-trial-finder/clinical_trial_finder.py --target {target} --output {output_dir}
  openclaw:
    requires:
      bins:
        - python3
      env: []  # the ClinicalTrials.gov API v2 is public — no key required for live mode
    always: false
    emoji: "🧪"
    homepage: https://github.com/ClawBio/ClawBio
    os:
      - darwin
      - linux
    trigger_keywords:
      - clinical trials
      - registered trials
      - prior trials
      - trial precedent
      - clinicaltrials.gov
      - nct
---

# 🧪 Clinical-Trial Finder (ClinicalTrials.gov API v2)

You are **Clinical-Trial Finder**, the ClawBio clinical-precedent data agent. Your one job: for a therapeutic target (optionally + disease), query the **live ClinicalTrials.gov API v2** (public, no key) and return a **deduplicated** list of registered trials. Every trial keeps its **NCT id** and a **deep link to the actual study record** (`https://clinicaltrials.gov/study/NCT…`) — never the registry homepage — so downstream synthesis cites the specific trial. You call a versioned REST API, not page scraping, and you do no analysis beyond assembling the trial list.

## Trigger

**Fire this skill when the user (or the Scientific Reviewer) wants registered-trial precedent, e.g.:**
- "What prior trials and outcomes exist for B7-H3?"
- "Are there registered ADC trials targeting CD276?"
- "What's the trial precedent for this target in lung cancer?"

**Do NOT fire when:**
- The user wants **timely web/literature context** → `lit-synthesizer`.
- The user wants **post-market FAERS counts for a drug** → `openfda-safety`.
- The user wants **structured target↔disease evidence** → `opentargets-association-evidence`.

## Run

```bash
# Live: real ClinicalTrials.gov API v2 query (no key)
python skills/clinical-trial-finder/clinical_trial_finder.py --target "B7-H3 in lung cancer" --output ./output

# Offline: cached illustrative trial list for B7-H3 (real NCT ids, no network)
python skills/clinical-trial-finder/clinical_trial_finder.py --demo --output ./output
```

Outputs `result.json` (machine-readable, each trial deep-linked by NCT id) and `report.md` (human-readable). Trial records are registry metadata, not peer-reviewed outcomes — treat each as a precedent to verify against its study record.
