import importlib.util
import tempfile
import unittest
import zipfile
from textwrap import dedent
from unittest import mock
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

    def test_build_book_slug_preserves_hyphenated_main_title(self):
        slug = self.download.build_book_slug(
            author="Jane Smith",
            title="Post-Truth",
            year=2021,
        )
        self.assertEqual(slug, "smith-post-truth-2021")

    def test_is_same_book_handles_diacritics(self):
        self.assertTrue(
            self.download.is_same_book(
                expected_author="García Márquez",
                expected_title="One Hundred Years of Solitude",
                actual_author="Garcia Marquez",
                actual_title="One Hundred Years of Solitude",
            )
        )

    def test_build_book_slug_retains_year_for_long_titles(self):
        slug = self.download.build_book_slug(
            author="Alex Example",
            title=(
                "Hyperdimensionality Hyperconnectivity Hypercomputationality "
                "Hypermaterialization: Bodies, Senses, and Computational Modernity"
            ),
            year=2024,
        )
        self.assertTrue(slug.endswith("-2024"))

    def test_build_book_slug_strips_em_dash_subtitle(self):
        slug = self.download.build_book_slug(
            author="Jane Smith",
            title="Signal Traffic — Critical Studies of Media Infrastructures",
            year=2019,
        )
        self.assertEqual(slug, "smith-signal-traffic-2019")

    def test_finalize_book_identity_updates_author_field(self):
        final = self.download.finalize_book_identity(
            manifest_book={
                "author": "A. Shew",
                "title": "Against Technoableism",
                "year": 2022,
                "slug": "shew-against-technoableism-2022",
            },
            actual_author="Ashley Shew",
            actual_title="Against Technoableism: Rethinking Who Needs Improvement",
            actual_year=2023,
        )
        self.assertEqual(final["author"], "Ashley Shew")
        self.assertEqual(final["slug"], "shew-against-technoableism-2023")

    def test_verify_book_pdf_uses_first_page_text_not_metadata(self):
        with mock.patch.object(
            self.download,
            "_extract_pdf_text",
            return_value="against technoableism ashley shew copyright 2023",
        ):
            result = self.download.verify_book_file(
                Path("/tmp/book.pdf"),
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
            )
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["author"], "Ashley Shew")

    def test_verify_book_file_returns_needs_review_when_text_is_too_weak(self):
        with mock.patch.object(
            self.download,
            "_extract_pdf_text",
            return_value="table of contents chapter 1 chapter 2",
        ):
            result = self.download.verify_book_file(
                Path("/tmp/book.pdf"),
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
            )
        self.assertEqual(result["status"], "needs_review")

    def test_text_mentions_title_handles_one_word_titles(self):
        self.assertTrue(self.download._text_mentions_title("debt debt debt", "Debt"))

    def test_text_mentions_author_handles_short_surnames(self):
        self.assertTrue(self.download._text_mentions_author("kai li wrote this book", "Kai Li"))

    def test_verify_book_pdf_disables_raw_byte_fallback(self):
        with mock.patch.object(
            self.download,
            "_extract_pdf_text",
            return_value="against technoableism ashley shew 2023",
        ) as extract_pdf_text:
            self.download.verify_book_file(
                Path("/tmp/book.pdf"),
                expected_author="Ashley Shew",
                expected_title="Against Technoableism",
            )

        extract_pdf_text.assert_called_once_with(
            "/tmp/book.pdf",
            max_pages=4,
            allow_raw_fallback=False,
        )

    def test_extract_epub_text_uses_spine_order_instead_of_zip_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "sample.epub"
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("META-INF/container.xml", dedent("""\
                    <?xml version="1.0"?>
                    <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                      <rootfiles>
                        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
                      </rootfiles>
                    </container>
                """))
                zf.writestr("OEBPS/content.opf", dedent("""\
                    <?xml version="1.0" encoding="UTF-8"?>
                    <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                      <manifest>
                        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/>
                        <item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>
                      </manifest>
                      <spine>
                        <itemref idref="title"/>
                        <itemref idref="nav"/>
                      </spine>
                    </package>
                """))
                zf.writestr("OEBPS/nav.xhtml", "<html><body>Navigation only</body></html>")
                zf.writestr("OEBPS/title.xhtml", "<html><body>Against Technoableism Ashley Shew 2023</body></html>")

            text = self.download._extract_epub_text(epub_path)

        self.assertTrue(text.strip().startswith(" against technoableism ashley shew 2023".strip()))
