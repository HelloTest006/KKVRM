import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kkvrm.bones import REQUIRED
from kkvrm.runner import RESULT_PREFIX, _run, convert, plan


def vrm_bytes():
    slots = sorted(REQUIRED)
    human = {}
    for index, slot in enumerate(slots):
        parts = slot.split("_")
        human[parts[0] + "".join(part.title() for part in parts[1:])] = {"node": index}
    document = {"asset": {"version": "2.0"}, "nodes": [{"name": slot} for slot in slots],
                "extensions": {"VRMC_vrm": {"specVersion": "1.0", "humanoid": {"humanBones": human}}}}
    chunk = json.dumps(document).encode()
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sII", b"glTF", 2, len(chunk) + 20) + struct.pack("<I4s", len(chunk), b"JSON") + chunk


class RunnerTests(unittest.TestCase):
    def test_dry_run_does_not_touch_existing_output_or_create_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder / "old.vrm"
            target.write_bytes(b"old")
            backup = folder / "old.vrm.bak"
            backup.write_bytes(b"older")
            before = set(folder.iterdir())
            with patch("kkvrm.runner.find_blender", return_value=folder / "blender.exe"), patch("sys.stderr"):
                result = convert(folder, target, dry_run=True)
                convert(folder, folder / "missing" / "new.vrm", dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(backup.read_bytes(), b"older")
            self.assertEqual(set(folder.iterdir()), before)

    def test_plan_does_not_require_blender_to_be_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("kkvrm.runner.find_blender", side_effect=FileNotFoundError("missing Blender")):
                job = plan(temp, Path(temp) / "out.vrm")
            self.assertIsNone(job["blender"])
            self.assertEqual(job["warnings"], ["missing Blender"])

    def test_crash_keeps_previous_export_and_reports_exit_code(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder / "out.vrm"
            target.write_bytes(b"previous")
            with patch("kkvrm.runner.find_blender", return_value=folder / "blender.exe"):
                with patch("kkvrm.runner._run", return_value=("native crash", -1)):
                    with self.assertRaisesRegex(RuntimeError, "blender exit -1"):
                        convert(folder, target)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertFalse(target.with_name("out.vrm.bak").exists())
            self.assertFalse(json.loads(target.with_suffix(".report.json").read_text())["ok"])

    def test_only_valid_complete_export_replaces_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder / "out.vrm"
            target.write_bytes(b"previous")

            def fake_run(command, *args, **kwargs):
                payload = json.loads(Path(command[-1]).read_text())
                Path(payload["output"]).write_bytes(vrm_bytes())
                return RESULT_PREFIX + json.dumps({"ok": True, "output": payload["output"]}), 0

            with patch("kkvrm.runner.find_blender", return_value=folder / "blender.exe"):
                with patch("kkvrm.runner._run", side_effect=fake_run), patch("sys.stderr"):
                    result = convert(folder, target)
            self.assertEqual(target.with_name("out.vrm.bak").read_bytes(), b"previous")
            self.assertEqual(target.read_bytes(), vrm_bytes())
            self.assertEqual(result["output"], str(target.resolve()))

    def test_timeout_preserves_partial_log(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "partial.log"
            command = [sys.executable, "-u", "-c", "import time; print('before timeout', flush=True); time.sleep(30)"]
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                _run(command, timeout=1, log_path=log)
            self.assertIn("before timeout", log.read_text())

    def test_malformed_result_line_is_a_clean_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with patch("kkvrm.runner.find_blender", return_value=folder / "blender.exe"):
                with patch("kkvrm.runner._run", return_value=(RESULT_PREFIX + "invalid json", 0)):
                    with self.assertRaisesRegex(RuntimeError, "no successful result"):
                        convert(folder, folder / "out.vrm", quiet=True)
