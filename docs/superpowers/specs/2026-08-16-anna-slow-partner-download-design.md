# Anna Slow Partner Download Design

## Problem

Book acquisition currently obtains one Anna candidate MD5 and then tries the
Fast API, its path/domain rotations, and LibGen. When those transports fail,
quasi never opens Anna's `/md5/{md5}` detail page and therefore never sees the
public Slow Partner links. LibGen is only a transport fallback for the same MD5
and has materially smaller coverage than Anna's partner inventory.

Slow Partner downloads may continue making progress for longer than one
Workflow specialist invocation. The existing stream helper truncates its
destination on every retry, so a killed invocation cannot contribute durable
progress to the next one.

## Scope

Add one deterministic final fallback to `quasi-download book fetch`:

```text
AA Fast default
→ AA Fast path/domain rotations
→ LibGen
→ Anna Slow Partner, no-wait only
```

This change does not add a Workflow, operation, Agent, user option, provider
plugin system, background process, or waitlist scheduler. The Book Workflow and
download-agent keep their existing responsibilities. Slow access remains an
implementation detail of the one bounded Book fetch capability.

## Anna page access

Extend the existing bounded Anna browser helper with explicit `search`,
`detail`, and `slow` page kinds. Ordinary HTTP remains the first attempt. A
confirmed DDoS-Guard page or an Anna HTTP 403 may invoke the same supervised
headless helper that search already uses; the helper exits before the caller
continues and never starts a detached download.

Search keeps its existing result-or-explicit-empty settling rule. Detail
settles on a non-challenge `/md5/{md5}` document with a populated main body,
including a document with no Slow links. Slow settles on a non-challenge
`/slow_download/` document that exposes either one supported final-URL shape or
an explicit countdown/waitlist marker. These predicates prevent one page kind
from accepting another kind's partially loaded shell.

The detail-page parser scans anchors in DOM order and selects links whose label
starts with `Slow Partner Server` and whose containing row says `no waitlist`.
It preserves first occurrence order with a list plus a seen set, resolves
relative links against the detail URL, and admits only credential-free HTTP(S)
URLs whose path contains `/slow_download/`. Server numbers such as `#5` and
`#8` are presentation text, not identifiers.

For each selected partner page, resolve the final file URL from the page shapes
currently used by Anna: a `Download now` anchor, an anchor with a `download`
attribute, clipboard JavaScript, location JavaScript, or an explicit HTTP(S)
URL displayed in the page. The resolved URL must be credential-free HTTP(S)
and must not point back to `/slow_download/`. The file request carries the
partner-page URL as `Referer`.

No-wait means only that quasi does not join a queue. If a selected page contains
only a countdown or waitlist, this version records that partner as unavailable
and proceeds to the next no-wait partner without sleeping.

## Durable transfer

The Book stream helper downloads into a sibling `<destination>.part` file. The
part file is the only recovery state; there is no cursor or sidecar manifest.

- With no part file, request the complete file and write it from byte zero.
- With a non-empty part file, request `Range: bytes=<size>-`.
- A coherent `206 Partial Content` appends to the part file.
- A `200 OK` response to a Range request means the server ignored Range; truncate
  the part and restart from byte zero using that response.
- An incoherent `Content-Range`, HTML response, or deterministic 4xx response
  rejects that transfer. HTML removes the part because it is not book data.
- Network interruption and host termination leave the part intact. A later
  invocation re-enters through the same exact temp destination and resumes.
- Once transfer completes, validate the promised PDF/EPUB container and compare
  the completed file's MD5 with the Anna candidate MD5. Only then atomically
  replace the canonical temp destination; mismatch removes the part.

The digest check is necessary because several Anna transports for one candidate
share the same part file. It also closes the existing gap where quasi validates
the MD5 embedded in a LibGen URL but not the downloaded bytes themselves.

The existing requests read timeout remains an inactivity timeout, not a total
download deadline. A no-wait server that continues delivering bytes may run for
as long as the host permits; if the host stops it, the next invocation resumes
from disk. No `nohup`, detached child, or hidden long-running worker is used.

## Results and failure handling

`quasi-download book fetch --json` reports the actual successful transport as
`anna_archive`, `libgen`, or `anna_archive_slow`. It also returns the ordered
source attempts as existing `{source,status,error}` rows, including failures,
so download-agent can copy rather than reconstruct its receipt evidence. Each
row uses `status:"ok"` with `error:null`, or `status:"failed"` with one concise
non-empty error code; repeated Fast rotations may produce repeated
`anna_archive` rows because they are distinct actual transport attempts.

Failure remains `status: download_failed` and `reason: all_sources_failed`, now
with the same ordered attempts. A retained `.part` is recoverable progress, not
proof of a successful writer or an accepted source. `quasi-download accept`
continues to own publication into `sources/`.

## Tests

Focused tests must prove:

- detail parsing finds every no-wait partner in DOM order and excludes waitlist,
  viewer, credentialed, and non-HTTP links;
- detail and slow browser modes settle only on their own page shapes;
- final URL parsing accepts the supported Anna shapes and rejects another
  `/slow_download/` URL;
- the cascade reaches Slow only after Fast rotations and LibGen fail, passes the
  partner URL as Referer, stops on first valid success, and reports ordered
  attempts;
- an interrupted transfer leaves `.part`, a later invocation sends the exact
  Range header, and a valid `206` appends;
- a server that ignores Range with `200` restarts cleanly rather than appending;
- invalid `Content-Range`, HTML, wrong MD5, and invalid containers never publish
  the canonical temp output;
- existing Fast and LibGen success paths remain ahead of Slow and continue to
  pass their current validation.

Run the focused download suite, the dead-name/orchestration guards, and the full
Python suite. No Workflow rebuild is required because no Workflow source or
artifact contract changes.

## Explicit non-goals

- Anna waitlist or countdown support.
- Persistent browser cookies or a reusable browser daemon.
- Copying Shelfmark's global URL rotation, four-failure threshold, in-memory
  whole-book buffer, or retry/watchdog constants.
- Independent LibGen search, WeLib, Z-Library, torrent, or Usenet providers.
- Changing candidate ranking, Book identity policy, source acceptance, or the
  Workflow recovery protocol.
