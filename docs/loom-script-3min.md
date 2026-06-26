# Virtual Biotech CSO — 3-minute Loom pitch script

*Structured on the hackathon-pitch-builder framework: **Hook → Problem → Solution → Proof (live demo) → Potential → Close.** Target ~3:00, ~440 words spoken at ~150 wpm. Cues in **[brackets]**.*

---

## [0:00–0:20] — HOOK + PROBLEM

**[On camera or title slide: "🧬 Virtual Biotech CSO"]**

"Ninety percent of drug programs fail. And most of them fail for one reason: lack of efficacy —
the drug didn't work because the **therapeutic target hypothesis was wrong.** The biology never
held up. That burns **billions of dollars** a year — a single failed Phase 3 can cost over a
billion on its own.

Choosing the right target is the most expensive guess in biotech.

---

## [0:20–0:55] — SOLUTION

**[Slide: architecture.svg — the three layers]**

"So we built a **virtual biotech** — a real, running multi-agent system that does target
selection end to end.

A **CSO orchestrator** plans and routes; it runs no analysis itself. **Four scientist
divisions** each call real bioinformatics tools over live public databases — Open Targets,
CELLxGENE, TCGA, DepMap, openFDA, ClinicalTrials.gov. And you bring your **own** experimental
data the same way: plug in an **MCP server** — a CRISPR screen, an in-house single-cell run, an
internal assay — and the loop **projects it into cited facts** that reason right alongside the
public knowledge graph. A **reviewer panel** audits the evidence and can *force the org back to
do more work* — and at every one of those review passes, a **human can join the panel**: approve,
override, or steer the next experiment. The org runs fully autonomous, or with a scientist in the
loop — same machinery.

And here's the part that makes a scientist trust it: the final GO / NO-GO is **not** written by
an LLM. It's **derived deductively** by a Prometheux reasoning engine — with a replayable chain
behind every conclusion."

---

## [0:55–2:15] — PROOF (the live demo — the 'wow' moment)

**[Screen: terminal. Run the command.]**

```bash
python skills/virtual-biotech-cso/harness.py --demo
```

"Let me just run it. The case is B7-H3 in lung cancer.

**[Point as output streams]**

The CSO decomposes the question into six sub-tasks and routes them across the four divisions.
Each scientist calls real skills and writes **cited edges** into a knowledge graph — nothing in
the verdict is ungrounded.

Now watch the reviewer panel — **[point]** — two of four lenses vote to *re-route*: a piece of
evidence, malignant-cell localisation, is missing. The org autonomously goes back to fill it.
No human in the loop.

**[Optional — UI run with '🧑‍⚖️ human in the loop' ticked]** And when you *want* a human there,
the loop pauses right at that vote — **[point at the checkpoint card]** — and a scientist can
approve the panel's call, override it, or redirect the next step to a different experiment. Then
the org carries on. The human is just another voice on the panel — the rest stays autonomous.

And this is the key idea — **the loop is iterative.** Each pass asks a **sharper question than
the last.** First pass: 'is B7-H3 expressed and specific?' The answer comes back *stromal* — so
the next pass narrows to: 'is it on the **malignant cells**, or just fibroblasts?' Every loop
interrogates the weakest link in the current hypothesis, so the hypothesis gets **progressively
refined**.

**[Point at the prometheux line]**

Then Prometheux derives the verdict — **TIER: SUPPORTED** — and tells you *why*:
cell-type-specific, tumour-localised, active trial. **[point]** And it writes a full report and
a replayable trace, so the whole run reproduces bit-for-bit."

---

## [2:15–2:45] — HOW WE USED THE SPONSOR TOOLS

**[Slide: sponsor logos]**

"Every layer here runs on the sponsor stack. **Prometheux** is the heart of it — its Vadalog
engine **derives the verdict**, and it's also the *non-silenceable reviewer*: a provably-missing
axis becomes a deductive fact that forces the org to re-work. **Tavily** powers the live
literature search the scientists call. The whole org is assembled on the **ClawBio** skill
platform — we reuse its bioinformatics skills as the agents' tools. And **Langfuse** mirrors the
entire loop as a hosted, replayable trace. Every one is optional — the workflow always degrades
to an offline, reproducible path."

---

## [2:45–3:00] — CLOSE

**[Title slide]**

"A multi-agent virtual biotech, with a verdict that's deductively derived and fully provenanced.
That's the Virtual Biotech CSO. Thanks for watching."

---

### Recording checklist
- Pre-run `--demo` once so fixtures are warm and output streams cleanly.
- Confirm your narration matches the real output lines (cited edges · `2/4 lenses vote re-route` · `TIER = SUPPORTED`).
- Have `architecture.svg` and the title slide open in tabs to cut to.
- Keep the terminal font large.
- If you run long, trim the iterative-loop paragraph to the two example questions — the demo is the star.
- **The human-in-the-loop beat is optional.** To show it, run the UI (`python3 frontend/server.py`) and tick **🧑‍⚖️ human in the loop** before submitting — the loop will pause at each reviewer pass with a checkpoint card (approve / override / redirect / add a gap). For the tight 3:00 cut, *say* the HITL line over the autonomous re-route and skip the live pause; for a longer demo, show the pause and click **override** or **redirect** once.
