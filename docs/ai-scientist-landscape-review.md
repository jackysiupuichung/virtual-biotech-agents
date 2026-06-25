# AI-Scientist landscape — and where virtual-biotech-cso sits

**The question that prompted this:** *"Right now I feel like I am simply calling a pipeline."*

That feeling is correct and diagnosable. This doc (1) reviews the relevant systems —
**TxAgent** (the arXiv 2503.10970 paper, which is *not* a survey of AI scientists), plus the
real autonomous-science landscape (Sakana AI Scientist, Google Co-Scientist, Biomni, Robin,
Coscientist, Kosmos); (2) places them and our `virtual-biotech-cso` on a single autonomy
spectrum; (3) names the exact lines of our code that make it pipeline-shaped; and (4) gives a
concrete path to move agency out of `routing.yaml` and into the reasoning roles we already have.

---

## 1. TxAgent (arXiv 2503.10970) — what the cited paper actually is

A frequent misread: **2503.10970 is *TxAgent: An AI Agent for Therapeutic Reasoning Across a
Universe of Tools*** (Gao, Zhu, Kong, Noori, Su, Ginder, Tsiligkaridis, Zitnik). It proposes
**no** taxonomy of autonomy and surveys **no** "AI Scientist" systems. It is a single,
fine-tuned **therapeutic-reasoning agent** — important to compare against, but not the survey
the title might suggest.

**Architecture:**

- **Backbone**: an 8B Llama-3.1 model fine-tuned on **TxAgent-Instruct** (~378K multi-step
  reasoning traces). The agent *loop behaviour is trained in*, not prompted.
- **ToolUniverse**: a registry of **211 verified biomedical tools** (all FDA-approved drugs
  since 1939, Open Targets, interaction/contraindication lookups).
- **ToolRAG**: it does **not** stuff 211 tool schemas into context. A retriever selects a
  candidate tool subset per step from a tool-description embedding store → tool selection is
  **learned and dynamic**.
- **Loop**: interleaves `Thought → ToolCall → Observation → …` until a final answer; can see
  that an observation contradicts its hypothesis and **re-plan**.

**Result:** the 8B agent hits **92.1%** on open-ended drug reasoning, beating GPT-4o and
out-reasoning DeepSeek-R1 (671B) on structured multi-step tasks.

**What makes it more than a pipeline:** the *tool sequence is not predetermined.* The same query
can yield different tool chains depending on intermediate observations. Control flow is
**emergent from the policy**, not authored by an engineer.

**What is still pipeline-ish:** it is a **reasoner over a fixed tool universe.** It does not form
genuinely novel hypotheses, design experiments that don't already exist as a tool, or carry a
world-model across runs. It *answers* therapeutic questions superbly; it does not *discover*.

---

## 2. The actual "AI Scientist" landscape

These are the systems that target the part TxAgent doesn't — hypothesis generation, experiment
design, and closing the loop. They define the high end of the spectrum.

| System | What it automates | Agentic core | Closes the loop? |
|---|---|---|---|
| **Sakana AI Scientist v2** (arXiv 2504.08066) | Whole ML-paper lifecycle: idea → code → experiments → manuscript → self-review | **Agentic tree search** over experiment plans, an experiment-manager agent, VLM figure-critique loop | Yes (in-silico). One manuscript passed an ICLR-workshop peer review — first fully AI-generated paper to do so |
| **Google Co-Scientist** (*Nature* 2026, s41586-026-10644-y) | Hypothesis generation & ranking | **Multi-agent tournament**: generator, critic, ranker (Elo via pairwise debate), evolution, meta-review agents | Partially — lab-validated (AML drug repurposing, liver fibrosis); proposes, humans/wet-lab confirm |
| **Biomni** (bioRxiv 2025.05.30.656746) | General biomedical task execution across 25 subfields | Single super-agent over **150 tools / 105 packages / 59 databases**, no task-specific prompt tuning | Generates hypotheses & runs analyses; not a standing discovery loop |
| **Robin** | Therapeutics discovery cycles | Lit-search + data-analysis agents proposing evidence-based hypotheses | Yes — proposed a novel drug candidate for blindness. Noted limitation: weak cross-agent context sharing |
| **Coscientist** (Boiko et al., *Nature* 2023) | Wet-lab chemistry | GPT-4 agent that planned & executed a Pd-catalysed cross-coupling on real hardware | Yes — physical experiment loop |
| **Kosmos** (arXiv 2511.02824) | Autonomous discovery cycles | Long-horizon agent accumulating findings across iterations | Yes — explicit multi-cycle accumulation |

**The pattern that separates these from TxAgent (and from us):** they own a **closed loop where
the system's own output changes its next action** — a tree-search branch, a tournament round, a
wet-lab readout fed back as a new constraint. TxAgent loops *within one query*; AI Scientists
loop *across hypotheses and experiments*.

---

## 3. A single autonomy spectrum (L0–L4)

Drawn from the *From AI for Science to Agentic Science* survey (arXiv 2508.14111) and the L0–L5
research-autonomy framing. The dimensions that actually move a system up the ladder:

| | **Plan** | **Tool selection** | **Iteration** | **Hypotheses** | **Memory across runs** |
|---|---|---|---|---|---|
| Fixed pipeline | hardcoded | hardcoded | none | none | no |
| **virtual-biotech-cso (today)** | **deterministic** (`routing.yaml` by case-key) | **deterministic** | **1 reviewer re-route** | reviewer/CSO *interpret*, don't generate | no |
| TxAgent | emergent (trained) | learned (ToolRAG) | unbounded within a query | answers, doesn't form | no (frozen after training) |
| Co-Scientist / Sakana | emergent | emergent | unbounded (tournament / tree search) | **generates & ranks** | within a run |
| Kosmos / Coscientist | emergent | emergent | unbounded + wet-lab | generates & tests | **accumulates** |

