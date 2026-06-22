# Evidence Gap Analysis — what the Virtual Biotech *computes* that Open Targets can't serve

**Purpose.** Go through every line of evidence the Virtual Biotech (Zhang et al. 2026) generates and
classify it as **(R) retrievable** from Open Targets / a public API, or **(C) compute** — a bespoke
analysis on primary data that no aggregator returns as a value. The **(C)** rows are the real gap:
the analyses you'd have to *run*, not look up. This is the grounding for the arena's evidence-card
spec (which axes are API pulls vs the one(s) worth computing) and for an honest "what's novel here"
slide.

> **Terminology.** The paper's "validation" is **in-silico** — computational experiments on *existing*
> primary atlases (single-cell, spatial, perturbation), not new wet-lab. Where a finding is ultimately
> a **hypothesis that only wet-lab can confirm**, it's flagged ⚗️. "Compute (C)" = you must run an
> analysis pipeline; it does not mean generate new biological samples.

---

## 1. Classification key

| Tag | Meaning |
|---|---|
| **R** | Retrieve — a lookup from Open Targets GraphQL or a public API (gnomAD, OpenFDA, ChEMBL, ClinicalTrials.gov, HPA, PDB/AlphaFold). No analysis. |
| **C** | Compute — bespoke analysis on primary data (single-cell, spatial, perturbation, patient-level clinicogenomics). Not served by any aggregator. **← the gap.** |
| **C\*** | Compute, but partially seeded by a retrievable resource (e.g. ENCODE E2G predictions exist, but the locus-/context-specific call is bespoke). |
| ⚗️ | Output is ultimately a hypothesis requiring wet-lab confirmation. |

---

## 2. Full evidence inventory (every analysis in the paper)

### Target Identification & Prioritization

| # | Evidence in the paper | Source | Tag | Why |
|---|---|---|---|---|
| 1 | Genetic association — GWAS + **L2G** + fine-mapped credible sets + QTL colocalization, rolled into a target–disease score | Open Targets | **R** | Paper used *"genetic evidence scores **from Open Targets**"* and *replicated Razuvayevskaya et al.* — it did **not** re-derive GWAS. |
| 2 | Genetic constraint — pLoF observed/expected ratio (B7-H3 = 0.67) | gnomAD (via OT) | **R** | Direct lookup. |
| 3 | Rare-variant burden meta-analyses | OT / public | **R** | Lookup. |
| 4 | Enhancer-to-gene — ENCODE E2G, "41 high-confidence regulatory elements at B7-H3 locus in lung" | ENCODE-rE2G | **C\*** | Predictions exist, but the **locus- and tissue-specific** enumeration/interpretation is a bespoke query, not an OT field. |
| 5 | Target essentiality — CRISPR KO screens | DepMap (partly OT) | **R** | Retrievable; OT surfaces DepMap. |
| 6 | **Drug-perturbation hallmark signatures** — 6 scores (apoptosis induction, proliferation suppression, cell-cycle arrest, DNA-damage response, stress, resistance) from **Tahoe-100M** | Tahoe-100M (HF) | **C** ⚗️ | **Not in OT.** Computed by DE of drug-perturbed vs unperturbed cells → log-FC over hallmark gene sets. The paper *designed* these. |
| 7 | **Cell-type specificity — tau index** (0=ubiquitous → 1=one cell type) | CELLxGENE / Tabula Sapiens v2 | **C** | **Not in OT.** OT baseline expression is **bulk** (GTEx/HPA), tissue-level. tau is computed per gene on a single-cell atlas. The paper's headline feature. |
| 8 | **Expression bimodality coefficient** (skew/kurtosis "on/off" signal; ρ=0.54 with tau) | CELLxGENE / Tabula Sapiens v2 | **C** | **Not in OT.** Novel cross-domain (psychometrics) metric, computed on single-cell distributions. |
| 9 | **Context-specific differential expression** — B7-H3 ↑ in fibroblasts (SCLC log2FC 1.94, FDR 3.0e-6; LUAD 1.46, FDR 1.1e-7), ↓ in T cells; pseudobulk by cell type, disease vs healthy | CELLxGENE atlases (SCLC 92,061 cells/9 donors; LUAD 337,002/69; healthy 86,478/26) | **C** | **Not in OT.** Requires QC, batch correction (Harmony), cell-typing, pseudobulk DE in the **specific** subtype. OT gives one disease-level number; this gives *which cell type, which subtype*. |
| 10 | **Cell-cell communication** — ligand-receptor inference, 152 interactions (SCLC) / 56 (LUAD) specific to B7-H3-high fibroblasts | LIANA+ on the atlas | **C** ⚗️ | **Not in OT.** Inference pipeline output; the 5 signaling classes are interpreted hypotheses needing wet-lab. |

