# Webpage Material Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `webpage` as a first-class Collect material that captures one public URL into an Apple WebArchive, derives one inspectable Markdown projection, and produces one canonical reading page through a fixed named Workflow.

**Architecture:** Follow the Image ownership model: `snapshot.webarchive` owns captured page evidence, `source.md` owns the deterministic readable projection, and `webpage.md` owns library metadata and interpretation. A small macOS/WebKit capability performs capture; a new narrow `webpage-agent` owns Identify/Capture/Prepare; the existing Analyse and Audit Agents own the canonical page. The Skill only transports a provisional URL, exact status observations, and typed material results.

**Tech Stack:** Python 3.10+, Swift 6/WebKit on macOS 11+, Trafilatura, Pydantic v2 artifact schemas, TypeScript ES2022 Workflow sources, esbuild-generated Claude Workflow bundles, pytest.

**Design:** `docs/superpowers/specs/2026-08-13-webpage-material-workflow-design.md`

## Global Constraints

- Start implementation with `superpowers:using-git-worktrees`; the primary worktree already contains unrelated uncommitted Translation, OCR, Skill, test, and generated-bundle edits. Do not absorb, overwrite, format, stage, or commit those changes.
- Use `superpowers:test-driven-development` for every behavior change: add one causal failing test, observe the expected failure, write the smallest implementation, then rerun the focused suite.
- Do not modify `topic.webcard`, Topic schemas, Topic orchestration, or Paper acquisition in this phase.
- Do not add Chrome, Playwright, Puppeteer, MHTML, Monolith, WARC, PDF, raw-HTML, or non-macOS capture fallbacks.
- Do not add a retry engine, network-idle heuristic, background process, lock, cursor, capture history, second state file, or compatibility path.
- Do not weaken Stage receipt validation. An ambiguous Capture/Prepare/Analyse writer result returns `needs_observation`; a schema-valid `blocked|failed` remains terminal; an ambiguous Audit remains blocked because disk status cannot prove a clean audit.
- The initial Webpage invocation carries `observation:null`; that means “no observation exists yet,” while retaining the same top-level `{seed,observation,options}` envelope shape as other leaves. Only the read-only Identify operation may run from this form.
- Webpage owner identity is stable on canonical slug + normalized final URL. Title and site are snapshot metadata: a fresh exact observation or a successful second-load Capture may update them without changing the owner route.
- Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.
- Generated `scripts/workflows/artifact-contracts/generated.{mjs,d.mts}` and `workflows/*.mjs` are changed only by `npm run build:workflows`.
- Do not bump plugin versions, publish, or push as part of this implementation plan. Release bookkeeping is a separate explicit action after verification.

---

### Task 1: Define the Webpage artifact and operation identities

**Files:**

- Create: `scripts/schemas/webpage.py`
- Modify: `scripts/schemas/body.py`
- Modify: `scripts/schemas/registry.py`
- Modify: `scripts/schemas/__init__.py`
- Modify: `scripts/schemas/operations.py`
- Modify: `scripts/schemas/SPEC.md`
- Modify: `scripts/schemas/pyproject.toml` (type-list description only; no package-version bump)
- Modify: `scripts/typecheck/typecheck.py`
- Test: `tests/test_schema_registry.py`

**Interfaces:**

- Canonical path: `vault/webpages/{slug}/webpage.md`
- Required frontmatter: `type`, `title`, `url`, `captured_at`
- Optional frontmatter: `authors`, `published`, `site`, `themes`, `topics`, `rating`
- Body: one H1, then required `Summary` and `Content` H2 sections
- Operations: `webpage.identify|capture|prepare|analyse|audit`

- [ ] **Step 1: Write failing schema and catalog tests**

Add one minimal valid page and one invalid technical-field case:

```python
def test_webpage_schema_and_body_contract(tmp_path: Path) -> None:
    path = tmp_path / "vault/webpages/example-org-example/webpage.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """---
type: webpage
title: Example page
url: https://example.org/page
captured_at: 2026-08-13T12:34:56Z
---
# Example page

## Summary

A concise account of the page.

## Content

### Original section

The complete cleaned page content.
""",
        encoding="utf-8",
    )

    result = check_file(path)
    assert result["frontmatter_errors"] == []
    assert result["body_violations"] == []
    contract = artifact_contract_for_type("webpage")
    assert contract["path_pattern"] == "vault/webpages/{slug}/webpage.md"
    assert contract["document"]["section_order"] == ["Summary", "Content"]


@pytest.mark.parametrize("field", ["snapshot", "format", "sha256", "bytes"])
def test_webpage_rejects_snapshot_technical_frontmatter(field: str) -> None:
    value = {
        "type": "webpage",
        "title": "Example page",
        "url": "https://example.org/page",
        "captured_at": "2026-08-13T12:34:56Z",
        field: "not-semantic-metadata",
    }
    with pytest.raises(ValidationError):
        WebpageSchema.model_validate(value)
```

