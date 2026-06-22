# Agentic Workflow Ideas — a broad catalog for the hypothesis arena

**What this is.** A wide brainstorm of agentic-workflow patterns (orchestration, memory, verification,
human-in-the-loop, tool use, learning, governance) and how each maps to the target-prioritization
arena. Most are *acknowledge / future-work*; a tagged few are 2-day-feasible. Goal: a menu to pick a
*signature* idea from, and to name-drop the rest as range. Pairs with the four design docs
([arena](target-arena-research.md), [evidence gap](evidence-gap-analysis.md),
[expert gaps](expert-gaps-review.md), [optimization](agentic-hypothesis-optimization.md)).

> **Legend:** ★ = genuinely novel / high-impress · ⚡ = 2-day-feasible · 🔭 = future-work framing.

---

## 1. Orchestration topologies (how agents are wired)

| Pattern | What it is | Map to project |
|---|---|---|
| **Hierarchical** (have it) | CSO → divisions → scientists | the Virtual Biotech baseline |
| **Blackboard** | agents read/write a shared evidence workspace; no fixed order; whoever can contribute, does | a shared **evidence ledger** all division agents append to; the judge reads the board, not siloed messages |
| **Market / auction** | agents *bid* compute on subtasks by expected value | ties to VoI: divisions bid to analyze the hypothesis where they'd add most info |
| **Mixture-of-Agents** (Wang 2024) | N agents answer independently, an aggregator synthesizes | run 3 independent CSO syntheses, aggregate — reduces single-chain variance |
| **Debate / adversarial** ★ | proposer vs skeptic argue to a judge | **the arena match itself** is this; extend to a "bull vs bear" debate per hypothesis |
| **Recursive decomposition** | an agent spawns sub-agents for sub-questions | a division that hits a sub-question spawns a focused analyst |
| **Society-of-personas** ★ | agents role-play distinct stakeholders (oncologist, tox, commercial, regulator) | a **review panel of personas** scores each hypothesis from its lens — richer than generic divisions |

## 2. Memory & accumulated knowledge

| Idea | Why it's cool | Map |
|---|---|---|
| **Persistent evidence cache** ⚡ | a target assessed once is reused across queries — compute amortizes | cache computed tau/cards keyed by (gene, atlas); second query is instant |
| **Episodic memory / case-based reasoning** ★ | "this hypothesis resembles a past one — recall what happened" | retrieve nearest prior assessments to prime the judge |
| **Growing knowledge graph** | provenance + relationships accrue into a reusable graph | every run adds nodes (target–evidence–outcome); the graph *is* the deliverable that compounds |
| **Reflection / lessons memory** (Reflexion, Generative Agents) | the system writes down *why* a past call was wrong and avoids it | a "post-mortem" note after each backtest miss, injected into future judging |
| **Skill library that grows** (Voyager) ★🔭 | agents *write and save* new analysis skills, building a competence library over time | losing-edge analyses become new ClawBio skills — your PRs literally do this |

## 3. Verification, trust & honesty

| Idea | Why | Map |
|---|---|---|
| **Adversarial verifier / red-team** ★⚡ | a skeptic agent tries to *refute* each top finding; survives ≥k refutations | re-judge the podium with a "find the fatal flaw" prompt before publishing |
| **Citation grounding** ⚡ | every claim must point to a source/tool output; uncited claims are dropped | your MET report's provenance tags, enforced as a gate |
| **Self-consistency / ensemble vote** ⚡ | sample the judge N times, take majority; report agreement | already needed for position-bias; report the agreement rate |
| **Abstention / "insufficient evidence"** ★ | the system is allowed to *decline* to rank a hypothesis with too-thin a card | a hypothesis with >X% missing axes gets "UNRANKED — gather more" instead of a fake number |
| **Pre-registration of the analysis plan** ★🔭 | agent commits to *what* it will analyze and *how it will decide* **before** seeing the data — kills p-hacking / hindsight | the CSO writes the decision rubric first; reviewers love this — it's real scientific rigor |
| **Independent replication agent** ★ | a second agent re-derives a key number from scratch; flag if they disagree | re-compute tau via a different path; disagreement = uncertainty flag |
| **Deterministic replay bundle** ⚡ | prompts + models + seeds + data hashes → reproducible run | the "reproducible codebase" claim, made real |

## 4. Human-in-the-loop & steerability

