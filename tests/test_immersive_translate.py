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
        self.assertEqual(settings["translate_model"], "kimi+qwen")
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

            resolved = module.resolve_source_pdf("sample-slug", repo_root=root)

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
                module.resolve_source_pdf("paper-slug", repo_root=root)

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
                repo_root=root,
            )

        self.assertEqual(outputs["output_dir"], root / "processing" / "translations" / "sample-slug")
        self.assertEqual(outputs["dual_pdf"].name, "sample-slug_zh-CN_dual.pdf")
        self.assertEqual(outputs["translation_pdf"].name, "sample-slug_zh-CN_translation.pdf")

    def test_poll_until_complete_allows_non_error_in_progress_statuses(self):
        module = self.load_module()

        class FakeClient:
            def __init__(self):
                self.responses = [
                    {"status": "queued", "overall_progress": 0},
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


if __name__ == "__main__":
    unittest.main()
