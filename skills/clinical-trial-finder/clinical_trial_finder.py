#!/usr/bin/env python
"""clinical-trial-finder — prior-trials/outcomes data-acquisition skill.

For a therapeutic target (optionally + disease), query the **live
ClinicalTrials.gov API v2** (public, no key) and return a deduplicated list of
trials, each carrying its **NCT id** and a **deep link to the actual study
record** (``https://clinicaltrials.gov/study/NCT…``) — not the registry
homepage. This is what lets downstream citations point at the specific trial.

Reproducible (public REST API, stdlib only), not page scraping. ``--demo``
returns a cached real-shaped response offline (no network), with real NCT ids so
the deep-link path is exercised identically to a live run.

This is the *clinical-precedent* front-end: it answers "what prior trials and
outcomes exist for this target?", complementing the structured-database skills
(Open Targets, openFDA) and the literature front-end (lit-synthesizer).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_NAME = "clinical-trial-finder"
VERSION = "0.1.0"
API_URL = "https://clinicaltrials.gov/api/v2/studies"
STUDY_BASE = "https://clinicaltrials.gov/study/"
DISCLAIMER = (
    "ClawBio is a research and educational tool. It is not a medical device and "
    "does not provide clinical diagnoses. Consult a healthcare professional before "
    "making any medical decisions."
)
EVIDENCE_NOTE = (
    "Trial records are registry metadata — registration status and design, not "
    "peer-reviewed outcomes. Treat each as a precedent to verify against its study "
    "record, not as an established result."
)


# --------------------------------------------------------------------------- #
# ClinicalTrials.gov API v2 (public, no key)
# --------------------------------------------------------------------------- #
def _get(url: str, timeout: int = 60) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _study_to_trial(study: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one API study record into {nct, title, status, phase, url}."""
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    nct = ident.get("nctId")
    if not nct:
        return None
    phases = ps.get("designModule", {}).get("phases", []) or []
    return {
        "nct": nct,
        "title": ident.get("briefTitle", ""),
        "status": ps.get("statusModule", {}).get("overallStatus", ""),
        "phase": ", ".join(phases),
        # the deep link to the ACTUAL study record — the whole point of this skill
        "url": f"{STUDY_BASE}{nct}",
    }


def fetch_trials(target: str, page_size: int = 10) -> dict[str, Any]:
    """Query the live API for trials matching the target and return deep-linked rows."""
    params = urllib.parse.urlencode({
        "query.term": target,
        "pageSize": page_size,
        "fields": "NCTId,BriefTitle,OverallStatus,Phase",
    })
    data = _get(f"{API_URL}?{params}") or {}
    trials: list[dict[str, Any]] = []
    seen: set[str] = set()
    for study in data.get("studies", []) or []:
        t = _study_to_trial(study)
        if t and t["nct"] not in seen:
            seen.add(t["nct"])
            trials.append(t)
    return {"target": target, "trials": trials, "n_trials": len(trials),
            # a representative study record as the row-level source url
            "source": trials[0]["url"] if trials else "https://clinicaltrials.gov/"}


# --------------------------------------------------------------------------- #
# Demo (offline; cached real-shaped response, real NCT ids)
# --------------------------------------------------------------------------- #
def build_demo() -> dict[str, Any]:
    """Cached illustrative trial list for B7-H3 (CD276); offline, real NCT ids."""
    trials = [
        {"nct": "NCT04145622", "title": "Ifinatamab deruxtecan (I-DXd) in advanced solid tumors",
         "status": "RECRUITING", "phase": "PHASE1, PHASE2",
         "url": f"{STUDY_BASE}NCT04145622"},
        {"nct": "NCT05276609", "title": "HS-20093 (B7-H3 ADC) in advanced solid tumors",
         "status": "RECRUITING", "phase": "PHASE1",
         "url": f"{STUDY_BASE}NCT05276609"},
    ]
    return {"target": "B7-H3 (CD276)", "trials": trials, "n_trials": len(trials),
            "source": trials[0]["url"], "_demo": True}


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_report(res: dict[str, Any], out_dir: Path, demo: bool) -> Path:
    L = [f"# Clinical-trial precedent — {res['target']}", ""]
    if demo:
        L += ["> **Demo:** cached illustrative trial list for B7-H3 (offline). Not a live query.", ""]
    L += [f"> {EVIDENCE_NOTE}", ""]
    trials = res.get("trials", [])
    if not trials:
        L += ["_No trials found._", ""]
    for t in trials:
        meta = " · ".join(b for b in (t.get("phase"), t.get("status")) if b)
        suffix = f" ({meta})" if meta else ""
        L.append(f"- **{t['nct']}** — {t['title']}{suffix} ([study record]({t['url']}))")
    L += ["", "---", f"*{DISCLAIMER}*", ""]
    p = out_dir / "report.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def _write_reproducibility(repro_dir: Path, argv, output_files):
    repro_dir.mkdir(parents=True, exist_ok=True)
    (repro_dir / "commands.sh").write_text(
        "#!/usr/bin/env bash\n# Command used to produce this trial list\n"
        "python clinical_trial_finder.py " + " ".join(argv) + "\n"
    )
    import platform

    (repro_dir / "environment.yml").write_text(
        f"name: {SKILL_NAME}\nchannels:\n  - conda-forge\n  - nodefaults\n"
        f"dependencies:\n  - python={platform.python_version()}\n"
        "  # ClinicalTrials.gov API v2 via stdlib urllib; no extra packages required\n"
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
        prog="clinical_trial_finder.py",
        description="Live ClinicalTrials.gov API v2 query for a therapeutic target; "
        "returns trials deep-linked by NCT id.",
    )
    p.add_argument("--target", type=str, default=None,
                   help="Target (optionally + disease), e.g. 'B7-H3 in lung cancer'")
    p.add_argument("--page-size", type=int, default=10, help="Max trials to return (default 10)")
    p.add_argument("--demo", action="store_true", help="Offline cached trial list (no network)")
    p.add_argument("--output", "--out", dest="out", type=str, default="./output",
                   help="Output directory (--output is the ClawBio runner convention)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.demo:
        res = build_demo()
    elif args.target:
        res = fetch_trials(args.target, args.page_size)
    else:
        raise SystemExit("provide --target, or use --demo")

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(
        {"skill": SKILL_NAME, "version": VERSION, "demo": bool(args.demo),
         "note": EVIDENCE_NOTE, **res, "disclaimer": DISCLAIMER}, indent=2))
    report_path = write_report(res, out_dir, demo=bool(args.demo))
    _write_reproducibility(out_dir / "reproducibility", argv, [result_path, report_path])

    print(json.dumps({"skill": SKILL_NAME, "target": res["target"],
                      "n_trials": res.get("n_trials", 0),
                      "result": result_path.name, "report": report_path.name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
