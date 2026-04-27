# Historical Source Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align historical `sources/` filenames to existing `vault/books/{slug}` directory names without renaming any book directories.

**Architecture:** Add a one-off maintenance script that scans a library root, builds a conservative rename plan from existing `vault/books`, `processing/authors/*/manifest.json`, `processing/chapters`, and `sources`, and only applies high-confidence renames. Keep the logic pure and testable; the CLI should default to dry-run and emit a machine-readable report before any rename is applied.

**Tech Stack:** Python 3 standard library (`argparse`, `json`, `pathlib`, `tempfile`, `shutil`), existing repo test stack (`unittest`).

---

### Task 1: Create the alignment planner with pure matching logic

**Files:**
- Create: `scripts/maintenance/align_book_sources.py`
- Create: `tests/test_align_book_sources.py`

- [ ] **Step 1: Write the failing tests for exact-match, manifest-assisted, and conflict cases**

```python
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlignBookSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aligner = load_module(
            "align_book_sources",
            REPO_ROOT / "scripts" / "maintenance" / "align_book_sources.py",
        )

    def test_exact_slug_match_is_reported_as_aligned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "chen-work-pray-code-2022").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            (root / "sources" / "chen-work-pray-code-2022.pdf").write_bytes(b"pdf")

            report = self.aligner.build_alignment_report(root)

            self.assertEqual(report["aligned"], [
                {
                    "slug": "chen-work-pray-code-2022",
                    "source": "sources/chen-work-pray-code-2022.pdf",
                }
            ])
            self.assertEqual(report["renamed"], [])
            self.assertEqual(report["needs_review"], [])

    def test_manifest_source_path_can_drive_high_confidence_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "shew-against-technoableism-2023").mkdir(parents=True)
            (root / "processing" / "authors" / "ashley-shew").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            old_file = root / "sources" / "against-technoableism.epub"
            old_file.write_bytes(b"epub")
            (root / "processing" / "authors" / "ashley-shew" / "manifest.json").write_text(
                '''{
  "books": [
    {
      "title": "Against Technoableism",
      "slug": "shew-against-technoableism-2023",
      "source": "sources/against-technoableism.epub",
      "status": "acquired"
    }
  ]
}''',
                encoding="utf-8",
            )

            report = self.aligner.build_alignment_report(root)

            self.assertEqual(report["renamed"], [
                {
                    "slug": "shew-against-technoableism-2023",
                    "from": "sources/against-technoableism.epub",
                    "to": "sources/shew-against-technoableism-2023.epub",
                    "reason": "manifest_source_path",
                }
            ])

    def test_existing_target_file_blocks_automatic_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "shew-against-technoableism-2023").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            (root / "sources" / "against-technoableism.epub").write_bytes(b"old")
            (root / "sources" / "shew-against-technoableism-2023.epub").write_bytes(b"new")

            report = self.aligner.build_alignment_report(root)

            self.assertEqual(report["renamed"], [])
            self.assertEqual(report["needs_review"], [
                {
                    "slug": "shew-against-technoableism-2023",
                    "candidates": [
                        "sources/against-technoableism.epub",
                        "sources/shew-against-technoableism-2023.epub",
                    ],
                    "reason": "target_exists_or_ambiguous",
                }
            ])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: FAIL with `FileNotFoundError` or import failure because `scripts/maintenance/align_book_sources.py` does not exist yet.

- [ ] **Step 3: Implement the minimal planner and report builder**

```python
#!/usr/bin/env python3

import json
from pathlib import Path


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def collect_book_slugs(root: Path) -> list[str]:
    books_dir = root / "vault" / "books"
    if not books_dir.exists():
        return []
    return sorted(p.name for p in books_dir.iterdir() if p.is_dir())


def collect_source_files(root: Path) -> dict[str, list[Path]]:
    sources_dir = root / "sources"
    if not sources_dir.exists():
        return {}
    by_stem: dict[str, list[Path]] = {}
    for path in sorted(p for p in sources_dir.iterdir() if p.is_file()):
        by_stem.setdefault(path.stem, []).append(path)
    return by_stem


