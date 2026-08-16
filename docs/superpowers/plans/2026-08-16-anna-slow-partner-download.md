# Anna Slow Partner Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Anna Slow Partner no-wait as the final deterministic Book download fallback without changing Workflow, Agent, or public CLI-result contracts.

**Architecture:** Keep Anna-specific page acquisition and parsing in `scripts/download/aa.py`, extend the existing supervised browser helper with explicit page kinds, and let `scripts/download/download.py` append one Slow provider to its existing synchronous cascade. Reuse the existing whole-file stream and container validation; no persistent partial state, waitlist loop, provider-result refactor, or background process is introduced.

**Tech Stack:** Python 3.9+, `requests`/`curl_cffi`, BeautifulSoup, SeleniumBase browser helper, pytest.

## Global Constraints

- Source order is exactly Fast default → existing Fast rotations → LibGen → Anna Slow no-wait.
- Slow links are discovered dynamically from `/md5/{md5}` and preserve DOM order.
- Only no-wait links are eligible; countdown/waitlist pages are skipped without sleeping.
- The final file request carries the Slow Partner page as `Referer`.
- Existing whole-file retry, minimum-size check, PDF/EPUB validation, CLI JSON, and `download_from_aa() -> path | None` behavior remain intact.
- No Workflow/Agent/schema/config/version changes, persistent `.part`, Range resume, browser daemon, or new digest policy.

---

### Task 1: Pure Anna Slow page parsers

**Files:**
- Modify: `scripts/download/aa.py`
- Test: `tests/test_download_cli.py`

**Interfaces:**
- Produces: `parse_aa_slow_partner_urls(detail_url: str, html_text: str) -> list[str]`
- Produces: `parse_aa_slow_final_url(partner_url: str, html_text: str) -> str`
- Consumes: BeautifulSoup already used by `aa.py`; add the standard-library
  `html` import for entity decoding and use `urllib.parse.urljoin`/URL parsing.

- [ ] **Step 1: Write failing detail-parser tests**

Add literal HTML fixtures to `tests/test_download_cli.py` that name the two breaks:

```python
def test_aa_slow_partner_parser_preserves_dom_order_and_deduplicates_no_wait():
    mod = _load_module(AA, "aa_slow_partner_order_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, but can be very slow</div>
      <div><a href="/slow_download/id/0/6">Slow Partner Server #6</a>
        — no waitlist, but can be very slow</div>
      <div><a href="/slow_download/id/0/5">Slow Partner Server #5</a>
        — no waitlist, duplicate</div>
    </main>
    """

    assert mod.parse_aa_slow_partner_urls(detail_url, page) == [
        "https://annas-archive.pk/slow_download/id/0/5",
        "https://annas-archive.pk/slow_download/id/0/6",
    ]


def test_aa_slow_partner_parser_excludes_waitlist_viewer_and_unsafe_urls():
    mod = _load_module(AA, "aa_slow_partner_filter_under_test")
    detail_url = "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef"
    page = """
    <main>
      <div><a href="/slow_download/id/0/1">Slow Partner Server #1</a>
        — waitlist, but faster</div>
      <div><a href="https://user:secret@example.org/slow_download/id/0/2">Slow Partner Server #2</a>
        — no waitlist</div>
      <div><a href="javascript:alert(1)">Slow Partner Server #3</a>
        — no waitlist</div>
      <div><a href="/viewer/id">After downloading: Open in our viewer</a></div>
    </main>
    """

    assert mod.parse_aa_slow_partner_urls(detail_url, page) == []
```

