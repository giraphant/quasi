# Task 4 report: observe Webpage ownership and status

## Implemented

- Added the `webpage` resolver item at the existing vault-resolve boundary.
  It normalizes URLs with Task 2's shared normalizer, indexes only safe
  `vault/webpages/<slug>/` directories, prefers canonical frontmatter URL
  evidence, falls back to the saved WebArchive URL, and reports duplicate URL
  owners without selecting one.
- Added deterministic collision suggestions using the shared URL hash helper.
  URL ownership is resolved before a requested slug can be considered.
- Added `quasi-status --kind webpage --slug SLUG --json` with exact snapshot,
  prepared, canonical, and capture-time facts. Snapshot identity comes from
  the parsed WebArchive; canonical identity is accepted only with required
  Webpage frontmatter and coherence with snapshot identity/provenance.
- Added Webpage scan discovery from the three exact artifact roots.

## TDD evidence

### RED

Command run before production edits:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q -k 'webpage'
```

Result: `11 failed, 36 deselected` (plus five pre-existing third-party Python
deprecation warnings). Failures were collected assertion failures, not import
or collection errors: the resolver returned its unsupported-kind error for
`webpage`; `quasi-status` rejected `webpage` as an invalid choice; and scan
returned no Webpage rows. This was expected before the new resolver and status
branches existed.

### GREEN

Focused command after implementation:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q -k 'webpage'
```

Result: `11 passed, 36 deselected` (the same five third-party warnings).

Full relevant command:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q
```

Result: `47 passed` (the same five third-party warnings).

`git diff --check` also passed.

## Files changed

- `scripts/vault/resolve.py`
- `scripts/status/status.py`
- `tests/test_vault_resolve.py`
- `tests/test_status_cli.py`
- `.superpowers/sdd/2026-08-13-webpage-material-workflow/task-4-report.md`

## Self-review

- Resolver behavior for Book, Paper, Talk, and Author remains on its existing
  path; the new logic is entered only for `kind:webpage`.
- Webpage ownership has no title/site/fuzzy matching and no live URL access.
- Status uses only the exact durable paths and parses the saved WebArchive; it
  does not invoke extraction or readability heuristics.
- Canonical mismatch retains snapshot identity and marks canonical unusable.

## Concerns

None. The test runner emits five unrelated Python runtime deprecation warnings
from installed binary dependencies; they are present on both RED and GREEN
runs and do not originate in this change.
