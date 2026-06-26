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

The streaming endpoint drives the SAME multi-agent loop the CLI runs
(harness.run), bridging its structured phase events to SSE via an emit callback —
so the browser sees the real planner agent, the concurrent division scientists,
the four-lens reviewer panel, the Prometheux voter, and the bounded review→reroute
loop. No fabrication: if no agent backend is available, the reasoning roles fall
back to cso.py's honest stubs and the event stream says so.
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
import harness      # noqa: E402  (the real multi-agent loop, driven via emit())
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

    def ev_edge(s, t, etype, *, value=None, ref=None, c=conf, url=None):
        """An evidence edge: the claim IS the edge; provenance is its metadata."""
        deltas.append(("edge", GRAPH.upsert_edge(
            s, t, etype, conf=c, axis=axis, value=value, grade=ev.get("grade"),
            prov=prov_kind, source=src_label, url=url or src_url,
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
    # Programs may be plain strings or structured {name/title, nct, url} rows from
    # the live clinical-trial-finder. When a trial carries its own NCT/url, the node
    # and its edges deep-link to that *specific* study record, not the registry base.
    programs = res.get("example_programs") or res.get("trials") or []
    for prog in programs[:4]:
        if isinstance(prog, dict):
            label = prog.get("name") or prog.get("title") or prog.get("nct") or "trial"
            trial_url = prog.get("url") or KG.trial_deep_link(prog.get("nct", "")) or src_url
            tr_key = prog.get("nct") or label
        else:
            label, trial_url, tr_key = prog, src_url, prog
        tr_id = KG.nid("trial", tr_key)
        emit_node(GRAPH.upsert_node(tr_id, "Trial", label, run=run_id, url=trial_url))
        ev_edge(target_id, tr_id, "EVALUATED_IN", value="prior program", url=trial_url)
        deltas.append(("edge", GRAPH.upsert_edge(
            disease_id, tr_id, "TREATED_IN", conf=conf, axis=axis, prov=prov_kind,
            source=src_label, url=trial_url, ref=ev.get("reference"), step=ev["step"], run=run_id)))

    return deltas


def run_loop(query: str, *, demo: bool, live: bool, partial: bool = False,
             backend: str | None = None):
    """Generator yielding (event_name, payload) for each phase of the loop.

    This drives the REAL multi-agent loop — ``harness.run()`` — and bridges its
    structured phase events to SSE. It is no longer a re-implementation that can
    drift: the planner agent, the N concurrent division scientists, the four-lens
    reviewer panel, the Prometheux voter, and the bounded review→reroute loop are
    exactly what the CLI runs. The harness pushes events via an ``emit`` callback;
    a background thread runs the loop while this generator forwards events (plus the
    graph deltas it derives from ``evidence`` events) to the browser in order.

    ``partial`` is unused now (kept for endpoint compatibility); the engine's
    structural-gap forcing is demonstrated by the live loop itself.
    """
    case = cso.case_key(query)
    run_id = f"run-{case}-{len(GRAPH.nodes)}"  # deterministic-ish; no RNG
    ents = parse_entities(query)
    # The reasoning roles run on `backend`: a per-request override (the UI's "live
    # agents" toggle) wins over the server's launch default. "stub" → honest offline
    # stubs (instant, deterministic — the default demo path); "auto"/a named provider
    # → real agent calls. DATA is cached whenever `demo` is set, independent of this.
    backend = backend or CONFIG["backend"]

    # Bridge the harness's emit-callback into this generator via a queue + worker
    # thread (harness.run is blocking; we want to stream as events arrive).
    import queue
    import threading
    q: "queue.Queue[tuple[str, dict] | None]" = queue.Queue()
    box: dict[str, Any] = {}

    def emit(event: str, payload: dict) -> None:
        q.put((event, payload))

    def worker() -> None:
        try:
            box["result"] = harness.run(
                query, None, backend=backend, model=CONFIG["model"],
                demo=demo, live=live, argv=[], emit=emit, quiet=True)
        except Exception as exc:  # surface to the stream, then end it
            box["error"] = exc
        finally:
            q.put(None)  # sentinel: loop finished

    # --- backbone: seed real ENTITIES before the loop streams evidence ------- #
    target_id = KG.nid("target", ents["target"])
    disease_id = KG.nid("disease", ents["disease"])
    target_canon = KG.canonical_entity("target", ents["target"])
    disease_canon = KG.canonical_entity("disease", ents["disease"])
    yield "start", {
        "query": query, "case": case, "run_id": run_id, "entities": ents,
        "mode": "demo" if demo else ("live" if live else "default"),
        "kg_nodes": len(GRAPH.nodes), "kg_edges": len(GRAPH.edges),
    }
    backbone = [
        ("node", {**GRAPH.upsert_node(target_id, "Target", ents["target"],
                                      run=run_id, **target_canon),
                  "shared_runs": GRAPH.shared_with(target_id, run_id)}),
        ("node", {**GRAPH.upsert_node(disease_id, "Disease", ents["disease"],
                                      run=run_id, **disease_canon),
                  "shared_runs": GRAPH.shared_with(disease_id, run_id)}),
        ("edge", GRAPH.upsert_edge(target_id, disease_id, "TARGETS", conf=1.0, prov="computed",
                                   modality=ents["modality"], run=run_id)),
    ]
    if ents["modality"]:
        mod_id = KG.nid("modality", ents["modality"])
        backbone.append(("node", {**GRAPH.upsert_node(mod_id, "Modality", ents["modality"], run=run_id),
                                   "shared_runs": GRAPH.shared_with(mod_id, run_id)}))
        backbone.append(("edge", GRAPH.upsert_edge(target_id, mod_id, "VIA_MODALITY", conf=0.9,
                                                   prov="web", run=run_id)))
    for ev_name, payload in backbone:
        yield ev_name, payload

    # --- run the real loop, forwarding its events (+ derived graph deltas) --- #
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    review_verdict = "synthesize"
    while True:
        item = q.get()
        if item is None:
            break
        event, payload = item
        # The server already emitted a richer "start" (entities + run_id + kg counts)
        # before launching the loop, and composes its own terminal "done" (with the
        # cross-run ranking) below — so swallow the harness's own start/done.
        if event in ("start", "done"):
            box[f"harness_{event}"] = payload
            continue
        yield event, payload
        # Every routed-step evidence event becomes biomedical nodes + edges.
        if event == "evidence":
            for ev_name, ev_payload in _ingest_evidence(run_id, ents, payload):
                yield ev_name, ev_payload
        elif event == "review":
            review_verdict = payload.get("review", {}).get("verdict", review_verdict)
        elif event == "decision":
            # stamp the hypothesis EDGE with the decision of record
            GRAPH.upsert_edge(target_id, disease_id, "TARGETS",
                              decision=payload.get("decision"),
                              confidence=payload.get("confidence"), run=run_id)
    thread.join()

    if box.get("error") is not None:
        raise box["error"]
    result = box.get("result", {})

    # persist the graph, then explain-a-rank over it (meaningful from run #2 on)
    GRAPH.commit()
    ranking_payload = _prometheux_ranking()
    yield "done", {
        "report_md": result.get("report_md", ""),
        "decision": result.get("summary", {}).get("decision"),
        "decision_source": result.get("summary", {}).get("decision_source"),
        "confidence": result.get("summary", {}).get("confidence"),
        "n_steps": result.get("summary", {}).get("n_steps"),
        "reviewer_verdict": result.get("summary", {}).get("reviewer_verdict", review_verdict),
        "ranking": ranking_payload,
        "kg_nodes": len(GRAPH.nodes), "kg_edges": len(GRAPH.edges),
    }


def _graded(results: list[dict], target: str) -> tuple[list[dict], str]:
    """Attach the derived grade to each step + extract a target symbol (for the engine)."""
    graded = [{**e, "grade": cso._evidence_grade(e), "step": e.get("step")} for e in results]
    return graded, target


def _prometheux_gaps(results: list[dict], target: str) -> list[dict]:
    """Run the Prometheux gap-detector over the routed evidence (guarded)."""
    try:
        import prometheux_reason as pr
        graded, tgt = _graded(results, target)
        return pr.gaps_from_evidence(graded, tgt)
    except Exception:  # noqa: BLE001 — degrade silently; the panel still works
        return []


def _prometheux_decision(results: list[dict], target: str) -> dict | None:
    """Run the Prometheux decision layer over the routed evidence (guarded)."""
    try:
        import prometheux_reason as pr
        graded, tgt = _graded(results, target)
        return pr.decide_from_evidence(graded, tgt)
    except Exception:  # noqa: BLE001 — degrade; agent decision stands
        return None


def _prometheux_ranking() -> dict:
    """Explain-a-rank over the persistent graph: why one target ranks over another.

    Reads the accumulated multi-run graph (not a single run's evidence), so the
    leaderboard only becomes meaningful once two or more targets have been assessed.
    Guarded — degrades to an empty board if the engine is unavailable.
    """
    try:
        import prometheux_reason as pr
        return {"leaderboard": pr.rank_targets(GRAPH),
                "edges": pr.rank_explanations(GRAPH)}
    except Exception:  # noqa: BLE001 — degrade; the ledger view still works
        return {"leaderboard": [], "edges": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter console
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            return self._stream(parse_qs(parsed.query))
        if parsed.path == "/api/ledger":
            return self._ledger()
        if parsed.path == "/api/ranking":
            return self._json(_prometheux_ranking())
        return self._static(parsed.path)

    def _json(self, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self._json(payload)

    # --- streaming run --------------------------------------------------- #
    def _stream(self, qs):
        query = (qs.get("query", [""])[0] or cso.DEFAULT_QUERY).strip()
        demo = qs.get("demo", ["0"])[0] in ("1", "true")
        live = qs.get("live", ["0"])[0] in ("1", "true")
        partial = qs.get("partial", ["0"])[0] in ("1", "true")
        # The UI's "live agents" toggle drives the WHOLE run, not just reasoning:
        #   agents=1 → real LLM agents (backend) AND execute routed skills for real
        #             (live=True, demo=False) — data is fetched, not cached.
        #   agents=0 → instant offline stubs over cached fixtures (demo=True).
        # It is authoritative over the demo/live params (which the UI always sends a
        # default for). Omit `agents` entirely (e.g. a hand-built link) to drive
        # demo/live manually with the server's default backend.
        agents = qs.get("agents", [None])[0]
        backend = None
        if agents in ("1", "true"):
            backend = CONFIG["backend"] if CONFIG["backend"] != "stub" else "auto"
            live, demo = True, False
        elif agents in ("0", "false"):
            backend = "stub"
            demo, live = True, False
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for event, data in run_loop(query, demo=demo, live=live, partial=partial,
                                        backend=backend):
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
    # Route map: "/" serves the marketing landing site; "/app" serves the live
    # console. Everything else falls through to a path under frontend/.
    ROUTES = {
        "": "site/index.html",
        "/": "site/index.html",
        "/app": "index.html",
        "/app/": "index.html",
        "/console": "index.html",
        "/schematic": "site/schematic.html",
        "/schematic.html": "site/schematic.html",
    }

    def _static(self, path):
        rel = self.ROUTES.get(path, path.lstrip("/"))
        # Resolve and constrain strictly within the frontend dir (no traversal).
        target = (HERE / rel).resolve()
        if HERE != target and HERE not in target.parents:
            self.send_error(403)
            return
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
    p.add_argument("--backend", choices=["auto", "anthropic", "openai", "gemini", "claude-cli", "stub"],
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
