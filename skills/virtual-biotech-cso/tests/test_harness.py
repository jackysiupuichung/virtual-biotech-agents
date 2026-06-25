"""Tests for the live multi-agent harness (offline; no network/LLM/API key).

Every test injects a fake runner via runners.select_runner monkeypatching, so
no provider SDK or API key is required. We verify the harness wiring:
  - live agent payloads flow into the report/result.json,
  - a live `re-route` verdict actually drives a 6th evidence step,
  - malformed agent JSON and a missing backend both degrade to honest stubs,
  - JSON extraction is robust to fences/prose.
"""
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import harness  # noqa: E402
import runners  # noqa: E402


class FakeRunner:
    """Returns a canned payload keyed by which role prompt it was handed."""

    name = "fake"
    model = "fake-1"

    def __init__(self, verdict="synthesize"):
        self._verdict = verdict
        self.calls = []

    def run(self, prompt, context, schema):
        # Dispatch on the prompt's title (first line) — robust to cross-references
        # between prompts (orchestrator.md mentions both "Chief-of-Staff" and
        # "Scientific Reviewer" in its body).
        title = prompt.splitlines()[0]
        self.calls.append(title)
        # The planner reuses the Orchestrator prompt but is the only call whose
        # schema asks for `subtasks` — dispatch on that before the synthesis branch.
        if "subtasks" in schema:
            return {"subtasks": [
                {"division": "target_id_and_prioritization",
                 "intent": "germline_genetic_support", "question": "germline?",
                 "depends_on": []},
                {"division": "clinical_officers",
                 "intent": "prior_trials_and_outcomes", "question": "prior trials?",
                 "depends_on": []},
            ]}
        if "Chief of Staff" in title:
            return {"context": "ctx", "data_availability": [], "priority_questions": ["q"],
                    "feasibility_flags": []}
        if "Scientific Reviewer" in title:
            return {"verdict": self._verdict,
                    "scores": {"relevance": 5, "evidence": 4, "thoroughness": 3},
                    "gaps": [{"missing": "spatial", "route_to": "scrna-orchestrator",
                              "why": "lost context"}] if self._verdict == "re-route" else [],
                    "experiments": []}
        if "Orchestrator" in title:
            return {"decision": "CONDITIONAL_GO", "confidence": "medium",
                    "recommendation": "rec [step_03]", "target_overview": "ov",
                    "liabilities": [{"risk": "r", "mitigation": "m"}],
                    "evidence_gaps": [], "proposed_experiments": []}
        raise AssertionError(f"unexpected prompt title: {title!r}")


def _run(monkeypatch, runner, tmp_path, demo=True):
    monkeypatch.setattr(runners, "select_runner", lambda *a, **k: runner)
    return harness.run("Assess B7-H3 in lung cancer", tmp_path,
                       backend="auto", model=None, demo=demo, live=False, argv=["--demo"])


# --------------------------- happy path ----------------------------------- #
def test_live_loop_writes_contract_and_marks_llm(monkeypatch, tmp_path):
    out = _run(monkeypatch, FakeRunner("synthesize"), tmp_path)
    assert Path(out["report"]).exists()
    assert Path(out["result"]).exists()
    summary = out["summary"]
    assert summary["calls_llm"] is True
    assert summary["backend"] == "fake"
    assert summary["decision"] == "CONDITIONAL_GO"
    # synthesis recommendation reached the rendered report
    assert "rec [step_03]" in Path(out["report"]).read_text()


# --------------------- agent-proposed plan (change #1) -------------------- #
def test_agent_proposed_plan_is_validated_and_used(monkeypatch, tmp_path):
    runner = FakeRunner("synthesize")
    out = _run(monkeypatch, runner, tmp_path)
    data = json.loads(Path(out["result"]).read_text())["data"]
    steps = [e["step"] for e in data["evidence"]]
    # The agent's 2-step plan (not the deterministic 5-step) was bound + executed.
    assert steps[:2] == ["step_01_germline_genetic_support",
                         "step_02_prior_trials_and_outcomes"], steps
    # plan bound to real skills from routing.yaml
    skills = {e["step"]: e["skill"] for e in data["evidence"]}
    assert skills["step_01_germline_genetic_support"] == "gwas-lookup"
    assert skills["step_02_prior_trials_and_outcomes"] == "clinical-trial-finder"