Add one direct operation-catalog assertion for exact kind, phase, effect, Agent, and path templates. Do not snapshot the whole Python dictionary.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m pytest tests/test_schema_registry.py -q -k 'webpage'
```

Expected: import/registry failures because `WebpageSchema`, `WEBPAGE_BODY`, and Webpage operations do not exist.

- [ ] **Step 3: Add the strict frontmatter model**

Implement `WebpageSchema` with `extra="forbid"` and strict fields. Parse `published` and `captured_at` from YAML strings with field-local `strict=False`; validate that `captured_at` is timezone-aware UTC with zero microseconds. Keep URL as a string field with an `http|https`, no-credentials validator; canonical URL normalization remains owned by the Webpage capability rather than being duplicated in the schema.

The effective model shape is:

```python
class WebpageSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["webpage"]
    title: Title
    url: WebURL
    captured_at: datetime = Field(strict=False)
    authors: list[Name] = Field(default_factory=list)
    published: date | None = Field(default=None, strict=False)
    site: ShortString | None = None
    themes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    rating: Rating | None = None
```

- [ ] **Step 4: Add the body contract without weakening other artifacts**

Add a `freeform` `BlockKind` used only inside a known section. In `check_body`, `freeform` accepts any non-empty detected block shape but still participates in required-section, unknown-H2, alias, and heading-level checks. This avoids teaching the checker that arbitrary top-level H2s are valid.

Define:

```python
WEBPAGE_BODY = BodySchema(
    type_name="webpage",
    artifact_schema_version="quasi.artifact.webpage/0.1",
    path_pattern="vault/webpages/{slug}/webpage.md",
    identity_fields=["title", "url", "site"],
    h1="使用 frontmatter.title",
    sections=[
        BodySection(
            h2="Summary",
            kind="paragraph",
            required=True,
            description="简要说明页面内容、论点及其知识库价值",
        ),
        BodySection(
            h2="Content",
            kind="freeform",
            required=True,
            description="逐字保留 source.md 的完整清洗后正文；内部标题从 H3 开始",
        ),
    ],
)
```

Register and export the model/body pair and document it in `SPEC.md`. Do not change unrelated Body schemas.

- [ ] **Step 5: Register only the five operation identities**

Add these catalog rows; behavior remains in the later descriptor-row task:

```python
"webpage.identify": {
    "kinds": ["webpage"], "phase": "Search", "effect": "readonly",
    "agent": "quasi:webpage-agent", "artifacts": {},
},
"webpage.capture": {
    "kinds": ["webpage"], "phase": "Acquire", "effect": "writer",
    "agent": "quasi:webpage-agent",
    "artifacts": {"snapshot": "vault/webpages/{slug}/snapshot.webarchive"},
},
"webpage.prepare": {
    "kinds": ["webpage"], "phase": "Prepare", "effect": "writer",
    "agent": "quasi:webpage-agent",
    "artifacts": {
        "snapshot": "vault/webpages/{slug}/snapshot.webarchive",
        "output": "processing/webpages/{slug}/source.md",
    },
},
"webpage.analyse": {
    "kinds": ["webpage"], "phase": "Analyse", "effect": "writer",
    "agent": "quasi:analyse-agent",
    "artifacts": {"output": "vault/webpages/{slug}/webpage.md"},
},
"webpage.audit": {
    "kinds": ["webpage"], "phase": "Audit", "effect": "writer",
    "agent": "quasi:audit-agent",
    "artifacts": {"target": "vault/webpages/{slug}/webpage.md"},
},
```

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
python3 -m pytest tests/test_schema_registry.py -q
git diff --check
```

Commit only Task 1 files:

```bash
git commit -m "feat: define webpage artifact contract"
```

---

### Task 2: Parse WebArchives and derive stable Markdown

**Files:**

- Create: `scripts/webpage/__init__.py`
- Create: `scripts/webpage/webarchive.py`
- Modify: `scripts/requirements.txt`
- Create: `tests/test_webpage_cli.py`

**Interfaces:**

- `normalize_web_url(raw: str) -> str`
- `collision_slug(base_slug: str, normalized_url: str) -> str`
- `read_webarchive(path: Path) -> WebArchiveDocument`
- `extract_webarchive(snapshot: Path, output: Path) -> ExtractionResult`

- [ ] **Step 1: Write failing pure capability tests**

Build binary plist fixtures in the test with `plistlib.dumps(..., fmt=plistlib.FMT_BINARY)`. Cover only the load-bearing cases:

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443", "https://example.com/"),
        ("http://Example.COM:80/a?q=2#frag", "http://example.com/a?q=2"),
    ],
)
def test_normalize_web_url(raw: str, expected: str) -> None:
    assert normalize_web_url(raw) == expected


