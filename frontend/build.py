#!/usr/bin/env python3
"""Recompile frontend/app.jsx -> app.js (the data is now served live by server.py).

Fully offline: uses the vendored Babel (vendor/babel.js) via headless Chrome, so no
Node toolchain is required. Run after editing app.jsx.

    python3 frontend/build.py
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def compile_jsx() -> None:
    src = (HERE / "app.jsx").read_text()
    harness = (
        '<!DOCTYPE html><html><head><script src="./vendor/babel.js"></script></head>'
        '<body><pre id="out"></pre><script>var SRC=' + json.dumps(src) + ';'
        'try{var o=Babel.transform(SRC,{presets:[["react",{runtime:"classic"}]]}).code;'
        'document.getElementById("out").textContent=o;}'
        'catch(e){document.getElementById("out").textContent="ERROR "+e.message;}'
        '</script></body></html>'
    )
    with tempfile.NamedTemporaryFile("w", dir=HERE, suffix="_compile.html", delete=False) as fh:
        fh.write(harness)
        tmp = pathlib.Path(fh.name)
    try:
        dom = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=8000", "--dump-dom", f"file://{tmp}"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    finally:
        tmp.unlink(missing_ok=True)
    m = re.search(r'<pre id="out">(.*)</pre>', dom, re.S)
    import html as _html
    code = _html.unescape(m.group(1)) if m else ""
    if not code or code.startswith("ERROR"):
        sys.exit(f"  compile FAILED: {code[:200] or 'empty output'}")
    (HERE / "app.js").write_text(code)
    print(f"  app.js   <- compiled app.jsx ({len(code)} chars)")


if __name__ == "__main__":
    print("building frontend...")
    compile_jsx()
    print("done. start the server: python3 frontend/server.py")
