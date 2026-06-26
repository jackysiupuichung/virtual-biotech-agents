#!/usr/bin/env python
"""lit-synthesizer — a ClawBio literature/landscape data-acquisition skill.

For a therapeutic target (optionally + disease), run **agentic web search** via
the Tavily Search API across three angles and return a cited, deduplicated
snippet bundle:

  - recent_literature   : recent papers / preprints on the target (+ disease)
  - competitive_landscape: other programs, trial readouts, deals on the same target
  - safety_signals      : recent safety findings / discontinuations not yet in FAERS

API-backed and reproducible (Tavily Search API), **not page scraping**. Every
returned item carries its source URL so downstream synthesis can cite it.
`--demo` returns a cached real-shaped response offline (no network, no key).

This is the *current-evidence* front-end: it answers "what does the recent web
say about this target right now?", complementing the structured-database skills
(Open Targets, openFDA, ClinicalTrials.gov) with timely, citable context. It is
the natural re-route target when the Scientific Reviewer flags missing recent
literature, competitive, or emerging-safety context.

Requires TAVILY_API_KEY for live mode; --demo needs neither network nor key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "lit-synthesizer"
VERSION = "0.1.0"
TAVILY_URL = "https://api.tavily.com/search"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)
EVIDENCE_NOTE = (
    "Web-search results are timely but unrefereed signal — recency and relevance, "
    "not peer-reviewed ground truth. Treat every item as a lead to verify against "
    "its cited source, not as an established claim."
)

# The three search angles. Each maps to a Tavily query template; {q} is the
# target (+ disease) string. Kept declarative so the angle set is auditable.
ANGLES: dict[str, str] = {
    "recent_literature": "recent research papers and preprints on {q} as a therapeutic target",
    "competitive_landscape": "clinical programs, trial readouts and deals targeting {q}",
    "safety_signals": "recent safety findings, adverse events or trial discontinuations for {q}",
}


# --------------------------------------------------------------------------- #
# Tavily Search API
# --------------------------------------------------------------------------- #
def _post(url: str, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any] | None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise SystemExit(
                "Tavily rejected the request (check TAVILY_API_KEY). Use --demo for offline mode."
            ) from e
        if e.code == 404:
            return None
        raise


def _search_angle(query: str, api_key: str, max_results: int) -> list[dict[str, Any]]:
    """One Tavily search → list of {title, url, content, score} items."""
    data = _post(TAVILY_URL, {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "topic": "general",
    })
    items = (data or {}).get("results", []) or []
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "content": (r.get("content", "") or "")[:600], "score": r.get("score")}
        for r in items if r.get("url")
    ]


def fetch_landscape(target: str, api_key: str, max_results: int = 5) -> dict[str, Any]:
    """Run all three angles for a target and dedupe items by URL across angles."""
    seen: set[str] = set()
    angles: dict[str, list[dict[str, Any]]] = {}
    for angle, template in ANGLES.items():
        items = _search_angle(template.format(q=target), api_key, max_results)
        fresh = []
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            fresh.append(it)
        angles[angle] = fresh
    return {"target": target, "angles": angles, "n_sources": len(seen)}


# --------------------------------------------------------------------------- #
# Demo (offline; cached real-shaped Tavily response)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    """Cached illustrative landscape for B7-H3 (CD276); offline, no key.

    Real-shaped Tavily output (title/url/content per item) so the offline demo
    exercises the same code path and report as a live run.
    """
    return {
        "target": "B7-H3 (CD276)",
        "angles": {
            "recent_literature": [
                {"title": "B7-H3 as an emerging immunotherapy target in solid tumors",
                 "url": "https://pubmed.ncbi.nlm.nih.gov/example-b7h3-review",
                 "content": "B7-H3 (CD276) is overexpressed across NSCLC and other solid tumors "
                            "with limited normal-tissue expression, motivating ADC and CAR-T programs.",
                 "score": 0.94},
                {"title": "Spatial heterogeneity of CD276 expression in lung adenocarcinoma",
                 "url": "https://www.biorxiv.org/content/example-cd276-spatial",
                 "content": "Single-cell and spatial data show stromal as well as malignant B7-H3 "
                            "expression, with implications for ADC bystander effects.",
                 "score": 0.89},
            ],
            "competitive_landscape": [
                {"title": "Ifinatamab deruxtecan (I-DXd): B7-H3 ADC clinical updates",
                 "url": "https://clinicaltrials.gov/example-idxd",
                 "content": "An anti-B7-H3 antibody-drug conjugate reporting responses in "
                            "small-cell lung cancer; competitive benchmark for new B7-H3 ADCs.",
                 "score": 0.91},
                {"title": "B7-H3-directed CAR-T programs entering early-phase trials",
                 "url": "https://example.com/b7h3-cart-landscape",
                 "content": "Multiple sponsors pursuing B7-H3 CAR-T; differentiation hinges on "
                            "tumor-cell vs stromal targeting and on-target/off-tumor safety.",
                 "score": 0.86},
            ],
            "safety_signals": [
                {"title": "On-target/off-tumor considerations for B7-H3 therapeutics",
                 "url": "https://example.com/b7h3-safety-note",
                 "content": "Low but non-zero B7-H3 in some normal epithelia raises on-target "
                            "off-tumor risk; payload choice and dosing mitigate the ADC liability.",
                 "score": 0.83},
            ],
        },
        "n_sources": 5,
        "_demo": True,
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
_ANGLE_TITLES = {
    "recent_literature": "Recent literature & preprints",
    "competitive_landscape": "Competitive / clinical landscape",
    "safety_signals": "Emerging safety signals",
}


def write_report(land: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# Literature & Landscape — {land['target']}", ""]
    if demo:
        L += ["> **Demo:** cached illustrative Tavily landscape for B7-H3 (offline). Not a live query.", ""]
    L += [f"> {EVIDENCE_NOTE}", ""]
    for angle, title in _ANGLE_TITLES.items():
        items = land["angles"].get(angle, [])
        L += [f"## {title}", ""]
        if not items:
            L += ["_No results._", ""]
            continue
        for it in items:
            L.append(f"- **{it['title']}** — {it['content']} ([source]({it['url']}))")
        L.append("")
    L += ["---", f"*{DISCLAIMER}*", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\n# Command used to produce this landscape\n"
        "python lit_synthesizer.py " + " ".join(argv) + "\n"
    )
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # Tavily Search API via stdlib urllib; no extra packages required\n"
    )
    lines = []
    for p in output_files:
        p = Path(p)
        if p.exists():
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (repro_dir / "checksums.sha256").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lit_synthesizer.py",
        description="Agentic web-search landscape for a therapeutic target via Tavily "
        "(recent literature + competitive landscape + safety signals).",
    )
    p.add_argument("--target", type=str, default=None,
                   help="Target (optionally + disease), e.g. 'B7-H3 in lung cancer'")
    p.add_argument("--max-results", type=int, default=5, help="Max results per angle (default 5)")
    p.add_argument("--demo", action="store_true", help="Offline cached landscape (no network, no key)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        land = build_demo()
    elif args.target:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise SystemExit("set TAVILY_API_KEY for live mode, or use --demo")
        land = fetch_landscape(args.target, api_key, args.max_results)
    else:
        raise SystemExit("provide --target, or use --demo")

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    landscape_path = out_dir / "landscape.json"
    landscape_path.write_text(json.dumps(
        {"skill": SKILL_NAME, "version": VERSION, "demo": bool(args.demo),
         "note": EVIDENCE_NOTE, **land, "disclaimer": DISCLAIMER}, indent=2))
    report_path = write_report(land, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [landscape_path, report_path])

    print(json.dumps({"skill": SKILL_NAME, "target": land["target"],
                      "n_sources": land.get("n_sources", 0),
                      "angles": {a: len(v) for a, v in land["angles"].items()},
                      "landscape": landscape_path.name, "report": report_path.name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