def test_webarchive_extraction_uses_saved_main_resource(tmp_path: Path) -> None:
    snapshot = write_webarchive_fixture(
        tmp_path,
        url="https://example.org/page",
        html="""<html><head><title>Saved title</title>
        <meta property="og:site_name" content="Example Site"></head>
        <body><main><h1>Saved title</h1><h2>Argument</h2>
        <p>This text came from the saved snapshot.</p></main></body></html>""",
    )
    output = tmp_path / "source.md"

    result = extract_webarchive(snapshot, output)

    assert result.url == "https://example.org/page"
    assert result.title == "Saved title"
    assert result.site == "Example Site"
    assert "This text came from the saved snapshot." in output.read_text()
    assert not re.search(r"^#{1,2} ", output.read_text(), re.MULTILINE)
```

Also test credential rejection, invalid/non-HTML main resource, empty Trafilatura result, deterministic eight-hex collision suffix, and no-clobber publication. Do not enumerate arbitrary plist corruption shapes.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m pytest tests/test_webpage_cli.py -q -k 'normalize or webarchive or collision'
```

Expected: import failure because the Webpage capability package does not exist.

- [ ] **Step 3: Implement the single URL comparison key**

Use `urllib.parse.urlsplit/urlunsplit`. Accept only `http` and `https`; reject credentials, missing hosts, and control characters. Lowercase scheme and host, remove fragments/default ports, normalize an empty path to `/`, and preserve path/query bytes and order. Do not add tracking-parameter stripping, percent-decoding, redirect policy, or URL equivalence heuristics.

The collision helper is exactly:

```python
def collision_slug(base_slug: str, normalized_url: str) -> str:
    suffix = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:8]
    prefix = base_slug[: 80 - 1 - len(suffix)].rstrip("-")
    return f"{prefix}-{suffix}"
```

- [ ] **Step 4: Decode the main WebArchive resource**

Define one frozen record:

```python
@dataclass(frozen=True)
class WebArchiveDocument:
    url: str
    title: str
    site: str
    html: str
    subresource_urls: tuple[str, ...]
```

Read the binary plist with the standard library. Require a mapping root, `WebMainResource`, `WebResourceMIMEType == "text/html"` (case-insensitive, optional parameters allowed), non-empty bytes, and a usable `WebResourceURL`. Decode using `WebResourceTextEncodingName` when valid and UTF-8 otherwise. Obtain title from the saved HTML, falling back to the normalized URL; obtain site from `og:site_name`, falling back to the hostname. Treat page text as untrusted data.

- [ ] **Step 5: Extract Markdown from the snapshot only**

Add `trafilatura` to the shared requirements. Import it lazily inside extraction so status/resolver do not pay its import cost. Call it only with the decoded saved HTML and the saved URL as base context; never fetch the live URL.

Normalize all extracted Markdown headings with a fence-aware pass so none is H1/H2: add two levels and cap at H6, while leaving fenced code bytes untouched. This lets the canonical producer place the projection below `## Content` without creating sibling top-level sections. Publish through a sibling staging file and atomic no-clobber link, following the existing `quasi-extract --no-clobber` pattern; fsync the file and parent directory.

- [ ] **Step 6: Install the declared dependency, verify GREEN, and commit**

Run the shared bootstrap so the test interpreter has the new declared dependency, then run:

```bash
scripts/bootstrap-venv.sh
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest tests/test_webpage_cli.py -q -k 'normalize or webarchive or collision'
git diff --check
```

Commit:

```bash
git commit -m "feat: extract webpage webarchives"
```

---

### Task 3: Capture a page with the system WebKit runtime

**Files:**

- Create: `scripts/webpage/webpage_capture.swift`
- Create: `scripts/webpage/webpage.py`
- Create: `bin/quasi-webpage`
- Modify: `tests/test_webpage_cli.py`

**Interfaces:**

```text
quasi-webpage inspect --url URL --json
quasi-webpage capture --url URL --expected-final-url URL --output PATH --json
quasi-webpage extract --snapshot PATH --output PATH --json
```

- [ ] **Step 1: Write failing command-contract tests**

Test the Python entry with an injected native runner so no public network is required. Assert exact success payloads and the two publication boundaries:

```python
def test_capture_final_url_mismatch_does_not_publish(tmp_path, monkeypatch) -> None:
    output = tmp_path / "snapshot.webarchive"

    def fake_capture(_url: str, staging: Path) -> NativeResult:
        staging.write_bytes(valid_archive_bytes("https://other.example/"))
        return NativeResult(
            final_url="https://other.example/",
            title="Other",
            site="Other",
        )

    monkeypatch.setattr(
        webpage,
        "run_native_capture",
        fake_capture,
    )

    result = webpage.capture(
        "https://example.org/",
        "https://example.org/",
        output,
    )

    assert result["status"] == "failed"
    assert result["issue"]["code"] == "webpage.capture_identity_changed"
    assert not output.exists()
```

