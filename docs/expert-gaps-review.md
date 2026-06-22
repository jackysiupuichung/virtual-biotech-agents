# Critical Review — unaddressed issues in target ID & prioritization

**What this is.** A skeptical read of the current plan ([target-arena-research.md](target-arena-research.md),
[evidence-gap-analysis.md](evidence-gap-analysis.md)) *and* the Virtual Biotech paper itself, listing
the target-identification-and-prioritization issues **neither** addresses. These are the questions a
serious **drug-discovery** scientist or an **AI-evaluation** researcher will raise in the first five
minutes. Each item says: what's missing, why it matters, which audience it impresses, and a
hackathon-scoped way to address or at least *acknowledge* it (acknowledging a deep flaw credibly beats
silently shipping it).

> **Scope of blame.** ✱P = the *paper* doesn't address it; ✱A = the *arena* doesn't; most are both.

---

## Top 5 — the ones that change how experts judge the project

### 1. The ranking is never shown to predict reality (no calibration / backtest) ✱A — **AI**
The arena produces a leaderboard by aggregating **LLM preferences**. But Chatbot Arena's Elo is
trusted because **human votes are a ground-truth proxy**; here the "voter" is another LLM with **no
privileged oracle**. Nothing in the plan demonstrates the leaderboard correlates with actual clinical
success — so as it stands it measures *self-consistent preference*, not *correctness*. This is the
single most damaging critique and also the single best opportunity.
- **Fix (feasible in 2 days):** a **retrospective backtest.** Assemble a held-out set of
  target–disease hypotheses with **known historical fates** (approved-for-efficacy vs
  failed-for-efficacy/safety), run them through the arena **blind**, and report **rank vs outcome**
  (AUROC / Spearman, with a permutation null). If specificity-rich, well-supported hypotheses rank
  above known failures, you've shown the arena *predicts*, not just *opines*. This mirrors the paper's
  own tau→trial-success validation, applied to the *composite* ranking. **Do this — it's the headline.**

### 2. Judge circularity / pretraining leakage ✱A — **AI**
The LLM judge already "knows" EGFR and MET succeeded in NSCLC. It can **recall outcomes instead of
reasoning from the card**, inflating apparent quality. Anonymizing the gene name is *not enough* — an
evidence card ("kinase, 500+ ligands, lung adenocarcinoma, approved precedent") **fingerprints** the
target. Experts will ask this immediately.
- **Fix:** quantify leakage rather than hand-wave it. (a) Ablation: does ranking accuracy **survive on
  targets/indications past the model's training cutoff**? (b) Counterfactual cards: **perturb a card's
  values** and check the verdict moves *with the evidence*, not with the recalled gene. (c) Report a
  **leakage-controlled** score. Even just *measuring* this is a strong slide.

### 3. A single Elo scalar collapses a genuinely multi-objective decision ✱P ✱A — **AI + drug discovery**
"Best target" is **not one-dimensional.** It's a Pareto trade-off across **efficacy potential ×
safety window × tractability × commercial differentiation**. Collapsing to one Elo number (a) hides
the trade-off a real portfolio committee needs to see, (b) is gameable, and (c) assumes a single
latent quality dimension that doesn't exist. The paper's CSO *narrates* the trade-off but never
formalizes it; the arena erases it.
- **Fix (feasible — you already have the parts):** your **division judges already produce per-axis
  verdicts.** Keep **one Elo per division** → render a **Pareto front** (e.g. safety vs efficacy) plus
  a *transparent, user-set utility weighting* for the scalar board. "Here's the trade-off, and here's
  the ranking under *your* risk appetite" is far more impressive than a black-box #1.

### 4. Genetics is scored as "support," not **direction** or **dose** ✱P-lite ✱A — **drug discovery**
The actionable output of human genetics isn't "is there a signal" — it's **which way to drug it**
(loss-of-function protective ⇒ *inhibit*; gain-of-function ⇒ the opposite) and the **dose–response
from an allelic series**. The paper gestures at this (B7-H3 LoF o/e = 0.67, interpreted qualitatively)
but neither it nor the arena card encodes **effect direction** or **allelic series** as a structured,
scored axis. Genetics-led pharma (Regeneron, GSK/Open Targets) treat directionality as *the whole point.*
- **Fix:** add a **direction-of-effect** field (protective/risk, with the implied modality direction)
  and, where available, an allelic-series/dose signal. Largely **retrievable** (Open Targets / gnomAD
  constraint + direction). Cheap, and it signals real genetics literacy.

### 5. Specificity (tau) is a success **biomarker**, not a **causal validation** ✱A — **both**
The paper is careful to call tau *correlational*. But the **arena, by ranking on tau, risks rewarding
a proxy** — a cell-type-specific gene is not necessarily a **driver**. Causal dependency (perturbation
→ phenotype) and genetic causality are *distinct* from expression specificity; a clean expression
profile on a bystander gene is a trap. Conflating "clean target" with "validated target" is a classic
target-ID error.
- **Fix:** keep **"is it a driver"** (genetics direction + CRISPR dependency, axes you can retrieve)
  **separate** from **"is it a clean/druggable target"** (specificity, tractability). Don't let
  specificity masquerade as validation in the card or the judge prompt.

