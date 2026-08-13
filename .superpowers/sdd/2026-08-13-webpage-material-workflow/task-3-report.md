# Task 3 report: capture webpage WebArchives

## Implemented

- Added `quasi-webpage inspect`, `capture`, and `extract` through the new
  Python command module and bootstrap-compatible `bin/quasi-webpage` shim.
- Added the offscreen, nonpersistent `WKWebView` helper. It performs one load,
  has a fixed 750 ms settle period, races the entire operation against one
  60-second timeout, and does not create a window or use Safari.
- Capture stages beside the requested output, parses the staged WebArchive with
  the Task 2 capability, checks both native and archive final URLs, sets a UTC
  whole-second mtime, fsyncs, then publishes through a no-clobber hard link.
- Reused Task 2's `normalize_web_url`, `read_webarchive`, and
  `extract_webarchive`; no parsing or extraction logic was duplicated.
- Added command-contract coverage for successful publication, final-URL
  mismatch/no publish, existing-output no-clobber, public extraction, and a
  macOS-gated loopback-only WebKit smoke test.

## TDD evidence

### RED

Command run before creating Task 3 production files:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'capture or command'
```

Outcome: `5 failed, 11 deselected in 0.08s`.

Each selected test was collected and failed at the test-local lazy loader with
`Failed: Webpage command capability has not been implemented`; this was an
assertion failure inside the test, not an import or collection error. The
failure was expected because `scripts.webpage.webpage` did not exist yet.

### GREEN

Focused command-contract and loopback native smoke command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'capture or command'
```

Outcome: `5 passed, 11 deselected in 3.26s`.

Final complete verification:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q
bash -n bin/quasi-webpage
git diff --check
swiftc -O -parse-as-library -framework WebKit scripts/webpage/webpage_capture.swift -o /private/tmp/quasi-sdd-webpage-data/bin/quasi-webpage-webkit-smoke
```

Outcome: `16 passed in 2.28s`; shell syntax, whitespace, and Swift compile all
succeeded. The integration test used only a `ThreadingHTTPServer` bound to
`127.0.0.1`; it did not contact a public website.

## Files changed

- `scripts/webpage/webpage_capture.swift`
- `scripts/webpage/webpage.py`
- `bin/quasi-webpage`
- `tests/test_webpage_cli.py`
- `.superpowers/sdd/2026-08-13-webpage-material-workflow/task-3-report.md`

## Self-review

- Scope is limited to Task 3 command/capture surfaces and their tests/report.
  No progress ledger, version, manifest, Topic, resolver, status, Workflow, or
  Skill file changed.
- The native helper has exactly `inspect` and `capture` modes, accepts HTTP(S)
  only, uses `WKWebsiteDataStore.nonPersistent()`, and has no fallback, retry,
  background worker, browser window, or Safari invocation.
- Capture does no durable write until both independently observed final URLs
  match the expected normalized URL. Existing outputs are never replaced.
- The timeout cancels an unfinished navigation and stops loading so the task
  group cannot outlive the one 60-second deadline.

## Concerns

None. The local smoke initially required the permitted unsandboxed runner only
because this execution sandbox forbids binding a loopback server; the completed
test remained strictly local.

## Fix round 1 — total timeout

### Cause and change

The first implementation used a structured task-group race. Its timeout child
could cancel the WebKit work task, but task-group scope still waited for an
uncooperative `evaluateJavaScript` or `createWebArchiveData` continuation.
Python also imposed a second 65-second subprocess watchdog that could become
the surfaced failure instead of the helper's closed timeout receipt.

The helper now schedules one main-queue deadline before all navigation,
settling, metadata, and archive work. The deadline emits exactly
`{"status":"failed","code":"webpage.capture_timeout","message":"page capture exceeded 60 seconds"}`
and exits nonzero independently of any WebKit continuation returning. Successful
and ordinary failed operations cancel that scheduled deadline. The Python
native invocation has no timeout argument, leaving the helper deadline as the
only operational deadline.

The test-only Swift build defines `QUASI_WEBPAGE_TESTING`, where a metadata
seam can intentionally await a continuation that never resumes and a 100 ms
deadline is selected. This has no effect in the production compile.

### TDD evidence

RED command against `49c4081` before changing production code:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'native_timeout_wins'
```

Outcome: `1 failed, 16 deselected in 2.19s`. The focused collected test set
the intended metadata stall environment, but the current helper completed with
return code 0; the assertion `assert completed.returncode != 0` failed. This
was the expected behavioral RED: the old helper had neither the test stall seam
nor a deadline able to win over an uncooperative metadata continuation.

GREEN focused command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'native_timeout_wins'
```

Outcome after the implementation and final cleanup: `1 passed, 16 deselected
in 1.17s`. The subprocess returned within its 3-second test guard, with a
nonzero exit and the exact closed `webpage.capture_timeout` JSON object.

### Final verification

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q
bash -n bin/quasi-webpage
swiftc -O -parse-as-library -framework WebKit scripts/webpage/webpage_capture.swift -o /private/tmp/quasi-sdd-webpage-data/bin/quasi-webpage-webkit-final
git diff --check
```

Outcome: `17 passed in 4.34s`; the original loopback capture smoke remains in
the full test file. Shell syntax, Swift compilation, and whitespace validation
succeeded.

### Scope review

Only the native timeout mechanism, its Python watchdog removal, the focused
native test seam, and this report changed. No capture publication behavior,
fallback, retry, background worker, or workflow/status surface was broadened.

## Fix round 2 — single terminal settlement

### Cause and change

The round-1 `DispatchWorkItem.cancel()` call was not serialized with the
deadline work item starting. If the deadline began as `loadOnce` completed,
both paths could write JSON, producing duplicate or interleaved terminal output
before the timeout exits.

`TerminalArbiter` is the sole terminal boundary now. It guards a settled flag
with `NSLock`; timeout, success, typed failure, and unexpected failure all call
`settle`. The winner alone emits one JSON object and, for a failure, exits
nonzero. A losing timeout cannot write after a successful settlement, and a
losing successful/failed continuation cannot write after the independently
executing timeout has settled. This preserves the round-1 full-operation
deadline without detached work, a retry, or an added background process.

The test-only `terminal-race` mode starts concurrent success and timeout
contenders behind the same semaphore. It is compiled only with
`QUASI_WEBPAGE_TESTING` and does not affect the production helper surface.

### TDD evidence

RED command against `a01a5cf` before changing production code:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'terminal_race'
```

Outcome: `1 failed, 17 deselected in 1.01s`. The focused collected test invoked
the test-only `terminal-race` seam, but the current helper rejected it with
`webpage.invalid_arguments` and exit code 2. The assertion requiring a single
success (0) or timeout (1) terminal failed, proving the current helper had no
contended terminal settlement boundary.

GREEN focused command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_webpage_cli.py -q -k 'terminal_race or native_timeout_wins'
```

Outcome: `2 passed, 16 deselected in 2.11s`. The forced concurrent contenders
produce exactly one parseable JSON line with the matching exit status, and the
uncooperative metadata timeout still returns the exact closed timeout result.

### Scope review

Only native terminal settlement, its test-only contention seam, the focused
test, and this report section changed. Publication and staging behavior are
unchanged.