Also assert an existing output is never overwritten and `extract` exposes the Task 2 projection through the public command.

- [ ] **Step 2: Run RED**

Run:

```bash
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest tests/test_webpage_cli.py -q -k 'capture or command'
```

Expected: command module/shim/native interfaces do not exist.

- [ ] **Step 3: Implement the offscreen native loader**

The Swift helper has only `inspect URL` and `capture URL STAGING_PATH` modes. On `@MainActor`, create a zero-frame `WKWebView` with `WKWebsiteDataStore.nonPersistent()`, attach one `WKNavigationDelegate`, load once, wait for `didFinish`, wait exactly 750 ms, and enforce one 60-second total timeout. Do not create an `NSWindow` or launch Safari.

After settle, evaluate only document metadata needed by the contract, then in Capture mode call:

```swift
let data = try await webView.createWebArchiveData()
try data.write(to: stagingURL)
```

Emit one JSON object containing `final_url`, `title`, and `site`; Capture also reports the exact staging path. Known navigation, timeout, evaluation, or archive errors emit one closed error object and a non-zero exit. The helper never retries or detaches.

- [ ] **Step 4: Implement Python compilation and publication**

Compile with:

```text
swiftc -O -parse-as-library -framework WebKit webpage_capture.swift -o $CLAUDE_PLUGIN_DATA/bin/quasi-webpage-webkit
```

Reuse the binary while its mtime is at least the source mtime, matching the existing Apple STT pattern. Missing macOS 11+, `swiftc`, WebKit, or a successful compile returns `webpage.capture_unavailable`; do not silently select another backend.

For Capture, give Swift a unique sibling staging path. After it exits, parse the staged WebArchive with `read_webarchive`, require the archive URL and native final URL to normalize to `--expected-final-url`, set the staging inode mtime to the exact whole-second UTC `captured_at`, fsync, and only then publish no-clobber. The correct timestamp is therefore visible atomically with the bytes. Return:

```json
{
  "schema_version": "quasi.webpage.capture/0.1",
  "status": "complete",
  "output_path": "vault/webpages/example/snapshot.webarchive",
  "final_url": "https://example.org/",
  "title": "Example",
  "site": "example.org",
  "captured_at": "2026-08-13T12:34:56Z",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "size": 1234,
  "write_state": "written"
}
```

Inspect and Extract get parallel versioned success/error envelopes. Paths in JSON remain the caller's lexical path; absolute resolved paths stay internal.

- [ ] **Step 5: Add one macOS-gated local integration smoke test**

Serve a fixture HTML, CSS, and tiny image from `ThreadingHTTPServer` bound to loopback. Invoke real Inspect and Capture, then parse the result and assert:

```python
assert archive.url == inspected["final_url"]
assert "Local fixture content" in archive.html
assert any(url.endswith("/fixture.css") for url in archive.subresource_urls)
```

