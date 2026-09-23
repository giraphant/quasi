# Quasi Architecture

date: 2026-08-04
status: current contract

Quasi is optimized for agent maintenance: keep a flat monorepo, keep each
capability in a readable large entrypoint, and make upper layers depend only on
the layer directly below them.

## Layers

```text
L5 skills/          user-facing coordinators and human gates
L4 scripts/workflows/ modular TypeScript source for named material plans
L4 workflows/       generated, host-loadable workflow entries
L3 agents/          specialist LLM workers, only calls quasi-* bins
L2 bin/             stable command surface
L1 scripts/         capability entrypoints and build sources
L0 scripts/core/    runtime plumbing
L0 scripts/schemas/ vault domain spec
```

`scripts/core/` and `scripts/schemas/` are both foundational, but intentionally
separate:

- `scripts/core/` knows paths, frontmatter, JSON, atomic writes, and module loading.
- `scripts/schemas/` knows vault types, frontmatter schemas, body schemas, and
  type aliases. It is the single source of truth for artifact structure.
- `scripts/core/` must not import sibling script domains or `scripts/schemas/`.
- agents and skills must not import Python packages directly; the Workflow
  build injects canonical artifact projections generated from this registry.

## Public CLI

| bin | contract |
|---|---|
| `quasi-search` | `book|paper` metadata discovery |
| `quasi-download` | `book candidates|fetch`; `paper fetch|diagnose`; `accept` |
| `quasi-extract` | `epub|text|ocr|ocr-generation|split` text extraction and normalisation (`ocr` default engine DS OCR2, `--engine dsocr2\|tesseract`, `--layout` replacement text layer; `ocr-generation` is the shared source/profile-bound immutable Paper/Book OCR transaction) |
| `quasi-audit` | agent-facing `--path PATH` autofix + typecheck + classify |
| `quasi-status` | read-only disk oracle: `--kind paper|book|talk|author|topic|webpage|archive --slug SLUG --json`; Translation additionally requires `--target-language TAG`; `--scan --json` |
| `quasi-transcribe` | `run|classify|silent` talk transcript engines |
| `quasi-archive` | `inspect` source candidates; `collect` originals + manifest + page; `read` saved Webarchive text without a derivative file |
| `quasi-webpage` | `inspect|capture|extract` one exact public webpage; capture requires macOS 11+ |
| `quasi-helpers` | `proofread prepare|cleanup`; `citation parse|biblio|resolve|review-cards|emit-bib`; `localise scan|write`; `talk compress-media`; `vault resolve` |
| `quasi-doctor` | runtime healthcheck: venv sync, core Python deps, optional external tools by profile |
| `quasi-translate` | configured `immersive|pdf2zh` PDF translation; shared alternating-page, TOC, ToUnicode, and coverage contract |

`quasi-status` imports `scripts/schemas/operations.py::OPERATION_CATALOG` for exact
artifact path templates. Its hardened manifest parsing,
frontmatter reads, media enumeration, derivative globbing, and scan discovery
remain explicit Python observation logic rather than a rule-DSL walker.

Removed legacy bins:

- `quasi-citation` → use `quasi-helpers citation ...`
- `quasi-proofread` → use `quasi-helpers proofread ...`

## Capability Entry Points

- `scripts/search/search.py`: metadata discovery, source merge, and book
  `localisations.zh` sidecar candidates.
- `scripts/download/download.py`: acquisition by DOI/URL/MD5, diagnostics, and accept
  into `sources/`. AA file search remains in `scripts/download/aa.py` because it is
  acquisition discovery, not metadata search. Its normal path is HTTP-only; a confirmed
  DDoS-Guard response invokes the bounded `scripts/download/aa_browser.py` helper through
  `uvx`, executes the site's JavaScript in isolated Chromium, and returns settled HTML to
  the same parser.
- `scripts/extract/extract.py`: unified extraction dispatcher.
- `scripts/audit/audit.py`: agent-facing typecheck wrapper. It always runs
  mechanical autofix, then typecheck, then residual issue classification, and
  emits JSON.
- `scripts/localise/localise.py`: scale-facing ISBN-keyed cndouban cache helper.
- `scripts/citation/citation.py`: deterministic draft citation helpers only.
- `scripts/proofread/proofread.py`: deterministic proofread setup/cleanup only.
- `scripts/doctor/doctor.py`: runtime healthcheck for venv sync, core Python deps, and optional system tools by profile.
- `scripts/translate/immersive_translate.py` and `pdf2zh_translate.py`: interchangeable PDF translation backends behind the `quasi-translate` shim. Both run `tounicode.py` repair followed by `coverage.py` acceptance; DS OCR2/MinerU are recovery dependencies only after `Under-translated`, not pdf2zh startup requirements.
- `scripts/webpage/webpage.py`: exact public-URL inspection, snapshot capture, and extraction behind the `quasi-webpage` shim.

