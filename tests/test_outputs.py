import tempfile
import unittest
from pathlib import Path

from kkvrm.outputs import backup_existing, backup_path, prepare_output, safe_stem


class SafeStemTests(unittest.TestCase):
    def test_strips_path_and_illegal_characters(self):
        self.assertEqual(safe_stem("VKSomi"), "VKSomi")
        self.assertEqual(safe_stem("a/b\\c:d*e?f\"g<h>i|j"), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(safe_stem("  spaced  "), "spaced")

    def test_falls_back_when_empty(self):
        self.assertEqual(safe_stem("   "), "model")
        self.assertEqual(safe_stem(""), "model")
        self.assertEqual(safe_stem(None), "model")
        self.assertEqual(safe_stem("///", fallback="folder"), "folder")

    def test_windows_reserved_names(self):
        self.assertEqual(safe_stem("CON"), "CON_")
        self.assertEqual(safe_stem("nul"), "nul_")
        self.assertEqual(safe_stem("com1"), "com1_")
        self.assertEqual(safe_stem("console"), "console")

    def test_truncates_long_names(self):
        self.assertLessEqual(len(safe_stem("x" * 200)), 60)


class BackupTests(unittest.TestCase):
    def test_returns_none_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "out.vrm"
            self.assertIsNone(backup_existing(target))
            self.assertEqual(backup_path(target), Path(temp) / "out.vrm.bak")

    def test_moves_existing_file_to_bak(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "out.vrm"
            target.write_text("new")
            backup = backup_existing(target)
            self.assertEqual(backup.read_text(), "new")
            self.assertFalse(target.exists())
            self.assertEqual(backup, backup_path(target))

    def test_stale_backup_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "out.vrm"
            stale = Path(temp) / "out.vrm.bak"
            stale.write_text("ancient")
            target.write_text("current")
            backup = backup_existing(target)
            self.assertEqual(backup.read_text(), "current")
            self.assertFalse((Path(temp) / "out.vrm.bak.bak").exists())

    def test_prepare_output_creates_the_parent_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "nested" / "deeper" / "out.vrm"
            self.assertIsNone(prepare_output(target))
            self.assertTrue(target.parent.is_dir())
            target.write_text("v1")
            self.assertEqual(backup_existing(target).read_text(), "v1")


if __name__ == "__main__":
    unittest.main()
