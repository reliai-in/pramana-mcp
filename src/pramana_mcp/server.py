"""The Pramana MCP server — read-only, plus offline bundle verification.

Five tools, all of them reads. There is deliberately no tool that starts a
replay or a model diff: a sandboxed batch calls the model for real on every
trace, so it spends money, and an MCP tool is a button any assistant can press
without a person deciding. Producing a comparison stays a CLI verb behind its
own confirmation gate.

Every tool returns structured data. The calling model writes the prose — that
is its job, not this server's, and prose here would be a second place for a
claim to drift out of step with the code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from mcp.server import MCPServer

from pramana_mcp.client import PramanaClient, PramanaError

# An assistant will cheerfully ask for everything. These are the ceilings.
MAX_LIMIT = 100
DEFAULT_LIMIT = 20
MAX_EVENTS_PER_TRACE = 200
MAX_FIELD_CHARS = 2000
# list_model_diffs / get_model_diff have no account-wide endpoint to call (see
# README, "What the API could not do"), so they walk recent traces. This caps
# that walk so one question cannot turn into hundreds of requests.
#
# 20, not 50, and the number was measured rather than picked. The walk is
# 1 + N *sequential* round trips, and `urllib` opens a fresh TCP+TLS connection
# for each one, so wall time is round-trip time multiplied by the budget and
# nothing else. Median RTT to https://www.reliai.in/api measured 0.114s on
# 28 Sept 2026, which put a 50-trace walk at 6.0s -- long enough that an
# assistant looks hung. 20 lands at ~2.4s. The cost is a narrower search
# window, which is why every response states the number rather than quietly
# returning a short list. An account-wide endpoint removes this whole
# trade-off; it is on the roadmap and not built.
TRACE_SCAN_BUDGET = 20

mcp = MCPServer(
    name="pramana",
    instructions=(
        "Read recorded AI agent runs captured by Pramana, and the findings of comparison runs that "
        "checked a prompt or model change against those recordings. Read-only: nothing here starts "
        "a replay or a comparison, because a comparison calls the model for real and costs money."
    ),
)


def _truncate(value: Any) -> Any:
    """Large payloads are cut, and the cut is stated in the data rather than
    left for the reader to infer from a value that merely looks complete."""
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"… [truncated, {len(value)} chars total]"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


def _iso_to_ns(value: str) -> int | None:
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return int(dt.timestamp() * 1_000_000_000)


# --- handlers (tested directly; the decorators below are the transport) ------


def _tool_list_traces(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
    client = PramanaClient()
    traces = client.list_traces(limit=limit)

    agent, since = args.get("agent"), args.get("since")
    filtered, notes = traces, []
    if since:
        cutoff = _iso_to_ns(since)
        if cutoff is None:
            notes.append(f"could not parse since={since!r} as ISO-8601; time filter not applied")
        else:
            filtered = [t for t in filtered if int(t.get("started_at_ns", 0)) >= cutoff]
    if agent:
        # /v1/traces returns agent_count, never the ids, so the only honest way
        # to filter by agent is to open each trace. Bounded, and disclosed.
        kept = []
        for t in filtered[:TRACE_SCAN_BUDGET]:
            try:
                events = client.get_trace(t["trace_id"]).get("events", [])
            except PramanaError:
                continue
            if any(e.get("agent_id") == agent for e in events):
                kept.append(t)
        if len(filtered) > TRACE_SCAN_BUDGET:
            notes.append(f"agent filter applied to the {TRACE_SCAN_BUDGET} most recent traces only")
        filtered = kept

    out: dict[str, Any] = {"traces": filtered, "count": len(filtered)}
    if notes:
        out["notes"] = notes
    return out


def _tool_get_trace(args: dict[str, Any]) -> dict[str, Any]:
    trace_id = args["trace_id"]
    data = PramanaClient().get_trace(trace_id)
    events = data.get("events", [])
    shown = events[:MAX_EVENTS_PER_TRACE]
    out: dict[str, Any] = {
        "trace_id": data.get("trace_id", trace_id),
        "event_count": len(events),
        "events": [_truncate(e) for e in shown],
    }
    if len(events) > MAX_EVENTS_PER_TRACE:
        out["truncated"] = (
            f"showing the first {MAX_EVENTS_PER_TRACE} of {len(events)} events; "
            f"long field values are also truncated at {MAX_FIELD_CHARS} characters"
        )
    return out


def _iter_recent_diff_runs(
    client: PramanaClient, budget: int = TRACE_SCAN_BUDGET
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (trace_id, run) over recent traces.

    There is no account-wide model-diffs endpoint — only
    /v1/traces/{id}/model-diffs — so this walks recent traces. Bounded by
    `budget`, and every caller reports the bound in its own output.
    """
    for t in client.list_traces(limit=budget):
        trace_id = t["trace_id"]
        try:
            runs = client.model_diffs_for_trace(trace_id)
        except PramanaError:
            continue
        for run in runs or []:
            yield trace_id, run


