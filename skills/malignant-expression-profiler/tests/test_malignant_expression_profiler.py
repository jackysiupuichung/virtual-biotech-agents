"""Tests for malignant-expression-profiler (offline)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from malignant_expression_profiler import (  # noqa: E402
    build_demo_adata,
    malignant_contrast,
    resolve_malignant_label,
)

SCRIPT = SKILL_DIR / "malignant_expression_profiler.py"


def _require_anndata():
    pytest.importorskip("anndata")
    pytest.importorskip("scanpy")


# --------------------------- pure logic ----------------------------------- #
def test_resolve_malignant_label_autodetect():
    cts = ["T cell", "malignant cell", "fibroblast"]
    assert resolve_malignant_label(cts, None) == "malignant cell"
    assert resolve_malignant_label(["T cell", "B cell"], None) is None
    assert resolve_malignant_label(cts, "fibroblast") == "fibroblast"


def test_contrast_on_tumour_favourable():
    expr = [5.0] * 50 + [0.0] * 50           # malignant high, rest off
    ct = ["malignant cell"] * 50 + ["fibroblast"] * 50
    out = malignant_contrast(expr, ct, "malignant cell")
    assert out["malignant"]["pct_expressing"] == 1.0
    assert out["malignant_enrichment"] is None          # non-malignant ≈ 0 → exclusive
    assert out["tumour_target_call"] == "on-tumour (favourable)"


def test_contrast_off_tumour_liability():
    expr = [0.0] * 50 + [5.0] * 50           # malignant off, stroma high
    ct = ["malignant cell"] * 50 + ["fibroblast"] * 50
    out = malignant_contrast(expr, ct, "malignant cell")
    assert out["malignant"]["pct_expressing"] == 0.0
    assert out["tumour_target_call"].startswith("off-tumour")


def test_contrast_normal_expression_risk():
    # on most malignant cells, but non-malignant expresses more
    expr = [1.0] * 50 + [3.0] * 50
    ct = ["malignant cell"] * 50 + ["luminal epithelial cell"] * 50
    out = malignant_contrast(expr, ct, "malignant cell")
    assert out["malignant_enrichment"] < 0.8
    assert "normal-expression risk" in out["tumour_target_call"]


# --------------------------- end-to-end demo ------------------------------ #
def test_demo_writes_contract(tmp_path):
    _require_anndata()
    out = tmp_path / "me"
    res = subprocess.run([sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert (out / "malignant_profile.json").exists()
    assert (out / "report.md").exists()
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (out / "reproducibility" / f).exists()
    prof = json.loads((out / "malignant_profile.json").read_text())
    assert prof["skill"] == "malignant-expression-profiler"
    assert prof["tumour_target_call"] == "on-tumour (favourable)"
