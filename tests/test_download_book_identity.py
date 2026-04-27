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
