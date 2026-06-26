# Frontend — Virtual Biotech CSO (live)

An interactive front-end for the `virtual-biotech-cso` multi-agent harness. You **submit a
target-assessment question** and watch the real loop run: a Chief-of-Staff briefing, the
division scientists, a Scientific Reviewer audit (with one re-route), and a CSO synthesis.
The **loop trace** and the **evidence graph** fill in **real time** as each phase streams
back; the **report** is constructed when the loop completes.

## Run

```bash
python3 frontend/server.py            # then open http://localhost:8765
```

Then type a question (or pick an example) and hit **Run assessment**. Options:

```bash
python3 frontend/server.py --backend claude-cli   # reasoning roles via the local `claude` CLI
python3 frontend/server.py --backend anthropic    # via ANTHROPIC_API_KEY
python3 frontend/server.py --backend stub         # force offline stub path (no LLM)
python3 frontend/server.py --port 9000
```

**Demo mode** (checkbox on the query screen, default on) runs the routed data steps from the
cached B7-H3 fixtures and uses the cached briefing/review/synthesis — fully offline, no LLM,
no network. Reliable for a stage demo, and it still exercises the **re-route loop** and a real
`CONDITIONAL_GO` decision. Unchecking it runs the reasoning roles as live agents via the
selected backend (`auto` picks an API key, else the local `claude` CLI).

## Three synced views

- **Loop trace** — the live timeline: each step appears as it starts (pulsing), then resolves
  with its provenance (🗄️ retrieved · 🔧 computed · 🌐 web · ⚪ gap) and evidence grade. The
  Reviewer's verdict and re-route are shown inline. Click a finished step to expand its detail.
- **Evidence graph** — a **canonical, persistent property graph** (see `kg.py`). Entities are
  deduplicated by stable id (`target:CD276`, `disease:LUAD`, `celltype:fibroblast`,
  `source:cellxgene`, `axis:specificity`), and evidence is metadata on the typed edges between
  them — not per-run blobs. It **grows as evidence arrives** and is marked **complete** when the
  report is built. **Click a node** for its normalized properties and connections; **click an
  edge** to open its reference — source, confidence, a clickable URL, and the loop step it
  traces to. The graph **persists and compounds across queries**: assess B7-H3, then MET, and
  they link on shared `LUAD` / source / axis nodes (marked with a dashed amber ring — "shared
  across runs"). Stored as `frontend/kg.json` (git-ignored; delete it to reset).
- **Report** — the final dossier (decision, confidence, recommendation, liabilities, gaps,
  experiments), constructed from the live synthesis once the loop finishes.

## How it works

```
browser (EventSource)  ──GET /api/run?query=…──►  server.py
        ▲                                            │  run_loop():  reuses cso.py + runners.py,
        └──────── Server-Sent Events ────────────────┘  yields one event per phase
                  (start · phase · briefing · plan · evidence · review · synthesis · done)
```

`server.py` mirrors `harness.run()` but **streams** after each phase instead of only printing.
It reuses the skill's own pure functions (`cso.py`) and pluggable agent runners (`runners.py`),
so the front-end shows the *real* loop — including the reviewer verdict driving a re-route. No
fabrication: with no backend, the reasoning roles fall back to `cso.py`'s honest stubs and the
UI labels the run accordingly.

Shareable links: `http://localhost:8765/?q=<question>&demo=1[&tab=graph]` auto-runs on load.

## Files

| File | Role |
|---|---|
| `server.py` | Live backend: serves the app + streams the loop as SSE (`/api/run`). |
| `kg.py` | Persistent canonical knowledge graph — dedupes entities, compounds across runs. |
| `index.html` | Page shell; loads vendored React/Tailwind + `app.js`. |
| `app.jsx` | Source (JSX). **Edit this**, then rebuild. |
| `app.js` | Precompiled from `app.jsx` (classic `React.createElement`, no runtime Babel). |
| `vendor/` | React, ReactDOM, Tailwind (+ Babel, used only at build time). |
| `build.py` | Recompiles `app.jsx → app.js` offline (vendored Babel via headless Chrome). |

## Rebuild after editing the UI

```bash
python3 frontend/build.py
```
