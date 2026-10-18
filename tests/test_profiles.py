import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kkvrm.__main__ import main
from kkvrm.profiles import list_profiles, load_profile, resolve_settings, save_profile


class ProfileTests(unittest.TestCase):
    def test_builtin_cloth_profile_enables_physics_and_colliders(self):
        result = resolve_settings(Path("Model"), profile="cloth-balanced")
        physics = result["options"]["physics"]
        self.assertTrue(physics["types"]["cloth"])
        self.assertTrue(physics["types"]["hair"])
        self.assertEqual(physics["colliders"], "auto")

    def test_file_relative_thumbnail_and_layer_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "20260101_Model"
            folder.mkdir()
            (root / "thumbnail.png").write_bytes(b"PNG")
            profile = root / "profile.json"
            profile.write_text(json.dumps({"meta": {"authors": ["Profile"], "thumbnail": "thumbnail.png"},
                                           "options": {"physics": {"preset": "balanced"}, "height": "keep"}}))
            (folder / "kkvrm.json").write_text(json.dumps({"meta": {"authors": ["Model"]},
                                                          "options": {"physics": {"types": {"hair": False}}}}))
            result = resolve_settings(folder, profile=str(profile), stored={"meta": {"authors": ["Stored"]}},
                                      meta={"authors": ["Flags"]}, overrides={"physics": {"types": {"cloth": False}}})
        self.assertEqual(result["meta"]["authors"], ["Flags"])
        self.assertEqual(result["meta"]["thumbnail"], str(root / "thumbnail.png"))
        self.assertFalse(result["options"]["physics"]["types"]["hair"])
        self.assertFalse(result["options"]["physics"]["types"]["cloth"])
        self.assertEqual(result["options"]["height"], "keep")
        self.assertEqual(result["provenance"]["meta.authors"], "command flags")

    def test_save_and_load_profile_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("kkvrm.profiles.profiles_dir", return_value=Path(temp)):
                save_profile("my-profile", {"options": {"height": "keep"}})
                self.assertEqual(load_profile("my-profile")["options"]["height"], "keep")
                self.assertTrue(any(item["name"] == "my-profile" for item in list_profiles()))
                with self.assertRaises(ValueError):
                    save_profile("my-profile", {})
                with self.assertRaises(ValueError):
                    save_profile("../bad", {})
                with self.assertRaises(ValueError):
                    save_profile("typo", {"options": {"hair_phyics": True}})

    def test_cli_profile_save_honors_physics_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("kkvrm.profiles.profiles_dir", return_value=Path(temp)), patch("sys.stdout"):
                self.assertEqual(main(["profile", "save", "custom", "--physics-preset", "balanced",
                                       "--cloth-physics", "on", "--author", "Author"]), 0)
                profile = load_profile("custom")
        self.assertEqual(profile["meta"]["authors"], ["Author"])
        self.assertEqual(profile["options"]["physics"]["types"]["cloth"], "on")
