# Skill Orchestration Schema

date: 2026-05-18
status: maintainer contract

This document defines how quasi skills are written and maintained. It is a
maintainer schema, not a runtime framework and not a document that active
`SKILL.md` files should cite.

## Runtime vs Maintainer

`SKILL.md` is runtime instruction. It should contain only what the executing
model needs to run the workflow: task, input normalisation, hard constraints,
state, worker contracts, phases, resume rules, and outputs.

This document, `AGENTS.md`, and `CLAUDE.md` are maintainer instruction. They
describe how to create or refactor skills. Do not put "follow
docs/SKILL_ORCHESTRATION.md" into active skills; that adds maintenance context
to the runtime task without improving execution.

## Principle

A skill is the main-process workflow owner. It turns a user request into a
small state machine, dispatches specialist agents, calls deterministic CLI
helpers, writes workflow state, and decides when to ask the user.

Agents are specialist workers. They should not own global workflow state.

## Skill File Schema

Active skills should use these landmarks. Extra domain sections are allowed
when they make execution clearer, but the core shape should stay recognisable.

```text
任务                 One short positive sentence: the work this skill performs.
输入                 User-provided facts to extract; not derived workflow state.
硬约束               Short list of rules the executing model must not violate.
状态                 Manifest/cache/decision files, status enum, and state ownership.
Agent / Helper 合同  The local worker contracts this skill actually calls.
工作流               Phase diagram or concise phase list.
执行流程             Concrete pseudocode when needed.
断点续跑             Skip conditions for each phase.
输出                 Final and important intermediate artifacts.
```

`wrap-up` is allowed to be longer because it contains human review, but it
should still follow the same ownership rules.

## Frontmatter Description

Frontmatter `description` is a routing hint, not a mini README.

Skill descriptions are user-intent facing:

```text
Use when the user wants to {core task} from/with {likely inputs}.
```

Agent descriptions are worker-facing:

```text
Worker for {single specialist action}. Reads/writes/returns {main contract}.
```

Keep descriptions short. Do not put phase names, historical rename notes, long
trigger-word lists, or detailed workflow steps in frontmatter.

`任务` should not explain orchestration, state, worker ownership, or negative
scope. Those belong in later sections. For example: "搜索、下载和分析用户提供的
论文。" is enough for a paper skill.

`输入` should describe facts available in the user's request, such as title,
author, DOI, ISBN, source path, topic, flags, or rough search query. Do not put
phase behavior, status branches, or derived canonical IDs there unless the user
can realistically provide them.

Avoid a `调用方式` section unless a skill has a real machine-facing invocation
surface. In normal plugin use, users trigger skills through natural language and
the frontmatter description; the skill body should normalise inputs rather than
document slash-command syntax.

## Ownership

- The skill main process owns workflow state files:
  `manifest.json`, `decisions.json`, recovery files, temporary search caches,
  and any `.quasi/<domain>/...` orchestration artifacts.
- A deterministic CLI may write an artifact only when that is its explicit
  contract, such as `quasi-helpers citation parse -o ...`.
- An agent may write only its assigned local product:
  `analyse-agent` writes the requested analysis file, `synthesis-agent` writes
  the requested synthesis file, `proofread-agent` edits the requested draft
  section, and `citecheck-agent` writes its `verdict_out`.
- `search-agent` never writes files. It returns curated candidates to the
  skill, and the skill decides whether and where to persist them.
- Agents must not mutate manifests, decisions, caches, or other workflow state
  unless their agent contract names that exact output path.

## Phase Contract

Each non-trivial phase should make these points explicit:

```text
Goal          Why this phase exists.
Skip if       The artifact or state value that makes the phase resumable.
Reads         Files/state consumed.
Writes        Files/state produced.
Calls         Agents or CLI helpers invoked.
Success       State transition or expected artifact.
Failure       Retry, mark failed, regenerate upstream, or ask user.
Concurrency   foreground, background fan-out, or strictly serial.
Human gate    Whether the user must decide before continuing.
```

The phase may be written as prose or pseudocode, but these facts should be
recoverable without reading another skill.

## Concurrency

- Blocking setup, downloads, extraction, synthesis, and audit are foreground
  unless the skill explicitly states otherwise.
- Map-reduce work may run in background, but the skill must wait by polling
  stable artifacts with `Glob` or by using foreground dispatch. Do not use
  fragile task-output inspection as the source of truth.
- If multiple workers write the same file, run them serially. This is why
  proofread sections run one at a time: all sections append to one draft record
  block.

## State

Any skill with a manifest must define a status enum and the transition rule for
each status. A status is not just a label; it controls which downstream phase
may consume the item.

Recommended shape:

```text
discovered       known but not enough metadata to acquire
metadata_found   enough metadata for download / processing
acquired         source file is available at a stable path
analysed         vault analysis file exists
done             terminal success, if the workflow needs it
failed           terminal failure with failure_note
```

Domain-specific warning fields such as `year_review`, `year_warning`, or
`needs_human_review` should not replace `status` if the source file is already
usable by downstream phases.

## Human Gates

User decisions belong in the skill main process. An agent can provide evidence
or a recommendation, but the skill asks the user, writes the decision, and then
continues or stops.

Examples:

- `process-book` asks the user what to do with book year ambiguity.
- `wrap-up` asks the user to review suspicious citations and missing sources.
- `translate-agent` may remain active because translation QA can become a real
  specialist judgment step; the workflow should still keep final state writes
  in the calling skill.

## Forbidden Active Contracts

Active skills must not rely on removed or old contracts. The canonical list is
kept in `tests/test_dead_names.py` so the forbidden spellings do not need to be
repeated in prose.
