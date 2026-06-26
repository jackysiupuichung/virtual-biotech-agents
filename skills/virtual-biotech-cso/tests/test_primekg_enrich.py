"""Tests for primekg_enrich — curated PrimeKG relations into the evidence graph.

All offline: the PrimeKG query is injected (query_fn), so we exercise the pairing,
resolution-gating, edge schema, and degrade-to-no-op behaviour without a token,
the SDK, or a compute machine.
"""
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import kg as KG  # noqa: E402
import primekg_enrich as pke  # noqa: E402


def _graph(tmp_path):
    return KG.KnowledgeGraph(store=tmp_path / "kg.json")


def _resolved_target(g, label, symbol, run="r1"):
    nid = KG.nid("target", label)
    return g.upsert_node(nid, "Target", label, run=run,
                         canonical_symbol=symbol, canonical_id="ENSG_x")


def _resolved_disease(g, label, symbol, run="r1"):
    nid = KG.nid("disease", label)
    return g.upsert_node(nid, "Disease", label, run=run,
                         canonical_symbol=symbol, canonical_id="MONDO_x")


def test_no_token_no_queryfn_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("PMTX_TOKEN", raising=False)
    g = _graph(tmp_path)
    _resolved_target(g, "B7-H3", "CD276")
    _resolved_disease(g, "lung cancer", "lung adenocarcinoma")
    # no PMTX_TOKEN and no injected query_fn → pure no-op, never touches the network
    assert pke.enrich(g, "r1") == []


def test_fewer_than_two_resolved_nodes_is_noop(tmp_path):
    g = _graph(tmp_path)
    _resolved_target(g, "B7-H3", "CD276")
    g.upsert_node(KG.nid("celltype", "fibroblast"), "CellType", "fibroblast", run="r1")
    # only one resolved entity → nothing to relate
    assert pke.enrich(g, "r1", query_fn=lambda names: [("CD276", "x", "x", "Y")]) == []


def test_adds_edge_for_returned_relation(tmp_path):
    g = _graph(tmp_path)
    t = _resolved_target(g, "B7-H3", "CD276")
    d = _resolved_disease(g, "lung cancer", "lung adenocarcinoma")

    def qf(names):
        assert "CD276" in names and "lung adenocarcinoma" in names
        return [("CD276", "associated_with", "associated with",
                 "lung adenocarcinoma", "gene/protein", "disease")]

    added = pke.enrich(g, "r1", query_fn=qf)
    assert len(added) == 1
    e = added[0]
    assert e["s"] == t["id"] and e["t"] == d["id"]
    assert e["type"] == "PRIMEKG_ASSOCIATED_WITH"
    # context-only: prov=primekg, NO axis / grade so the decision layer ignores it
    assert e["prov"] == "primekg" and e.get("primekg") is True
    assert "axis" not in e and "grade" not in e
    assert e["relation"] == "associated with"


def test_skips_relation_to_unknown_endpoint(tmp_path):
    g = _graph(tmp_path)
    _resolved_target(g, "B7-H3", "CD276")
    _resolved_disease(g, "lung cancer", "lung adenocarcinoma")
    # PrimeKG returns a row whose Y endpoint isn't one of the run's resolved nodes
    added = pke.enrich(g, "r1", query_fn=lambda n: [
        ("CD276", "interacts_with", "interacts with", "SOME_OTHER_GENE")])
    assert added == []


def test_dedupes_repeated_relation(tmp_path):
    g = _graph(tmp_path)
    _resolved_target(g, "B7-H3", "CD276")
    _resolved_disease(g, "lung cancer", "lung adenocarcinoma")
    rels = [("CD276", "associated_with", "associated with", "lung adenocarcinoma")] * 3
    added = pke.enrich(g, "r1", query_fn=lambda n: rels)
    assert len(added) == 1  # same (s, type, t) collapses


def test_query_failure_degrades_to_noop(tmp_path):
    g = _graph(tmp_path)
    _resolved_target(g, "B7-H3", "CD276")
    _resolved_disease(g, "lung cancer", "lung adenocarcinoma")

    def boom(names):
        raise RuntimeError("NO_ACTIVE_COMPUTE")

    assert pke.enrich(g, "r1", query_fn=boom) == []


def test_rel_type_normalization():
    assert pke._rel_type("associated with") == "PRIMEKG_ASSOCIATED_WITH"
    assert pke._rel_type("parent-child") == "PRIMEKG_PARENT_CHILD"
    assert pke._rel_type("") == "PRIMEKG_PRIMEKG_REL"


def test_vada_query_filters_both_endpoints(tmp_path):
    q = pke._vada_query(["CD276", "lung adenocarcinoma"])
    assert "kg_csv" in q and "@output(\"primekg_rel\")" in q
    assert '"CD276"' in q and '"lung adenocarcinoma"' in q
    assert "Xn in [" in q and "Yn in [" in q  # both endpoints constrained
