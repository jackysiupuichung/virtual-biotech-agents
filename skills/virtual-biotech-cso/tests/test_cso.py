"""Tests for the virtual-biotech-cso skill (offline; no network/LLM)."""
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import pytest  # noqa: E402

from cso import (  # noqa: E402
    PlanValidationError,
    case_key,
    decompose_and_route,
    load_routing,
    validate_and_bind_plan,
    _reroute_task,
    _result_digest,
)

SCRIPT = SKILL_DIR / "cso.py"


# --------------------------- pure helpers --------------------------------- #
def test_case_key_b7h3_aliases():
    for q in ("Assess B7-H3 in lung cancer", "what about CD276?", "b7h3 target"):
        assert case_key(q) == "b7h3"


def test_case_key_generic_slug():
    assert case_key("Evaluate KRAS G12C in colorectal cancer").startswith("evaluate_kras")


def test_decompose_routes_from_yaml():
    routing = load_routing()
    tasks = decompose_and_route("Assess B7-H3 in lung cancer", "b7h3", routing)
    assert [t.step for t in tasks] == [
        "step_01_gwas",
        "step_02_celltype_expression",
        "step_03_celltype_specificity",
        "step_04_offtarget_safety",
        "step_05_clinical_trials",
    ]
    # routing.yaml binds the specificity sub-question to our PR #1 skill
    spec = next(t for t in tasks if t.step == "step_03_celltype_specificity")
    assert spec.skill == "celltype-specificity-profiler"
    # dependency wiring is preserved
    assert spec.depends_on == ["step_02_celltype_expression"]


def test_reroute_task_uses_gap_route():
    gap = {"missing": "spatial validation", "route_to": "scrna-orchestrator", "why": "x"}
    t = _reroute_task(gap)
    assert t.skill == "scrna-orchestrator"
    assert t.step == "step_06_reroute"


def test_result_digest_specificity_shape():
    env = {"result": {"tau": 0.78, "interpretation": "cell-type-specific (tau > 0.7)"}}
    assert "tau=0.78" in _result_digest(env)


# --------------------------- end-to-end demo ------------------------------ #
def _run(args, env_extra=None):
    env = os.environ.copy()
    # ensure no LLM/clawbio path is taken even if a key is present in CI
    env.pop("ANTHROPIC_API_KEY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, env=env,
    )


def test_demo_writes_full_contract(tmp_path):
    out = tmp_path / "demo"
    res = _run(["--demo", "--output", str(out)])
    assert res.returncode == 0, res.stderr
    summary = json.loads(res.stdout)["summary"]
    assert summary["case"] == "b7h3"
    assert summary["mode"] == "demo"
    assert summary["reviewer_verdict"] == "re-route"
    assert summary["n_steps"] == 6  # 5 + one re-route

    assert (out / "report.md").exists()
    assert (out / "result.json").exists()
    repro = out / "reproducibility"
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (repro / f).exists()

    report = (out / "report.md").read_text()
    assert "cached illustrative fixtures" in report  # honesty label present
    assert "celltype-specificity-profiler" in report  # chains to PR #1 skill
    # target-ID dossier structure
    for header in ("## Executive summary", "## Evidence by division", "## Evidence gaps",
                   "## Proposed experiments", "## References & data sources"):
        assert header in report, f"missing section: {header}"
    assert "**Decision:**" in report                       # decision present
    assert "[1]" in report                                 # per-row reference markers
    assert "https://clinicaltrials.gov/" in report          # a harvested source URL

    envelope = json.loads((out / "result.json").read_text())
    assert envelope["skill"] == "virtual-biotech-cso"
    assert envelope["data"]["review"]["verdict"] == "re-route"
    assert len(envelope["data"]["evidence"]) == 6
    # new schema fields
    for key in ("references", "evidence_gaps", "proposed_experiments"):
        assert key in envelope["data"], f"missing data key: {key}"
    assert len(envelope["data"]["references"]) == 6
    assert envelope["summary"]["decision"] == "CONDITIONAL_GO"
    assert envelope["data"]["proposed_experiments"]  # non-empty (synthesis + reviewer)