### Target Safety

| # | Evidence | Source | Tag | Why |
|---|---|---|---|---|
| 11 | Pathway / PPI collateral reasoning (IntAct, Reactome, STRING, SignaLink, GO) | databases / OT | **C\*** | Interactions are retrievable; **network propagation / collateral-effect reasoning** over them is bespoke. |
| 12 | Cell-type-specific off-target expression (low normal-tissue → lower broad-tissue AE risk) | CELLxGENE | **C** | Same single-cell computation as #7–9, applied to the safety question. |
| 13 | FDA regulatory safety signals — historical AE reports | OpenFDA | **R** | API lookup. |

### Modality Selection

| # | Evidence | Source | Tag | Why |
|---|---|---|---|---|
| 14 | Druggability / tractability **by modality** | Open Targets | **R** | OT tractability buckets. |
| 15 | Structure — PDB / AlphaFold | PDB, AlphaFold DB | **R** | Lookup. |
| 16 | Subcellular localization — HPA (B7-H3 cell-surface, vesicular) | Human Protein Atlas | **R** | API lookup. |
| 17 | Chemical probes, mouse KO phenotypes | OT / public | **R** | Lookup. |

### Clinical Officers

| # | Evidence | Source | Tag | Why |
|---|---|---|---|---|
| 18 | Clinical trial **records** (NCT metadata) | ClinicalTrials.gov | **R** | API lookup. OT had the trial *list* (55,984). |
| 19 | **Curated trial OUTCOMES** — endpoint success, AE rates, phase progression, source-tracked | 37,075 agents, 3-tier cascade (CT.gov → PubMed → press release) | **C** | **Not in OT or CT.gov structured fields** — *"frequently incomplete, inconsistently reported, or free-text-only."* The paper *built* this dataset. Concordance 89.7%/83.9%/92.4% vs human; 85.3% vs TDC. |
| 20 | **Clinicogenomic survival** — TCGA LUAD (566 pts), B7-H3 quartile Cox PH adjusted age/stage/sex: OS HR 1.62 (1.05–2.48), DSS HR 1.82 (1.06–3.15) | cBioPortal TCGA | **C** | **Not in OT.** Patient-level RNA-seq + survival → a fitted Cox model. A number you compute, not retrieve. |

### Spatial (B7-H3 case)

| # | Evidence | Source | Tag | Why |
|---|---|---|---|---|
| 21 | **Spatial immune exclusion** — Visium (12 LUAD samples, ~65k spots), Cell2Location deconvolution (13 cell types), mixed-effects model (k=6 neighbors) showing B7-H3-high spots deplete neighboring T cells/macrophages/monocytes/DCs | Visium primary data | **C** ⚗️ | **Not in OT.** Heavy bespoke pipeline; the immune-exclusion phenotype is the spatial *validation* of the dissociated-data hypothesis. |

### Cross-cutting statistical experiment