def _tool_list_model_diffs(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
    since_ns = _iso_to_ns(args["since"]) if args.get("since") else None
    client = PramanaClient()

    found: list[dict[str, Any]] = []
    for trace_id, run in _iter_recent_diff_runs(client):
        if since_ns is not None and run.get("created_at"):
            ns = _iso_to_ns(str(run["created_at"]))
            if ns is not None and ns < since_ns:
                continue
        summary = {
            "diff_id": run.get("run_id"),
            "trace_id": trace_id,
            "created_at": run.get("created_at"),
            "change_id": run.get("change_id"),
            "compared_model": run.get("compared_model"),
            "is_control": run.get("is_control"),
            "call_sites_compared": len(run.get("results", []) or []),
        }
        found.append({k: v for k, v in summary.items() if v not in (None, "")})
        if len(found) >= limit:
            break

    return {
        "model_diffs": found,
        "count": len(found),
        "notes": [
            (
                f"Pramana has no account-wide comparison endpoint, so this searched the "
                f"{TRACE_SCAN_BUDGET} most recent traces. A comparison against an older trace "
                f"will not appear here."
            )
        ],
    }


_ROOT_CLASSIFICATIONS = ("BEHAVIOURAL", "ERRORED", "HALTED")


def _tool_get_model_diff(args: dict[str, Any]) -> dict[str, Any]:
    diff_id = args["diff_id"]
    client = PramanaClient()

    run, trace_id = None, args.get("trace_id")
    if trace_id:
        for candidate in client.model_diffs_for_trace(trace_id) or []:
            if candidate.get("run_id") == diff_id:
                run = candidate
                break
    else:
        for tid, candidate in _iter_recent_diff_runs(client):
            if candidate.get("run_id") == diff_id:
                run, trace_id = candidate, tid
                break

    if run is None:
        raise PramanaError(
            f"No comparison run {diff_id!r} found"
            + (
                f" on trace {trace_id!r}."
                if args.get("trace_id")
                else f" in the {TRACE_SCAN_BUDGET} most recent traces. Pass trace_id to look it up directly."
            )
        )

    results = run.get("results", []) or []
    buckets: dict[str, int] = {}
    for r in results:
        # is_consequent is checked first: a consequent finding is counted once,
        # as consequent, never also under its own classification.
        if r.get("is_consequent"):
            key = "superseded" if r.get("superseded") else "consequent"
        else:
            key = str(r.get("classification", "") or "unclassified").lower()
            key = {"no_change": "unchanged"}.get(key, key)
        buckets[key] = buckets.get(key, 0) + 1

    def _finding(r: dict[str, Any]) -> dict[str, Any]:
        f = {
            "call_site_id": r.get("call_site_id"),
            "call_site_ordinal": r.get("call_site_ordinal"),
            "classification": r.get("classification"),
            "label": r.get("label"),
            "detail": r.get("detail"),
            "model": r.get("model"),
        }
        truncated = _truncate({k: v for k, v in f.items() if v not in (None, "")})
        assert isinstance(truncated, dict)  # _truncate preserves the container type
        return truncated

    roots = [
        _finding(r)
        for r in results
        if not r.get("is_consequent") and r.get("classification") in _ROOT_CLASSIFICATIONS
    ]
    consequent = [_finding(r) for r in results if r.get("is_consequent")]

    return {
        "diff_id": diff_id,
        "trace_id": trace_id,
        "change_id": run.get("change_id") or None,
        "is_control_run": bool(run.get("is_control")),
        "call_sites_compared": len(results),
        "bucket_counts": buckets,
        # Root and consequent are never merged: one root cause that produced
        # forty downstream differences is one thing to investigate, not forty.
        "root_findings": roots,
        "consequent_findings": consequent,
        "reading_this": (
            "root_findings are the causes. consequent_findings diverged only because an earlier "
            "step on the same run diverged, and are listed separately for that reason."
        ),
    }


_VERIFY_MEANING = (
    "A pass proves the bundle has not been altered since it was signed. It does NOT prove that what "
    "was captured was everything that happened. This is a proof of record, not a judgement of conduct."
)


def _tool_verify_bundle(args: dict[str, Any]) -> dict[str, Any]:
    import json
    import pathlib

    from pramana_verify.verifier import UnsupportedBundleError, verify_evidence_artifact

    bundle_path = pathlib.Path(args["bundle_path"]).expanduser()
    key_path = pathlib.Path(args["public_key_path"]).expanduser()
    if not bundle_path.is_file():
        raise PramanaError(f"No bundle file at {bundle_path}.")
    if not key_path.is_file():
        raise PramanaError(
            f"No public key file at {key_path}. This argument is required — the key shipped inside "
            f"a bundle is never used to check that same bundle."
        )
    try:
        bundle = json.loads(bundle_path.read_text())
    except json.JSONDecodeError as e:
        raise PramanaError(f"{bundle_path} is not valid JSON: {e}") from None

    try:
        result = verify_evidence_artifact(bundle, key_path.read_text().strip())
    except UnsupportedBundleError as e:
        return {
            "verdict": "UNSUPPORTED",
            "detail": str(e),
            "action": "Upgrade the verifier: pip install -U pramana-verify",
            "what_a_pass_proves": _VERIFY_MEANING,
        }
    return {
        "verdict": "VALID" if result.ok else "TAMPERED_OR_INVALID",
        "errors": list(result.errors) if not result.ok else [],
        "artifact_type": bundle.get("artifact_type", "production_run"),
        "checked_with_public_key_from": str(key_path),
        "what_a_pass_proves": _VERIFY_MEANING,
    }


def _guard(handler: Callable[[dict[str, Any]], dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    """Errors come back as data, not as a transport failure — an assistant
    relaying a bare status code helps nobody, and the person reading it cannot
    see this process's environment."""
    try:
        return handler({k: v for k, v in args.items() if v is not None})
    except PramanaError as e:
        return {"error": str(e)}
    except KeyError as e:
        return {"error": f"missing required argument: {e}"}


# --- tools ------------------------------------------------------------------


@mcp.tool(
    name="list_traces",
    description=(
        "List recorded AI agent runs (traces) captured by Pramana, optionally filtered by agent, "
        "status or time range."
    ),
)
def list_traces(
    agent: str | None = None, since: str | None = None, limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """agent: only runs involving this agent id. since: ISO-8601, e.g. 2026-09-22T00:00:00Z.
    limit: default 20, max 100."""
    return _guard(_tool_list_traces, {"agent": agent, "since": since, "limit": limit})


@mcp.tool(
    name="get_trace",
    description=(
        "Get one recorded agent run: its steps, model calls, tool calls with arguments, and outcome."
    ),
)
def get_trace(trace_id: str) -> dict[str, Any]:
    """Large payloads are truncated, and the response says that they were."""
    return _guard(_tool_get_trace, {"trace_id": trace_id})


@mcp.tool(
    name="list_model_diffs",
    description=(
        "List comparison runs that checked a prompt or model change against recorded production runs."
    ),
)
def list_model_diffs(limit: int = DEFAULT_LIMIT, since: str | None = None) -> dict[str, Any]:
    """limit: default 20, max 100. since: ISO-8601."""
    return _guard(_tool_list_model_diffs, {"limit": limit, "since": since})


@mcp.tool(
    name="get_model_diff",
    description=(
        "Get the findings of one comparison run: which decisions changed behaviourally, which were "
        "cosmetic, and which runs halted."
    ),
)
def get_model_diff(diff_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """diff_id: from list_model_diffs. trace_id: optional but much faster — without it the server
    searches recent traces, because Pramana has no account-wide comparison endpoint."""
    return _guard(_tool_get_model_diff, {"diff_id": diff_id, "trace_id": trace_id})


@mcp.tool(
    name="verify_bundle",
    description=("Verify a Pramana signed evidence bundle offline, with no account and no network access."),
)
def verify_bundle(bundle_path: str, public_key_path: str) -> dict[str, Any]:
    """public_key_path is required: the key shipped inside a bundle is never used to check that
    same bundle."""
    return _guard(_tool_verify_bundle, {"bundle_path": bundle_path, "public_key_path": public_key_path})


# Names kept stable for the tests, which drive the handlers directly.
_HANDLERS = {
    "list_traces": _tool_list_traces,
    "get_trace": _tool_get_trace,
    "list_model_diffs": _tool_list_model_diffs,
    "get_model_diff": _tool_get_model_diff,
    "verify_bundle": _tool_verify_bundle,
}


async def run() -> None:
    await mcp.run_stdio_async()
