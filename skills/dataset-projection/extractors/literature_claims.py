#!/usr/bin/env python3
"""literature_claims.py — project documents (papers/abstracts) into claim facts.

The "mixed / documents" case of the projection contract. A document is opaque to
Vadalog, so it never enters Prometheux; we extract its *relational claims* — gene
→ disease / cell-type associations — into the same :class:`Fact` shape, keeping a
DOI/PMID provenance pointer back to the source.

Two extraction backends, same output:

  * ``--llm``  — an Anthropic-Claude extractor (the latest model, claude-opus-4-8):
                 one structured tool-call per document returning typed claims. Used
                 when ``ANTHROPIC_API_KEY`` is set and ``--llm`` is passed.
  * default    — a dependency-free dictionary matcher over a small biomedical
                 lexicon (genes x relation-cues x diseases/cell-types). Deterministic,
                 offline, good enough to demo the contract and to fall back to.

Input is a JSONL of documents: ``{"id": "...", "text": "...", "doi"/"pmid": "..."}``.
A tiny sample is shipped at ``../examples/abstracts.sample.jsonl``.

    python3 literature_claims.py --in ../examples/abstracts.sample.jsonl
    ANTHROPIC_API_KEY=... python3 literature_claims.py --in docs.jsonl --llm
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from facts import Fact, node_id, write_facts  # noqa: E402

DATASET = "literature"
DEFAULT_IN = Path(__file__).resolve().parent.parent / "examples" / "abstracts.sample.jsonl"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "out" / "literature_claims.facts.csv"

# A small lexicon for the offline matcher. Genes/diseases are matched as whole
# words; a relation cue between a gene and a disease in the same sentence yields a
# GENETIC_LINK claim. Deliberately tiny — the LLM backend is for real coverage.
GENES = ["CD276", "B7-H3", "EGFR", "KRAS", "MET", "MS4A1", "CD3D", "FCGR3A", "NKG7", "CD14"]
DISEASES = {
    "lung adenocarcinoma": "luad", "luad": "luad",
    "non-small cell lung": "nsclc", "nsclc": "nsclc",
    "melanoma": "melanoma", "glioblastoma": "glioblastoma",
    "colorectal cancer": "colorectal-cancer",
}
CUES = ["associated with", "linked to", "overexpressed in", "mutated in",
        "implicated in", "drives", "promotes", "expressed in"]


def _offline_claims(doc: dict) -> list[Fact]:
    text = doc.get("text", "")
    prov = doc.get("doi") or doc.get("pmid") or doc.get("id") or "unknown"
    facts: list[Fact] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        low = sent.lower()
        if not any(c in low for c in CUES):
            continue
        genes_here = [g for g in GENES if re.search(rf"\b{re.escape(g)}\b", sent, re.I)]
        dis_here = {slug for name, slug in DISEASES.items() if name in low}
        for g in genes_here:
            for slug in dis_here:
                facts.append(Fact(
                    subject=node_id("target", g),
                    relation="GENETIC_LINK",
                    object=node_id("disease", slug),
                    value=sent.strip()[:160],
                    confidence=0.6,           # asserted-in-text, not quantitative
                    source_dataset=DATASET,
                    provenance=f"{prov}",
                ))
    return facts


_CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gene": {"type": "string"},
                    "disease": {"type": "string"},
                    "relation": {"type": "string",
                                 "enum": ["GENETIC_LINK", "EXPRESSED_IN"]},
                    "evidence_sentence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["gene", "disease", "relation", "evidence_sentence",
                             "confidence"],
            },
        }
    },
    "required": ["claims"],
}


def _llm_claims(doc: dict) -> list[Fact]:
    import anthropic  # optional dep; only needed for --llm

    client = anthropic.Anthropic()
    prov = doc.get("doi") or doc.get("pmid") or doc.get("id") or "unknown"
    msg = client.messages.create(
        model="claude-opus-4-8",       # latest, most capable extractor
        max_tokens=2048,
        tools=[{"name": "emit_claims",
                "description": "Emit gene-disease/cell-type relational claims stated "
                               "in the document. Only claims the text actually asserts.",
                "input_schema": _CLAIM_SCHEMA}],
        tool_choice={"type": "tool", "name": "emit_claims"},
        messages=[{"role": "user",
                   "content": "Extract relational biomedical claims from this "
                              f"document as tool input.\n\n{doc.get('text','')}"}],
    )
    block = next((b for b in msg.content if getattr(b, "type", "") == "tool_use"), None)
    claims = (block.input.get("claims", []) if block else [])
    facts: list[Fact] = []
    for c in claims:
        facts.append(Fact(
            subject=node_id("target", c["gene"]),
            relation=c["relation"],
            object=node_id("disease", c["disease"]),
            value=c["evidence_sentence"][:160],
            confidence=max(0.0, min(1.0, float(c["confidence"]))),
            source_dataset=DATASET,
            provenance=str(prov),
        ))
    return facts


def extract(docs_path: Path, use_llm: bool) -> list[Fact]:
    backend = _llm_claims if use_llm else _offline_claims
    facts: list[Fact] = []
    seen: set[tuple] = set()
    for line in docs_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        for f in backend(json.loads(line)):
            key = (f.subject, f.relation, f.object)
            if key not in seen:        # dedup identical claims across docs
                seen.add(key)
                facts.append(f)
    return facts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="inp", type=Path, default=DEFAULT_IN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--llm", action="store_true",
                   help="use the Claude extractor (needs ANTHROPIC_API_KEY)")
    args = p.parse_args(argv)

    if args.llm and not os.environ.get("ANTHROPIC_API_KEY"):
        print("--llm requires ANTHROPIC_API_KEY; falling back to offline matcher")
        args.llm = False
    facts = extract(args.inp, args.llm)
    n = write_facts(facts, args.out)
    print(f"projected {n} literature claims from {args.inp.name} "
          f"({'llm' if args.llm else 'offline'}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