| Idea | Why | Map |
|---|---|---|
| **Clarifying interview** (paper has it) | align on intent before expensive work | CSO asks 2–3 questions up front |
| **Steerable utility weights** ★⚡ | user sets risk appetite (efficacy vs safety vs speed); ranking re-sorts live | the Pareto front from [expert-gaps #3](expert-gaps-review.md) under *the user's* weights |
| **Checkpoint gating** | human approves before the costly stage | "spend $X on the spatial analysis? [y/n]" |
| **Interactive drill-down** ⚡ | click a leaderboard row → see the debate transcript + cards | the Streamlit match-inspector already sketched |
| **Expert-feedback loop** ★🔭 | a human overrides a verdict; the system updates and explains the delta | active learning from expert corrections |

## 5. Tool use & the environment

| Idea | Why | Map |
|---|---|---|
| **Code-as-action** (CodeAct) ★ | agent *writes and runs* analysis code, not just calls fixed tools | the gap from [the earlier discussion](expert-gaps-review.md): compute, don't cite — let the agent write the DE/survival script |
| **Tool synthesis when none exists** ★🔭 | agent builds a missing tool on the fly, then reuses it | your `celltype-specificity-profiler` is this, done by hand |
| **Self-debugging sandbox** ⚡ | run code → read the error → fix → retry | robustness for the live-compute axes |
| **Multi-fidelity tools** | cheap estimate vs exact | single-turn judge vs multi-turn debate (already in plan) |

## 6. Planning, reasoning & hypothesis dynamics

| Idea | Why | Map |
|---|---|---|
| **Plan → act → replan** | explicit, revisable plan | CSO decomposition + Reviewer re-route |
| **Counter-hypothesis generation** ★ | for each target, generate the *strongest case to kill it* | a "bear case" card the judge must weigh — combats confirmation bias |
| **Cross-examination between divisions** ★ | divisions *challenge* each other's evidence, not just report in parallel | the safety agent interrogates the efficacy agent's claim |
| **Ablation / counterfactual reasoning** | "if this evidence flipped, would the rank change?" | sensitivity analysis on each card axis (also a VoI signal) |
| **Hypothesis trees / argument graphs** (ToT/GoT) | structured search over reframings | the Mode-B evolution as a tree of theses |

## 7. Learning & improvement over time

| Idea | Why | Map |
|---|---|---|
| **Outcome-anchored backtest loop** ★⚡ | the leaderboard is validated against real clinical fates | [expert-gaps #1](expert-gaps-review.md) — the credibility anchor |
| **Auto-curated benchmark** ★🔭 | past runs + known outcomes accrue into an eval set | a target-prioritization benchmark as a *second* deliverable |
| **Prompt / rubric evolution** | the judging rubric improves against the backtest | optimize judge weights to maximize backtest AUROC |
| **Meta-learning across diseases** 🔭 | patterns learned in NSCLC transfer to a new indication | the knowledge graph carries priors |

## 8. Observability & governance

| Idea | Why | Map |
|---|---|---|
| **Trajectory trace / agent-flow viz** ⚡ | show the reasoning + tool calls live | the paper's UI does this; Streamlit can too |
| **Cost & latency dashboard** ⚡ | every match's tokens/compute, budget burn-down | pairs with the VoI budget loop |
| **Failure-mode taxonomy** 🔭 | catalog *how* the system errs (leakage, intransitivity, thin cards) | a limitations appendix that impresses |
| **Equity / bias audit** ★ | report ancestry coverage of the evidence behind each rank | Track-3 `equity-scorer`; both ESG *and* a validity check |
| **Confidence-gated claims** ⚡ | downgrade language when evidence is thin | "suggestive" vs "supported" vs "strong" by axis coverage |

---

## Top novel picks (if you want a *signature* beyond the arena)

These are the ones a science-AI audience rarely sees in a demo and that read as real rigor:

1. **Pre-registration of the decision rubric** ★🔭 — commit to "how I'll decide" before seeing data.
   Almost nobody does this in agentic demos; it directly answers the "is this just hindsight?" critique.
2. **Adversarial kill-the-target / bear-case agent** ★⚡ — every top hypothesis must survive a dedicated
   skeptic. Cheap, dramatic, and it visibly fights confirmation bias.
3. **Cross-examination between divisions** ★ — agents *challenge* each other rather than reporting in
   parallel; surfaces conflicts the paper's siloed divisions miss.
4. **Abstention** ★ — letting the system say "insufficient evidence to rank" is more credible than a
   confident number on a thin card.
5. **Growing skill library** ★🔭 — analyses the arena lacks become new ClawBio skills (you already do
   this); framed as a *self-extending competence loop*, it's a strong narrative.

## Hackathon cut (⚡ items, ranked by impress-per-hour)

1. **Backtest loop** (§7) — the anchor.
2. **Adversarial bear-case re-judge of the podium** (§3) — one extra prompt, big credibility.
3. **Steerable utility weights → live Pareto re-sort** (§4) — interactive, memorable.
4. **Provenance + confidence-gated claims** (§3, §8) — you already have the scaffolding.
5. **Persistent evidence cache + trajectory/cost dashboard** (§2, §8) — cheap polish that reads as "real system."

Everything else: name it on a **"design space we considered"** slide. Showing you mapped orchestration
topologies, memory, verification, and governance — and *chose* deliberately — impresses more than any
single feature.

---
*Companion to the four design docs. Status: brainstorm — ⚡ items feed the build; ★/🔭 items feed the
limitations/future-work narrative.*