## Workflow source and runtime

`scripts/schemas/operations.py` is the single source of operation identity.
`OPERATION_CATALOG` maps each stable operation to eligible kinds,
display phase, effect, Agent, and artifact path templates. The Python exporter projects
that catalog into `scripts/workflows/artifact-contracts/generated.mjs` alongside the
canonical artifact contracts and emits matching declarations. It contains no stage
order, carry, alias, or next-operation graph.

`scripts/workflows/operations/rows/*.mts` owns operation-specific context derivation and
request/receipt behavior. Eight material-local catalogs expose only the rows needed by
Paper, Book, Talk, Translation, Author, Archive, or Webpage, plus the quarantined legacy Topic regression catalog. Their named plans own progression,
joins, checkpoints, and bounded repair; Author composes leaf plans through explicit host-observation handshakes. Topic research is controlled by the main agent using its Skill. `scripts/build-workflows.mjs` verifies each fixed
entry's metadata and `materialKind`, generated-artifact currency, and bundle ABI,
imports, and size. Focused pytest checks prove operation-catalog/local-row alignment.
The pinned esbuild dependency compiles the editable `.mts` entries into the
committed `workflows/{paper,book,talk,translation,author,webpage,archive}.mjs` bundles;
`npm run check:workflows` also runs strict `tsc --noEmit`. The former Topic bundle is generated only under `deprecated/workflows/` for regression reference, not loaded as an active plugin entry. The same build exports `skills/research-topic/artifact-contract.json` from the canonical schema for direct Topic writers.

`collect-material` drives each leaf with one exact pre-status and a fixed kind→entry
mapping, except that an initial Archive or Webpage URL has no canonical route: it starts with the
closed provisional URL seed and `observation:null`, then Collect observes the exact
returned material route before resuming. A leaf entry validates its closed seed/observation/options envelope, runs from
that testimony to one material-level terminal, and returns
`quasi.material.result/0.1`; the Skill never selects a Stage or consumes a Stage receipt.
Paper, Talk, and Translation dispatch sequential owned operations. Book alone uses the
host `pipeline()` to fan out manifest-listed chapters whose exact outputs are disjoint,
then joins before synthesis. Any named entry may return `needs_observation` with exact
routes and an opaque continuation; the Skill refreshes those routes and reinvokes that
same entry. The complete returned status observations for the same routes advance only
when they differ byte-for-byte; it stops after two consecutive byte-for-byte identical
recovery observations. A typed gate returns the current effective
`{route,seed,options}`; the caller obtains fresh exact status and adds only the new
decision. Unknown writer outcomes stop instead of racing a second writer.

A Paper complete result names the exact accepted source, the normalized text selected by
Prepare, and the canonical page. An existing canonical owner therefore still reconciles
Prepare before Audit; if its source is absent, Acquire runs first. Audit alone proves only
the canonical page and cannot turn a missing source or prepared projection into complete.
The accepted source is exactly one of `sources/{slug}.pdf` and `sources/{slug}.txt`;
simultaneous alternatives are a visible conflict. PDF responses and Paper accept require a
readable, non-empty PDF container, while verified scholarly HTML or strict UTF-8 text may be
normalized into the text alternative. A bounded Paper fetch returns before the host ceiling
instead of claiming an unfinished provider cascade was exhausted.

Book Prepare projects resumable OCR progress through status. Each `quasi-extract ocr
--resume` call owns one exact page range and atomically advances a source/config-bound part
inventory; the Book entry returns `needs_observation` between ranges and finalizes only after
the merged OCR output is durable. No background OCR process or hidden Workflow cursor is
introduced.

Inside a named plan, each descriptor row gives one specialist a goal, exact refs,
declared capabilities, and a closed
`quasi.stage.receipt/0.3` model-facing schema. After StructuredOutput validates the
model-produced judgement fields and terminal, the host stamps top-level single-value
bookkeeping consts through the prepared-dispatch boundary. No universal stage router or
mode envelope remains.

Root `settings.json` supplies a plugin-default `subagentStatusLine`. The
zero-dependency `scripts/subagent-statusline.py` renders only quasi task rows,
so unrelated subagents retain Claude Code's default row.

## Active Agents