def collect_manifest_source_hints(root: Path) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    for manifest_path in sorted((root / "processing" / "authors").glob("*/manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for book in data.get("books", []):
            slug = book.get("slug")
            source = book.get("source") or book.get("file")
            if slug and source:
                hints.setdefault(slug, []).append(source)
    return hints


def build_alignment_report(root: Path) -> dict:
    source_by_stem = collect_source_files(root)
    manifest_hints = collect_manifest_source_hints(root)
    aligned = []
    renamed = []
    needs_review = []

    for slug in collect_book_slugs(root):
        exact = source_by_stem.get(slug, [])
        if len(exact) == 1:
            aligned.append({"slug": slug, "source": _rel(exact[0], root)})
            continue
        if len(exact) > 1:
            needs_review.append({
                "slug": slug,
                "candidates": [_rel(path, root) for path in exact],
                "reason": "target_exists_or_ambiguous",
            })
            continue

        hint_paths = manifest_hints.get(slug, [])
        if len(hint_paths) == 1:
            old_rel = hint_paths[0]
            old_path = root / old_rel
            if old_path.exists():
                target_path = old_path.with_name(f"{slug}{old_path.suffix}")
                if target_path.exists():
                    needs_review.append({
                        "slug": slug,
                        "candidates": sorted([old_rel, _rel(target_path, root)]),
                        "reason": "target_exists_or_ambiguous",
                    })
                else:
                    renamed.append({
                        "slug": slug,
                        "from": old_rel,
                        "to": _rel(target_path, root),
                        "reason": "manifest_source_path",
                    })
                continue

        needs_review.append({
            "slug": slug,
            "candidates": [],
            "reason": "no_high_confidence_source_match",
        })

    return {
        "aligned": aligned,
        "renamed": renamed,
        "needs_review": needs_review,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: PASS for all three tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/maintenance/align_book_sources.py tests/test_align_book_sources.py
git commit -m "feat: add historical source alignment planner"
```

### Task 2: Add front-text confirmation for unresolved source candidates

**Files:**
- Modify: `scripts/maintenance/align_book_sources.py`
- Modify: `tests/test_align_book_sources.py`

- [ ] **Step 1: Write the failing tests for front-text confirmation and weak evidence fallback**

```python
    def test_front_text_match_can_confirm_old_source_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "chen-work-pray-code-2022").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            (root / "sources" / "work-pray-code.pdf").write_bytes(b"pdf")

            with unittest.mock.patch.object(
                self.aligner,
                "extract_source_text",
                return_value="work pray code carolyn chen when work becomes religion in silicon valley",
            ):
                report = self.aligner.build_alignment_report(root)

            self.assertEqual(report["renamed"], [
                {
                    "slug": "chen-work-pray-code-2022",
                    "from": "sources/work-pray-code.pdf",
                    "to": "sources/chen-work-pray-code-2022.pdf",
                    "reason": "front_text_match",
                }
            ])

    def test_weak_front_text_stays_in_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "book-one-2020").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            (root / "sources" / "unknown-book.pdf").write_bytes(b"pdf")

            with unittest.mock.patch.object(
                self.aligner,
                "extract_source_text",
                return_value="chapter one chapter two table of contents",
            ):
                report = self.aligner.build_alignment_report(root)

            self.assertEqual(report["renamed"], [])
            self.assertEqual(report["needs_review"][0]["reason"], "no_high_confidence_source_match")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: FAIL because `extract_source_text()` and front-text-based matching do not exist yet.

- [ ] **Step 3: Implement content probing for unresolved source files**

```python
def extract_source_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-l", "4", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                return result.stdout.lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    if path.suffix.lower() == ".epub":
        with zipfile.ZipFile(path) as zf:
            chunks = []
            for name in zf.namelist():
                if name.endswith((".xhtml", ".html", ".htm")):
                    chunks.append(re.sub(r"<[^>]+>", " ", zf.read(name).decode("utf-8", errors="ignore")))
                if len(chunks) >= 3:
                    break
        return " ".join(chunks).lower()
    return ""


def _front_text_matches_slug(text: str, slug: str) -> bool:
    if not text:
        return False
    parts = slug.split("-")
    if len(parts) < 3:
        return False
    surname = parts[0]
    title_words = [word for word in parts[1:-1] if len(word) >= 4]
    title_hits = sum(1 for word in title_words if word in text)
    return surname in text and title_hits >= max(2, min(3, len(title_words)))


def _probe_front_text_matches(root: Path, slug: str, source_by_stem: dict[str, list[Path]]):
    candidates = []
    for paths in source_by_stem.values():
        for path in paths:
            text = extract_source_text(path)
            if _front_text_matches_slug(text, slug):
                candidates.append(path)
    return candidates


def build_alignment_report(root: Path) -> dict:
    source_by_stem = collect_source_files(root)
    manifest_hints = collect_manifest_source_hints(root)
    aligned = []
    renamed = []
    needs_review = []

    for slug in collect_book_slugs(root):
        exact = source_by_stem.get(slug, [])
        if len(exact) == 1:
            aligned.append({"slug": slug, "source": _rel(exact[0], root)})
            continue
        if len(exact) > 1:
            needs_review.append({
                "slug": slug,
                "candidates": [_rel(path, root) for path in exact],
                "reason": "target_exists_or_ambiguous",
            })
            continue

        hint_paths = manifest_hints.get(slug, [])
        if len(hint_paths) == 1:
            old_rel = hint_paths[0]
            old_path = root / old_rel
            if old_path.exists():
                target_path = old_path.with_name(f"{slug}{old_path.suffix}")
                if target_path.exists():
                    needs_review.append({
                        "slug": slug,
                        "candidates": sorted([old_rel, _rel(target_path, root)]),
                        "reason": "target_exists_or_ambiguous",
                    })
                else:
                    renamed.append({
                        "slug": slug,
                        "from": old_rel,
                        "to": _rel(target_path, root),
                        "reason": "manifest_source_path",
                    })
                continue

        front_text_matches = _probe_front_text_matches(root, slug, source_by_stem)
        if len(front_text_matches) == 1:
            old_path = front_text_matches[0]
            target_path = old_path.with_name(f"{slug}{old_path.suffix}")
            if target_path.exists():
                needs_review.append({
                    "slug": slug,
                    "candidates": sorted([_rel(old_path, root), _rel(target_path, root)]),
                    "reason": "target_exists_or_ambiguous",
                })
            else:
                renamed.append({
                    "slug": slug,
                    "from": _rel(old_path, root),
                    "to": _rel(target_path, root),
                    "reason": "front_text_match",
                })
            continue

        needs_review.append({
            "slug": slug,
            "candidates": [_rel(path, root) for path in front_text_matches],
            "reason": "no_high_confidence_source_match",
        })

    return {
        "aligned": aligned,
        "renamed": renamed,
        "needs_review": needs_review,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: PASS for the original planner tests plus the new front-text confirmation tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/maintenance/align_book_sources.py tests/test_align_book_sources.py
git commit -m "feat: add front-text confirmation for source alignment"
```

### Task 3: Add safe apply mode, JSON report output, and dry-run CLI

**Files:**
- Modify: `scripts/maintenance/align_book_sources.py`
- Modify: `tests/test_align_book_sources.py`

- [ ] **Step 1: Write the failing tests for apply mode and JSON output**

```python
    def test_apply_report_renames_only_high_confidence_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vault" / "books" / "chen-work-pray-code-2022").mkdir(parents=True)
            (root / "processing" / "authors" / "julie-chen").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            old_file = root / "sources" / "work-pray-code.pdf"
            old_file.write_bytes(b"pdf")
            (root / "processing" / "authors" / "julie-chen" / "manifest.json").write_text(
                '''{"books":[{"slug":"chen-work-pray-code-2022","source":"sources/work-pray-code.pdf"}]}''',
                encoding="utf-8",
            )

            report = self.aligner.build_alignment_report(root)
            self.aligner.apply_alignment_report(root, report)

            self.assertFalse(old_file.exists())
            self.assertTrue((root / "sources" / "chen-work-pray-code-2022.pdf").exists())

    def test_main_writes_json_report_in_dry_run_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "report.json"
            (root / "vault" / "books" / "book-one-2020").mkdir(parents=True)
            (root / "sources").mkdir(parents=True)
            (root / "sources" / "book-one-2020.pdf").write_bytes(b"pdf")

            exit_code = self.aligner.main([
                "--library-root", str(root),
                "--report", str(report_path),
            ])

            self.assertEqual(exit_code, 0)
            written = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(written["aligned"][0]["slug"], "book-one-2020")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: FAIL with `AttributeError` because `apply_alignment_report()` and `main()` do not exist yet.

- [ ] **Step 3: Implement dry-run CLI, report writing, and apply mode**

```python
import argparse


def apply_alignment_report(root: Path, report: dict) -> None:
    for item in report["renamed"]:
        src = root / item["from"]
        dst = root / item["to"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align historical sources filenames to existing book slugs",
    )
    parser.add_argument("--library-root", required=True)
    parser.add_argument("--report", help="Write JSON report to this path")
    parser.add_argument("--apply", action="store_true", help="Apply planned renames")
    args = parser.parse_args(argv)

    root = Path(args.library_root).resolve()
    report = build_alignment_report(root)

    if args.report:
        report_path = Path(args.report)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.apply:
        apply_alignment_report(root, report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_align_book_sources -v`
Expected: PASS for the original planner tests plus the new apply/report tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/maintenance/align_book_sources.py tests/test_align_book_sources.py
git commit -m "feat: add safe apply mode for historical source alignment"
```

### Task 4: Validate against the real library before any rename

**Files:**
- Modify: none (manual validation only)

- [ ] **Step 1: Produce a dry-run report against the real library**

Run: `python3 scripts/maintenance/align_book_sources.py --library-root ../bts --report /tmp/bts-source-alignment-report.json`
Expected: Exit code 0 and a JSON report written to `/tmp/bts-source-alignment-report.json` with non-empty `aligned` and a reviewable set of `renamed` / `needs_review` items.

- [ ] **Step 2: Inspect the rename set before applying**

Run: `python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('/tmp/bts-source-alignment-report.json').read_text())
print('aligned', len(report['aligned']))
print('renamed', len(report['renamed']))
print('needs_review', len(report['needs_review']))
for item in report['renamed'][:20]:
    print(item)
PY`
Expected: A small sample of high-confidence renames with reasons like `manifest_source_path`; any ambiguous items should appear in `needs_review`, not `renamed`.

- [ ] **Step 3: Apply only after manual confirmation of the report**

Run: `python3 scripts/maintenance/align_book_sources.py --library-root ../bts --report /tmp/bts-source-alignment-report.json --apply`
Expected: Only the files listed in `renamed` are renamed; no book directories are touched.

- [ ] **Step 4: Verify post-apply consistency**

Run: `comm -23 <(find ../bts/vault/books -mindepth 1 -maxdepth 1 -type d | sed 's#^.*/##' | sort) <(find ../bts/sources -maxdepth 1 -type f | sed 's#^.*/##' | sed 's/\.[^.]*$//' | sort) | sed -n '1,50p'`
Expected: The unmatched set is smaller than before and mainly contains intentional review cases, not obvious old-name drift.

- [ ] **Step 5: Commit only the script/test work, not external library data**

```bash
git status --short
git diff --stat
# No commit expected here unless validation uncovered a bug that required a code change.
```
