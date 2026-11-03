# quasi maintainer guide

quasi is a research-library toolkit for academic reading: it collects papers, books, talks, webpages, archival originals, translations and author portraits into a local vault, and supports topic research over that vault. The repository root is itself one agent skill (`SKILL.md`), with a deterministic Python capability layer inside it. Any harness that reads Agent Skills (Codex, Claude Code, agy, Pi) can run it.

`CLAUDE.md` only imports this file. Edit `AGENTS.md`.

Further reading: `docs/REDESIGN.md` (why the redesign, decisions and the round-by-round test record), `docs/SETUP.md` (one-time install: tools, secrets, skill links, permissions), `docs/PDF_PIPELINE.md` (measured OCR and translation pipeline; read it before touching `scripts/extract/` or `scripts/translate/`), `docs/ARCHIVE_STORAGE.md` (Archive storage and Marple contract), `docs/CHANGELOG.md`.

## Layout

```text
SKILL.md                 skill root: route to collect / research / draft; global conventions
collect/README.md        route by material type; rules shared by all materials
collect/<material>/      one leaf per material: README.md flow + search/acquire/prepare/writing pages
research/                the topic research loop and its writing brief
draft/                   placeholder; draft finalisation is to be redesigned
connectors/rex.md        the only place that knows how workers are launched (Rex panes)
scripts/quasi            single CLI entry; dispatches to scripts/commands/quasi-<command>
scripts/commands/        per-command shell shims; bootstrap the venv, load secrets, run the Python module
scripts/                 Python capabilities (search, download, extract, transcribe, translate,
                         webpage, archive, audit/typecheck, status, citation, proofread, localise, vault)
scripts/schemas/         single source of truth for artifact structure (frontmatter, H1, sections)
tests/, docs/            maintenance only; agents running the skill never read them
```

The whole repository is the installable skill: clone or link it as `quasi` into a skills directory (see `docs/SETUP.md`). Everything the skill needs at run time lives inside it.

## How the skill works

- The session the user opens is the orchestrator. It reads only the branch of the tree it walks: root → `collect/README.md` → one material leaf (or `research/README.md`).
- Writing always goes to a **writer**: a fresh interactive session in a Rex pane, given only a writing brief, input files and bibliographic facts, so writing can run on the model with the best prose (agy in real use, Codex in tests). Whole materials in a batch go to **material sessions**. At most three levels: main → material session → writer.
- Verify artifacts, not reports: `quasi status` says what exists, `quasi audit` says whether it conforms. Repair once with the brief, the audit diagnostics and the existing page; preserve user-written content.
- No Workflow, no receipts or JSON envelopes, no harness-native subagents. Rex commands appear only in `connectors/rex.md`; supporting another terminal framework means adding another connector page.
- Each quasi command is written as one plain command (no pipes, redirects, heredocs or `&&`), JSON is passed by file under `.quasi/temp/`, so harness permission prefix rules can match it.

## Writing skill pages

- Plain Chinese prose addressed to the executing model. Say what to do and why; no protocol vocabulary, schemas or pseudo-code.
- An entry file routes and states the rules inherited below it; a leaf opens with "如果你是被直接派到这里的，先读…". Keep the tree at most three levels deep.
- Writing briefs are craft prompts: who the writer is and for whom, the writing requirements, the style, then the page structure. Models mirror the register of their prompt; a protocol-heavy brief produces protocol-flavoured prose.
- Page structure in a brief must match `scripts/schemas/`. When the schema changes, update the brief in the same commit.

## CLI surface

