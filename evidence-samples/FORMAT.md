# Evidence bundle format

Two artifact types. They are deliberately **not** interchangeable, and the difference is the
most important thing on this page.

| | `production_run` | `model_diff_comparison` |
|---|---|---|
| Claim | *This happened, in this order, and has not been modified.* | *This comparison ran, under this configuration, and concluded this.* |
| Contains | real recorded events and their payloads | findings about a replay; **never a live production event** |
| Strength | the strong claim | weaker, and different in kind |
| `artifact_type` | `"production_run"` | `"model_diff_comparison"` |

A comparison bundle carries a `disclaimer` field stating this in full, in the bundle itself — so
a reader who opens the raw JSON and skims sees it among the first few keys, rather than having
to know this page exists.

## Reading the first two fields first

Every bundle opens with `artifact_type` and `format_version`, and a verifier reads them **before
it checks anything else**. A bundle it does not recognise is refused as unsupported, with its
own message — never reported as tampered.

That distinction matters more than it looks. *"I do not understand this file"* and *"this file
was altered"* are different facts, and telling an auditor the second when the first is true is
the worst output a verifier could produce. `pramana-verify` 0.0.1 conflated them; it was fixed,
and there are tests whose only job is keeping the word "tampered" out of that response.

Both types are currently at `format_version: 1`. A bundle with a higher version than your
verifier understands is unsupported, not invalid — upgrade with `pip install -U pramana-verify`.

## `production_run`

| Field | Meaning |
|---|---|
| `bundle_id` | `evb_…` — identifies this bundle. |
| `tenant_id`, `trace_id` | whose run, and which run. |
| `from_seq`, `to_seq` | the slice of the trace this bundle covers. A bundle can attest to part of a run; these say which part. |
| `events` | the recorded events, in chain order. Each carries its own `this_hash` and the `prev_hash` of the one before it. |
| `blobs` | the payloads the events reference, keyed by `payload_ref`. An event names its payload by content hash, so a payload that does not hash to its own reference is detected. |
| `merkle_root` | computed over the events' hashes. |
| `signature_hex` | over a header binding `tenant_id`, `trace_id`, `from_seq`, `to_seq` and `merkle_root` together. |
| `signer_public_key_hex` | the public half of the signing key — **present for reference, never used to check the bundle it arrives in.** See below. |
| `code_version` | free text supplied at export; a label, not an attested fact. |

## `model_diff_comparison`

| Field | Meaning |
|---|---|
| `bundle_id` | `mdb_…`. |
| `change_id` | **a label supplied by the caller.** The bundle attests the comparison and its results, not the contents of the change the label names. Nothing ties the label to any particular edit. |
| `signed_at` | when the bundle was signed — distinct from when the comparison ran. |
| `comparison_run_started_at` / `…_completed_at` | when the comparison actually ran. |
| `traces_submitted` / `traces_included` / `traces_excluded` | these reconcile by construction: every submitted trace lands in exactly one of `trace_ids` or `excluded_traces`, never both, never neither. They exist so a reviewer never computes the wrong denominator. |
| `trace_ids` | the traces this bundle's counts actually attest to. |
| `excluded_traces` | traces dropped, each **with its reason**. A bad trace is named and disclosed, not silently omitted, and not allowed to void the whole bundle. |
| `models_observed` | every model name seen across the comparison. A fact about what ran — *not* a claim about which model the change targeted. |
| `exclude_keys` | fields the comparison was told to ignore. |
| `classifier_version` | which classifier produced the outcomes. |
| `redactor_active` | whether a redactor was filtering payloads during capture. |
| `mode` | how the replay was run — see below. |
| `bucket_counts` | a strict partition: every compared call site lands in exactly one bucket, and they sum to the sites compared. |
| `per_trace` | the same counts per trace, plus `control_confirmations`, `control_run_present`, `halted`. |
| `instrumentation_coverage_disclosure` | states in the artifact that coverage is limited to instrumented calls. |
| `content_hash` | over the canonical form of every field above. |
| `signature_hex` | over `content_hash`. |

### `bucket_counts` — the ten names

`behavioural`, `consequent`, `superseded`, `cosmetic`, `unchanged`, `errored`, `unstable`,
`reordered`, `halted`, `unclassified`.

`behavioural` is a decision that changed. `cosmetic` is wording that changed while the decision
did not. `consequent` diverged only because an earlier step on the same run diverged — one root
cause that produced forty downstream differences is one thing to investigate, not forty, and
keeping them in separate buckets is what makes that true in the artifact and not just in a
dashboard. `unstable` is a finding the control run reproduced, i.e. the old model wandering on
its own rather than your change.

### `mode`

```json
"mode": { "clock_and_rng": "frozen_replayed_from_recording", "tools": "live_tools" }
```

`tools` is the field to read. **The sample here says `live_tools` because it was produced from a
single trace, and a single trace always runs with live tools.** A batch of two or more traces is
sandboxed by default, and says so here. Read this field rather than assuming; the bundle is the
place that knows.

In a sandboxed batch, the tool calls that were **wrapped** are served from the recording and
never executed. The model is still called for real — the new model is the thing being tested. A
tool call that was never wrapped is invisible to Pramana and runs normally, which is what
`instrumentation_coverage_disclosure` is telling you.

## The public key inside the bundle is not the one that checks it

Every bundle carries `signer_public_key_hex`. `pramana-verify` **requires** `--pubkey` and never
falls back to that field, because a bundle that vouches for itself vouches for nothing: anyone
who altered the contents could re-sign with their own key and write their own public key into
the field. The key has to reach you by some path other than the file being checked.

For the samples in this directory that path is `sample-public-key.txt`, sitting beside them in a
public repository — which is exactly as trustworthy as this repository, and no more. For a real
bundle it means obtaining the key from us out of band.

## What a pass proves

That the bundle has not been altered since it was signed.

**Not** that what was captured was everything that happened. Pramana records the calls that were
instrumented. A call nobody wrapped leaves no trace, and no signature can attest to something
that was never recorded. A pass is a proof of record, not a judgement of conduct.