Skip only when the platform is not macOS or `swiftc` is absent. Never contact a public website.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest tests/test_webpage_cli.py -q
bash -n bin/quasi-webpage
git diff --check
```

Commit:

```bash
git commit -m "feat: capture webpage webarchives"
```

---

### Task 4: Make Webpage ownership and durable progress observable

**Files:**

- Modify: `scripts/vault/resolve.py`
- Modify: `scripts/status/status.py`
- Modify: `tests/test_vault_resolve.py`
- Modify: `tests/test_status_cli.py`

**Interfaces:**

- Resolver item: `{kind:"webpage",slug,url}`
- Status route: `quasi-status --kind webpage --slug SLUG --json`
- Status facts: `kind`, `snapshot`, `prepared`, `canonical`, `captured_at`
- Status identity: `null | {slug,title,url,site}`

- [ ] **Step 1: Write failing resolver tests**

Cover four causal states: no owner, canonical same-URL owner, snapshot-only same-URL owner, and duplicate URL owners. Add one collision assertion showing that an occupied requested slug with a different URL yields the deterministic hash-suffixed slug instead of reusing the wrong owner.

The successful partial-owner row must point at the artifact that proves ownership:

```python
assert row == {
    "kind": "webpage",
    "slug": "proposed-slug",
    "vault_slug": "existing-owner",
    "path": "vault/webpages/existing-owner/snapshot.webarchive",
    "match": "url",
}
```

Do not add title similarity, site similarity, fuzzy URL matching, or a global compatibility scan.

- [ ] **Step 2: Write failing status tests**

Add absent, snapshot-only, prepared, canonical-complete, and snapshot/canonical identity-mismatch cases. Assert the exact envelope:

```python
assert payload["facts"] == {
    "kind": "webpage",
    "snapshot": {"path": snapshot_path, "present": True, "usable": True},
    "prepared": {"path": source_path, "present": True, "usable": True},
    "canonical": {"path": canonical_path, "present": True, "usable": True},
    "captured_at": "2026-08-13T12:34:56Z",
}
assert payload["identity"] == {
    "slug": slug,
    "title": "Saved title",
    "url": "https://example.org/page",
    "site": "Example Site",
}
```

Add one scan test proving any of the three exact roots discovers a safe Webpage slug once.

- [ ] **Step 3: Run RED**

Run:

```bash
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q -k 'webpage'
```

Expected: Webpage kind is rejected or absent.

- [ ] **Step 4: Extend the resolver at its existing boundary**

For Webpage only, build one normalized-URL index over safe `vault/webpages/<slug>/` directories. Prefer a readable canonical frontmatter URL; when canonical is absent/unusable, read the WebArchive main resource URL. Resolve URL before exact slug so a proposed slug cannot steal an owner with another URL. Return zero/one/multiple results without choosing among duplicates.

If no URL owner exists and the proposed slug belongs to another URL, return the `collision_slug()` suggestion after proving that suffixed path is not already another owner. Keep Book/Paper/Talk/Author behavior byte-for-byte unchanged.

- [ ] **Step 5: Add the exact status observer**

Implement `webpage_status(root, slug)` by expanding operation-catalog paths. Use specialized observations:

- snapshot usable = regular non-empty file + parseable WebArchive + non-empty HTML main resource;
- prepared usable = regular non-empty UTF-8 Markdown;
- canonical usable = existing canonical frontmatter observation plus title/normalized URL/site/captured-at coherence when snapshot is present; an omitted optional `site` projects to the URL hostname before comparison.

Derive `captured_at` from snapshot mtime, normalized to UTC whole seconds. Use snapshot identity first; use canonical identity only when snapshot is missing. If both exist and disagree, keep snapshot identity and mark canonical unusable. Do not run Trafilatura or semantic readability heuristics from status.

Add the `material_status` branch, CLI choice, and scan roots. Keep `quasi.status/0.2` and `quasi.status-scan/0.2` unchanged.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest tests/test_vault_resolve.py tests/test_status_cli.py -q
git diff --check
```

Commit only the resolver/status hunks and their tests:

```bash
git commit -m "feat: observe webpage material state"
```

---

### Task 5: Define the narrow Agent and operation descriptors

**Files:**

- Create: `agents/webpage-agent.md`
- Modify: `agents/analyse-agent.md`
- Create: `scripts/workflows/operations/rows/webpage.mts`
- Create: `scripts/workflows/operations/catalogs/webpage.mts`
- Modify: `scripts/build-workflows.mjs` (`ARTIFACT_CONTRACTS` only in this task)
- Generated: `scripts/workflows/artifact-contracts/generated.mjs`
- Generated: `scripts/workflows/artifact-contracts/generated.d.mts`
- Generated: existing `workflows/*.mjs` affected by the regenerated catalog
- Modify: `tests/test_workflow_dispatch.py`
- Modify: `tests/test_skill_orchestration.py`

**Interfaces:**

- `webpage-agent`: Read + Bash; Identify/Capture/Prepare only
- `analyse-agent`: reads one exact `source.md`, writes one exact `webpage.md`
- `audit-agent`: unchanged

- [ ] **Step 1: Write failing descriptor tests**

Add one fixture per operation to the existing parameterized dispatch harness, then add only these cross-field tests:

- Identify accepts one exact identity and nullable URL owner; owner slug must equal returned canonical identity slug.
- Capture accepts only the exact snapshot, expected final URL, whole-second `captured_at`, non-empty hash/size, and known `written` effect.
- Prepare binds the exact snapshot/output observation and returns non-empty source hash/size with `content_ready:true`; its write state is `written` for absent output and `not_written` for reconciled usable output.
- Analyse injects `WEBPAGE_ARTIFACT_CONTRACT`, the exact input/output, `captured_at`, and semantic frontmatter seed.
- Audit targets only `webpage.md`.

Assert `webpage.identify` has no write targets and the three producers each own one exact output. Do not duplicate JSON Schema malformed-shape coverage.