| agent | depends on |
|---|---|
| `metadata-agent` | `quasi-search` + vault resolve → one canonical identity and local owner |
| `discovery-agent` | `quasi-search book|paper|kagi`, scoped local recall and WebFetch → bounded candidates |
| `steer-agent` | legacy Topic regression specialist; no active Skill dispatch |
| `webcard-agent` | readonly source discovery via `quasi-search kagi` + WebFetch; exact Archive reads → topic `cards/` page |
| `archive-agent` | exact URL + Archive URL/slug resolve → one canonical Archive with provenance and Topic tags |
| `download-agent` | `quasi-download`, direct AA search import |
| `extract-agent` | `quasi-extract` capabilities → Paper/Book Prepare Stage |
| `analyse-agent` | vault/source files |
| `synthesis-agent` | vault analysis files |
| `audit-agent` | `quasi-audit` |
| `proofread-agent` | draft sections prepared by `quasi-helpers` |
| `citecheck-agent` | citation manifest prepared by `quasi-helpers` |
| `transcribe-agent` | `quasi-transcribe` capabilities → Talk Prepare Stage |
| `translate-agent` | `quasi-translate` + optional layout OCR → Translation Prepare Stage |
| `webpage-agent` | `quasi-webpage` + vault resolve → Webpage identity, snapshot, and source projection |

### Write ownership

- `metadata-agent` and `discovery-agent` return JSON and do not write files.
- `download-agent` reconciles or accepts one exact Book/Paper source through `quasi-download`; it returns that material's direct Acquire receipt, including a standard `needs_input` terminal for a Book year gate, and does not own caller manifests. A failed download preserves `failure_reason` and per-source `attempts` in its receipt.
- `extract-agent` owns Paper/Book Prepare judgement and local recovery over caller-named refs. It invokes deterministic `quasi-extract` transactions; those CLI transactions own chapter files and `processing/chapters/{slug}/manifest.json`.
- `analyse-agent`, `synthesis-agent`, `proofread-agent`, and `citecheck-agent` write only the exact product path assigned by the caller.
- The research main agent owns Topic outline/resources updates by batch, preserving user edits. It may delegate one exact output to synthesis; one writer owns each shared file. Independent synthesis reports may run in parallel without writes.
- `webcard-agent` discovers source URLs readonly for one topic `web_task`; after Archive collection it turns the exact Archive records into one evidence card at the caller-named `vault/topics/{slug}/cards/{card-slug}.md`; it writes nothing else, and returns `status: empty` rather than writing a card it could not verify. Cards travel on their own `cards` channel (outline `subquestions[].cards`, synth `card_paths`) and never enter the `book|paper|talk` corpus table.
- `audit-agent` runs `quasi-audit --path`; it may apply local mechanical fixes but does not own workflow state.
- `transcribe-agent` and `translate-agent` own Talk and Translation Prepare with the same terminal shape, preserving media reconciliation and fenced-generation publication contracts. Video Talks prepare `vault/talks/{slug}/recording.mp4` by default; when `prepare_media:true`, this file and its sidecar are part of Prepare and material completion, exposed by `quasi-status` as `facts.prepared`.
- `archive-agent` selects same-object originals; `quasi-archive collect` publishes the exact Archive page, provenance manifest and originals, preserving existing Topic membership and user prose. It checks observed revision under per-slug and per-URL process locks.
- `webpage-agent` owns exact-URL inspection, `vault/webpages/{slug}/snapshot.webarchive`, and `processing/webpages/{slug}/source.md`; `analyse-agent` owns `vault/webpages/{slug}/webpage.md` and `audit-agent` owns its mechanical repair.

Deprecated agents live under `deprecated/agents/` and must not be dispatched by
active skills.

## Active Skills

- `collect-material`
- `research-topic`
- `finalise-draft`

`collect-material` owns the current Paper/Book/Author/Talk/Translation/Webpage/Archive entry. Its six
leaf kinds route to named material Workflows; the named Author Workflow composes the
Paper and Book entries after the Skill supplies fresh exact statuses for its returned routes.
`research-topic` guides the main agent's research loop. It delegates bounded local/web/academic
searches to discovery and exact-input synthesis to synthesis-agent, selects material candidates,
drives the same leaf entries using collect-material, reads returned materials as needed, and decides
the next round. Synthesis is evidence, not a mandatory decision gate. `finalise-draft`
owns interactive proofreading, citation review, and bibliography closure.