class BadPlanRunner(FakeRunner):
    """Proposes an invented division → harness must fall back to deterministic plan."""

    def run(self, prompt, context, schema):
        if "subtasks" in schema:
            return {"subtasks": [{"division": "made_up_division", "intent": "x"}]}
        return super().run(prompt, context, schema)


def test_invalid_plan_falls_back_to_deterministic(monkeypatch, tmp_path):
    out = _run(monkeypatch, BadPlanRunner("synthesize"), tmp_path)
    data = json.loads(Path(out["result"]).read_text())["data"]
    steps = [e["step"] for e in data["evidence"]]
    # deterministic 5-step plan, not the invented one
    assert steps[0] == "step_01_gwas", steps
    assert len(steps) >= 5


# --------------------- reviewer verdict drives control flow --------------- #
def test_live_reroute_adds_sixth_step(monkeypatch, tmp_path):
    out = _run(monkeypatch, FakeRunner("re-route"), tmp_path)
    data = json.loads(Path(out["result"]).read_text())["data"]
    steps = [e["step"] for e in data["evidence"]]
    assert "step_06_reroute" in steps, steps
    assert out["summary"]["reviewer_verdict"] == "re-route"


def test_synthesize_verdict_has_no_reroute(monkeypatch, tmp_path):
    out = _run(monkeypatch, FakeRunner("synthesize"), tmp_path)
    data = json.loads(Path(out["result"]).read_text())["data"]
    assert "step_06_reroute" not in [e["step"] for e in data["evidence"]]


# --------------------- graceful degradation ------------------------------- #
class BoomRunner:
    name = "boom"
    model = "boom-1"

    def run(self, prompt, context, schema):
        return "this is not json at all"  # forces AgentError downstream


def test_malformed_json_falls_back_to_stub(monkeypatch, tmp_path):
    # run_with_retry will raise AgentError; harness must stub, not crash.
    out = _run(monkeypatch, BoomRunner(), tmp_path)
    assert Path(out["report"]).exists()


class NoBackendRunner(runners.StubRunner):
    pass


def test_no_backend_degrades_to_honest_stub(monkeypatch, tmp_path):
    out = _run(monkeypatch, NoBackendRunner(), tmp_path)
    # stub runner → calls_llm False, backend none, but still produces a report
    assert out["summary"]["calls_llm"] is False
    assert out["summary"]["backend"] == "none"
    assert Path(out["report"]).exists()


# --------------------------- JSON extraction ------------------------------ #
def test_extract_json_handles_fences_and_prose():
    assert runners._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert runners._extract_json('Here you go: {"a": 1, "b": [2]} done') == {"a": 1, "b": [2]}
    with pytest.raises(runners.AgentError):
        runners._extract_json("no json here")


def test_select_runner_no_keys_no_cli_returns_stub(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(runners.shutil, "which", lambda _: None)
    r = runners.select_runner("auto")
    assert isinstance(r, runners.StubRunner)
    with pytest.raises(runners.NoBackendError):
        r.run("p", "c", {})


# --------------------------- Claude CLI backend --------------------------- #
def test_auto_selects_cli_when_no_key_but_binary(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(runners.shutil, "which", lambda _: "/usr/local/bin/claude")
    r = runners.select_runner("auto")
    assert isinstance(r, runners.ClaudeCLIRunner)


def test_cli_runner_parses_output_envelope(monkeypatch):
    class Proc:
        returncode = 0
        stdout = json.dumps({"result": '```json\n{"verdict": "synthesize"}\n```'})
        stderr = ""

    monkeypatch.setattr(runners.subprocess, "run", lambda *a, **k: Proc())
    r = runners.ClaudeCLIRunner(bin_path="/usr/local/bin/claude")
    assert r.run("Scientific Reviewer", "ctx", {}) == {"verdict": "synthesize"}


def test_cli_runner_raises_on_nonzero_exit(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "auth error"

    monkeypatch.setattr(runners.subprocess, "run", lambda *a, **k: Proc())
    r = runners.ClaudeCLIRunner(bin_path="/usr/local/bin/claude")
    with pytest.raises(runners.AgentError):
        r.run("p", "c", {})


def test_cli_runner_missing_binary_raises_no_backend(monkeypatch):
    monkeypatch.setattr(runners.shutil, "which", lambda _: None)
    with pytest.raises(runners.NoBackendError):
        runners.ClaudeCLIRunner()
