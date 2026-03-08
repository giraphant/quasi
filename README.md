# quasi

A Claude Code plugin for academic literature processing. Automates the full pipeline from discovery to synthesis: search, download, extract, analyze, and synthesize scholarly texts.

## What it does

quasi turns a book or paper into structured, analyzable knowledge. Given an EPUB/PDF, it extracts chapters, runs each through a parameterized analysis template, and produces a synthesis with cross-references. It also chains citations to build reading corpora around a topic.

## Skills

### Atomic skills — single operations

| Skill | Type | Description |
|-------|------|-------------|
| `search` | tool | Unified search across Google Books, OpenLibrary, OpenAlex, Anna's Archive, Unpaywall, Semantic Scholar, and Wayback Machine |
| `download` | tool | File acquisition by MD5 (books) or DOI/URL (papers), with OA/Wayback cascade fallback |
| `extract` | tool | Chapter-level text extraction from EPUB/PDF, with OCR support for scanned PDFs |
| `analyze` | template | Structured analysis of a single text (chapter or paper) using parameterized prompt templates |
| `synthesize` | template | Cross-text synthesis reports, aggregated reference lists, and knowledge base updates |

### Composite skills — multi-step workflows

| Skill | Description |
|-------|-------------|
| `process-book` | EPUB/PDF → chapter extraction → per-chapter analysis → book-level synthesis |
| `process-journal` | Journal scan report → batch download → per-paper analysis → synthesis |
| `process-author` | Scholar discovery (up to 5 books + 10 papers) → acquire → analyze → author profile |
| `citation-snowball` | Seed paper → citation chain expansion round by round → topic-focused corpus + synthesis |

Composite skills are subagent-driven: the main process dispatches coordinator agents that handle all internal orchestration, keeping the context window clean.

## Usage

```
# Process a book
/quasi:process-book oxford-handbook-sociology-body

# Search for papers by an author
/quasi:search --mode papers --author "Donna Haraway" --year_from 2000

# Download a paper by DOI
/quasi:download 10.1177/1357034X09337767

# Build a citation corpus from a seed paper
/quasi:citation-snowball posthuman-embodiment --seed 10.xxxx/xxxxx --topic "posthuman embodiment and digital technology"

# Process a scholar's body of work
/quasi:process-author donna-haraway
```

## Architecture

```
quasi/
├── .claude-plugin/          # Plugin manifest
├── shared/
│   └── output-format.md     # Frontmatter standards & naming conventions
└── skills/
    ├── search/              # SKILL.md + scripts/search.py
    ├── download/            # SKILL.md + scripts/download.py
    ├── extract/             # SKILL.md + scripts/split_chapters.py, process_epub.py, ocr_pdf.sh
    ├── analyze/             # SKILL.md + prompts/text-analysis.md, snowball-extra.md
    ├── synthesize/          # SKILL.md + prompts/synthesis.md, kb-update.md + scripts/aggregate_refs.py
    ├── process-book/        # SKILL.md (composite)
    ├── process-journal/     # SKILL.md (composite)
    ├── process-author/      # SKILL.md (composite)
    └── citation-snowball/   # SKILL.md (composite)
```

## Installation

As a Claude Code plugin from a [custom marketplace](https://docs.anthropic.com/en/docs/claude-code/plugins):

```bash
claude plugin add quasi --marketplace ramu-toolkit
```

Or register the repo as a local marketplace:

```jsonc
// ~/.claude/plugins/known_marketplaces.json
{
  "ramu-toolkit": {
    "source": { "source": "github", "repo": "giraphant/quasi" },
    "autoUpdate": true
  }
}
```

## Configuration

Each project provides its own analysis parameters in its `CLAUDE.md`:

```yaml
topic: "your research topic"
preamble: >
  Project-specific instructions for the analysis template
  (e.g., "This is a humanities text, focus on theoretical arguments...")
```

These are injected into the `{topic}` and `{preamble}` placeholders in `analyze/prompts/text-analysis.md`.

## License

Private use.
