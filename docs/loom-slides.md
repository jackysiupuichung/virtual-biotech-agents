---
marp: true
theme: default
paginate: true
---

# 🧬 Virtual Biotech CSO

### A multi-agent system for therapeutic target selection

<!--
~2 min: ~1 min slides + ~1 min live demo.
-->

---

## The Problem

- **90% of drug programs fail** — most for one reason: **lack of efficacy**
- The drug didn't work because the **therapeutic target hypothesis was wrong**
- A single failed Phase 3 can cost **over a billion dollars**
- Getting it right means **diving into millions of papers** and **digging across dozens of experimental data sources** to retrieve the evidence, form a hypothesis, and refine it — far beyond what any one team can do by hand

> Choosing the right target is the most expensive guess in biotech.

<!--
[0:00–0:20] HOOK + PROBLEM. On camera or title slide.
-->

---

## The Solution

**We introduce the Virtual Biotech** — a coordinated team of AI agents that mirrors the structure of human therapeutic research organizations to support **end-to-end computational discovery**.

A real, running multi-agent system that does target selection end to end.

- **CSO orchestrator** — plans and routes; runs no analysis itself
- **Four scientist divisions** — call real tools over live databases: Open Targets, CELLxGENE, TCGA, DepMap, openFDA, ClinicalTrials.gov
- **Bring your own data** — plug in an **MCP server** (CRISPR screen, single-cell run, internal assay); the loop projects it into **cited facts**

<!--
[0:20–0:55] SOLUTION. Slide: architecture.svg — the three layers.
-->

---

## Grounded & Trustworthy

- All evidence reasons alongside **PrimeKG** — the canonical knowledge graph
  - **78,000 targets · 39,000 diseases · millions of relationships**
- A **reviewer panel** audits the evidence and can **force the org back to do more work**
- At every review pass, a **human can join the panel**: approve, override, or steer
- Runs **fully autonomous**, or with a scientist in the loop — same machinery

---

## Hypothesis Generation & Refinement

Each pass asks a **sharper question than the last**:

- **Pass 1:** is B7-H3 expressed and specific? → answer comes back *stromal*
- **Pass 2:** is it on the **malignant cells**, or just fibroblasts?

We frame target selection as **multi-armed-bandit information maximisation** — each loop spends the next experiment on the axis that **maximises information gain**, interrogating the **weakest link** in the current hypothesis so it's **progressively refined**.

A **human can join the loop** at any pass and apply **domain knowledge** to pursue more information — steering the next experiment toward the axis they know matters most.

**Verdict:** `TIER: SUPPORTED` — cell-type-specific, tumour-localised, active trial.
→ Full report + replayable trace, reproducible bit-for-bit.

<!--
Optional HITL beat: run the UI with '🧑‍⚖️ human in the loop' ticked; loop pauses at the vote with a checkpoint card.
-->

---

## Explainable by Design — on the Sponsor Stack

> The final **GO / NO-GO is not written by an LLM** — it's **derived deductively**, with a replayable chain behind every conclusion.

- **Prometheux** — the heart: its Vadalog engine **derives the verdict**, and acts as a *non-silenceable reviewer* (a provably-missing axis becomes a fact that forces re-work)
- **Tavily** — powers the live literature search the scientists call
- **Cursor** — wrote the codebase
- **Gemini** — powers the agents' reasoning
- **Langfuse** — mirrors the entire loop as a hosted, replayable trace

> Every layer is optional — the workflow always degrades to an offline, reproducible path.

<!--
[2:15–2:45] HOW WE USED THE SPONSOR TOOLS. Slide: sponsor logos.
-->

---

# Thank You

### A multi-agent virtual biotech —
### a verdict that's **deductively derived** and **fully provenanced**.

**That's the Virtual Biotech CSO.**

<!--
[2:45–3:00] CLOSE. Title slide.
-->
