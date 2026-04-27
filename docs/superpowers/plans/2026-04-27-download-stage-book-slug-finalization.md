# Download-Stage Book Slug Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalize canonical book slugs during download, allow one-time book identity correction from file contents, and remove slug re-derivation from downstream workflows.

**Architecture:** Extend `scripts/download/download.py` with pure helper functions for canonical slug generation and book-match decisions, then add file-content evidence extraction for PDF/EPUB and a manifest-aware book finalization path. Update `discover-agent`, `download-agent`, `process-book`, and `process-author` so `discover` emits canonical-style candidate slugs, `download` verifies and corrects them once, and downstream workflows consume final slugs without recomputing them.

**Tech Stack:** Python 3 (`json`, `pathlib`, `re`, `zipfile`, `xml.etree.ElementTree`, `unittest.mock`), existing download stack in `scripts/download/download.py`, markdown agent/skill docs.

---

### Task 1: Add pure book slug and match helpers to `download.py`

**Files:**
- Modify: `scripts/download/download.py`
- Create: `tests/test_download_book_identity.py`

- [ ] **Step 1: Write the failing tests for canonical slug generation and relaxed match rules**

```python
import importlib.util
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


class DownloadBookIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.download = load_module(
            "download_module",
            REPO_ROOT / "scripts" / "download" / "download.py",
        )

    def test_build_book_slug_uses_author_title_year_format(self):
        slug = self.download.build_book_slug(
            author="Ashley Shew",
            title="Against Technoableism: Rethinking Who Needs Improvement",
            year=2023,
        )
        self.assertEqual(slug, "shew-against-technoableism-2023")

    def test_same_book_match_ignores_subtitle_and_edition_noise(self):
        self.assertTrue(
            self.download.is_same_book(
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
                actual_author="Ashley Shew",
                actual_title="Against Technoableism: Rethinking Who Needs Improvement (paperback edition)",
            )
        )

    def test_different_author_fails_even_when_topic_is_similar(self):
        self.assertFalse(
            self.download.is_same_book(
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
                actual_author="Wendy Chun",
                actual_title="Against Technoableism",
            )
        )

    def test_finalize_book_identity_can_correct_candidate_slug(self):
        final = self.download.finalize_book_identity(
            manifest_book={
                "title": "Against Technoableism",
                "year": 2022,
                "slug": "shew-against-technoableism-2022",
            },
            actual_author="Ashley Shew",
            actual_title="Against Technoableism: Rethinking Who Needs Improvement",
            actual_year=2023,
        )
        self.assertEqual(final["slug"], "shew-against-technoableism-2023")
        self.assertEqual(final["year"], 2023)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: FAIL with `AttributeError` because `build_book_slug`, `is_same_book`, and `finalize_book_identity` do not exist yet.

- [ ] **Step 3: Implement the minimal pure helpers in `download.py`**

```python
def _normalize_book_title(title):
    text = (title or "").lower()
    text = re.sub(r"\(.*?edition.*?\)", "", text)
    text = re.split(r"[:\-\u2014]", text, maxsplit=1)[0]
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _author_surname(author):
    parts = re.findall(r"[a-zA-Z]+", (author or "").lower())
    return parts[-1] if parts else "unknown"


def build_book_slug(author, title, year):
    short_title = _normalize_book_title(title)
    words = short_title.split()[:4]
    return slugify(f"{_author_surname(author)}-{' '.join(words)}-{year}")


def is_same_book(expected_author, expected_title, actual_author, actual_title):
    if _author_surname(expected_author) != _author_surname(actual_author):
        return False
    expected = _normalize_book_title(expected_title)
    actual = _normalize_book_title(actual_title)
    return bool(expected and actual and (expected in actual or actual in expected))


def finalize_book_identity(manifest_book, actual_author, actual_title, actual_year):
    final_year = actual_year or manifest_book.get("year")
    final_title = actual_title or manifest_book.get("title")
    final_author = actual_author or manifest_book.get("author")
    return {
        **manifest_book,
        "title": final_title,
        "year": final_year,
        "slug": build_book_slug(final_author, final_title, final_year),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: PASS for all four book-identity tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/download/download.py tests/test_download_book_identity.py
git commit -m "feat: add canonical book slug helpers"
```

### Task 2: Add PDF/EPUB evidence extraction for book verification

**Files:**
- Modify: `scripts/download/download.py`
- Modify: `tests/test_download_book_identity.py`

- [ ] **Step 1: Write the failing tests for PDF/EPUB evidence extraction hooks**

```python
from unittest import mock

    def test_verify_book_pdf_uses_first_page_text_not_metadata(self):
        with mock.patch.object(self.download, "_extract_pdf_text", return_value="against technoableism ashley shew copyright 2023"):
            result = self.download.verify_book_file(
                Path("/tmp/book.pdf"),
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
            )
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["author"], "Ashley Shew")

    def test_verify_book_file_returns_needs_review_when_text_is_too_weak(self):
        with mock.patch.object(self.download, "_extract_pdf_text", return_value="table of contents chapter 1 chapter 2"):
            result = self.download.verify_book_file(
                Path("/tmp/book.pdf"),
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
            )
        self.assertEqual(result["status"], "needs_review")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: FAIL with `AttributeError` because `verify_book_file()` does not exist yet.

