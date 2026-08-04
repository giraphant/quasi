# Run-stage test migration map

This ledger records the pre-refactor baseline at commit
`e423c328b811ded8eeb17503fcd08259dd0439d1`.  It is the deletion gate for
`tests/test_run_stage.py`: each row below must have its named replacement
passing before the old test is retired.  Rows labelled **mode-only** cover the
retired public `stage`, `until`, `units`, selection-error, or batch-envelope
interface; delete them after all active callers migrate.

## Pre-change baseline

```text
$ npm run check:workflows

> check:workflows
> node scripts/build-workflows.mjs --check && tsc --noEmit

run-stage workflow bundle is current

exit status: 0
```

```text
$ python3 -m pytest tests/test_run_stage.py tests/test_status_cli.py tests/test_skill_orchestration.py tests/test_dead_names.py -q
........................................................................ [ 67%]
...................................                                      [100%]
107 passed in 3.37s

exit status: 0
```

```text
$ python3 -m pytest --collect-only -q
546 tests collected in 0.72s

warnings: urllib3 NotOpenSSLWarning; two importlib DeprecationWarnings for
SwigPyPacked and SwigPyObject; a swigvarlink DeprecationWarning.
exit status: 0
```

The collection command's complete name listing is intentionally not copied
here: its exact command result is the successful collection of 546 tests, with
the warning summary recorded above.  The command remains the reproducible
source for the full listing.

## Per-function migration ledger

| Existing invariant | Replacement test | Retirement condition |
|---|---|---|
| `test_chapter_analyse_pins_complete_to_caller_output_observation`: `output_exists` selects `create/written` or `reconciled/not_written` | `test_material_plans.py::test_book_binds_create_and_reconcile_from_initial_observation` | replacement passes |
| `test_chapter_analyse_requires_caller_output_observation`: missing chapter output observation rejects before dispatch | focused `chapter.analyse` context test in `test_workflow_dispatch.py` | replacement passes |
| `test_chapter_analyse_keeps_manifest_title_when_label_is_missing`: manifest title is preserved when label is absent | focused `chapter.analyse` request test in `test_workflow_dispatch.py` | replacement passes |
| `test_chapter_analyse_prefixes_explicit_label_once`: explicit chapter label prefixes the title exactly once | focused `chapter.analyse` request test in `test_workflow_dispatch.py` | replacement passes |
| `test_paper_acquire_prompt_preserves_urls_and_real_diagnostic_capabilities`: Paper Acquire request retains both URLs and only real diagnostic capabilities | focused `paper.acquire` request test in `test_workflow_dispatch.py` | replacement passes |
| `test_prompt_and_schema_are_exactly_the_selected_row_pair`: the chosen operation uses its own prompt/schema pair and shared phase/agent wiring | `test_workflow_dispatch.py::test_catalog_prepares_each_operation_with_its_own_schema` | replacement passes |
| `test_every_request_envelope_uses_shared_stage_tag`: every request envelope has the shared request version/tag | catalog wiring test in `test_workflow_dispatch.py` | replacement passes |
| `test_stage_protocol_has_exactly_four_closed_terminal_branches`: Stage receipt has exactly the four closed terminals | `test_workflow_dispatch.py::test_stage_terminal_union_is_closed` | replacement passes |
| `test_every_row_schema_types_its_consts`: every schema `const` also declares its type | schema-closure test in `test_workflow_dispatch.py` | replacement passes |
| `test_acquire_write_outcome_lives_only_in_complete_terminal`: Paper/Book Acquire write fields appear only in `complete` | focused Paper/Book Acquire schema test in `test_workflow_dispatch.py` | replacement passes |
| `test_model_schema_omits_host_stamps_and_requires_judgement_fields`: model schema excludes host stamps and requires judgement fields | `test_workflow_dispatch.py::test_dispatch_stamps_only_host_fields` | replacement passes |
| `test_host_stamps_bookkeeping_onto_validated_model_output`: host stamps only host-owned bookkeeping onto validated model output | `test_workflow_dispatch.py::test_dispatch_stamps_only_host_fields` | replacement passes |
| `test_unknown_selection_returns_typed_error`: unknown public kind/stage returns a top-level selection error | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |
| `test_paper_chain_dispatches_fixed_sequence_and_carries_prepare_input`: Paper sequence carries Prepare's selected input into Analyse | `test_material_plans.py::test_paper_happy_path_carries_selected_input` | replacement passes |
| `test_paper_chain_stops_at_needs_input_gate`: Paper stops at its typed `needs_input` gate without later dispatch | focused Paper gate test in `test_material_plans.py` | replacement passes |
| `test_paper_chain_rejects_incoherent_complete_before_next_stage`: a schema-valid but incoherent complete stops dispatch | `test_workflow_dispatch.py::test_incoherent_complete_blocks` | replacement passes |
| `test_paper_chain_records_dead_agent_as_null_receipt`: null/exception Agent outcome blocks without replay | `test_workflow_dispatch.py::test_unknown_outcome_blocks_without_replay` | replacement passes |
| `test_chain_rejects_units_as_invalid_context`: `units` is invalid in public `until` chain mode | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |
| `test_chain_rejects_reverse_range`: reverse public `until` range rejects | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |
| `test_chain_rejects_kind_without_sequence`: public `until` rejects a kind with no stage sequence | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |
| `test_book_analyse_fans_out_units_and_preserves_receipt_order`: Book chapter work preserves manifest order through the public `units` batch envelope | `test_material_plans.py::test_book_pipeline_preserves_manifest_order` | replacement passes; old `units`/batch envelope is mode-only and deletes after all active callers migrate |
| `test_batch_invalid_context_is_per_unit_and_other_units_dispatch`: public batch envelope reports one bad unit while dispatching siblings | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |
| `test_batch_duplicate_units_fail_before_any_agent_dispatch`: overlapping chapter writers reject before dispatch | `test_material_plans.py::test_book_rejects_overlapping_outputs_before_dispatch` | replacement passes |
| `test_single_mode_returns_host_stamped_receipt_and_logs_narrative`: single public `stage` mode stamps receipt and logs narrative | `test_workflow_dispatch.py::test_dispatch_stamps_only_host_fields` | replacement passes; old public `stage` mode is mode-only and deletes after all active callers migrate |
| `test_batch_unknown_selection_remains_a_top_level_error`: unknown kind/stage remains a top-level public batch error | none — **mode-only; delete after all active callers migrate** | mode-only; delete after all active callers migrate |

## Required destination cross-check

The required migration targets are represented above: row/schema pairing,
closed terminals, host stamping, incoherent complete, unknown outcome, Paper
carry/order, chapter order, duplicate writer ownership, `output_exists`
binding, generated-bundle execution, missing chapter observation, chapter
label/title, Paper Acquire URL/capabilities, shared request tag/phase, typed
schema constants, model-schema host-stamp exclusion, and complete-only Acquire
write fields.  The generated-bundle ABI invariant is recorded independently
below because it is currently embedded in the generated compatibility bundle
rather than a separately named `test_*` function in `test_run_stage.py`.

| Existing invariant | Replacement test | Retirement condition |
|---|---|---|
| generated bundle executes source `run` | `test_workflow_bundle_abi.py::test_generated_workflow_returns_source_run_result` | replacement passes |
