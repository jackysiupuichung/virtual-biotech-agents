# KG + Pareto + Provenance — unified design

**The key insight:** your three chosen features are **one system, not three.** A **knowledge graph**
is the data model; **provenance + confidence** are first-class edge metadata on it; the **Pareto
re-sort** is an aggregation query over it; and the **front-end** is a renderer of graph queries. Build
the graph once, and the leaderboard, the Pareto front, and the provenance display all fall out as
*views*.

```
        agents/skills emit evidence
                  │
                  ▼
        ┌───────────────────────┐
        │  KNOWLEDGE GRAPH       │  ← accumulates across queries (the "buildup")
        │  nodes + typed edges   │
        │  every edge carries:   │
        │   value · axis ·       │
        │   confidence · source  │  ← provenance is on the edge, not bolted on
        └───────────┬───────────┘
        ┌───────────┼───────────────────────┐
        ▼           ▼                        ▼
  Pareto re-sort   Provenance/confidence   Graph explorer
  (aggregate by    display (render edge    (query subgraphs,
   axis → fronts)   metadata, gate claims)  "why ranked here?")
        └───────────┴───────────────────────┘
                  FRONT-END (Streamlit)
```

---

## 1. Knowledge graph schema

A **property graph** (nodes + typed, attributed edges). Node and edge types:

**Nodes**
| Type | Example | Key props |
|---|---|---|
| `Hypothesis` | *B7-H3 → ADC → LUAD* | id, target, disease, modality, status |
| `Target` | CD276 / B7-H3 | gene symbol, ensembl id |
| `Disease` | LUAD | EFO/MONDO id |
| `Modality` | ADC | class |
| `EvidenceItem` | "tau = 0.71" | axis, value, direction, confidence |
| `CellType` | fibroblast | ontology id |
| `Pathway` / `PPI` | "myeloid reprogramming" | id |
| `Trial` | NCT07130032 | phase, status, outcome |
| `Source` | CELLxGENE / Open Targets / PubMed | kind, url, version |

**Edges** (all carry `confidence ∈ [0,1]`, `source`, `method`, `timestamp`)
| Edge | From → To | Meaning |
|---|---|---|
| `HAS_EVIDENCE` | Hypothesis → EvidenceItem | a card field |
| `ON_AXIS` | EvidenceItem → Axis | which prioritization dimension |
| `SUPPORTS` / `REFUTES` | EvidenceItem → Hypothesis | direction of the evidence |
| `DERIVED_FROM` | EvidenceItem → Source | **provenance** |
| `EXPRESSED_IN` | Target → CellType | single-cell finding |
| `SIGNALS_TO` | CellType → CellType | cell-cell communication |
| `BEAT` | Hypothesis → Hypothesis | an arena match result (with margin) |

**Example subgraph (B7-H3), as triples:**
```
(H1: B7H3→ADC→LUAD) -HAS_EVIDENCE-> (E1: tau=0.71)         {axis: specificity, conf: 0.9}
(E1) -ON_AXIS-> (specificity)
(E1) -SUPPORTS-> (H1)
(E1) -DERIVED_FROM-> (CELLxGENE Census)                     {method: tau on LUAD atlas, ts: ...}
(B7H3) -EXPRESSED_IN-> (fibroblast)                         {log2FC: 1.46, FDR: 1.1e-7, conf: 0.95}
(H1) -HAS_EVIDENCE-> (E2: genetic_support=weak)            {axis: genetics, conf: 0.6}
(E2) -DERIVED_FROM-> (Open Targets)                         {datatype: genetic_association}
(H1) -BEAT-> (H2: MET→TKI→LUAD)                            {margin: 3-1, judge: panel}
```

This makes **provenance structural**: every evidence node has a `DERIVED_FROM` edge, so "where did
this come from?" is a one-hop query, and "show everything from Open Targets" is a node filter.

---

## 2. Building & accumulating the graph (the "buildup")

