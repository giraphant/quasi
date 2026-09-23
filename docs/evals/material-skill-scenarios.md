# Material Skill Consumer Scenarios

These are manual or headless consumer checks for the thin `collect-material`
driver. They are not deterministic unit tests: each run records the actual
Workflow result and exact `quasi-status` evidence from a disposable vault.

## 1. Ordinary leaf completion

**Fixture:** one Paper (or Book/Talk/Translation) whose input is available in a
disposable project root.

**Run:**

1. Record `quasi-status --kind <kind> --slug <request-key> --json`; for
   Translation also pass `--target-language <normalized-target>`.
2. Invoke the matching named Workflow through `collect-material`.
3. Record the returned `quasi.material.result/0.1`.
4. Record exact post-status at `result.material.canonical.slug`.

**Pass evidence:** one named Workflow handled the logical material; the result
is `complete`; every returned artifact is present and usable in post-status;
the Skill did not choose a stage or consume a Stage receipt.

**Last run:** not yet recorded.

## 2. Typed gate and fresh-observation resume

**Fixture:** a real identity, Book-year/structure, or Translation-source
ambiguity.

**Run:**

1. Capture the `needs_input` MaterialResult and user-visible gate.
2. Answer the gate.
3. Run one fresh exact status for the returned `resume_seed.route`.
4. Restart the route's named Workflow with `resume_seed.seed`,
   `resume_seed.options`, that fresh observation, and a `UserDecision` whose
   `material_key`, `operation`, and gate testimony are copied byte-for-byte;
   add only the user's selected candidate, source path, or action in the owning
   gate's closed value shape.

**Pass evidence:** the Skill does not derive a new decision key, canonical slug,
operation, candidate set, conflict set, year evidence, temp path, source
fingerprint, seed, route, or options; `translation_configuration` uses Configure
plus the returned continuation and no decision object; the resumed Workflow
either completes or returns a new typed terminal honestly. A Book identity gate
followed by a year/structure gate resumes from the latter gate without replaying
the identity decision; Translation source→configuration retains the selected
source in the returned effective options.

**Last run:** not yet recorded.

## 3. Two-material batch

**Fixture:** two distinct leaf request keys, optionally of different kinds.

**Run:** process both through `collect-material`, allowing both named Workflows
to be in flight.

**Pass evidence:** at most five Workflows are in flight; each exact key has at
most one owner; a stop in one item does not cancel the other; the report restores
original input order. Only byte-identical pre-launch keys are coalesced.

**Last run:** not yet recorded.

## 4. Malformed intake

**Fixture:** a public material envelope that violates its fixed entry parser,
such as a Paper provisional seed with neither title nor DOI.

**Run:** invoke the relevant generated named Workflow through the same wrapper
used by the Skill.

**Pass evidence:** the result is `terminal:"blocked"` with
`issue.code:"material.invalid_input"`; the Agent call count is zero; the Skill
does not pre-validate by reproducing the TypeScript contract.

**Last run:** not yet recorded.

## 5. Delayed Webpage hydration through the real host (opt-in)

Run `QUASI_RUN_CLAUDE_WEBPAGE_E2E=1 python -m pytest tests/test_webpage_host_e2e.py -q`
with an already provisioned Python environment, authenticated `claude` with named
Workflow support, Node, and macOS `swiftc`/WebKit. This is a paid model integration
check, skipped by default; after opt-in missing dependencies fail explicitly.
It loads this checkout via `--plugin-dir`, restricts settings to `--setting-sources project`,
disables Chrome with `--no-chrome`, and uses a fresh session UUID and a resolved
disposable vault, and serves a random-port loopback page whose sentinel arrives
only in a 2.3s delayed response, beyond the production 1.5s minimum. The host runs with permission bypass inside that test
vault; run only in a trusted test environment. Startup/user hooks are disabled;
bare shims receive the checkout PATH and disposable plugin data directly, with a
symlink to the already provisioned test virtualenv. All declared Python dependency
imports are checked before launching Claude; no dependency installation is done.

Pass evidence comes from the exact fresh session JSONL, dynamically discovered
Workflow run sidecars/journals and their specialist Bash transcripts: exactly two
named Webpage invocations, Identify/Capture/Prepare/Analyse/Audit once each, and
exactly one capture. Sidecars are matched to coordinator calls in provisional→canonical
order: the exact initial envelope must return `needs_observation`; the resumed
seed/options must equal its `resume_seed`, with the canonical route's fresh
`quasi.status/0.2` observation. Every journal `started` must have exactly one later
`result` for the same agentId. Every specialist transcript row must name the
resolved disposable vault cwd; literal Bash inspect/capture/extract calls must
occur once each under Identify/Capture/Prepare respectively; Analyse/Audit may not
call them. Raw argv must match the exact relative request spelling, not an absolute
equivalent. Each call requires one later non-error strict JSON receipt matching
its CLI schema, complete status, URL and artifact refs (and written state for
writers). Each capability call must be one simple command with the bare exact
`quasi-webpage` or `quasi-status` token: prefixes, chains, wrappers, assignments,
redirects and alternative executable paths are rejected. Conflicting duplicate
tool IDs are rejected. All evidence JSON uses one strict loader, rejecting nested
duplicate keys and NaN/Infinity without quoting raw contents.