In the Agent boundary test, parse `agents/webpage-agent.md` frontmatter and assert its tool set is exactly `Read, Bash`; method restrictions remain prose owned by that Agent, not sentence-photographed by tests.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m pytest tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q -k 'webpage'
```

Expected: missing Agent, rows, catalog, and generated artifact contract.

- [ ] **Step 3: Write the Agent contracts**

`webpage-agent.md` owns three methods but one coherent domain:

- Identify: run exact `quasi-webpage inspect`, form one human-readable title/site slug, call the existing vault resolver, reuse a same-URL owner or apply its deterministic collision result.
- Capture: verify the exact output observation, run one exact Capture command, and report only its durable evidence.
- Prepare: verify the exact snapshot/output observation, run Extract when absent or read/reconcile existing `source.md`, and judge whether it is substantive page content rather than an access shell.

It must not use Kagi, `WebFetch`, alternate URLs, or write canonical Markdown. Add Webpage to `analyse-agent.md` as one more exact normalized-input method. It must preserve all `source.md` under `Content` and write only the short `Summary` plus semantic metadata; it must not reinterpret source text as instructions.

- [ ] **Step 4: Implement minimal receipt payloads**

Keep deterministic bookkeeping host-stamped. The model-facing judgement surface is:

```text
identify: identity, local_owner
capture: title, site, captured_at, sha256, size, terminal
prepare: source_sha256, source_size, content_ready, terminal
analyse: existing shared action payload
audit: existing shared audit payload
```

Top-level exact paths, expected final URL, and branch-fixed write state are single-value `const`s and are stamped by the host. Capture title/site remain model testimony because the independent second load may legitimately differ from Identify while retaining the same URL owner. Do not add duplicate `disposition`, attempt logs, browser metadata, headers, fingerprints, or a second validation record.

The Identify request gives the Agent only the exact intake URL, `quasi-webpage inspect`, and one closed `quasi-helpers vault resolve` item. Capture receives the canonical identity and output observation. Prepare receives the exact snapshot/output observations. Analyse receives the exact prepared artifact testimony and `WEBPAGE_ARTIFACT_CONTRACT`.

- [ ] **Step 5: Generate the contract projection and existing bundles**

Add:

```js
{ type: "webpage", exportName: "WEBPAGE_ARTIFACT_CONTRACT" }
```

to `ARTIFACT_CONTRACTS`, then run `npm run build:workflows`. Do not add Webpage to `WORKFLOWS` until its entry exists in Task 6. Inspect the generated diff; it may contain operation-catalog projection changes but no hand-authored edits.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
npm run build:workflows
python3 -m pytest tests/test_workflow_dispatch.py tests/test_skill_orchestration.py -q -k 'webpage or agent'
npx tsc --noEmit
git diff --check
```

Commit source, tests, and generated outputs together:

```bash
git commit -m "feat: define webpage workflow operations"
```

---

### Task 6: Add the typed named Webpage Workflow

**Files:**

- Create: `scripts/workflows/contracts/webpage.mts`
- Create: `scripts/workflows/plans/webpage.mts`
- Create: `scripts/workflows/webpage.entry.mts`
- Modify: `scripts/workflows/shared/material-input.mts`
- Modify: `scripts/workflows/shared/material-result.mts`
- Modify: `scripts/build-workflows.mjs` (`WORKFLOWS`)
- Generated: `workflows/webpage.mjs`
- Generated: any other bundle changed by the shared type/catalog projection
- Create: `tests/test_webpage_plan.py`
- Modify: `tests/test_material_result.py`
- Modify: `tests/test_workflow_entries.py`

**Interfaces:**

```ts
type WebpageSeed =
  | { state: "provisional"; url: string }
  | {
      state: "canonical";
      material_slug: string;
      identity: { slug: string; title: string; url: string; site: string };
    };
```

- [ ] **Step 1: Write failing parser/result tests**

Add tests proving:

- provisional accepts exact `{seed,observation:null,options:{}}` and rejects any writer observation;
- canonical requires one exact `webpage` status with matching slug and either null identity or the same normalized URL owner; observed title/site become the effective identity;
- Webpage route/key is `webpage:<slug>`;
- `LeafResumeSeed` transports the canonical Webpage seed and empty options;
- complete results accept `snapshot`, `normalized_text`, and `canonical` roles.

Do not add a Webpage `LeafGate` or `userDecision` case.

- [ ] **Step 2: Write failing plan journeys**

Create a focused `tests/test_webpage_plan.py` using the existing Workflow harness. Cover:

```python
def test_webpage_identify_requests_first_exact_observation() -> None:
    report = run_webpage(
        provisional_webpage_input("https://example.org/page"),
        [identify_complete(slug="example-org-page")],
    )
    assert operation_names(report) == ["webpage.identify"]
    assert report["result"]["terminal"] == "needs_observation"
    assert report["result"]["routes"] == [
        {"kind": "webpage", "slug": "example-org-page"}
    ]


def test_webpage_empty_status_runs_linear_pipeline() -> None:
    report = run_webpage(
        canonical_webpage_input(),
        [capture_complete(), prepare_complete(), analyse_complete(), audit_complete()],
    )
    assert operation_names(report) == [
        "webpage.capture",
        "webpage.prepare",
        "webpage.analyse",
        "webpage.audit",
    ]
    assert report["pipelineCalls"] == 0
    assert report["result"]["terminal"] == "complete"
```

