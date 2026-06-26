"""kg.py — a persistent, canonical property graph for the Virtual Biotech CSO.

The design (docs/kg-pareto-provenance-design.md §1-2): evidence is NOT stored as
private per-run blobs. Entities are **canonical and deduplicated** — `CD276`,
`LUAD`, `fibroblast`, `CELLxGENE` are one node each, forever — and evidence is
metadata on typed edges between them. The graph **persists and compounds across
queries**: assess B7-H3 today and MET tomorrow, and they link on the shared
LUAD / fibroblast / source nodes.

Node id grammar (stable, canonical):  ``<kind>:<slug>``
    target:CD276 · disease:LUAD · celltype:fibroblast · source:cellxgene ·
    axis:specificity · modality:ADC · hypothesis:CD276@LUAD@ADC · evidence:<step-uid>

Every edge carries confidence ∈ [0,1], provenance, method, a human ``ref``, the
source url (if any), the originating loop ``step``, and the ``run`` id — so a run
can be replayed/attributed and "where did this come from?" is a one-hop query.

Stored as a single JSON file so it is zero-infra, inspectable, and reproducible.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

STORE = Path(__file__).resolve().parent / "kg.json"
_LOCK = threading.Lock()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-") or "x"


# --- canonical id helpers --------------------------------------------------- #
def nid(kind: str, key: str) -> str:
    return f"{kind}:{_slug(key)}"


# map a routed-step provenance icon / source string to a canonical Source node.
# Each entry: keyword -> (label, url). The keyword is matched against the
# "<reference> <skill>" text, so both the human ref string and the skill name can
# resolve a source. Order matters: more specific keys should precede generic ones.
_SOURCE_CANON = {
    "cellxgene": ("CELLxGENE Census", "https://cellxgene.cziscience.com"),
    "census":    ("CELLxGENE Census", "https://cellxgene.cziscience.com"),
    "tabula":    ("Tabula Sapiens", "https://tabula-sapiens.sf.czbiohub.org"),
    # genetics / trials: match the lead catalog before the federated partners, so a
    # ref like "GWAS Catalog / Open Targets / PheWeb" labels as GWAS Catalog.
    "gwas":      ("GWAS Catalog", "https://www.ebi.ac.uk/gwas/"),
    "clinicaltrials": ("ClinicalTrials.gov", "https://clinicaltrials.gov/"),
    "ctgov":     ("ClinicalTrials.gov", "https://clinicaltrials.gov/"),
    "euctr":     ("EU Clinical Trials Register", "https://www.clinicaltrialsregister.eu"),
    "pheweb":    ("PheWeb", "https://pheweb.org"),
    "opentargets": ("Open Targets", "https://platform.opentargets.org"),
    "open targets": ("Open Targets", "https://platform.opentargets.org"),
    "zhang":     ("Zhang et al. 2026 (bioRxiv)", "https://www.biorxiv.org"),
    "biorxiv":   ("bioRxiv preprint", "https://www.biorxiv.org"),
    "pubmed":    ("PubMed", "https://pubmed.ncbi.nlm.nih.gov"),
    # computed/derived analyses are real, named sources too — not a nameless bucket
    "scvi":      ("Single-cell atlas (scVI/scANVI)", ""),
    "scanvi":    ("Single-cell atlas (scVI/scANVI)", ""),
    "scanpy":    ("Single-cell atlas (Scanpy)", ""),
    "single-cell atlas": ("Single-cell atlas", ""),
    "tau":       ("Derived: τ-specificity analysis", ""),
    "bimodality": ("Derived: τ-specificity analysis", ""),
}

# friendlier names for the provenance fallback bucket (never the literal "source")
_PROV_LABEL = {
    "🧪": ("Demo fixture", "demo-fixture"),
    "🔧": ("Computed analysis", "computed"),
    "🗄️": ("Retrieved dataset", "retrieved"),
    "🌐": ("Web / literature search", "web"),
    "⚪": ("Gap — not available", "gap"),
}


def canonical_source(reference: str, skill: str, provenance_icon: str) -> tuple[str, str, str]:
    """Return (canonical_source_id, label, url) for an evidence item.

    Resolves to a *named data source entity* (CELLxGENE, Open Targets, a named
    derived analysis, …) so the same source is one shared node across all runs.
    A literal URL in the reference always wins for the url; the node is keyed by
    its human label so it dedupes by *what it is*, not by a generic provenance
    bucket. We never emit the nameless ``source:source`` node again.
    """
    text = f"{reference} {skill}".lower()
    url_in_ref = re.search(r"https?://[^\s)]+", reference or "")
    for key, (label, url) in _SOURCE_CANON.items():
        if key in text:
            return nid("source", label), label, (url_in_ref.group(0) if url_in_ref else url)
    # No catalog match: still give it a meaningful, deduped identity from the
    # provenance kind — labelled by what it IS, keyed so each kind is one node.
    label, slug = _PROV_LABEL.get(provenance_icon, ("Other source", "other"))
    return nid("source", slug), label, (url_in_ref.group(0) if url_in_ref else "")


class KnowledgeGraph:
    """A persistent canonical property graph. Upserts dedupe by node/edge id."""

    def __init__(self, store: Path = STORE) -> None:
        self.store = store
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self._load()

    # --- persistence -------------------------------------------------------- #
    def _load(self) -> None:
        if self.store.exists():
            try:
                data = json.loads(self.store.read_text())
                self.nodes = {n["id"]: n for n in data.get("nodes", [])}
                self.edges = {e["id"]: e for e in data.get("edges", [])}
            except Exception:
                self.nodes, self.edges = {}, {}

    def _save(self) -> None:
        self.store.write_text(json.dumps(
            {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())},
            indent=2, default=str))

    # --- upserts (canonical: same id merges) -------------------------------- #
    def upsert_node(self, node_id: str, kind: str, label: str, **props) -> dict:
        existing = self.nodes.get(node_id)
        if existing:
            # canonical merge: keep first label, accumulate the runs that touched it
            runs = set(existing.get("runs", []))
            if props.get("run"):
                runs.add(props.pop("run"))
            existing["runs"] = sorted(runs)
            for k, v in props.items():
                if v is not None:
                    existing[k] = v
            return existing
        runs = [props.pop("run")] if props.get("run") else []
        node = {"id": node_id, "kind": kind, "label": label, "runs": runs, **props}
        self.nodes[node_id] = node
        return node

    def upsert_edge(self, s: str, t: str, etype: str, **props) -> dict:
        edge_id = f"{s}|{etype}|{t}"
        existing = self.edges.get(edge_id)
        if existing:
            runs = set(existing.get("runs", []))
            if props.get("run"):
                runs.add(props["run"])
            existing["runs"] = sorted(runs)
            # keep the highest-confidence observation, but remember it was re-seen
            if props.get("conf", 0) >= existing.get("conf", 0):
                existing.update({k: v for k, v in props.items() if k != "run"})
            existing["observations"] = existing.get("observations", 1) + 1
            return existing
        edge = {"id": edge_id, "s": s, "t": t, "type": etype,
                "runs": [props["run"]] if props.get("run") else [], "observations": 1,
                **{k: v for k, v in props.items() if k != "run"}}
        self.edges[edge_id] = edge
        return edge

    # --- queries ------------------------------------------------------------ #
    def shared_with(self, node_id: str, this_run: str) -> list[str]:
        """Other runs that also reference this canonical node (the cross-run link)."""
        n = self.nodes.get(node_id)
        return [r for r in (n.get("runs", []) if n else []) if r != this_run]

    def neighborhood_runs(self, node_id: str) -> int:
        return len(self.nodes.get(node_id, {}).get("runs", []))

    # edges that ARE evidence claims (carry an axis / value / source). The
    # structural/backbone edges (TARGETS hypothesis link, VIA_MODALITY) are not
    # themselves evidence rows.
    _STRUCTURAL = {"TARGETS", "VIA_MODALITY"}

    def ledger(self) -> list[dict]:
        """The accumulated-evidence trail: one row per evidence EDGE.

        In the entity-centric model the edges ARE the evidence, so the ledger is a
        flat read of every evidence edge — the two entities it connects, the axis,
        the value, the grade/confidence, and the source (with url). An auditable
        "what do we hold, between what, where from, how sure" view across all runs.
        """
        rows: list[dict] = []
        for e in self.edges.values():
            if e["type"] in self._STRUCTURAL or not e.get("axis"):
                continue
            s = self.nodes.get(e["s"], {})
            t = self.nodes.get(e["t"], {})
            rows.append({
                "edge_id": e["id"],
                "subject": s.get("label", e["s"]),
                "subject_kind": s.get("kind"),
                "relation": e["type"],
                "object": t.get("label", e["t"]),
                "object_kind": t.get("kind"),
                "axis": e.get("axis"),
                "value": e.get("value"),
                "grade": e.get("grade"),
                "conf": e.get("conf"),
                "prov": e.get("prov"),
                "source": e.get("source") or e.get("ref", ""),
                "url": e.get("url") or "",
                "ref": e.get("ref") or "",
                "step": e.get("step"),
                "runs": sorted(set(e.get("runs", []))),
                "observations": e.get("observations", 1),
            })
        # group by subject entity, then axis, so the trail reads like a dossier
        rows.sort(key=lambda r: (r["subject"], r["axis"] or "", -(r["conf"] or 0)))
        return rows

    def commit(self) -> None:
        with _LOCK:
            self._save()
