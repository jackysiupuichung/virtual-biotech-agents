# Prometheux / Vadalog on the evidence graph — applicability review

**The question:** does **Prometheux** (the Vadalog reasoning engine) apply to our evidence
graph — the canonical property graph in [frontend/kg.py](../frontend/kg.py) designed in
[docs/kg-pareto-provenance-design.md](kg-pareto-provenance-design.md)?

**Short answer:** Yes, but as a *reasoning layer on top of* the graph, not a replacement for it.
The strongest fits are the three things our design already wants and currently hand-codes in
Python: **recursive/transitive inference over the typed edges**, **explainable provenance ("why
is this here?")**, and **confidence/rule-gated derivation**. The weakest fit is operational:
it's a heavier dependency than the "zero-infra NetworkX + JSON" stance the design deliberately
took, and it doesn't natively own the Pareto/scalarization numerics. Recommendation: not for the
2-day demo slice; a credible **stretch / post-demo** layer if explainable multi-hop reasoning
becomes the headline.

---

## 1. What Prometheux/Vadalog actually is

- A **knowledge-graph reasoning engine** built on **Warded Datalog±** (Datalog+/-), the language
  core from the Oxford / TU Wien KG labs. Warded Datalog± is the sweet spot: it keeps **PTIME**
  data complexity while supporting **ontological reasoning** (existential rules, recursion).
- Commercialized as **Vadalog Parallel** — a distributed engine for large-scale ontological
  reasoning, with a GPU/RAPIDS path (the NVIDIA neurosymbolic blog).
- **Explainability is a first-class feature**, not a bolt-on: it can answer *"why was this
  conclusion derived?"* by replaying the logical provenance of a derived fact — template-driven,
  human-readable explanations grounded in the rule chain.
- **Reasons across sources without moving data** (declarative rules over heterogeneous stores).
- Accessed via a hosted **platform** (`platform.prometheux.ai`) and an **API / Python** client
  (`docs.prometheux.ai`). Cloud-agnostic; on-prem not clearly advertised.
- Track record in our adjacent domains: **drug repurposing for AstraZeneca**, financial reasoning
  for the Bank of Italy — i.e. it has been pointed at life-sciences KGs before.

Sources:
[Prometheux Research](https://prometheux.ai/research.html) ·
[Vadalog System (VLDB 2018)](https://www.vldb.org/pvldb/vol11/p975-bellomarini.pdf) ·
[arXiv 1807.08709](https://arxiv.org/abs/1807.08709) ·
[NVIDIA: Vadalog Parallel + RAPIDS](https://developer.nvidia.com/blog/accelerating-neurosymbolic-ai-with-rapids-and-vadalog-parallel/)

---

## 2. Our evidence graph today (what it would reason over)

From [frontend/kg.py](../frontend/kg.py) and the design doc:

- A **canonical, deduplicated property graph** (`<kind>:<slug>` node ids), persisted as a single
  JSON file, queried in-process with plain Python.
- **Provenance and confidence live on every edge** (`conf ∈ [0,1]`, `source`, `method`, `ref`,
  `url`, `run`, `step`) — already the structural substrate Prometheux's explainability consumes.
- Typed edges: `HAS_EVIDENCE`, `ON_AXIS`, `SUPPORTS`/`REFUTES`, `DERIVED_FROM`, `EXPRESSED_IN`,
  `SIGNALS_TO`, `BEAT`.
- The graph **compounds across runs** (shared LUAD / fibroblast / Source nodes link hypotheses).
- Current "reasoning" is Python aggregation: per-axis roll-ups, Pareto domination, the
  cross-run `shared_with` link, "missing axes" gap queries.

The key observation: **this is already a fact base shaped like Datalog facts.** Each edge is a
ground atom — `supports(E1, H1)`, `derived_from(E1, cellxgene){conf:0.9}`,
`beat(H1, H2){margin:3-1}`. That makes a Datalog engine a natural — not forced — fit.

---

## 3. Where it genuinely applies (the strong fits)

| Our design feature (doc §) | Today (Python) | What Vadalog adds |
|---|---|---|
| **"Explain a rank" — why H1 > H2** (§3, the killer demo) | hand-walk differentiating edges | the *native* Vadalog capability: derived facts carry a replayable rule-chain explanation. "MET > B7-H3 **because** these confidence-weighted axis facts" falls out of the engine, not bespoke code |
| **Transitive / multi-hop links** ("targets sharing a CellType/Pathway", cell→cell `SIGNALS_TO` chains) | manual graph walks | recursive rules: `co_niche(A,B) :- expressed_in(A,C), expressed_in(B,C).` and transitive closure over `SIGNALS_TO` — exactly Warded Datalog±'s recursion strength |
| **Confidence-gated claims / abstention** (§5) | Python thresholds on edge `conf` | rules as first-class guardrails: `strong_claim(H,Ax) :- axis_score(H,Ax,S), S≥0.8.` — the gating *is* the logic, uniformly applied and inspectable |
| **Provenance "where did this come from?"** (§5) | one-hop `DERIVED_FROM` lookup | same one-hop, but now *composes* through derivations: a derived conclusion keeps the full source lineage automatically |
| **Cross-run compounding** (§2) | `shared_with` run set | ontological linking — same-entity / equivalence rules merge evidence across runs declaratively |

The throughline: the three features the design calls "one system" (KG + provenance + the explain
query) are precisely a **deductive-reasoning + explanation** problem, which is Prometheux's home turf.

---

## 4. Where it does *not* apply (the weak fits)

- **The Pareto numerics.** Non-dominated-set computation and steerable scalarization (weighted
  sum / Chebyshev, live slider re-sort) are numeric optimization, not deduction. Datalog can
  *feed* the per-axis vectors but won't replace the numpy/plotly layer. Vadalog stays a
  pre-aggregator here.
- **Infra weight vs. the stated stance.** The design explicitly chose "**Skip Neo4j/RDF
  triple-stores** — NetworkX + JSON" for zero-infra reproducibility (§6). Prometheux is a hosted
  platform / external API — heavier than that posture, and a network/SaaS dependency in a demo
  that currently has none.
- **Scale mismatch (for now).** Vadalog Parallel's value is *enterprise-scale* KGs (AstraZeneca,
  central-bank data). Our graph is hundreds of nodes. We'd adopt it for its **explainability and
  rule semantics**, not its scale — and at our size, plain Python rules are competitive.
- **Confidence as a *number on a derivation*.** Our `conf` is probabilistic/heuristic and we want
  it to *propagate* (uncertainty bands on Pareto coords, doc §4 honesty note). Classical Datalog±
  is boolean-derivation; confidence-weighted propagation needs an annotated-provenance / semiring
  extension — check whether Vadalog supports it before assuming the gating composes numerically.

---

## 5. If we adopted it — the minimal shape

1. **Export, don't migrate.** Keep `kg.py` as the source of truth; emit the edges as Vadalog
   facts (`supports/2`, `derived_from/2` + annotations). The graph stays canonical JSON; Vadalog
   is a queryable *view*, mirroring how the doc treats Pareto/cards as projections.
2. **Encode the demo queries as rules:** transitive `co_niche`, `signals_path`, the
   axis-aggregation, the confidence gate, and the "differentiating edges between H1 and H2" rule.
3. **Surface the explanation** from Vadalog's "why" output into the front-end's provenance panel —
   replacing the bespoke edge-highlight walk with engine-generated lineage.
4. **Leave Pareto + sliders in numpy/plotly**, fed by Vadalog's per-axis aggregation.

**Open questions to resolve before committing** (each a reason it could be wrong for us):
confidence-semiring support; API latency vs. an interactive demo; auth/cost for a hosted
platform; whether on-prem/embedded is possible (so the "zero-infra, reproducible" promise
survives). The honest comparison is **Vadalog vs. ~50 lines of Python recursion** — adopt only if
the *explanation quality* and *rule maintainability* clearly beat that for the multi-hop cases.

---

## 6. Verdict

- **For the 2-day demo slice ([design §8](kg-pareto-provenance-design.md)):** **no.** The "explain
  a rank" moment is achievable with edge-walking Python, and Prometheux adds an external dependency
  the design deliberately avoided.
- **As a stretch / post-demo reasoning layer:** **yes, credible and on-theme.** If explainable
  *multi-hop* reasoning ("why this target, traced through the niche") becomes the headline over the
  single-hop card, Vadalog is the right-shaped tool — its Warded Datalog± recursion + native
  provenance explanations map almost one-to-one onto our typed, provenance-bearing edges, and it
  has a real drug-discovery pedigree.
- **The deciding test:** prototype the transitive `co_niche` / `signals_path` and "differentiating
  edges" rules in Vadalog against an exported `kg.json`, and compare the engine's explanation
  output to the hand-coded walk. If it reasons *and explains* better than the Python, it earns the
  dependency; otherwise the design's zero-infra stance wins.

---
*Status: applicability review. Recommendation — defer for the demo, prototype as a post-demo
explainable-reasoning layer; gate adoption on the confidence-semiring + latency + embeddability
questions in §5.*