- [ ] **Step 2: Run the detail-parser tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'slow_partner_parser_preserves or slow_partner_parser_excludes'
```

Expected: two collected assertion failures caused by the absent parser, not import or fixture errors.

- [ ] **Step 3: Implement the minimal ordered no-wait parser**

In `aa.py`, add a small shared URL predicate and the parser:

```python
def _safe_http_url(value):
    parsed = urllib.parse.urlparse(str(value or ""))
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def parse_aa_slow_partner_urls(detail_url, html_text):
    if not _HAS_BS4:
        return []
    soup = BeautifulSoup(str(html_text or ""), "html.parser")
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        context = " ".join(anchor.parent.get_text(" ", strip=True).split()).lower()
        if not label.startswith("slow partner server") or "no waitlist" not in context:
            continue
        candidate = urllib.parse.urljoin(detail_url, anchor.get("href", ""))
        if (
            _safe_http_url(candidate)
            and "/slow_download/" in urllib.parse.urlparse(candidate).path
            and candidate not in seen
        ):
            seen.add(candidate)
            urls.append(candidate)
    return urls
```

- [ ] **Step 4: Write failing final-URL parser tests**

Add a parameterized test with hand-written expected URLs for these supported shapes: `Download now` anchor, anchor with `download`, `navigator.clipboard.writeText(...)`, `window.location.href=...`, and a visible URL in `code` or `span`. Add one negative test containing credentialed URLs and another `/slow_download/` URL. Each test calls `parse_aa_slow_final_url(partner_url, html)` and asserts the exact URL or `""`.

- [ ] **Step 5: Run the final-URL parser tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q -k 'slow_final_url_parser'
```

Expected: collected assertion failures because the parser is absent.

- [ ] **Step 6: Implement the minimal final-URL parser**

Implement one normalization path for every candidate:

```python
def _normalise_slow_final_url(partner_url, candidate):
    value = html.unescape(str(candidate or "")).replace(r"\/", "/").strip()
    value = urllib.parse.urljoin(partner_url, value)
    if not _safe_http_url(value):
        return ""
    if "/slow_download/" in urllib.parse.urlparse(value).path:
        return ""
    return value
```

`parse_aa_slow_final_url` checks the five approved shapes in the design order and returns the first normalized admissible URL. It returns `""` for countdown-only, waitlist-only, malformed, credentialed, or recursive Slow pages; it does not sleep or refetch.

- [ ] **Step 7: Run the focused parser tests and commit**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'slow_partner_parser or slow_final_url_parser'
git diff --check
```

Expected: all focused tests pass and diff check exits 0.

Commit:

```bash
git add scripts/download/aa.py tests/test_download_cli.py
git commit -m "feat(download): parse Anna slow partners"
```

### Task 2: Page-kind-aware bounded browser access

**Files:**
- Modify: `scripts/download/aa.py`
- Modify: `scripts/download/aa_browser.py`
- Test: `tests/test_download_cli.py`

**Interfaces:**
- Consumes: Task 1 parser-supported Slow page shapes.
- Produces: `_fetch_aa_with_browser(url: str, page_kind: str = "search") -> str`
- Produces: `fetch_aa_page(url: str, *, page_kind: str) -> str`
- Produces: `aa_request(..., headers: dict | None = None)` while preserving existing callers.

- [ ] **Step 1: Write failing browser page-kind tests**

Extend the existing browser-process test to assert the command contains `--page-kind detail` when invoked with `page_kind="detail"`. Add direct behavior tests for:

```python
assert _looks_like_settled_page(
    "detail",
    "https://annas-archive.pk/md5/0123456789abcdef0123456789abcdef",
    "Book details are loaded",
    "<main><h1>Book details are loaded</h1></main>",
)
assert not _looks_like_settled_page("detail", search_url, "results", search_html)
assert _looks_like_settled_page(
    "slow", slow_url, "Download now", '<a download href="https://files.example/book.pdf">Download now</a>'
)
assert _looks_like_settled_page(
    "slow", slow_url, "Wait 20 seconds", '<span class="js-partner-countdown">20</span>'
)
assert not _looks_like_settled_page("slow", slow_url, "Loading", "<main>Loading</main>")
```

The production mutation caught is accepting a search shell as detail/Slow, or omitting the page kind from the supervised helper command.

- [ ] **Step 2: Run browser tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'browser_fallback_is_bounded or browser_page_kind or browser_detail_mode or browser_slow_mode'
```

