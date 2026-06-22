# Workflow: B7-H3 (CD276) ADC nomination in lung cancer

The demo case study for the hybrid Virtual-Biotech CSO. Reproduces, in scoped form, the
B7-H3 analysis from Zhang et al. 2026 — showing the orchestration end-to-end on one query.

Packaged for ClawBio as the **`virtual-biotech-cso`** skill (PR #2), which sits below
`bio-orchestrator` and routes to the division skills below — including
**`celltype-specificity-profiler`** (PR #1, [ClawBio#307](https://github.com/ClawBio/ClawBio/pull/307)).

**Query:** *"Assess B7-H3 potential as a therapeutic target in lung cancer."*

## The chain (as the CSO routes it)

| # | Division | Sub-question | ClawBio skill | Expected signal |
|---|----------|--------------|---------------|-----------------|
| 0 | Office of CSO | Field briefing | `chief_of_staff` | IO checkpoint, ADC landscape, atlases available |
| 1 | Target ID | Germline genetic support? | `gwas-lookup` | **Weak/absent** — CSO rules non-disqualifying |
| 2 | Target ID | Which cell types express it? | `scrna-embedding` | Enriched in **fibroblasts**, down in T cells |
| 3 | Target ID | How cell-type-specific? | `celltype-specificity-profiler` | High tau + bimodality → favorable prior |
| 4 | Target Safety | Off-target tissue risk? | `celltype-specificity-profiler` | Specificity ⇒ lower broad-tissue AE risk |
| 5 | Clinical | Prior trials / outcomes | `clinical-trial-finder` | Existing B7-H3 ADC programs |
| — | Reviewer | Audit → gap? | `reviewer` | Flags missing **spatial** validation → re-route |
| 6 | Target ID | Spatial immune exclusion? | `scrna-orchestrator` | B7-H3-high spots depleted of immune cells |

> `chief_of_staff` and `reviewer` are **agent roles** the driving agent runs from the skill's
> `prompts/` (one subagent each) — not standalone ClawBio skills. Every other row is a real
> ClawBio skill the CSO routes to via `routing.yaml`.

## Reviewer loop (the hybrid's distinguishing feature)

After steps 1–5 the **Scientific Reviewer** notes that the fibroblast/immune signal came from
*dissociated* single-cell data and lacks spatial context — exactly the gap the paper's reviewer
caught. It returns `re-route → scrna-orchestrator` for spatial validation (step 6). Once that
confirms immune exclusion, it returns `synthesize`.

## Synthesis (CSO output)

A report concluding: B7-H3 has **weak germline genetics but strong somatic/stromal rationale**,
cell-type-specific expression (favorable trial-success and safety priors), and spatial evidence
of an immune-excluded niche — supporting an **ADC strategy**, with the stromal-vs-malignant
expression split called out as a key liability.

## Demo de-risking

- `clawbio run virtual-biotech-cso --demo` runs the whole chain **fully offline** from cached,
  clearly-labelled fixtures in the skill's `demo_data/b7h3/` — no network, no API key. The skill
  itself makes **no LLM call**; the briefing / reviewer / synthesis reasoning is delegated to the
  driving agent (e.g. Claude Code subagents) via the skill's `prompts/`.
- `--live` executes the routed skills through the ClawBio runtime; anything unavailable is reported
  honestly, never fabricated.
- The cached fixture values are **illustrative** (labelled as such in each file), not live results.

## Run

```bash
# Packaged ClawBio skill — offline demo, no API key
clawbio run virtual-biotech-cso --demo

# …or against your own target, executing routed skills via the runtime
clawbio run virtual-biotech-cso --query "Assess B7-H3 potential as a therapeutic target in lung cancer" --live
```

Source: [`skills/virtual-biotech-cso/`](../skills/virtual-biotech-cso/).
