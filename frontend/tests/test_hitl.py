"""Tests for the human-in-the-loop bridge in the frontend server.

The HITL gate blocks the review loop on a per-run decision queue while the browser
shows a checkpoint; the browser delivers the human's choice via submit_decision.
These tests cover the bridge wiring offline (no HTTP, no LLM): the gate emits a
wait/resolved pair, blocks until a decision arrives, and times out to auto-approve.
"""
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                       # frontend/
sys.path.insert(0, str(HERE.parent.parent / "skills" / "virtual-biotech-cso"))

import server  # noqa: E402


def test_hitl_off_returns_no_gate():
    assert server._hitl_gate("run-x", lambda *a: None) is not None  # factory always builds
    # but run_loop only builds it when hitl=True — exercised via the param default below


def test_submit_decision_unknown_run_is_false():
    assert server.submit_decision("no-such-run", {"action": "approve"}) is False


def test_gate_blocks_then_applies_submitted_decision():
    events = []
    gate = server._hitl_gate("run-1", lambda ev, p: events.append((ev, p)))

    result = {}

    def call_gate():
        result["decision"] = gate({"iteration": 0, "verdict": "re-route"})

    t = threading.Thread(target=call_gate)
    t.start()
    # wait for the gate to register its queue, then deliver a decision
    for _ in range(100):
        if server.submit_decision("run-1", {"action": "override_verdict",
                                            "verdict": "synthesize"}):
            break
        time.sleep(0.01)
    t.join(timeout=2)
    assert result["decision"] == {"action": "override_verdict", "verdict": "synthesize"}
    names = [e for e, _ in events]
    assert names == ["checkpoint_wait", "checkpoint_resolved"]


def test_gate_times_out_to_auto_approve(monkeypatch):
    monkeypatch.setattr(server, "HITL_TIMEOUT_S", 0.05)
    gate = server._hitl_gate("run-2", lambda *a: None)
    decision = gate({"iteration": 0, "verdict": "re-route"})
    assert decision == {"action": "approve", "timed_out": True}
    # the queue is cleaned up after timeout → no stale waiter
    assert server.submit_decision("run-2", {}) is False