Add one parameterized durable-progress test for snapshot/prepared/canonical skipping; one writer-ambiguity test for Capture, Prepare, and Analyse; one schema-valid failure passthrough; and one audit repair journey. Do not cross-product all receipt fields.

In the empty-status journey, make Capture return a title/site different from the read-only Identify seed while retaining the same final URL, and assert the Analyse request uses the Capture title/site. This protects the deliberate two-load boundary without adding a general identity-reconciliation subsystem.

- [ ] **Step 3: Run RED**

Run:

```bash
python3 -m pytest tests/test_material_result.py tests/test_webpage_plan.py tests/test_workflow_entries.py -q -k 'webpage'
```

Expected: missing Webpage types, parser, plan, and entry.

- [ ] **Step 4: Extend only the shared material unions**

Add `webpage` to `StatusKind`, `MaterialKind`, `ObservationRoute`, and `ObservationKey`; add `snapshot` to `ExactArtifactRef.role`; add one Webpage branch to `LeafResumeSeed`. Update route parsing/key construction. Do not add Webpage to Author or Topic composition unions.

- [ ] **Step 5: Implement the closed input parser**

Use the same top-level keys in both forms:

```ts
{ seed, observation, options }
```

Require `options` to be exactly empty. Provisional requires `observation === null` and a syntactically valid credential-free HTTP(S) URL; this is intake rejection, not URL normalization. Canonical requires a valid exact status. The closed facts are:

```ts
interface WebpageStatusFacts {
  kind: "webpage";
  snapshot: ArtifactObservation;
  prepared: ArtifactObservation;
  canonical: ArtifactObservation;
  captured_at: string | null;
}
```

Validate the three exact paths and UTC whole-second timestamp. If status identity is present, require its slug and normalized URL to match the seed, then adopt its observed title/site as the effective identity for subsequent requests. This is route admission, not a second status validator, and it lets a snapshot produced after an ambiguous Capture resume safely when only mutable page metadata changed.

- [ ] **Step 6: Implement the linear plan**

The provisional branch dispatches Identify with the internal bookkeeping slug `webpage-intake`; it never writes. On complete, use a same-URL local owner when present and immediately return:

```ts
needsObservationMaterialResult(
  resultSeed({ requestedSlug: null, canonicalSlug: identity.slug }),
  [{ kind: "webpage", slug: identity.slug }],
  {
    route: { kind: "webpage", slug: identity.slug },
    seed: { state: "canonical", material_slug: identity.slug, identity },
    options: {},
  },
)
```

The canonical branch reads only its fresh status and selects the first incomplete durable stage:

1. Capture only when snapshot is unusable. On success, keep the owner slug/URL and adopt the Capture receipt's title/site for Prepare/Analyse.
2. Prepare only when projection is unusable; when Analyse is needed and prepared is already usable, dispatch Prepare in reconcile mode to obtain semantic readiness and exact hash/size testimony.
3. Analyse when canonical is unusable. If this invocation just created a missing snapshot beside an older canonical page, force Analyse repair so `captured_at` and content match the new snapshot.
4. Audit once; on an exact `webpage.md` semantic escalation, Analyse repair once and re-audit once.

Capture/Prepare/Analyse `unknown_outcome|incoherent_complete` returns exact `needs_observation`. A receipt terminal `blocked|failed` passes through. Identify ambiguity and Audit ambiguity return blocked. A second dirty audit returns `workflow.repair_exhausted`. Never call `pipeline()`.

Complete with exactly:

```ts
[
  { role: "snapshot", path: `vault/webpages/${slug}/snapshot.webarchive` },
  { role: "normalized_text", path: `processing/webpages/${slug}/source.md` },
  { role: "canonical", path: `vault/webpages/${slug}/webpage.md` },
]
```

- [ ] **Step 7: Add the entry and build projection**

Create `webpage.entry.mts` with phases Search, Acquire, Prepare, Analyse, and Audit. Add one `WORKFLOWS` row with `name/kind:"webpage"`, run the generator, and never edit the bundle by hand.

- [ ] **Step 8: Verify GREEN and commit**

Run:

```bash
npm run build:workflows
python3 -m pytest tests/test_material_result.py tests/test_webpage_plan.py tests/test_workflow_entries.py -q -k 'webpage'
npm run check:workflows
git diff --check
```

Commit:

```bash
git commit -m "feat: add webpage material workflow"
```

---

### Task 7: Route Webpage through the thin Collect Skill

**Files:**

