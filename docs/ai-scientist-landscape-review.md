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
| virtual-biotech-cso (before #1–#3) | deterministic (`routing.yaml` by case-key) | deterministic | 1 reviewer re-route | reviewer/CSO *interpret*, don't generate | no |
| **virtual-biotech-cso (now)** | **agent-proposed, validated** | **agent-chosen, catalog-validated** | **bounded loop (≤`MAX_REROUTES`)** | reviewer/CSO interpret, don't generate | **no — by design** (§5 #4) |
| TxAgent | emergent (trained) | learned (ToolRAG) | unbounded within a query | answers, doesn't form | no (frozen after training) |
| Co-Scientist / Sakana | emergent | emergent | unbounded (tournament / tree search) | **generates & ranks** | within a run |
| Kosmos / Coscientist | emergent | emergent | unbounded + wet-lab | generates & tests | **accumulates** |

**Mapping to levels:**

- **L1** — automate a single sub-task (our individual ClawBio skills: `gwas-lookup`,
  `celltype-specificity-profiler`).
- **L2 — task-level autonomy: where virtual-biotech-cso sits today.** Multi-agent-flavoured
  orchestration of a *complete* sub-process (brief → divisions → review → synthesis), but the
  workflow shape is fixed.
- **L3 — goal-level autonomy: where virtual-biotech-cso sits *after* changes #1–#3.** A
  super-agent that *plans, orchestrates, and iterates* the workflow itself — the plan, the
  iteration count, and the reroute target are now agent decisions validated against the catalog.
- **L4** — full lifecycle incl. question formulation and experiment execution (Sakana, Kosmos).
  Out of scope for bounded assessment queries, and gated on cross-run memory we deliberately
  don't build (see §5 #4).

---

## 4. Where our code *was* pipeline-shaped (the diagnosis that motivated changes #1–#3)

> This section describes the **starting point** — the state that prompted the work. Changes #1–#3
> (§5) have since moved each of these into a validated agent decision; kept here as the diagnosis.

Our own SKILL.md is admirably honest that the skill makes no LLM call and delegates reasoning.
The harness *is* the driving agent. But the **agency was bottlenecked into one slot.**

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

Four loops, in order of impact. We don't need to rebuild; we let the reasoning roles *decide*,
with the deterministic substrate keeping them honest and reproducible. **Loops #1–#3 are
implemented (changes #1–#3); #4 is deliberately not — see why below.**

1. **Dynamic planning — the biggest lever (L2 → L3).** *(implemented — change #1)*
   The **plan is an agent output.** `decompose_and_route` no longer generates the plan as the
   primary path; the Chief-of-Staff / CSO role *proposes* it and `validate_and_bind_plan` is the
   **validator** that binds it against `routing.yaml` (rejects invented divisions/intents/skills
   and forward deps, resolves each to a real skill), falling back to `decompose_and_route` on any
   failure. Same guardrails, but the *shape* of the assessment now varies with the query. This is
   the change that stops it being a pipeline.

2. **Bounded review→reroute loop.** *(implemented — change #2)*
   Lift the one-pass cap to "loop until the reviewer returns `synthesize` **or** `MAX_REROUTES`."
   The reviewer re-audits the *grown* evidence each pass; successive reroutes are numbered
   `step_06/07/08`. Mirrors how Co-Scientist and Sakana iterate rather than single-shot, with a
   hard cap to avoid the unbounded-recursion failure mode the Gotchas warn about.

3. **Hypothesis-driven tool selection.** *(implemented — change #3)*
   The reviewer *chooses* which skill fills a gap; `_reroute_task` validates that choice against
   `catalog_skills(routing)` and degrades an invented target to the designated fallback. Closer
   to TxAgent's ToolRAG and Biomni's open tool-selection — selection becomes reasoning, not a
   constant, but still bound to real skills.

4. **Memory across runs — *not* the next move for this system.**
   It's tempting to read "Kosmos accumulates state, so we should too" as the path to a higher
   tier. That reasoning is wrong, and the reason is worth stating because it's a general rule:

   **Cross-run memory is forced by *task horizon*, not by *capability*.** A system pays for
   memory to solve two specific problems — (a) the run is too long to fit in one context window,
   and (b) an open-ended loop won't *converge* unless each cycle builds on the last. Kosmos has
   both: it runs hundreds of sequential discover-cycles over an **unbounded** space with no plan
   known up front, so persisted state is a mechanical necessity *and* the accumulated trajectory
   **is** the deliverable. Notably, **TxAgent — a sophisticated agent — has no cross-run memory
   either**, because it answers *bounded* questions in one reasoning episode. Capability isn't the
   axis; horizon is.

   Our queries are the bounded kind: a self-contained `(target, disease)` go/no-go over four
   known divisions, one pass plus ≤`MAX_REROUTES`, the whole run fits in context, and it converges
   by construction. None of the forcing functions apply. Worse, **planner memory would fight our
   strongest property** — the reproducibility contract (byte-stable dossiers, a `reproducibility/`
   bundle). A planner that "remembers B7-H3 was stromal last time and skips the specificity step"
   is *less* auditable, not more, and risks serving stale data when the underlying source has moved.

   The genuine cross-target value (Pareto ranking across targets, "what did we nominate this
   quarter") is a **queryable store, decoupled from the planning loop** — persist each run's
   provenance-tagged findings into the [[kg-pareto-provenance-design]] KG and *query* it for
   comparative/portfolio questions, while every single assessment still runs **cold and
   reproducible**. That's a new query mode (rank N targets in one run), not planner memory. Build
   that; do **not** let the store short-circuit an assessment's evidence pull.

**Where this leaves us.** Changes #1–#3 converted "a pipeline that calls an LLM in three slots"
into "an agent that plans, iterates, and selects tools — over a substrate that keeps it
reproducible and refuses to fabricate." Plan shape, iteration count, and reroute target are now
agent decisions, each validated against `routing.yaml` before it can act. That is a better
architecture than TxAgent's for our goals, because we keep provenance and the no-fabrication
contract while gaining emergent control flow — a solid **L3** on bounded assessment queries.

**Next move is *not* #4.** The forward value is a **comparative/portfolio query mode** (rank N
targets in one run, Pareto over the persisted [[kg-pareto-provenance-design]] KG), which is a new
query type over a queryable store — explicitly *not* planner memory, for the reasons in #4. See
[[agentic-workflow-ideas]] and [[agentic-hypothesis-optimization]] for adjacent design notes.

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
