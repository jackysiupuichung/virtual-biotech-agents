#!/usr/bin/env python3
"""facts.py — the normalized fact contract every dataset projects into.

The projection layer exists because Prometheux reasons over *facts* (ground
relational atoms), not over raw experimental matrices or documents. So we never
upload the raw data; we upload its **conclusions, shaped as facts**, and let the
hosted Vadalog engine join and reason across all of them.

Every extractor — whatever the source (a single-cell ``.h5ad`` matrix, a GWAS
table, an extracted-from-PDF claim) — emits rows in ONE schema:

    subject, relation, object, value, confidence, source_dataset, provenance

* ``subject``  — a node id, matching the kg.py convention (``target:cd276``,
                 ``celltype:b-cells``, ``disease:luad``). Lowercased, kebab.
* ``relation`` — the edge type, matching kg.py (``EXPRESSED_IN``, ``GENETIC_LINK``…).
* ``object``   — the other node id.
* ``value``    — a human-readable summary of the conclusion (e.g. "84% expressing").
* ``confidence``— float in [0, 1]; the engine's rules gate on it (STRONG_CONF=0.8).
* ``source_dataset`` — which dataset this fact came from (the bind/provenance key).
* ``provenance`` — a traceable pointer back to the raw source (file, row, doi…).

Adding a dataset = writing one extractor that yields :class:`Fact` rows. The CSV
this module writes is exactly what gets ``@bind``-ed into Prometheux next to
``kg_csv`` (PrimeKG) — see ``bind.vada``.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

COLUMNS = ["subject", "relation", "object", "value",
           "confidence", "source_dataset", "provenance"]


@dataclass(frozen=True)
class Fact:
    subject: str
    relation: str
    object: str
    value: str
    confidence: float
    source_dataset: str
    provenance: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of [0,1]: {self.confidence!r}")
        for f in ("subject", "relation", "object", "source_dataset"):
            if not getattr(self, f):
                raise ValueError(f"{f} is required and must be non-empty")


def node_id(kind: str, label: str) -> str:
    """Build a kg.py-style node id: ('CellType', 'CD4 T cells') -> 'celltype:cd4-t-cells'."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return f"{kind.strip().lower()}:{slug}"


def write_facts(facts: Iterable[Fact], out: Path) -> int:
    """Write facts to a CSV with the canonical header. Returns the row count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for f in facts:
            w.writerow(asdict(f))
            n += 1
    return n
