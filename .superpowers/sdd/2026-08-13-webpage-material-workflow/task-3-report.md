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
