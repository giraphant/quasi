# Webpage Material Workflow Design

**Status:** Approved in conversation on 2026-08-13.

## Goal

Add `webpage` as a first-class material collected through one fixed named
Workflow. A successful run preserves the page as a single WebArchive snapshot
and creates a canonical Markdown reading artifact derived from that exact
snapshot.

The design follows the Image ownership model: the captured payload and the
Markdown semantic layer are both authoritative for different facts. It does
not turn a Topic evidence card into a material or put webpage-specific work in
the outer Skill.

## Product boundary

The first version accepts one public `http` or `https` URL on macOS 11 or
newer. `collect-material` recognizes `webpage` beside Paper, Book, Talk,
Translation, and Author and routes it to `workflows/webpage.mjs`. One Workflow
invocation owns one logical webpage.

The capture carrier is Apple WebArchive. `WKWebView.createWebArchiveData`
preserves the current DOM and loaded rendering subresources in one file without
requiring Chrome, Playwright, or Puppeteer. WebArchive is primarily readable by
WebKit, so the canonical Markdown page is also the portable reading copy.

The first version is intentionally macOS-only. It has no alternate capture
backend.

## Chosen architecture

`webpage` becomes a complete material boundary, not merely a Workflow filename:

- `MaterialKind`, `StatusKind`, observation route, and material result support
  `webpage`;
- the schema registry owns a `webpage` artifact contract;
- the operation catalog owns the Webpage operation names and path templates;
- `quasi-status --kind webpage --slug SLUG --json` observes its exact durable
  artifacts;
- `workflows/webpage.mjs` is a generated named leaf entry; and
- `collect-material` selects that entry and transports its typed results.

The existing `topic.webcard` operation is unchanged in this phase. A later,
separate change may make Topic reference first-class Webpage materials and
retire Topic-owned cards.

## Artifact model

One Webpage owns three durable artifacts:

```text
vault/webpages/<slug>/snapshot.webarchive
vault/webpages/<slug>/webpage.md
processing/webpages/<slug>/source.md
```

Their ownership is distinct:

- `snapshot.webarchive` is the captured evidence layer. It owns the page state
  and loaded resources present at capture time.
- `source.md` is a deterministic, user-inspectable projection of the main
  document extracted from that snapshot. It is an analysis input, not a second
  canonical page.
- `webpage.md` is the semantic knowledge layer. It owns library metadata, a
  short explanation, and the readable main content.

The snapshot path is derived from the entity directory and is not repeated in
frontmatter. Snapshot format, byte size, and hash are technical facts observed
from the payload and are not persisted in `webpage.md`.

### Canonical Markdown contract

Required frontmatter:

```yaml
type: webpage
title: Example title
url: https://example.org/final-url
captured_at: 2026-08-13T12:34:56Z
```

Optional semantic fields are `authors`, `published`, `site`, `themes`,
`topics`, and `rating`. Empty optional arrays are omitted according to the
existing schema convention. `url` is the final loaded URL. `captured_at` is the
published snapshot's UTC capture time, not the page publication date.
`authors` is a name list, `published` is a full ISO date when the page exposes
one, and `site` is the human-readable site name.

The body has one H1 matching `title` and two ordered sections:

```markdown
# Example title

## Summary

A short explanation of the page and why it matters.

## Content

The cleaned main-document Markdown derived from the snapshot.
```

`Content` preserves the full cleaned projection in `source.md`; it is not a
second summary or a paraphrase. Analyse owns the short `Summary` and the
semantic frontmatter while carrying that readable source projection forward.

`webpage.md` is not a disposable cache. A later repair must preserve
user-maintained metadata and prose unless the exact diagnostic requires a
change.

## Identity and slug admission

Webpage intake requires only an exact URL. Its provisional material result has
`requested.slug:null` because a human-readable slug is not known before the
page is inspected.

