# Task 1 report: Pure Anna Slow page parsers

## RED/GREEN evidence

- Detail-parser RED:
  `python3 -m pytest tests/test_download_cli.py -q -k 'slow_partner_parser_preserves or slow_partner_parser_excludes'`
  → `2 failed, 112 deselected`; both failures were expected `AttributeError` for the absent parser, with no fixture/import errors.
- Detail-parser GREEN:
  same command → `2 passed, 112 deselected` (one unrelated LibreSSL warning).
- Final-URL parser RED:
  `python3 -m pytest tests/test_download_cli.py -q -k 'slow_final_url_parser'`
  → `6 failed, 114 deselected`; all failures were expected `AttributeError` for the absent parser.
- Final-URL parser GREEN:
  same command → `6 passed, 114 deselected` (one unrelated LibreSSL warning).
- Focused verification:
  `python3 -m pytest tests/test_download_cli.py -q -k 'slow_partner_parser or slow_final_url_parser'`
  → `8 passed, 112 deselected`.
- Full file verification:
  `CLAUDE_PLUGIN_DATA=/tmp/quasi-task1-test python3 -m pytest tests/test_download_cli.py -q`
  → `120 passed, 6 warnings`.
  The same command without the writable environment override had one unrelated permission failure while opening the existing EZProxy throttle state under `/Users/ramudai/.cache/quasi`.
- `git diff --check` → exit 0, no output.

## Changes

- Added `_safe_http_url` with HTTP(S), hostname, and credential rejection.
- Added ordered, no-wait, deduplicating `parse_aa_slow_partner_urls`.
- Added candidate normalization and `parse_aa_slow_final_url` for the five approved page shapes, rejecting recursive Slow URLs and unsafe candidates without sleeping or fetching.
- Added literal detail fixtures and parameterized final-URL fixtures plus negative cases.

## Self-review

- Only the two brief-allowed files were modified.
- DOM order and first-admissible candidate order are preserved.
- URL normalization uses `html.unescape` and `urllib.parse.urljoin`; credentials, non-HTTP schemes, and `/slow_download/` recursion are rejected.
- No network calls, sleeps, or Task 2 changes were introduced.

## Commit

`acc9af8 feat(download): parse Anna slow partners`

## Concerns

None for Task 1. The default full-file run requires `CLAUDE_PLUGIN_DATA` to point to a writable directory in this sandbox because the pre-existing EZProxy throttle path is outside the writable workspace.
