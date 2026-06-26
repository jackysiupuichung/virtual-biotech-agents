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


# Cache of alias → canonical metadata so repeat runs / repeat targets don't re-hit
# the Open Targets API. Keyed by (kind, lowercased raw symbol).
_CANON_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def canonical_entity(kind: str, raw: str) -> dict[str, Any]:
    """Resolve a raw target/disease symbol to canonical-identity metadata.

    Uses :mod:`resolver` (Open Targets ``mapIds``, live-first) to turn an alias
    (``B7-H3``) into its canonical symbol/id (``CD276`` / ``ENSG…``; diseases →
    EFO/MONDO). Returns a dict of node properties to attach::

        {"canonical_symbol": str, "canonical_id": str, "ontology": str,
         "alias_of": str | None}

    The node *id* itself stays slug-based (``nid``) so existing ``kg.json`` nodes
    keep deduping — this only enriches the node with its canonical identity, and
    records ``alias_of`` when the input differed from the canonical symbol. Resolver
    failure (offline, no hit) yields empty metadata; we never block node creation on
    a network call, and never fabricate an id. ``kind`` is ``"target"`` or
    ``"disease"`` (anything else returns empty — only those two normalize).
    """
    entity = {"target": "target", "disease": "disease"}.get(kind)
    if not entity or not raw:
        return {}
    ck = (entity, raw.strip().lower())
    if ck in _CANON_CACHE:
        return _CANON_CACHE[ck]

    meta: dict[str, Any] = {}
    try:
        import resolver  # local module; optional at import time
        r = resolver.resolve_one(raw, entity)
        if r.resolved:
            ontology = ("Ensembl" if entity == "target"
                        else r.canonical_id.split("_", 1)[0] or "EFO")
            meta = {"canonical_symbol": r.canonical_name,
                    "canonical_id": r.canonical_id, "ontology": ontology}
            if r.canonical_name.lower() != raw.strip().lower():
                meta["alias_of"] = r.canonical_name
    except Exception:  # noqa: BLE001 — resolution is best-effort enrichment
        meta = {}
    _CANON_CACHE[ck] = meta
    return meta


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


# A clinical-trial registry id (ClinicalTrials.gov NCT… or EUCTR yyyy-nnnnnn-nn)
# anywhere in a ref/result should deep-link to the *actual* study record, not the
# registry homepage. These map an id → its canonical study URL.
_NCT_RE = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
_EUCTR_RE = re.compile(r"\b\d{4}-\d{6}-\d{2}\b")


def trial_deep_link(text: str) -> str:
    """Return a deep link to the actual trial record if `text` names a registry id.

    A bare ``NCT01234567`` or an EUCTR ``2020-001234-10`` resolves to the study
    page; without an id we have no specific trial to point at, so return "" and
    let the caller fall back to the registry homepage.
    """
    m = _NCT_RE.search(text or "")
    if m:
        return f"https://clinicaltrials.gov/study/{m.group(0).upper()}"
    m = _EUCTR_RE.search(text or "")
    if m:
        return (f"https://www.clinicaltrialsregister.eu/ctr-search/search"
                f"?query={m.group(0)}")
    return ""


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
    # A specific trial id deep-links to the study record, beating both a generic
    # homepage and a registry-base url already in the ref.
    trial_url = trial_deep_link(reference)
    for key, (label, url) in _SOURCE_CANON.items():
        if key in text:
            chosen = trial_url or (url_in_ref.group(0) if url_in_ref else url)
            return nid("source", label), label, chosen
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
