#!/usr/bin/env python
"""runners.py — a pluggable agent runner for the virtual-biotech-cso harness.

The CSO skill (``cso.py``) makes no LLM call: it packages three reasoning roles
(Chief of Staff, Scientific Reviewer, CSO synthesis) as delegation stubs. This
module supplies the *driving agent* those stubs assume — but deliberately NOT
tied to any one vendor or to Claude Code being installed. A single entry point,
``run_agent(prompt, context, schema)``, is backed by an auto-selected provider:

  - ``AnthropicRunner`` — the ``anthropic`` SDK + ``ANTHROPIC_API_KEY`` (primary).
  - ``OpenAIRunner``    — an OpenAI-compatible client (``OPENAI_API_KEY``,
                          optional ``OPENAI_BASE_URL``) using JSON mode, so the
                          harness runs from Cursor or any other environment.

If no backend is configured, ``select_runner`` returns a ``StubRunner`` that
raises ``NoBackendError`` — the harness catches it and falls back to cso.py's
honest delegation stub rather than fabricating a result.

JSON contract: every role returns a JSON object matching the ``schema`` passed
in (the shape is harvested from the role's prompt file). Runners instruct the
model to return JSON only, parse it, and on a parse failure retry once before
giving up (the harness then stubs that role).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol


class NoBackendError(RuntimeError):
    """Raised when no agent backend is configured (no API key present)."""


class AgentError(RuntimeError):
    """Raised when a configured backend fails to return usable JSON."""


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object out of a model response.

    Tolerates ```json fenced blocks and leading/trailing prose. Raises
    ``AgentError`` if no object can be parsed.
    """
    if not text or not text.strip():
        raise AgentError("empty response")
    # Strip a ```json … ``` fence if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1).strip() if fence else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} span.
    start = candidate.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise AgentError("no JSON object found in response")


def _compose(prompt: str, context: str, schema: dict[str, Any]) -> str:
    """Build the user message: role prompt + injected context + strict-JSON ask."""
    return (
        f"{prompt}\n\n"
        f"## Context for this run\n{context}\n\n"
        "## Output requirement\n"
        "Return ONLY a single valid JSON object — no prose, no markdown fence — "
        "matching exactly this schema (keys and value types):\n"
        f"{json.dumps(schema, indent=2)}\n"
    )


SYSTEM = (
    "You are a division agent inside a virtual-biotech multi-agent system. "
    "You return rigorous, evidence-grounded JSON and never fabricate data. "
    "If evidence is absent, say so in the JSON rather than inventing it."
)


class Runner(Protocol):
    name: str
    model: str

    def run(self, prompt: str, context: str, schema: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicRunner:
    """Primary backend — Anthropic Messages API. Portable to any environment."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str | None = None) -> None:
        import anthropic  # imported lazily so the dep is optional

        self.name = "anthropic"
        self.model = model or os.environ.get("VBIO_MODEL") or self.DEFAULT_MODEL
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def run(self, prompt: str, context: str, schema: dict[str, Any]) -> dict[str, Any]:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": _compose(prompt, context, schema)}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _extract_json(text)


class OpenAIRunner:
    """OpenAI-compatible backend — for Cursor users / other keys. JSON mode."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI  # lazy optional dep

        self.name = "openai"
        self.model = model or os.environ.get("VBIO_MODEL") or self.DEFAULT_MODEL
        # base_url honours OPENAI_BASE_URL for OpenAI-compatible gateways.
        base_url = os.environ.get("OPENAI_BASE_URL")
        self._client = OpenAI(base_url=base_url) if base_url else OpenAI()

    def run(self, prompt: str, context: str, schema: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _compose(prompt, context, schema)},
            ],
        )
        return _extract_json(resp.choices[0].message.content or "")


class StubRunner:
    """No backend configured — every call raises so the harness stubs the role."""

    name = "stub"
    model = "none"

    def run(self, prompt: str, context: str, schema: dict[str, Any]) -> dict[str, Any]:
        raise NoBackendError(
            "No agent backend configured. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) "
            "to run the live multi-agent loop; running stub-only for now."
        )


def select_runner(backend: str = "auto", model: str | None = None) -> Runner:
    """Choose a runner by explicit ``backend`` or by which API key is present.

    Order for ``auto``: Anthropic, then OpenAI, then a no-op StubRunner. The
    StubRunner is always returned (never None) so callers have a uniform object;
    it raises NoBackendError on use.
    """
    backend = (backend or "auto").lower()
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if backend == "anthropic":
        return AnthropicRunner(model)
    if backend == "openai":
        return OpenAIRunner(model)
    if backend not in ("auto",):
        raise ValueError(f"unknown backend {backend!r} (use auto|anthropic|openai)")

    if has_anthropic:
        return AnthropicRunner(model)
    if has_openai:
        return OpenAIRunner(model)
    return StubRunner()


def run_with_retry(runner: Runner, prompt: str, context: str,
                   schema: dict[str, Any], retries: int = 1) -> dict[str, Any]:
    """Call ``runner`` with one retry on a JSON parse/agent error.

    NoBackendError is not retried — it propagates so the harness can stub the
    role immediately.
    """
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            result = runner.run(prompt, context, schema)
            if not isinstance(result, dict):
                raise AgentError(f"runner returned {type(result).__name__}, expected dict")
            return result
        except NoBackendError:
            raise
        except Exception as exc:  # noqa: BLE001 — provider SDKs vary
            last = exc
    raise AgentError(f"agent failed after {retries + 1} attempts: {last}")
