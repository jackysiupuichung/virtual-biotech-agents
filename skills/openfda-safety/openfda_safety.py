#!/usr/bin/env python
"""openfda-safety — a ClawBio safety data-acquisition skill (FDA Safety Officer).

For a drug, query the **openFDA** APIs and return a post-market safety snapshot:
  - top adverse-event reaction terms + report counts (FAERS, `drug/event`)
  - the label boxed warning, if any (`drug/label`)

API-backed and reproducible (api.fda.gov), **not web scraping**. `--demo` returns
a cached real FAERS response offline (no network, no key).

This is the post-market counterpart to the structural/genetic safety in
`opentargets-target-factors`: it asks "what has actually been reported in
patients on this drug?", at the **drug** level (supply a drug that targets the
gene of interest — e.g. from clinical-trial-finder / Open Targets known drugs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "openfda-safety"
VERSION = "0.1.0"
FAERS_URL = "https://api.fda.gov/drug/event.json"
LABEL_URL = "https://api.fda.gov/drug/label.json"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)
SAFETY_NOTE = (
    "FAERS counts are spontaneous reports — they reflect reporting frequency, not "
    "incidence or causation, and are confounded by indication and reporting bias."
)


# --------------------------------------------------------------------------- #
# openFDA API (stdlib urllib — no key needed at low volume)
# --------------------------------------------------------------------------- #
def _get(url: str, params: dict[str, str], timeout: int = 60) -> dict[str, Any] | None:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:  # openFDA returns 404 when a search matches nothing
            return None
        raise


def fetch_adverse_events(drug: str, limit: int = 15) -> list[dict[str, Any]]:
    """Top FAERS reaction terms for a drug, by report count.

    Tries the structured openfda.generic_name field first, then falls back to the
    free-text medicinalproduct field.
    """
    count_field = "patient.reaction.reactionmeddrapt.exact"
    for search in (
        f'patient.drug.openfda.generic_name:"{drug}"',
        f'patient.drug.medicinalproduct:"{drug}"',
    ):
        data = _get(FAERS_URL, {"search": search, "count": count_field, "limit": str(limit)})
        if data and data.get("results"):
            return [{"reaction": r["term"], "report_count": r["count"]} for r in data["results"]]
    return []


def fetch_boxed_warning(drug: str) -> str | None:
    """The label boxed warning for a drug, if present."""
    for field in ("openfda.generic_name", "openfda.brand_name"):
        data = _get(LABEL_URL, {"search": f'{field}:"{drug}"', "limit": "1"})
        if data and data.get("results"):
            res = data["results"][0]
            bw = res.get("boxed_warning")
            if bw:
                return " ".join(bw)[:1500] if isinstance(bw, list) else str(bw)[:1500]
            return None
    return None


# --------------------------------------------------------------------------- #
# Demo (offline; cached real FAERS response)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    """Cached real openFDA snapshot for capmatinib (a MET inhibitor); offline."""
    return {
        "drug": "capmatinib",
        "adverse_events": [
            {"reaction": "DEATH", "report_count": 411},
            {"reaction": "PERIPHERAL SWELLING", "report_count": 288},
            {"reaction": "FATIGUE", "report_count": 260},
            {"reaction": "OEDEMA PERIPHERAL", "report_count": 243},
            {"reaction": "NAUSEA", "report_count": 240},
            {"reaction": "MALIGNANT NEOPLASM PROGRESSION", "report_count": 179},
            {"reaction": "DYSPNOEA", "report_count": 138},
            {"reaction": "OEDEMA", "report_count": 134},
        ],
        "boxed_warning": None,
        "_demo": True,
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_report(snap: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# openFDA Safety Snapshot — {snap['drug']}", ""]
    if demo:
        L += ["> **Demo:** cached real FAERS response for capmatinib (offline). Not a live query.", ""]
    L += [f"> {SAFETY_NOTE}", "", "## Top adverse-event reactions (FAERS)", "",
          "| Reaction | Reports |", "|---|---|"]
    for e in snap["adverse_events"]:
        L.append(f"| {e['reaction']} | {e['report_count']} |")
    if not snap["adverse_events"]:
        L.append("| (no FAERS reports matched) | — |")
    L += ["", "## Boxed warning", "", (snap.get("boxed_warning") or "_None on the openFDA label._"),
          "", "---", f"*{DISCLAIMER}*", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\n# Command used to produce this safety snapshot\n"
        "python openfda_safety.py " + " ".join(argv) + "\n"
    )
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # openFDA via stdlib urllib; no extra packages required\n"
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
        prog="openfda_safety.py",
        description="openFDA post-market safety snapshot for a drug (FAERS adverse events + boxed warning).",
    )
    p.add_argument("--drug", type=str, default=None, help="Drug name (generic or brand), e.g. capmatinib")
    p.add_argument("--limit", type=int, default=15, help="Top-N reaction terms (default 15)")
    p.add_argument("--demo", action="store_true", help="Offline cached FAERS snapshot (no network)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        snap = build_demo()
    elif args.drug:
        snap = {
            "drug": args.drug,
            "adverse_events": fetch_adverse_events(args.drug, args.limit),
            "boxed_warning": fetch_boxed_warning(args.drug),
        }
    else:
        raise SystemExit("provide --drug, or use --demo")

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safety_path = out_dir / "safety.json"
    safety_path.write_text(json.dumps(
        {"skill": SKILL_NAME, "version": VERSION, "demo": bool(args.demo),
         "note": SAFETY_NOTE, **snap, "disclaimer": DISCLAIMER}, indent=2))
    report_path = write_report(snap, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [safety_path, report_path])

    print(json.dumps({"skill": SKILL_NAME, "drug": snap["drug"],
                      "n_reactions": len(snap["adverse_events"]),
                      "top_reactions": [e["reaction"] for e in snap["adverse_events"][:5]],
                      "boxed_warning": bool(snap.get("boxed_warning")),
                      "safety": safety_path.name, "report": report_path.name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
