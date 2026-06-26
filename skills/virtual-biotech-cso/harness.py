#!/usr/bin/env python
"""harness.py — run virtual-biotech-cso as a LIVE multi-agent loop.

``cso.py`` is a deterministic orchestrator that plans, routes to ClawBio skills,
and assembles a report — but it makes no LLM call. Its three reasoning roles
(Chief of Staff, Scientific Reviewer, CSO synthesis) are emitted as delegation
stubs for a *driving agent* to fill. This harness IS that driving agent.

It reuses cso.py's pure functions for everything deterministic (decompose/route,
execute routed skills, render the report, write the output contract) and
replaces only the three reasoning slots with live agent calls via ``runners.py``
— a pluggable backend (Anthropic SDK primary, OpenAI-compatible fallback) that
runs in any environment, not only where Claude Code is installed.

The defining behaviour cso.py could not show on its own: the **live reviewer
verdict drives control flow** — when the reviewer returns ``re-route``, the
harness executes one real follow-up step before synthesis. When no backend is
configured it degrades to cso.py's honest stubs (never fabricates) and says so.

Usage:
    python harness.py --query "Assess B7-H3 ... in lung cancer" [--out ./output]
                      [--backend auto|anthropic|openai] [--model NAME]
                      [--demo]   # use cached fixtures for the routed DATA steps,
                                 # but still run the three roles as live agents
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

# Structured phase-event sink: emit(event_name, payload). The frontend supplies
# one to stream the live loop as SSE; the CLI leaves it unset (console only).
Emit = Callable[[str, dict[str, Any]], None]

import cso  # sibling module — reused, never modified
import runners
from tracing import TraceRecorder

# --- JSON schemas per role (harvested from prompts/*.md) -------------------- #
BRIEFING_SCHEMA = {
    "context": "string",
    "data_availability": [{"source": "string", "relevance": "high|medium|low", "note": "string"}],
    "priority_questions": ["string"],
    "feasibility_flags": ["string"],
}
REVIEW_SCHEMA = {
    "verdict": "synthesize|re-route",
    "scores": {"relevance": "1-5", "evidence": "1-5", "thoroughness": "1-5"},
    "gaps": [{"missing": "string", "route_to": "skill-name", "why": "string"}],
    "experiments": [{"missing": "string", "proposed_experiment": "string",
                     "route_to": "skill-name", "expected_readout": "string", "why": "string"}],
}
PLAN_SCHEMA = {
    "subtasks": [{"division": "string (a routing.yaml division)",
                  "intent": "string (an intent under that division)",
                  "question": "string", "depends_on": ["step_NN_intent"]}],
}
DIVISION_FINDING_SCHEMA = {
    "division": "string",
    "interpretation": "string (cite [step_NN])",
    "confidence": "high|medium|low",
    "caveats": ["string"],
    "evidence_grade": "strong|supporting|weak",
}
SYNTHESIS_SCHEMA = {
    "decision": "GO|CONDITIONAL_GO|REVIEW|NO_GO",
    "confidence": "high|medium|low",
    "recommendation": "string (cite evidence steps e.g. [step_03])",
    "target_overview": "string",
    "liabilities": [{"risk": "string", "mitigation": "string"}],
    "evidence_gaps": ["string"],
    "proposed_experiments": [{"experiment": "string", "expected_readout": "string",
                              "rationale": "string"}],
}

AGENT_SOURCE = "agent (live)"  # provenance tag for agent-produced slots
MAX_REROUTES = 3  # change #2: bound the review→reroute loop (avoid unbounded recursion)


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _usage_of(runner: runners.Runner) -> dict[str, int]:
    """Token usage from the runner's last call, tolerant of runners that omit it.

    ``last_usage`` is an optional part of the Runner protocol — a custom or test
    runner need not set it. Missing/empty → no tokens recorded for that span."""
    return getattr(runner, "last_usage", None) or {}


def _evidence_context(results: list[dict[str, Any]]) -> str:
    """Compact JSON of the routed evidence for the reviewer / synthesis agent."""
    slim = [{"step": e["step"], "division": e["division"], "skill": e["skill"],
             "question": e["question"], "result": e.get("result", {})} for e in results]
    return json.dumps(slim, indent=2, default=str)


class Trace:
    """Prints a per-step trace so the multi-agent loop is visible in the demo.

    Also carries an optional structured ``emit(event, payload)`` callback. The CLI
    leaves it None (console only); the frontend passes one so the SAME loop streams
    per-phase events to the UI — keeping one source of truth for the multi-agent
    loop instead of a re-implementation that drifts. ``event`` is a no-op when no
    emitter is set, so threading it through the helpers costs the CLI nothing.
    """

    def __init__(self, backend: str, model: str,
                 emit: "Emit | None" = None, *, quiet: bool = False) -> None:
        self._emit = emit
        self._quiet = quiet
        if not quiet:
            print("┌─ virtual-biotech CSO · live multi-agent loop")
            print(f"│  backend: {backend}  model: {model}\n│")

    def step(self, icon: str, msg: str) -> None:
        if not self._quiet:
            print(f"│  {icon} {msg}")

    def event(self, name: str, payload: dict[str, Any]) -> None:
        """Emit a structured phase event to the UI (no-op without an emitter)."""
        if self._emit is not None:
            self._emit(name, payload)

    def done(self, report: str) -> None:
        if not self._quiet:
            print(f"│\n└─ wrote {report}")


def _agent_or_stub(trace: Trace, role: str, runner: runners.Runner, prompt: Path,
                   context: str, schema: dict[str, Any], stub: dict[str, Any],
                   rec: TraceRecorder) -> tuple[dict[str, Any], str]:
    """Run a reasoning role live; on any failure fall back to cso's honest stub.

    Returns (payload, source) where source is AGENT_SOURCE or cso's DELEGATE.
    Each call opens a ``rec`` span tagged with the backend, status (ok/stub), and
    token usage — the degradation moments land as ``status="stub"`` spans.
    """
    with rec.span(role, kind="agent", backend=runner.name, model=runner.model) as sp:
        try:
            payload = runners.run_with_retry(runner, _read_prompt(prompt), context, schema)
            sp.record_usage(**_usage_of(runner)).set(source=AGENT_SOURCE)
            trace.step("🤖", f"{role}: live agent ({runner.name})")
            return payload, AGENT_SOURCE
        except runners.NoBackendError as exc:
            sp.status = "stub"
            sp.set(source=cso.DELEGATE, degraded="no-backend", reason=str(exc))
            trace.step("⚪", f"{role}: {exc}")
            return stub, cso.DELEGATE
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            sp.status = "stub"
            sp.set(source=cso.DELEGATE, degraded="agent-failed", reason=str(exc))
            trace.step("⚠️", f"{role}: agent failed ({exc}); using honest stub")
            return stub, cso.DELEGATE


def _plan(trace: Trace, runner: runners.Runner, query: str, briefing: dict[str, Any],
          case: str, routing: dict[str, Any], rec: TraceRecorder
          ) -> tuple[list[cso.Subtask], str]:
    """Ask the planning agent for a plan; validate + bind it, else fall back.

    This is change #1 from docs/ai-scientist-landscape-review.md: the plan becomes an
    *agent output* validated against routing.yaml, not a deterministic lookup. The
    agent may only reference real (division, intent) pairs — anything invented, or any
    backend failure, degrades to cso.decompose_and_route (the honest deterministic plan).
    """
    catalog = cso._routable_intents(routing)
    menu = "\n".join(f"- {div}: {', '.join(sorted(ix))}" for div, ix in catalog.items())
    context = (
        f"User query: {query}\n\nBriefing:\n{json.dumps(briefing, default=str)}\n\n"
        f"Propose a plan. Each subtask must use one (division, intent) pair from this "
        f"routing menu — do not invent divisions, intents, or skills:\n{menu}\n\n"
        f"depends_on entries must reference earlier steps as step_NN_<intent>."
    )
    with rec.span("planner", kind="agent", backend=runner.name, model=runner.model) as sp:
        try:
            payload = runners.run_with_retry(
                runner, _read_prompt(cso.ORCHESTRATOR_PROMPT), context, PLAN_SCHEMA)
            subtasks = cso.validate_and_bind_plan(payload.get("subtasks", []), routing)
            sp.record_usage(**_usage_of(runner)).set(
                source=AGENT_SOURCE, n_steps=len(subtasks), validated=True)
            trace.step("🗺️", f"planner: agent-proposed plan ({len(subtasks)} steps, validated)")
            return subtasks, AGENT_SOURCE
        except runners.NoBackendError:
            subtasks = cso.decompose_and_route(query, case, routing)
            sp.status = "stub"
            sp.set(source=cso.DELEGATE, degraded="no-backend", n_steps=len(subtasks))
            trace.step("⚪", f"planner: no backend → deterministic plan ({len(subtasks)} steps)")
            return subtasks, cso.DELEGATE
        except Exception as exc:  # noqa: BLE001 — incl. PlanValidationError; degrade, never fabricate
            subtasks = cso.decompose_and_route(query, case, routing)
            sp.status = "stub"
            sp.set(source=cso.DELEGATE, degraded=type(exc).__name__,
                   reason=str(exc), n_steps=len(subtasks))
            trace.step("⚠️", f"planner: {type(exc).__name__} → deterministic plan ({exc})")
            return subtasks, cso.DELEGATE


def _review_panel(trace: Trace, runner: runners.Runner, results: list[dict[str, Any]],
                  routing: dict[str, Any], rec: TraceRecorder,
                  query: str = "") -> dict[str, Any]:
    """Fan out N lens-specialised reviewers concurrently, then aggregate (panel).

    Each lens is an independent agent call with the shared reviewer prompt plus its
    own focus; they run in a thread pool (true concurrent multi-agent). A lens that
    fails abstains honestly (synthesize, no gaps) rather than crashing the panel.
    The deterministic cso.aggregate_panel_review folds them into one verdict the
    loop consumes unchanged. Only invoked on a live backend (stub keeps 1 reviewer).
    """
    prompt = _read_prompt(cso.REVIEWER_PROMPT)
    evidence = _evidence_context(results)

    # Announce the panel: one running phase per lens (concurrent reviewer agents).
    trace.event("phase", {"id": "review", "role": "Scientific Reviewer panel",
                          "kind": "agent", "division": "Audit loop",
                          "title": f"{len(cso.REVIEWER_LENSES)} lens reviewers audit evidence",
                          "status": "running",
                          "lenses": [l["key"] for l in cso.REVIEWER_LENSES]})

    def _one(lens: dict[str, str]) -> tuple[str, dict[str, Any]]:
        ctx = f"## Your review lens: {lens['key']}\nFocus on: {lens['focus']}\n\n{evidence}"
        with rec.span(f"reviewer:{lens['key']}", kind="agent",
                      backend=runner.name, model=runner.model) as sp:
            try:
                payload = runners.run_with_retry(runner, prompt, ctx, REVIEW_SCHEMA)
                sp.record_usage(**_usage_of(runner)).set(source=AGENT_SOURCE,
                                                         verdict=payload.get("verdict"))
                return lens["key"], payload
            except Exception as exc:  # noqa: BLE001 — a lens abstains, never fabricates
                sp.status = "stub"
                sp.set(degraded="lens-failed", reason=str(exc))
                return lens["key"], {"verdict": "synthesize", "scores": {}, "gaps": [],
                                     "experiments": []}

    with rec.span("review_panel", kind="loop", n_lenses=len(cso.REVIEWER_LENSES)) as panel_sp:
        with ThreadPoolExecutor(max_workers=len(cso.REVIEWER_LENSES)) as pool:
            lens_reviews = list(pool.map(_one, cso.REVIEWER_LENSES))
        engine_gaps = _engine_gaps(trace, results, rec, query)
        review = cso.aggregate_panel_review(lens_reviews, routing, extra_gaps=engine_gaps)
        panel = review["panel"]
        panel_sp.set(verdict=review["verdict"], reroute_votes=panel["reroute_votes"],
                     forced_by_engine=panel.get("forced_by_engine", False))
    review["source"] = AGENT_SOURCE
    forced = " (engine-forced)" if panel.get("forced_by_engine") else ""
    trace.step("👥", f"reviewer panel: {panel['reroute_votes']}/{panel['n_lenses']} lenses "
               f"flag re-route → verdict {review['verdict']}{forced}")
    # Per-lens verdicts so the UI can render the panel vote, then the engine's
    # structural gaps as a distinct (non-silenceable) voice, then the folded review.
    trace.event("panel", {"lenses": [{"key": k, "verdict": r.get("verdict"),
                                      "scores": r.get("scores", {})}
                                     for k, r in lens_reviews],
                          "reroute_votes": panel["reroute_votes"],
                          "n_lenses": panel["n_lenses"]})
    trace.event("engine_gaps", {"gaps": engine_gaps,
                                "forced": any(g.get("forces_reroute") for g in engine_gaps)})
    trace.event("review", {"review": review})
    return review


def _engine_gaps(trace: Trace, results: list[dict[str, Any]],
                 rec: TraceRecorder, query: str = "") -> list[dict[str, Any]]:
    """Prometheux gap-detector: derive *structural* gaps as a non-silenceable vote.

    The reviewer panel's LLM lenses catch semantic gaps; the Vadalog engine catches
    structural ones — a required prioritization axis with no graded evidence at all —
    as a derived fact with a replayable explanation. Such a gap carries
    ``forces_reroute`` so it re-routes on its own (the engine is load-bearing here).
    Import is local + guarded so a missing module never breaks the panel.
    """
    with rec.span("prometheux_gaps", kind="agent", backend="prometheux") as sp:
        try:
            import re

            import prometheux_reason as pr
            # a target symbol for the gap explanation (e.g. "B7-H3" from the query)
            m = re.search(r"\b([A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]+)?)\b", query or "")
            target = m.group(1) if m else (query or "target")
            graded = [{**e, "grade": cso._evidence_grade(e), "step": e.get("step")}
                      for e in results]
            gaps = pr.gaps_from_evidence(graded, target)
            n_forcing = sum(1 for g in gaps if g.get("forces_reroute"))
            sp.set(source="prometheux", n_gaps=len(gaps), forcing=n_forcing)
            if gaps:
                kind = (f"{n_forcing} structural" if n_forcing else f"{len(gaps)} weak")
                trace.step("🔷", f"prometheux: {kind} gap(s) "
                           f"→ {', '.join(g['route_to'] for g in gaps)}"
                           + (" [forces re-route]" if n_forcing else ""))
            return gaps
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            sp.status = "stub"
            sp.set(degraded="engine-unavailable", reason=str(exc))
            return []


def _engine_decision(trace: Trace, results: list[dict[str, Any]],
                     rec: TraceRecorder, query: str = "") -> dict[str, Any] | None:
    """Prometheux decision layer: derive a quantitative, replayable GO/NO-GO tier.

    Runs the same graded evidence the gap-detector sees through the decision rules —
    a weighted per-axis coverage score plus a non-negotiable safety hard-gate. The
    derived tier is *authoritative* for the report's Decision field; the synthesis
    agent's free-text becomes rationale (logic decides, the agent explains). Import
    is local + guarded so a missing module never breaks synthesis — returns None.
    """
    with rec.span("prometheux_decision", kind="agent", backend="prometheux") as sp:
        try:
            import re

            import prometheux_reason as pr
            m = re.search(r"\b([A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]+)?)\b", query or "")
            target = m.group(1) if m else (query or "target")
            graded = [{**e, "grade": cso._evidence_grade(e), "step": e.get("step")}
                      for e in results]
            decision = pr.decide_from_evidence(graded, target)
            sp.set(source="prometheux", tier=decision["tier"], score=decision["score"])
            trace.step("🔷", f"prometheux decision: {decision['tier']} "
                       f"(score {decision['score']}/{decision['max_score']})")
            return decision
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            sp.status = "stub"
            sp.set(degraded="engine-unavailable", reason=str(exc))
            return None


def _review_loop(trace: Trace, runner: runners.Runner, query: str, case: str,
                 routing: dict[str, Any], results: list[dict[str, Any]],
                 demo: bool, live: bool, rec: TraceRecorder) -> dict[str, Any]:
    """Run reviewer→reroute until `synthesize` or MAX_REROUTES (changes #2 + #3).

    Each iteration re-runs the reviewer over the *current* evidence (so a re-route's
    new step is itself reviewable), and on a `re-route` verdict executes one follow-up
    bound to the reviewer's chosen skill — validated against the catalog, with a
    numbered step id so successive re-routes don't collide. Returns the *last*
    reviewer payload (the one the synthesis sees), with its source tag set.
    """
    panel_capable = runner.name != "stub"  # a live backend → fan out the reviewer panel
    review: dict[str, Any] = {}
    with rec.span("review_loop", kind="loop", mode="panel" if panel_capable else "single"
                  ) as loop_sp:
        for i in range(MAX_REROUTES + 1):  # initial review + up to MAX_REROUTES follow-ups
            if panel_capable:
                review = _review_panel(trace, runner, results, routing, rec, query)
                review_src = AGENT_SOURCE
            else:
                trace.event("phase", {"id": "review", "role": "Scientific Reviewer",
                                      "kind": "agent", "division": "Audit loop",
                                      "title": "Audit evidence", "status": "running"})
                review, review_src = _agent_or_stub(
                    trace, "scientific_reviewer", runner, cso.REVIEWER_PROMPT,
                    _evidence_context(results), REVIEW_SCHEMA,
                    stub=cso.load_review(query, case, results, demo=demo), rec=rec)
                # The Prometheux gap-detector is deterministic — it runs on the stub
                # path too, and a forcing structural gap re-routes even when no live
                # reviewer panel is available (the engine is the non-silenceable voter).
                engine_gaps = _engine_gaps(trace, results, rec, query)
                if engine_gaps:
                    merged = cso.aggregate_panel_review(
                        [("scientific_reviewer", review)], routing, extra_gaps=engine_gaps)
                    review = {**review, "verdict": merged["verdict"],
                              "gaps": merged["gaps"], "panel": merged["panel"]}
                trace.event("engine_gaps", {
                    "gaps": engine_gaps,
                    "forced": any(g.get("forces_reroute") for g in engine_gaps)})
                trace.event("review", {"review": review})
            review.setdefault("source", review_src)

            if review.get("verdict") != "re-route":
                trace.step("✅", f"reviewer verdict: {review.get('verdict', 'synthesize')}")
                break
            if i == MAX_REROUTES:
                trace.step("🛑", f"reviewer still re-routing after {MAX_REROUTES} passes; "
                           "synthesizing with residual gaps")
                break

            # Convergence: a reroute only adds evidence if it runs a skill we have
            # not already run. Resolve each gap to its *actual* skill (via
            # _reroute_task, which validates the reviewer's route_to and falls back
            # to the catalog reroute target for an invalid/missing one), then pick
            # the first gap whose resolved skill is not yet executed. Forcing engine
            # gaps sort first, so a required uncovered axis is always preferred. If
            # every gap resolves to an already-run skill — a weak/absent axis that
            # re-running cannot improve — stop and synthesize with the residual gaps
            # rather than thrash on the same skill (the loop's old failure).
            executed = {e.get("skill") for e in results if e.get("skill")}
            followup = None
            for g in review.get("gaps") or []:
                cand = cso._reroute_task(g, routing, step_n=6 + i, executed=executed)
                if cand.skill not in executed:
                    gap, followup = g, cand
                    break
            if followup is None:
                trace.step("✅", "no actionable gap left (every gap re-runs a covered "
                           "skill) → synthesize with residual gaps")
                break
            trace.step("🔁", f"reroute {i + 1}/{MAX_REROUTES} → {followup.skill} "
                       f"({gap.get('missing', 'gap')})")
            trace.event("phase", {"id": followup.step, "role": followup.skill,
                                  "kind": "skill", "division": followup.division + " (re-route)",
                                  "title": followup.question, "status": "running",
                                  "reroute": True, "why": gap.get("missing", "")})
            with rec.span(f"reroute:{followup.skill}", kind="tool", iteration=i + 1,
                          missing=gap.get("missing")):
                # pass the query as the live target so a reroute to lit-synthesizer
                # runs a real-time Tavily search for this target, not the cached demo.
                env = cso.execute_skill(followup, case, demo, live, target=query)
                results.append(env)
            trace.event("evidence", {**_evidence_event(env), "reroute": True})

            # A cached/stub reviewer can't re-evaluate the new evidence — its verdict is
            # fixed, so looping would just append duplicate re-routes. Only a *live*
            # reviewer genuinely re-reviews; honor exactly one re-route otherwise.
            if review_src != AGENT_SOURCE:
                trace.step("✅", "reviewer (cached/stub) → one re-route, then synthesize")
                break
        loop_sp.set(verdict=review.get("verdict", "synthesize"))
    return review


def run(query: str, out_dir: Path | None, *, backend: str, model: str | None,
        demo: bool, live: bool, argv: list[str], emit: "Emit | None" = None,
        quiet: bool = False) -> dict[str, Any]:
    """Run the live multi-agent loop.

    ``emit`` is an optional structured-event sink: when set (the frontend supplies
    one), each phase pushes an event the UI streams as SSE — so the browser shows
    the SAME loop the CLI prints, not a re-implementation. ``quiet`` suppresses the
    console trace (the server doesn't want it). ``out_dir=None`` skips writing the
    report/result files (the streaming caller renders from the events + final dict).
    """
    case = cso.case_key(query)
    routing = cso.load_routing()
    runner = runners.select_runner(backend, model)
    trace = Trace(runner.name, runner.model, emit=emit, quiet=quiet)
    rec = TraceRecorder(out_dir, run_name=case, backend=runner.name, model=runner.model)

    calls_llm = runner.name != "stub"
    trace.event("start", {
        "query": query, "case": case,
        "backend": runner.name if calls_llm else "none",
        "model": runner.model if calls_llm else "none",
        "calls_llm": calls_llm,
        "mode": "demo" if demo else ("live" if live else "default"),
    })

    # 1 — BRIEF (live agent role) ------------------------------------------- #
    trace.event("phase", {"id": "briefing", "role": "Chief of Staff", "kind": "agent",
                          "division": "Office of CSO", "title": "Field briefing",
                          "status": "running"})
    briefing, brief_src = _agent_or_stub(
        trace, "chief_of_staff", runner, cso.CHIEF_OF_STAFF_PROMPT,
        f"User query: {query}", BRIEFING_SCHEMA,
        stub=cso.load_briefing(query, case, demo=demo), rec=rec)
    briefing.setdefault("source", brief_src)
    trace.event("briefing", {"briefing": briefing, "source": brief_src})

    # 2 — PLAN (live agent role; validated against routing.yaml, else deterministic) #
    subtasks, plan_src = _plan(trace, runner, query, briefing, case, routing, rec)
    trace.step("🧭", f"plan → {len(subtasks)} routed sub-tasks ({plan_src})")
    trace.event("plan", {"subtasks": [t.as_plan_entry() for t in subtasks],
                         "source": plan_src})

    # 3 — DIVISION SCIENTISTS (one agent per division; runs its skills + interprets) #
    #     Virtual-Biotech structure: the CSO delegates each division to a domain
    #     scientist agent, run concurrently. division_findings carry their reasoning.
    with rec.span("execute", kind="tool", n_subtasks=len(subtasks)):
        results, division_findings = _run_divisions(
            subtasks, runner, query, case, demo, live, trace, rec, target=query)

    # 4 — REVIEW → RE-ROUTE loop (change #2: bounded; verdict drives control flow) #
    #     The reviewer re-runs after each re-route until it returns `synthesize` or
    #     MAX_REROUTES is hit. Each re-route target is the reviewer's *chosen* skill,
    #     validated against the catalog (change #3) before execution.
    review = _review_loop(trace, runner, query, case, routing, results, demo, live, rec)

    # 4b — DECISION (Prometheux): derive the GO/NO-GO tier deductively from the final
    #      evidence. Authoritative for the report's Decision field; the agent narrates.
    decision = _engine_decision(trace, results, rec, query)

    # 5 — SYNTHESIZE (CSO integrates the division scientists' findings + review) -- #
    decision_ctx = (f"\n\nDeductive decision (Prometheux, authoritative tier):\n"
                    f"{json.dumps(decision, default=str)}\n"
                    "Write your recommendation consistent with this tier; it is the "
                    "Decision of record. If you disagree, argue it in the rationale."
                    if decision else "")
    syn_context = (
        f"User query: {query}\n\nBriefing:\n{json.dumps(briefing, default=str)}\n\n"
        f"Division scientist findings:\n{json.dumps(division_findings, default=str)}\n\n"
        f"Evidence:\n{_evidence_context(results)}\n\n"
        f"Reviewer:\n{json.dumps(review, default=str)}{decision_ctx}"
    )
    trace.event("phase", {"id": "synth", "role": "CSO Orchestrator", "kind": "agent",
                          "division": "Synthesis", "title": "Synthesize recommendation",
                          "status": "running", "terminal": True})
    synthesis: dict[str, Any] | None
    synthesis, _ = _agent_or_stub(
        trace, "cso_synthesis", runner, cso.ORCHESTRATOR_PROMPT,
        syn_context, SYNTHESIS_SCHEMA, stub={}, rec=rec)
    if not synthesis:  # stub path returns {} → let the report show "pending"
        synthesis = None
    trace.event("synthesis", {"synthesis": synthesis})

    # The derived tier is the Decision of record; the agent's free-text is rationale.
    agent_decision = (synthesis or {}).get("decision")
    decision_tier = (decision or {}).get("tier") or agent_decision or "REVIEW"
    trace.event("decision", {
        "decision": decision_tier,
        "decision_source": "prometheux" if decision else "agent",
        "agent_decision": agent_decision,
        "engine": decision,
        "diverges": bool(decision and agent_decision
                         and agent_decision != decision["tier"]),
        "confidence": (synthesis or {}).get("confidence", "n/a"),
    })

    # 6 — ASSEMBLE (reuse cso's renderer + output contract) ----------------- #
    report_md = cso.synthesize_report(query, case, briefing, results, review, synthesis,
                                      demo, decision_engine=decision)
    report_path = result_path = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / "report.md"
        report_path.write_text(report_md, encoding="utf-8")

        summary, data = _build_envelope(query, case, briefing, subtasks, results, review,
                                        synthesis, runner, backend, demo, live,
                                        division_findings=division_findings,
                                        decision_engine=decision)
        result_path = cso._write_result_json(out_dir, summary, data)
        cso._write_reproducibility(out_dir / "reproducibility", argv,
                                   [report_path, result_path])
    else:
        summary, data = _build_envelope(query, case, briefing, subtasks, results, review,
                                        synthesis, runner, backend, demo, live,
                                        division_findings=division_findings,
                                        decision_engine=decision)

    # Finalise the execution trace (span tree + timing + token totals).
    trace_path = rec.close(query=query, decision=summary.get("decision"),
                           reviewer_verdict=summary.get("reviewer_verdict"),
                           calls_llm=summary.get("calls_llm"))
    if trace_path is not None:
        tok = rec.totals.get("total_tokens", 0)
        trace.step("🧾", f"trace: {tok} tokens across spans → {trace_path.name}")
    summary["trace_tokens"] = rec.totals.get("total_tokens", 0)

    trace.event("done", {
        "report_md": report_md,
        "decision": summary.get("decision"),
        "decision_source": summary.get("decision_source"),
        "confidence": summary.get("confidence"),
        "n_steps": summary.get("n_steps"),
        "reviewer_verdict": summary.get("reviewer_verdict"),
    })
    if report_path is not None:
        trace.done(str(report_path))
    return {"report": str(report_path) if report_path else None,
            "result": str(result_path) if result_path else None,
            "trace": str(trace_path) if trace_path else None,
            "summary": summary, "data": data, "report_md": report_md,
            "decision_engine": decision}


def _execute_steps(subtasks: list[cso.Subtask], case: str, demo: bool, live: bool,
                   target: str | None) -> dict[str, dict[str, Any]]:
    """Run a division's routed steps respecting depends_on; independent ones parallel.

    Returns {step_id: evidence_envelope}. This is the *tool layer* a division
    scientist agent drives — the deterministic data acquisition, no interpretation."""
    done: dict[str, dict[str, Any]] = {}
    remaining = list(subtasks)
    while remaining:
        ready = [t for t in remaining if all(d in done for d in t.depends_on)]
        if not ready:  # safety: break dependency deadlock by running the rest
            ready = remaining
        with ThreadPoolExecutor(max_workers=max(1, len(ready))) as pool:
            for task, env in zip(ready, pool.map(
                    lambda t: cso.execute_skill(t, case, demo, live, target=target), ready)):
                done[task.step] = env
        remaining = [t for t in remaining if t.step not in done]
    return done


def _run_divisions(subtasks: list[cso.Subtask], runner: runners.Runner, query: str,
                   case: str, demo: bool, live: bool, trace: Trace, rec: TraceRecorder,
                   target: str | None = None
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Virtual-Biotech structure: one **division scientist agent** per division.

    The CSO delegates each division to a domain-specialised scientist agent that
    (1) runs its routed skills (its tools, via _execute_steps) and (2) interprets the
    raw output into a division finding. Divisions run **concurrently** — N parallel
    scientist agents, mirroring the paper's cross-functional R&D org. Without a live
    backend the interpretation degrades to an honest stub (raw evidence still flows).

    Returns (evidence_steps, division_findings) — evidence preserves the existing
    per-step contract the reviewer/report consume; findings are the agents' reasoning.
    """
    groups = cso.group_by_division(subtasks)
    prompt = _read_prompt(cso.DIVISION_SCIENTIST_PROMPT)

    # Announce every routed skill as a running phase up front (in plan order), so
    # the UI shows the full division roster before the concurrent agents report back.
    for t in subtasks:
        trace.event("phase", {"id": t.step, "role": t.skill, "kind": "skill",
                              "division": t.division, "title": t.question,
                              "status": "running"})

    def _scientist(division: str, tasks: list[cso.Subtask]
                   ) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
        with rec.span(f"scientist:{division}", kind="agent", backend=runner.name,
                      model=runner.model, n_skills=len(tasks)) as sp:
            t0 = time.perf_counter()
            done = _execute_steps(tasks, case, demo, live, target)  # the agent's tools
            sp.set(exec_ms=round((time.perf_counter() - t0) * 1000.0, 2))
            evidence_ctx = _evidence_context([done[t.step] for t in tasks])
            ctx = (f"Your division: {division}\nUser query: {query}\n\n"
                   f"Raw skill output for your division:\n{evidence_ctx}")
            try:
                finding = runners.run_with_retry(
                    runner, prompt, ctx, DIVISION_FINDING_SCHEMA)
                finding["division"] = division
                finding["source"] = AGENT_SOURCE
                sp.record_usage(**_usage_of(runner)).set(
                    grade=finding.get("evidence_grade"))
            except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
                sp.status = "stub"
                sp.set(degraded="no-backend" if isinstance(exc, runners.NoBackendError)
                       else "agent-failed", reason=str(exc))
                finding = {"division": division, "interpretation": None,
                           "confidence": "n/a", "caveats": [], "evidence_grade": None,
                           "source": cso.DELEGATE}
            return division, done, finding

    with rec.span("divisions", kind="loop", n_divisions=len(groups)):
        with ThreadPoolExecutor(max_workers=max(1, len(groups))) as pool:
            results = list(pool.map(lambda g: _scientist(*g), groups))

    merged: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, Any]] = []
    for division, done, finding in results:
        merged.update(done)
        findings.append(finding)
        live_tag = "🧪 stub" if finding.get("source") == cso.DELEGATE else \
            f"{finding.get('evidence_grade', '?')}"
        trace.step("🔬", f"division scientist [{division}]: {len(done)} skill(s) "
                   f"→ {live_tag}")
        trace.event("division_finding", {"division": division, "finding": finding,
                                         "n_skills": len(done)})
    # Stream each completed step's evidence in stable plan order (the work ran
    # concurrently; ordered emission keeps the SSE stream + graph build deterministic).
    evidence = [merged[t.step] for t in subtasks]
    for env in evidence:
        trace.event("evidence", _evidence_event(env))
    return evidence, findings