---

## Fuller catalog (raise these to show range)

| # | Issue | Audience | Why it impresses | Hackathon move |
|---|---|---|---|---|
| 6 | **Therapeutic window is about *vital* tissues, not generic specificity** — a target specific to heart/CNS is *worse*, not better | drug disc | shows you understand on-target/off-tumor toxicity, not just an index | weight specificity by **essential-organ expression** (GTEx) — retrievable |
| 7 | **Resistance / durability** — single-agent kinase targets fail fast; durability ≠ initial response | drug disc | the MET resistance story is in the paper but unscored | add a resistance-liability flag (known bypass/secondary mutations) |
| 8 | **Cross-species translatability** — human-specific biology / model faithfulness kills programs | drug disc | "is there a faithful model" is a real go/no-go | score mouse-ortholog expression conservation (retrievable) |
| 9 | **Ancestry portability of genetic evidence** — GWAS is ~European; a target validated on EUR may not generalize | drug disc + equity | ties to your Track-3 equity angle; a *validity* issue, not just ESG | report ancestry coverage of the evidence (your `equity-scorer`) |
| 10 | **Survivorship / era confounding in the trial-success priors** — old vs new targets, indication maturity | AI + stats | shows you don't take the paper's ORs as causal | caveat the `--trial-prior`; note it's correlational + era-confounded |
| 11 | **Pleiotropy / cross-indication portfolio value** — the arena fixes one disease; a target's real value is across indications (and pleiotropy is also an AE risk) | drug disc | portfolio thinking impresses biz-dev/translational | note as a multi-disease extension |
| 12 | **Competitive / IP / commercial differentiation absent** — prioritization is never pure biology | drug disc | drug hunters live here; the paper's B7-H3 "differentiation" is unscored | add a "competitive intensity" axis (count of active programs) |
| 13 | **Intransitivity of LLM preferences** (A>B>C>A) **violates Bradley–Terry's assumptions** | AI | sophisticated eval point most demos miss | **measure & report** the transitivity / cycle rate of judge verdicts |
| 14 | **No evidence-uncertainty → rating-uncertainty propagation** — a card built mostly from gaps should produce a *wide* CI, not a confident rank | AI | rigor: uncertainty isn't only match-count noise | widen a hypothesis's prior CI by its **fraction of missing/stale axes** |
| 15 | **Value-of-information evidence acquisition** — decide *which* extra analysis would most change the ranking, run only that | AI/systems | frontier idea; turns a fixed card into an active agent | even a heuristic ("run tau only when it could flip the top-2") is a great slide |
| 16 | **Hypotheses are exogenous** — both paper and arena *rank a human's shortlist*; Co-Scientist *generates* hypotheses | AI | closing generation→ranking→evolution is the ambitious version | demo: derive 1–2 novel target×modality theses from the single-cell data, drop them into the arena |
| 17 | **The "reproducible codebase" claim vs the stochastic LLM layer** — skills are checksummed; agent reasoning isn't deterministic | AI/eng | honesty about what "reproducible" means | version prompts+model+seed; report judge run-to-run variance |

---

## What to actually do in 2 days (you can't build all 17)

Most of these are **acknowledge-don't-build**. But three are both feasible *and* maximally impressive,
and you already have the parts:

1. **#1 Backtest** — the credibility anchor. A held-out set of ~15–20 known-fate hypotheses + an
   AUROC/Spearman of arena-rank vs outcome. *This is the difference between "demo" and "result."*
2. **#3 Per-division Elo + Pareto front** — your division judges already emit per-axis verdicts; don't
   throw them into one scalar. Show the trade-off.
3. **#4 + #5 Direction & driver-vs-clean split** — two retrievable card fields that signal real
   target-ID literacy and cost almost nothing.

Then **explicitly list #2, #6–#17 as "known limitations / future work"** in the writeup. A slide titled
*"What would make this real: calibration, leakage control, multi-objective Pareto, directional
genetics, VoI-driven acquisition"* tells expert judges you see the whole problem — which impresses more
than pretending the demo solved it.

---

## One-paragraph framing for the writeup

> *"The Virtual Biotech assesses one hypothesis at a time; our arena ranks competing hypotheses. But a
> ranking is only as good as its anchor — so we **backtest the leaderboard against known clinical
> outcomes** rather than trusting LLM preference, **decompose quality into a per-division Pareto front**
> rather than a single gameable scalar, and **separate causal validation (directional genetics,
> dependency) from target cleanliness (specificity)** to avoid rewarding well-behaved bystanders. We
> are explicit about what remains open — judge leakage control, value-of-information evidence
> acquisition, ancestry portability, and hypothesis generation — which is the honest frontier of
> AI-driven target prioritization."*

---

*Companion to [target-arena-research.md](target-arena-research.md) and
[evidence-gap-analysis.md](evidence-gap-analysis.md). Status: critical review — items #1, #3, #4, #5
are candidates for the build; the rest are framed as limitations/future work.*
