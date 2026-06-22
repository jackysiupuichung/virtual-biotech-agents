# Agentic Hypothesis Optimization — compute-budgeted information maximization

**What you're describing.** Not "rank a fixed slate once," but a **loop that decides where to spend
the next unit of compute so that the hypotheses' information is maximized** — and *checks back* to see
whether more compute is still worth it. That has a precise name and a 60-year literature: **sequential
experimental design under a budget**, governed by **Value of Information (VoI)**. Below: the unifying
frame, the cross-domain techniques that implement it, and the hackathon-scoped version.

> This is the "cooler agentic pipeline" axis. It's also exactly what separates a *static tournament*
> (run all matches, rank) from an *adaptive scientist* (spend compute where it changes the answer).
> Google's Co-Scientist only gestures at this (Elo plateau); doing it deliberately is novel.

---

## 1. The unifying frame: maximize expected information gain per unit compute

Hold a **belief** over each hypothesis's quality (e.g., a distribution over its latent Elo/utility).
At each step choose the **action** `a` — *gather evidence axis X for hypothesis H*, *run match (H_i,
H_j)*, *refine a losing hypothesis* — that maximizes:

```
        Expected Information Gain (a)            ΔH(belief)                    EIG(a)
score(a) = ─────────────────────────── = E[ entropy reduction ] ; pick argmax ──────
                  cost(a)                                                       cost(a)
```

Then **act → update the belief → re-evaluate VoI → stop when the best remaining `EIG/cost` falls below
a threshold (or the budget is spent).** The "check back if information is maximized" you described *is*
this stopping rule on marginal information. Foundations: **Lindley** (information from experiments,
1956), **Howard** (Value of Information, 1966), **Chaloner & Verdinelli** (Bayesian OED review, 1995),
**Rainforth et al.** (modern Bayesian experimental design, 2024).

Three properties make it tractable:
- **Submodularity / diminishing returns** — information is (usually) submodular, so **greedy** EIG
  maximization is near-optimal (1−1/e). You don't need to plan the whole sequence; greedy is provably good.
- **Multi-fidelity** — cheap noisy estimates first, expensive precise ones only where it matters.
- **Anytime** — the loop yields a usable ranking at *any* budget; more compute only sharpens it.

---

## 2. Cross-domain techniques that implement this (the "other domains" you asked about)

Each row: the field that perfected it, the mechanism, and the map to your hypothesis arena.

| Domain | Technique | Mechanism | Map to your pipeline |
|---|---|---|---|
| **AutoML / HPO** | **Successive Halving / Hyperband** (Jamieson & Talwalkar 2016; Li et al. 2018), **BOHB** (Falkner 2018) | run all configs cheaply, kill the worst half, escalate compute to survivors | judge **all** pairs single-turn → keep top-k → spend **multi-turn debate + extra evidence compute** only on survivors. *Formalizes the "panel only for top contenders" heuristic already in your plan.* |
| **Pure-exploration bandits** | **Best-arm identification** — Sequential Halving (Karnin 2013), LUCB, racing | allocate the next pull to the arm whose outcome most reduces uncertainty about *which is best* | allocate the next **match** to the hypothesis pair near the decision boundary, not random round-robin |
| **Bayesian optimization** | **Acquisition functions** — Expected Improvement, UCB, **Thompson sampling**, knowledge-gradient (Frazier) | balance explore/exploit over a design space | choose which **new hypothesis** (target×modality) to evaluate next when generating, not just ranking |
| **Active learning** | **Query-by-committee** (Seung 1992), uncertainty sampling (Settles 2012), expected model change | query the point the *committee disagrees* on most | your **division panel IS a committee** — compute the next expensive axis where the divisions *disagree* (max VoI) |
| **Decision analysis** | **Value of Information** (Howard 1966) | only run an experiment if its expected effect on the *decision* exceeds its cost | **only compute tau for H if its CI overlaps a rival** (could flip the rank). Don't compute what won't change the answer. |
| **RL** | **Information-Directed Sampling** (Russo & Van Roy 2018) | minimize regret *per bit of information* | principled allocation when matches are expensive |
| **Evolutionary computation** | **Quality-Diversity** — MAP-Elites (Mouret & Clune 2015), novelty search; **FunSearch** (Romera-Paredes, Nature 2024), **AlphaEvolve** (DeepMind 2025) | maintain a *diverse population*, mutate/recombine, keep an elite per niche | the **Mode-B "evolving hypotheses"** loop: mutate losing theses (swap modality / narrow population), keep a *diverse* front not just the single best — avoids collapse to one idea |
| **Game AI** | **MCTS / AlphaZero**, **Tree of Thoughts** (Yao 2023) | search a tree of refinements, expand promising branches | search over **hypothesis refinements**: each node = a reframed thesis, value = arena Elo |
| **Optimal stopping** | secretary problem, **Gittins index** | when to stop searching and commit | the **stopping rule**: halt matches when top-k rank-CIs separate (sequential test) |
| **LLM self-improvement** | **Reflexion** (Shinn 2023), **Self-Refine** (Madaan 2023), self-consistency (Wang 2022), **debate** | critique → revise → re-evaluate; sample-and-verify | the Reviewer→refine→re-enter loop; best-of-N with a verifier |
| **Test-time scaling** | **compute-optimal inference** (Snell 2024), best-of-N (Brown 2024) | spend *more tokens* on *harder* instances | give **close matches** more debate turns; easy blowouts get one cheap pass |