Expected: collected assertion failures for missing page-kind behavior.

- [ ] **Step 3: Implement explicit page kinds**

In `aa_browser.py`:

- replace `_looks_like_settled_search` internally with `_looks_like_settled_page(page_kind, current_url, body, html)`;
- keep a thin `_looks_like_settled_search(...)` wrapper for the existing direct test contract;
- add `page_kind` to `_fetch` and `--page-kind {search,detail,slow}` with
  default `search` to `main`;
- require two consecutive settled observations exactly as today.

In `aa.py`, make `_fetch_aa_with_browser(url, page_kind="search")` pass `--page-kind`, and name its bounded temporary output `<page_kind>.html` rather than `search.html`.

- [ ] **Step 4: Write failing HTTP-first page-fetch tests**

Add tests where `_request` returns complete response-shaped doubles with `status_code`, `headers`, `text`, and `url`:

- HTTP 200 detail returns its body and never calls browser;
- confirmed DDoS-Guard detail invokes browser with `detail`;
- Anna 403 Slow invokes browser with `slow`;
- ordinary 500 returns `""` and never invokes browser.

Also extend the existing `aa_request` boundary test or add one that passes `headers={"Referer": "..."}` and proves `_request` receives that exact mapping.

- [ ] **Step 5: Run page-fetch tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'fetch_aa_page or aa_request_forwards_headers'
```

Expected: collected assertion failures because the page helper/header argument does not exist.

- [ ] **Step 6: Implement HTTP-first access**

Add:

```python
def fetch_aa_page(url, *, page_kind):
    if page_kind not in {"search", "detail", "slow"}:
        raise ValueError(f"unsupported Anna page kind: {page_kind}")
    try:
        response = _request("GET", url, timeout=30)
    except Exception:
        return ""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if _is_ddos_guard_challenge(response) or (
        response.status_code == 403 and host.startswith("annas-archive.")
    ):
        return _fetch_aa_with_browser(url, page_kind)
    return response.text if response.status_code == 200 else ""
```

Extend `_request`/`aa_request` header forwarding without changing default headers or existing search behavior.

- [ ] **Step 7: Run Task 2 and existing browser tests, then commit**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'aa_browser or fetch_aa_page or aa_request_forwards_headers'
git diff --check
```

Expected: all selected tests pass.

Commit:

```bash
git add scripts/download/aa.py scripts/download/aa_browser.py tests/test_download_cli.py
git commit -m "feat(download): fetch Anna detail and slow pages"
```

### Task 3: Append Slow no-wait to the Book transport cascade

**Files:**
- Modify: `scripts/download/download.py`
- Test: `tests/test_download_cli.py`

**Interfaces:**
- Consumes: `fetch_aa_page`, `parse_aa_slow_partner_urls`, and `parse_aa_slow_final_url` from Tasks 1–2.
- Produces: `_try_aa_slow_download(base_url, md5, dest, fmt) -> bool`
- Preserves: `download_from_aa(...) -> str | None` and current Book-fetch JSON.

- [ ] **Step 1: Write a failing Referer-forwarding test**

Exercise the real `_stream_download` with a response-shaped in-memory requester. The requester must require a `headers` keyword and record it; the assertion is:

```python
assert observed_headers["Referer"] == "https://annas-archive.pk/slow_download/id/0/5"
```

The fake response supplies a payload larger than 10 KiB, content type `application/pdf`, content length, `iter_content`, and `raise_for_status`. This test catches the current bug where the requester branch discards caller headers.

- [ ] **Step 2: Run the Referer test and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q -k 'stream_download_forwards_partner_referer'
```

Expected: one collected failure because `_stream_download` calls the requester without headers.

- [ ] **Step 3: Forward request headers in the existing stream helper**

Change only the requester branch:

```python
request_headers = headers or HEADERS_BROWSER
if requester:
    r = requester("GET", url, timeout=120, stream=True, headers=request_headers)
