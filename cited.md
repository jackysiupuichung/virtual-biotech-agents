---
title: Target Assessment — B7H3 · B7-H3 (CD276) ADC in lung cancer
decision: CONDITIONAL_GO
published_by: Virtual-Biotech CSO (multi-agent loop)
access: paid
payment_manifest: cited.payment.json
---

> 🔓 **Paywalled artifact.** This report is published behind agent payment rails.
> Agents fetch the full text by paying over **x402** (HTTP 402) — see
> [`cited.payment.json`](cited.payment.json) for the price, pay-to address, and
> the MPP / CDP / agentic.market listings. The text below is the published copy
> of record; the live gate is enforced by `server.py` at `GET /api/report`.

# Target Assessment — B7H3 · B7-H3 (CD276) ADC in lung cancer

*Virtual-Biotech CSO v0.1.0 · mode: demo · the skill makes no LLM call; reasoning is delegated to the driving agent via `prompts/`.*

> **Demo run** — skill results, briefing, review and synthesis are **cached illustrative fixtures** (B7-H3 walkthrough), not live results.

## Executive summary

- **Decision:** CONDITIONAL_GO
- **Confidence:** medium

B7-H3 (CD276) is a credible antibody-drug-conjugate target in lung cancer: germline genetics are weak (expected and non-disqualifying for an IO surface antigen) [step_01], expression is cell-type-specific (high tau + bimodality — a favourable trial-success/safety prior) [step_03], and prior ADC programs validate the modality [step_05]. Advance an ADC strategy conditional on resolving the stromal-vs-malignant expression split.

## Target overview

B7-H3 / CD276 is an immune-checkpoint surface glycoprotein over-expressed across solid tumours including lung cancer; it is an active antibody-drug-conjugate target with no small-molecule tractability.

## Evidence by division

| # | Division | Sub-question | Skill | Provenance | Grade | Key result | Ref |
|---|----------|--------------|-------|------------|-------|------------|-----|
| 1 | target_id_and_prioritization | Is there germline genetic support for B7-H3 (CD276)? | `gwas-lookup` | 🧪 demo | illustrative | tau=None; No genome-wide-significant germline signal expected for this checkpoint antigen; the CSO treats this as non-disqualifying and weights somatic/stromal evidence instead. | [1] |
| 2 | target_id_and_prioritization | Which cell types express B7-H3 (CD276)? | `scrna-embedding` | 🧪 demo | illustrative | CD276 expression in the lung reference is enriched in fibroblasts and endothelium, low in T/B lymphocytes. | [2] |
| 3 | target_id_and_prioritization | How cell-type-specific is B7-H3 (CD276) expression (tau + bimodality)? | `celltype-specificity-profiler` | 🧪 demo | illustrative | tau=0.78; cell-type-specific (tau > 0.7) | [3] |
| 4 | target_safety | What is the off-target / broad-tissue expression risk for B7-H3 (CD276)? | `celltype-specificity-profiler` | 🧪 demo | illustrative | Cell-type-specific expression implies lower broad-tissue off-target risk; main liability is shared fibroblast/stromal expression in normal tissue. | [4] |
| 5 | clinical_officers | What prior trials and outcomes exist for B7-H3 (CD276)? | `clinical-trial-finder` | 🧪 demo | illustrative | Multiple active B7-H3 ADC programs in solid tumours including NSCLC — validates the modality and target, but the space is competitive. | [5] |
| 6 | target_id_and_prioritization | Reviewer follow-up: spatial validation of the fibroblast/immune signal — The fibroblast enrichment and immune exclusion came from dissociated single-cell data, which loses spatial context. Spatial confirmation of B7-H3-high, immune-excluded niches is needed before synthesis. | `scrna-orchestrator` | 🧪 demo | illustrative | tau=None; Supports the immune-exclusion hypothesis the reviewer flagged; clears the gap for synthesis. | [6] |

## Evidence strength

- 0/6 steps graded **strong** (live skill data); 6 executed, 0 absent.
- Reviewer scores — relevance: 5, evidence: 4, thoroughness: 3 (1–5).

## Liabilities & risks

- **expression is partly stromal (fibroblast), not malignant-cell-intrinsic [step_02, step_03]** — *mitigation:* confirm tumour-cell expression fraction before committing payload strategy
- **trial-success / safety priors are correlational (Zhang et al. 2026), not causal** — *mitigation:* treat as a prior, not a guarantee; weight against direct evidence
- **competitive B7-H3 ADC landscape [step_05]** — *mitigation:* differentiate on payload / linker / indication

## Evidence gaps

- **spatial validation of the fibroblast/immune signal** — The fibroblast enrichment and immune exclusion came from dissociated single-cell data, which loses spatial context. Spatial confirmation of B7-H3-high, immune-excluded niches is needed before synthesis.
- malignant-cell expression fraction not measured (specificity was stromal)
- normal-tissue cross-tissue specificity not quantified (therapeutic window)

## Proposed experiments to strengthen evidence

- **spatial / tumour-cell single-cell profiling** — expected readout: B7-H3 on malignant vs stromal cells. resolves the efficacy-critical stromal-vs-malignant question
- **multi-tissue normal-atlas specificity profiling** — expected readout: cross-tissue tau. bounds on-target/off-tumour toxicity for the ADC window
- **spatial / single-cell profiling resolving tumour vs stroma** (via `scrna-orchestrator`) — expected readout: fraction of B7-H3 signal on malignant cells vs fibroblast/immune stroma. the specificity signal was stromal; an ADC needs a tumour-cell target to be efficacious
- **multi-tissue specificity profiling across a normal-tissue atlas** (via `cellxgene-fetch + celltype-specificity-profiler`) — expected readout: cross-tissue tau bounding the therapeutic window. single-tissue tau does not bound normal-tissue on-target toxicity

## References & data sources

1. **gwas-lookup** [🧪 demo] — GWAS Catalog / Open Targets / PheWeb (federated) — https://www.ebi.ac.uk/gwas/
2. **scrna-embedding** [🧪 demo] — single-cell atlas (scVI/scANVI embedding) — https://cellxgene.cziscience.com/
3. **celltype-specificity-profiler** [🧪 demo] — derived: tau + bimodality on the fetched atlas — https://cellxgene.cziscience.com/
4. **celltype-specificity-profiler** [🧪 demo] — derived: tau + bimodality on the fetched atlas — https://cellxgene.cziscience.com/
5. **clinical-trial-finder** [🧪 demo] — ClinicalTrials.gov API v2 (+ EUCTR); https://clinicaltrials.gov/study/NCT04145622 — https://clinicaltrials.gov/study/NCT04145622
6. **scrna-orchestrator** [🧪 demo] — single-cell atlas (Scanpy pipeline) — https://cellxgene.cziscience.com/

## Reproducibility

- Bundle: `reproducibility/{commands.sh, environment.yml, checksums.sha256}`; per-step provenance markers above (🔧 live · 🧪 demo · 🌐 web · ⚪ absent).

---
*Trial-success priors are correlational (Zhang et al. 2026); not a guarantee of clinical success.*

*ClawBio is a research and educational tool. It is not a medical device and does not provide clinical diagnoses. Consult a healthcare professional before making any medical decisions.*
