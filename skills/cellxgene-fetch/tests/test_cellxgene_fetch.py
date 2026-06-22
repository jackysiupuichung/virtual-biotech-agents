"""Tests for the cellxgene-fetch skill (offline; no network, no cellxgene-census)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from cellxgene_fetch import DEMO_CELL_TYPES, DEMO_GENES, build_demo_adata  # noqa: E402

SCRIPT = SKILL_DIR / "cellxgene_fetch.py"
PROFILER = SKILL_DIR.parent / "celltype-specificity-profiler" / "profiler.py"


def _require_anndata():
    pytest.importorskip("anndata")
    pytest.importorskip("scanpy")


# --------------------------- demo atlas builder --------------------------- #
def test_demo_adata_shape_and_labels():
    _require_anndata()
    a = build_demo_adata(n_per_type=20)
    assert a.n_obs == 20 * len(DEMO_CELL_TYPES)
    assert list(a.var_names) == DEMO_GENES
    assert set(a.obs["cell_type"]) == set(DEMO_CELL_TYPES)
    # log-normalized → non-negative (valid for tau)
    import numpy as np
    assert float(np.asarray(a.X).min()) >= 0.0


def test_restricted_marker_is_b_cell_high():
    _require_anndata()
    import numpy as np
    a = build_demo_adata(n_per_type=40)
    col = np.asarray(a[:, "MARKER_RESTRICTED"].X).ravel()
    bmask = (a.obs["cell_type"] == "B cell").values
    assert col[bmask].mean() > col[~bmask].mean() * 5  # strongly restricted


# --------------------------- end-to-end demo ------------------------------ #
def test_demo_writes_contract(tmp_path):
    _require_anndata()
    out = tmp_path / "cxg"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert (out / "atlas.h5ad").exists()
    assert (out / "result.json").exists()
    repro = out / "reproducibility"
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (repro / f).exists()
    summary = json.loads((out / "result.json").read_text())
    assert summary["skill"] == "cellxgene-fetch"
    assert summary["n_cell_types"] == len(DEMO_CELL_TYPES)


def test_chain_into_specificity_profiler(tmp_path):
    """cellxgene-fetch --demo  ->  celltype-specificity-profiler  ->  tau.

    Skipped when the profiler isn't present, so this skill stays standalone
    (it ships as its own PR, independent of celltype-specificity-profiler).
    """
    _require_anndata()
    if not PROFILER.exists():
        pytest.skip("celltype-specificity-profiler not present — cellxgene-fetch is standalone")
    out = tmp_path / "cxg"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
        check=True, capture_output=True, text=True,
    )
    prof_out = tmp_path / "prof"
    res = subprocess.run(
        [sys.executable, str(PROFILER), "--gene", "MARKER_RESTRICTED",
         "--atlas", str(out / "atlas.h5ad"), "--out", str(prof_out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    profile = json.loads(res.stdout)
    assert profile["tau"] >= 0.85                      # restricted -> high tau
    assert profile["interpretation"].startswith("cell-type-specific")
    assert profile["top_cell_types"][0]["cell_type"] == "B cell"