`webpage.identify` loads the exact URL without writing a durable artifact and
returns the final URL, page title, site name, and a canonical slug. The slug is
an ASCII kebab formed from the site's host label and a concise English or
transliterated version of the page title, with the normal 80-character limit.
This wording is identity-specialist judgement rather than a second generic
slugification library. If that slug belongs to a different URL, identity
resolution appends the first eight hexadecimal characters of SHA-256 over the
normalized final URL instead of asking the user to resolve a mechanical
collision.

URL identity comparison lowercases scheme and host, removes a fragment and a
default port, and treats an empty path as `/`; it preserves the path and query.
URLs containing credentials are rejected. This one normalized URL key is used
by Identify, Capture, status admission, and local-owner resolution.

Identity resolution also checks for an existing Webpage owner by final URL. A
match reuses that owner's vault slug. It must also find a partial owner whose
snapshot exists but whose canonical Markdown does not yet exist; partial
capture is durable progress, not a new material.

This lookup extends the existing deterministic
`quasi-helpers vault resolve --items-file -` capability with `kind:webpage`.
For each safe `vault/webpages/<slug>/` directory, the resolver reads the
canonical frontmatter URL when available and otherwise the WebArchive main
resource URL. Zero hits means no owner, one hit returns its exact vault slug and
path, and multiple hits return an error rather than choosing. The identity
Agent consumes that closed resolver row just as the Book/Paper identity stage
does. A fresh `quasi-status` observation is still required before any writer.

Because the initial URL has no canonical status route, the first invocation is
the sole exception to Collect's pre-observation rule:

1. Collect invokes the Webpage entry with a provisional URL seed and no
   observations.
2. The Workflow may run only the read-only `webpage.identify` operation.
3. It returns `needs_observation` with the canonical Webpage route and an opaque
   canonical resume seed.
4. Collect runs exact `quasi-status` for that route and resumes the same named
   entry.
5. No writer may run until that fresh canonical observation is present.

This keeps URL inspection and identity policy inside the Workflow while the
Skill remains the sole orchestration status observer. The bounded resolver row
is identity evidence carried in the Identify receipt; it never admits a writer
without the subsequent exact status observation.

## Operations and Agent ownership

The Workflow is linear:

```text
identify -> observe -> capture -> prepare -> analyse -> audit
```

| Operation | Agent | Effect | Exact result |
| --- | --- | --- | --- |
| `webpage.identify` | new `webpage-agent` | read-only | canonical Webpage identity and optional local owner |
| `webpage.capture` | `webpage-agent` | writer | `snapshot.webarchive` |
| `webpage.prepare` | `webpage-agent` | writer | `source.md` extracted from the saved snapshot |
| `webpage.analyse` | existing `analyse-agent` | writer | canonical `webpage.md` |
| `webpage.audit` | existing `audit-agent` | writer | mechanical fixes and diagnostics for `webpage.md` |

Only one new Agent is added. `webpage-agent` owns URL inspection, WebKit
capture, and snapshot preparation because those methods are specific to this
material. It receives only `Read` and `Bash`; deterministic helpers, not the
Agent, publish files. It does not search Kagi, use `WebFetch`, write the
canonical Markdown, or investigate alternative URLs.

The existing specialist Agents remain narrow:

- `metadata-agent` remains the bibliographic Book/Paper identity specialist;
- `download-agent` remains the Book/Paper source acquisition specialist;
- `webcard-agent` remains Topic-owned until the later Topic integration;
- `analyse-agent` gains only the Webpage analysis method over one exact
  normalized input and one injected artifact contract; and
- `audit-agent` already works against an exact target and needs no new
  professional role.

## Deterministic capability

A new stable shell surface exposes three closed commands:

```text
quasi-webpage inspect --url URL --json
quasi-webpage capture --url URL --expected-final-url URL --output PATH --json
quasi-webpage extract --snapshot PATH --output PATH --json
```

The Python-facing shim follows the existing bootstrap convention. On macOS it
compiles a small Swift/WebKit helper into `CLAUDE_PLUGIN_DATA` and reuses the
binary until its source changes. Absence of macOS 11+, WebKit support, or a
Swift compiler is an explicit unavailable-capability failure; it does not
select another backend.

### Inspect and capture