**Mapping to levels:**

- **L1** — automate a single sub-task (our individual ClawBio skills: `gwas-lookup`,
  `celltype-specificity-profiler`).
- **L2 — task-level autonomy: where virtual-biotech-cso sits today.** Multi-agent-flavoured
  orchestration of a *complete* sub-process (brief → divisions → review → synthesis), but the
  workflow shape is fixed.
- **L3 — goal-level autonomy.** A super-agent that *plans, orchestrates, and iterates* the
  workflow itself. **This is the next rung for us, and it's reachable without a rebuild.**
- **L4** — full lifecycle incl. question formulation and experiment execution (Sakana, Kosmos).

---

## 4. Where our code is pipeline-shaped (with line references)

Our own SKILL.md is admirably honest that the skill makes no LLM call and delegates reasoning.
The harness *is* the driving agent. But the **agency is bottlenecked into one slot.**

The plan is **computed, not reasoned** — [`harness.py:124-126`](../skills/virtual-biotech-cso/harness.py#L124-L126):

```python
# 2 — DECOMPOSE & ROUTE (deterministic, reused)
subtasks = cso.decompose_and_route(query, case, routing)
```

`decompose_and_route` is a lookup keyed off `case_key(query)` against `routing.yaml`. Same case →
same plan, every time. That is the single biggest reason it "feels like a pipeline."

The **one genuinely agentic loop** — [`harness.py:138-144`](../skills/virtual-biotech-cso/harness.py#L138-L144):

```python
if review.get("verdict") == "re-route":
    gap = (review.get("gaps") or [{}])[0]
    followup = cso._reroute_task(gap)
    ...
    results.append(cso.execute_skill(followup, case, demo, live))
```

A **live reviewer verdict drives control flow** — real agency. But it is capped at **one** pass
(by design; documented in SKILL.md Gotchas), and the follow-up skill is read off `gap["route_to"]`
from a fixed gap template rather than *chosen* by the agent.

**Net:** three reasoning slots (Chief of Staff, Reviewer, CSO synthesis) wrap a **fixed
plan + fixed routing + single re-route.** That is a high-quality L2 — more transparent than
TxAgent (every step carries provenance, an evidence grade, and a citation; it refuses to
fabricate), but its *control flow* is authored, not emergent.

---

## 5. What to change — move agency from `routing.yaml` into the roles we already have

Four loops, in order of impact. We don't need to rebuild; we need to let the reasoning roles
*decide*, with the deterministic substrate keeping them honest and reproducible.

1. **Dynamic planning — the biggest lever (L2 → L3).**
   Make the **plan an agent output.** Today `decompose_and_route` *generates* the plan; instead,
   have the Chief-of-Staff / CSO role *propose* it, and turn `decompose_and_route` into a
   **validator** that binds the proposed plan against `routing.yaml` (reject invented skills,
   resolve each to a real division). Same guardrails, but the *shape* of the assessment now
   varies with the query. This is the change that stops it being a pipeline.

2. **Unbounded review→reroute (bounded by budget).**
   Lift the one-pass cap at [`harness.py:138`](../skills/virtual-biotech-cso/harness.py#L138) to
   "loop until the reviewer returns `synthesize` **or** N rounds / token budget." Mirrors how
   Co-Scientist and Sakana iterate rather than single-shot. Keep a hard cap to avoid the
   unbounded-recursion failure mode the Gotchas warn about.

3. **Hypothesis-driven tool selection.**
   Let the reviewer/CSO *choose* which catalog skill fills a gap, rather than reading
   `route_to` off a fixed gap template. Closer to TxAgent's ToolRAG and Biomni's open
   tool-selection — selection becomes reasoning, not a constant.

4. **Memory across runs — the real frontier.**
   Neither we nor TxAgent has this; Kosmos does. A standing "virtual biotech" should remember
   that B7-H3 specificity came back stromal-not-malignant last time and not re-derive it. This
   is where the [[kg-pareto-provenance-design]] KG becomes the substrate: persisted, provenance-
   tagged findings the planner can read before deciding what to run. Hardest, highest ceiling.

**Recommended first move:** #1. Turning `decompose_and_route` into a *validator of an
agent-proposed plan* converts "a pipeline that calls an LLM in three slots" into "an agent that
plans, over a substrate that keeps it reproducible and refuses to fabricate" — which is a better
architecture than TxAgent's for our goals, because we keep provenance and the no-fabrication
contract while gaining emergent control flow. See [[agentic-workflow-ideas]] and
[[agentic-hypothesis-optimization]] for adjacent design notes.

---

## Sources

- TxAgent — [arXiv 2503.10970](https://arxiv.org/abs/2503.10970)
- Sakana AI Scientist v2 — [arXiv 2504.08066](https://arxiv.org/pdf/2504.08066) ·
  [GitHub](https://github.com/sakanaai/ai-scientist-v2)
- Google Co-Scientist — [*Nature* s41586-026-10644-y](https://www.nature.com/articles/s41586-026-10644-y) ·
  [DeepMind blog](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/)
- Biomni — [bioRxiv 2025.05.30.656746](https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1) ·
  [PMC12157518](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12157518/)
- Robin — [overview](https://www.marinbio.com/robin-the-ai-scientist-that-performs-scientific-discovery-and-discovered-a-new-drug-candidate-for-blindness)
- Kosmos — [arXiv 2511.02824](https://arxiv.org/pdf/2511.02824)
- Survey: *From AI for Science to Agentic Science* — [arXiv 2508.14111](https://arxiv.org/abs/2508.14111)
- Virtual Biotech (the loop we reproduce) — Zhang et al. 2026, bioRxiv doi:10.64898/2026.02.23.707551
