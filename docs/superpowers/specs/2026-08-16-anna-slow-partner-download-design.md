# Anna Slow Partner Download Design

## Problem

Book acquisition currently obtains one Anna candidate MD5 and then tries the
Fast API, its path/domain rotations, and LibGen. When those transports fail,
quasi never opens Anna's `/md5/{md5}` detail page and therefore never sees the
public Slow Partner links. LibGen is only a transport fallback for the same MD5
and has materially smaller coverage than Anna's partner inventory.

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

## Transfer boundary

The resolved file URL goes through the existing foreground Book stream helper,
with the Slow Partner page supplied as `Referer`. Its current behavior remains
unchanged: transient failures retry the complete transfer, an HTML payload is
removed, files below the existing minimum are rejected, and the promised
PDF/EPUB container is checked before the temp path is returned.

There is no persistent `.part`, Range protocol, cursor, sidecar, background
worker, or new digest policy. If the host interrupts a Slow transfer, that
invocation fails. A later invocation follows the existing temp preflight and
whole-file overwrite behavior; it does not interpret incomplete bytes as
progress. Persistent resume will be designed separately only if production
evidence shows repeated host-lifetime failures on otherwise progressing
no-wait transfers.

## Results and failure handling

The public Book fetch JSON remains unchanged. Success still reports the temp
path, `source:"anna_archive"`, and inspect evidence; failure remains
`status:"download_failed"` with `reason:"all_sources_failed"`. Provider-level
attempt reporting, quota-result normalization, and actual-transport naming are
separate contract work and are not prerequisites for adding this fallback.

An incomplete temp file is not writer success and is not an accepted source.
`quasi-download accept` continues to own publication into `sources/`.

## Tests

Focused tests must prove:

- detail parsing finds every no-wait partner in DOM order and excludes waitlist,
  viewer, credentialed, and non-HTTP links;
- detail and slow browser modes settle only on their own page shapes;
- final URL parsing accepts the supported Anna shapes and rejects another
  `/slow_download/` URL;
- the cascade reaches Slow only after Fast rotations and LibGen fail, passes the
  partner URL as Referer, and stops on first valid success;
- an interrupted or HTML transfer never becomes a successful temp result;
- invalid containers never become a successful temp result;
- existing Fast and LibGen success paths remain ahead of Slow and continue to
  pass their current validation.

Run the focused download suite, the dead-name/orchestration guards, and the full
Python suite. No Workflow rebuild is required because no Workflow source or
artifact contract changes.

## Explicit non-goals

- Anna waitlist or countdown support.
- Persistent browser cookies or a reusable browser daemon.
- Persistent partial files, Range resume, or a new payload-digest policy.
- Provider-attempt JSON, quota-result normalization, or source-name changes.
- Copying Shelfmark's global URL rotation, four-failure threshold, in-memory
  whole-book buffer, or retry/watchdog constants.
- Independent LibGen search, WeLib, Z-Library, torrent, or Usenet providers.
- Changing candidate ranking, Book identity policy, source acceptance, or the
  Workflow recovery protocol.