- [ ] **Step 3: Implement minimal evidence extraction and verification**

```python
def _extract_epub_text(epub_path, max_items=3):
    import zipfile

    texts = []
    with zipfile.ZipFile(epub_path) as zf:
        for name in zf.namelist():
            if not name.endswith(('.xhtml', '.html', '.htm')):
                continue
            if len(texts) >= max_items:
                break
            data = zf.read(name).decode('utf-8', errors='ignore')
            text = re.sub(r'<[^>]+>', ' ', data)
            texts.append(text)
    return ' '.join(texts).lower()


def _guess_year(text):
    matches = re.findall(r"\b(?:19|20)\d{2}\b", text)
    return int(matches[0]) if matches else None


def _title_keywords(title):
    words = re.findall(r"[a-z0-9]+", _normalize_book_title(title))
    return [word for word in words if len(word) >= 4]


def _text_mentions_author(text, expected_author):
    surname = _author_surname(expected_author)
    return len(surname) >= 3 and surname in text.lower()


def _text_mentions_title(text, expected_title):
    lowered = text.lower()
    keywords = _title_keywords(expected_title)
    hits = sum(1 for word in keywords if word in lowered)
    return hits >= max(2, min(3, len(keywords)))


def verify_book_file(path, expected_author, expected_title):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        text = _extract_pdf_text(str(path), max_pages=4)
    elif suffix == '.epub':
        text = _extract_epub_text(path)
    else:
        return {"status": "needs_review", "reason": "unsupported_format"}

    if not text or len(text.strip()) < 40:
        return {"status": "needs_review", "reason": "weak_evidence"}

    if not _text_mentions_author(text, expected_author):
        return {"status": "mismatch", "reason": "author_not_found"}
    if not _text_mentions_title(text, expected_title):
        return {"status": "mismatch", "reason": "title_or_author_not_found"}

    return {
        "status": "match",
        "author": expected_author,
        "title": expected_title,
        "year": _guess_year(text),
        "evidence": text[:500],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: PASS for the helper tests plus the new verification tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/download/download.py tests/test_download_book_identity.py
git commit -m "feat: add book file verification helpers"
```

### Task 3: Add manifest-aware book finalization to `download.py`

**Files:**
- Modify: `scripts/download/download.py`
- Modify: `tests/test_download_book_identity.py`

- [ ] **Step 1: Write the failing test for book manifest finalization and source rename**

```python
import json
import tempfile

    def test_finalize_downloaded_book_updates_manifest_and_renames_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            sources_dir = root / "sources"
            sources_dir.mkdir()
            old_path = sources_dir / "against-technoableism.epub"
            old_path.write_bytes(b"epub")
            manifest_path.write_text(
                json.dumps({
                    "books": [
                        {
                            "title": "Against Technoableism",
                            "year": 2022,
                            "slug": "shew-against-technoableism-2022",
                            "status": "discovered",
                            "source": str(old_path),
                        }
                    ]
                }),
                encoding="utf-8",
            )

            with mock.patch.object(self.download, "verify_book_file", return_value={
                "status": "match",
                "author": "Ashley Shew",
                "title": "Against Technoableism: Rethinking Who Needs Improvement",
                "year": 2023,
            }):
                final = self.download.finalize_downloaded_book(
                    manifest_path=manifest_path,
                    book_index=0,
                    downloaded_path=old_path,
                    expected_author="Ashley Shew",
                )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(final["slug"], "shew-against-technoableism-2023")
            self.assertEqual(manifest["books"][0]["slug"], "shew-against-technoableism-2023")
            self.assertTrue((sources_dir / "shew-against-technoableism-2023.epub").exists())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: FAIL with `AttributeError` because `finalize_downloaded_book()` does not exist yet.

- [ ] **Step 3: Implement finalization and manifest rewrite**

```python
def finalize_downloaded_book(manifest_path, book_index, downloaded_path, expected_author):
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    book = manifest["books"][book_index]
    verification = verify_book_file(
        Path(downloaded_path),
        expected_author=expected_author,
        expected_title=book["title"],
    )
    if verification["status"] != "match":
        book["status"] = verification["status"]
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return book

    final = finalize_book_identity(
        manifest_book=book,
        actual_author=verification["author"],
        actual_title=verification["title"],
        actual_year=verification.get("year"),
    )
    new_path = Path(downloaded_path).with_name(f"{final['slug']}{Path(downloaded_path).suffix}")
    if new_path != Path(downloaded_path):
        Path(downloaded_path).rename(new_path)
    final["source"] = str(new_path)
    final["status"] = "acquired"
    manifest["books"][book_index] = final
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return final
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_download_book_identity -v`
Expected: PASS for the manifest finalization test and all earlier helper tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/download/download.py tests/test_download_book_identity.py
git commit -m "feat: finalize downloaded books with canonical slugs"
```

