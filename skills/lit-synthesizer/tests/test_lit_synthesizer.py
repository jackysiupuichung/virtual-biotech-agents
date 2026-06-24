"""Tests for lit-synthesizer (offline; no network, no key)."""
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from lit_synthesizer import ANGLES, build_demo, fetch_landscape  # noqa: E402

SCRIPT = SKILL_DIR / "lit_synthesizer.py"


def test_demo_shape():
    d = build_demo()
    assert d["target"].startswith("B7-H3")
    # all three fixed angles present and non-empty in the demo
    assert set(d["angles"]) == set(ANGLES)
    assert all(d["angles"][a] for a in ANGLES)
    # every item is citation-first: title + url + content
    for items in d["angles"].values():
        for it in items:
            assert it["url"] and it["title"]
    # n_sources equals the count of distinct URLs across angles
    urls = {it["url"] for items in d["angles"].values() for it in items}
    assert d["n_sources"] == len(urls)


def test_fetch_dedupes_urls_across_angles(monkeypatch):
    # Same URL returned by every angle → counted once, kept only in the first angle.
    import lit_synthesizer as mod

    dup = [{"title": "t", "url": "https://x/dup", "content": "c", "score": 0.5}]
    monkeypatch.setattr(mod, "_search_angle", lambda q, k, n: list(dup))
    land = fetch_landscape("B7-H3", api_key="fake", max_results=5)
    assert land["n_sources"] == 1
    angle_with = [a for a in ANGLES if land["angles"][a]]
    assert angle_with == [next(iter(ANGLES))]  # only the first angle keeps it


def test_demo_writes_contract(tmp_path):
    out = tmp_path / "lit"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", "--output", str(out)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert (out / "landscape.json").exists()
    assert (out / "report.md").exists()
    for f in ("commands.sh", "environment.yml", "checksums.sha256"):
        assert (out / "reproducibility" / f).exists()
    land = json.loads((out / "landscape.json").read_text())
    assert land["skill"] == "lit-synthesizer"
    assert land["demo"] is True
    # the unrefereed-web caveat must always be present, and items must be linked
    report = (out / "report.md").read_text()
    assert "unrefereed" in land["note"]
    assert "[source](" in report


def test_requires_target_or_demo():
    res = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "--target" in (res.stderr + res.stdout)


def test_live_without_key_exits():
    import os

    env = {k: v for k, v in os.environ.items() if k != "TAVILY_API_KEY"}
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--target", "B7-H3"],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode != 0
    assert "TAVILY_API_KEY" in (res.stderr + res.stdout)
