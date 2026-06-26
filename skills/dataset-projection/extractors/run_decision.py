#!/usr/bin/env python3
"""run_decision.py — project a finished CSO harness run into decision facts.

A completed run produces two conclusions worth reasoning across later (NOT the
prose report, NOT the loop trace — those stay on disk; Vadalog reasons over
facts only):

* the **final overall verdict** — the authoritative GO/CONDITIONAL_GO/REVIEW/NO_GO
  tier + score from ``prometheux_reason.decide_from_evidence`` (the *what*);
* the **per-axis subreport conclusions** — the strongest graded evidence on each
  decision axis that the tier was computed from (the *why*).

Storing both is not redundant: the axis facts justify the tier, and having both
in the engine lets a later program re-derive or audit any past verdict, and join
it against PrimeKG (e.g. "which targets did we NO_GO, and on which axis").

Two ways in:

  # from a graded-results JSON (list of evidence dicts) + target — recomputes the
  # decision the same way the harness does, so the facts always match the run:
  python extractors/run_decision.py --results run_results.json --target CD276

  # or from an already-computed decision dict (decide_from_evidence output):
  python extractors/run_decision.py --decision decision.json --target CD276

Writes ``out/<target>.decision.facts.csv`` in the canonical Fact schema, ready to
``@bind`` next to ``kg_csv`` (PrimeKG). See facts.py + bind.vada.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from facts import Fact, node_id, write_facts  # noqa: E402

# the run's own decision logic — single source of truth for tier/axes, so the
# projected facts can never drift from what the report showed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                       / "virtual-biotech-cso"))


def _decision_facts(decision: dict[str, Any], target: str,
                    run_id: str) -> Iterable[Fact]:
    """Final-overall verdict → one decision fact, plus one fact per axis subreport."""
    tgt = node_id("target", target)
    tier = decision["tier"]
    score = float(decision["score"])
    max_score = float(decision.get("max_score", 4.0))
    prov = f"cso-run:{run_id}"

    # The final overall verdict. confidence = normalized coverage score; the tier
    # itself is the conclusion (carried in `value`). object is the tier node so a
    # later program can group/join targets by verdict.
    yield Fact(
        subject=tgt,
        relation="DECIDED",
        object=node_id("verdict", tier),
        value=f"{tier} (score {score}/{max_score}): {decision.get('explanation', '')}".strip(),
        confidence=round(min(max(score / max_score, 0.0), 1.0), 4),
        source_dataset="cso_run_decision",
        provenance=prov,
    )

    # Per-axis subreport conclusions: the strongest graded evidence on each axis,
    # i.e. the rows the tier was computed from. value carries the grade; confidence
    # is the axis weight (already in [0,1] per GRADE_WEIGHT).
    for axis, a in (decision.get("axes") or {}).items():
        grade = a.get("grade", "absent")
        weight = float(a.get("weight", 0.0))
        yield Fact(
            subject=tgt,
            relation="HAS_AXIS_EVIDENCE",
            object=node_id("axis", axis),
            value=f"{axis}={grade}",
            confidence=round(min(max(weight, 0.0), 1.0), 4),
            source_dataset="cso_run_decision",
            provenance=f"{prov}#axis={axis}",
        )


def _load_decision(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """Return (decision_dict, target). Recompute from graded results, or load direct."""
    target = args.target
    if args.decision:
        decision = json.loads(Path(args.decision).read_text())
        return decision, target

    import prometheux_reason as pr
    results = json.loads(Path(args.results).read_text())
    if not isinstance(results, list):
        raise SystemExit("--results must be a JSON list of evidence dicts")
    # grade any rows that arrive ungraded, mirroring _engine_decision in harness.py.
    try:
        import cso
        graded = [{**e, "grade": e.get("grade") or cso._evidence_grade(e),
                   "step": e.get("step")} for e in results]
    except Exception:  # noqa: BLE001 — cso optional; rows may already carry grade
        graded = [{**e, "grade": e.get("grade", "absent")} for e in results]
    return pr.decide_from_evidence(graded, target), target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--results", help="JSON list of (graded) evidence dicts from a run")
    src.add_argument("--decision", help="JSON of a decide_from_evidence output dict")
    ap.add_argument("--target", required=True, help="target symbol, e.g. CD276")
    ap.add_argument("--run-id", default="adhoc", help="run identifier for provenance")
    ap.add_argument("--out", type=Path, default=None,
                    help="output CSV (default out/<target>.decision.facts.csv)")
    args = ap.parse_args(argv)

    decision, target = _load_decision(args)
    out = args.out or (Path(__file__).resolve().parent.parent / "out"
                       / f"{target.lower()}.decision.facts.csv")
    n = write_facts(_decision_facts(decision, target, args.run_id), out)
    print(f"wrote {n} facts → {out}  (tier={decision['tier']}, "
          f"score={decision['score']}/{decision.get('max_score', 4.0)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
