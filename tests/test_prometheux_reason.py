"""Tests for skills/virtual-biotech-cso/prometheux_reason.py — the Vadalog reasoning layer.

Exercise the engine-independent path (compile → local reasoning) without a token;
the live Prometheux path is verified at the hackathon once PMTX_TOKEN exists.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "virtual-biotech-cso"
sys.path.insert(0, str(SKILL))

import kg as KG  # noqa: E402
import prometheux_reason as pr  # noqa: E402


@pytest.fixture
def graph() -> KG.KnowledgeGraph:
    """Two targets sharing the fibroblast niche; MET clears the strong gate."""
    g = KG.KnowledgeGraph(store=Path(tempfile.mktemp(suffix=".json")))
    g.upsert_edge("target:b7-h3", "celltype:fibroblast", "EXPRESSED_IN", conf=0.61, axis="target_id", run="r1")
    g.upsert_edge("target:met", "celltype:fibroblast", "EXPRESSED_IN", conf=0.55, axis="target_id", run="r2")
    g.upsert_edge("target:met", "disease:nsclc", "SPECIFIC_TO", conf=0.9, axis="specificity", run="r2")
    g.upsert_edge("target:b7-h3", "disease:luad", "SPECIFIC_TO", conf=0.6, axis="specificity", run="r1")
    return g


def test_compiles_facts_and_rules(graph: KG.KnowledgeGraph) -> None:
    vada = pr.graph_to_vada(graph)
    assert 'expressed_in("target:b7-h3", "celltype:fibroblast", 0.61).' in vada
    assert "co_niche(A, B) :-" in vada
    assert "differentiates(A, B, Ax) :-" in vada
    assert '@explain("console").' in vada


def test_local_reasoning_derives_co_niche(graph: KG.KnowledgeGraph) -> None:
    res = pr.reason(graph, prefer="local")
    assert res.engine == "local"
    assert ("target:b7-h3", "target:met") in res.derived["co_niche"]


def test_local_reasoning_gates_strong_claims(graph: KG.KnowledgeGraph) -> None:
    res = pr.reason(graph, prefer="local")
    # MET specificity is 0.9 (>= 0.8) → strong; B7-H3 at 0.6 is not.
    assert ("target:met", "specificity") in res.derived["strong_claim"]
    assert ("target:b7-h3", "specificity") not in res.derived["strong_claim"]


def test_explain_a_rank(graph: KG.KnowledgeGraph) -> None:
    res = pr.reason(graph, prefer="local")
    assert ("target:met", "target:b7-h3", "specificity") in res.derived["differentiates"]
    assert any("ranks over" in e["nl"] for e in res.explanations)


def test_empty_graph_derives_nothing() -> None:
    g = KG.KnowledgeGraph(store=Path(tempfile.mktemp(suffix=".json")))
    res = pr.reason(g, prefer="local")
    assert res.derived["co_niche"] == []
    assert res.explanations == []


# --- the reviewer gap-detector (load-bearing role) ------------------------- #
def test_gaps_from_evidence_flags_missing_axes() -> None:
    # only a specificity step is present → safety/genetics/tractability are gaps
    results = [{"step": "step_03_celltype_specificity", "grade": "strong"}]
    gaps = pr.gaps_from_evidence(results, "B7-H3")
    axes = {g["why"].split("'")[1] for g in gaps}
    assert axes == {"safety", "genetics", "tractability"}
    assert all(g["forces_reroute"] for g in gaps)
    assert all(g["lenses"] == ["prometheux"] for g in gaps)


def test_gaps_bind_to_real_routing_skills() -> None:
    gaps = pr.gaps_from_evidence([], "MET")
    routes = {g["why"].split("'")[1]: g["route_to"] for g in gaps}
    assert routes["safety"] == "openfda-safety"
    assert routes["specificity"] == "celltype-specificity-profiler"


def test_absent_grade_is_weak_not_forcing() -> None:
    # a step that targeted safety but returned no data → reported, but NOT forcing
    # (re-routing to the same empty skill would loop). The other axes are structural.
    results = [{"skill": "openfda-safety", "step": "step_04_offtarget_safety", "grade": "absent"}]
    gaps = {g["why"].split("'")[1]: g for g in gaps_by_axis(results)}
    assert gaps["safety"]["forces_reroute"] is False
    assert gaps["genetics"]["forces_reroute"] is True  # never assessed → structural


def gaps_by_axis(results):
    return pr.gaps_from_evidence(results, "B7-H3")


def test_full_coverage_yields_no_gaps() -> None:
    results = [
        {"step": "step_01_gwas", "grade": "supporting"},
        {"step": "step_03_celltype_specificity", "grade": "strong"},
        {"step": "step_04_offtarget_safety", "grade": "supporting"},
        {"step": "step_05_clinical_trials", "grade": "supporting"},
    ]
    assert pr.gaps_from_evidence(results, "B7-H3") == []


def test_decision_go_requires_strong_safety_and_coverage() -> None:
    """Full coverage with a strong safety read clears the GO bar (score 3.0)."""
    results = [
        {"step": "step_03_celltype_specificity", "grade": "strong"},
        {"step": "step_01_gwas", "grade": "supporting"},
        {"step": "step_05_clinical_trials", "grade": "supporting"},
        {"step": "step_04_offtarget_safety", "grade": "strong"},
    ]
    dec = pr.decide_from_evidence(results, "B7-H3")
    assert dec["tier"] == "GO"
    assert dec["score"] == 3.0


def test_decision_safety_hard_gate_forces_no_go() -> None:
    """A strong claim with no safety read is NO_GO regardless of other coverage."""
    results = [
        {"step": "step_03_celltype_specificity", "grade": "strong"},
        {"step": "step_01_gwas", "grade": "strong"},
        {"step": "step_05_clinical_trials", "grade": "strong"},
        # no safety step at all
    ]
    dec = pr.decide_from_evidence(results, "B7-H3")
    assert dec["tier"] == "NO_GO"
    assert "safety" in dec["explanation"]


def test_decision_weak_coverage_yields_review() -> None:
    """Below the conditional threshold the tier is REVIEW, not a soft GO."""
    results = [
        {"step": "step_03_celltype_specificity", "grade": "suggestive"},
        {"step": "step_04_offtarget_safety", "grade": "suggestive"},
    ]
    dec = pr.decide_from_evidence(results, "B7-H3")
    assert dec["tier"] == "REVIEW"
    assert dec["score"] < pr.CONDITIONAL_THRESHOLD


def test_decision_conditional_go_at_threshold() -> None:
    """Score == conditional threshold with safety covered → CONDITIONAL_GO."""
    results = [
        {"step": "step_03_celltype_specificity", "grade": "supporting"},
        {"step": "step_01_gwas", "grade": "supporting"},
        {"step": "step_05_clinical_trials", "grade": "supporting"},
        {"step": "step_04_offtarget_safety", "grade": "supporting"},
    ]
    dec = pr.decide_from_evidence(results, "B7-H3")
    assert dec["tier"] == "CONDITIONAL_GO"
    assert dec["score"] == 2.0


def test_forcing_gap_overrides_vote_threshold() -> None:
    """A single forcing engine gap re-routes even with zero lens votes."""
    import cso  # noqa: PLC0415
    lens_reviews = [("safety", {"verdict": "synthesize", "gaps": []})]
    engine_gaps = pr.gaps_from_evidence([], "B7-H3")  # all axes missing → forcing
    review = cso.aggregate_panel_review(lens_reviews, extra_gaps=engine_gaps)
    assert review["verdict"] == "re-route"
    assert review["panel"]["forced_by_engine"] is True
    assert review["gaps"][0]["forces_reroute"] is True  # forcing gap sorted first
