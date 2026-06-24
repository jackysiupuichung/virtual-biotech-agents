# Frontend — Virtual Biotech CSO report viewer

A self-contained report viewer for the `virtual-biotech-cso` multi-agent harness, built
for a hackathon demo. Two views over a single CSO run:

- **Report** — the target-assessment dossier: decision (GO / CONDITIONAL_GO / REVIEW /
  NO_GO), confidence, executive summary, liabilities & mitigations, evidence gaps, and
  proposed experiments.
- **Loop trace** — the **traceability hero**: a step-by-step timeline of the orchestration
  loop (Chief-of-Staff briefing → routed skills → Scientific Reviewer audit →
  one-pass **re-route** → CSO synthesis). Each step shows whether it was an **agent** role
  or a routed **skill**, its provenance (🗄️ retrieved · 🔧 computed · 🌐 web · ⚪ gap), an
  evidence grade, and — on click — its inputs, metrics (e.g. τ, bimodality), and detail.

It renders the **B7-H3 / CD276** demo case from
`skills/virtual-biotech-cso/demo_data/b7h3/` (illustrative cached fixtures, labelled as
such — see the workflow at [`workflows/b7h3_adc_nomination.md`](../workflows/b7h3_adc_nomination.md)).

## Run

Just open the file — no server, no Node, no network:

```bash
open frontend/index.html      # macOS
```

All dependencies (React, ReactDOM, Tailwind) are **vendored** under `frontend/vendor/`, so
the page renders fully offline. This is deliberate: a demo machine on flaky conference wifi
still shows the full UI.

## Files

| File | Role |
|---|---|
| `index.html` | Page shell; loads vendored libs + `data.js` + `app.js`. |
| `app.jsx` | Source (JSX). **Edit this**, then rebuild. |
| `app.js` | Precompiled from `app.jsx` (classic `React.createElement` runtime — no Babel at runtime). |
| `data.js` | `window.CSO_DEMO` — the B7-H3 fixtures bundled as JS (avoids `file://` fetch/CORS). |
| `vendor/` | React, ReactDOM, Tailwind (+ Babel, used only at build time). |
| `build.py` | Regenerates `data.js` and recompiles `app.jsx → app.js`. |

## Rebuild after editing

After changing `app.jsx` or the demo fixtures:

```bash
python3 frontend/build.py
```

`build.py` re-bundles the fixtures into `data.js` and recompiles `app.jsx` into `app.js`
using the vendored Babel via headless Chrome (no Node required).

## Pointing at a different / live run

`data.js` is just `window.CSO_DEMO = {...}` with the same keys as the fixture filenames
(`briefing`, `step_01_gwas`, …, `synthesis`). To render a live `result.json` from
`harness.py`, map its sections to those keys and regenerate `data.js`. The loop model lives
in `buildLoop()` in `app.jsx`.