- Modify: `skills/collect-material/SKILL.md`
- Modify: `tests/test_skill_orchestration.py`
- Modify identically: `AGENTS.md`
- Modify identically: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SKILL_ORCHESTRATION.md`

**Interfaces:**

- Collect mapping: `webpage -> $CLAUDE_PLUGIN_ROOT/workflows/webpage.mjs`
- Initial input: `{seed:{state:"provisional",url}, observation:null, options:{}}`
- Resume: existing direct-leaf `needs_observation` pump
- Pre/post status: exact `quasi-status --kind webpage --slug SLUG --json` once a canonical route exists

- [ ] **Step 1: Write failing Skill coherence tests**

Extend the parsed closed manifest with:

```python
"webpage": {
    "entry": "$CLAUDE_PLUGIN_ROOT/workflows/webpage.mjs",
    "required": ["seed", "observation", "options"],
    "optional": [],
    "seed_keys": ["state", "url"],
    "option_keys": [],
    "initial_observation": None,
}
```

Add a semantic AST/JSON test that the initial Webpage envelope carries the caller URL as data and `observation:null`. Reuse the existing generic `needs_observation` test; do not pin Chinese prose or reproduce stage names.

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m pytest tests/test_skill_orchestration.py tests/test_dead_names.py -q -k 'collect or webpage'
```

Expected: the closed Collect map lacks Webpage.

- [ ] **Step 3: Add the one special initial transport rule**

Teach Collect that an exact public URL is a Webpage intake when the user asks to preserve the webpage itself; a URL explicitly presented as a Paper/Book clue stays with that material kind. Webpage starts with:

```python
workflow_input = {
    "seed": {"state": "provisional", "url": exact_url},
    "observation": None,
    "options": {},
}
result = Workflow(scriptPath=entry, args=workflow_input)
```

On `needs_observation`, use the existing direct-leaf pump: run exact status for each returned route, copy `resume_seed.{seed,options}` byte-for-byte, and call the same named entry. Preserve the existing two unchanged-observation stop rule. After complete, re-observe the canonical Webpage route and require snapshot, prepared, and canonical artifacts to be present/usable and equal to returned refs.

Do not put Identify, Capture, Prepare, WebKit, slugging, timeout, extraction, or audit language in the Skill.

- [ ] **Step 4: Update active documentation at its owning level**

Update the mirrored maintainer guides with the new material kind and public CLI, then copy the same bytes to both files. Update Architecture with artifact ownership, Agent write ownership, status route, and named entry. Update Skill orchestration only for the pre-observation exception and exact resume. Update README’s user-facing capability and data-layout lists.

Do not edit `docs/GRAPH_COLLABORATION.md` unless an exact stale material-kind list is found; the existing unknown-writer rule already covers Webpage. Do not add a changelog release entry or version number yet.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
python3 -m pytest tests/test_skill_orchestration.py tests/test_dead_names.py -q
cmp -s CLAUDE.md AGENTS.md
claude plugin validate .
git diff --check
```

Commit:

```bash
git commit -m "docs: route webpage collection"
```

---

### Task 8: Verify the complete feature without release side effects

**Files:**

- Verify only; modify a task-owned source/test only if a failing check exposes a real defect

- [ ] **Step 1: Run the focused Webpage suite**

```bash
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest \
  tests/test_webpage_cli.py \
  tests/test_schema_registry.py \
  tests/test_vault_resolve.py \
  tests/test_status_cli.py \
  tests/test_workflow_dispatch.py \
  tests/test_material_result.py \
  tests/test_webpage_plan.py \
  tests/test_workflow_entries.py \
  tests/test_skill_orchestration.py \
  tests/test_dead_names.py -q
```

Expected: all pass, including the real local WebKit smoke on macOS.

- [ ] **Step 2: Verify generated code and the full repository**

```bash
npm run check:workflows
"${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}/.venv/bin/python" -m pytest -q
cmp -s CLAUDE.md AGENTS.md
claude plugin validate .
git diff --check
```

Do not claim completion from focused tests alone.

- [ ] **Step 3: Inspect package growth and scope**

Record, but do not optimize against, the feature’s actual source/generated delta:

```bash
git diff --stat 3364c35..HEAD
wc -c workflows/*.mjs
git status --short
```

Confirm the changed paths contain no Topic implementation, browser fallback, retry framework, version bump, or unrelated dirty-worktree content. Generated bundle growth is acceptable only when traceable to the new Webpage catalog/entry.

- [ ] **Step 4: Request final code review**

Use `superpowers:requesting-code-review` against the approved design and this plan. Resolve only load-bearing findings, rerun the affected focused test and the final verification commands, and commit any correction under a narrowly named fix commit.

- [ ] **Step 5: Hand off through the branch-finishing workflow**

Use `superpowers:finishing-a-development-branch` to present integration options. Do not version, push, or publish until the user explicitly chooses that action.
