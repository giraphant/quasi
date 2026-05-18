# citation-agent vault-grounded judgment — Design

Date: 2026-05-18
Affects: `agents/citation-agent.md`, `skills/wrap-up/SKILL.md`
Version target: 0.25.1 (patch — agent contract change, no breaking schema)

## Background

`quasi:wrap-up` Phase 2.2 dispatches `citation-agent` to do **context-fit
judgment** on each draft citation against its vault candidate(s) — picking
the right `bib_source` and flagging whether a human should re-look.

Current agent contract (`agents/citation-agent.md` as of 0.22.0):

1. Read `manifest.json` (candidates + mentions per cite)
2. Read `biblio.json` (entire vault frontmatter view)
3. For each cite, judge fit by comparing `mention` context against the
   candidate's metadata fields (`title / journal / themes / publisher`)
   plus LLM prior knowledge of the work
4. Output `{key, picked_slug, flag, note}` per cite

## Problem

The judgment step is **grounded in metadata + LLM prior knowledge**, not in
the user's actual vault summary. Two failure modes:

1. **LLM hallucinates the candidate's content.** For canonical English
   works ("Sexing the Body", "Homo Sacer") the model can usually recall
   themes from its pretraining corpus. For obscure works, non-English
   works, or works the user has interpreted idiosyncratically, the model
   guesses — and guesses wrong, with high confidence.
2. **Metadata fields are weak signals.** `title` + `themes` + `publisher`
   don't carry enough information to judge whether a 200-word mention
   block is genuinely about *this* book vs a same-year same-author work
   on a different topic.

A secondary problem prompted the original investigation: agent reads the
**entire** `biblio.json` (whole-vault frontmatter index) per dispatch,
which is token-wasteful when the agent only needs metadata for ~16 candidates
per batch.

## Decision

Re-ground the judgment in **vault summary content**, not metadata.

The vault already contains the user's curated summaries:

- `vault/papers/{slug}.md` — full paper summary
- `vault/books/{slug}/00-overview.md` — book overview

The `manifest.json` candidates already carry a `path` field (relative to
`$CLAUDE_PROJECT_DIR`) pointing at these files —
populated by `scripts/citation/biblio.py:230` and propagated through
`scripts/citation/resolve.py:101`.

The agent will Read each candidate's summary file directly and judge fit
against actual summary content. `biblio.json` is dropped from agent input
entirely.

This also satisfies the "agent as context isolator" design principle: the
extra byte volume (real summaries) stays in the agent's context window;
the main process is unaffected.

## Architecture changes

### Change 1 — `agents/citation-agent.md` execution steps

Replace the current step 1-3 (`Read manifest → Read biblio → judge from
metadata`) with:

```
1. Read manifest, extract entries with key ∈ batch_keys
2. For each entry:
   a. For each candidate, Read vault summary at candidate.path
      (default limit=200 lines; expand a further range only if needed)
   b. Compare mention context vs actual summary content
   c. picked_slug = candidate whose summary best matches mention topic
   d. flag = ok (clear match) | review (ambiguous / weak match)
3. Write verdict_out
```

### Change 2 — `agents/citation-agent.md` "契合度判断要点"

Rewrite to forbid metadata-only / LLM-prior judgment:

```
读 mention 上下文 + candidate 的真实摘要内容 (vault 里那个 .md 文件正文),
问自己: mention 谈的, 跟这本书/篇摘要里写的核心议题对得上吗?

— 摘要明确讨论 mention 谈的概念 → flag=ok
— 摘要核心议题跟 mention 不在一个 topic → flag=review
— multi-hit 时, 挑摘要内容跟 mention 最贴的那个作为 picked_slug
— 严禁仅凭 title / publisher / LLM 先验知识判断,
  必须以 vault 摘要正文为依据
```

### Change 3 — `agents/citation-agent.md` input parameters

Drop `biblio` from the input parameters section. Inputs become:

- `manifest` — manifest.json absolute path
- `batch_keys` — list of cite keys to process this batch
- `verdict_out` — output path

### Change 4 — `skills/wrap-up/SKILL.md` Phase 2.2 dispatch

In the agent prompt template, drop the `biblio:` line:

```diff
 Agent("quasi:citation-agent", background=True,
       prompt=f"manifest: {ct_dir}/manifest.json\n"
-            f"biblio: {ct_dir}/biblio.json\n"
              f"batch_keys: {batch_keys_json}\n"
              f"verdict_out: {ct_dir}/verdicts/batch-{NNN}.json")
```

