#!/usr/bin/env python3
"""to_cso.py — import projected fact CSVs into the CSO evidence graph.

The projection layer ([facts.py](facts.py)) produces dataset-agnostic fact CSVs;
this is the bridge that makes them *evidence the CSO loop reasons over*. It reads
any ``*.facts.csv`` and upserts one evidence edge per fact into the CSO knowledge
graph ([../virtual-biotech-cso/kg.py](../virtual-biotech-cso/kg.py)), so the
imported facts flow through the very same machinery as live-routed steps:
``prometheux_reason.derive_gaps`` / ``decide_from_evidence`` /
``rank_explanations`` all consume the graph ledger, and now see these edges too.

The mapping (fact contract → CSO edge):

  * ``subject``/``object`` node ids already match kg.py's ``kind:slug`` scheme, so
    nodes upsert directly (kind inferred from the id prefix).
  * ``relation`` → edge type, and an **axis**: ``EXPRESSED_IN`` → ``specificity``,
    ``GENETIC_LINK`` → ``genetics`` (the REQUIRED_AXES the gap-detector checks).
  * ``confidence`` → ``conf`` + a **grade** via the same thresholds the report uses.
  * ``source_dataset``/``provenance`` → ``source``/``ref`` so the ledger stays
    auditable ("what do we hold, from where").

    python3 to_cso.py out/pbmc3k_expression.facts.csv out/literature_claims.facts.csv
    python3 to_cso.py --store /tmp/kg.json out/*.facts.csv     # import into a copy
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "virtual-biotech-cso"))
import kg as KG  # noqa: E402

# relation -> the prioritization axis it fills (matches prometheux_reason.REQUIRED_AXES)
_RELATION_AXIS = {
    "EXPRESSED_IN": "specificity",
    "GENETIC_LINK": "genetics",
    "OFF_TARGET_IN": "safety",
    "EVALUATED_IN": "tractability",
}

_KIND_LABEL = {"gene": "Gene", "target": "Target", "celltype": "CellType",
               "disease": "Disease", "drug": "Drug"}


def _grade(conf: float) -> str:
    """Confidence → grade, aligned with prometheux_reason.GRADE_WEIGHT bins."""
    if conf >= 0.8:
        return "strong"
    if conf >= 0.5:
        return "supporting"
    if conf > 0.0:
        return "suggestive"
    return "absent"


def _kind_of(node_id: str) -> str:
    return node_id.split(":", 1)[0] if ":" in node_id else "entity"


def _orient(subject: str, obj: str, relation: str) -> tuple[str, str]:
    """Orient an edge so a candidate **target** is the evidence subject, never a marker.

    The CSO reasoning treats any node that is the subject of an evidence edge as a
    target (prometheux_reason.derive_gaps / the ``evidence(T,Ax,_)`` facts). A
    ``gene:``-prefixed scRNA *marker* (CD3D) is NOT a therapeutic target — it is
    evidence about a **cell type's** expression profile. So for an ``EXPRESSED_IN``
    fact written gene→celltype we flip it to celltype→gene: the cell type carries the
    expression evidence and the marker gene never appears as a target. ``target:``
    subjects (candidate targets, e.g. CD276 from literature) are left as-is.
    """
    if relation == "EXPRESSED_IN" and _kind_of(subject) == "gene":
        return obj, subject          # celltype --EXPRESSED_IN--> gene
    return subject, obj


def import_facts(csv_paths: list[Path], store: Path) -> int:
    graph = KG.KnowledgeGraph(store=store)
    run = f"dataset-projection-import"
    n = 0
    for path in csv_paths:
        for r in csv.DictReader(path.open()):
            rel = r["relation"]
            s, t = _orient(r["subject"], r["object"], rel)
            conf = float(r["confidence"])
            axis = _RELATION_AXIS.get(rel, "evidence")
            s_kind, t_kind = _kind_of(s), _kind_of(t)
            graph.upsert_node(s, _KIND_LABEL.get(s_kind, s_kind.title()),
                              s.split(":", 1)[-1], run=run)
            graph.upsert_node(t, _KIND_LABEL.get(t_kind, t_kind.title()),
                              t.split(":", 1)[-1], run=run)
            graph.upsert_edge(
                s, t, rel, run=run, conf=conf, axis=axis, grade=_grade(conf),
                value=r.get("value", ""), prov="imported",
                source=r.get("source_dataset", ""), ref=r.get("provenance", ""),
                step=f"projection_{r.get('source_dataset','')}")
            n += 1
    graph.commit()
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("facts", nargs="+", type=Path, help="*.facts.csv files to import")
    p.add_argument("--store", type=Path, default=KG.STORE,
                   help="kg.json to import into (default: the CSO graph store)")
    args = p.parse_args(argv)

    n = import_facts(args.facts, args.store)
    print(f"imported {n} projected facts as evidence edges into {args.store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
