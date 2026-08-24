# Material Success Reliability Design

date: 2026-08-24
status: approved

## Goal

Raise the real completion rate of recent Paper and Book collections without
weakening identity checks, accepting corrupt files, inventing fake success, or
moving professional method into Skills and Workflow plans.

This design addresses four observed failure classes:

1. full-book OCR exceeds one foreground Bash call and ends without a receipt;
2. a Paper can have a verified article-text source even when no PDF exists, but
   the material contract currently names only `sources/{slug}.pdf`;
3. the Paper cascade can mistake a large non-HTML payload for PDF or run until
   the host kills it without a terminal JSON object;
4. a normal web article can enter Paper search and later fail as if it were a
   missing scholarly PDF instead of continuing through Webpage collection.

## Non-goals

- Do not add `nohup`, detached writers, a daemon, a process supervisor, or a
  general job framework.
- Do not disable TLS verification, automate Cloudflare/Turnstile, or weaken
  Paper/Book identity requirements.
- Do not make working papers, theses, talks, or book chapters pretend to be
  journal articles. Those remain typed unsupported materials until their own
  product type exists.
- Do not replace the provider cascade with Workflow-level provider policy.
- Do not change Translation layout OCR in this release. Its layout pass needs
  book-wide typography evidence and is a separate measured pipeline.

## Invariants

- A long Book OCR remains one logical `book.prepare` writer. It makes progress
  through short foreground transactions and never leaves a detached process.
- Every durable OCR progress fact is an explicit `book.prepare` artifact and is
  projected by `quasi-status`; there is no hidden Skill cursor.
- One OCR step commits at most one validated page-range part. A final recovery
  PDF becomes visible only after every range is validated and merged.
- A Paper accepted source is exactly one of `sources/{slug}.pdf` or
  `sources/{slug}.txt`. Zero sources means Acquire is needed. Two usable sources
  are a conflict, never an implicit preference.
- A `.pdf` candidate is not usable merely because a server labels it PDF or it
  is larger than an arbitrary byte threshold. It must have a PDF header, open
  with PyMuPDF, and contain at least one page.
- A text source must pass the existing exact title/author identity proof and an
  article-structure check before it can be accepted.
- Every Paper fetch invocation emits one JSON terminal before the host Bash
  ceiling. Budget exhaustion means “this invocation did not finish the
  cascade,” not “all sources are known to be absent.”
- Skills continue to transport exact status and typed results only. They do not
  inspect OCR pages, provider attempts, source formats, or publication types.

## 1. Resumable Book OCR

### Public capability

Extend `quasi-extract ocr` with a Book-only resumable mode:

```text
quasi-extract ocr INPUT.pdf OUTPUT.pdf \
  --resume --progress-file PROGRESS.json --chunk-pages N \
  [--engine dsocr2|tesseract] --no-clobber --json
```

`--resume` requires an explicit output, progress file, `--no-clobber`, and
non-layout mode. `N` defaults to 8 and is bounded to 1–32. One invocation
processes exactly one missing contiguous range, so its wall time remains below
the foreground command ceiling under the measured DS OCR2 rate. Ordinary OCR
and Translation `--layout` behavior remain unchanged.

### Durable state

Book Prepare owns:

```text
processing/chapters/{slug}/ocr.pdf
processing/chapters/{slug}/ocr.progress.json
processing/chapters/{slug}/.ocr-parts/
```

The progress document is closed JSON:

```json
{
  "schema_version": "quasi.ocr.progress/0.1",
  "input_path": "sources/example.pdf",
  "output_path": "processing/chapters/example/ocr.pdf",
  "source_sha256": "64 lowercase hex",
  "engine": "dsocr2",
  "chunk_pages": 8,
  "total_pages": 996,
  "completed_pages": 24,
  "next_page": 25
}
```

The CLI holds an exclusive lock beside the progress file. A new state is
created only after validating the source as a readable PDF and hashing it.
Every resume verifies the input path, output path, source hash, engine, chunk
size, total page count, and the completed part inventory. A mismatch returns a
typed failure and preserves both the accepted source and existing parts.

For one step the CLI writes an exact source slice, invokes the existing OCR
engine on that slice, verifies the resulting PDF and expected page count, then
atomically publishes one part. Only after the part is durable does it atomically
replace the progress document. When all ranges exist, it merges them in page
order into a sibling stage, validates total page count, atomically publishes
`ocr.pdf` with no-clobber semantics, then removes the progress document and
private parts directory.

JSON statuses are:

- `partial`: one part committed; includes the full progress projection;
- `ok`: final output committed by this call;
- `existing`: a previously committed final output was verified;
- `failed`: no new durable part or final output was claimed.

### Workflow recovery

`book.prepare` adds `ocrProgress` to its artifact catalog and write scope.
`quasi-status --kind book` projects a closed `ocr_progress` fact containing the
path, present/usable state, source hash, total/completed pages, and next page.

The Extract Agent calls resumable OCR once when a full-book scan needs OCR. On
`partial`, it returns schema-valid
`blocked + book.prepare.ocr_in_progress + retryable:true` and performs no split
or manifest write. The Book plan converts only that exact terminal into
`needs_observation` for the same Book route. Collect's existing observation
pump sees `completed_pages` change and resumes. Two byte-identical observations
still stop, so a stuck OCR does not loop indefinitely. When the final OCR step
returns `ok` or `existing`, the same Extract Agent continues normal text
extraction, chapter splitting, and manifest publication.

Unknown writer outcomes retain the existing stop-and-observe policy. A later
invocation may resume only committed parts; it never assumes the interrupted
range completed.

