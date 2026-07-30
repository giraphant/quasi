# Claude Workflow native E2E evidence

Date: 2026-07-30
Scope: Claude Code side only
Repository baseline: `cfb82147de0bba9466b667202b3ab3441ead1ddf` (`main`, dirty worktree preserved)
Claude Code: `2.1.211`
Workflow: `workflows/process-material.mjs`
Native run id: `wf_a10ebf24-df4`

Snapshot note: this native run occurred immediately before the final G6 receipt-hardening
patches. Those later patches tightened download/analyse/OCR/audit validation and made OCR
no-clobber atomic; they did not receive a second native run because the Claude account was
already at 98% of its weekly allowance. The final snapshot is covered by source, contract,
bundle, and full-suite tests, but this record must not be presented as a final-snapshot
native E2E.

## Test

An interactive Claude Code session loaded this checkout with `--plugin-dir` and received an
explicit human request to invoke the native Workflow tool. The run used a fresh isolated
vault under `/tmp` and one synthetic, born-digital three-page paper. The source PDF was
pre-populated so the legacy download node exercised its existing-source verification path
without network acquisition or real user data.

Arguments:

```json
{
  "kind": "paper",
  "slug": "example-infrastructural-memory-2024",
  "meta": {
    "title": "Infrastructural Memory: Archives, Standards, and Repair",
    "authors": ["Ada Example", "Lin Chen"],
    "year": 2024,
    "journal": "Journal of Synthetic Media Studies",
    "doi": "10.5555/example.2024.1",
    "confidence": "verified"
  }
}
```

This was not a Pi runner, Codex runner, mocked Agent harness, or synthetic Workflow trace.
Claude Code displayed its native Workflow approval card, `/workflows` progress row, phases,
per-Agent labels, token counts, and the final native result.

## Result

The native run completed in 232,504 ms with five Agents, 74,023 tokens, 17 tool calls, and
no Agent errors:

```json
{
  "slug": "example-infrastructural-memory-2024",
  "status": "ok",
  "material_receipt": {
    "schema_version": "quasi.material-loop.receipt/0.1",
    "material_key": "paper:example-infrastructural-memory-2024",
    "status": "complete",
    "disposition": "created",
    "stage": "audit",
    "failure": null,
    "resume": null
  }
}
```

Observed native sequence:

```text
paper.download.legacy  succeeded (existing valid source)
document.extract-text  succeeded (2,924 chars; 3/3 text pages)
document.assess-readability  readable
paper.analyse  succeeded, action=create
paper.audit.legacy  clean, remaining_violations=0, escalated=[]
```

Artifacts:

| Role | Path | Size | SHA-256 |
| --- | --- | ---: | --- |
| source | `sources/example-infrastructural-memory-2024.pdf` | 3,979 | `f73f97285c2742f3b662ea37fffa079e755bf7a6327563fb97572a0dab4218a4` |
| normalized text | `processing/papers/example-infrastructural-memory-2024/source.txt` | 2,924 | `550749b3f8694f8d00e71c0683fe7173af2c190b991c852ee0263847eb3ab77f` |
| canonical analysis | `vault/papers/example-infrastructural-memory-2024.md` | 6,414 | `e42fb87bf5e1b4d15d22b9603c215c9cdd64c27ffb10c0fd42b720af0a536eeb` |

The canonical Markdown was independently inspected after the run. It contained the
required metadata and ordered analysis sections, and the final audit receipt targeted the
exact canonical path.

## Permission evidence and limits

The initial Workflow launch required the expected native approval. A preliminary Bash
filesystem probe also requested permission; switching the isolated session to auto mode
allowed the run to proceed, but Claude reported that its safety classifier was unavailable
for three subagent reviews. This was surfaced as an advisory log, not a functional failure.
The artifacts and exact receipts were therefore checked independently.

This run validates the born-digital Paper happy path only. Scan/OCR recovery,
audit-escalation repair, and native pause/resume writer replay were not exercised as real
Claude Workflow E2Es in this run. Their current evidence remains contract, characterization,
and adapter-runner tests and must not be described as production validation.

## Final-snapshot BTS run and live schema correction

A second interactive Claude Code 2.1.211 session loaded the current checkout with
`--plugin-dir /Users/ramudai/Vibe/quasi` and ran the plugin Workflow in the BTS vault.
The isolated fixture used:

```text
slug: quasi-e2e-workflow-boundaries-2026
source: sources/quasi-e2e-workflow-boundaries-2026.pdf
source SHA-256: 98644e38ba3066f0a99dda095f4cc44392c4f9d32f1f70e057003f25352c0d01
```

The first run, `wf_96ad279b-39f`, successfully completed download reconciliation,
text normalization, semantic readability assessment, and `paper.analyse`. The audit
Agent then failed before executing with:

```text
API Error: 400 tools.3.custom.input_schema: input_schema does not support
oneOf, allOf, or anyOf at the top level
```

This was a genuine native-host incompatibility that the mock runner and schema tests
had not detected. The coordinator removed only the top-level `anyOf` from
`PAPER_AUDIT_SCHEMA`; the Workflow's `strictAuditReceipt` retained the full
`clean|partial|error` cross-field matrix. The generated bundle and 68 focused
Paper/build tests passed before relaunch.

The corrected fresh run, `wf_fb151d65-766`, used the current bundle directly through
Claude's Workflow tool. It completed in 133,839 ms with seven Agents and 129,588
tokens:

```text
paper.download.legacy       succeeded, disposition=reused, identity_verified=true
document.extract-text       succeeded, 2,514 bytes, 3/3 text pages
document.assess-readability succeeded, signal=readable
paper.analyse               blocked/reconciled; existing canonical not overwritten
paper.audit.legacy pass 1   partial, one exact block_kind_mismatch
paper.analyse repair        succeeded, action=repair
paper.audit.legacy pass 2   clean, remaining_violations=0, escalated=[]
```

The final result was:

```json
{
  "status": "ok",
  "material_receipt": {
    "status": "complete",
    "disposition": "repaired",
    "stage": "audit",
    "audit": {
      "status": "clean",
      "remaining_violations": 0,
      "escalated": []
    }
  }
}
```

The first audit found that `## 核心引用` was a paragraph although the Paper schema
requires a numbered list. The bounded repair reformatted it without inventing
bibliographic citations, then the second audit passed. Independent verification with
`quasi-audit --path` returned `clean`, zero diagnostics, and zero modified files.

Final artifact hashes:

| Role | Path | SHA-256 |
| --- | --- | --- |
| source | `sources/quasi-e2e-workflow-boundaries-2026.pdf` | `98644e38ba3066f0a99dda095f4cc44392c4f9d32f1f70e057003f25352c0d01` |
| normalized text | `processing/papers/quasi-e2e-workflow-boundaries-2026/source.txt` | `cdfc6aeeba8e128978ad322548eb58a4416ae3afef429edc77dd0815de8c02fb` |
| canonical | `vault/papers/quasi-e2e-workflow-boundaries-2026.md` | `ef9e088c7bb6083dea7b33270f80afb28cf48c697fcff0d88593f878c2e4d025` |

The native journal contains seven `started` and seven matching `result` records, with
no started-only key. No OCR file was created. This validates the final Paper
born-digital path, live structured-output schema, exact-output reconciliation, and one
audit-repair loop. It still does not validate a real scanned-PDF OCR run or a
same-run pause/resume replay.
