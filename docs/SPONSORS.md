# 🏆 Sponsors

This project was built at the **[Multiagents Hackathon](https://multiagents-hackathon.devpost.com/)
("tokens& Hacks")**, hosted by **[Tessl AI](https://tessl.io)** in London on **4 Jul 2026** —
*"build something real with multi-agent systems."*

The event is backed by Google DeepMind, ClickHouse, Gensyn, **Prometheux**, **Tavily**,
Cursor, ElevenLabs, Twilio, **Tessl**, and Senso.

---

## 🥇 Prometheux — primary sponsor (Intelligence Prize)

**[Prometheux](https://prometheux.ai) is the decision layer of this project**, not a bolt-on.
The GO / NO-GO verdict is **derived deductively** by a **Prometheux Vadalog** program — *no
LLM generates the verdict*.

### How it's implemented

All in [`prometheux_reason.py`](../skills/virtual-biotech-cso/prometheux_reason.py):

1. **Graph → Vadalog facts.** The CSO evidence graph ([`kg.py`](../skills/virtual-biotech-cso/kg.py))
   is already a Datalog fact base — every cited edge is a ground atom with confidence +
   provenance. `graph_to_vada()` compiles it into a `.vada` program (facts + recursive rules
   + `@model` / `@explain` annotations). Inspect it with `python3 prometheux_reason.py --vada`.
2. **Recursive reasoning rules.** The program derives explainable conclusions — e.g.
   `co_niche(A,B)` (shared cell-type niche, recursive), `strong_claim(T,Ax)` (a
   confidence-gated ≥ 0.8 claim as a first-class rule), and `differentiates(A,B,Ax)` (the
   *explain-a-rank* edges showing **why** one target ranks over another).
3. **Two execution paths, one program.**
   - **Live Prometheux** (`_reason_prometheux`, when `PMTX_TOKEN` is set): the hosted Vadalog
     engine runs the rules via the `prometheux-chain` SDK — a `project → concept → run →
     fetch` sequence POSTed to the JarvisPy backend (`JARVISPY_URL`) — and returns native
     `@explain` output: each derived fact with a human-readable rule-chain.
   - **Local fallback**: a small in-process semi-naive Datalog evaluator over the *same*
     facts + rules, emitting the same `@model` strings. No network, no token, fully
     reproducible — so the reasoning always runs. Both paths return the identical
     `ReasonResult` shape, so callers are engine-agnostic.
4. **Load-bearing role — the reviewer's gap-detector.** `derive_gaps(graph)` runs a
   *structural-gap* rule set and returns gaps in the exact shape the harness reviewer panel
   consumes (`{missing, route_to, why, lenses, explanation, forces_reroute}`). A proven
   missing prioritization axis (no `evidence(T, Ax, _)` at all) is a **deductive fact, not a
   judgement call** — so Prometheux becomes a *non-silenceable panel member*: such a gap
   forces a re-route on its own. Pull this module and the panel goes blind to structural gaps.

```bash
python3 prometheux_reason.py            # local fallback
PMTX_TOKEN=... python3 prometheux_reason.py   # live hosted engine
python3 prometheux_reason.py --vada     # print the .vada program
python3 prometheux_reason.py --gaps     # the reviewer gap-detector output
```

> 🎯 We target the **Prometheux Intelligence Prize** (best overall project built with Prometheux).

---

## 🔍 Tavily — live literature search

**[Tavily](https://tavily.com)** powers the live literature search feeding the cited
knowledge graph.

### How it's implemented

In [`lit_synthesizer.py`](../skills/lit-synthesizer/lit_synthesizer.py): the Clinical &
Literature division queries the **Tavily Search API** (`https://api.tavily.com/search`)
across **three search angles** — each a query template — then deduplicates and returns
`{title, url, content, score}` items as **cited** evidence. It is API-backed and
reproducible, **not page scraping**: every claim carries a source URL. Live mode needs
`TAVILY_API_KEY`; `--demo` replays a cached, real-shaped Tavily response with no key or
network. The harness ([`harness.py`](../skills/virtual-biotech-cso/harness.py)) routes a
re-route to this skill when the reviewer panel needs deeper literature evidence.

---

## 🧰 Tessl — host

**[Tessl AI](https://tessl.io)** hosted the hackathon and set the brief: ship something real
with multi-agent systems.

---

## Supporting runtime

- **[ClawBio](https://github.com/ClawBio/ClawBio)** — the skill runtime each scientist
  division executes over real public databases (Open Targets, CELLxGENE, TCGA, DepMap,
  openFDA, ClinicalTrials.gov).

---

*See [PROJECT.md](PROJECT.md) for the project overview and [README](../README.md) for full architecture.*