| command | contract |
|---|---|
| `quasi search` | `book\|paper` metadata discovery; `kagi` web search |
| `quasi download` | `book candidates\|fetch`; `paper fetch\|diagnose`; `accept` |
| `quasi extract` | `epub\|text\|ocr\|ocr-generation\|split`; `ocr-generation` is the source/profile-bound immutable Paper/Book OCR transaction, one page range per call |
| `quasi audit` | `--path PATH`: mechanical autofix, typecheck, residual diagnostics |
| `quasi status` | read-only disk observation: `--kind paper\|book\|talk\|author\|topic\|webpage\|archive --slug SLUG --json`; translation also takes `--target-language TAG`; `--scan --json` |
| `quasi transcribe` | `observe\|prepare-media\|run\|classify\|silent` |
| `quasi webpage` | `inspect\|capture\|extract` one exact public webpage (capture needs macOS 11+) |
| `quasi archive` | `inspect` a source; `collect --request-file` publishes originals, manifest and page; `read` |
| `quasi translate` | `observe\|run` configured `immersive\|pdf2zh` translation |
| `quasi helpers` | `vault resolve`; `citation ...`; `proofread ...`; `localise ...`; `talk compress-media` |
| `quasi doctor` | venv sync and dependency check by profile |
| `quasi config` | `show [--json]\|set NAME [VALUE]\|unset NAME`: the user's keys in the macOS Keychain; secret values only via stdin or prompt. For the user and GUI front ends (Marple), not for agents |

- A deterministic CLI may write an artifact only when its command contract names that output path.
- `quasi status` takes artifact path templates from `scripts/schemas/operations.py::OPERATION_CATALOG`.
- Paper metadata merging treats Crossref as the authority for the journal container title and decodes its HTML entities at the adapter boundary. Do not let asynchronous adapter completion order choose `venue`; OpenAlex may omit meaningful punctuation from the same journal name.

## Paths

The current working directory is the vault root. `sources/` holds accepted source files; `processing/` holds inspectable intermediates (`papers/`, `chapters/`, `translations/`, `talks/`, `webpages/`); `vault/` holds reading pages (`papers/`, `books/`, `talks/`, `webpages/`, `archives/`, `authors/`, `topics/`); `.quasi/` holds temp files, worker prompts and replies, caches and manifests. Persistent tool data lives in `${CLAUDE_PLUGIN_DATA:-~/.cache/quasi}` (venv, throttle state).

## Secrets and configuration

Scripts read only `QUASI_*` environment variables. Every key lives in the macOS login Keychain, one generic-password item per key (service `quasi`, account = key name), owned by `scripts/config/config.py`. On macOS every Python-facing shim sources `scripts/load-config-env.sh`, which fills the missing `QUASI_*` values from those items; explicit `QUASI_*` values take precedence and values never enter argv. Items are only ever written through `/usr/bin/security` (via `quasi config set`, which feeds `security -i` on stdin), so the reads through the same tool never raise an access prompt; GUI front ends call `quasi config` instead of touching the Keychain themselves. Values are printable ASCII only, because `security -w` prints anything else as hex. The keys and what they are for are listed in `docs/SETUP.md`.

The repository is not a Claude plugin: a `.claude-plugin/plugin.json` here makes Claude Code treat the linked skill as a plugin named `quasi` that collides with an installed plugin of that name.

| variable | consumer |
|---|---|
| `QUASI_ANNA_DONATOR_KEY` | `scripts/download/aa.py` |
| `QUASI_COOKIECLOUD_SERVER`, `_UUID`, `_PASSWORD`, `_EZPROXY_DOMAIN`, `_EZPROXY_BASE_URL` | `scripts/download/cookiecloud.py` |
| `QUASI_TRANSLATE_BACKEND` | `scripts/commands/quasi-translate`, `scripts/translate/translate.py` |
| `QUASI_IMMERSIVE_AUTH_KEY` | `scripts/translate/immersive_translate.py` |
| `QUASI_TRANSLATE_BASE_URL`, `_API_KEY`, `_MODEL` | `scripts/translate/pdf2zh_translate.py` |
| `QUASI_KAGI_SESSION_TOKEN` | `scripts/search/`, `scripts/download/download.py` (mapped to `KAGI_SESSION_TOKEN` for the kagi CLI) |
| `QUASI_SONIOX_API_KEY` | `scripts/transcribe/engines.py` |
| `QUASI_WORKER_PERMISSIONS=full` | `connectors/rex.md`: launch workers with permission-bypass commands (dev machine only). A login-shell variable, not a Keychain key: the agent reads it directly |

## Extraction and translation invariants

The measured reasoning behind each rule is in `docs/PDF_PIPELINE.md`; do not relax one without reading its paragraph there.

