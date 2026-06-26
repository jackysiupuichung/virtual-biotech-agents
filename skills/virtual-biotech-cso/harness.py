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
from typing import Any

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
    """Prints a per-step trace so the multi-agent loop is visible in the demo."""

    def __init__(self, backend: str, model: str) -> None:
        print("┌─ virtual-biotech CSO · live multi-agent loop")
        print(f"│  backend: {backend}  model: {model}\n│")

    def step(self, icon: str, msg: str) -> None:
        print(f"│  {icon} {msg}")

    def done(self, report: str) -> None:
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
                  routing: dict[str, Any], rec: TraceRecorder) -> dict[str, Any]:
    """Fan out N lens-specialised reviewers concurrently, then aggregate (panel).

    Each lens is an independent agent call with the shared reviewer prompt plus its
    own focus; they run in a thread pool (true concurrent multi-agent). A lens that
    fails abstains honestly (synthesize, no gaps) rather than crashing the panel.
    The deterministic cso.aggregate_panel_review folds them into one verdict the
    loop consumes unchanged. Only invoked on a live backend (stub keeps 1 reviewer).
    """
    prompt = _read_prompt(cso.REVIEWER_PROMPT)
    evidence = _evidence_context(results)

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
        review = cso.aggregate_panel_review(lens_reviews, routing)
        panel = review["panel"]
        panel_sp.set(verdict=review["verdict"], reroute_votes=panel["reroute_votes"])
    review["source"] = AGENT_SOURCE
    trace.step("👥", f"reviewer panel: {panel['reroute_votes']}/{panel['n_lenses']} lenses "
               f"flag re-route → verdict {review['verdict']}")
    return review


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
                review = _review_panel(trace, runner, results, routing, rec)
                review_src = AGENT_SOURCE
            else:
                review, review_src = _agent_or_stub(
                    trace, "scientific_reviewer", runner, cso.REVIEWER_PROMPT,
                    _evidence_context(results), REVIEW_SCHEMA,
                    stub=cso.load_review(query, case, results, demo=False), rec=rec)
            review.setdefault("source", review_src)

            if review.get("verdict") != "re-route":
                trace.step("✅", f"reviewer verdict: {review.get('verdict', 'synthesize')}")
                break
            if i == MAX_REROUTES:
                trace.step("🛑", f"reviewer still re-routing after {MAX_REROUTES} passes; "
                           "synthesizing with residual gaps")
                break

            gap = (review.get("gaps") or [{}])[0]
            followup = cso._reroute_task(gap, routing, step_n=6 + i)
            trace.step("🔁", f"reroute {i + 1}/{MAX_REROUTES} → {followup.skill} "
                       f"({gap.get('missing', 'gap')})")
            with rec.span(f"reroute:{followup.skill}", kind="tool", iteration=i + 1,
                          missing=gap.get("missing")):
                # pass the query as the live target so a reroute to lit-synthesizer
                # runs a real-time Tavily search for this target, not the cached demo.
                results.append(cso.execute_skill(followup, case, demo, live, target=query))

            # A cached/stub reviewer can't re-evaluate the new evidence — its verdict is
            # fixed, so looping would just append duplicate re-routes. Only a *live*
            # reviewer genuinely re-reviews; honor exactly one re-route otherwise.
            if review_src != AGENT_SOURCE:
                trace.step("✅", "reviewer (cached/stub) → one re-route, then synthesize")
                break
        loop_sp.set(verdict=review.get("verdict", "synthesize"))
    return review


def run(query: str, out_dir: Path, *, backend: str, model: str | None,
        demo: bool, live: bool, argv: list[str]) -> dict[str, Any]:
    case = cso.case_key(query)
    routing = cso.load_routing()
    runner = runners.select_runner(backend, model)
    trace = Trace(runner.name, runner.model)
    rec = TraceRecorder(out_dir, run_name=case, backend=runner.name, model=runner.model)

    # 1 — BRIEF (live agent role) ------------------------------------------- #
    briefing, brief_src = _agent_or_stub(
        trace, "chief_of_staff", runner, cso.CHIEF_OF_STAFF_PROMPT,
        f"User query: {query}", BRIEFING_SCHEMA,
        stub=cso.load_briefing(query, case, demo=False), rec=rec)
    briefing.setdefault("source", brief_src)

    # 2 — PLAN (live agent role; validated against routing.yaml, else deterministic) #
    subtasks, plan_src = _plan(trace, runner, query, briefing, case, routing, rec)
    trace.step("🧭", f"plan → {len(subtasks)} routed sub-tasks ({plan_src})")

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

    # 5 — SYNTHESIZE (CSO integrates the division scientists' findings + review) -- #
    syn_context = (
        f"User query: {query}\n\nBriefing:\n{json.dumps(briefing, default=str)}\n\n"
        f"Division scientist findings:\n{json.dumps(division_findings, default=str)}\n\n"
        f"Evidence:\n{_evidence_context(results)}\n\n"
        f"Reviewer:\n{json.dumps(review, default=str)}"
    )
    synthesis: dict[str, Any] | None
    synthesis, _ = _agent_or_stub(
        trace, "cso_synthesis", runner, cso.ORCHESTRATOR_PROMPT,
        syn_context, SYNTHESIS_SCHEMA, stub={}, rec=rec)
    if not synthesis:  # stub path returns {} → let the report show "pending"
        synthesis = None

    # 6 — ASSEMBLE (reuse cso's renderer + output contract) ----------------- #
    report_md = cso.synthesize_report(query, case, briefing, results, review, synthesis, demo)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    summary, data = _build_envelope(query, case, briefing, subtasks, results, review,
                                    synthesis, runner, backend, demo, live,
                                    division_findings=division_findings)
    result_path = cso._write_result_json(out_dir, summary, data)
    cso._write_reproducibility(out_dir / "reproducibility", argv, [report_path, result_path])

    # Finalise the execution trace (span tree + timing + token totals).
    trace_path = rec.close(query=query, decision=summary.get("decision"),
                           reviewer_verdict=summary.get("reviewer_verdict"),
                           calls_llm=summary.get("calls_llm"))
    if trace_path is not None:
        tok = rec.totals.get("total_tokens", 0)
        trace.step("🧾", f"trace: {tok} tokens across spans → {trace_path.name}")
    summary["trace_tokens"] = rec.totals.get("total_tokens", 0)

    trace.done(str(report_path))
    return {"report": str(report_path), "result": str(result_path),
            "trace": str(trace_path) if trace_path else None, "summary": summary}


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
    evidence = [merged[t.step] for t in subtasks]
    return evidence, findings


def _build_envelope(query, case, briefing, subtasks, results, review, synthesis,
                    runner, backend, demo, live, division_findings=None
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
        "decision": syn.get("decision", "REVIEW"),
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
    p.add_argument("--backend", choices=["auto", "anthropic", "openai", "claude-cli"],
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