- **Every skill/agent run emits triples**, not just a card. `celltype-specificity-profiler` →
  `(H)-HAS_EVIDENCE->(tau)`, `(tau)-DERIVED_FROM->(CELLxGENE)`. The card is just a *projection* of the
  hypothesis's subgraph.
- **It persists and compounds across queries** — assess B7-H3 today, MET tomorrow; both land in the
  same graph, so shared nodes (LUAD, fibroblast, a pathway) **link** them. The graph gets richer and
  *more useful* with every run — this is the part you found cool, and it's a compounding deliverable.
- **Caching for free:** before computing tau for (gene, atlas), check if the node exists → instant
  reuse. The graph *is* the cache (ties to [workflow-ideas §2](agentic-workflow-ideas.md)).
- **Confidence is set at emit time** by the producing agent (data quality, sample size, method
  maturity, or "this axis was a gap-fill") and stored on the edge.

---

## 3. Querying it — where it gets cool for the demo

The graph turns into *interactive exploration*, not a static report:

| Query | Returns | Demo value |
|---|---|---|
| `subgraph(H1)` | the full evidence dossier for one hypothesis | the card, but clickable/expandable |
| `aggregate HAS_EVIDENCE by ON_AXIS` | per-axis score → **feeds the Pareto sort** | §4 |
| `path(H1 → … → H2)` "why is H1 > H2?" | the **differentiating** evidence edges | **the killer demo: explain a rank** |
| `targets sharing a CellType / Pathway` | cross-hypothesis links | "these 3 targets all hit the immunosuppressive fibroblast niche" |
| `missing axes for H` | nodes *absent* in the subgraph | drives VoI ("what to compute next", [optimization doc](agentic-hypothesis-optimization.md)) |
| `filter DERIVED_FROM = Open Targets` | all retrieved (vs computed) evidence | the retrieve-vs-compute split, made visual |
| `nodes where confidence < 0.5` | the shaky evidence | honesty surface |

The *"highlight the edges that explain why MET ranks above B7-H3"* query is the moment that lands with
experts — it shows the ranking is **traceable to evidence**, not vibes.

---

## 4. Pareto re-sort across prioritization axes

