# Sample evidence bundles

Two signed Pramana evidence bundles, a tampered copy of each, and the public key that checks
them. Nothing here needs a Pramana account, and the check runs offline.

The point is that you don't have to take our word for it. Run the check, watch it pass. Then
open a tampered copy, see the single value we changed, and watch the same command fail.

**The key is `sample-public-key.txt`, in this directory — not the production key.** These samples
are signed by a separate, sample-only key. Pramana's production deployment publishes its own key at
`https://reliai.in/api/.well-known/pramana-evidence-public-key`, and that one will **not** verify
these files, by design: demo artifacts and real customer bundles should not be indistinguishable by
signer. Use `sample-public-key.txt` here, and a deployment's own key for a bundle from it.

## Check them yourself

**Python 3.9 or newer.** That floor is deliberately low: this is the one tool we hand to people
whose environment we do not control, and it needs nothing modern — it reads JSON and checks a
signature. Tested on 3.9, 3.10, 3.11, 3.12 and 3.13, by installing from PyPI and verifying these
exact files.

```console
$ pip install 'pramana-verify>=0.0.6'
$ pramana-verify production-run.json --pubkey sample-public-key.txt
OK — 2 event(s), merkle_root=6ec957f1ec1443e56c01bab5440df06cfbdd6bbd67c9e8c35398d02d1a840a3a
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

It exits `0` on a pass and `1` on a failure, so it works as a CI step. Two other codes exist, and
both mean *"not checked"* rather than *"failed"*: `2` if your `pramana-verify` is too old to read
the bundle's format, and `3` if the key you supplied is not the key the bundle was signed with —

```console
$ pramana-verify production-run.json --pubkey 15c9f0c15e8c15c5f55fec6c0357052234e82dfa01eb0e87a613777348806983
KEY MISMATCH — bundle NOT checked: this bundle was signed by key 20b3d73eb4546cd8… but the key supplied was 15c9f0c15e8c15c5…. Nothing is wrong with the bundle — it has not been checked at all, because it was not signed by the key you asked about. Pramana's published sample bundles are signed by a separate sample-only key (sample-public-key.txt, beside the samples), NOT by a production deployment's key served at /.well-known/pramana-evidence-public-key. Verify a sample with the sample key, and a bundle from your own deployment with that deployment's key.
```

That is what you get for pointing the production key at a sample. It needs
`pramana-verify >= 0.0.6`; before that, this exact mistake was reported as `TAMPERED / INVALID`,
which was wrong and is fixed.

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

**What the bundle itself asserts**, which since `format_version: 3` includes what actually
changed:

```json
"bucket_counts": { "behavioural": 1, "cosmetic": 1, "unchanged": 0, … },
"per_trace": { "refund-SAMPLE-4417-…": {
    "call_sites_compared": 2,
    "control_run_present": true,
    "control_confirmations": [ { "call_site_id": "c5b93d0be1ef674f33a9e0bce66dffc8", "classification": "BEHAVIOURAL",
                                 "control_verdict": "confirmed" } ],
    "findings": [
      { "classification": "COSMETIC",    "label": "\"Order SAMPLE-4417 arrived nine days late…\"",
        "detail": "choices: […12.00…] -> […249.00…]" },
      { "classification": "BEHAVIOURAL", "label": "issue_refund",
        "detail": "amount_inr: 12.0 -> 249.0" } ] } }
```

So the bundle attests how many call sites landed in each outcome, **which** ones, **what changed
at each**, and that a control run — the original prompt replayed a second time — came back clean,
making that finding a consequence of the change rather than the model being non-deterministic.

Until 3 October 2026 it carried only the counts and the call site id. A reviewer holding the
bundle knew one decision had changed and where, and had to go back to the run to see what it
changed to — which is the second question an auditor asks, so the artifact was answering one of
two. `findings` is what closed that.

Only **root** findings appear. A finding that diverged because an earlier one did is counted in
`bucket_counts` but not listed: one root cause that produced forty downstream differences is one
thing to investigate, not forty.

## Read this before quoting the check

**A pass proves the bundle has not been altered since it was signed. It does not prove that what
was captured was everything that happened.** Pramana records the calls you instrumented; a call
you never wrapped leaves no trace, and no signature can attest to something that was never
recorded. This is a proof of record, not a judgement of conduct.

**These files are signed with a sample key, not the key that signs real bundles.** That key's
only job is signing the files in this directory. `sample-public-key.txt` checks these four files
and nothing else — a real Pramana bundle will not verify against it, and that is correct. A
production deployment publishes its own key at
`https://reliai.in/api/.well-known/pramana-evidence-public-key`, no account needed, so checking a
real bundle no longer means asking us for a key.

One limit worth stating plainly: **a bundle carries no key id.** It records
`signer_public_key_hex`, which this tool uses only to tell you *which* key signed it when you
supply the wrong one — never to decide that a signature is good. With one key and no rotation that
changes nothing today, but it means an already-issued bundle has nothing in it to pin against if
the key ever changes.

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