The native helper:

- accepts only `http` and `https` URLs;
- creates an offscreen `WKWebView` with a non-persistent website data store;
- does not open Safari or a visible window;
- waits for the main navigation to finish, then uses a fixed 750 ms settle
  interval before capture;
- applies one 60-second total timeout rather than a network-idle heuristic or
  retry engine; and
- returns the final URL and document metadata used by the calling command.

Before publishing, Capture normalizes the URL actually loaded by its second
page load and requires it to equal `--expected-final-url`. A mismatch is a
known no-write `webpage.capture_identity_changed` failure. It does not publish
under the previously selected owner or silently derive another route.

`capture` calls `createWebArchiveData`, stages the bytes beside the exact
output, and atomically publishes one non-empty WebArchive. The helper records
the published file's capture timestamp in its JSON receipt. Navigation or
capture failure leaves the canonical output unchanged.

Inspect and capture intentionally perform separate page loads. This small cost
keeps identity read-only, establishes the final output route before a writer
runs, and avoids a hidden staged snapshot crossing the observation boundary.

### Prepare

`extract` reads only the exact saved WebArchive. It decodes the binary property
list, obtains the main HTML resource, and runs deterministic main-content
extraction to Markdown. It never revisits the live URL and never executes page
scripts. The resulting UTF-8 Markdown is staged and atomically published to
`processing/webpages/<slug>/source.md`.

Main-content extraction uses Trafilatura over the saved main HTML. It is a
normal Python dependency installed by the shared plugin bootstrap, not a
browser backend. Page text is untrusted source material; Agents treat it as
evidence, never as instructions.

## Status and stepwise resume

Webpage status reports exactly:

```json
{
  "schema_version": "quasi.status/0.2",
  "kind": "webpage",
  "slug": "example-org-example-title",
  "identity": null,
  "facts": {
    "kind": "webpage",
    "snapshot": {"path": "...", "present": false, "usable": false},
    "prepared": {"path": "...", "present": false, "usable": false},
    "canonical": {"path": "...", "present": false, "usable": false},
    "captured_at": null
  }
}
```

Snapshot usability requires a non-empty, parseable WebArchive with a non-empty
HTML main resource; prepared usability requires readable non-empty UTF-8
Markdown; canonical usability follows the existing canonical Markdown
observation.

The closed Webpage identity shape is
`{slug,title,url,site}`. `slug` is the observed directory; `url` is normalized;
`site` is the captured site name or, when absent, the hostname. Status identity
is null only while neither a usable snapshot nor a usable canonical page can
supply this shape. A usable snapshot supplies it from the WebArchive main
resource. A usable canonical page may supply it when filling in a missing
snapshot, but when both artifacts exist their title, normalized URL, and site
must agree or status marks the canonical artifact unusable.

Webpage facts additionally contain `captured_at`, an ISO UTC whole-second
string when the snapshot is usable and null otherwise. Capture sets the
immutable snapshot file's modification time to that exact whole-second capture
instant; status derives the same normalized value from that file metadata. If
Capture's receipt was lost, this supplies provenance for the first canonical
write. Once `webpage.md` exists, its persisted `captured_at` must equal the
observation and remains the canonical semantic value.

At each entry the plan selects only the first incomplete stage:

- usable snapshot skips Capture;
- usable prepared Markdown prevents a Prepare writer, but the Prepare Agent
  still reads and reconciles it before Analyse so structural existence is not
  mistaken for semantic readiness;
- usable canonical Markdown skips Analyse; and
- a complete current invocation still requires its audit receipt because audit
  has no durable status signal.

A successful material result returns exact `snapshot`, `normalized_text`, and
`canonical` artifact refs. The shared exact-observation pump handles any
`needs_observation` result: Collect obtains fresh status and resumes the opaque
seed. It stops after the existing two unchanged observation cycles rather than
spinning.

## Audit and repair

Webpage uses the established single-artifact audit shape. The audit Agent may
make evidence-preserving mechanical fixes. If it escalates a semantic
diagnostic for `webpage.md`, the Workflow dispatches the exact `analyse-agent`
owner once in repair mode and performs one re-audit. Diagnostics targeting any
other path are owner ambiguity and stop.

