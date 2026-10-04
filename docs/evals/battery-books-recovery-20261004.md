# Four battery books: diagnosis, ablation reasoning and repair

Date: 2026-10-04. Repository repair; no whole-book translation or user-vault write.

## Observed failures

- The Battery: 326 recognition pages completed; layout preparation then rejected
  `image_block`. This is a legal, empty container in the pinned MinerU library.
- Bottled Energy: 448 recognition pages completed; layout preparation then rejected
  `xrightarrow`. Both books failed before a translation provider was started.
- Charged: an EPUB generation contained nine reading sections plus a publisher's
  Weyerhaeuser Environmental Books catalogue. The specialist correctly identified
  it but lacked a transactional way to exclude it. Only an EPUB is accepted in BTS;
  PDF translation separately requires acquiring a PDF source.
- Bottled Lightning: chapter preparation completed, but all sixteen analysis agents
  returned scope conflicts. Their host-supplied user frame contained only the latest
  additive translation message and called it the only user voice. Earlier processing
  instructions were absent. The script still correctly dispatched chapter analysis.

The last case is a host context limitation plus a mistaken interpretation of the
sequential request; it is not a corrupt source or a missing chapter file.

## Ablation thought experiment

These are counterfactual design checks, not measured model experiments.

| Change considered in isolation | Expected result | Decision |
| --- | --- | --- |
| Remove unknown-block validation | The Battery could pass, but genuinely unknown content could disappear | Retain validation; recognize known visual containers and preserve their children |
| Remove unknown-LaTeX validation | Energy could pass with an arrow or annotation lost | Add a semantic projection for annotated arrows; unknown placed prose remains an error |
| Only skip formula conversion in layout | Standalone formula images survive; an inline annotated arrow in body text still fails | Also support arrows in ordinary text and placed paragraphs |
| Replace the annotated arrow with a bare arrow | Direction survives, but charge/discharge conditions disappear | Preserve direction plus both labelled arguments |
| Add one publisher to the skip list | Charged passes; another series catalogue produces the same dead end | Add exact, explicit exclusions with transactional regeneration |
| Delete the catalogue file or edit its manifest manually | The visible extra chapter disappears, but owned-file/fingerprint coherence is no longer proven | Use the existing generation transaction and manifest precondition |
| Treat each latest message as a replacement task | Additive translation cancels previously requested analysis | Keep active tasks unless the user cancels; interpret “after processing” as a dependency |
| Tell specialists that computed tasks override user requests | May suppress this refusal but also ignore real cancellations | Preserve user priority; distinguish additive sequencing from explicit “only translate” |
| Replay failures or introduce an OCR cache | Does not remove the compatibility or authority mismatch | No automatic replay, hidden cursor, or new persistent OCR cache |

## Implementation boundaries

- Known `image_block`, `equation_block` and `chart` handling; nonempty containers
  still fail. Layout keeps independent visual math as pixels, while text extraction
  retains recognized equations/tables. `xrightarrow`/`xleftarrow` conversion keeps
  annotations and the existing font/text integrity checks. Page numbers accompany
  normalization failures.
- `quasi-extract epub --exclude-title EXACT_TITLE` is repeatable, exact and
  case-sensitive. Empty, repeated, missing, ambiguous and all-chapter exclusions
  fail without replacing the prior generation. The exclusion set participates in
  the request fingerprint. Existing explicit exclusions must be carried forward
  by the specialist when it adds another. No title-specific blacklist was added.
- Collect retains the ongoing request and appends Translation after verified Book
  completion. Analyse distinguishes sequential additions from cancellations. The
  Chapter request names its role within Book processing without asserting user
  consent. Scope failures remain failures; unknown writers must be reconciled.
  This is an agent/Skill mitigation: Quasi cannot change the proprietary host's
  latest-message relay. No live-host behavioral acceptance is claimed here.

## Validation evidence

Before implementation, the added OCR/exclusion regressions produced 18 failures
and 39 passes. Two subsequent test expectation errors (`reused` versus the CLI's
existing `reconciled` disposition) were corrected without changing runtime behavior.

Real Charged acceptance used a disposable directory under `/private/tmp`, reading
the existing EPUB with SHA-256
`1d2a841701d8fc7705b2dc0c6d50c96c39c62545afd50d8d7b40d783fb045e81`.
The normal extraction had ten entries; an explicit catalogue exclusion produced
nine. All nine retained chapter files were byte-identical to the original
extraction and the EPUB hash was unchanged. No BTS manifest or reading output was
modified. Kept: Foreword, Introduction, four body chapters, Conclusion, Notes and
Bibliography.

OCR fixtures exercise both PDF output modes, retained caption/equation children,
arrow direction and both annotations after PDF extraction, source-pixel equality
in layout, provenance inspection, malformed annotation rejection and preservation
of failures for unsupported body markup. They do not constitute a new whole-book
recognition run or a translation quality audit.

The final targeted suite passed **467 tests** across `test_ocr_mineru`,
`test_extract_epub_cli`, `test_extract_cli`, `test_translate_cli`,
`test_workflow_dispatch`, `test_material_plans`, `test_dead_names` and
`test_skill_orchestration`. `npm run build:workflows` regenerated the owned
bundles; `npm run check:workflows`, `cmp -s CLAUDE.md AGENTS.md` and
`git diff --check` passed. Tests used the existing Quasi runtime interpreter with
the locally installed pytest package made importable; no runtime dependency was
installed or changed. Model recognition was stubbed in OCR regressions.

The patch is packaged as version 0.68.4. The failed runs used the
installed 0.68.2 plugin; its cache was not edited. Material recovery must use the
updated code, fresh exact status, and a complete active task scope. Completing a
whole-book PDF still requires the ordinary source/layout, provider, ToUnicode and
coverage checks; passing these regressions does not claim any book is translated.
