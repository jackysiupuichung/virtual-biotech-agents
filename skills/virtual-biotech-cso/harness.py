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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cso  # sibling module — reused, never modified
import runners

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


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
                   context: str, schema: dict[str, Any],
                   stub: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Run a reasoning role live; on any failure fall back to cso's honest stub.

    Returns (payload, source) where source is AGENT_SOURCE or cso's DELEGATE.
    """
    try:
        payload = runners.run_with_retry(runner, _read_prompt(prompt), context, schema)
        trace.step("🤖", f"{role}: live agent ({runner.name})")
        return payload, AGENT_SOURCE
    except runners.NoBackendError as exc:
        trace.step("⚪", f"{role}: {exc}")
        return stub, cso.DELEGATE
    except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
        trace.step("⚠️", f"{role}: agent failed ({exc}); using honest stub")
        return stub, cso.DELEGATE


def run(query: str, out_dir: Path, *, backend: str, model: str | None,
        demo: bool, live: bool, argv: list[str]) -> dict[str, Any]:
    case = cso.case_key(query)
    routing = cso.load_routing()
    runner = runners.select_runner(backend, model)
    trace = Trace(runner.name, runner.model)

    # 1 — BRIEF (live agent role) ------------------------------------------- #
    briefing, brief_src = _agent_or_stub(
        trace, "chief_of_staff", runner, cso.CHIEF_OF_STAFF_PROMPT,
        f"User query: {query}", BRIEFING_SCHEMA,
        stub=cso.load_briefing(query, case, demo=False))
    briefing.setdefault("source", brief_src)

    # 2 — DECOMPOSE & ROUTE (deterministic, reused) ------------------------- #
    subtasks = cso.decompose_and_route(query, case, routing)
    trace.step("🧭", f"decomposed → {len(subtasks)} routed sub-tasks")

    # 3 — EXECUTE DIVISIONS (deterministic data layer; concurrent where free) #
    results = _execute_concurrent(subtasks, case, demo, live, trace)

    # 4 — REVIEW (live agent role; verdict drives control flow) ------------- #
    review, review_src = _agent_or_stub(
        trace, "scientific_reviewer", runner, cso.REVIEWER_PROMPT,
        _evidence_context(results), REVIEW_SCHEMA,
        stub=cso.load_review(query, case, results, demo=False))
    review.setdefault("source", review_src)

    if review.get("verdict") == "re-route":
        gap = (review.get("gaps") or [{}])[0]
        followup = cso._reroute_task(gap)
        trace.step("🔁", f"reviewer re-routed → {followup.skill} ({gap.get('missing', 'gap')})")
        results.append(cso.execute_skill(followup, case, demo, live))
    else:
        trace.step("✅", f"reviewer verdict: {review.get('verdict', 'synthesize')}")

    # 5 — SYNTHESIZE (live agent role) -------------------------------------- #
    syn_context = (
        f"User query: {query}\n\nBriefing:\n{json.dumps(briefing, default=str)}\n\n"
        f"Evidence:\n{_evidence_context(results)}\n\n"
        f"Reviewer:\n{json.dumps(review, default=str)}"
    )
    synthesis: dict[str, Any] | None
    synthesis, _ = _agent_or_stub(
        trace, "cso_synthesis", runner, cso.ORCHESTRATOR_PROMPT,
        syn_context, SYNTHESIS_SCHEMA, stub={})
    if not synthesis:  # stub path returns {} → let the report show "pending"
        synthesis = None

    # 6 — ASSEMBLE (reuse cso's renderer + output contract) ----------------- #
    report_md = cso.synthesize_report(query, case, briefing, results, review, synthesis, demo)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    summary, data = _build_envelope(query, case, briefing, subtasks, results, review,
                                    synthesis, runner, backend, demo, live)
    result_path = cso._write_result_json(out_dir, summary, data)
    cso._write_reproducibility(out_dir / "reproducibility", argv, [report_path, result_path])

    trace.done(str(report_path))
    return {"report": str(report_path), "result": str(result_path), "summary": summary}


def _execute_concurrent(subtasks: list[cso.Subtask], case: str, demo: bool, live: bool,
                        trace: Trace) -> list[dict[str, Any]]:
    """Run routed steps respecting depends_on; independent ones run in parallel."""
    done: dict[str, dict[str, Any]] = {}
    remaining = list(subtasks)
    while remaining:
        ready = [t for t in remaining if all(d in done for d in t.depends_on)]
        if not ready:  # safety: break dependency deadlock by running the rest
            ready = remaining
        with ThreadPoolExecutor(max_workers=max(1, len(ready))) as pool:
            for task, env in zip(ready, pool.map(
                    lambda t: cso.execute_skill(t, case, demo, live), ready)):
                done[task.step] = env
        trace.step("🔬", f"executed {len(ready)} division step(s): "
                   + ", ".join(t.division for t in ready))
        remaining = [t for t in remaining if t.step not in done]
    return [done[t.step] for t in subtasks]


def _build_envelope(query, case, briefing, subtasks, results, review, synthesis,
                    runner, backend, demo, live) -> tuple[dict[str, Any], dict[str, Any]]:
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
