# Sample evidence bundles

Two signed Pramana evidence bundles, a tampered copy of each, and the public key that checks
them. Nothing here needs a Pramana account, and the check runs offline.

The point is that you don't have to take our word for it. Run the check, watch it pass. Then
open a tampered copy, see the single value we changed, and watch the same command fail.

## Check them yourself

```console
$ pip install pramana-verify
$ pramana-verify production-run.json --pubkey sample-public-key.txt
OK — 2 event(s), merkle_root=4fd442ccbf515c6018c0d7908bd1b1f9853df86894e67e8c40b5d1590f48418d
```

```console
$ pramana-verify model-diff-comparison.json --pubkey sample-public-key.txt
OK — MODEL-DIFF COMPARISON (not a production record), change_id='refund-policy-2026-Q3', 2 call site(s), 1 behavioural · 1 cosmetic
```

Now the tampered copies. Each is the original with the smallest edit that would actually be
worth making:

```console
$ pramana-verify production-run.TAMPERED.json --pubkey sample-public-key.txt
TAMPERED / INVALID:
  - payload 535f17dac0ea...: content does not hash to its reference — this recorded prompt or response was tampered with

$ pramana-verify model-diff-comparison.TAMPERED.json --pubkey sample-public-key.txt
TAMPERED / INVALID:
  - content_hash does not match this bundle's own content — it was edited after signing
```

It exits `0` on a pass and `1` on a failure, so it works as a CI step.

```console
$ diff <(python3 -m json.tool production-run.json) \
       <(python3 -m json.tool production-run.TAMPERED.json)
```

One line — the refunded amount, `12.0` changed to `1.0`. Someone making a refund look smaller
than it was.

The comparison bundle's diff is **three** lines, and the extra two are the interesting part:

```
-        "behavioural": 1,
+        "behavioural": 0,
-        "unchanged": 0,
+        "unchanged": 1,
```

Hiding the behavioural finding means also moving that call site into `unchanged`, because the
buckets are a strict partition and have to sum to the sites compared. A forger who only zeroed
`behavioural` would leave counts that visibly do not add up. So this is the *careful* version of
the forgery — the one that survives a human skim — and the signature rejects it just the same.

## What the sample shows

A refund agent. A customer's order arrived nine days late, and policy refunds shipping on a
late delivery when the item still arrived. The recorded run refunds the **shipping fee, 12.00**.

`model-diff-comparison.json` is what happened when the same recorded run was replayed against a
changed prompt (`change_id: refund-policy-2026-Q3`). The new prompt refunds the **whole order,
249.00**. Two call sites were compared, and the tool that moves money was one of them:

```
[COSMETIC]    the model call     different wording
[BEHAVIOURAL] issue_refund       amount_inr: 12.0 -> 249.0
```

One of those is a rewrite. The other is money. Separating them is the job.

**Read what the bundle itself asserts, though, not the summary above.** That two-line listing is
what the CLI printed when the comparison ran. What the *signed artifact* contains is this:

```json
"bucket_counts": { "behavioural": 1, "cosmetic": 1, "unchanged": 0, … },
"per_trace": { "refund-SAMPLE-4417-…": {
    "call_sites_compared": 2,
    "control_run_present": true,
    "control_confirmations": [ {
        "call_site_id": "4a2db46ad7a8b9de64c2f34e75364420",
        "classification": "BEHAVIOURAL",
        "control_verdict": "confirmed" } ] } }
```

So the bundle attests **how many** call sites landed in each outcome, **which** call site the
behavioural finding was at, and that a **control run** — the original prompt replayed a second
time — came back clean, making that finding a real consequence of the change rather than the
model being non-deterministic. It does **not** carry the human-readable "what moved" string. The
tool name `issue_refund` and the text `amount_inr: 12.0 -> 249.0` are not in this file; they live
in the CLI output and the dashboard. Grep the file for `249` and you will not find it.

That is a real limit of the current format and it is stated here rather than glossed: a reviewer
holding only this bundle knows that one decision changed and where, but has to go back to the
run to see what it changed to.

## Read this before quoting the check

**A pass proves the bundle has not been altered since it was signed. It does not prove that what
was captured was everything that happened.** Pramana records the calls you instrumented; a call
you never wrapped leaves no trace, and no signature can attest to something that was never
recorded. This is a proof of record, not a judgement of conduct.

**These files are signed with a sample key, not the key that signs real bundles.** That key's
only job is signing the files in this directory. `sample-public-key.txt` checks these four files
and nothing else — a real Pramana bundle will not verify against it, and that is correct. We do
not yet publish the production public key at a stable URL, so checking a real bundle still means
obtaining its key from us. That is not the same as independent verification and is not claimed
as such.

**`pramana-verify` is a separate package from the SDK.** It has no network code and no account
concept. Its source ships in the sdist on PyPI, so you can read exactly what the check does
rather than trusting this description of it.

## Files

| File | |
|---|---|
| `production-run.json` | A recorded run. Claim: *this happened, in this order, unmodified.* |
| `model-diff-comparison.json` | A comparison. Claim: *this comparison ran and concluded this.* Weaker, and different in kind — see `FORMAT.md`. |
| `production-run.TAMPERED.json` | The first file with one value changed. |
| `model-diff-comparison.TAMPERED.json` | The second file with one value changed. |
| `sample-public-key.txt` | Checks the four files above. Nothing else. |
| `FORMAT.md` | Field-by-field, and what each artifact type does and does not assert. |

These files are generated by the same builders that produce customer bundles, from a real
recorded trace on a real database — not written by hand. The tenant is `sample-tenant` and every
identifier in them is synthetic.
