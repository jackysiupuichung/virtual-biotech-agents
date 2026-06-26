#!/usr/bin/env python3
"""run_live.py — run the cross-dataset join on the hosted Prometheux engine.

Joins the projected single-cell facts against the live PrimeKG ``kg_csv`` bind and
fetches ``marker_disease_link`` — a conclusion that exists from neither source
alone. Verified live 2026-06-26: 7 strong markers → 32 disease links.

**Why the facts are INLINED as ground atoms, not bound as a second CSV.** The
JarvisPy SDK (``prometheux-chain==0.2.14``) has NO file-upload endpoint — every
client method is projects/sources/concepts *metadata*. ``connect_sources`` only
registers a *database connection* (host/port) and 500s on a local CSV ("Failed to
check database connection"). PrimeKG's ``kg.csv`` was placed on the engine's
``disk/`` out-of-band via the web app's file upload. So until the CSV is uploaded
that way (or an upload endpoint exists), the projected facts are inlined into the
Vadalog program as ``cell_marker(...)`` ground atoms. This is fine at projection
scale — the whole point is that the *facts* are a small, joinable set. For a large
projected set, upload the CSV in the web app and switch to the ``bind.vada`` form.

Needs an ACTIVE compute machine (free-tier idle-suspends → 400 NO_ACTIVE_COMPUTE)
and ``PMTX_TOKEN`` + ``JARVISPY_URL`` in the env. Failures are surfaced.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import prometheux_chain as px

HERE = Path(__file__).resolve().parent
PROJECT_ID = "2862a5285d8"   # virtual_biotech (see prometheux-live-integration memory)
OUTPUT = "marker_disease_link"
STRONG = 0.8


def _gene_label(node_id: str) -> str:
    """gene:cd3d -> CD3D  (match PrimeKG's canonical X_name casing)."""
    return node_id.split(":", 1)[-1].upper().replace("-", "")


def main() -> int:
    url = os.environ.get("JARVISPY_URL")
    if url:
        px.config.set("JARVISPY_URL", url)

    facts_csv = HERE / "out" / "projected_facts.csv"
    if not facts_csv.exists():
        facts_csv = HERE / "out" / "pbmc3k_expression.facts.csv"
    rows = list(csv.DictReader(facts_csv.open()))
    atoms = [f'cell_marker("{_gene_label(r["subject"])}","'
             f'{r["object"].split(":",1)[-1]}",{r["confidence"]}).'
             for r in rows
             if r["relation"] == "EXPRESSED_IN" and float(r["confidence"]) >= STRONG]
    print(f"[1/4] {len(atoms)} strong markers inlined from {facts_csv.name}")

    vada = (
        '@bind("kg_csv","csv useHeaders=\'true\'","disk/","kg.csv").\n'
        + "\n".join(atoms) + "\n"
        'marker_disease_link(G,C,D) :- cell_marker(G,C,_), '
        'kg_csv(_,_,_,_,"gene/protein",G,_,_,_,"disease",D,_).\n'
        f'@output("{OUTPUT}").\n'
    )
    px.save_concept(PROJECT_ID, definition=vada, output_predicate=OUTPUT,
                    concept_name=OUTPUT, existing_name=OUTPUT)
    print(f"[2/4] concept {OUTPUT} saved")
    px.run_concept(PROJECT_ID, OUTPUT, persist_outputs=True)
    print("[3/4] run complete; fetching ...")
    res = px.fetch_results(PROJECT_ID, output_predicate=OUTPUT, page_size=1000)
    facts = res.get("results", {}).get("facts", []) if isinstance(res, dict) else res
    total = res.get("pagination", {}).get("total_count") if isinstance(res, dict) else len(facts)
    print(f"[4/4] {OUTPUT}: {total} cross-dataset link(s)")
    for r in facts[:25]:
        print(f"   • {r[0]} (strong marker of {r[1]}) — PrimeKG links to disease: {r[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