Codex uses only the standalone `codex/skills/quasi` entry, with Orca orchestration
as its coordination dependency. Its main agent uses snowball research: seed sources and
notes yield leads, new sources change the meaning of older observations, and interpretations
generate further questions. It prioritizes promising branches and seeks independent sources
beyond the initial source network. Notes reuse the existing outline body or user note location; synthesis and
resources remain the existing Topic pages. Research rounds count exploration and
judgement updates, not individual archives. Collection and independent research overlap.
A real Claude Code worker owns each whole collect-material or finalise-draft task.
CC startup, routes and result handling live in an on-demand reference; normal reception
does not repeat material audit or inspect specialist logs. CC runs the existing Workflows
and observations. Dispatched CC user gates travel through Orca ask/reply.
No Codex plugin package, hooks, duplicated material state machine or interpreter
is installed. See `docs/CODEX_ENTRY.md` for installation and acceptance.

Archive has a named URL collection Workflow. It owns `vault/archives/{slug}/archive.md`,
`manifest.yaml` and descriptively named files under `originals/`. New pages provide a structured reading entry (overview, source/coverage and concrete content summary),
with source/url, verified creator and publication date in frontmatter. Publication date is distinct
from creation, capture and modification dates; unknown dates remain omitted and explained.
The inventory owns per-file provenance and capture records. Existing lightweight pages remain readable. Missing originals
are coverage notes, not a completeness quota; link-only empty inventories are valid.
Explicit archival intent uses Archive; standalone webpage reading preserves Webpage.
`archive.identify` resolves a unique existing Archive by normalized source URL;
ambiguous owners or occupied slugs stop. `archive.collect` selects originals and invokes
`quasi-archive collect` for publication or Topic membership merge. Each write returns
an exact observation request; completion requires fresh usable metadata/inventory and
a clean audit. Legacy link records are enriched on next collection. Video/audio are
saved for playback only. Storage and Marple resolution: `docs/ARCHIVE_STORAGE.md`.

Topic non-academic sources enter Archive through the existing leaf Workflow with Topic membership.
Fresh material status proves collection; a card is optional. Archive pages, manifests and selected
originals can be direct synthesis inputs. Main updates resources and outline once a useful batch
is available; there is no per-material Topic checkpoint, recall restart, or mandatory Steer.
Searches on independent lines can run concurrently, as can synthesis and unrelated discovery.
At most five distinct materials are in flight. Cross-process research partitions sources and shared
output ownership before launch. Other participants return reports to the single shared-page writer.
Existing outline/items/cards and all saved Topic pages remain readable without migration.

Journal has a schema but no active or archived workflow; its future entry will
be a thin collection loop over Paper receipts.

For a single Book or Paper request, `collect-material` passes user-provided hints and
one exact disk observation to the fixed named entry. Its plan invokes
`material.search`, where `metadata-agent` receives both search and vault-resolution
capabilities and establishes canonical identity plus exact existing owner in one
investigation. Search owns author order, year, identifiers, venue/publisher, access
URLs, and canonical slug; the Skill only consumes the material result. Author/Topic candidate finding uses
`discovery-agent`; Chinese-edition matching uses the deterministic
`quasi-helpers localise scan|write` helper.

For a Webpage request, Collect accepts an exact public URL only when the user wants to
preserve that webpage itself; a URL explicitly given as a Paper or Book clue keeps that
kind. The first named invocation transports `{seed:{state:"provisional",url},
observation:null,options:{}}`. Its `needs_observation` result supplies the canonical
Webpage route for the existing direct-leaf exact-status pump. A complete result is
reported only after fresh Webpage status proves its snapshot, prepared, and canonical
refs equal, present, and usable.
When Paper Search instead proves that the requested item itself is a normal public web
article, its typed Webpage next route enters that same provisional flow. Author surfaces the redirect as an unsupported child type. The Topic main agent decides whether the redirected source belongs in its Archive collection.

For 2–32 top-level leaf materials, the skill preserves input order, coalesces only
byte-identical known material keys before launch, and drives at most five independent
named Workflows concurrently. Canonical owner collisions discovered after Search stay
visible for manual resolution; there is no reservation, lock, or cleanup subsystem.

Topic synthesis normally produces `00-overview.md` and `01-resources.md` beside the
user-editable `02-outline.md`; per-subquestion dossier pages are retired as a
product decision.

## Material Loops

Concrete materials are named leaf Workflows, not product categories layered above a
universal library executor. One invocation coordinates exact operation inputs/outputs,
joins producer artifacts, audits the canonical product, and terminates through typed
`complete|needs_input|blocked|failed` edges. Book's chapter fan-out is internal to that
one material. Agents own professional judgement; bins own deterministic effects;
`sources/`, `processing/`, and `vault/` are the persisted result space.

