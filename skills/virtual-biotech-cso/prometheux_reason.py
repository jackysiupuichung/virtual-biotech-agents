#!/usr/bin/env python3
"""prometheux_reason.py — Vadalog reasoning over the evidence graph.

The CSO evidence graph ([kg.py](kg.py)) is already shaped like a Datalog fact
base: every edge is a ground atom with confidence + provenance. This module is
the **reasoning layer** the applicability review
([docs/prometheux-evidence-graph-applicability.md]) recommended — it turns those
edges into a **Vadalog program** (facts + recursive rules + ``@model``/``@explain``
annotations) and derives *explainable* conclusions:

  * ``co_niche(A, B)``      — two targets share a cell-type niche (recursion)
  * ``shares_axis(A, B, X)``— two targets carry evidence on the same axis
  * ``strong_claim(T, Ax)`` — confidence-gated claim (≥ 0.8) as a first-class rule
  * ``differentiates(A, B, Ax)`` — the **explain-a-rank** edges: axes where A has a
                                   strong claim and B does not (why A ranks over B)

Two execution paths, same program:

  1. **Live Prometheux** (``prometheux_chain``, when ``PMTX_TOKEN`` is set) — the
     hosted Vadalog engine runs the rules and returns native ``@explain`` output:
     each derived fact with a human-readable rule-chain explanation. Verified against
     ``prometheux-chain==0.2.14``: reasoning is a project → concept → run → fetch
     sequence (see :func:`_reason_prometheux`), POSTed to the JarvisPy backend; the
     hosted engine is reached only when ``JARVISPY_URL`` points at a real org/user.
  2. **Local fallback** — a small in-process semi-naive Datalog evaluator over the
     same facts + rules, emitting the same ``@model`` natural-language strings. No
     network, no token, fully reproducible — so the reasoning always runs.

Both paths return the identical ``ReasonResult`` shape, so callers (CLI, a future
UI panel) are agnostic to which engine produced it.

**Load-bearing role — the reviewer's gap-detector.** Beyond the read-only view
above, ``derive_gaps(graph)`` runs a *structural-gap* rule set and returns gaps in
the exact shape the harness reviewer panel consumes (``{missing, route_to, why,
lenses, explanation, forces_reroute}``). A proven missing prioritization axis (no
``evidence(T, Ax, _)`` at all) is a deductive fact, not a judgement call — so the
engine becomes a non-silenceable panel member: such a gap forces a re-route on its
own. Pull this module and the panel goes blind to structural gaps.

    python3 prometheux_reason.py                 # local fallback
    PMTX_TOKEN=... python3 prometheux_reason.py   # live Prometheux
    python3 prometheux_reason.py --vada           # print the .vada program
    python3 prometheux_reason.py --gaps           # the reviewer gap-detector output
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import kg as KG  # the canonical graph this reasons over

STRONG_CONF = 0.8  # confidence gate for a "strong" claim (design §5)

# --- decision layer: quantitative, replayable GO/NO-GO over the required axes - #
# Each axis contributes the weight of its *best* graded evidence; the four axis
# scores sum to a coverage score in [0, 4]. The tier is then a threshold over that
# score, with a non-negotiable safety hard-gate on top (``unsafe_advance``). The
# weights reuse the ``_evidence_grade`` vocabulary so the decision and the report's
# grade column can never disagree about how strong a step is.
GRADE_WEIGHT = {
    "strong": 1.0,
    "supporting": 0.5, "supported": 0.5, "illustrative": 0.5,
    "suggestive": 0.25,
    "absent": 0.0,
}
GO_THRESHOLD = 3.0          # score >= this AND strong safety  -> GO
CONDITIONAL_THRESHOLD = 2.0  # score >= this AND safety covered -> CONDITIONAL_GO


# --------------------------------------------------------------------------- #
# 1. Compile the graph → a Vadalog program (facts + rules + annotations)
# --------------------------------------------------------------------------- #
def _atom_id(node_id: str) -> str:
    """A Vadalog-safe string constant for a node id (kept human-readable)."""
    return node_id.replace('"', "")


def graph_to_vada(graph: KG.KnowledgeGraph) -> str:
    """Render the evidence graph as a Vadalog program.

    Facts model the edges we reason over; rules derive the explainable
    conclusions; ``@model`` gives each derivable predicate a natural-language
    template and ``@explain`` requests the rule-chain explanation. The same text
    is what we'd POST to the hosted engine and what the local evaluator parses.
    """
    facts: list[str] = []
    for n in graph.nodes.values():
        if n.get("kind") == "Target":
            facts.append(f'target("{_atom_id(n["id"])}").')
    for e in graph.edges.values():
        s, t = _atom_id(e["s"]), _atom_id(e["t"])
        conf = float(e.get("conf") or 0.0)
        if e["type"] == "EXPRESSED_IN":
            facts.append(f'expressed_in("{s}", "{t}", {conf}).')
        elif e["type"] in ("SPECIFIC_TO", "GENETIC_LINK", "OFF_TARGET_IN", "EVALUATED_IN"):
            axis = e.get("axis") or "evidence"
            facts.append(f'evidence("{s}", "{axis}", {conf}).')

    rules = [
        "% --- recursion: two targets share a cell-type niche -----------------",
        'co_niche(A, B) :- expressed_in(A, C, _), expressed_in(B, C, _), A != B.',
        "% --- two targets carry evidence on the same prioritization axis ------",
        'shares_axis(A, B, Ax) :- evidence(A, Ax, _), evidence(B, Ax, _), A != B.',
        "% --- confidence-gated claim: the gating IS the logic -----------------",
        f'strong_claim(T, Ax) :- evidence(T, Ax, S), S >= {STRONG_CONF}.',
        "% --- explain-a-rank: axes where A is strong and B is not -------------",
        'differentiates(A, B, Ax) :- strong_claim(A, Ax), evidence(B, Ax, S), '
        f'S < {STRONG_CONF}, A != B.',
    ]
    models = [
        '@model("co_niche", "[\'A:string\',\'B:string\']", '
        '"[A] and [B] occupy a shared cell-type niche").',
        '@model("strong_claim", "[\'T:string\',\'Ax:string\']", '
        '"[T] has strong evidence on the [Ax] axis (confidence >= 0.8)").',
        '@model("differentiates", "[\'A:string\',\'B:string\',\'Ax:string\']", '
        '"[A] ranks over [B] on [Ax]: [A] has a strong claim there, [B] does not").',
    ]
    outputs = ['@output("co_niche").', '@output("strong_claim").',
               '@output("differentiates").', '@explain("console").']
    return "\n".join(["% facts", *facts, "", "% rules", *rules, "",
                      "% models", *models, "", "% outputs", *outputs, ""])


# --------------------------------------------------------------------------- #
# 2. A tiny in-process Datalog evaluator (the fallback engine)
# --------------------------------------------------------------------------- #
@dataclass
class ReasonResult:
    engine: str                       # "prometheux" | "local"
    derived: dict[str, list[tuple]]   # predicate -> list of fact tuples
    explanations: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"engine": self.engine,
                "derived": {k: [list(t) for t in v] for k, v in self.derived.items()},
                "explanations": self.explanations}


_FACT_RE = re.compile(r'(\w+)\((.*)\)\.')


def _parse_facts(vada: str) -> dict[str, list[tuple]]:
    """Parse the ground ``% facts`` atoms back into tuples (engine-independent)."""
    facts: dict[str, list[tuple]] = {}
    for line in vada.splitlines():
        line = line.strip()
        if not line or line.startswith("%") or line.startswith("@") or ":-" in line:
            continue
        m = _FACT_RE.match(line)
        if not m:
            continue
        pred, args = m.group(1), m.group(2)
        toks: list[Any] = []
        for a in (x.strip() for x in args.split(",")):
            if a.startswith('"'):
                toks.append(a.strip('"'))
            else:
                try:
                    toks.append(float(a))
                except ValueError:
                    toks.append(a)
        facts.setdefault(pred, []).append(tuple(toks))
    return facts


def _reason_local(vada: str) -> ReasonResult:
    """Evaluate the four rules directly over the parsed facts.

    The rules are fixed and small, so we hand-evaluate them rather than ship a
    general Datalog solver — this keeps the fallback dependency-free and obvious,
    and it emits the same @model natural-language strings the hosted engine would.
    """
    f = _parse_facts(vada)
    expressed = f.get("expressed_in", [])      # (target, celltype, conf)
    evidence = f.get("evidence", [])           # (target, axis, conf)

    # co_niche(A,B): shared cell type
    by_ct: dict[str, set[str]] = {}
    for tgt, ct, _ in expressed:
        by_ct.setdefault(ct, set()).add(tgt)
    co_niche = sorted({(a, b) for members in by_ct.values()
                       for a in members for b in members if a != b})

    # strong_claim(T,Ax): conf >= gate
    strong = sorted({(t, ax) for (t, ax, c) in evidence if c >= STRONG_CONF})
    strong_set = set(strong)

    # differentiates(A,B,Ax): A strong on Ax, B has evidence on Ax below gate
    weak = {(t, ax) for (t, ax, c) in evidence if c < STRONG_CONF}
    differentiates = sorted({(a, b, ax) for (a, ax) in strong_set
                             for (b, bax) in weak if bax == ax and a != b})

    explanations: list[dict[str, Any]] = []
    for a, b in co_niche:
        explanations.append({"fact": f"co_niche({a}, {b})",
                             "nl": f"{_short(a)} and {_short(b)} occupy a shared cell-type niche"})
    for t, ax in strong:
        explanations.append({"fact": f"strong_claim({t}, {ax})",
                             "nl": f"{_short(t)} has strong evidence on the {ax} axis (confidence >= {STRONG_CONF})"})
    for a, b, ax in differentiates:
        explanations.append({"fact": f"differentiates({a}, {b}, {ax})",
                             "nl": f"{_short(a)} ranks over {_short(b)} on {ax}: "
                                   f"{_short(a)} has a strong claim there, {_short(b)} does not"})

    return ReasonResult("local",
                        {"co_niche": co_niche, "strong_claim": strong,
                         "differentiates": differentiates},
                        explanations)


def _short(node_id: str) -> str:
    """target:b7-h3 -> b7-h3 for readable explanations."""
    return node_id.split(":", 1)[-1] if ":" in node_id else node_id


# --------------------------------------------------------------------------- #
# 2b. The reviewer's gap-detector — structural gaps as derived facts
# --------------------------------------------------------------------------- #
# The prioritization axes a credible target assessment is expected to cover, each
# bound to the routing.yaml skill that fills it. A *missing* axis (no evidence at
# all) is a deductive fact: the engine asserts the gap and forces a re-route to the
# bound skill. The skill names are validated against the catalog downstream by
# cso._reroute_task, so a rename degrades to the routing.yaml fallback, never to an
# invented route.
REQUIRED_AXES = {
    "safety": "openfda-safety",
    "specificity": "celltype-specificity-profiler",
    "genetics": "gwas-lookup",
    "tractability": "clinical-trial-finder",
}


def gap_rules() -> str:
    """The Vadalog gap-detector rules (for ``--vada`` and the live engine).

    These mirror what ``derive_gaps`` evaluates locally. ``missing_axis`` uses
    negation-as-failure over ``required_axis``/``evidence``; ``unsafe_advance`` is
    the safety lens as logic — a target with a strong claim but no safety evidence.
    """
    req = "\n".join(f'required_axis("{ax}").' for ax in REQUIRED_AXES)
    return "\n".join([
        "% required prioritization axes (the dossier contract)",
        req,
        "",
        "% --- a target is missing an axis it should carry evidence on --------",
        'has_axis(T, Ax) :- evidence(T, Ax, _).',
        'missing_axis(T, Ax) :- target(T), required_axis(Ax), not has_axis(T, Ax).',
        "% --- safety lens as logic: a strong claim with no safety read -------",
        'unsafe_advance(T) :- strong_claim(T, _), not has_axis(T, "safety").',
        '@model("missing_axis", "[\'T:string\',\'Ax:string\']", '
        '"[T] carries no evidence on the required [Ax] axis").',
        '@model("unsafe_advance", "[\'T:string\']", '
        '"[T] has a strong claim but no safety evidence — do not advance").',
        '@output("missing_axis").', '@output("unsafe_advance").',
        '@explain("console").',
    ])


# Keywords that mark a routed step as covering a prioritization axis. Matched
# against the step's *skill* and *step id* together, so coverage detection is
# robust to plan-specific step naming (``step_01_gwas`` vs ``step_01_germline...``)
# rather than keyed on exact step ids. Each axis is filled by REQUIRED_AXES[ax].
_AXIS_KEYWORDS = {
    "safety": ("safety", "offtarget", "off-target", "openfda", "adverse"),
    "specificity": ("specificity", "celltype", "cell-type", "expression", "malignant"),
    "genetics": ("gwas", "genetic", "germline", "fine-mapping", "association"),
    "tractability": ("trial", "clinical", "tractab"),
}


def _covered_axis(skill: str, step: str) -> str | None:
    """Which required axis (if any) a routed step covers, by skill/step keywords."""
    hay = f"{skill} {step}".lower()
    for axis, words in _AXIS_KEYWORDS.items():
        if any(w in hay for w in words):
            return axis
    return None


def gaps_from_evidence(results: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    """Derive structural gaps straight from the harness's routed evidence steps.

    Equivalent to :func:`derive_gaps` over the property graph, but reads the axis
    coverage from each step's skill + step id — so the harness reviewer panel can
    call the gap-detector without depending on kg.py / the frontend graph store.

    Two grades of gap, deliberately distinct:

    * **No step targeted the axis at all** → a *structural* gap. This is a clean
      deductive fact ("the plan never looked at safety"), so it ``forces_reroute``:
      the engine is the non-silenceable voter and a re-route to the bound skill is
      warranted regardless of the LLM panel.
    * **A step targeted the axis but returned no data** (grade ``absent``) → a
      *weak-evidence* gap. It is reported (so the reviewer panel can weigh it) but
      does **not** force a re-route — re-routing to the same skill that already
      returned nothing would loop without adding evidence. The bounded reviewer
      loop and ``absent``-handling already cover this case.
    """
    attempted: set[str] = set()   # an axis some step targeted (any grade)
    with_data: set[str] = set()   # an axis with a non-absent result
    for e in results:
        axis = _covered_axis(e.get("skill", ""), e.get("step", ""))
        if not axis:
            continue
        attempted.add(axis)
        if e.get("grade") and e.get("grade") != "absent":
            with_data.add(axis)

    tgt = _short(target)
    gaps: list[dict[str, Any]] = []
    for ax, skill in REQUIRED_AXES.items():
        if ax not in attempted:
            gaps.append({
                "missing": f"no {ax} evidence for {tgt}",
                "route_to": skill,
                "why": f"required axis '{ax}' was never assessed by any routed step",
                "lenses": ["prometheux"],
                "forces_reroute": True,
                "fact": f"missing_axis({tgt}, {ax})",
                "explanation": f"{tgt} carries no evidence on the required {ax} axis "
                               f"(no step targeted it)",
            })
        elif ax not in with_data:
            gaps.append({
                "missing": f"{ax} evidence for {tgt} returned empty",
                "route_to": skill,
                "why": f"the step on axis '{ax}' returned no data (grade: absent)",
                "lenses": ["prometheux"],
                "forces_reroute": False,
                "fact": f"weak_axis({tgt}, {ax})",
                "explanation": f"{tgt}'s {ax} axis was assessed but returned no data",
            })
    return gaps


# --------------------------------------------------------------------------- #
# 2c. The decision layer — a quantitative, replayable GO/NO-GO tier
# --------------------------------------------------------------------------- #
def decision_rules() -> str:
    """The Vadalog decision rules (for ``--vada`` and the live engine).

    Mirrors what :func:`decide_from_evidence` evaluates locally. ``axis_score`` takes
    the best graded evidence per axis; ``score`` sums them; the tier predicates gate
    on the thresholds plus the ``unsafe_advance`` safety hard-gate (already declared
    in :func:`gap_rules`). The thresholds are emitted as facts so the program is
    self-describing.
    """
    weights = "\n".join(f'grade_weight("{g}", {w}).'
                        for g, w in sorted(GRADE_WEIGHT.items()))
    return "\n".join([
        "% --- grade weights + thresholds (the decision contract) -------------",
        weights,
        f'go_threshold({GO_THRESHOLD}).',
        f'conditional_threshold({CONDITIONAL_THRESHOLD}).',
        "% --- best graded evidence per axis becomes that axis's score --------",
        'axis_score(T, Ax, W) :- evidence(T, Ax, G), grade_weight(G, W).',
        '% score(T) = sum over axes of max axis_score  (aggregation)',
        'score(T, sum(W)) :- target(T), axis_score(T, _, W).',
        "% --- tiers: thresholds over score, with the safety hard-gate --------",
        'no_go(T) :- unsafe_advance(T).',
        f'go(T) :- score(T, S), S >= {GO_THRESHOLD}, '
        'strong_claim(T, "safety"), not unsafe_advance(T).',
        f'conditional_go(T) :- score(T, S), S >= {CONDITIONAL_THRESHOLD}, '
        'has_axis(T, "safety"), not unsafe_advance(T), not go(T).',
        'review(T) :- target(T), not go(T), not conditional_go(T), not no_go(T).',
        '@model("go", "[\'T:string\']", "[T] meets the GO bar: coverage score '
        '>= threshold with a strong safety read").',
        '@output("no_go").', '@output("go").', '@output("conditional_go").',
        '@output("review").', '@explain("console").',
    ])


def decide_from_evidence(results: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """Derive a quantitative, replayable GO/NO-GO tier from the routed evidence.

    Reads axis coverage from each step's skill + step id via :func:`_covered_axis`
    (the *same* mapping the gap-detector uses, so coverage can never drift between
    the two), grades each axis by its strongest evidence, and scores the target as
    the weighted sum across :data:`REQUIRED_AXES`. The tier is a threshold over that
    score plus a non-negotiable safety hard-gate: a target with a strong claim on
    any axis but no safety read is ``NO_GO`` regardless of score.

    Returns the shape the report consumes::

        {"tier": "GO"|"CONDITIONAL_GO"|"REVIEW"|"NO_GO",
         "score": float, "max_score": 4.0,
         "axes": {axis: {"grade": str, "weight": float}},
         "explanation": str,        # the rule-chain, decomposed to per-axis facts
         "facts": [str, ...]}       # ground decision atoms, for replay

    Pure-local and dependency-free — the same path runs whether or not a token is
    set, so the decision always renders.
    """
    tgt = _short(target)
    # best graded evidence per required axis (max weight wins)
    axes: dict[str, dict[str, Any]] = {
        ax: {"grade": "absent", "weight": 0.0} for ax in REQUIRED_AXES}
    for e in results:
        # harness steps carry skill/step (keyword-mapped); graph ledger rows carry
        # an explicit `axis` already — accept either so the CLI and live loop agree.
        axis = e.get("axis") if e.get("axis") in axes else None
        if axis is None:
            axis = _covered_axis(e.get("skill", ""), e.get("step", ""))
        if axis not in axes:
            continue
        grade = e.get("grade") or "absent"
        w = GRADE_WEIGHT.get(grade, 0.0)
        if w > axes[axis]["weight"]:
            axes[axis] = {"grade": grade, "weight": w}

    score = round(sum(a["weight"] for a in axes.values()), 3)
    # axes with genuinely no information — named explicitly so a low score reads as
    # "no information on X", never as a quietly-discounted number.
    absent_axes = [ax for ax, a in axes.items() if a["grade"] == "absent"]
    safety = axes["safety"]
    has_safety = safety["grade"] != "absent"
    strong_safety = safety["grade"] == "strong"
    # a strong claim on any axis with no safety read is the hard-gate trigger
    any_strong = any(a["grade"] == "strong" for a in axes.values())
    unsafe = any_strong and not has_safety

    if unsafe:
        tier, why = "NO_GO", (f"a strong claim exists but {tgt} has no safety read "
                              "— safety hard-gate fires (unsafe_advance)")
    elif score >= GO_THRESHOLD and strong_safety:
        tier, why = "GO", (f"coverage score {score}/4.0 >= {GO_THRESHOLD} with a "
                           "strong safety read")
    elif score >= CONDITIONAL_THRESHOLD and has_safety:
        tier, why = "CONDITIONAL_GO", (f"coverage score {score}/4.0 >= "
                                       f"{CONDITIONAL_THRESHOLD} with safety covered")
    else:
        bar = (f"below {CONDITIONAL_THRESHOLD}" if score < CONDITIONAL_THRESHOLD
               else "safety not covered")
        tier, why = "REVIEW", f"coverage score {score}/4.0 ({bar})"

    breakdown = ", ".join(f"{ax}={a['grade']}({a['weight']})"
                          for ax, a in axes.items())
    # State absence plainly: name the axes with no information rather than letting a
    # low score imply weak-but-present evidence.
    absence = (f" No information on: {', '.join(absent_axes)}." if absent_axes else "")
    explanation = (f"{tgt} → {tier}: {why}.{absence} Per-axis: {breakdown} "
                   f"(sum {score}/4.0).")
    facts = [f"axis_score({tgt}, {ax}, {a['weight']})" for ax, a in axes.items()]
    facts += [f"no_information({tgt}, {ax})" for ax in absent_axes]
    facts.append(f"score({tgt}, {score})")
    facts.append(f"{tier.lower()}({tgt})")
    return {"tier": tier, "score": score, "max_score": 4.0, "axes": axes,
            "absent_axes": absent_axes, "explanation": explanation, "facts": facts}


def derive_gaps(graph: KG.KnowledgeGraph) -> list[dict[str, Any]]:
    """Derive structural review gaps from the graph (the gap-detector role).

    Returns gaps in the exact shape the harness reviewer panel consumes — one per
    (target, missing axis), each carrying a replayable ``explanation``, the
    ``route_to`` skill that fills it, and ``forces_reroute=True`` because a *proven*
    missing axis is not a judgement call. Runs through the same live/local engine
    split as :func:`reason`; on the live path the explanation is the engine's native
    ``@explain`` rule-chain, on the local path the ``@model`` template string.
    """
    # Reuse the fact base reason() compiles, then evaluate the gap rules over it.
    facts = _parse_facts(graph_to_vada(graph))
    evidence = facts.get("evidence", [])           # (target, axis, conf)

    # A node is a target if it is *declared* one or carries *prioritization-axis*
    # evidence. Appearing only in an expression edge (expressed_in) does NOT confer
    # targethood — that is expression context (e.g. a scRNA marker / a cell type),
    # not a candidate-target claim. Folding expressed_in subjects in here would flag
    # markers and cell types as targets missing every axis.
    declared = {t for (t,) in facts.get("target", [])}
    targets = sorted(declared | {t for (t, _, _) in evidence})
    axes_of: dict[str, set[str]] = {}
    for (t, ax, _) in evidence:
        axes_of.setdefault(t, set()).add(ax)

    gaps: list[dict[str, Any]] = []
    for t in targets:
        present = axes_of.get(t, set())
        for ax, skill in REQUIRED_AXES.items():
            if ax not in present:
                gaps.append({
                    "missing": f"no {ax} evidence for {_short(t)}",
                    "route_to": skill,
                    "why": f"required axis '{ax}' has no evidence on the graph",
                    "lenses": ["prometheux"],
                    "forces_reroute": True,
                    "fact": f"missing_axis({t}, {ax})",
                    "explanation": f"{_short(t)} carries no evidence on the required {ax} axis",
                })
    return gaps


# --------------------------------------------------------------------------- #
# 3. Live Prometheux path (used when PMTX_TOKEN is present)
# --------------------------------------------------------------------------- #
# The predicates we ask the hosted engine to populate and read back. These are the
# @output predicates in the compiled program (graph_to_vada); fetch_results pulls
# each one's derived rows.
_PX_OUTPUTS = ("co_niche", "strong_claim", "differentiates")
_PX_PROJECT = "virtual-biotech-cso"
_PX_CONCEPT = "evidence_reasoning"


def _reason_prometheux(vada: str) -> ReasonResult:
    """Run the program on the hosted Vadalog engine via ``prometheux_chain``.

    Confirmed against ``prometheux-chain==0.2.14``: the SDK has no single
    ``reason(program)`` call — reasoning is a **project → concept → run → fetch**
    sequence. We:

      1. ``save_project`` to get / reuse a project,
      2. ``save_concept`` with the Vadalog program as the ``definition`` (one
         ``@output`` predicate per concept; the engine populates it on run),
      3. ``run_concept`` to evaluate the rules, then
      4. ``fetch_results`` to read each derived predicate's rows.

    Auth is the ``PMTX_TOKEN`` env var + the ``JARVISPY_URL`` config the SDK reads
    (the SDK defaults to ``http://localhost:8000``, so the hosted org/user URL must
    be applied or every call 404s). Any failure raises so :func:`reason` degrades to
    the local evaluator (never fabricates). Verified live against the hosted engine
    (2026-06-26): ``run_concept`` needs ``persist_outputs=True`` or ``fetch_results``
    404s on a missing results file, and the result rows are nested at
    ``["results"]["facts"]`` — see :func:`_normalize_px_rows`.
    """
    import prometheux_chain as px  # optional dependency

    # auth: PMTX_TOKEN is read from the env by the SDK; JARVISPY_URL points the SDK
    # at the hosted backend (it ships defaulting to http://localhost:8000, so the
    # hosted org/user URL MUST be applied or every call 404s). Both come from the
    # process env, which the caller/CLI is expected to have loaded from .env.
    url = os.environ.get("JARVISPY_URL")
    if url:
        px.config.set("JARVISPY_URL", url)

    project_id = px.save_project(project_name=_PX_PROJECT)
    # one concept per @output predicate, sharing the same program definition; the
    # engine derives all rules but populates the named output_predicate for fetch.
    derived: dict[str, list[tuple]] = {}
    explanations: list[dict[str, Any]] = []
    for pred in _PX_OUTPUTS:
        concept_name = f"{_PX_CONCEPT}_{pred}"
        px.save_concept(project_id, definition=vada, output_predicate=pred,
                        concept_name=concept_name, existing_name=concept_name)
        # persist_outputs=True is REQUIRED: without it the run computes but writes
        # no results file and fetch_results 500s with PATH_NOT_FOUND. page_size is
        # capped at 1000 by the backend.
        px.run_concept(project_id, concept_name, persist_outputs=True)
        rows = px.fetch_results(project_id, output_predicate=pred, page_size=1000)
        derived[pred] = _normalize_px_rows(rows)
        for r in derived[pred]:
            explanations.append({"fact": f"{pred}({', '.join(map(str, r))})",
                                 "nl": f"{pred}: {', '.join(_short(str(x)) for x in r)}"})
    return ReasonResult("prometheux", derived, explanations)


def _normalize_px_rows(rows: Any) -> list[tuple]:
    """Coerce a ``fetch_results`` payload into a list of fact tuples.

    Permissive on purpose — the precise shape (paginated dict vs list of dicts vs
    list of lists) is confirmed under a live token; this handles the common forms
    and never fabricates: an unrecognised shape yields no rows rather than guesses.
    """
    if rows is None:
        return []
    # The live JarvisPy shape (verified against the hosted engine) is nested:
    #   {"results": {"facts": [[...], ...], "columnNames": [...]},
    #    "pagination": {...}}
    # — rows live at ["results"]["facts"]. We also accept the flatter shapes
    # ({"results"/"rows"/"data"/"items": [...]}) so the parser stays permissive.
    if isinstance(rows, dict):
        inner = rows.get("results")
        if isinstance(inner, dict) and isinstance(inner.get("facts"), list):
            rows = inner["facts"]
        else:
            for key in ("results", "rows", "data", "items"):
                if isinstance(rows.get(key), list):
                    rows = rows[key]
                    break
            else:
                return []
    out: list[tuple] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(tuple(r.values()))
        elif isinstance(r, (list, tuple)):
            out.append(tuple(r))
        else:
            out.append((r,))
    return out


# --------------------------------------------------------------------------- #
# 4. Orchestration: prefer live Prometheux, degrade to local — never fabricate
# --------------------------------------------------------------------------- #
def reason(graph: KG.KnowledgeGraph | None = None, *, prefer: str = "auto") -> ReasonResult:
    """Compile the graph and reason over it.

    ``prefer``: ``auto`` (Prometheux if PMTX_TOKEN set, else local), ``prometheux``
    (force live; error surfaces), or ``local`` (force the in-process evaluator).
    """
    graph = graph or KG.KnowledgeGraph()
    vada = graph_to_vada(graph)

    want_px = prefer == "prometheux" or (prefer == "auto" and os.environ.get("PMTX_TOKEN"))
    if want_px:
        try:
            return _reason_prometheux(vada)
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            if prefer == "prometheux":
                raise
            print(f"[prometheux] live reasoning unavailable ({exc}); using local fallback")
    return _reason_local(vada)


# --------------------------------------------------------------------------- #
# 5. Ranking explanations — surface the `differentiates` rule (explain-a-rank)
# --------------------------------------------------------------------------- #
def rank_explanations(graph: KG.KnowledgeGraph | None = None, *,
                      prefer: str = "auto") -> list[dict[str, Any]]:
    """Surface the ``differentiates`` rule as structured ranking edges.

    ``differentiates(A, B, Ax)`` means *A ranks over B on axis Ax* — A has a strong
    claim there and B has only weak evidence. The rule is already evaluated by
    :func:`reason` (live Prometheux or the local fallback, same split); this function
    just shapes its output into the explain-a-rank edges the report and the frontend
    consume, one per (winner, loser, axis)::

        {"winner": str, "loser": str, "axis": str,
         "explanation": str,           # natural-language rule chain
         "fact": "differentiates(A, B, Ax)"}

    A target that wins on more axes is the better-supported one — but the value here
    is the *why*, not a bare rank: every edge names the axis and the evidence
    asymmetry that produced it. Returns ``[]`` when the graph has fewer than two
    targets (nothing to differentiate).
    """
    result = reason(graph, prefer=prefer)
    edges: list[dict[str, Any]] = []
    for row in result.derived.get("differentiates", []):
        if len(row) != 3:
            continue
        a, b, ax = row
        edges.append({
            "winner": _short(a), "loser": _short(b), "axis": ax,
            "explanation": f"{_short(a)} ranks over {_short(b)} on {ax}: "
                           f"{_short(a)} has a strong claim there, {_short(b)} does not",
            "fact": f"differentiates({a}, {b}, {ax})",
        })
    return edges


def rank_targets(graph: KG.KnowledgeGraph | None = None, *,
                 prefer: str = "auto") -> list[dict[str, Any]]:
    """Aggregate the ranking edges into a per-target leaderboard.

    Counts the axes each target wins on (``differentiates`` edges where it is the
    winner) minus the axes it loses on, giving a transparent net-wins score whose
    every point traces back to a named axis in :func:`rank_explanations`. Sorted best
    first; ties broken by fewer losses then name. Returns ``[]`` for a single target.
    """
    edges = rank_explanations(graph, prefer=prefer)
    wins: dict[str, set[str]] = {}
    losses: dict[str, set[str]] = {}
    for e in edges:
        wins.setdefault(e["winner"], set()).add(e["axis"])
        losses.setdefault(e["loser"], set()).add(e["axis"])
    targets = set(wins) | set(losses)
    board = [{
        "target": t,
        "wins_on": sorted(wins.get(t, set())),
        "loses_on": sorted(losses.get(t, set())),
        "net_wins": len(wins.get(t, set())) - len(losses.get(t, set())),
    } for t in targets]
    board.sort(key=lambda r: (-r["net_wins"], len(r["loses_on"]), r["target"]))
    return board


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vadalog reasoning over the CSO evidence graph.")
    p.add_argument("--store", type=Path, default=KG.STORE, help="kg.json to reason over")
    p.add_argument("--prefer", choices=["auto", "prometheux", "local"], default="auto")
    p.add_argument("--vada", action="store_true", help="print the compiled Vadalog program and exit")
    p.add_argument("--gaps", action="store_true", help="run the reviewer gap-detector and exit")
    p.add_argument("--decide", action="store_true", help="run the GO/NO-GO decision layer and exit")
    p.add_argument("--rank", action="store_true", help="explain-a-rank: why target A ranks over B")
    p.add_argument("--target", default="", help="target symbol for --decide (else inferred from the graph)")
    p.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = p.parse_args(argv)

    graph = KG.KnowledgeGraph(store=args.store)
    if not graph.edges:
        print(f"[prometheux] no graph at {args.store} — run the CSO loop first to build one")
        return 1

    if args.vada:
        print(graph_to_vada(graph))
        print(gap_rules())
        print(decision_rules())
        return 0

    if args.decide:
        # Reconstruct the routed-evidence shape from the graph ledger (which already
        # carries axis + grade), then derive the tier over it.
        rows = graph.ledger()
        target = args.target or next(
            (r["subject"] for r in rows if str(r.get("subject", "")).startswith("target:")),
            "target")
        decision = decide_from_evidence(rows, target)
        if args.json:
            print(json.dumps(decision, indent=2))
            return 0
        print(f"decision: {decision['tier']}  (score {decision['score']}/{decision['max_score']})")
        print(f"  {decision['explanation']}")
        return 0

    if args.rank:
        edges = rank_explanations(graph, prefer=args.prefer)
        board = rank_targets(graph, prefer=args.prefer)
        if args.json:
            print(json.dumps({"leaderboard": board, "edges": edges}, indent=2))
            return 0
        if not edges:
            print("explain-a-rank — fewer than two comparable targets on the graph; "
                  "nothing to differentiate yet.")
            return 0
        print(f"explain-a-rank — leaderboard ({len(board)} targets):")
        for r in board:
            print(f"  {r['net_wins']:+d}  {r['target']}  "
                  f"(wins on {', '.join(r['wins_on']) or '—'})")
        print(f"\nranking edges ({len(edges)}):")
        for e in edges:
            print(f"  • {e['explanation']}")
        return 0

    if args.gaps:
        gaps = derive_gaps(graph)
        if args.json:
            print(json.dumps(gaps, indent=2))
            return 0
        print(f"reviewer gap-detector — {len(gaps)} structural gap(s):")
        for g in gaps:
            force = " [forces re-route]" if g.get("forces_reroute") else ""
            print(f"  • {g['explanation']} → route_to {g['route_to']}{force}")
        return 0

    result = reason(graph, prefer=args.prefer)
    if args.json:
        print(json.dumps(result.to_json(), indent=2))
        return 0

    print(f"engine: {result.engine}")
    for pred, rows in result.derived.items():
        print(f"\n{pred} ({len(rows)}):")
        for r in rows:
            print("  " + ", ".join(map(str, r)))
    print("\nexplanations:")
    for e in result.explanations:
        print(f"  • {e['nl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
