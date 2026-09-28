"""What this server must never do, asserted rather than trusted.

Three properties, each of which has already gone wrong somewhere in this
product's history or would be silent if it went wrong here:

1. An unknown `artifact_type` must be its own outcome, never "tampered". That
   exact confusion was a real bug in `pramana-verify` 0.0.1; it was fixed one
   layer down, and this asserts it was not reintroduced one layer up.
2. The recent-trace walk must be *bounded*. There is no account-wide
   comparison endpoint, so these tools walk traces -- an unbounded walk would
   turn one assistant question into hundreds of API requests.
3. The walk must survive a trace it cannot read. One 403 in the middle of a
   list must not take the whole answer down.
"""

from __future__ import annotations

import json

import pytest

from pramana_mcp.client import PramanaError
from pramana_mcp.server import (
    TRACE_SCAN_BUDGET,
    _guard,
    _tool_list_model_diffs,
    _tool_verify_bundle,
)


class FakeClient:
    """Counts requests, and refuses one trace in the middle of the list."""

    def __init__(self, n_traces: int, unreadable: set[str] | None = None):
        self.n_traces = n_traces
        self.unreadable = unreadable or set()
        self.trace_requests: list[str] = []

    def list_traces(self, limit: int = 20, before: str | None = None):
        return [{"trace_id": f"t{i}", "started_at_ns": 0} for i in range(min(limit, self.n_traces))]

    def model_diffs_for_trace(self, trace_id: str):
        self.trace_requests.append(trace_id)
        if trace_id in self.unreadable:
            raise PramanaError("Pramana rejected the API key (403).")
        return [{"run_id": f"mdr_{trace_id}", "change_id": "c1", "results": []}]


def test_the_recent_trace_walk_is_bounded(monkeypatch):
    """1000 traces available, and the walk must still stop at the budget."""
    fake = FakeClient(n_traces=1000)
    monkeypatch.setattr("pramana_mcp.server.PramanaClient", lambda *a, **k: fake)

    out = _tool_list_model_diffs({"limit": 100})

    assert len(fake.trace_requests) <= TRACE_SCAN_BUDGET, (
        f"walked {len(fake.trace_requests)} traces; the budget is {TRACE_SCAN_BUDGET}"
    )
    assert str(TRACE_SCAN_BUDGET) in " ".join(out["notes"]), (
        "the bound must be disclosed in the response, not just enforced silently"
    )


def test_a_trace_that_cannot_be_read_does_not_sink_the_whole_answer(monkeypatch):
    fake = FakeClient(n_traces=5, unreadable={"t2"})
    monkeypatch.setattr("pramana_mcp.server.PramanaClient", lambda *a, **k: fake)

    out = _tool_list_model_diffs({"limit": 100})

    assert out["count"] == 4, "the four readable traces must still come back"
    assert "mdr_t2" not in json.dumps(out)


@pytest.mark.parametrize(
    "mutation,expected_in_detail",
    [
        ({"artifact_type": "quarterly_compliance_pack"}, "unrecognised artifact_type"),
        ({"format_version": 99}, "format_version 99"),
    ],
)
def test_a_bundle_this_verifier_does_not_understand_is_never_called_tampered(
    tmp_path, mutation, expected_in_detail
):
    """ "I do not understand this file" and "this file was altered" are
    different facts, and telling an auditor the second when the first is true
    is the worst output this tool could produce. `pramana-verify` 0.0.1 shipped
    with exactly that confusion; this keeps it from coming back a layer up."""
    bundle = tmp_path / "b.json"
    bundle.write_text(json.dumps({"artifact_type": "model_diff_comparison", **mutation}))
    key = tmp_path / "k.txt"
    key.write_text("not-used-we-never-get-that-far")

    out = _guard(_tool_verify_bundle, {"bundle_path": str(bundle), "public_key_path": str(key)})

    assert out["verdict"] == "UNSUPPORTED"
    assert expected_in_detail in out["detail"]
    assert "tamper" not in json.dumps(out).lower(), (
        "an unsupported bundle must never be described with the word 'tampered'"
    )