else:
    r = requests.get(url, headers=request_headers, stream=True, timeout=120)
```

Do not add Range, partial-file, or content-length policy.

- [ ] **Step 4: Write failing Slow cascade tests**

Add one test with two literal no-wait partner pages. Stub only external page/stream boundaries while keeping `_try_aa_slow_download` real:

- detail returns partner #5 then #6;
- #5 resolves to a transfer whose written file fails `_is_valid_book_file`;
- #6 resolves to a valid transfer;
- observed stream headers contain each partner as its own Referer;
- function returns `True`, the second payload remains, and no third call occurs.

Add a high-level `download_from_aa` test proving `_try_aa_slow_download` is not called when Fast or LibGen succeeds, and is called exactly once after both existing stages fail. Add a quota regression where one rotation raises `AAQuotaExhausted`; it must skip remaining Fast rotations but still try LibGen and Slow before re-raising only if both fail.

- [ ] **Step 5: Run cascade tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q \
  -k 'aa_slow_download or book_download_reaches_slow or book_rotation_quota_still_reaches_fallbacks'
```

Expected: collected assertion failures because Slow is not in the cascade and rotation quota currently exits early.

- [ ] **Step 6: Implement the Slow provider and append it once**

Import the three Task 1–2 helpers into `download.py`. Implement:

```python
def _try_aa_slow_download(base_url, md5, dest, fmt):
    detail_url = f"{base_url}/md5/{md5}"
    detail_html = fetch_aa_page(detail_url, page_kind="detail")
    for partner_url in parse_aa_slow_partner_urls(detail_url, detail_html):
        partner_html = fetch_aa_page(partner_url, page_kind="slow")
        download_url = parse_aa_slow_final_url(partner_url, partner_html)
        if not download_url:
            continue
        headers = {**HEADERS_BROWSER, "Referer": partner_url}
        if _stream_download(download_url, dest, headers=headers, requester=aa_request):
            if _is_valid_book_file(dest, fmt):
                return True
            if os.path.exists(dest):
                os.remove(dest)
    return False
```

After LibGen fails, call this helper once, then apply the existing `_aa_verify` identity check before returning `dest`. Change the Stage 2 quota handler from immediate `raise` to storing `quota_error` and `break`, so the already-declared independent fallbacks remain reachable; preserve the final quota exception if LibGen and Slow both fail.

- [ ] **Step 7: Run focused and full download tests, then commit**

Run:

```bash
python3 -m pytest tests/test_download_cli.py -q
git diff --check
```

Expected: the complete download test module passes with no failures.

Commit:

```bash
git add scripts/download/download.py tests/test_download_cli.py
git commit -m "feat(download): add Anna slow fallback"
```

### Task 4: Repository verification

**Files:**
- Verify only; modify production/tests only if a failing gate exposes a defect caused by Tasks 1–3.

**Interfaces:**
- Consumes: all completed task commits.
- Produces: fresh verification evidence for the feature and repository contracts.

- [ ] **Step 1: Run targeted contract suites**

```bash
python3 -m pytest tests/test_download_cli.py tests/test_dead_names.py tests/test_skill_orchestration.py -q
```

Expected: all collected tests pass; existing third-party deprecation warnings may remain unchanged.

- [ ] **Step 2: Run the full Python suite**

```bash
python3 -m pytest -q
```

Expected: all collected tests pass.

- [ ] **Step 3: Run repository consistency checks**

```bash
cmp -s CLAUDE.md AGENTS.md
git diff --check
git status --short --branch
```

Expected: mirror comparison and diff check exit 0; status contains no uncommitted Task 1–3 files.

- [ ] **Step 4: Review scope against the approved design**

Confirm from the final diff that no Workflow bundle, Agent, schema, manifest,
version, waitlist loop, persistent partial state, provider-attempt result, or
unrelated download provider changed. Record any unavoidable deviation before
claiming completion.
