import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kkvrm.__main__ import main
from kkvrm.config import load, save


class ConfigTests(unittest.TestCase):
    def test_removing_metadata_keeps_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            with patch("kkvrm.config.config_path", return_value=path):
                save({"blender": "old path", "meta": {"authors": ["Stored"]}})
                save({"meta": None})
                self.assertEqual(load(), {"blender": "old path"})

    def test_cli_clear_and_sexual_permission_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            with patch("kkvrm.config.config_path", return_value=path), patch("sys.stdout"):
                self.assertEqual(main(["config", "--author", "Stored", "--sexual-ok"]), 0)
                self.assertTrue(json.loads(path.read_text())["meta"]["allow_sexual"])
                self.assertEqual(main(["config", "--clear-meta"]), 0)
                self.assertNotIn("meta", json.loads(path.read_text()))