### Task 4: Update agent and workflow docs to consume only final slugs

**Files:**
- Modify: `agents/discover-agent.md`
- Modify: `agents/download-agent.md`
- Modify: `skills/process-book/SKILL.md`
- Modify: `skills/process-author/SKILL.md`

- [ ] **Step 1: Update `discover-agent` to require canonical-style candidate slugs**

```markdown
## slug 约束（书籍）

- `books[].slug` 必须直接使用 canonical 格式：`{author-surname}-{short-title}-{year}`
- 不允许只写短标题型旧名，例如 `against-technoableism`、`work-pray-code`
- 该 slug 是候选 canonical slug，后续允许由 download-agent 基于文件内容做一次纠偏
```

- [ ] **Step 2: Update `download-agent` with verification and manifest rewrite steps**

```markdown
### 书籍下载后验真（必须执行）

1. 书籍下载完成后，读取文件前部内容验真
2. PDF 不读 metadata，只看 title page / copyright page / 前部正文可提取文本
3. EPUB metadata 只作辅助，主证据仍以正文前部文本为准
4. 只要确认是同一本书、同一个作者，就视为 `match`
5. 若 `title/year/slug` 有偏差，允许重命名为新的 canonical slug
6. 必须回写 manifest 中该书的 `title`、`year`、`slug`、`source/file`、`status`
```

- [ ] **Step 3: Remove slug re-derivation from `process-book`**

```markdown
# 0. 使用已定稿 slug
book_slug = parse_args()
source_file = Glob("sources/{book_slug}.epub|.pdf")
chapters_dir = f"processing/chapters/{book_slug}/"

# 不再从 source_file 推导新的 slug
```

- [ ] **Step 4: Clarify `process-author` consumes finalized `book.slug` only**

```markdown
# 2. ACQUIRE
manifest = read_json(manifest_path)
if any(status == "discovered"):
    Agent("quasi:download-agent", foreground=True,
          prompt=f"manifest_path: {manifest_path}, mode: both")

# 说明：Phase 2 结束后，manifest.books[*].slug 必须已经是 download-agent
# 验真并定稿后的最终 slug。Phase 3 之后只复用，不再重算。
```

- [ ] **Step 5: Verify the docs are internally consistent**

Run: `rg -n "derive_slug|against-technoableism|work-pray-code|final slug|canonical" agents/discover-agent.md agents/download-agent.md skills/process-book/SKILL.md skills/process-author/SKILL.md`
Expected: `derive_slug` is removed from `process-book`; canonical/final slug wording appears in `discover-agent`, `download-agent`, and `process-author`.

- [ ] **Step 6: Commit**

```bash
git add agents/discover-agent.md agents/download-agent.md skills/process-book/SKILL.md skills/process-author/SKILL.md
git commit -m "docs: finalize slug responsibilities across workflows"
```

### Task 5: Verify the end-to-end behavior for future downloads

**Files:**
- Modify: `tests/test_download_book_identity.py`

- [ ] **Step 1: Add an end-to-end unit test for candidate-slug correction**

```python
    def test_candidate_slug_is_corrected_once_before_process_book_uses_it(self):
        manifest_book = {
            "title": "Work Pray Code",
            "year": 2021,
            "slug": "chen-work-pray-code-2021",
            "status": "discovered",
        }

        final = self.download.finalize_book_identity(
            manifest_book=manifest_book,
            actual_author="Carolyn Chen",
            actual_title="Work Pray Code: When Work Becomes Religion in Silicon Valley",
            actual_year=2022,
        )

        self.assertEqual(final["slug"], "chen-work-pray-code-2022")
        self.assertEqual(final["title"], "Work Pray Code: When Work Becomes Religion in Silicon Valley")
```

- [ ] **Step 2: Run the focused tests**

Run: `python3 -m unittest tests.test_download_book_identity tests.test_config_paths -v`
Expected: PASS; the new slug finalization path does not break the existing config-path guarantees.

- [ ] **Step 3: Smoke-check the CLI help for `download.py`**

Run: `python3 scripts/download/download.py --help`
Expected: Existing CLI still works and no previous download path is removed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_download_book_identity.py
git commit -m "test: cover one-time canonical book slug correction"
```