def _evidence_event(env: dict[str, Any]) -> dict[str, Any]:
    """Normalize one routed-step result into a graph/report-ready event payload.

    Shared by the streaming UI (graph ingestion) and any caller that wants the
    graded, provenance-tagged view of a step without reaching into cso internals."""
    prov_icon, prov_note = cso._provenance(env)
    return {
        "step": env["step"], "division": env["division"], "skill": env["skill"],
        "question": env.get("question", ""), "result": env.get("result", {}),
        "grade": cso._evidence_grade(env), "provenance": prov_icon,
        "provenance_note": prov_note, "reference": cso._evidence_reference(env),
        "digest": cso._result_digest(env), "source": env.get("source", ""),
    }


def _build_envelope(query, case, briefing, subtasks, results, review, synthesis,
                    runner, backend, demo, live, division_findings=None,
                    decision_engine=None
                    ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mirror cso.run()'s result.json envelope, marking the live-agent loop."""
    syn = synthesis or {}
    references = [
        {"n": i, "skill": e["skill"], "provenance": cso._provenance(e)[0],
         "grade": cso._evidence_grade(e), "source": cso._evidence_reference(e), "step": e["step"]}
        for i, e in enumerate(results, 1)
    ]
    evidence_gaps = (
        [f"{e['division']}/{e['skill']} ({e['step']}): {cso._provenance(e)[1]}"
         for e in results if cso._evidence_grade(e) == "absent"]
        + [g.get("missing") for g in review.get("gaps", [])]
        + list(syn.get("evidence_gaps", []))
    )
    proposed = list(syn.get("proposed_experiments", [])) + list(review.get("experiments", []))
    calls_llm = runner.name != "stub"
    summary = {
        "query": query, "case": case,
        "mode": "demo" if demo else ("live" if live else "default"),
        "loop": "live-agent-harness",
        "backend": runner.name if calls_llm else "none",
        "model": runner.model if calls_llm else "none",
        "n_steps": len(results),
        "reviewer_verdict": review.get("verdict", "synthesize"),
        "n_executed": len([e for e in results if e.get("source") in ("clawbio", cso.DEMO_SOURCE)]),
        # Derived tier is the decision of record when the engine ran; the agent's
        # free-text is kept alongside so a divergence is auditable, not erased.
        "decision": (decision_engine or {}).get("tier") or syn.get("decision", "REVIEW"),
        "decision_source": "prometheux" if decision_engine else "agent",
        "agent_decision": syn.get("decision"),
        "decision_engine": decision_engine,
        "confidence": syn.get("confidence", "n/a"),
        "calls_llm": calls_llm,
    }
    data = {
        "briefing": briefing,
        "plan": [t.as_plan_entry() for t in subtasks],
        "division_findings": division_findings or [],
        "evidence": results,
        "review": review,
        "synthesis": synthesis,
        "references": references,
        "evidence_gaps": evidence_gaps,
        "proposed_experiments": proposed,
        "disclaimer": cso.DISCLAIMER,
    }
    return summary, data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="harness.py",
        description="Run virtual-biotech-cso as a live multi-agent loop "
        "(Chief of Staff · division scientists · Scientific Reviewer · CSO synthesis).")
    p.add_argument("--query", type=str, default=cso.DEFAULT_QUERY,
                   help=f"Target-assessment query (default: {cso.DEFAULT_QUERY!r})")
    p.add_argument("--backend", choices=["auto", "anthropic", "openai", "gemini", "claude-cli"],
                   default="auto",
                   help="Agent backend (default: auto — Anthropic/OpenAI key, else claude CLI)")
    p.add_argument("--model", type=str, default=None, help="Override the model id")
    p.add_argument("--demo", action="store_true",
                   help="Use cached fixtures for routed DATA steps; roles still run live")
    p.add_argument("--live", action="store_true",
                   help="Execute routed skills via the ClawBio runtime")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out).expanduser().resolve()
    summary = run(args.query, out_dir, backend=args.backend, model=args.model,
                  demo=args.demo, live=args.live, argv=argv)
    print("\n" + json.dumps(summary["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
