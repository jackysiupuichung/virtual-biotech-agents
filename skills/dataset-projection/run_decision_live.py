#!/usr/bin/env python3
"""run_decision_live.py — join prior CSO run verdicts against PrimeKG, live.

Takes the decision facts written by ``extractors/run_decision.py`` (a finished
run's final-overall tier + per-axis subreport conclusions) and reasons over them
on the hosted Prometheux engine alongside PrimeKG (``kg_csv``):

  * ``prior_verdict``            — the run's tier per target (echoed back from the facts);
  * ``verdict_disease_context``  — a previously-decided target joined to the diseases
                                   PrimeKG ties it to (a conclusion neither has alone).

**Facts are INLINED as ground atoms, not bound as a CSV** — same reason as
run_live.py: prometheux-chain 0.2.14 has no file-upload endpoint, and decision
facts are tiny (~5 rows/run), so inlining is the right tool. The ``bind.vada`` CSV
form is the large-scale path (verdicts uploaded via the web app's ``disk/``).

The PrimeKG join is on the canonical gene symbol: targets are projected as
``target:<symbol>``, so we inline the upper-cased symbol (matching kg_csv's X_name).

Needs an ACTIVE compute machine + ``PMTX_TOKEN`` / ``JARVISPY_URL`` in env.
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import prometheux_chain as px

HERE = Path(__file__).resolve().parent
PROJECT_ID = "2862a5285d8"   # virtual_biotech (see prometheux-live-integration memory)
OUTPUT = "verdict_disease_context"


def _sym(target_node: str) -> str:
    """target:cd276 -> CD276  (match PrimeKG's canonical X_name casing)."""
    return target_node.split(":", 1)[-1].upper().replace("-", "")


def _esc(s: str) -> str:
    """Escape a string literal for a Vadalog ground atom."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", type=Path, default=HERE / "out" / "run_decision.facts.csv",
                    help="decision facts CSV from run_decision.py (default out/run_decision.facts.csv)")
    args = ap.parse_args(argv)

    url = os.environ.get("JARVISPY_URL")
    if url:
        px.config.set("JARVISPY_URL", url)

    if not args.facts.exists():
        raise SystemExit(f"no decision facts at {args.facts} — run extractors/run_decision.py first")
    rows = [r for r in csv.DictReader(args.facts.open()) if r["relation"] == "DECIDED"]
    if not rows:
        raise SystemExit(f"{args.facts} has no DECIDED rows")

    # Inline one verdict atom per target, with the symbol pre-cased for the kg_csv join:
    #   run_verdict("CD276","GO (score 3.0/4.0): ...").
    atoms = [f'run_verdict("{_sym(r["subject"])}","{_esc(r["value"])}").' for r in rows]
    print(f"[1/4] {len(atoms)} prior verdict(s) inlined from {args.facts.name}")

    vada = (
        '@bind("kg_csv","csv useHeaders=\'true\'","disk/","kg.csv").\n'
        + "\n".join(atoms) + "\n"
        # echo the verdicts back, and join each to PrimeKG's gene/protein->disease edges.
        'prior_verdict(Sym,T) :- run_verdict(Sym,T).\n'
        'verdict_disease_context(Sym,T,D) :- run_verdict(Sym,T), '
        'kg_csv(_,_,_,_,"gene/protein",Sym,_,_,_,"disease",D,_).\n'
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
    print(f"[4/4] {OUTPUT}: {total} verdict×disease link(s)")
    for r in facts[:25]:
        print(f"   • {r[0]} [{r[1][:40]}] — PrimeKG disease: {r[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
