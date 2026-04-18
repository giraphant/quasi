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


class ConfigPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.download = load_module(
            "download_module",
            REPO_ROOT / "scripts" / "download" / "download.py",
        )
        cls.search = load_module(
            "search_module",
            REPO_ROOT / "scripts" / "search" / "search.py",
        )

    def test_download_uses_project_local_config_paths(self):
        self.assertEqual(
            self.download.CONFIG_PATH,
            REPO_ROOT / "config" / "anna-archive.json",
        )
        self.assertEqual(
            self.download._EZPROXY_PATH,
            REPO_ROOT / "config" / "ezproxy.json",
        )

    def test_search_uses_project_local_aa_config_path(self):
        self.assertEqual(
            self.search.AA_CONFIG_PATH,
            REPO_ROOT / "config" / "anna-archive.json",
        )