Exactly two coordinator `quasi-status` calls must surround capture/completion,
with completed Workflow retrievals and status outputs joined to the invocation
sequence. TaskOutput completion requires a unique later exact-name tool call
whose task_id matches the launch, followed by its unique non-error tool_result
with matching task_id, completed status and sidecar result. Orphan task payloads
are rejected. Inline, TaskOutput and consumed SDK notification completion channels
remain mutually exclusive; launch and status tool results must also be non-error.
CLI receipts have closed key sets, nonempty string metadata, positive integer
sizes (not booleans), lowercase SHA-256 and capture UTC second timestamps; capture
now includes the normalized requested URL. Extract metadata must agree with the
snapshot capture receipt. The test independently invokes the source `bin/quasi-status` after the
host exits; its fresh disk status must prove snapshot, prepared and canonical
usable; the delayed sentinel must survive the archive main resource, source and
canonical `Content`. The host has a 900s process-group timeout with TERM/KILL/reap;
the server and vault are cleaned on success or failure. Session journals remain in
Claude's normal session store. Failure messages report bounded counts/reasons,
never raw transcripts, environment values, or host stderr.

**Last run:** 2026-09-21 — independent fresh paid Host E2E against the final
production code, `1 passed in 222.19s`, using a new disposable vault and session.
The opt-in invocation was `QUASI_RUN_CLAUDE_WEBPAGE_E2E=1 ... pytest -q -s tests/test_webpage_host_e2e.py`.
It verified the real named `workflows/webpage.mjs` and owner-correct specialists:
two Workflow calls, two fresh coordinator statuses, one capture writer, bare
literal refs, closed receipts/MaterialResults/metadata, and independent source
`bin/quasi-status` proving snapshot, prepared source and canonical artifacts all
present and usable. The delayed sentinel was present in WebMainResource,
`source.md` and canonical `## Content`. The corrected single direct literal
`--items-json` resolver contract passed this run. Default tests still skip paid
Host E2E unless explicitly opted in.


**Known real negative evidence (read-only replay):** session
`090cb79b-d796-4f93-ac8f-e4514711803e` delivered consumed SDK task notifications.
Coordinator sequencing and all five journal pairs pass, but specialist evidence
fails the single bare simple-command guard (and also violates dynamic-ref rules): Capture passed `$output`
after deriving it from `${CLAUDE_PROJECT_DIR:-$PWD}`. A complete sidecar and
successful write do not satisfy literal exact-ref argv evidence. Keep this as a
negative record; do not replay its writer or simulate shell expansion to accept it.
**Historical saved evidence:** session
`f452fb53-307a-4575-878f-c78554d8d75b` passed the previous receipt subset checks.
Its capture receipt predates the requested `url` field and cannot prove the new
closed receipt contract. Read-only coordinator replay still passes for it and
TaskOutput session `2f58ce5b-19ae-4948-bbb6-42e9cc33a5e8`, with session and sidecar
SHA-256 unchanged. Neither replay validates the changed native runtime or substitutes for current
full Host acceptance. That acceptance was separately completed by the independent
fresh run recorded above.

Deterministic native coverage also exercises immediate response headers with a
2.3s streamed body, preserving the last-chunk-only sentinel through archive and
extract, including page monkey-patching of JS intrinsics. DOM sampling runs in an
isolated content world; document-start hooks capture native intrinsics and report
unique request start/settle messages to Swift-owned state. At the 5s bound the
last sample must be valid and archive-safe: ready complete, no incomplete
images/loading fonts, WebView not loading, and Swift pending zero. A streamed
body still pending after 5s fails with stabilization_failed and publishes nothing;
continuous DOM churn can succeed only when those safety predicates hold. Parent TERM/INT/HUP cancellation and KILL are tested against a
real stalled Swift helper with staging present; cleanup must finish within the
test's hard bound without publishing canonical output. These local regressions
do not invoke Claude or substitute for the separate successful fresh Host run.

