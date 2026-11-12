"""Regression tests for inputs that used to crash, be silently accepted, or pick the wrong value."""

import _isolation  # noqa: F401  (must precede kkvrm imports)
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kkvrm.__main__ import main
from kkvrm.card import CardError, identify
from kkvrm.config import find_blender, newest, resolve_blender
from kkvrm.meta import build_meta, load_meta_file
from kkvrm.options import validate_options
from kkvrm.outputs import format_stem
from kkvrm.physics import normalize_config, plan_physics
from kkvrm.physics_sources import load_sources
from kkvrm.shaders import shader_map

NOT_NUMBERS = (None, True, False, [], [1], {}, {"a": 1}, "abc", "nan", "inf")


class StrictNumberTests(unittest.TestCase):
    def test_spring_settings_reject_non_numbers_with_value_error(self):
        for key in ("stiffness", "drag_force", "hit_radius", "gravity_power"):
            for value in NOT_NUMBERS:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    normalize_config({"settings": {"hair": {key: value}}})

    def test_gravity_dir_rejects_non_numeric_components(self):
        for value in ([None, 0, -1], [True, 0, 0], ["x", 0, 0], [0, 0, float("nan")], [0, 0], "down"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_config({"settings": {"hair": {"gravity_dir": value}}})

    def test_numeric_strings_remain_accepted(self):
        config = normalize_config({"settings": {"hair": {"stiffness": "0.5", "gravity_dir": ["0", "0", "-2"]}}})
        self.assertEqual(config["settings"]["hair"]["stiffness"], 0.5)
        self.assertEqual(config["settings"]["hair"]["gravity_dir"], [0.0, 0.0, -1.0])

    def test_option_numbers_reject_null_bool_and_containers(self):
        for field in ("bust_lift", "height"):
            for value in (None, True, [], {}, "nan"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_options({field: value})
        for value in (None, True, [0.5], "inf"):
            with self.subTest(alpha_cutoff=value), self.assertRaises(ValueError):
                validate_options({"material_overrides": {"m": {"alpha_cutoff": value}}})

    def test_option_boundaries(self):
        self.assertEqual(validate_options({"bust_lift": 0})["bust_lift"], 0.0)
        self.assertEqual(validate_options({"bust_lift": 0.05})["bust_lift"], 0.05)
        self.assertEqual(validate_options({"height": "1.7"})["height"], 1.7)
        for bad in ({"bust_lift": -0.001}, {"bust_lift": 0.0501}, {"height": 0}, {"height": 10.01},
                    {"outfit": -1}, {"outfit": True}, {"outfit": 1.0}, {"sfw": "yes"}, {"include_mesh": [""]},
                    {"material_overrides": {"m": {"alpha_mode": "blend"}}},
                    {"material_overrides": {"m": {"double_sided": 1}}},
                    {"material_overrides": {"m": {"unknown": 1}}}, {"unknown_option": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_options(bad)


class MetadataTypeTests(unittest.TestCase):
    def test_text_fields_reject_lists_objects_and_booleans(self):
        for field in ("contact", "copyright", "license", "licenseUrl", "version", "name"):
            for value in (["a"], {"a": 1}, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_meta("Model", overrides={field: value})

    def test_numeric_version_is_kept_as_text(self):
        self.assertEqual(build_meta("Model", overrides={"version": 2})["version"], "2")

    def test_metadata_file_errors_are_value_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            for content in (b"[1, 2]", b"{not json", b"\xff\xfe\x00garbage"):
                path = Path(temp) / "meta.json"
                path.write_bytes(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_meta_file(path)

    def test_metadata_file_accepts_a_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "meta.json"
            path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"authors": ["Bom"]}).encode())
            self.assertEqual(load_meta_file(path)["authors"], ["Bom"])


class SidecarTests(unittest.TestCase):
    def test_shader_map_tolerates_bom_and_skips_undecodable_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            document = [{"MaterialInformation": [{"MaterialName": "cf_m_body", "ShaderName": "main_skin"}]}]
            (folder / "KK_MaterialData.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(document).encode())
            (folder / "Broken_MaterialData.json").write_bytes(b"\xff\xfe\xfd")
            self.assertEqual(shader_map(folder), {"cf_m_body": "main_skin"})

    def test_null_and_string_list_fields_do_not_crash_or_substring_match(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            renderers = [{"SMRName": "ct_hair_b", "SMRBoneNames": "xx_ribbon_root_xx", "SMRMaterialNames": None},
                         {"SMRName": "o_hair", "SMRBoneNames": ["ribbon_root"], "SMRMaterialNames": "hair_mat"}]
            dynamics = [{"Root": "ribbon_root", "Exclusions": "ribbon_root", "Colliders": None, "ParticleBones": None}]
            (folder / "KK_SMRData.json").write_text(json.dumps(renderers))
            (folder / "KK_DynamicBoneData.json").write_text(json.dumps(dynamics))
            system = load_sources(folder)["dynamics"][0]
        self.assertEqual(system["renderers"], ["o_hair"])
        self.assertEqual(system["materials"], [])
        self.assertEqual(system["exclusions"], [])
        self.assertEqual(system["colliders"], [])
        self.assertEqual(system["bones"], ["ribbon_root"])
        self.assertEqual(system["category"], "cloth")


class SpringLabelTests(unittest.TestCase):
    def test_spring_names_stay_unique_when_a_generated_suffix_is_taken(self):
        # Old behaviour: X -> cloth_X, X_2 -> cloth_X_2, X again -> cloth_X_ + len(planned) = cloth_X_2 (duplicate).
        bones = [{"name": name, "parent": parent, "aliases": []} for name, parent in (
            ("Root", None), ("a", "Root"), ("a1", "a"), ("b", "Root"), ("b1", "b"), ("c", "Root"), ("c1", "c"))]
        config = {"preset": "balanced", "endpoints": False,
                  "chains": [{"name": "X", "category": "cloth", "bones": ["a", "a1"]},
                             {"name": "X_2", "category": "cloth", "bones": ["b", "b1"]}]}
        sources = {"dynamics": [{"name": "X", "category": "cloth", "enabled": True, "bones": ["c", "c1"]}]}
        result = plan_physics(bones, config, sources)
        names = [item["name"] for item in result["chains"]]
        self.assertEqual(len(names), 3)
        self.assertEqual(len(names), len(set(names)), names)


class BlenderDiscoveryTests(unittest.TestCase):
    def test_newest_compares_version_numbers_numerically(self):
        paths = [Path("Blender 4.9/blender.exe"), Path("Blender 4.10/blender.exe"), Path("Blender 4.2/blender.exe")]
        self.assertEqual(newest(paths), Path("Blender 4.10/blender.exe"))
        self.assertIsNone(newest([]))

    def test_directory_resolution_prefers_the_newest_nested_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for version in ("5.2", "5.10", "5.9"):
                (root / f"blender-{version}").mkdir()
                (root / f"blender-{version}" / "blender.exe").write_text("")
            self.assertEqual(resolve_blender(root).parent.name, "blender-5.10")
            self.assertIsNone(resolve_blender(root / "missing"))

    def test_explicit_missing_path_is_an_error_and_env_is_honoured(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                find_blender(Path(temp) / "nope.exe")
            exe = Path(temp) / "blender.exe"
            exe.write_text("")
            with patch.dict("os.environ", {"KKVRM_BLENDER": str(exe)}):
                self.assertEqual(find_blender(), exe)


class CliInputTests(unittest.TestCase):
    def run_cli(self, *argv):
        with patch("sys.stdout"), patch("sys.stderr"):
            return main(list(argv))

    def test_relative_default_profile_is_stored_as_absolute_path(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "mine.json"
            profile.write_text(json.dumps({"options": {"physics": {"preset": "soft"}}}))
            with patch("kkvrm.config.config_path", return_value=Path(temp) / "config.json"):
                cwd = Path.cwd()
                try:
                    import os
                    os.chdir(temp)
                    self.assertEqual(self.run_cli("config", "--profile", "mine.json"), 0)
                finally:
                    os.chdir(cwd)
                stored = json.loads((Path(temp) / "config.json").read_text())["default_profile"]
            self.assertTrue(Path(stored).is_absolute())
            self.assertEqual(Path(stored).resolve(), profile.resolve())

    def test_bad_inputs_exit_cleanly_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "physics.json"
            bad.write_text(json.dumps({"settings": {"hair": {"stiffness": None}}}))
            with patch("kkvrm.config.config_path", return_value=Path(temp) / "config.json"):
                self.assertEqual(self.run_cli("config", "--physics-config", str(bad)), 1)
                self.assertEqual(self.run_cli("config", "--bust-lift", "nan"), 1)
                self.assertEqual(self.run_cli("check", "--timeout", "0"), 1)
                self.assertEqual(self.run_cli("profile", "show", "../escape"), 1)
                self.assertEqual(self.run_cli("profile", "save", "legacy"), 1)
                self.assertEqual(self.run_cli("convert", temp, "--jobs", "0"), 1)

    def test_malformed_name_template_is_a_friendly_error(self):
        for template in ("{name", "{name}}x{", "{}", "{name!r}", "{name:>10}", "{0}"):
            with self.subTest(template=template), self.assertRaisesRegex(ValueError, "name-template"):
                format_stem(template, name="a", folder="b", version="1")


class CardTests(unittest.TestCase):
    def test_other_games_and_non_bytes_are_rejected(self):
        for blob in (b"HoneySelect2", b"AIS_Chara", b"", b"\x89PNG"):
            with self.subTest(blob=blob), self.assertRaises(CardError):
                identify(blob)
        with self.assertRaises(CardError):
            identify("KoiKatuChara")
        self.assertEqual(identify(b"AIS_Chara KoiKatuChara"), "koikatsu")


if __name__ == "__main__":
    unittest.main()
