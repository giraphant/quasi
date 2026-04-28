# Immersive Translate Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Quasi agent and Python CLI that translate a slug-addressed PDF through Immersive Translate's Zotero API using project-local config.

**Architecture:** Keep the feature in Quasi's existing thin-agent pattern. Put all operational logic in one Python script, keep the agent declarative, and store translated PDFs in `processing/translations/{slug}/`.

**Tech Stack:** Python 3 standard library plus `requests`, Quasi markdown agent specs, unittest.

---

### Task 1: Lock the contract with tests

**Files:**
- Create: `tests/test_immersive_translate.py`

- [ ] Add tests for project-local config path, default config values, slug-to-PDF resolution, ambiguous-match handling, and processing output paths.
- [ ] Run `python3 -m unittest tests.test_immersive_translate` and confirm the new tests fail before implementation.

### Task 2: Implement the CLI script

**Files:**
- Create: `scripts/translate/immersive_translate.py`

- [ ] Implement pure helpers first so the Task 1 tests pass.
- [ ] Add request helpers for auth-check, upload URL, upload, task creation, polling, and result download.
- [ ] Add a CLI entrypoint that resolves the slug, loads config, runs the translation flow, and prints a compact result block.
- [ ] Re-run `python3 -m unittest tests.test_immersive_translate` and confirm green.

### Task 3: Add the agent wrapper and docs

**Files:**
- Create: `agents/translate-agent.md`
- Modify: `README.md`

- [ ] Add the new agent with strict config-handling rules and the expected script invocation.
- [ ] Document the new config file and `processing/translations/{slug}/` output convention in `README.md`.

### Task 4: Verify the integrated change

**Files:**
- Verify: `tests/test_immersive_translate.py`
- Verify: `tests/`

- [ ] Run `python3 -m unittest tests.test_immersive_translate`.
- [ ] Run `python3 -m unittest discover -s tests`.
- [ ] Review the final diff for scope creep and keep only the requested feature.