The axes are **projections of the graph**: aggregate each hypothesis's `HAS_EVIDENCE` edges by
`ON_AXIS` into a per-axis score (signed by `SUPPORTS`/`REFUTES`, weighted by `confidence`). With the
per-division Elo from [expert-gaps #3](expert-gaps-review.md), each hypothesis becomes a vector:

```
H = (efficacy, safety, tractability, specificity, commercial)   # each from KG aggregation
```

Two views, both from the same vectors:
1. **Pareto front** — compute the **non-dominated set** (no other hypothesis is ≥ on all axes and >
   on one). Plot e.g. *safety vs efficacy*, front highlighted. "These 4 are the undominated choices;
   the rest are strictly worse."
2. **Steerable scalarization** — user sets axis weights with **sliders**; the leaderboard re-sorts
   **live** (weighted sum, or Chebyshev for a fairer front). *"Under a safety-first portfolio, the
   board reorders like this."*

Why it impresses: it refuses the black-box single number, exposes the **trade-off a real portfolio
committee argues about**, and makes the user a participant. ~30 lines (numpy domination check + plotly
scatter + Streamlit sliders).

> Honesty detail: **weight the per-axis aggregation by edge confidence**, so a thin/gap-filled axis
> contributes a *wider* uncertainty band on that coordinate — uncertainty propagates from graph to
> Pareto point ([expert-gaps #14](expert-gaps-review.md)).

---

## 5. Provenance & confidence — the front-end display spec

Because provenance/confidence live on every edge, the UI renders them uniformly:

**Provenance legend (per evidence item):**
| Icon | Source kind |
|---|---|
| 🗄️ | retrieved — Open Targets / public API |
| 🔧 | computed — ClawBio skill (live) |
| 🌐 | agent web/literature search |
| ⚪ | gap — not available |

**Confidence → visual + language gating:**
| Confidence | Visual | Claim language (auto-gated) |
|---|---|---|
| ≥ 0.8 | solid, full opacity | "**strong**: …" |
| 0.5–0.8 | medium | "**supported**: …" |
| 0.2–0.5 | faded | "**suggestive**: …" |
| < 0.2 / ⚪ | dashed outline | "**insufficient** — flagged as gap" |

**Rendering rules:**
- Every card field shows its icon + confidence color; **hover/click → the `DERIVED_FROM` node** (source,
  method, timestamp, version). One-hop from the graph.
- **Language is generated from confidence**, never hardcoded — a low-confidence axis can't print a
  strong claim. This is confidence-gating as a *guardrail*, not just styling.
- A hypothesis whose card is mostly ⚪ triggers **abstention** ("UNRANKED — insufficient evidence")
  rather than a confident fake rank ([workflow-ideas §3](agentic-workflow-ideas.md)).
- Edge color in the graph view = source kind; edge opacity = confidence. The graph *looks* like its
  evidence quality.

---

## 6. Tech stack (2-day-realistic)

| Layer | Pick | Why |
|---|---|---|
| Graph store | **NetworkX** (in-memory, property graph via node/edge attrs) | zero infra, trivial to query in Python; persist to JSON/pickle |
| Graph viz | **streamlit-agraph** or **pyvis** | interactive node-click in Streamlit |
| Pareto | numpy (domination check) + **plotly** scatter | live, hover, slider-reactive |
| Provenance/conf | edge attributes → rendered in card components | no extra store |
| App | **Streamlit** | matches your chosen deliverable |

Skip Neo4j/RDF triple-stores unless you already know them — NetworkX + a JSON dump gives you the graph,
the queries, and reproducibility without standing up a database. (If a judge loves graph DBs, a Neo4j
export is a one-evening stretch.)

---

## 7. The demo script (the three features as one flow)

1. **Watch it build** — run two queries (B7-H3, MET); the graph **grows** on screen, new nodes linking
   to shared LUAD/fibroblast nodes. *"The system accumulates a reusable evidence graph."*
2. **Explore** — click MET → its subgraph; every edge shows 🗄️/🔧/🌐 and confidence shading. Click a
   tau node → jumps to the CELLxGENE source. *"Every claim is traceable."*
3. **Explain a rank** — "why MET > B7-H3?" → the differentiating edges highlight. *"The ranking is
   grounded in evidence, not preference."*
4. **Steer** — drag the **safety** weight up; the leaderboard and Pareto front **re-sort live**.
   *"Prioritization under your risk appetite, with the trade-off visible."*
5. **Honesty** — a thin-card hypothesis shows faded/dashed edges and reads *"suggestive / insufficient
   — flagged."* *"It tells you when it doesn't know."*

---

## 8. 2-day build slice

**Day 1:** graph schema in NetworkX; emit triples from the existing skills + Open Targets pulls (with
provenance/confidence on edges); card = subgraph projection; Streamlit skeleton renders one hypothesis
card with icons + confidence shading.
**Day 2:** per-axis aggregation → Pareto front + weight sliders (live re-sort); graph explorer
(streamlit-agraph) with click-through provenance; "explain a rank" edge-highlight query; confidence-
gated language + abstention. Polish the 5-step demo.

---

## 9. How it connects to the other docs
- It's the **data substrate** under [the arena](target-arena-research.md) — `BEAT` edges are matches;
  evidence subgraphs are the frozen cards.
- It **implements** the retrieve-vs-compute split ([evidence gap](evidence-gap-analysis.md)) as
  `DERIVED_FROM` source kinds.
- It **renders** [expert-gaps #3 (Pareto)](expert-gaps-review.md) and **#14 (uncertainty)** and the
  [workflow-ideas](agentic-workflow-ideas.md) memory/provenance/abstention patterns.
- "Missing axes" queries **drive** the VoI loop ([optimization](agentic-hypothesis-optimization.md)).

---
*Status: design for the three chosen features (KG buildup + query, Pareto re-sort, provenance/confidence
display), unified on one graph substrate. Build candidate.*