## 2. Paper source carriers

### Artifact contract

Replace the single Paper Acquire output with two exact alternatives:

```text
outputPdf  = sources/{slug}.pdf
outputText = sources/{slug}.txt
```

Paper status exposes a deterministic `sources` array in that order, using the
same `{format,artifact}` shape already used by Book. The Paper input parser
requires both observations. The plan selects the sole usable source, dispatches
Acquire when neither is usable, and returns `paper.source_conflict` when both
are usable. Complete results name only the selected source.

`paper.acquire` receives both exact paths, may write only those paths, and its
complete receipt chooses one `output_path` from the closed pair. Existing PDF
behavior remains valid. A verified text candidate is accepted to the text
path; it is never renamed to `.pdf`.

### Prepare

`quasi-extract text INPUT OUTPUT --json` accepts either PDF or UTF-8 text.
For PDF it preserves current `pdftotext` behavior. For text it validates UTF-8,
normalizes newlines, writes a fsynced sibling stage, and atomically replaces the
exact normalized output. It reports the same character/page signals.

Paper Prepare receives the selected PDF or text source. A usable text source is
normalized directly and never OCRed. A PDF retains current text-layer/OCR
judgement. The canonical Paper page and audit contract do not change.

### HTML acquisition

Any direct, OA, publisher, EZProxy, Wayback, or Kagi response may become a text
candidate when all of these hold:

- it is not a PDF, Cloudflare challenge, login page, or unsupported MIME;
- deterministic extraction yields at least 500 characters;
- the full normalized expected title and expected author identity proof passes;
- at least one scholarly article marker such as abstract, introduction,
  keywords, references, or article information is present.

The gate is evidence-based rather than host-name-based. Landing pages with only
metadata, paywalls, search results, or navigation fail closed. A successful
text fallback enters the same identity review and single atomic accept path as
a PDF.

## 3. Paper transport and validation

### PDF validation

Use one shared `readable_pdf_bytes` predicate for direct HTTP, Sci-Hub,
publisher, EZProxy, Wayback, and Kagi results. It requires a PDF header within
the allowed prefix, successful PyMuPDF parsing, and `page_count > 0`. A response
header cannot override invalid bytes. Accepted PDF files are checked again
under the destination lock before publication.

### Bounded terminal

Add `--budget-seconds` to `quasi-download paper fetch`, default 480 and bounded
to 30–540. A monotonic deadline is owned by the Paper CLI, not the Agent or
Workflow. Network timeouts, retry sleeps, EZProxy throttle waits, and provider
transitions are capped by remaining time. When less than the minimum safe
request budget remains, the cascade stops and returns:

```json
{
  "status": "budget_exhausted",
  "kind": "paper",
  "doi": "...",
  "urls": [],
  "reason": "paper_fetch_budget_exhausted"
}
```

Exit is non-zero, no partial candidate is accepted, and any fenced identity
candidates already completed remain available to the Agent. The Download Agent
maps this result to `paper.acquire_blocked`, `retryable:true`; it must not call
the same broad cascade again in that invocation. This preserves the distinction
between an interrupted investigation and `all_sources_failed`.

Certificate-verification failures are deterministic for one mirror and are not
retried against that same mirror. TLS verification remains enabled. Provider
order and professional stopping judgement stay inside Download Agent/CLI.

## 4. Web article routing

When Paper Search can prove the requested item is a normal public web article
and has an exact public URL, it returns failed issue
`material.webpage_redirect` plus that URL. This is not used for working papers,
theses, conference papers, chapters, or journal articles with an HTML full-text
carrier.

The direct Paper plan converts this exact typed outcome into a complete result
with no Paper artifacts and `next:{kind:"webpage",url}`. Collect invokes the
existing Webpage provisional entry with that exact URL. Author and Topic
composition do not silently substitute a webpage for a requested Paper member;
they surface a typed unsupported child redirect.

`MaterialNextRoute` becomes the closed union of existing Book identity redirect
and Webpage URL redirect. Collect switches only on `next.kind`; it does not
reclassify materials itself.

## Error boundaries

- Invalid/stale OCR state: `blocked`, non-retryable until the exact progress
  artifact is inspected or removed; accepted source is untouched.
- OCR partial progress: exact retryable issue converted to observation, never a
  generic replay.
- Both Paper source formats present: `paper.source_conflict`, non-retryable.
- Paper budget exhausted: blocked/retryable with no claim of source exhaustion.
- Structurally invalid PDF: provider miss; never an identity candidate.
- Verified wrong identity: retained only in the existing fenced candidate list
  for specialist judgement, never published.
- Webpage redirect without one valid public URL: incoherent receipt, blocked.

## Tests and acceptance

The release is complete only when all of the following are proven:

1. repeated resumable OCR invocations commit one range at a time, change Book
   status testimony, merge exact page order, and recover after a killed range;
2. stale state, output races, bad parts, and simultaneous callers fail closed;
3. Paper status/plan accepts exactly one PDF or text source, rejects both, and
   Prepare normalizes text without OCR;
4. article-like HTML from a previously unknown host yields a verified text
   source, while login/paywall/search HTML does not;
5. mislabeled or corrupt PDF bytes never reach identity verification or accept;
6. a forced Paper deadline returns `budget_exhausted` JSON before the host
   ceiling and leaves no accepted output;
7. direct Paper-to-Webpage continuation works, while Author/Topic composition
   does not silently reclassify a member;
8. generated Workflow bundles are current, TypeScript passes, the full pytest
   suite passes, plugin manifests validate, and CLAUDE/AGENTS remain identical.