def test_demo_report_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _run(["--demo", "--output", str(a)])
    _run(["--demo", "--output", str(b)])
    assert (a / "report.md").read_text() == (b / "report.md").read_text()


def test_default_mode_is_honest_without_backends(tmp_path):
    # no --demo, no --live, no API key -> honest 'unavailable'/'not generated', never fabricated
    out = tmp_path / "default"
    res = _run(["--output", str(out)])
    assert res.returncode == 0, res.stderr
    summary = json.loads(res.stdout)["summary"]
    assert summary["n_executed"] == 0
    report = (out / "report.md").read_text()
    assert "not executed" in report
    assert "no data-derived recommendation" in report


# --------------------- validate_and_bind_plan (change #1) ----------------- #
ROUTING = load_routing()


def test_validate_binds_proposed_plan_to_real_skills():
    plan = [
        {"division": "target_id_and_prioritization",
         "intent": "germline_genetic_support", "question": "germline?"},
        {"division": "target_id_and_prioritization",
         "intent": "cell_type_specificity", "question": "specific?",
         "depends_on": ["step_01_germline_genetic_support"]},
    ]
    subtasks = validate_and_bind_plan(plan, ROUTING)
    assert [s.step for s in subtasks] == [
        "step_01_germline_genetic_support", "step_02_cell_type_specificity"]
    assert subtasks[0].skill == "gwas-lookup"
    assert subtasks[1].skill == "celltype-specificity-profiler"
    assert subtasks[1].depends_on == ["step_01_germline_genetic_support"]


def test_validate_rejects_unknown_division():
    with pytest.raises(PlanValidationError, match="unknown division"):
        validate_and_bind_plan([{"division": "nope", "intent": "x"}], ROUTING)


def test_validate_rejects_unroutable_intent():
    with pytest.raises(PlanValidationError, match="not routable"):
        validate_and_bind_plan(
            [{"division": "clinical_officers", "intent": "made_up"}], ROUTING)


def test_validate_rejects_forward_dependency():
    with pytest.raises(PlanValidationError, match="earlier step"):
        validate_and_bind_plan([
            {"division": "clinical_officers", "intent": "prior_trials_and_outcomes",
             "depends_on": ["step_99_future"]},
        ], ROUTING)


def test_validate_rejects_empty_plan():
    with pytest.raises(PlanValidationError, match="empty"):
        validate_and_bind_plan([], ROUTING)


# --------------------- catalog_skills + validated reroute (changes #2/#3) -- #
from cso import catalog_skills, REROUTE_FALLBACK_SKILL  # noqa: E402


def test_catalog_skills_includes_primary_and_also():
    skills = catalog_skills(ROUTING)
    assert "gwas-lookup" in skills                 # primary skill
    assert "lit-synthesizer" in skills             # reroute target
    assert "gwas-catalog-region-fetch" in skills   # from an `also:` list
    assert "scrna-orchestrator" not in skills       # only a reference, not routable


def test_reroute_validates_invented_target():
    gap = {"missing": "x", "route_to": "made-up-skill", "why": "y"}
    t = _reroute_task(gap, ROUTING)
    assert t.skill == REROUTE_FALLBACK_SKILL


def test_reroute_keeps_valid_target_and_numbers_step():
    gap = {"missing": "recency", "route_to": "lit-synthesizer", "why": "stale"}
    t = _reroute_task(gap, ROUTING, step_n=7)
    assert t.skill == "lit-synthesizer"
    assert t.step == "step_07_reroute"


def test_reroute_without_routing_is_backward_compatible():
    # no routing passed → no validation → caller's choice honored (legacy demo path)
    gap = {"missing": "spatial", "route_to": "scrna-orchestrator", "why": "z"}
    assert _reroute_task(gap).skill == "scrna-orchestrator"
