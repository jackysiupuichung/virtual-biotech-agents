# Therapeutic-Hypothesis Arena — Research & Design Review

**Goal:** emulate *The Virtual Biotech* (Zhang et al. 2026) on a hackathon scale, replacing its
absolute "weigh-the-evidence" synthesis with a **ranking arena** — competing **therapeutic
hypotheses** for a disease are pitted pairwise, an LLM (or panel) judges each match, and a rating
system produces a **leaderboard**.

> **Unit of analysis — read first.** The player is **not a bare target/gene** — it is a fully framed
> **therapeutic (target × disease × modality) hypothesis** (see §1.2). The paper's own outputs are
> hypotheses of this shape ("B7-H3, via an ADC, in LUAD/SCLC, exploiting stromal overexpression"),
> and Co-Scientist likewise ranks *hypotheses*. This reframing is load-bearing for §3.3 (what a card
> contains) and §7 (whether cards may evolve).

**Scope constraints (fixed for this build):**
- **5–15 candidate hypotheses per disease** (drives all the cost/feasibility math below).
- **2-day hackathon** timeline.
- **Deliverable:** standalone Python + **Streamlit** live-leaderboard UI (not a ClawBio skill this time).
- This document is **for review only** — it surveys the literature and lays out the design options
  ("research all / compare all"). No code is built yet.

> **TL;DR recommendation (details in §4–§6):** run a **round-robin (n≤10) or Swiss (n=12–15)**
> schedule, judge each match with a **division panel** of LLM judges (order-swapped to kill position
> bias), animate **Elo** live in Streamlit for the demo, but compute the **final** leaderboard with a
> **Bradley–Terry** fit (stable ranking + confidence intervals). This is exactly the path the two
> most relevant precedents converged on — Google's AI Co-Scientist (Elo tournament of LLM debates)
> and LMArena (Elo → Bradley–Terry for the published board).

---

## 1. Literature review

### 1.1 Google "AI Co-Scientist" — the direct precedent