Design history (RFCs, campaign plans, review records) lives in git history
and `docs/CHANGELOG.md`; this file plus `CLAUDE.md`,
`docs/PDF_PIPELINE.md`, `docs/SKILL_ORCHESTRATION.md`, and
`docs/GRAPH_COLLABORATION.md` are the only maintained maintainer documents.

Active skill writing follows `docs/SKILL_ORCHESTRATION.md`: Skill owns user intent,
request order, exact observations, and human decisions; a named leaf Workflow owns
material identity/progression and descriptor dispatch; Agent owns specialist judgement,
and CLI owns deterministic writes. Active `SKILL.md`
files contain runtime instructions, not links back to maintainer docs.

## Configure options and env flow

Authoritative sources are `.claude-plugin/plugin.json#userConfig` and
`scripts/hooks/inject-userconfig.py::_KEYS`; the mapping below documents the
current flow from Configure field to script consumer.

| Configure field | Hook env input | Script env output | Main consumer |
| --- | --- | --- | --- |
| `anna_donator_key` | `CLAUDE_PLUGIN_OPTION_ANNA_DONATOR_KEY` | `QUASI_ANNA_DONATOR_KEY` | `scripts/download/aa.py` |
| `cookiecloud_server` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_SERVER` | `QUASI_COOKIECLOUD_SERVER` | `scripts/download/cookiecloud.py` |
| `cookiecloud_uuid` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_UUID` | `QUASI_COOKIECLOUD_UUID` | `scripts/download/cookiecloud.py` |
| `cookiecloud_password` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_PASSWORD` | `QUASI_COOKIECLOUD_PASSWORD` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_domain` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_DOMAIN` | `QUASI_COOKIECLOUD_EZPROXY_DOMAIN` | `scripts/download/cookiecloud.py` |
| `cookiecloud_ezproxy_base_url` | `CLAUDE_PLUGIN_OPTION_COOKIECLOUD_EZPROXY_BASE_URL` | `QUASI_COOKIECLOUD_EZPROXY_BASE_URL` | `scripts/download/cookiecloud.py` |
| `immersive_auth_key` | `CLAUDE_PLUGIN_OPTION_IMMERSIVE_AUTH_KEY` | `QUASI_IMMERSIVE_AUTH_KEY` | `scripts/translate/immersive_translate.py` |
| `translate_backend` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_BACKEND` | `QUASI_TRANSLATE_BACKEND` | `bin/quasi-translate` |
| `translate_base_url` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_BASE_URL` | `QUASI_TRANSLATE_BASE_URL` | `scripts/translate/pdf2zh_translate.py` |
| `translate_api_key` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_API_KEY` | `QUASI_TRANSLATE_API_KEY` | `scripts/translate/pdf2zh_translate.py` |
| `translate_model` | `CLAUDE_PLUGIN_OPTION_TRANSLATE_MODEL` | `QUASI_TRANSLATE_MODEL` | `scripts/translate/pdf2zh_translate.py` |
| `kagi_session_token` | `CLAUDE_PLUGIN_OPTION_KAGI_SESSION_TOKEN` | `QUASI_KAGI_SESSION_TOKEN` | `scripts/search/search.py`, `scripts/search/sources/douban_cn.py`, `scripts/download/download.py` |
| `soniox_api_key` | `CLAUDE_PLUGIN_OPTION_SONIOX_API_KEY` | `QUASI_SONIOX_API_KEY` | `scripts/transcribe/engines.py` |

Every Python-facing `quasi-*` shim sources `scripts/load-keychain-env.sh`, which fills missing `QUASI_*` values at runtime from the existing encrypted `Claude Code-credentials` Keychain record. On macOS the PreToolUse hook uses the same `--keychain-exports` helper for coordinator commands, including Claude-hosted commands whose `CLAUDE_PLUGIN_OPTION_*` values are visible only to the hook. Command argv contains only helper paths, never secret values; explicit `QUASI_*` values take precedence because the helper fills only missing keys. Non-macOS currently keeps the older direct-export hook fallback because it has no shared Keychain provider.

## Guardrails

- Keep scripts as large, sectioned entrypoints unless splitting removes real
  duplication.
- Add shared code to `scripts/core/` only when at least two capability domains need the
  exact same runtime policy.
- Keep schema changes in `scripts/schemas/`; do not duplicate schema facts in
  agents or skill prose.
- Active agents/skills must not reference removed entrypoint names; this is
  enforced by `tests/test_dead_names.py`.
