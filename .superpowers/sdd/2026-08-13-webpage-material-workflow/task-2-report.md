# Task 2 report — WebArchive parsing and Markdown extraction

## Status

Complete. The pure WebArchive capability is implemented and committed without
WebKit runtime, status, resolver, agent, or workflow changes.

## Files

- `scripts/webpage/__init__.py` — public pure capability exports.
- `scripts/webpage/webarchive.py` — URL comparison key, binary WebArchive
  reader, saved-HTML metadata extraction, lazy Trafilatura Markdown extraction,
  fence-aware heading nesting, and atomic no-clobber publication.
- `scripts/requirements.txt` — adds `trafilatura` and its explicit
  `lxml_html_clean` runtime dependency required by the resolved current lxml.
- `tests/test_webpage_cli.py` — real binary-plist fixtures and behavior tests.

## RED

Command:

```bash
python3 -m pytest tests/test_webpage_cli.py -q -k 'normalize or webarchive or collision'
```

Output: `10 failed in 0.07s`; each failure was the deliberate
`pytest.fail("WebArchive capability package has not been implemented")` from
the test-local lazy loader.

Reason: the tests exercised the absent public capability as a normal test
failure (rather than a collection error), proving that each specified behavior
would be unimplemented before production code existed.

## GREEN

Bootstrap command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data scripts/bootstrap-venv.sh
```

Verification command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data \
  /private/tmp/quasi-sdd-webpage-data/.venv/bin/python \
  -m pytest tests/test_webpage_cli.py -q -k 'normalize or webarchive or collision'
git diff --check
```

Output: `10 passed, 1 warning in 0.17s`; `git diff --check` exited zero. The
warning is urllib3's LibreSSL/OpenSSL environment warning, not a test failure.

## Commit

`68a8d35 feat: extract webpage webarchives`

Only the four Task 2 implementation/test/dependency files were committed.

## Self-review

- The one comparison key only accepts credential-free HTTP(S), removes
  fragments/default ports, lowercases scheme/host, and preserves path/query.
- The parser reads only the saved binary plist main resource, validates HTML
  MIME/data/URL, decodes with its declared encoding or UTF-8 fallback, and
  derives title/site from saved HTML.
- Extraction imports Trafilatura only when invoked and supplies saved HTML plus
  saved URL context; it never performs a live fetch.
- Heading nesting is fence-aware, and publication writes/fsyncs a sibling stage
  file before `os.link` no-clobber publication and directory fsync.

## Concerns

- Current Trafilatura resolution with lxml 6 requires `lxml_html_clean`; it is
  therefore declared explicitly beside Trafilatura. Bootstrap emits a benign
  warning that lxml itself no longer provides that extra.
- The task-local venv did not include pytest after bootstrap, so pytest was
  installed only into `/private/tmp/quasi-sdd-webpage-data/.venv` for the
  required verification command; `scripts/requirements.txt` was not changed to
  include pytest.

## Fix round 1 — valueless metadata attribute

Reviewer finding: valid saved HTML containing `<meta property>` caused
`HTMLParser` to supply `None` for `property`, and metadata extraction called
`.lower()` on that untrusted value.

RED command:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data \
  /private/tmp/quasi-sdd-webpage-data/.venv/bin/python \
  -m pytest tests/test_webpage_cli.py -q -k 'valueless_meta_property'
```

RED output: `1 failed, 10 deselected in 0.03s`, with
`AttributeError: 'NoneType' object has no attribute 'lower'` at
`scripts/webpage/webarchive.py:91`.

Fix: guard the `property` attribute with `isinstance(property_value, str)`
before its case-insensitive comparison. A focused real binary-WebArchive test
now confirms extraction succeeds, preserves the saved title, and falls back to
the saved URL hostname for the absent site name.

GREEN commands:

```bash
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data \
  /private/tmp/quasi-sdd-webpage-data/.venv/bin/python \
  -m pytest tests/test_webpage_cli.py -q -k 'valueless_meta_property'
CLAUDE_PLUGIN_DATA=/private/tmp/quasi-sdd-webpage-data \
  /private/tmp/quasi-sdd-webpage-data/.venv/bin/python \
  -m pytest tests/test_webpage_cli.py -q
git diff --check
```

GREEN output: `1 passed, 10 deselected, 1 warning in 0.16s`; then
`11 passed, 1 warning in 0.17s`; `git diff --check` exited zero. The warning is
the existing urllib3 LibreSSL/OpenSSL environment warning.
