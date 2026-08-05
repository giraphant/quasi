# Workflow Friction Reduction Design

**Status:** Approved in conversation on 2026-08-05.

## Goal

Remove three observed sources of avoidable Book/Paper orchestration friction without weakening chapter provenance, adding retries, or creating another state machine.

## Acquire outcome contract

Paper and Book Acquire receipts currently describe one successful effect twice:

- `write_state`: `written|not_written|unknown`; and
- `terminal.disposition`: `created|reused`.

The host rejects a complete receipt unless the two model-produced fields form one exact pair. This is not independent durability evidence and caused a verified existing PDF to stop on `reused + written`.

Keep `write_state` as the single effect claim and remove `terminal.disposition` from Paper and Book Acquire receipts. A complete receipt requires:

- an exact allowed output and format;
- `identity_verified:true`;
- `write_state` equal to `written` or `not_written`; and
- the existing Book year-evidence predicate where applicable.

`write_state:unknown`, a blocked/failed terminal, and a missing Agent receipt continue to stop. `source:"existing_file"` remains the successful reuse testimony; no runtime consumer needs a second `reused` label.

## Chapter page provenance and legacy repair

Do not relax the page-range invariant. Every canonical chapter row has either:

- integer `start_page` and `end_page` with `1 <= start_page <= end_page`; or
- both values null when the producer has no page provenance.

The current status/TypeScript boundary enforces this, while the extractor's durable manifest validator accepts a one-sided range. Move the pure page-pair rule to the schema-owned chapter-manifest contract and consume it from both the status observer and extractor validator.

An existing manifest that is ownership-safe but fails only this page-pair rule is recoverable input, not a reusable generation. Under the existing output lock and source/request fingerprint checks, `quasi-extract split` rebuilds the complete staged chapter generation with the current producer, which writes paired ranges, then publishes through the existing manifest-last transaction. Unsafe filenames, missing/changed owned chapter files, source mismatch, or other invalid manifest structure remain blocked; no manual manifest edit or generic cleanup path is added.

## Skill decision envelope

The outer Skill gets one generic machine-facing wrapper, not one literal per gate:

```python
user_decision = {
    "material_key": gate.material_key,
    "operation": gate.operation,
    "value": gate_owned_value,
}
```

`gate_owned_value` is still assembled only from the returned gate testimony plus the user's one choice. The Skill must not inspect a generated Workflow bundle to rediscover this wrapper. Existing per-gate value rules remain prose because their owning parsers and returned gates define the exact fields.

## Explicit non-goals

- No automatic writer retry or replay.
- No new cursor, receipt log, recovery state, or status loop.
- No relaxed or inferred chapter end pages.
- No per-stage or per-gate literal catalogue in the Skill.
- No special case for *The Explanation of Social Action*.

## Verification

- Red/green coverage proves `reused + written` no longer has a second disposition field to contradict, while `write_state:unknown` still cannot complete.
- Red/green extractor coverage proves a same-request, ownership-safe legacy manifest with an unpaired range is rebuilt into paired ranges rather than reused.
- Existing status tests continue rejecting unpaired ranges before repair.
- A semantic Skill test checks the generic wrapper has exactly `material_key`, `operation`, and `value`, without pinning prose.
- Workflow build/type checks and the complete test suite pass.
