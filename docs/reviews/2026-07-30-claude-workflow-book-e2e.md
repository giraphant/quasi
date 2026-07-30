# Claude Workflow refactor: Book native E2E

Date: 2026-07-30
Scope: strict Book vertical slice on the Claude Code native Workflow host.

## Result

**PASS.** A fresh Claude Code 2.1.211 session launched from the BTS vault with
the required Monster settings invoked the committed Workflow bundle exactly
once. The run returned legacy `status=ok` and
`MaterialReceipt.status=complete`.

- Claude session: `162ddf4f-05f0-4fc0-b013-393fef31aab2`
- Workflow run: `wf_18f4222a-9c9`
- Journal:
  `/Users/ramudai/.claude/projects/-Users-ramudai-Documents-Learn-bts/162ddf4f-05f0-4fc0-b013-393fef31aab2/subagents/workflows/wf_18f4222a-9c9/journal.jsonl`
- BTS evidence report:
  `/Users/ramudai/Documents/Learn/bts/session/quasi-book-native-e2e7-20260730-b2e46f81-report.md`
- Slug: `quasi-book-native-e2e7-20260730-b2e46f81`
- Final disposition: `repaired`
- Final stage: `audit`

The session process was launched as:

```text
claude --settings /Users/ramudai/.agents/models/monster.json \
  --plugin-dir /Users/ramudai/Vibe/quasi \
  --dangerously-skip-permissions
```

Its startup cwd was `/Users/ramudai/Documents/Learn/bts`; it did not rely on an
in-prompt `cd`. No skill, Pi runner, Codex adapter, fake harness, resume, or
rerun was used.

## Fixed inputs

The run used a generated three-chapter EPUB with two independent 2026 signals
and unique ALPHA/BETA/GAMMA sentinels.

| Object | SHA-256 |
| --- | --- |
| Source EPUB | `4445fdffe37259bea4e56bfc1529ee615a657676320e70ce1e1b183b702f04fc` |
| Metadata JSON | `1a0379de52b8ec638e4ff67fb8dcb72a3c685043cfdb98c0afcd725fae85ed83` |
| Workflow bundle | `d0ce2ff3faa1b8ab75c477c5522f1d6d1b2c1103df9107906b9e6f9f7a74518d` |

All three hashes were unchanged after the Workflow and independent audit.

## Operation evidence

The run exercised the complete strict Book path:

1. `book.download.legacy` reconciled the existing EPUB, verified identity, and
   returned `MATCH` from two independent 2026 signals.
2. `chapter.extract` produced one atomic manifest and the CLI-native filenames
   `01_Alpha_Stable_Inputs.txt`, `02_Beta_Parallel_Chapters.txt`, and
   `03_Gamma_Audit_and_Repair.txt`.
3. `chapter.assess-boundaries` returned `ready`; `input_paths` contained exactly
   the three chapter text paths, while `manifest_path` remained a separate
   receipt field.
4. All three `chapter.analyse` nodes started before any result was consumed by
   synthesis. All three results were present before `book.synthesise` started.
5. Synthesis wrote the overview from the exact ordered chapter paths.
6. The first audit returned clean after mechanical normalization and accurately
   reported its modified paths. Because chapter dependencies changed, the graph
   ran one bounded overview repair/reconciliation.
7. The second audit returned `clean`, `remaining_violations=0`,
   `escalated=[]`, and `mutated_paths=[]`.

The journal contains 20 events: 10 `started` and 10 `result`. Every unique key
has exactly one of each, with zero errors, empty results, skipped Agents, or
started-only dead nodes. Synthesis started only after all three chapter results.

## Artifacts and independent audit

The MaterialReceipt records nine artifacts: the unchanged source, manifest,
three normalized chapter texts, three chapter Markdown products, and
`00-overview.md`. The final chapter products retain the ALPHA, BETA, and GAMMA
sentinels, and the overview synthesizes all three.

After Workflow completion, an independent exact-path command:

```text
/Users/ramudai/Vibe/quasi/bin/quasi-audit \
  --path /Users/ramudai/Documents/Learn/bts/vault/books/quasi-book-native-e2e7-20260730-b2e46f81
```

returned `status=clean`, checked four files, reported zero diagnostics and zero
modified files, and left all fixed-input hashes unchanged.

## Native seams found before the passing run

The earlier fresh native runs were retained as negative evidence and each
stopped at the first deterministic seam:

1. A synthetic ISBN had only one physical year signal, correctly failing the
   strict two-signal gate. The fixture was corrected rather than weakening the
   contract.
2. The graph expected `ch{slot}-{slug}.txt`, while the transactional CLI
   correctly emitted `NN_Title.txt`. The validator was aligned to the CLI
   identity contract.
3. One run was invalidated because it was launched without the required Monster
   settings; it is not counted as acceptance evidence.
4. Claude StructuredOutput returned `"attempt":"1"` when schemas declared only
   `const: 1`. Every active operation schema now declares
   `type: "integer", const: 1`, guarded across all exported schemas.
5. The boundary prompt ambiguously encouraged including the manifest in
   `input_paths`. It now requires exact ordered chapter paths and explicitly
   excludes `manifest_path`.
6. A later preflight compared the metadata hash to the bundle expectation and
   launched no Workflow. This was classified as a test-spec error rather than a
   plugin defect.

Each actual contract correction received a focused regression, the bundle was
regenerated, and the complete Python 3.12 suite passed before the final run:
`708 passed` with five third-party deprecation warnings.

## Boundaries and residual risk

- This is genuine Claude Workflow evidence, not a Pi/Codex adapter smoke.
- It verifies born-digital EPUB extraction, strict receipts, chapter fan-out,
  barrier ordering, exact synthesis membership, bounded audit dependency
  repair, and terminal reconciliation.
- It does not yet verify Book scanned-PDF OCR in a native run, an actual
  mid-writer pause/resume, kernel crash durability, or advisory-lock behavior on
  non-local filesystems.
- The legacy download and audit nodes remain explicitly named composite debt.
  Unknown writer outcomes remain blocked and resume through reconciliation
  rather than automatic replay.
- No commit, push, PR, release, deployment, cleanup, or Pi/Codex adapter
  redesign was performed.
