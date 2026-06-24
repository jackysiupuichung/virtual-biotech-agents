// AUTO-GENERATED from skills/virtual-biotech-cso/demo_data/b7h3/. Do not edit by hand — run frontend/build.py.
window.CSO_DEMO = {
  "briefing": {
    "context": "B7-H3 (CD276) is an immune-checkpoint molecule over-expressed across many solid tumours, including non-small-cell lung cancer. It is an active antibody-drug-conjugate (ADC) target; germline genetic support is expected to be weak (typical for immuno-oncology surface antigens), so the assessment should weight somatic/stromal expression and single-cell specificity over GWAS. Relevant atlases (Tabula Sapiens, CELLxGENE lung) and ClinicalTrials.gov coverage are available.",
    "data_availability": [
      "GWAS Catalog / Open Targets germline associations",
      "CELLxGENE + Tabula Sapiens single-cell lung references",
      "ClinicalTrials.gov / PubMed for prior B7-H3 programs"
    ],
    "priority_questions": [
      "Is B7-H3 expression cell-type-specific enough to favour a wide therapeutic index?",
      "Is the tumour signal malignant-cell or stromal (fibroblast) driven?",
      "Do existing B7-H3 ADC trials de-risk or crowd the space?"
    ],
    "feasibility_flags": [
      "Dissociated scRNA loses spatial context \u2014 may need spatial validation",
      "Stromal vs malignant expression split is a known interpretation hazard"
    ],
    "source": "cached demo (illustrative)"
  },
  "step_01_gwas": {
    "summary": "Weak/absent germline genetic support for CD276 in lung cancer \u2014 non-disqualifying for an immuno-oncology surface target.",
    "lead_associations": [],
    "interpretation": "No genome-wide-significant germline signal expected for this checkpoint antigen; the CSO treats this as non-disqualifying and weights somatic/stromal evidence instead.",
    "note": "Illustrative cached value for the demo walkthrough, not a live GWAS query."
  },
  "step_02_celltype_expression": {
    "summary": "CD276 expression in the lung reference is enriched in fibroblasts and endothelium, low in T/B lymphocytes.",
    "top_cell_types": [
      {
        "cell_type": "fibroblast",
        "mean_expr": 2.4,
        "pct_expressing": 0.61
      },
      {
        "cell_type": "endothelial cell",
        "mean_expr": 1.1,
        "pct_expressing": 0.28
      },
      {
        "cell_type": "T cell",
        "mean_expr": 0.2,
        "pct_expressing": 0.05
      }
    ],
    "note": "Illustrative cached value for the demo walkthrough, not a live scrna-embedding run."
  },
  "step_03_celltype_specificity": {
    "skill": "celltype-specificity-profiler",
    "gene": "CD276",
    "tau": 0.78,
    "bimodality_coefficient": 0.61,
    "interpretation": "cell-type-specific (tau > 0.7)",
    "summary": "High tau + bimodality \u2192 cell-type-specific expression, a favourable trial-success / safety prior (Zhang et al. 2026).",
    "note": "Illustrative cached value for the demo walkthrough. Run celltype-specificity-profiler --demo for a real (pbmc3k/MS4A1) computation."
  },
  "step_04_offtarget_safety": {
    "skill": "celltype-specificity-profiler",
    "gene": "CD276",
    "summary": "Cell-type-specific expression implies lower broad-tissue off-target risk; main liability is shared fibroblast/stromal expression in normal tissue.",
    "broad_tissue_risk": "moderate-low",
    "note": "Illustrative cached value (specificity re-used for off-target read-out), not a live run."
  },
  "step_05_clinical_trials": {
    "skill": "clinical-trial-finder",
    "summary": "Multiple active B7-H3 ADC programs in solid tumours including NSCLC \u2014 validates the modality and target, but the space is competitive.",
    "example_programs": [
      "B7-H3 ADC (NSCLC, early phase)",
      "B7-H3 ADC (multiple solid tumours)"
    ],
    "note": "Illustrative cached value for the demo walkthrough, not a live ClinicalTrials.gov query."
  },
  "review": {
    "verdict": "re-route",
    "scores": {
      "relevance": 5,
      "evidence": 4,
      "thoroughness": 3
    },
    "gaps": [
      {
        "missing": "spatial validation of the fibroblast/immune signal",
        "route_to": "scrna-orchestrator",
        "why": "The fibroblast enrichment and immune exclusion came from dissociated single-cell data, which loses spatial context. Spatial confirmation of B7-H3-high, immune-excluded niches is needed before synthesis."
      }
    ],
    "experiments": [
      {
        "missing": "malignant-cell vs stromal expression fraction",
        "proposed_experiment": "spatial / single-cell profiling resolving tumour vs stroma",
        "route_to": "scrna-orchestrator",
        "expected_readout": "fraction of B7-H3 signal on malignant cells vs fibroblast/immune stroma",
        "why": "the specificity signal was stromal; an ADC needs a tumour-cell target to be efficacious"
      },
      {
        "missing": "quantified normal-tissue off-target expression",
        "proposed_experiment": "multi-tissue specificity profiling across a normal-tissue atlas",
        "route_to": "cellxgene-fetch + celltype-specificity-profiler",
        "expected_readout": "cross-tissue tau bounding the therapeutic window",
        "why": "single-tissue tau does not bound normal-tissue on-target toxicity"
      }
    ],
    "note": "Illustrative cached reviewer verdict for the demo walkthrough; exercises the one-pass re-route loop and proposes follow-up experiments.",
    "source": "cached demo (illustrative)"
  },
  "step_06_reroute": {
    "skill": "scrna-orchestrator",
    "summary": "Spatial analysis indicates B7-H3-high regions are depleted of infiltrating immune cells \u2014 consistent with an immune-excluded niche.",
    "interpretation": "Supports the immune-exclusion hypothesis the reviewer flagged; clears the gap for synthesis.",
    "note": "Illustrative cached value for the re-route step, not a live spatial run."
  },
  "synthesis": {
    "decision": "CONDITIONAL_GO",
    "confidence": "medium",
    "recommendation": "B7-H3 (CD276) is a credible antibody-drug-conjugate target in lung cancer: germline genetics are weak (expected and non-disqualifying for an IO surface antigen) [step_01], expression is cell-type-specific (high tau + bimodality \u2014 a favourable trial-success/safety prior) [step_03], and prior ADC programs validate the modality [step_05]. Advance an ADC strategy conditional on resolving the stromal-vs-malignant expression split.",
    "target_overview": "B7-H3 / CD276 is an immune-checkpoint surface glycoprotein over-expressed across solid tumours including lung cancer; it is an active antibody-drug-conjugate target with no small-molecule tractability.",
    "liabilities": [
      {
        "risk": "expression is partly stromal (fibroblast), not malignant-cell-intrinsic [step_02, step_03]",
        "mitigation": "confirm tumour-cell expression fraction before committing payload strategy"
      },
      {
        "risk": "trial-success / safety priors are correlational (Zhang et al. 2026), not causal",
        "mitigation": "treat as a prior, not a guarantee; weight against direct evidence"
      },
      {
        "risk": "competitive B7-H3 ADC landscape [step_05]",
        "mitigation": "differentiate on payload / linker / indication"
      }
    ],
    "evidence_gaps": [
      "malignant-cell expression fraction not measured (specificity was stromal)",
      "normal-tissue cross-tissue specificity not quantified (therapeutic window)"
    ],
    "proposed_experiments": [
      {
        "experiment": "spatial / tumour-cell single-cell profiling",
        "expected_readout": "B7-H3 on malignant vs stromal cells",
        "rationale": "resolves the efficacy-critical stromal-vs-malignant question"
      },
      {
        "experiment": "multi-tissue normal-atlas specificity profiling",
        "expected_readout": "cross-tissue tau",
        "rationale": "bounds on-target/off-tumour toxicity for the ADC window"
      }
    ],
    "note": "Illustrative cached synthesis for the demo walkthrough; live runs generate this from real skill outputs via the driving agent (prompts/orchestrator.md)."
  }
};
