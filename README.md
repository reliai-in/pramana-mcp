# Pramana MCP server

mcp-name: io.github.loopg/pramana-mcp

**Decide whether a prompt or model change is safe to ship, by running it against your own
production runs.**

[Pramana](https://pypi.org/project/pramana-sdk/) is a flight recorder for AI agents. It records
every non-deterministic decision your agent makes in production, replays any past run exactly
against your changed code, and reports which decisions moved — not which sentences got reworded.

This MCP server lets an assistant read what Pramana recorded, and check a signed evidence bundle
offline. **It is read-only.** There is deliberately no tool that starts a replay or a comparison:
a sandboxed batch calls the model for real on every trace, so it spends money, and an MCP tool is
a button any assistant can press without a person deciding. Producing a comparison stays a CLI
verb behind its own confirmation gate.

## Install

Nothing to install — `uvx` fetches it on demand.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "pramana": {
      "command": "uvx",
      "args": ["pramana-mcp"],
      "env": {
        "PRAMANA_API_KEY": "<your-engineer-or-admin-api-key>"
      }
    }
  }
}
```

### Claude Code

```console
$ claude mcp add pramana --env PRAMANA_API_KEY=<your-engineer-or-admin-api-key> -- uvx pramana-mcp
```

Create a key in **Settings → API keys** at [reliai.in](https://www.reliai.in/). Use an **engineer**
or **admin** key — an auditor key deliberately never receives recorded prompts or responses, so
`get_trace` would come back empty. Self-hosting? Set `PRAMANA_API_URL` to your own API.

## Tools

### `list_traces`

List recorded AI agent runs (traces) captured by Pramana, optionally filtered by agent, status or
time range.

> *"What agent runs did we record last Tuesday?"*

```json
{ "agent": "refund-agent", "since": "2026-09-22T00:00:00Z", "limit": 20 }
```

### `get_trace`

Get one recorded agent run: its steps, model calls, tool calls with arguments, and outcome.

> *"Walk me through what the agent did in run loan-07 — which tools did it call, and with what?"*

```json
{ "trace_id": "loan-07-5a6eef" }
```

Long payloads are truncated, and the response says so rather than looking complete.

### `list_model_diffs`

List comparison runs that checked a prompt or model change against recorded production runs.

> *"Have we compared anything against production since the model upgrade?"*

```json
{ "since": "2026-09-20T00:00:00Z", "limit": 20 }
```

### `get_model_diff`

Get the findings of one comparison run: which decisions changed behaviourally, which were
cosmetic, and which runs halted.

> *"What changed when we moved to the new model last Tuesday?"*

```json
{ "diff_id": "mdr_9f2c1a", "trace_id": "loan-07-5a6eef" }
```

Returns bucket counts first, then **root findings**, then **consequent** ones — never merged. One
root cause that produced forty downstream differences is one thing to investigate, not forty.
Passing `trace_id` is optional but much faster (see *What the API could not do* below).

### `verify_bundle`

Verify a Pramana signed evidence bundle offline, with no account and no network access.

> *"Here's the evidence bundle the vendor sent. Is it intact?"*

```json
{ "bundle_path": "./bundle.json", "public_key_path": "./pramana-public-key.txt" }
```

`public_key_path` is **required**. The public key shipped inside a bundle is never used to check
that same bundle — that would defeat the point.

A pass proves the bundle has not been altered since it was signed. It does **not** prove that what
was captured was everything that happened. This is a proof of record, not a judgement of conduct.

## What the API could not do

Two tools are worse than they should be, and it is the API's fault rather than a design choice:

- **There is no account-wide endpoint for comparison runs.** They are only reachable per trace
  (`/v1/traces/{id}/model-diffs`), so `list_model_diffs` and a `get_model_diff` without `trace_id`
  walk the 20 most recent traces. A comparison against an older trace will not be found. Every
  response says so in a `notes` field rather than quietly returning a short list. The bound is 20
  rather than something larger because the walk is that many sequential round trips: measured
  against the production API, 50 took 6.0s and 20 takes 2.4s.
- **`/v1/traces` returns `agent_count`, not agent ids**, so filtering by `agent` means opening each
  trace. That filter is applied to the 20 most recent traces only, and says so.

## Limitations

These are the same limitations as the SDK. They are not softened for a registry listing.

- **You cannot import existing conversation logs.** Replay needs the execution trace, and a
  transcript does not carry one. Your corpus starts the day you instrument.
- **It reports that a decision changed, never whether the change is good.** Judging a changed
  decision is your call.
- **Sandboxing only covers tool calls you wrapped.** In a sandboxed batch the tool calls you have
  wrapped are served from the recording and never executed, and the model is called for real
  because the new model is the thing you are testing. In a plain replay, nothing leaves the
  process at all: outbound network access is blocked at the process level, below whatever HTTP
  client you use. A tool call you did **not** wrap is invisible to Pramana and will execute
  normally, once per trace — the CLI prints how many wrapped tool call sites it found before a
  batch runs, and what that means multiplied across the batch.
- Python only. No JavaScript or TypeScript SDK.
- The OpenAI and Anthropic clients are supported. Azure OpenAI and `AnthropicBedrock` are routed to
  those adapters and covered by tests; neither has been exercised against live cloud credentials.
  Raw `boto3` is not supported.
- LangChain is tested. LangGraph, CrewAI and LlamaIndex are not, and are not supported.
- No SOC 2, no penetration test, no uptime SLA, no on-premise deployment.
- **The evidence public key is not yet published at a stable URL.** `verify_bundle` runs offline
  and needs no account, but today you still obtain the key from us — which is not the same as
  independent verification, and is not claimed as such.

## Sample evidence bundles

`evidence-samples/` holds two signed bundles, a tampered copy of each, and the key that checks
them. No account, no network:

```console
$ pip install pramana-verify
$ pramana-verify evidence-samples/production-run.json \
    --pubkey evidence-samples/sample-public-key.txt
OK — 2 event(s), merkle_root=4fd442ccbf515c6018c0d7908bd1b1f9853df86894e67e8c40b5d1590f48418d

$ pramana-verify evidence-samples/production-run.TAMPERED.json \
    --pubkey evidence-samples/sample-public-key.txt
TAMPERED / INVALID:
  - payload …: content does not hash to its reference — this recorded prompt or response was tampered with
```

`evidence-samples/FORMAT.md` is the field-by-field specification. Those files are signed with a
sample key, not the key that signs real bundles.

---

[Documentation](https://www.reliai.in/docs/) · [reliai.in](https://www.reliai.in/) ·
[`pramana-sdk`](https://pypi.org/project/pramana-sdk/) ·
[`pramana-verify`](https://pypi.org/project/pramana-verify/)