- `quasi-extract ocr` defaults to MinerU2.5-Pro `two_step_extract`, with `mineru-vl-utils==2.0.5`, `mlx-vlm==0.7.3`, and `mlx==0.32.2`. DS OCR2 execution is retired; Tesseract is explicit-only. Missing dependencies, inference failure or missing text blocks must not silently become another engine or per-line output. Do not reject a candidate OCR model for requiring transformers 5.x.
- New translations of image-bearing sources require `--layout` at the existing recovery path before provider work. Classify by page image objects, never font names. In-PDF layout evidence binds the source hash and actual paragraph placement; unproven recovery files cannot bypass the gate. Successful translation fences are cleaned recursively; lock waiters recheck inode identity before entering after lock-file removal.
- `--layout` accepts unfamiliar nonempty MinerU blocks as text; labels choose presentation rather than admission. Translation Prepare names `--recognition-json` to preserve complete source-bound OCR before placement and reuse it after placement failures. Raw recognition is not layout proof or a Workflow cursor. Optional `--review-json` applies source-bound page corrections after visual review; keep raw recognition unchanged and embed the applied review in the layout PDF. Reviewed blank scans retain their images; body pages retain unaffected text.
- `--layout` writes one invisible textbox per MinerU paragraph over the scan image, strips old text at the operator level (strings, comments and inline images are lexed, never regex-matched) including Form XObjects, and leaves pages without image objects unchanged. Fit paragraph text into its own box, use line height 1.15, snap body sizes within 20% of the book-wide dominant size, and start at SHRINK 0.90. Titles and page furniture keep their own sizes. Tables/formulas stay as images in layout; ordinary text OCR retains their recognized content. Clean inline LaTeX/HTML before placement.
- Source-bound MinerU evidence records body-paragraph disagreement with a usable old layer (<0.85 word-sequence agreement), retains the new text, and exempts classified reference/footnote blocks. Missing baselines and empty recognition pages remain explicit. The check reports disagreement, not truth or a guarantee against hallucination. Generation manifests retain the same evidence with global page numbers.
- Both translate backends share one output contract (`processing/translations/{slug}-{canonical-target-lower}.pdf`, with Mainland Chinese canonicalized to `-zh.pdf`; alternating original/translated pages, bookmarks) and both must run `tounicode.py::repair_pdf` before the Chinese body coverage gate (median >= 0.30; ratios < 0.05 on at most 10% of measurable body pages). Exclude only source-evidenced bibliography/index/notes sections, report their ranges, and fall back to all measurable pages if exclusions leave fewer than three; ambiguous and mixed body pages remain scored. Provider adapters map canonical `zh` to `zh-CN`. Rejected or uncertain generations stay in their fenced `processing/translations/.{stem}.translate-*` directory and never become canonical output.
- Backend selection is user config (`translate_backend`), not a free caller argument. For pdf2zh, a root-only `translate_base_url` gets `/v1` appended; explicit paths are preserved. Provider credentials stay out of argv.

## Development and tests

- Development and live tests run on the Mac Mini (`rex -S "Mac Mini"`): repo `~/Vibe/quasi`, test vault `~/Vibe/quasi-testvault`, full worker permissions. Use a test vault, never the user's library.
- All tests live in `tests/`. Run them in an environment with `scripts/requirements.txt` plus `pytest`: `python -m pytest tests -q`.
- `tests/test_skill_tree.py` checks that every path and quasi command a skill page mentions exists. Keep it passing when moving or renaming skill pages.
- Python dependencies are declared in `scripts/requirements.txt`; `scripts/bootstrap-venv.sh` installs them and every shim self-bootstraps. Do not add pip installs to individual shims.

## Change checklist

1. Artifact structure change: edit `scripts/schemas/`, then the matching writing brief under `collect/` or `research/`.
2. New or renamed CLI command: update the CLI table here and every skill page that calls it.
3. Skill page moved or renamed: update the routing table that points to it; run `tests/test_skill_tree.py`.
4. Worker launch or harness change: edit `connectors/rex.md` only.
5. New key: add it to `scripts/config/config.py::KEYS`, the table above and `docs/SETUP.md`.
6. Record live test rounds and design decisions in `docs/REDESIGN.md`.
