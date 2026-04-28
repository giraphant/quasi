import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "translate" / "immersive_translate.py"


def load_module(name: str, path: Path):
    if not path.exists():
        raise AssertionError(f"Expected script to exist at {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImmersiveTranslateTests(unittest.TestCase):
    def load_module(self):
        try:
            return load_module("immersive_translate_module", SCRIPT_PATH)
        except AssertionError as exc:
            self.fail(str(exc))

    def test_uses_project_local_config_path(self):
        module = self.load_module()
        self.assertEqual(
            module.CONFIG_PATH,
            REPO_ROOT / "config" / "immersive-translate.json",
        )

    def test_load_settings_applies_plugin_defaults(self):
        module = self.load_module()
        settings = module.load_settings({"auth_key": "secret"})

        self.assertEqual(settings["auth_key"], "secret")
        self.assertEqual(settings["target_language"], "zh-CN")
        self.assertEqual(settings["translate_model"], "gemini-1")
        self.assertEqual(settings["layout_model"], "version_3")
        self.assertEqual(settings["dual_mode"], "lort")
        self.assertTrue(settings["rich_text_translate"])
        self.assertFalse(settings["enhance_compatibility"])

    def test_resolve_source_pdf_prefers_sources_directory(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = root / "sources"
            sources.mkdir()
            exact = sources / "sample-slug.pdf"
            exact.write_bytes(b"%PDF-1.7")

            resolved = module.resolve_source_pdf("sample-slug", project_root=root)

        self.assertEqual(resolved, exact)

    def test_resolve_source_pdf_raises_for_ambiguous_matches(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources").mkdir()
            processing = root / "processing"
            (processing / "incoming").mkdir(parents=True)
            (processing / "archive").mkdir(parents=True)
            first = processing / "incoming" / "paper-slug.pdf"
            second = processing / "archive" / "paper-slug.pdf"
            first.write_bytes(b"%PDF-1.7")
            second.write_bytes(b"%PDF-1.7")

            with self.assertRaises(module.AmbiguousSourceError) as ctx:
                module.resolve_source_pdf("paper-slug", project_root=root)

        self.assertEqual(
            sorted(ctx.exception.candidates),
            sorted([first.resolve(), second.resolve()]),
        )

    def test_build_output_paths_write_into_processing_translations(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            outputs = module.build_output_paths(
                slug="sample-slug",
                target_language="zh-CN",
                project_root=root,
            )

        self.assertEqual(outputs["output_dir"], root / "processing" / "translations")
        self.assertEqual(outputs["final_pdf"], root / "processing" / "translations" / "sample-slug-zh.pdf")
        self.assertEqual(outputs["dual_tmp"].name, ".sample-slug-zh.dual.tmp.pdf")
        self.assertEqual(outputs["dual_tmp"].parent, outputs["output_dir"])

    def test_poll_until_complete_allows_non_error_in_progress_statuses(self):
        module = self.load_module()

        class FakeClient:
            def __init__(self):
                self.responses = [
                    {"status": "", "overall_progress": 50},
                    {"status": "ok", "overall_progress": 100},
                ]

            def get_translate_status(self, pdf_id):
                return self.responses.pop(0)

        with mock.patch.object(module.time, "sleep"):
            result = module.poll_until_complete(
                FakeClient(),
                "pdf-123",
                interval_seconds=0,
                max_polls=2,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["overall_progress"], 100)

    def test_poll_until_complete_treats_unknown_status_as_failure(self):
        module = self.load_module()

        class FakeClient:
            def get_translate_status(self, pdf_id):
                return {"status": "quota_exceeded", "overall_progress": 0, "message": "quota exceeded"}

        with mock.patch.object(module.time, "sleep"):
            with self.assertRaises(module.TranslationError) as ctx:
                module.poll_until_complete(
                    FakeClient(),
                    "pdf-123",
                    interval_seconds=0,
                    max_polls=2,
                )

        self.assertIn("quota exceeded", str(ctx.exception))

    def test_upload_pdf_wraps_requests_errors(self):
        module = self.load_module()
        client = module.ImmersiveTranslateClient(module.load_settings({"auth_key": "secret"}))

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.7")

            with mock.patch.object(
                client.session,
                "put",
                side_effect=module.requests.RequestException("boom"),
            ):
                with self.assertRaises(module.TranslationError):
                    client.upload_pdf("https://example.com/upload", pdf_path)


    def test_split_dual_pdf_doubles_page_count(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_path = root / "dual.pdf"
            dst_path = root / "split.pdf"

            # Build a minimal 2-page dual PDF via pymupdf
            import pymupdf
            doc = pymupdf.open()
            for _ in range(2):
                page = doc.new_page(width=800, height=600)
                page.insert_text(pymupdf.Point(50, 50), "left side")
                page.insert_text(pymupdf.Point(450, 50), "right side")
            doc.save(str(src_path))
            doc.close()

            result = module.split_dual_pdf(src_path, dst_path)

            self.assertEqual(result, dst_path)
            self.assertTrue(dst_path.exists())

            out = pymupdf.open(str(dst_path))
            self.assertEqual(len(out), 4)
            self.assertAlmostEqual(out[0].rect.width, 400, delta=1)
            self.assertAlmostEqual(out[1].rect.width, 400, delta=1)
            out.close()

    def test_add_toc_to_split_pdf_maps_source_outline_to_original_pages(self):
        module = self.load_module()
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.pdf"
            split_path = root / "split.pdf"

            source = pymupdf.open()
            for _ in range(3):
                source.new_page(width=400, height=600)
            source.set_toc([
                [1, "Chapter 1", 1],
                [2, "Section 1.1", 2],
                [1, "Chapter 2", 3],
            ])
            source.save(str(source_path))
            source.close()

            split = pymupdf.open()
            for _ in range(6):
                split.new_page(width=400, height=600)
            split.save(str(split_path))
            split.close()

            count = module.add_toc_to_split_pdf(source_pdf=source_path, split_pdf=split_path)

            self.assertEqual(count, 3)
            out = pymupdf.open(str(split_path))
            self.assertEqual(
                out.get_toc(simple=True),
                [
                    [1, "Chapter 1", 1],
                    [2, "Section 1.1", 3],
                    [1, "Chapter 2", 5],
                ],
            )
            out.close()

    def test_add_toc_to_split_pdf_accepts_tocify_style_json(self):
        module = self.load_module()
        import json
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.pdf"
            split_path = root / "split.pdf"
            toc_path = root / "toc.json"

            source = pymupdf.open()
            source.new_page(width=400, height=600)
            source.save(str(source_path))
            source.close()

            split = pymupdf.open()
            for _ in range(4):
                split.new_page(width=400, height=600)
            split.save(str(split_path))
            split.close()

            toc_path.write_text(
                json.dumps([
                    {"title": "Intro", "level": 1, "page": 1},
                    {"title": "Methods", "level": 1, "page": 2},
                ]),
                encoding="utf-8",
            )

            count = module.add_toc_to_split_pdf(
                source_pdf=source_path,
                split_pdf=split_path,
                toc_json=toc_path,
                page_side="translated",
            )

            self.assertEqual(count, 2)
            out = pymupdf.open(str(split_path))
            self.assertEqual(
                out.get_toc(simple=True),
                [
                    [1, "Intro", 2],
                    [1, "Methods", 4],
                ],
            )
            out.close()

    def test_add_toc_to_split_pdf_uses_fallback_manifest_when_source_has_no_outline(self):
        module = self.load_module()
        import json
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.pdf"
            split_path = root / "split.pdf"
            manifest_path = root / "manifest.json"

            source = pymupdf.open()
            source.new_page(width=400, height=600)
            source.new_page(width=400, height=600)
            source.save(str(source_path))
            source.close()

            split = pymupdf.open()
            for _ in range(4):
                split.new_page(width=400, height=600)
            split.save(str(split_path))
            split.close()

            manifest_path.write_text(
                json.dumps({
                    "chapters": [
                        {"title": "Frontmatter", "start_page": 1},
                        {"title": "Chapter 1", "start_page": 2},
                    ],
                }),
                encoding="utf-8",
            )

            count = module.add_toc_to_split_pdf(
                source_pdf=source_path,
                split_pdf=split_path,
                fallback_toc_json=manifest_path,
            )

            self.assertEqual(count, 2)
            out = pymupdf.open(str(split_path))
            self.assertEqual(
                out.get_toc(simple=True),
                [
                    [1, "Frontmatter", 1],
                    [1, "Chapter 1", 3],
                ],
            )
            out.close()


if __name__ == "__main__":
    unittest.main()
