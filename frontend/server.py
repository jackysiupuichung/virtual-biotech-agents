#!/usr/bin/env python3
"""server.py — live backend for the Virtual Biotech CSO frontend.

Serves the static frontend and exposes a streaming endpoint that runs the real
multi-agent loop and emits one Server-Sent Event per phase, so the UI fills in
real time (loop trace + evidence graph build up; report finalizes at the end).

    python3 frontend/server.py            # http://localhost:8765
    python3 frontend/server.py --port 9000 --backend claude-cli

Endpoints
    GET  /                         -> index.html (and sibling static assets)
    GET  /api/run?query=...&demo=1 -> text/event-stream of loop events

The loop reuses the skill's own pure functions (cso.py) and agent runners
(runners.py); it mirrors harness.run() but yields after each phase instead of
only printing. No fabrication: if no agent backend is available, the reasoning
roles fall back to cso.py's honest stubs and the event stream says so.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "skills" / "virtual-biotech-cso"
sys.path.insert(0, str(SKILL))

import cso          # noqa: E402  (sibling skill module)
import harness      # noqa: E402  (schemas + helpers)
import runners      # noqa: E402
import kg as KG      # noqa: E402  (persistent canonical knowledge graph)

# default config, overridable via CLI
CONFIG = {"backend": "auto", "model": None}

# one shared, persistent knowledge graph across all runs (the cross-query "buildup")
GRAPH = KG.KnowledgeGraph()


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode("utf-8")


import re as _re

# rough query → canonical (target, disease, modality). Good enough to dedupe across runs;
# a real system would resolve symbols against an ontology (Open Targets / EFO).
_DISEASE_ALIASES = {
    "lung adenocarcinoma": "LUAD", "luad": "LUAD", "nsclc": "NSCLC",
    "lung cancer": "LUAD", "non-small-cell lung": "NSCLC",
}
_MODALITY_ALIASES = {"adc": "ADC", "antibody-drug": "ADC", "tki": "TKI",
                     "small molecule": "small-molecule", "antibody": "antibody"}


def parse_entities(query: str) -> dict[str, str]:
    q = query.lower()
    target = (_re.search(r"\b([A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]+)?)\b", query) or [None, "TARGET"])[1]
    disease = next((v for k, v in _DISEASE_ALIASES.items() if k in q), "disease")
    modality = next((v for k, v in _MODALITY_ALIASES.items() if k in q), None)
    return {"target": target, "disease": disease, "modality": modality}


def _ingest_evidence(run_id: str, ents: dict, ev: dict) -> list[tuple[str, dict]]:
    """Upsert one routed-step result as BIOMEDICAL ENTITIES + EVIDENCE EDGES.

    The graph models biology: **nodes are entities** (Target, Disease, CellType,
    Modality, Tissue, Trial) and **edges ARE the evidence** between them — every
    edge carries the axis, value, grade, confidence, provenance, source + url and
    the originating step/run. There are no EvidenceItem/Axis/Source nodes; "where
    did this come from?" is metadata on the edge, "what is it about?" is the two
    entities it connects. Entities dedupe by canonical id, so repeat runs link on
    shared nodes (fibroblast, LUAD, …).
    """
    deltas: list[tuple[str, dict]] = []
    res = ev.get("result", {}) or {}
    target_id = KG.nid("target", ents["target"])
    disease_id = KG.nid("disease", ents["disease"])
    conf = {"strong": 0.9, "illustrative": 0.6, "supported": 0.7, "suggestive": 0.4,
            "absent": 0.1, "insufficient": 0.15}.get(ev.get("grade"), 0.5)
    prov_icon = ev.get("provenance", "")
    prov_kind = {"🧪": "computed", "🔧": "computed", "🗄️": "retrieved", "🌐": "web", "⚪": "gap"}.get(prov_icon, "computed")
    _src_id, src_label, src_url = KG.canonical_source(ev.get("reference", ""), ev["skill"], prov_icon)
    axis = {"step_03_celltype_specificity": "specificity", "step_04_offtarget_safety": "safety",
            "step_01_gwas": "genetics", "step_05_clinical_trials": "tractability",
            "step_06_reroute": "efficacy"}.get(ev["step"], ev.get("division", "evidence"))

    def emit_node(node):
        deltas.append(("node", {**node, "shared_runs": GRAPH.shared_with(node["id"], run_id)}))

    def ev_edge(s, t, etype, *, value=None, ref=None, c=conf):
        """An evidence edge: the claim IS the edge; provenance is its metadata."""
        deltas.append(("edge", GRAPH.upsert_edge(
            s, t, etype, conf=c, axis=axis, value=value, grade=ev.get("grade"),
            prov=prov_kind, source=src_label, url=src_url,
            ref=ref or ev.get("reference"), step=ev["step"], run=run_id)))

    # --- step_02: target EXPRESSED_IN cell types ---------------------------- #
    for c in (res.get("top_cell_types") or [])[:4]:
        ct_id = KG.nid("celltype", c["cell_type"])
        emit_node(GRAPH.upsert_node(ct_id, "CellType", c["cell_type"], run=run_id))
        pct = float(c.get("pct_expressing", 0.5))
        ev_edge(target_id, ct_id, "EXPRESSED_IN", c=pct,
                value=f"{round(pct*100)}% expressing · mean {c.get('mean_expr')}",
                ref=f"{ents['target']} in {c['cell_type']}: mean expr {c.get('mean_expr')}, "
                    f"{round(pct*100)}% expressing.")

    # --- step_03: target SPECIFIC_TO its niche (τ) -------------------------- #
    if res.get("tau") is not None:
        # specificity is a property of the target in the disease context
        ev_edge(target_id, disease_id, "SPECIFIC_TO", value=f"τ={res['tau']}",
                ref=ev.get("reference"))

    # --- step_01: genetic link target → disease ---------------------------- #
    if res.get("lead_associations") is not None:
        n_assoc = len(res["lead_associations"])
        ev_edge(target_id, disease_id, "GENETIC_LINK",
                value=f"{n_assoc} lead assoc." if n_assoc else "no genome-wide assoc.",
                c=conf if n_assoc else 0.2)

    # --- step_04: off-target risk in a broad tissue ------------------------ #
    if res.get("broad_tissue_risk"):
        tis_id = KG.nid("tissue", "broad/normal tissue")
        emit_node(GRAPH.upsert_node(tis_id, "Tissue", "broad/normal tissue", run=run_id))
        ev_edge(target_id, tis_id, "OFF_TARGET_IN",
                value=f"risk: {res['broad_tissue_risk']}")

    # --- step_05: prior trials (target/disease EVALUATED_IN) --------------- #
    for prog in (res.get("example_programs") or [])[:4]:
        tr_id = KG.nid("trial", prog)
        emit_node(GRAPH.upsert_node(tr_id, "Trial", prog, run=run_id))
        ev_edge(target_id, tr_id, "EVALUATED_IN", value="prior program")
        deltas.append(("edge", GRAPH.upsert_edge(
            disease_id, tr_id, "TREATED_IN", conf=conf, axis=axis, prov=prov_kind,
            source=src_label, url=src_url, ref=ev.get("reference"), step=ev["step"], run=run_id)))

    return deltas


def run_loop(query: str, *, demo: bool, live: bool):
    """Generator yielding (event_name, payload) for each phase of the loop."""
    case = cso.case_key(query)
    routing = cso.load_routing()
    run_id = f"run-{case}-{len(GRAPH.nodes)}"  # deterministic-ish; no RNG
    ents = parse_entities(query)
    # Demo mode (and an explicit "stub" backend) force the no-backend path: the reasoning
    # roles use cso.py's cached briefing/review/synthesis instead of a live agent. This keeps
    # the demo fully offline and fast (no LLM/CLI call) while still exercising the re-route
    # loop and a real CONDITIONAL_GO. Non-demo runs use the selected backend (live agents).
    if demo or CONFIG["backend"] == "stub":
        runner = runners.StubRunner()
    else:
        runner = runners.select_runner(CONFIG["backend"], CONFIG["model"])
    calls_llm = runner.name != "stub"

    yield "start", {
        "query": query, "case": case, "run_id": run_id, "entities": ents,
        "backend": runner.name if calls_llm else "none",
        "model": runner.model if calls_llm else "none",
        "calls_llm": calls_llm,
        "mode": "demo" if demo else ("live" if live else "default"),
        "kg_nodes": len(GRAPH.nodes), "kg_edges": len(GRAPH.edges),
    }

    # seed the biomedical backbone: real ENTITIES, linked by the hypothesis edge.
    # The "hypothesis" is no longer a node — it's the Target ──TARGETS──> Disease
    # edge (modality carried as edge metadata). Entities dedupe across runs.
    target_id = KG.nid("target", ents["target"])
    disease_id = KG.nid("disease", ents["disease"])
    backbone = [
        ("node", {**GRAPH.upsert_node(target_id, "Target", ents["target"], run=run_id),
                  "shared_runs": GRAPH.shared_with(target_id, run_id)}),
        ("node", {**GRAPH.upsert_node(disease_id, "Disease", ents["disease"], run=run_id),
                  "shared_runs": GRAPH.shared_with(disease_id, run_id)}),
        ("edge", GRAPH.upsert_edge(target_id, disease_id, "TARGETS", conf=1.0, prov="computed",
                                   modality=ents["modality"], run=run_id)),
    ]
    if ents["modality"]:
        mod_id = KG.nid("modality", ents["modality"])
        backbone.append(("node", {**GRAPH.upsert_node(mod_id, "Modality", ents["modality"], run=run_id),
                                   "shared_runs": GRAPH.shared_with(mod_id, run_id)}))
        # the therapeutic approach: this target is pursued VIA this modality
        backbone.append(("edge", GRAPH.upsert_edge(target_id, mod_id, "VIA_MODALITY", conf=0.9,
                                                   prov="web", run=run_id)))
    for ev_name, payload in backbone:
        yield ev_name, payload

    # 1 — BRIEF (agent role) ------------------------------------------------- #
    yield "phase", {"id": "briefing", "role": "Chief of Staff", "kind": "agent",
                    "division": "Office of CSO", "title": "Field briefing", "status": "running"}
    briefing, brief_src = harness._agent_or_stub(
        _NullTrace(), "chief_of_staff", runner, cso.CHIEF_OF_STAFF_PROMPT,
        f"User query: {query}", harness.BRIEFING_SCHEMA,
        stub=cso.load_briefing(query, case, demo=demo))
    briefing.setdefault("source", brief_src)
    yield "briefing", {"briefing": briefing, "source": brief_src}

    # 2 — DECOMPOSE & ROUTE -------------------------------------------------- #
    subtasks = cso.decompose_and_route(query, case, routing)
    yield "plan", {"subtasks": [t.as_plan_entry() for t in subtasks]}

    # 3 — EXECUTE DIVISIONS (stream each step as it completes) --------------- #
    results: list[dict] = []
    for task in subtasks:
        yield "phase", {"id": task.step, "role": task.skill, "kind": "skill",
                        "division": task.division, "title": task.question, "status": "running"}
        env = cso.execute_skill(task, case, demo, live)
        results.append(env)
        evev = _evidence_event(env)
        yield "evidence", evev
        for ev_name, payload in _ingest_evidence(run_id, ents, evev):
            yield ev_name, payload

    # 4 — REVIEW (agent role; verdict drives control flow) ------------------- #
    yield "phase", {"id": "review", "role": "Scientific Reviewer", "kind": "agent",
                    "division": "Audit loop", "title": "Audit evidence", "status": "running"}
    review, review_src = harness._agent_or_stub(
        _NullTrace(), "scientific_reviewer", runner, cso.REVIEWER_PROMPT,
        harness._evidence_context(results), harness.REVIEW_SCHEMA,
        stub=cso.load_review(query, case, results, demo=demo))
    review.setdefault("source", review_src)
    yield "review", {"review": review}

    # 5 — RE-ROUTE (one follow-up step if the reviewer flagged a gap) -------- #
    if review.get("verdict") == "re-route":
        gap = (review.get("gaps") or [{}])[0]
        followup = cso._reroute_task(gap)
        yield "phase", {"id": followup.step, "role": followup.skill, "kind": "skill",
                        "division": followup.division + " (re-route)", "title": followup.question,
                        "status": "running", "reroute": True,
                        "why": gap.get("missing", "")}
        env = cso.execute_skill(followup, case, demo, live)
        results.append(env)
        evev = {**_evidence_event(env), "reroute": True}
        yield "evidence", evev
        for ev_name, payload in _ingest_evidence(run_id, ents, evev):
            yield ev_name, payload

    # 6 — SYNTHESIZE (agent role) ------------------------------------------- #
    yield "phase", {"id": "synth", "role": "CSO Orchestrator", "kind": "agent",
                    "division": "Synthesis", "title": "Synthesize recommendation",
                    "status": "running", "terminal": True}
    syn_context = (
        f"User query: {query}\n\nBriefing:\n{json.dumps(briefing, default=str)}\n\n"
        f"Evidence:\n{harness._evidence_context(results)}\n\n"
        f"Reviewer:\n{json.dumps(review, default=str)}"
    )
    synthesis, _ = harness._agent_or_stub(
        _NullTrace(), "cso_synthesis", runner, cso.ORCHESTRATOR_PROMPT,
        syn_context, harness.SYNTHESIS_SCHEMA, stub=cso.load_synthesis(query, case, results, demo=demo))
    yield "synthesis", {"synthesis": synthesis}

    # stamp the hypothesis EDGE (Target ──TARGETS──> Disease) with its decision,
    # then persist the whole graph
    decision = (synthesis or {}).get("decision", "REVIEW")
    confidence = (synthesis or {}).get("confidence", "n/a")
    GRAPH.upsert_edge(target_id, disease_id, "TARGETS",
                      decision=decision, confidence=confidence, run=run_id)
    GRAPH.commit()

    # 7 — DONE: assemble report.md + summary -------------------------------- #
    report_md = cso.synthesize_report(query, case, briefing, results, review, synthesis, demo)
    yield "done", {
        "report_md": report_md,
        "decision": decision,
        "confidence": confidence,
        "n_steps": len(results),
        "reviewer_verdict": review.get("verdict", "synthesize"),
        "kg_nodes": len(GRAPH.nodes), "kg_edges": len(GRAPH.edges),
    }


def _evidence_event(env: dict) -> dict:
    """Normalize one routed-step result into a graph/report-ready event."""
    prov_icon, prov_note = cso._provenance(env)
    return {
        "step": env["step"],
        "division": env["division"],
        "skill": env["skill"],
        "question": env.get("question", ""),
        "result": env.get("result", {}),
        "grade": cso._evidence_grade(env),
        "provenance": prov_icon,
        "provenance_note": prov_note,
        "reference": cso._evidence_reference(env),
        "digest": cso._result_digest(env),
        "source": env.get("source", ""),
    }


class _NullTrace:
    """harness._agent_or_stub expects a trace with .step(); we don't need it."""
    def step(self, *a, **k): pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            return self._stream(parse_qs(parsed.query))
        if parsed.path == "/api/ledger":
            return self._ledger()
        return self._static(parsed.path)

    # --- accumulated-evidence ledger ------------------------------------- #
    def _ledger(self):
        rows = GRAPH.ledger()
        # sources now live on the evidence edges, not on nodes — collect them there
        sources = sorted({(r["source"], r["url"]) for r in rows if r["source"]})
        payload = {
            "rows": rows,
            "n_evidence": len(rows),
            "n_runs": len({r for row in rows for r in row["runs"]}),
            "sources": [{"label": l, "url": u} for l, u in sources],
            "kg_nodes": len(GRAPH.nodes), "kg_edges": len(GRAPH.edges),
        }
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- streaming run --------------------------------------------------- #
    def _stream(self, qs):
        query = (qs.get("query", [""])[0] or cso.DEFAULT_QUERY).strip()
        demo = qs.get("demo", ["0"])[0] in ("1", "true")
        live = qs.get("live", ["0"])[0] in ("1", "true")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for event, data in run_loop(query, demo=demo, live=live):
                self.wfile.write(_sse(event, data))
                self.wfile.flush()
        except BrokenPipeError:
            return
        except Exception as exc:  # surface the error to the UI, don't 500 silently
            traceback.print_exc()
            try:
                self.wfile.write(_sse("error", {"message": str(exc)}))
                self.wfile.flush()
            except Exception:
                pass

    # --- static files ---------------------------------------------------- #
    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (HERE / rel).resolve()
        if HERE not in target.parents and target != HERE / rel or not target.is_file():
            # constrain to the frontend dir
            target = (HERE / rel)
        if not target.is_file():
            self.send_error(404)
            return
        ctype = {
            ".html": "text/html", ".js": "application/javascript",
            ".css": "text/css", ".json": "application/json",
            ".png": "image/png", ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description="Live server for the Virtual Biotech CSO frontend.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--backend", choices=["auto", "anthropic", "openai", "claude-cli", "stub"],
                   default="auto", help="Agent backend (default: auto)")
    p.add_argument("--model", default=None, help="Override the model id")
    args = p.parse_args()
    CONFIG["backend"] = args.backend
    CONFIG["model"] = args.model
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Virtual Biotech CSO — live server on http://localhost:{args.port}")
    print(f"  backend={args.backend}  (open the URL and submit a query)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    main()
