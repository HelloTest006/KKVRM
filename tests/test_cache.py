import tempfile
import unittest
from pathlib import Path

from kkvrm.cache import location, locked, source_digest


class CacheTests(unittest.TestCase):
    def test_export_settings_and_generated_textures_do_not_invalidate_import(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "model"
            folder.mkdir()
            (folder / "model.pmx").write_bytes(b"mesh")
            first = source_digest(folder)
            (folder / "kkvrm.json").write_text('{"options":{"physics":{"preset":"soft"}}}')
            generated = folder / "kkvrm_baked"
            generated.mkdir()
            (generated / "cloth.png").write_bytes(b"derived texture")
            self.assertEqual(first, source_digest(folder))
            (folder / "model.pmx").write_bytes(b"new mesh")
            self.assertNotEqual(first, source_digest(folder))

    def test_sfw_affects_key_but_physics_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "model"
            folder.mkdir()
            (folder / "model.pmx").write_bytes(b"mesh")
            blender = root / "blender.exe"
            blender.write_bytes(b"Blender")
            _, first = location(folder, blender, {"sfw": False}, root / "cache")
            _, second = location(folder, blender, {"sfw": False, "physics": {"preset": "soft"}}, root / "cache")
            _, third = location(folder, blender, {"sfw": True}, root / "cache")
            self.assertEqual(first, second)
            self.assertNotEqual(first, third)
            with self.assertRaisesRegex(ValueError, "outside"):
                location(folder, blender, {"sfw": False}, folder / "cache")

    def test_cache_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache" / "prepared.blend"
            with locked(path):
                with self.assertRaisesRegex(RuntimeError, "in use"):
                    with locked(path, timeout=0):
                        pass
            with locked(path, timeout=0):
                self.assertTrue(path.parent.is_dir())