`biblio.json` is still generated upstream (by `quasi-audit emit-bib`) and
consumed by `resolve.py` — the agent simply no longer touches it.

### Non-changes

- `scripts/citation/biblio.py` — unchanged. `path` field already present.
- `scripts/citation/resolve.py` — unchanged. `path` already propagated to
  candidates. The `journal / publisher / themes` enrichment proposed in
  earlier drafts is dropped because those fields aren't the right judgment
  basis.
- `scripts/citation/emit_bib.py` — unchanged. Still consumes
  `decisions.json` and `biblio.json` deterministically.
- `manifest.json` schema — unchanged.
- `verdict_out` schema (`{batch_id, notes: [{key, picked_slug, flag,
  note}]}`) — unchanged.

## Data flow (post-change)

```
quasi-helpers citation parse   ─→ parse.json
quasi-helpers citation resolve ─→ manifest.json (candidates carry path)
                                       │
                                       ▼
              ┌──────── citation-agent ────────┐
              │  Read manifest                  │
              │  Read vault/{candidate.path}    │ ← new
              │  judge from real summary        │
              │  Write verdict-NNN.json         │
              └─────────────────────────────────┘
                                       │
                                       ▼
                          wrap-up Phase 2.4 TUI 审定
```

## Token cost

Per batch (8 cites × ~2 candidates average):

| Item                                       | Before     | After      |
|--------------------------------------------|------------|------------|
| Read manifest.json                         | ✓ (small)  | ✓ (small)  |
| Read biblio.json (whole-vault frontmatter) | ✓ (large)  | —          |
| Read vault summary files (16 × ~10KB)      | —          | ✓ (medium) |

`biblio.json` grows with whole-vault size (hundreds of entries × full
frontmatter per entry — typically several hundred KB once a vault has
been worked on for a while). The replacement reads are scoped to the
actual candidates of the batch (a few × 200-line summary slices). So
net byte volume to the agent is **lower**, not just neutral — and
judgment quality is substantially better.

Main-process context: unaffected. Main process still builds the same
prompt structure (one path fewer) and reads the same outputs.

## Edge cases

- **Missing vault summary file.** If `candidate.path` doesn't resolve to
  an existing file, the agent records `flag=review` with a note like
  "vault 摘要文件 {path} 读不到, 无法判断契合". Should be rare — the
  path comes from `biblio.py` which discovered the file via glob.
- **Very long book overviews.** Some `00-overview.md` files exceed
  500 lines. Agent default: `Read(path, limit=200)` — the first 200
  lines almost always cover the curated summary, key argument, and
  theme tags. Agent may Read additional ranges if context fit looks
  unclear from the first slice. This is guidance in the agent prompt
  (Step 2a above), not enforced by tooling.
- **Empty / placeholder summary.** Some entries have only frontmatter
  + a TODO body. Agent treats as "summary unavailable" → flag=review,
  note explains.
- **Path encoding.** `candidate.path` is relative to project_root with
  forward slashes (set by `biblio.py:230` via `Path.relative_to`). Agent
  joins with `$CLAUDE_PROJECT_DIR`. No spaces in vault paths (slug
  conventions), so no quoting concerns.

## Non-goals

- Reading vault chapter notes (`vault/books/{slug}/01-*.md` etc.). The
  `00-overview.md` is the curated summary; chapter notes are deeper but
  not needed for context-fit judgment.
- Online verification. Citation-agent stays offline. Online recovery for
  miss-hits is `search-agent`'s job in Phase 2.3.
- Manifest schema changes. Earlier draft proposed enriching candidates
  with `journal / publisher / themes`; this is dropped — those fields
  shouldn't be the judgment basis at all.
- New bin / new skill. Pure agent contract + skill prompt edit.

## Rollback

If the new approach turns out worse than expected (e.g. agent context
fills on huge book overviews, or judgments degrade), rollback is:

1. Revert `agents/citation-agent.md` to its 0.22.0 form
2. Restore `biblio:` line in `wrap-up SKILL.md` Phase 2.2

No data migration. No artefact format change. No biblio/manifest rebuild.

## Version

0.25.1 — patch. Agent contract simplifies; no schema break; no caller
break beyond the wrap-up dispatch one-line edit (in same release).
