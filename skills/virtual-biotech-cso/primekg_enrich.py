#!/usr/bin/env python3
"""primekg_enrich.py — propagate curated PrimeKG relations into the evidence graph.

The run's evidence graph (kg.py) is built from what the scientist agents fetched.
PrimeKG — the ~3M-edge curated biomedical knowledge graph bound server-side in
Prometheux as the ``kg_csv`` datasource (see the live-integration notes) — holds
*curated* relationships the agents never queried. This module closes that gap:

    for every PAIR of run-graph entity nodes that BOTH resolve to a PrimeKG node,
    ask the engine whether PrimeKG records a relation between them; if so, add a
    **provenance-distinct corroborating edge** (prov="primekg") to the graph.

Design decisions (deliberate, see the task discussion):

  * **Context-only, never scored.** A PrimeKG edge is curated-DB corroboration, not
    the run's own derived evidence. It carries no ``axis`` and is NOT graded, so the
    Prometheux decision layer (which scores graded *evidence* rows on the four axes)
    is untouched — the verdict logic never sees these edges. They enrich the *graph*
    a scientist reads, not the go/no-go arithmetic.
  * **Resolution-gated.** Only nodes carrying a resolved ``canonical_symbol`` (targets
    → e.g. CD276, diseases → a MONDO name) are eligible — PrimeKG joins on names.
    CellType / Tissue / Trial nodes have no PrimeKG key, so those pairs are skipped.
  * **One batched query, not N.** All eligible names go into a single Vadalog query
    filtered to that name set, so enrichment is one round-trip regardless of pair count.
  * **Guarded / additive.** No ``PMTX_TOKEN`` (or the SDK / compute machine absent) →
    returns ``[]`` and the run is unaffected. Never fabricates a relation.

The PrimeKG query is injectable (``query_fn``) so the pairing + edge logic is fully
testable offline; the default ``query_fn`` is the live JarvisPy path.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Iterable

# A PrimeKG relation row, normalized: (x_name, relation, display_relation, y_name,
# x_type, y_type). Names are PrimeKG canonical names (gene symbol / MONDO disease).
PrimeKGRel = tuple

QueryFn = Callable[[list[str]], list[PrimeKGRel]]

_PX_PROJECT = "virtual_biotech"
# PrimeKG node types we surface as graph entities. PrimeKG uses gene/protein for
# targets and disease for diseases; the rest (drug, pathway, …) ride along if a
# resolved node happens to match, but we only *seed* the query with target/disease.
_KIND_TO_PRIMEKG_TYPE = {"Target": "gene/protein", "Disease": "disease"}


def _canon_name(node: dict[str, Any]) -> str | None:
    """The PrimeKG-joinable name for a node, or None if it isn't resolved.

    PrimeKG joins on names: targets by approved gene symbol (CD276), diseases by
    MONDO name. ``canonical_symbol`` is set by kg.canonical_entity via the resolver;
    without it we have no reliable key and skip the node (never guess from a label)."""
    sym = node.get("canonical_symbol")
    if sym and node.get("kind") in _KIND_TO_PRIMEKG_TYPE:
        return str(sym)
    return None


def _eligible(nodes: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map PrimeKG name → run node, for the resolved target/disease entity nodes."""
    out: dict[str, dict[str, Any]] = {}
    for n in nodes:
        name = _canon_name(n)
        if name:
            out[name] = n
    return out


def _vada_query(names: list[str]) -> str:
    """A Vadalog program: PrimeKG edges where BOTH endpoints are in ``names``.

    Reads the server-side ``kg_csv`` bind (12 capitalized columns) and emits
    ``primekg_rel(X_name, Relation, Display_relation, Y_name, X_type, Y_type)`` only
    for rows whose two endpoint names are both in the run's resolved-name set — so
    the result is exactly the curated relations between the run's own entities."""
    # quote + escape each name for the Vadalog string literal membership test
    quoted = ", ".join('"' + n.replace('"', '\\"') + '"' for n in sorted(set(names)))
    return (
        '@bind("kg_csv","csv useHeaders=\'true\'","disk/","kg.csv").\n'
        "primekg_rel(Xn, Rel, Disp, Yn, Xt, Yt) :-\n"
        "    kg_csv(Rel, Disp, _, _, Xt, Xn, _, _, _, Yt, Yn, _),\n"
        f"    Xn in [{quoted}], Yn in [{quoted}].\n"
        "@output(\"primekg_rel\").\n"
    )