---

## 3. The exact thing you described, made concrete

> *"check back if the hypothesis information is maximised based on compute budget"*

This is a **VoI loop with a plateau stopping rule**. Concretely, three nested policies:

**(a) Which evidence to compute — VoI-gated acquisition.** A hypothesis card has axes of differing
cost (tau is expensive; an Open Targets pull is cheap) and differing *decisiveness*. Compute the
expensive axis **only when its expected information would change the hypothesis's rank** — i.e. when
its current rating CI overlaps a neighbor's. This is the literal "maximize info per compute": a
hypothesis already clearly #1 or clearly last doesn't earn a tau computation.

**(b) Which match to run — boundary-focused allocation.** Don't run a full round-robin. Use
**Sequential Halving / LUCB**: spend matches on pairs whose outcome is *uncertain and rank-decisive*.
A 1500-vs-1200 match teaches you nothing; a 1480-vs-1470 match resolves the podium.

**(c) When to stop — marginal-information plateau.** Track the **expected entropy reduction of the
next-best action**. Stop when it drops below `cost` (VoI ≤ 0) *or* when the top-k leaderboard's
confidence intervals separate (a sequential hypothesis test). This is the rigorous version of
Co-Scientist's "Elo stopped climbing."

Pseudocode:
```
budget = B
init beliefs (Elo±σ) from cheap retrieved axes only
while budget > 0:
    a* = argmax_a  EIG(a) / cost(a)         # over {compute-axis, run-match, refine-hypothesis}
    if EIG(a*) / cost(a*) < τ: break        # ← "check back": marginal info not worth it → STOP
    result = execute(a*); budget -= cost(a*)
    update beliefs(result)
report Pareto front + leaderboard + "stopped because marginal VoI < τ at B-spent"
```

---

## 4. Hackathon-scoped: add ONE of these credibly

You can't build all of §2. The highest impress-per-effort, using parts you already have:

1. **Multi-fidelity allocation (Successive Halving), cite Hyperband.** Single-turn judge on all pairs →
   keep top-⌈n/2⌉ → multi-turn debate + compute tau **only** for survivors. This is a 1-paragraph
   policy change to your existing plan, but now it's a *named, principled* compute-allocation scheme,
   not an ad-hoc "top contenders" rule. **Do this.**
2. **VoI-gated tau computation.** Compute the expensive single-cell axis for a hypothesis **only if its
   rating CI overlaps a rival's.** Log "skipped tau for H (rank already decided) — saved X compute."
   That log line *is* the demo: it visibly shows the system spending compute where it matters.
3. **A plateau stopping rule.** Stop matches when the top-3 CIs separate; report
   *"converged after M/総 matches (Y% of full round-robin) — VoI exhausted."* Pairs beautifully with
   the §3 backtest in [expert-gaps-review.md](expert-gaps-review.md).

Together these turn "a tournament" into **"an agent that allocates a compute budget to maximize
decision-relevant information and knows when to stop"** — which is precisely the frontier framing that
impresses both AI-systems and decision-science reviewers.

---

## 5. How this composes with the rest of the plan

- It **subsumes** the §4 cost table in [target-arena-research.md](target-arena-research.md): instead of
  a fixed call budget, compute is *allocated adaptively* to stay under it.
- It **operationalizes** the Mode-B "evolving hypotheses" (§3.3 there) as **quality-diversity search**
  (MAP-Elites): refine losers, keep a diverse elite front.
- It's the **mechanism** behind expert-gap #15 (value-of-information) and #14 (uncertainty
  propagation) in [expert-gaps-review.md](expert-gaps-review.md) — those weren't loose ideas, they're
  this framework.

---

## 6. References (concept → canonical source)
- VoI / OED: Lindley 1956; Howard 1966; Chaloner & Verdinelli 1995; Rainforth et al. 2024 (*Modern Bayesian Experimental Design*)
- Submodular greedy: Nemhauser, Wolsey, Fisher 1978; Krause & Golovin (submodular optimization)
- Hyperband / Successive Halving: Jamieson & Talwalkar 2016; Li et al. 2018; BOHB: Falkner et al. 2018
- Best-arm identification: Karnin et al. 2013 (Sequential Halving); LUCB
- Bayesian optimization / acquisition: Shahriari et al. 2016 (review); Thompson 1933; Frazier (knowledge-gradient)
- Active learning: Settles 2012 (survey); Seung et al. 1992 (query-by-committee)
- Information-Directed Sampling: Russo & Van Roy 2018
- Quality-Diversity / evolution: Mouret & Clune 2015 (MAP-Elites); Romera-Paredes et al. 2024 (FunSearch); DeepMind 2025 (AlphaEvolve)
- Tree search / reasoning: Yao et al. 2023 (Tree of Thoughts)
- LLM self-improvement: Shinn et al. 2023 (Reflexion); Madaan et al. 2023 (Self-Refine); Wang et al. 2022 (self-consistency)
- Test-time compute: Snell et al. 2024; Brown et al. 2024 (best-of-N)
- AI Co-Scientist (Elo tournament, evolution): Gottweis et al. 2025 — [arXiv:2502.18864](https://arxiv.org/abs/2502.18864)

---
*Companion to [target-arena-research.md](target-arena-research.md), [evidence-gap-analysis.md](evidence-gap-analysis.md),
[expert-gaps-review.md](expert-gaps-review.md). Status: design/research — §4 items are build candidates.*