[*Towards an AI co-scientist*](https://arxiv.org/abs/2502.18864) (Gottweis, Natarajan et al., Google,
Feb 2025; lab-validated results published in [Nature, May 2026](https://www.nature.com/)) is the
closest existing system to what you're proposing. It is a multi-agent system (built on Gemini 2.0)
whose agents are **Generation → Reflection → Ranking → Evolution → Proximity → Meta-review**.

The piece you're reinventing is the **Ranking agent**, and it works almost exactly like your idea:

- It runs an **Elo-based tournament** in which hypotheses compete via **pairwise comparisons** that
  take the form of **simulated scientific debates** between the two ideas.
- **Winners gain Elo points, losers lose them; upsets** (a lower-rated hypothesis beating a
  higher-rated one) **produce larger rating changes** — standard Elo dynamics.
- Confirmed quotes from Google's writeup
  ([research.google blog](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/)):
  *"The system's self-improvement relies on the Elo auto-evaluation metric derived from its
  tournaments"* and *"higher Elo ratings positively correlate with a higher probability of correct
  answers."* The tournament is iterative — *"as the system spends more time reasoning and improving,
  the self-rated quality of results improve."*
- The **Proximity agent** builds a similarity graph over hypotheses; this is used for **matchmaking**
  (prefer comparing *similar* hypotheses, where a debate is most informative — analogous to Swiss
  pairing rather than random).
- Reported design detail (from the paper / secondary summaries, not directly quotable from the
  gated PDF here): **top-ranked** hypotheses get **multi-turn** debates, while lower-stakes pairs get
  a cheaper **single-turn** comparison — a cost-control pattern worth copying.

**What this validates for you:** an Elo/tournament + LLM-judge approach to *ranking scientific
candidates* is a peer-reviewed, Nature-published design, not a gimmick. The honest framing for your
submission: *"We apply the AI Co-Scientist's Elo-tournament ranking idea to the Virtual Biotech's
target-prioritization problem."*

> ⚠️ **Sourcing caveat:** the arXiv PDF and the UQAM mirror are bot-gated; the mechanics above come
> from Google's own blog plus search-surfaced summaries. Before citing exact Elo constants (K-factor,
> initial rating) in the final report, open the PDF in a browser and confirm — I could not retrieve
> those numbers directly.

### 1.2 The Virtual Biotech (the system you're scaling down)

[Zhang et al. 2026](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1) — CSO orchestrator →
four scientist divisions (Target ID, Target Safety, Modality, Clinical) → Scientific Reviewer audit →
synthesis. Crucially, its assessment is **absolute and narrative**: each hypothesis gets a reasoned,
multi-scale evidence dossier; the CSO *weighs* it. **There is no tournament and no head-to-head
comparison** — every verdict is rendered on one hypothesis in isolation. So your arena is a genuine
*methodological* contribution on top of the paper, not a re-implementation: you convert the paper's
qualitative, single-hypothesis "weigh the divisions" step into a **quantified, reproducible pairwise
ranking** across hypotheses. Its division structure maps cleanly onto a **panel of division judges**
(§3.1, Option A).

#### Unit of analysis: the therapeutic (target × disease × modality) hypothesis

The paper's atomic unit is **not a gene** — it is a fully-specified **therapeutic hypothesis**:

> target × disease × **modality** × **mechanism/direction** × **patient stratum**
> e.g. *"**B7-H3**, antagonized via an **ADC**, in **LUAD/SCLC**, exploiting **stromal/CAF
> overexpression**, with a **c-Met-high–style selection biomarker**."*

This is exactly what the paper *outputs* (B7-H3→ADC with the stromal-vs-malignant liability;
OSMRβ→mAb with biomarker-guided enrollment) and exactly what Co-Scientist ranks (hypotheses, not
entities). Two consequences:

- **The "player" is a claim, not a fixed entity.** A *target* is immutable; a *hypothesis* can be
  refined (swap modality, narrow the population, add a biomarker). This is why the "freeze the card"
  decision is a **pragmatic** choice between two legitimate modes, not an ontological given (§3.3, §7).
- **The arena can rank things bare targets can't** — including **competing strategies for the *same*
  target** ("MET via TKI" vs "MET via ADC" vs "MET via mAb"), turning the paper's *Modality Selection*
  division into a contest, as well as cross-target comparisons. Every leaderboard entry is a complete
  go-to-clinic thesis.

The judge's match question is therefore: *"Given two framed therapeutic hypotheses for the same
disease, which is the more plausible / better-de-risked program?"* — the comparative judgment neither
paper's orchestrator makes.

### 1.3 Chatbot Arena / LMArena — how to do "arena ranking" correctly

[LMSYS Chatbot Arena](https://www.lmsys.org/blog/2023-12-07-leaderboard/) is the reference
implementation of large-scale pairwise ranking. Two lessons transfer directly:

1. **They started on online Elo and migrated to the [Bradley–Terry model](https://arxiv.org/html/2412.18407v1).**
   Bradley–Terry (BT) is the maximum-likelihood estimate of the same latent strength Elo
   approximates, but computed **centrally over all matches at once**, so it is **order-independent**
   and yields **confidence intervals**. LMSYS: *"The transition from the online Elo system to the
   Bradley–Terry model gives us significantly more stable ratings and precise confidence intervals."*
2. **Confidence intervals matter.** Top-ranked items routinely sit within **overlapping CIs**, i.e.
   their exact rank order is partly noise. For a *target* leaderboard this is the headline honesty
   feature: "MET and EGFR are statistically tied at the top" is a more defensible claim than "MET is
   #1." Your scale (5–15 candidates, all-pairs feasible) is *ideal* for BT — it shines exactly when
   you have dense pairwise data on few players.

### 1.4 LLM-as-a-judge — reliability and the bias you must mitigate

The judge is where most of your risk lives. From the
[MT-Bench paper](https://arxiv.org/pdf/2306.05685) and
[position-bias studies](https://arxiv.org/abs/2406.07791):

- **Pairwise comparison is the *most reliable* LLM-judge mode** (more consistent than absolute
  scoring) — good news for an arena. Strong judges reach **>80% agreement with humans**.
- **Position bias is real and large:** GPT-4 flipped its preferred answer when the two options were
  swapped on **~⅓ of cases**. **Mandatory mitigation:** judge **every match in both orders** and only
  count a result when the verdict is **consistent**; ties/inconsistencies go to a tiebreak or are
  recorded as draws. This **doubles** judge calls — budget for it (§4).
- Other known biases to note in the writeup: verbosity/length bias, self-preference bias. For a
  target arena, also watch **name/familiarity bias** (judge favors well-known targets like EGFR
  regardless of the evidence card) — mitigate by having judges compare **anonymized evidence cards**,
  not gene names.

### 1.5 Rating-system background (for the methods section)

- **Elo:** online, sequential, one update per match; `R' = R + K·(S − E)`,
  `E = 1/(1+10^((R_opp−R)/400))`. Simple, animatable, **order-dependent**, no native uncertainty.
- **Bradley–Terry:** `P(i beats j) = p_i/(p_i+p_j)`; fit latent strengths by MLE over all matches.
  Order-independent, gives CIs, needs the full match set up front (fine for round-robin/Swiss).
- **[TrueSkill](https://www.microsoft.com/en-us/research/project/trueskill-ranking-system/)** (Herbrich
  et al., Microsoft): Bayesian skill = `μ ± σ`; converges in **few games**, supports >2 players and
  partial schedules. Best if you *can't* run all pairs and want principled uncertainty early.

---

## 2. Pipeline overview

```text
 disease + 5–15 candidate therapeutic hypotheses  (target × disease × modality)
        │
        ▼
 ① Evidence cards   ── per hypothesis: a frozen, anonymized plausibility dossier (§3.3)
        │
        ▼
 ② Schedule         ── which pairs play: round-robin / Swiss / proximity (§3.2 / §4)
        │
        ▼
 ③ Judge each match ── division panel / single CSO / rubric, order-swapped (§3.1)
        │
        ▼
 ④ Rating           ── Elo live  +  Bradley–Terry final leaderboard with CIs (§3.2)
        │
        ▼
 ⑤ Reviewer audit   ── sanity-check leaderboard vs known clinical reality (re-route if absurd)
        │
        ▼
 Streamlit live leaderboard + per-match debate transcripts + reproducible result.json
```

---

## 3. Design dimensions — options compared

### 3.1 The judge (who decides each match)

| Option | How it works | Pros | Cons | Calls / match | Paper-faithfulness |
|---|---|---|---|---|---|
| **A. Division-judge panel** ✅ | 4 LLM judges (Genetics, Single-Cell, Safety, Clinical); each picks the winner *on its axis*; weighted/majority vote decides the match | Maps 1:1 onto the Virtual Biotech divisions; best demo narrative; per-axis transparency; diversity reduces single-judge bias | 4× cost; need a tie/aggregation rule; weights are a design choice to defend | 4 (×2 for order = 8) | **Highest** |
| **B. Single CSO judge** | One model sees both cards, picks winner + rationale | Cheapest, simplest, fastest to build | One model's biases dominate; less "multi-agent" story | 1 (×2 = 2) | Medium |
| **C. Deterministic rubric** | Weighted-sum of card fields; higher total wins, no LLM | Free, instant, fully reproducible | No reasoning, no "agent"; just re-derives an absolute score | 0 | Low |

**Recommendation:** **A**, with **C as a baseline** run alongside it — showing "the agent panel
disagrees with the naive rubric on X% of matches, and here's why" is a strong slide and free
ablation. Always judge **both orders** (§1.4). For cost control, copy Co-Scientist: use **single-turn
panel votes** for most pairs and reserve **multi-turn debate** for the **top-quartile contenders**
(the matches that actually decide the podium).

### 3.2 The rating math (how match outcomes → leaderboard)

For **n = 5–15**, full round-robin is `C(n,2)` matches = **10 (n=5) → 28 (n=8) → 45 (n=10) → 66
(n=12) → 105 (n=15)**. This is small enough that you are **not** forced into online Elo's
approximations.

| Option | Best when | Pros | Cons |
|---|---|---|---|
| **Elo (online)** | live demo animation | Leaderboard visibly climbs match-by-match — great on stage | Order-dependent; final ranks wobble; no CIs |
| **Round-robin → win-rate** | n ≤ 10 | Dead simple, every pair plays, intuitive | Ignores strength-of-schedule; ties common; no CIs |
| **Bradley–Terry** ✅ | n = 5–15, dense pairs | Order-independent, **CIs**, accounts for *who* you beat; LMArena's choice | Needs all matches first (fine here); ~30 lines to fit |
| **TrueSkill** | partial schedule / n=15 with budget limits | Uncertainty after few games; principled early stopping | Heavier mental model to explain to judges |

**Recommendation (hybrid — gets you both the show and the rigor):**
1. Pick the **schedule** by size: **round-robin for n ≤ 10**; **Swiss (~4 rounds, ≈30 matches) for
   n = 12–15** to keep cost bounded, optionally **proximity-paired** (Co-Scientist style) so similar
   targets meet.
2. **Animate Elo live** in Streamlit as matches stream in (the demo wow-factor).
3. Compute the **final published leaderboard with Bradley–Terry + 95% CIs**, and **call out
   statistical ties**. One paragraph in the report explains why (cite LMArena §1.3).

### 3.3 The evidence cards (what each hypothesis brings to a match)

A card is the **frozen plausibility dossier for one fully-specified therapeutic hypothesis** (§1.2) —
i.e. the Virtual-Biotech per-hypothesis assessment, captured as structured fields. **Content source**
options:

| Option | Source | Pros | Cons |
|---|---|---|---|
| **A. Scorer axes + live single-cell** ✅ | reuse [`target-validation-scorer`](../../clawbio-fork/skills/target-validation-scorer/target_validation_scorer.py) 5 axes (disease assoc, druggability, chem matter, clinical precedent, structure) **+** live tau/bimodality from [`celltype-specificity-profiler`](../skills/celltype-specificity-profiler/profiler.py) | Reuses existing code; lands the paper's *headline* single-cell feature as a **computed** number; ~half the card is real | Some axes still cached/curated |
| **B. Paper-faithful, all divisions live** | compute every axis live (CELLxGENE, gwas-lookup, clinical-trial-finder…) | Most rigorous, fully "computed" | High data-wiring risk for 2 days; likely the thing that sinks the timeline |
| **C. LLM-generated from web search** | agent writes cards from literature | Fastest to fill 15 cards | Borrowed, not computed — the weakness already seen in `met_nsclc_report.md`; judges then grade prose, not data |

**Recommendation:** **A** as the spine, with **C as automatic fallback** for any axis where the live
data isn't wired in time (clearly flagged per-field, the way your MET report already does provenance).
Anonymize the card (drop the gene/target name) before it reaches the judge to blunt familiarity bias (§1.4).

#### Cards are frozen per hypothesis (and why this is a *choice*)

For the hackathon, **compute each card once, freeze it, and reuse it identically in every match** that
hypothesis plays. The reasons are **pragmatic, not ontological** — a hypothesis *could* change
(unlike a gene):

- **Rating validity** — Elo/Bradley–Terry assume each player has a *fixed latent strength*; a mutating
  card makes its rating meaningless.
- **Fairness** — every opponent faces the same dossier.
- **Reproducibility** — freeze N cards ⇒ the only stochasticity left is the judge; same cards + seed =
  same board.
- **Cost** — card generation runs **N times** (once per hypothesis), not `C(n,2)` times.

What is *constant*: card content. What *varies* across matches: the opponent, the judge's verdict
(comparative, so a card can win vs a weak rival and lose vs a strong one), presentation order
(order-swapped, §1.4), and the rating itself.

Two legitimate modes — pick **A** for 2 days:

| Mode | Card | Faithful to | Hackathon |
|---|---|---|---|
| **A. Fixed slate** ✅ | **constant** — enumerate N hypotheses up front, freeze one dossier each, rank them | Co-Scientist's tournament *within a round* | **build this** |
| **B. Evolving hypotheses** | **not constant** — a losing hypothesis triggers a refinement pass (reframe modality/population/biomarker) and re-enters the arena | Co-Scientist's *Evolution agent* / full loop | future work (§7) |

> Because the unit is a *hypothesis*, Mode B is a **principled, paper-faithful extension**, not a
> gimmick — but it breaks rating stationarity (needs Elo resets / re-fit) and is out of 2-day scope.

---

## 4. Cost & feasibility math (the number that decides the build)

Judge calls ≈ **(matches) × (judges) × (2 for order-swap)**. Multi-turn debates cost ~2–4× a
single-turn call.

| n | Round-robin matches | Swiss matches | Single-judge, order-swapped | **Division panel (×4), order-swapped** |
|---|---|---|---|---|
| 5 | 10 | — | 20 | **80** |
| 8 | 28 | — | 56 | **224** |
| 10 | 45 | — | 90 | **360** |
| 12 | 66 | ~24 | 132 / 48 | **528 / 192** |
| 15 | 105 | ~30 | 210 / 60 | **840 / 240** |

**Reading this table:** the full-fat config (n=15, round-robin, 4-judge panel, order-swapped) is
**~840 LLM calls** — too slow/expensive to run live on stage and risky to debug in 2 days. **Keep it
tractable** by combining: **Swiss instead of round-robin at n≥12**, **single-judge for the bulk +
panel only for top contenders**, and **caching judged pairs**. A sane demo target is **≤250 judge
calls**, e.g. *n=10, round-robin, single-judge order-swapped (90) + panel re-judge of the top-6's 15
pairs (120) ≈ 210 calls.*

---

## 5. Recommended architecture (one concrete combo)

> **Disease:** NSCLC (reuses your MET + B7-H3 work). **Hypotheses:** 8–10 framed
> target×modality theses (e.g. *MET→ADC*, *MET→TKI*, *CD276/B7-H3→ADC*, *EGFR→TKI*, *KRAS→small
> molecule*, *ERBB2→ADC*, *TROP2→ADC*, *ALK→TKI*, …) — note this deliberately includes **competing
> modalities for the same target** so the board ranks *strategies*, not just genes. **Cards:** §3.3-A
> (scorer axes + live tau, anonymized, **frozen** per hypothesis).
> **Schedule:** round-robin (45 matches at n=10). **Judge:** §3.1-A division panel, order-swapped,
> single-turn for all + multi-turn debate for top-quartile pairs; **rubric baseline** run alongside.
> **Rating:** Elo animated live → **Bradley–Terry final board with CIs**. **Audit:** Reviewer flags
> if the board contradicts known reality (MET/B7-H3/EGFR should land high — built-in sanity check).
> **UI:** Streamlit.

**Streamlit UX sketch:**
```text
┌─ Target Arena: NSCLC ─────────────────────────────────────┐
│ Leaderboard (Bradley–Terry, 95% CI)        [▶ run matches] │
│  1. EGFR    1540 ±48  ▓▓▓▓▓▓▓▓▓▓                            │
│  2. MET     1505 ±55  ▓▓▓▓▓▓▓▓▓   ← CI overlaps #1 (tie)   │
│  3. B7-H3   1460 ±70  ▓▓▓▓▓▓▓▓                             │
│  ...                                                       │
│  [Elo-over-rounds animated line chart]                     │
├─ Match inspector ─────────────────────────────────────────┤
│ MET vs B7-H3   panel 3–1                                   │
│  Genetics  → B7-H3  · SingleCell → MET · Safety → MET ...  │
│  [expand debate transcript]   [rubric said: MET]           │
└───────────────────────────────────────────────────────────┘
```

---

## 6. Two-day plan

**Day 1 — engine + offline correctness (no live LLM yet):**
- Evidence-card schema + loader; build 8–10 cards (§3.3-A; cache axes, stub tau).
- Scheduler (round-robin; Swiss optional), **deterministic rubric judge** (§3.1-C), Elo + Bradley–Terry.
- Streamlit skeleton wired to the rubric run end-to-end. **Demo-safe checkpoint reached.**

**Day 2 — agents + polish:**
- Swap in the **LLM division panel** (§3.1-A) with **order-swap consistency**; keep rubric as baseline ablation.
- Compute **live tau/bimodality** for ≥2 targets so at least one real axis is computed, not cited.
- Bradley–Terry CIs + "statistical tie" callout; Reviewer sanity-audit; record `result.json` (reproducible).
- Rehearse the ≤250-call config so it runs in front of judges.

---

## 7. Open questions / risks to resolve before building

1. **Division-judge weighting** — equal vote, or disease-aware weights (e.g. up-weight Clinical for a
   crowded indication)? Defensible either way; pick one and justify it.
2. **Draws** — order-swap inconsistency → draw, or best-of-3 tiebreak? Draws are cleaner; BT handles them.
3. **Where do the hypotheses come from** — fixed curated slate of target×modality theses (recommended
   for the demo) vs CSO *generating* them live from the query (flashier, riskier; this is Co-Scientist's
   Generation agent). Also decide whether the slate includes **competing modalities for one target**
   (recommended — it's the most novel comparison and showcases the *hypothesis* unit, §1.2).
4. **Frozen vs evolving cards (Mode A vs B, §3.3)** — confirmed **frozen** for 2 days. **Evolving
   hypotheses** (a losing thesis is refined and re-enters) is the principled, Co-Scientist-faithful
   extension and the headline "future work" line — but it breaks rating stationarity, so it stays out
   of hackathon scope.
5. **Confirm Co-Scientist Elo constants** from the actual PDF before quoting them (§1.1 caveat).
6. **Is Streamlit final?** It's chosen here, but note it diverges from the ClawBio-skill submission
   format your earlier PRs use — confirm the hackathon track accepts a standalone app.

---

## 8. References

- Gottweis, Natarajan et al. — *Towards an AI co-scientist* — [arXiv:2502.18864](https://arxiv.org/abs/2502.18864) · [Google blog](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) · [DeepMind blog](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
- Zhang, Eckmann, Miao, Mahon, Zou — *The Virtual Biotech* — [bioRxiv 10.64898/2026.02.23.707551](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1)
- LMSYS — *Chatbot Arena / Elo system update* — [LMSYS blog](https://www.lmsys.org/blog/2023-12-07-leaderboard/) · *A Statistical Framework for Ranking LLM-Based Chatbots* — [arXiv:2412.18407](https://arxiv.org/html/2412.18407v1)
- Zheng et al. — *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* — [arXiv:2306.05685](https://arxiv.org/pdf/2306.05685)
- *Judging the Judges: position bias in pairwise LLM-as-a-judge* — [arXiv:2406.07791](https://arxiv.org/abs/2406.07791)
- Herbrich, Minka, Graepel — *TrueSkill* — [Microsoft Research](https://www.microsoft.com/en-us/research/project/trueskill-ranking-system/)

---
*Status: research/design review for the target-prioritization arena. No implementation yet —
decisions in §7 should be locked before Day 1.*
