"""Tests for openfda-safety (offline; no network)."""
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from openfda_safety import build_demo  # noqa: E402

SCRIPT = SKILL_DIR / "openfda_safety.py"


def test_demo_shape():
    d = build_demo()
    assert d["drug"] == "capmatinib"
    assert d["adverse_events"]
    # sorted by report_count descending (FAERS count query order)
    counts = [e["report_count"] for e in d["adverse_events"]]
    assert counts == sorted(counts, reverse=True)
    assert all("reaction" in e and "report_count" in e for e in d["adverse_events"])


def test_demo_writes_contract(tmp_path):
    out = tmp_path / "fda"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert (out / "safety.json").exists()
    assert (out / "report.md").exists()
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (out / "reproducibility" / f).exists()
    safety = json.loads((out / "safety.json").read_text())
    assert safety["skill"] == "openfda-safety"
    assert safety["demo"] is True
    # the spontaneous-reporting caveat must always be present
    report = (out / "report.md").read_text()
    assert "spontaneous reports" in safety["note"]
    assert "not incidence or causation" in report or "reporting frequency" in report


def test_requires_drug_or_demo():
    res = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "--drug" in (res.stderr + res.stdout)