Navigation protocol coverage executes the production Swift state transitions:
A active → native generation reset → stale A init/start/settle ignored → B
init/start/settle accepted. The main-frame navigation policy rotates the secret
before cross-document/reload loads and reinstalls its document-start script.
Fragment-only changes (all other URL components equal) and javascript: actions
retain the current generation. Reloads, form submissions and provisional full
navigations/redirects cannot be classified as fragment changes. A real WebKit
second-navigation fixture also retains the delayed sentinel through capture and
extract. Both tests compile with the macOS 11 deployment target.

Production WebKit coverage also changes location.hash while a 2.3s fetch is
pending: the serialized DOM must record the hash change and retain the delayed
sentinel in both the archive main resource and extracted source. Javascript:
actions, same-URL reloads, HTTP 302 and two-document navigation remain covered;
CLI URL normalization still intentionally drops fragments.

Current acceptance requires exact closed quasi.status/0.2 top-level, facts and
artifact key sets, actual booleans (not integers), bounded identity with a
credential-free HTTP(S) URL and matching slug, and whole-second UTC captured_at
exactly when snapshot is usable. Identify must execute one bare quasi-helpers
vault resolve --items-json simple command with a literal five-field item array; its unique later non-error result must match the actual {resolved,
scanned} receipt and bind the fresh-vault no-owner, suggested slug and final
Workflow identity. Other specialists cannot resolve. All specialists reject
quasi-status and known direct Python/module/native writer entrypoints.

Compilation uses a source/recipe/target/architecture/platform/toolchain content
key. A separate supervisor owns compiler process groups, temporary files and
atomic cache publication and watches caller death independently of Python finally.
Capture inherits its exclusive staging descriptor, verifies inode identity and
computes validation/receipt/hash before no-clobber commit. Precommit cancellation
cleans staging; postcommit errors are explicitly capture_outcome_unknown and
require fresh disk observation, never writer replay. This combined contract has
deterministic coverage and passed the independent fresh Host run recorded above;
historical transcripts cannot substitute for that acceptance.


Final capture transaction regressions pin root/output ancestry using no-follow
openat descriptors, swap output parents during compile and validation, and test a
link that succeeds before raising. All publication and cleanup uses the pinned
dirfd. The runtime `scripts/webpage/capture_guard.py` is shipped alongside
`compiler_guard.py` and launched by the source capability; it creates and owns
staging through validation/commit, cleaning after caller SIGKILL at allocation
and post-helper barriers. No Python-only staging ownership gap is permitted.
Compiler cache recipes include the complete sanitized environment actually passed
to swiftc; SDKROOT, DEVELOPER_DIR and target environment changes invalidate cache
without exposing their raw values in filenames or receipts.

Host evidence requires inspect result before resolver call and exact inspected
item metadata, non-null completed/fresh status identity bound to all three CLI
receipts, and run-local agent metadata plus transcript/session identity. Metadata
inventory must match journal dispatches and agentType must match operation owner.
MaterialResult validation follows the editable contract: needs_observation has
material/issue/routes/resume_seed (no next); complete has material/issue/artifacts/
next, including normalized_text for the prepared source. Extra/missing fields,
wrong types and inconsistent continuation/artifacts fail with redacted errors.
These additions have deterministic coverage and were also validated by the
independent fresh Host acceptance recorded above.

Root pinning acceptance includes replacement of an ancestor above the project
root during validation. Authority comes from the initial `/` or cwd descriptor
walk, not from reopening a previously validated pathname. Relative roots and
empty/unset project roots retain their cwd semantics.

Strict JSON acceptance rejects finite-grammar exponent overflows (1e9999 and
-1e9999) at every nesting depth. Explicit TaskOutput uses the observed closed
retrieval/task/output envelopes; arbitrary outer fields are not ignored.

The production network-churn fixture makes short fetch/XHR requests every 80ms
without changing DOM. Even at the 5s bound, network/resource quiet must have
lasted 0.6s; pending-zero at one sample cannot replace that window. Continuous
DOM-only churn remains eligible at the bound once resource/network quiet holds.
These local tests do not invoke Claude; the separate fresh paid Host acceptance
recorded above passed.


An earlier fresh paid Host run reached durable complete (one successful capture receipt,
then fresh post-status with all three artifacts present/usable), but failed
specialist evidence: Identify attempted two `printf | ... --items-file -`
resolvers and omitted title/site. That deleted disposable vault must never be
replayed or resumed. The causal runtime fix replaces the advertised capability
with one direct literal --items-json invocation after successful Inspect, binding
kind/slug/url/title/site; generated request and specialist prompt prohibit stdin,
pipes and resolver repair/repetition. Deterministic tests reject the observed
commands and accept one direct five-field call. The corrected direct `--items-json`
contract subsequently passed the independent fresh Host run on 2026-09-21
(`1 passed in 222.19s`) with a new disposable vault/session. The earlier failed
run remains historical negative evidence only; its deleted vault was not
replayed or resumed.
