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

## Fix round 1

Addressed exactly the three reviewer findings:

- Webpage resolver now rejects a requested slug that fails the existing
  canonical-kebab regex, returning a closed error row with no suggestion.
- Canonical Webpage frontmatter is now validated by `WebpageSchema` before it
  can supply identity or pass coherence; strict typed optional fields and
  forbidden extras therefore make the artifact unusable.
- Webpage scan roots must now have a contained, no-symlink directory ancestry
  before enumeration, so external artifacts behind a symlinked root are not
  discovered.

### RED

Before the fixes, I ran:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q -k 'unsafe_requested_slug or outside_the_webpage_schema or symlinked_webpage_root'
```

Result: `3 failed, 47 deselected` (plus the same five third-party warnings).
The failures were the expected assertion failures: `../escape` was suggested,
an unknown canonical frontmatter field remained usable, and a symlinked
`vault/webpages` root exposed an external webpage scan row.

### GREEN

Focused command after the fixes:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q -k 'unsafe_requested_slug or outside_the_webpage_schema or symlinked_webpage_root'
```

Result: `3 passed, 47 deselected` (the same five warnings).

Full relevant verification:

```sh
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data /private/tmp/quasi-sdd-webpage-data/.venv/bin/python -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q
git diff --check
```

Result: `50 passed`; `git diff --check` passed. The five third-party warnings
remain deferred as requested.
