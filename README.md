# virtual-biotech-agents

**Replicating "The Virtual Biotech" as composable ClawBio skills — built for the ClawBio Hackathon: Agentic Genomics @ King's (18 Jun 2026).**

This repo reconstructs the multi-agent therapeutic-discovery framework from the bioRxiv preprint **"The Virtual Biotech: A Multi-Agent AI Framework for Therapeutic Discovery and Development"** (Harrison G. Zhang, Peter Eckmann, Jiacheng Miao, Andrew B. Mahon & James Zou, Stanford / PHD Biosciences, 2026 — [doi:10.64898/2026.02.23.707551](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1)) on top of the **[ClawBio](https://github.com/ClawBio/ClawBio)** skill platform.

The paper's system is a "virtual R&D org": a **virtual CSO** breaks queries into sub-tasks, routes them to specialized scientist agents, and a **scientific reviewer** audits results before synthesis. ClawBio mirrors this with the same separation the paper relies on — a **routing layer** (the LLM/CSO) over a **validated, reproducible execution layer** (peer-reviewable skills, each exporting `commands.sh` + `environment.yml` + SHA-256 checksums). So we don't rebuild the stack; we map the org onto ClawBio's ~128 existing skills and contribute the two capabilities that are missing — a single-cell specificity primitive and the CSO orchestration skill itself — as upstream PRs.

---

## The framework (precise architecture from the paper)

**4 scientific divisions · 11 agents · 100+ MCP tools**, spanning 78,726 targets, 39,530 diseases, 14.5M protein–protein interactions, 3M+ genetic credible sets, 100M+ single-cell profiles, 18,119 drugs, and 4B+ drug-perturbation expression measurements (Tahoe-100M).

**Office of the CSO** — `CSO Orchestrator` (plans, routes, synthesizes; runs no analysis itself), `Chief of Staff` (field-awareness briefing via web + infra review), `Scientific Reviewer` (audits methodology/evidence/thoroughness; triggers re-routing).

**Divisions & scientist agents:**
| Division | Agents | MCP data sources |
|---|---|---|
| **Target ID & Prioritization** | Statistical Genetics, Functional Genomics & Perturbation, Single Cell Atlas | GWAS, QTL, gnomAD, ClinVar, dbSNP, pLOF rare variants, PharmGKB; DepMap CRISPR, Tahoe-100M; CELLxGENE Census, Tabula Sapiens v2 |
| **Target Safety** | Bio Pathways & PPI, FDA Safety Officer, Single Cell Atlas | IntAct, Reactome, STRING, SignaLink, GO; OpenFDA, DailyMed; GTEx v8 |
| **Modality Selection** | Target Biologist, Pharmacologist | Human Protein Atlas, Tractability by Modality, Chemical Probes, Mouse KO phenotypes; ChEMBL, Drug Molecular Targets |
| **Clinical Officers** | Clinical Trialist, FDA Safety Officer | ClinicalTrials.gov, PubMed; OpenFDA AE reports; cBioPortal (TCGA) |

**Workflow:** query → CSO clarifies intent + Chief-of-Staff briefing (parallel) → task decomposition & routing → scientist analyses → Scientific Reviewer audit → re-route to fill gaps *or* synthesize report + reproducible codebase.

**Headline result we anchor on:** by curating 55,984 trials (37,075 parallel clinical-trialist agents using a 3-tier ClinicalTrials.gov → PubMed → press-release cascade), the system found **single-cell features of drug targets predict trial success** — cell-type-specific targets were **40% more likely** to progress Phase I→II, **48% more likely** to reach Phase IV, with **32% lower** adverse-event rates. Case studies: **B7-H3** lung-cancer ADC and a terminated **OSMRβ** ulcerative-colitis trial.

---

## How this maps onto ClawBio (assembly, not new code)

| Paper agent | Existing ClawBio skill(s) |
|---|---|
| CSO orchestration | `bio-orchestrator` + our `virtual-biotech-cso` skill |
| Statistical Genetics | `gwas-lookup`, `fine-mapping`, `mendelian-randomisation`, `gwas-catalog-region-fetch`, `eqtl-catalogue-region-fetch` |
| Single Cell Atlas | `scrna-embedding`, `scrna-orchestrator` |
| Functional Genomics & Perturbation | `drug-repurposing-screen`, `crispr-screen-triage` |
| Bio Pathways & PPI | `pathway-enricher`, `turingdb-graph` |
| Target Biologist / Pharmacologist | `omics-target-evidence-mapper`, `target-validation-scorer`, `struct-predictor` |
| FDA Safety / Clinical Trialist | `clinical-trial-finder`, `clinpgx` |
| HEIM / equity (Track 3) | `equity-scorer`, `claw-ancestry-pca` |

---

## ⭐ Primary deliverable: the `virtual-biotech-cso` ClawBio skill (Track 2)

Our submission reproduces the paper's **orchestration** as a first-class ClawBio skill — [`skills/virtual-biotech-cso/`](skills/virtual-biotech-cso/) — submitted upstream as PR #2. It sits **below** `bio-orchestrator` (which routes target-assessment queries to it) and runs the paper's loop over the existing ClawBio skills:

- **Chief of Staff** ([`prompts/chief_of_staff.md`](skills/virtual-biotech-cso/prompts/chief_of_staff.md)) — before any expensive analysis, a briefing: field context, data availability, and the sub-questions worth prioritizing.
- **Scientific Reviewer** ([`prompts/reviewer.md`](skills/virtual-biotech-cso/prompts/reviewer.md)) — after the scientist skills run, audits the outputs (does it answer the query? is the evidence strong? is it thorough?) and either **re-routes once** to fill a gap or clears the CSO to synthesize.

**Keyless, ClawBio-aligned:** the skill makes **no LLM call itself** — like `lit-synthesizer`, it is deterministic routing + report assembly. The three reasoning roles are delegated to the *driving agent* (e.g. Claude Code subagents) via [`prompts/`](skills/virtual-biotech-cso/prompts/) and surfaced as an `agent_tasks` list in `result.json`. No API key required.

```text
query → Chief-of-Staff briefing
      → CSO decomposes & routes → ClawBio skills (via routing.yaml)
      → Scientific Reviewer audit ──gap?──> re-route (once)
                                  └─ok──> synthesize report.md + result.json + reproducible bundle
```

**Scoped to one case study** (B7-H3 lung cancer — 6 routed steps + a reviewer re-route). `clawbio run virtual-biotech-cso --demo` runs **fully offline** from cached, clearly-labelled fixtures; `--live` executes the routed skills through the ClawBio runtime. See [workflows/b7h3_adc_nomination.md](workflows/b7h3_adc_nomination.md).

---

## 🎯 Supporting contribution (also the upstream PR): `celltype-specificity-profiler`

The workflow needs a skill that doesn't exist yet — so building it is both the missing link in the chain **and** a clean PR to ClawBio.

**Gap (verified against all 128 catalog skills):** `scrna-embedding` and `omics-target-evidence-mapper` exist, but **none compute per-gene cell-type specificity metrics** — the tau index and expression-distribution shape that the paper shows predict trial outcomes. We contribute that as a **general, reusable primitive**, with the paper's trial-success scoring behind an optional flag (so the skill isn't locked to one preprint's coefficients).

**`skills/celltype-specificity-profiler/`** — see its [README](skills/celltype-specificity-profiler/README.md).
- **Input:** a gene symbol (+ optional tissue/atlas).
- **Core output (general):** tau cell-type specificity index (0 = ubiquitous → 1 = single-cell-type restricted), **bimodality coefficient** (skewness/kurtosis "on/off" signal — the paper's novel cross-domain transfer from psychometrics, ρ≈0.54 with tau), ranked expressing cell types, per-cell-type expression stats. Clean JSON/CSV.
- **Optional `--trial-prior`:** maps the two features to the paper's published odds ratios for phase-progression / endpoint-success / AE-risk (clearly labeled *Zhang et al. 2026*).
- **Chains:** `omics-target-evidence-mapper` → `celltype-specificity-profiler` → `target-validation-scorer` → `clinical-trial-finder`.
- **Demo:** `clawbio run celltype-specificity-profiler --demo` runs on a bundled real dataset (scanpy `pbmc3k`, gene MS4A1), fully offline. **Open as [ClawBio#307](https://github.com/ClawBio/ClawBio/pull/307).**

Contribution contract (per ClawBio `templates/SKILL-TEMPLATE.md`): `SKILL.md` spec (loud triggers, workflow, ≥3 stress-tested gotchas, citations), Python implementation, `demo_data/`, `tests/`, and a `reproducibility/` bundle.

> **Stretch PR:** a `target-perturbation-hallmark` skill scoring the paper's six Tahoe-100M hallmark signatures (apoptosis, proliferation suppression, cell-cycle arrest, DNA-damage response, stress, resistance) for oncology targets — also absent from the catalog.

---

## 🛠️ Hackathon tracks

**Submitting under Track 2 (Agentic Workflows)**, with the Track 1 skill as the enabling contribution.

2. **Track 2 — Agentic workflow (primary):** the `virtual-biotech-cso` skill above — Chief-of-Staff briefing → routing over ClawBio skills → Scientific-Reviewer audit loop → synthesis — reproducing the B7-H3 ADC nomination (PR #2).
1. **Track 1 — New skill (supporting):** `celltype-specificity-profiler`, the missing single-cell primitive the workflow depends on, submitted upstream as [ClawBio#307](https://github.com/ClawBio/ClawBio/pull/307).
3. **Track 3 — Equity (HEIM, stretch):** have the reviewer call `equity-scorer` so each target assessment also reports cross-population coverage of the single-cell/GWAS references used (the paper's atlases skew to specific ancestries).

---

## 📁 Repository structure

```text
├── skills/
│   ├── celltype-specificity-profiler/  # NEW skill — PR #1 (ClawBio#307)
│   │   ├── SKILL.md                    # ClawBio spec: triggers, workflow, gotchas, citations
│   │   ├── README.md                   # Human-facing overview
│   │   ├── profiler.py                 # tau + bimodality; optional --trial-prior
│   │   └── tests/
│   └── virtual-biotech-cso/            # NEW orchestration skill — PR #2
│       ├── SKILL.md                    # ClawBio spec
│       ├── cso.py                      # the loop: brief → route → reviewer → synthesize (no LLM call)
│       ├── routing.yaml                # query intent → ClawBio skill map
│       ├── prompts/                    # chief_of_staff / reviewer / orchestrator (run by the driving agent)
│       ├── demo_data/b7h3/             # cached, offline B7-H3 fixtures
│       └── tests/
├── workflows/
│   └── b7h3_adc_nomination.md          # Case study: B7-H3 lung-cancer ADC nomination
├── data/                               # Sample configs & schemas
└── README.md
```

> Layout mirrors ClawBio's `skills/<name>/SKILL.md` convention so each skill lifts directly into a ClawBio fork for its PR.

---

## 🚀 Getting started

```bash
# 1. Install ClawBio (provides ~128 existing skills + runtime)
pip install clawbio            # or: /plugin install clawbio  (Claude Code)

# 2. Sanity-check an existing domain skill
clawbio run omics-target-evidence-mapper --demo

# 3. Run the new skill on demo data
clawbio run celltype-specificity-profiler --demo

# 4. Run the full Virtual-Biotech CSO skill (primary deliverable) — offline demo
clawbio run virtual-biotech-cso --demo
# → briefing → routed skill chain → Reviewer re-route → synthesized report.md + result.json
```

## References & links

- Paper: [The Virtual Biotech (bioRxiv)](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1) · open-access mirror: [PMC12970349](https://pmc.ncbi.nlm.nih.gov/articles/PMC12970349/)
- Platform: [ClawBio on GitHub](https://github.com/ClawBio/ClawBio) · [clawbio.ai](https://clawbio.ai/) · [hackathon](https://dorahacks.io/hackathon/clawbio/detail)
- Context: Manuel Corpas — [Agentic Genomics](https://manuelcorpas.com/2026/03/09/agentic-genomics-why-the-future-of-biology-belongs-to-ai-agents/)
- Key methods/data: Tabula Sapiens v2, CELLxGENE Census, Tahoe-100M, Open Targets, ClinicalTrials.gov, tau specificity index, bimodality coefficient
```