This is a bounded owner-correct repair, not a generic retry loop. No writer is
replayed after an ambiguous outcome inside the same invocation.

## Error semantics

The first version has no ordinary human gate. Missing titles, ordinary
redirects, and slug collisions have deterministic resolutions.

- Invalid schemes and known unsupported platform capability are non-retryable
  failures.
- Known navigation, transport, capture, parse, or content-extraction failures
  return the owning operation's typed `failed` result with an honest retryable
  value.
- Trafilatura returning no main content prevents `source.md` publication. An
  access page or empty shell that still yields text is judged by the Prepare
  specialist while reconciling the exact projection; status itself adds no
  second readability heuristic.
- A missing Agent receipt or another host-level ambiguous writer outcome
  becomes material `needs_observation`, because fresh status can prove whether
  the exact output was published.
- A schema-valid specialist `blocked` result, including an exact-ref mismatch,
  remains `blocked`; it is not reinterpreted as observation recovery.
- A schema-valid specialist failure is not automatically replayed.
- An existing usable snapshot is never overwritten. Same-URL intake reuses the
  existing material.

There is no Chrome, MHTML, Monolith, WARC, PDF, raw-HTML, or alternate-provider
fallback.

## Collect integration

`collect-material` adds one closed dispatch mapping:

```text
webpage -> workflows/webpage.mjs
```

The Skill accepts a URL, transports the provisional or canonical seed, invokes
the fixed entry, presents any typed terminal, performs requested exact
observations, and verifies exact post-status after completion. It contains no
WebKit instructions, slug algorithm, main-content heuristic, capture timeout,
or Webpage stage list.

Top-level Webpage concurrency follows the existing Collect material limit.
There is no internal fan-out.

## Tests

Tests protect causal seams instead of exhaustively enumerating malformed
receipts.

1. Schema tests accept the minimal Webpage frontmatter/body and reject wrong
   type, path, H1, or section order. They also guard that snapshot technical
   fields do not enter frontmatter.
2. Helper tests cover URL normalization, resolver zero/one/multiple-hit
   behavior, collision suffixing, binary WebArchive main-resource extraction,
   Capture final-URL mismatch, atomic no-clobber publication, and readable
   Markdown projection using local fixtures.
3. A macOS-gated integration smoke test loads a local fixture page in the
   offscreen WKWebView, captures a WebArchive, and proves its main resource and
   local subresource are present. Unit tests do not require public network.
4. Status tests cover absent, snapshot-only, prepared, and canonical states,
   including snapshot-derived identity and scan discovery.
5. Workflow tests cover provisional Identify to `needs_observation`, same-URL
   owner reuse, the exact linear operation sequence, skipping each durable
   completed stage, capture/prepare unknown-outcome observation recovery,
   schema-valid failure passthrough, and one owner-correct audit repair.
6. Skill and entry tests cover the closed Collect mapping, opaque observation
   resume, post-status verification, generated bundle parity, and dead-name
   guards.

Tests do not assert prose sentences, create a cross-product of impossible JSON
shapes, exercise public websites, or duplicate the JSON Schema validator.

## Scope and non-goals

This phase does not:

- modify Topic, migrate existing Topic cards, or retire `webcard-agent`;
- use Webpage as a Paper acquisition fallback;
- capture authenticated sessions, the user's current browser tab, or Safari
  cookies;
- support non-macOS capture;
- maintain recapture history, versions, refresh, or overwrite policy;
- guarantee infinite-scroll, click-revealed, or arbitrarily late asynchronous
  content;
- add a PDF, screenshot, video, or separate image description;
- export or replay WebArchive outside WebKit; or
- introduce capture configuration, provider cascades, background processes,
  retry budgets, or a new durable orchestration state file.

These are separate product decisions. The first version succeeds when one
public webpage can enter Collect, resume safely at each durable boundary, and
produce one inspectable snapshot plus one useful canonical reading page.
