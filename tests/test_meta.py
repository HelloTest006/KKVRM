import json
import tempfile
import unittest
from pathlib import Path

from kkvrm.meta import build_meta
from kkvrm.runner import convert, resolve_meta


class MetaTests(unittest.TestCase):
    def test_defaults_match_previous_license(self):
        info = build_meta("Mika")
        self.assertEqual(info["name"], "Mika")
        self.assertEqual(info["version"], "1.0.0")
        self.assertEqual(info["authors"], ["KKVRM"])
        self.assertEqual(info["avatar_permission"], "onlyAuthor")
        self.assertFalse(info["allow_sexual"])
        self.assertFalse(info["allow_violent"])
        self.assertEqual(info["commercial_usage"], "personalNonProfit")
        self.assertEqual(info["credit"], "required")
        self.assertFalse(info["allow_redistribution"])
        self.assertEqual(info["modification"], "prohibited")
        self.assertEqual(info["license"], "")
        self.assertEqual(info["license_url"], "")

    def test_file_then_cli_then_sexual_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            thumb = Path(temp) / "thumb.png"
            thumb.write_bytes(b"png")
            meta = Path(temp) / "meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "authors": ["Mika"],
                        "license": "personal use only",
                        "licenseUrl": "https://example.com/license",
                        "allowSexual": False,
                        "thumbnail": "thumb.png",
                        "avatarPermission": "everyone",
                        "modification": "allowModification",
                    }
                ),
                encoding="utf-8",
            )
            info = build_meta(
                "FromFolder",
                overrides={"copyright": "2026 Mika", "authors": ["Ada"]},
                meta_file=meta,
                sexual_ok=True,
            )
        self.assertEqual(info["authors"], ["Ada"])
        self.assertEqual(info["copyright"], "2026 Mika")
        self.assertEqual(info["license"], "personal use only")
        self.assertEqual(info["license_url"], "https://example.com/license")
        self.assertTrue(info["allow_sexual"])
        self.assertEqual(info["avatar_permission"], "everyone")
        self.assertEqual(info["modification"], "allowModification")
        self.assertTrue(info["thumbnail"].endswith("thumb.png"))

    def test_bad_field_and_enum(self):
        with self.assertRaises(ValueError):
            build_meta("Mika", overrides={"nope": 1})
        with self.assertRaises(ValueError):
            build_meta("Mika", overrides={"modification": "yes"})

    def test_config_layer_sits_between_defaults_and_file(self):
        with tempfile.TemporaryDirectory() as temp:
            meta = Path(temp) / "meta.json"
            meta.write_text(
                json.dumps({"authors": ["FromFile"], "license": "file license"}),
                encoding="utf-8",
            )
            config = {"authors": ["FromConfig"], "copyright": "config copyright", "contact": "keep me"}
            info = build_meta("Mika", overrides={"license": "flag wins"}, meta_file=meta, config_meta=config)
        self.assertEqual(info["authors"], ["FromFile"])
        self.assertEqual(info["license"], "flag wins")
        self.assertEqual(info["copyright"], "config copyright")
        self.assertEqual(info["contact"], "keep me")

    def test_config_layer_used_without_file(self):
        info = build_meta("Mika", config_meta={"authors": ["Stored"], "modification": "allowModification"})
        self.assertEqual(info["authors"], ["Stored"])
        self.assertEqual(info["modification"], "allowModification")
        self.assertEqual(info["commercial_usage"], "personalNonProfit")

    def test_sexual_flag_forces_on_over_every_layer(self):
        info = build_meta("Mika", config_meta={"allow_sexual": False}, sexual_ok=True)
        self.assertTrue(info["allow_sexual"])

    def test_resolve_meta_uses_folder_name(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "20260905_VKSomi"
            folder.mkdir()
            info = resolve_meta(folder)
        self.assertEqual(info["name"], "VKSomi")

    def test_bust_lift_rejected_before_blender(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "export"
            folder.mkdir()
            with self.assertRaises(ValueError):
                convert(folder, Path(temp) / "out.vrm", bust_lift=1)
