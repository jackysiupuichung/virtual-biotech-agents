#!/usr/bin/env python3
"""Generate brand graphics with Gemini 3 Pro Image ("Nano Banana 2").

Reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment (or repo .env) and
writes PNGs into this assets/ dir. Run:  python3 frontend/assets/gen.py
"""
import base64
import json
import os
import pathlib
import sys
import urllib.request

MODEL = "gemini-3-pro-image"  # Nano Banana 2
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith(("GEMINI_API_KEY=", "GOOGLE_API_KEY=")):
                    key = line.split("=", 1)[1].strip()
                    if key:
                        break
    if not key:
        sys.exit("No GEMINI_API_KEY / GOOGLE_API_KEY found in env or .env")
    return key


# Shared art direction so every asset reads as one identity.
STYLE = (
    "Visual identity for a 'Virtual Biotech CSO' — an AI multi-agent system that "
    "assesses drug-discovery targets. Deep navy background (#0a0e1a), like a dark "
    "scientific console at night. Restrained palette of emerald (#34d399), sky blue "
    "(#38bdf8), and amber (#fbbf24) used as evidence-grade signal accents only. "
    "Clean, precise, editorial — not a generic glossy 3D render, not stock-photo "
    "neon. Subtle, intentional, high craft."
)

ASSETS = {
    "hero.png": (
        "A wide hero banner. A luminous knowledge graph of a therapeutic target: "
        "labeled nodes (a protein target, a disease, a cell type, evidence sources) "
        "connected by thin glowing edges, each edge tinted emerald / sky / amber to "
        "signal evidence strength. A faint ribbon-diagram protein structure dissolves "
        "into the graph on the right. Generous negative space on the left for a "
        "headline. " + STYLE + " Aspect ratio 16:9, cinematic, no text labels baked in."
    ),
    "logo-mark.png": (
        "A minimal app icon / logomark on deep navy. A single abstract mark that fuses "
        "a molecular bond node-and-edge motif with a subtle 'eye / assessment' read — "
        "three nodes forming a triangle, edges in emerald, sky, amber, one node "
        "brighter as the focal target. Centered, lots of padding, flat and crisp, "
        "works small. " + STYLE + " Square 1:1, no text."
    ),
    "decision-card.png": (
        "An abstract decorative graphic representing a GO / NO-GO drug-target decision. "
        "A clean horizontal gauge or evidence ledger: stacked thin bars in emerald, "
        "sky, and amber representing axes of evidence (specificity, expression, "
        "tractability) resolving toward a single bright verdict marker. Diagrammatic, "
        "dashboard-like, calm. " + STYLE + " Aspect 3:2, no real text."
    ),
}


def generate(name: str, prompt: str, key: str) -> None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
    )
    body = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]}
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.load(resp)
    parts = payload["candidates"][0]["content"]["parts"]
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            out = HERE / name
            out.write_bytes(base64.b64decode(inline["data"]))
            print(f"  wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
            return
    raise RuntimeError(f"no image in response for {name}: {json.dumps(payload)[:400]}")


def main() -> None:
    key = load_key()
    only = set(sys.argv[1:])
    for name, prompt in ASSETS.items():
        if only and name not in only:
            continue
        print(f"generating {name} …")
        try:
            generate(name, prompt, key)
        except Exception as exc:  # keep going; report which failed
            print(f"  FAILED {name}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
