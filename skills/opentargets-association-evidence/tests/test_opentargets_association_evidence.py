"""Tests for opentargets-association-evidence (offline; no network)."""
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from opentargets_association_evidence import build_demo, interpret  # noqa: E402

SCRIPT = SKILL_DIR / "opentargets_association_evidence.py"


def test_interpret_bands():
    assert interpret({"overall_score": 0.7, "datatype_scores": {"somatic_mutation": 0.6}})["strength"] == "strong"
    assert interpret({"overall_score": 0.2, "datatype_scores": {"literature": 0.2}})["strength"] == "moderate"
    assert interpret({"overall_score": 0.005, "datatype_scores": {"literature": 0.04}})["strength"] == "weak"
    assert interpret({"overall_score": 0.0, "datatype_scores": {}})["strength"] == "no association"


def test_literature_only_flagged():
    interp = interpret(build_demo())
    assert interp["evidence_datatypes_present"] == ["literature"]
    assert "literature-only" in interp["interpretation"]


def test_demo_writes_contract(tmp_path):
    out = tmp_path / "ae"
    res = subprocess.run([sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert (out / "association.json").exists()
    assert (out / "report.md").exists()
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (out / "reproducibility" / f).exists()
    a = json.loads((out / "association.json").read_text())
    assert a["skill"] == "opentargets-association-evidence"
    assert a["disease"] == "lung carcinoma"
    assert "genetic_association" not in a["datatype_scores"]  # CD276 lung is literature-only
    report = (out / "report.md").read_text()
    assert "Evidence by datatype" in report


def test_requires_gene_and_disease():
    res = subprocess.run([sys.executable, str(SCRIPT), "--gene", "MET"],
                         capture_output=True, text=True)
    assert res.returncode != 0