| # | Evidence | Source | Tag | Why |
|---|---|---|---|---|
| 22 | **Feature → trial-success association** — standardized ORs w/ 95% CIs (tau: Phase I→II OR 1.27; reach Phase IV +48%; AE −32%), **1,000-iteration permutation null**, mixed-effects adjusting phase/year/modality/indication, adjusted for genetic evidence, replicated in the 74.6% with no genetic evidence | derived dataset (#7–9 × #19) | **C** | **Not retrievable** — this *is* the paper's discovery, a regression experiment over the two computed layers. |

---

## 3. The gap, distilled

Strip out the **R** rows and the gap is **eight computational capabilities** Open Targets cannot serve:

| Gap | Capability | Primary data | Method / tool | ClawBio skill | 2-day feasibility |
|---|---|---|---|---|---|
| **G1** | Cell-type specificity (tau) | CELLxGENE / Tabula Sapiens slice | tau index per gene | [`celltype-specificity-profiler`](../skills/celltype-specificity-profiler/profiler.py) ✅ exists | **S — do it** |
| **G2** | Expression bimodality | same atlas | skew/kurtosis BC | same skill ✅ | **S — do it** |
| **G3** | Context-specific single-cell DE | disease + healthy atlases | QC → Harmony → pseudobulk DE | [`scrna-embedding`](../skills/) + [`cellxgene-fetch`](../skills/cellxgene-fetch/cellxgene_fetch.py) | **M** |
| **G4** | Cell-cell communication ⚗️ | annotated atlas | LIANA+ ligand-receptor | gap skill | **M–L** |
| **G5** | Drug-perturbation hallmarks ⚗️ | Tahoe-100M | DE → 6 hallmark log-FC scores | gap skill (`target-perturbation-hallmark`, your stretch PR) | **M–L** |
| **G6** | Clinicogenomic survival | cBioPortal/TCGA | Cox PH + quartile stratification | gap skill | **M** |
| **G7** | Spatial immune-exclusion ⚗️ | Visium | Cell2Location + mixed-effects neighborhood | gap skill | **L — skip/demo only** |
| **G8** | Trial-outcome curation | CT.gov + PubMed + web | agent 3-tier cascade → structured JSON | gap skill (`clinical-trial-outcome-curator`) | **L at scale; S for a few** |

⚗️ = output is a hypothesis ultimately needing wet-lab confirmation (the in-silico result is a
prioritization signal, not proof).

---

## 4. What this means for the hackathon arena

**Recommendation: compute G1+G2 only; retrieve everything else from Open Targets.** The evidence card
(§3.3 of [target-arena-research.md](target-arena-research.md)) then splits cleanly:

- **Retrieved (R) axes — Open Targets GraphQL:** genetic association, tractability/modality, known
  drugs / clinical precedent, baseline expression, structure, HPA localization, OpenFDA safety. Cheap,
  reliable, no pipeline risk.
- **Computed (C) axis — the differentiator:** cell-type specificity **tau + bimodality** (G1+G2) live
  via `celltype-specificity-profiler`. This is the **one** gap that is (a) the paper's headline signal,
  (b) already a working skill, and (c) cheap enough for 2 days.
- **Optional stretch if time:** G6 survival (Cox on a cBioPortal cohort) is the next most tractable and
  adds a clinical axis; G5 perturbation hallmarks aligns with your stretch PR but is heavier.
- **Out of scope:** G4 (LIANA+), G7 (spatial) — high effort, low marginal value for a *ranking* card.
  G8 (trial-outcome curation) is its own project; for the arena, retrieve trial *status* from OT and
  curate outcomes for only a handful of hero examples if needed.

**Why this is the right cut:** every **R** row is something Open Targets already did well — re-doing
it adds nothing and burns your 2 days. Every **C** row is a genuine analysis, but only **G1+G2** are
simultaneously *novel*, *paper-headline*, *already-skilled*, and *cheap*. Compute those; retrieve the
rest; be honest in the UI about which card fields are pulled vs computed (provenance tags, as your MET
report already does).

---

## 5. Honest framing for the writeup

> *"The Virtual Biotech's genetics, tractability, drug, and safety axes are aggregations Open Targets
> already serves — and the paper itself sources them from Open Targets. Its genuine computational
> contribution is the **single-cell and perturbation feature layer** (cell-type specificity, bimodality,
> perturbation hallmarks) plus the **curated trial-outcome dataset** — none of which any aggregator
> returns. Our arena retrieves the former and **computes the cell-type-specificity layer live**, which
> is both the paper's headline trial-success signal and the one gap tractable in a 2-day build."*

---

## 6. References
- Zhang, Eckmann, Miao, Mahon, Zou — *The Virtual Biotech* — [bioRxiv 10.64898/2026.02.23.707551](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1)
- Open Targets Platform — [GraphQL API](https://platform.opentargets.org/api)
- Razuvayevskaya et al. — genetic evidence & clinical trial success (Open Targets) — cited as ref [34] in the paper
- Tahoe-100M — perturbational transcriptomics atlas
- CELLxGENE Census · Tabula Sapiens v2 · ENCODE-rE2G · cBioPortal · LIANA+ · Cell2Location

---
*Companion to [target-arena-research.md](target-arena-research.md). Status: review only — confirm the
current Open Targets schema before locking which axes are "R" (it evolves; single-cell expression is
being added).*
