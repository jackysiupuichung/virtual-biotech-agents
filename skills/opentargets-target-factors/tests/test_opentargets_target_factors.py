"""Tests for opentargets-target-factors (offline; no network)."""
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from opentargets_target_factors import FACTOR_DIVISION, build_demo, map_factors  # noqa: E402

SCRIPT = SKILL_DIR / "opentargets_target_factors.py"


# ----------------------------- pure mapping ------------------------------- #
def test_map_factors_divisions_and_floats():
    mapped = map_factors(build_demo())
    assert mapped["symbol"] == "CD276"
    assert mapped["ensembl_id"] == "ENSG00000103855"
    by_key = {f["key"]: f for f in mapped["prioritisation_factors"]}
    # DepMap essentiality routed to functional genomics
    assert by_key["geneEssentiality"]["division"].startswith("functional_genomics")
    # safety factors routed to target_safety
    assert by_key["geneticConstraint"]["division"] == "target_safety"
    # string OT values are coerced to float
    assert by_key["geneticConstraint"]["value"] == -0.14
    assert by_key["tissueSpecificity"]["value"] == -1.0
    # antibody tractability retained as positive
    assert any(t["label"] == "Advanced Clinical" for t in mapped["tractability_positive"])


def test_every_demo_factor_has_a_division():
    mapped = map_factors(build_demo())
    for f in mapped["prioritisation_factors"]:
        assert f["division"]  # non-empty (FACTOR_DIVISION or "other")


# ----------------------------- end-to-end demo ---------------------------- #
def test_demo_writes_contract(tmp_path):
    out = tmp_path / "otf"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert (out / "factors.json").exists()
    assert (out / "report.md").exists()
    repro = out / "reproducibility"
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (repro / f).exists()
    factors = json.loads((out / "factors.json").read_text())
    assert factors["skill"] == "opentargets-target-factors"
    assert factors["demo"] is True
    # report groups by division
    report = (out / "report.md").read_text()
    assert "functional_genomics (DepMap)" in report
    assert "Advanced Clinical" in report
