"""Tests for tcga-somatic-profiler (offline; no network)."""
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from tcga_somatic_profiler import build_demo, interpret  # noqa: E402

SCRIPT = SKILL_DIR / "tcga_somatic_profiler.py"


def test_interpret_calls():
    assert interpret(build_demo())["call"] == "recurrent somatic driver"  # MET UCEC 16%
    assert interpret({"top_cancer_types": [{"cancer_type": "X", "mutated_cases": 5,
                      "cohort": 100, "frequency_pct": 5.0}]})["call"] == "moderate somatic frequency"
    assert "expression target" in interpret({"top_cancer_types": [{"cancer_type": "X",
                      "mutated_cases": 1, "cohort": 100, "frequency_pct": 1.0}]})["call"]
    assert interpret({"top_cancer_types": []})["call"] == "no somatic signal"


def test_demo_ranked_descending():
    d = build_demo()
    f = [r["frequency_pct"] for r in d["top_cancer_types"]]
    assert f == sorted(f, reverse=True)
    # LUAD ~4% matches METex14
    luad = [r for r in d["top_cancer_types"] if r["cancer_type"] == "TCGA-LUAD"][0]
    assert 3.0 <= luad["frequency_pct"] <= 5.0


def test_demo_writes_contract(tmp_path):
    out = tmp_path / "ts"
    res = subprocess.run([sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert (out / "somatic.json").exists()
    assert (out / "report.md").exists()
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (out / "reproducibility" / f).exists()
    s = json.loads((out / "somatic.json").read_text())
    assert s["skill"] == "tcga-somatic-profiler"
    assert s["gene"] == "MET"
    assert "frequency_pct" in s["top_cancer_types"][0]


def test_requires_gene_or_demo():
    res = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode != 0