def _live_query(names: list[str]) -> list[PrimeKGRel]:
    """Default query_fn: run the membership query on the hosted JarvisPy engine.

    Mirrors prometheux_reason._reason_prometheux's project→concept→run→fetch dance
    (and its verified gotchas: JARVISPY_URL override, persist_outputs=True, nested
    result shape). Any failure raises so the caller degrades to no enrichment."""
    import prometheux_chain as px  # optional dependency
    import prometheux_reason as pr  # reuse the verified row normalizer

    url = os.environ.get("JARVISPY_URL")
    if url:
        px.config.set("JARVISPY_URL", url)
    project_id = px.save_project(project_name=_PX_PROJECT)
    concept = "primekg_enrich"
    px.save_concept(project_id, definition=_vada_query(names),
                    output_predicate="primekg_rel", concept_name=concept,
                    existing_name=concept)
    px.run_concept(project_id, concept, persist_outputs=True)
    rows = px.fetch_results(project_id, output_predicate="primekg_rel", page_size=1000)
    return pr._normalize_px_rows(rows)


def enrich(graph, run_id: str, *, query_fn: QueryFn | None = None,
           prefer: str = "auto") -> list[dict[str, Any]]:
    """Add PrimeKG corroborating edges between the run's resolved entity nodes.

    Returns the list of edge dicts upserted (each as kg.upsert_edge returns), so the
    caller can stream them to the UI. Empty when enrichment can't or shouldn't run:

      * ``prefer="local"`` or (``prefer="auto"`` and no ``PMTX_TOKEN``) → [] (no-op),
      * fewer than two resolved entity nodes → [] (nothing to relate),
      * the live query fails / SDK absent / no compute machine → [] (degrade),
      * PrimeKG records no relation between any eligible pair → [].

    Never fabricates: an edge is added only for a relation PrimeKG actually returns,
    tagged ``prov="primekg"`` and carrying NO axis/grade so the decision layer ignores
    it. ``query_fn`` is injectable for testing; the default is the live JarvisPy path.
    """
    want = prefer == "prometheux" or (prefer == "auto" and os.environ.get("PMTX_TOKEN"))
    if not (want or query_fn is not None):
        return []
    by_name = _eligible(graph.nodes.values())
    if len(by_name) < 2:
        return []

    qf = query_fn or _live_query
    try:
        rels = qf(list(by_name.keys()))
    except Exception:  # noqa: BLE001 — degrade, never fabricate
        return []

    added: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rels:
        # tolerate the (Xn, Rel, Disp, Yn, Xt, Yt) shape; be permissive on extras
        if len(row) < 4:
            continue
        xn, rel, disp, yn = str(row[0]), str(row[1]), str(row[2]), str(row[3])
        sx, ty = by_name.get(xn), by_name.get(yn)
        if not sx or not ty or sx["id"] == ty["id"]:
            continue  # both endpoints must be the run's own resolved entities
        etype = _rel_type(disp or rel)
        key = (sx["id"], etype, ty["id"])
        if key in seen:
            continue
        seen.add(key)
        edge = graph.upsert_edge(
            sx["id"], ty["id"], etype,
            # NO axis / grade → invisible to the decision layer (context-only).
            prov="primekg", source="PrimeKG", primekg=True,
            relation=disp or rel,
            url="https://github.com/mims-harvard/PrimeKG",
            ref=f"PrimeKG: {xn} —{disp or rel}→ {yn}",
            conf=0.6, run=run_id)
        added.append(edge)
    return added


def _rel_type(display_relation: str) -> str:
    """Map a PrimeKG display relation to an UPPER_SNAKE graph edge type.

    PrimeKG display relations are short lowercase phrases (e.g. "associated with",
    "target", "parent-child"); normalize to the graph's edge-type convention while
    keeping the original phrase on the edge's ``relation`` field for display."""
    s = (display_relation or "primekg_rel").strip().lower()
    s = s.replace("-", " ").replace("/", " ")
    token = "_".join(s.split()) or "primekg_rel"
    return f"PRIMEKG_{token.upper()}"
