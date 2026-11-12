"""End-to-end host pipeline tests: the real runner drives a fake Blender subprocess."""

import _isolation  # noqa: F401  (must precede kkvrm imports)
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from kkvrm.__main__ import main
from kkvrm.inspection import inspect_export
from kkvrm.runner import RESULT_PREFIX, convert, invoke, reexport
from _fixtures import HUMANOID_BONES, glb, pmx_bytes, vrm_bytes, vrm_document

FAKE_BLENDER = textwrap.dedent(f'''
    import json, os, sys
    from pathlib import Path
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = os.environ.get("KKVRM_FAKE_MODE", "ok")
    Path(os.environ["KKVRM_FAKE_PAYLOAD"]).write_text(json.dumps(payload), encoding="utf-8")
    print("Blender 5.2 (fake)")
    print('KKVRM_PROGRESS {{"stage": "Importing KKBP character", "elapsed_seconds": 1.5}}', flush=True)
    print("KKVRM_PROGRESS not-json", flush=True)
    if mode == "crash":
        print("Segmentation fault", flush=True)
        sys.exit(3)
    if mode == "error":
        print({RESULT_PREFIX!r} + json.dumps({{"ok": False, "error": "KKBP import failed: CANCELLED"}}), flush=True)
        sys.exit(1)
    if payload.get("action") == "check":
        print({RESULT_PREFIX!r} + json.dumps({{"ok": False, "issues": ["missing extension: kkbp"]}}), flush=True)
        sys.exit(1)
    output = Path(payload["output"])
    output.write_bytes(Path(os.environ["KKVRM_FAKE_VRM"]).read_bytes())
    if payload.get("keep_blend"):
        output.with_suffix(".blend").write_bytes(b"BLENDER-v400")
        output.with_suffix(".blend.json").write_text("{{}}")
    print({RESULT_PREFIX!r} + json.dumps({{"ok": True, "output": str(output), "springs": 0}}), flush=True)
''')


class FakeBlender:
    """Context manager that routes runner subprocesses to FAKE_BLENDER."""

    def __init__(self, root, mode="ok", vrm=None):
        self.root, self.mode, self.vrm = Path(root), mode, vrm if vrm is not None else vrm_bytes()

    def __enter__(self):
        script = self.root / "fake_blender.py"
        script.write_text(FAKE_BLENDER, encoding="utf-8")
        source = self.root / "source.vrm"
        source.write_bytes(self.vrm)
        self.executable = self.root / "blender.exe"
        self.executable.write_bytes(b"")
        self.payload_path = self.root / "payload.json"
        self.patches = [
            patch.dict(os.environ, {"KKVRM_FAKE_MODE": self.mode, "KKVRM_FAKE_VRM": str(source),
                                    "KKVRM_FAKE_PAYLOAD": str(self.payload_path)}),
            patch("kkvrm.runner.find_blender", return_value=self.executable),
            patch("kkvrm.runner.blender_command",
                  side_effect=lambda blender, args: [sys.executable, "-I", str(script), str(args)]),
        ]
        for item in self.patches:
            item.start()
        return self

    def payload(self):
        return json.loads(self.payload_path.read_text(encoding="utf-8"))

    def __exit__(self, *exc):
        for item in reversed(self.patches):
            item.stop()


def make_export(root, name="20260101_Mika", bones=None, sidecars=None):
    folder = Path(root) / name
    folder.mkdir(parents=True)
    (folder / "model.pmx").write_bytes(pmx_bytes(bones or HUMANOID_BONES, morphs=["eye smiling"]))
    (folder / "card.png").write_bytes(b"\x89PNG KoiKatuCharaSun")
    for filename, content in (sidecars or {}).items():
        (folder / filename).write_text(json.dumps(content), encoding="utf-8")
    return folder


class RunnerPipelineTests(unittest.TestCase):
    def test_successful_export_publishes_validated_output_report_log_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            target = Path(temp) / "out" / "Mika.vrm"
            target.parent.mkdir()
            target.write_bytes(b"previous")
            stderr = io.StringIO()
            with FakeBlender(temp) as fake, redirect_stderr(stderr):
                result = convert(folder, target)
                payload = fake.payload()
            self.assertTrue(result["ok"])
            self.assertEqual(target.read_bytes(), vrm_bytes())
            self.assertEqual(target.with_name("Mika.vrm.bak").read_bytes(), b"previous")
            report = json.loads(target.with_suffix(".report.json").read_text())
            self.assertTrue(report["ok"])
            self.assertTrue(report["validation"]["ok"])
            self.assertIn("Blender 5.2 (fake)", target.with_suffix(".log").read_text())
            self.assertIn("[Mika] Importing KKBP character (1.5s)", stderr.getvalue())
            self.assertNotIn("not-json", stderr.getvalue())
            # Blender writes to a staging file; the final path is only passed for reference.
            self.assertNotEqual(Path(payload["output"]), target)
            self.assertEqual(Path(payload["final_output"]), target.resolve())
            self.assertEqual(sorted(path.name for path in target.parent.iterdir()),
                             ["Mika.log", "Mika.report.json", "Mika.vrm", "Mika.vrm.bak"])

    def test_keep_blend_publishes_snapshot_and_companion(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            target = Path(temp) / "Mika.vrm"
            with FakeBlender(temp), redirect_stderr(io.StringIO()):
                convert(folder, target, options={"keep_blend": True})
            self.assertEqual(target.with_suffix(".blend").read_bytes(), b"BLENDER-v400")
            self.assertTrue(target.with_suffix(".blend.json").is_file())

    def test_invalid_vrm_is_never_published(self):
        broken = vrm_document()
        del broken["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]["head"]
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            target = Path(temp) / "Mika.vrm"
            target.write_bytes(b"previous")
            with FakeBlender(temp, vrm=glb(broken)), redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "missing humanoid bone: head"):
                    convert(folder, target)
            self.assertEqual(target.read_bytes(), b"previous")
            self.assertFalse(target.with_name("Mika.vrm.bak").exists())
            self.assertFalse(json.loads(target.with_suffix(".report.json").read_text())["ok"])
            self.assertFalse(any(path.name.startswith(".kkvrm-export-") for path in Path(temp).iterdir()))

    def test_blender_errors_and_crashes_surface_message_and_log(self):
        for mode, expected in (("error", "KKBP import failed: CANCELLED"), ("crash", "blender exit 3")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                folder = make_export(temp)
                target = Path(temp) / "Mika.vrm"
                with FakeBlender(temp, mode=mode), redirect_stderr(io.StringIO()):
                    with self.assertRaises(RuntimeError) as caught:
                        convert(folder, target, quiet=True)
                self.assertIn(expected, str(caught.exception))
                self.assertIn(str(target.resolve().with_suffix(".log")), str(caught.exception))
                self.assertFalse(target.exists())

    def test_cache_payload_and_cache_dir_inside_export_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            target = Path(temp) / "Mika.vrm"
            with FakeBlender(temp) as fake, redirect_stderr(io.StringIO()):
                convert(folder, target, options={"cache": True}, cache_root=Path(temp) / "cache")
                payload = fake.payload()
                self.assertTrue(Path(payload["cache_path"]).parent.is_dir())
                self.assertEqual(len(payload["cache_key"]), 64)
                with self.assertRaisesRegex(ValueError, "outside the source export"):
                    convert(folder, target, options={"cache": True}, cache_root=folder / "cache")
            report = json.loads(target.with_suffix(".report.json").read_text())
            self.assertFalse(report["ok"])
            self.assertIn("outside the source export", report["error"])

    def test_check_returns_the_diagnostic_result_even_when_blender_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            with FakeBlender(temp):
                result = invoke({"action": "check"}, quiet=True)
        self.assertEqual(result["issues"], ["missing extension: kkbp"])


class ReexportTests(unittest.TestCase):
    def prepared(self, temp, sfw=False):
        blend = Path(temp) / "Mika.blend"
        blend.write_bytes(b"BLENDER")
        stat = blend.stat()
        project = {"import_dir": str(Path(temp) / "missing-export"), "blend_size": stat.st_size,
                   "blend_mtime_ns": stat.st_mtime_ns,
                   "settings": {"schema_version": 1, "meta": {"name": "Mika", "authors": ["A"]},
                                "options": {"sfw": sfw, "physics": {"preset": "soft"}}}}
        blend.with_suffix(".blend.json").write_text(json.dumps(project))
        return blend

    def test_dry_run_uses_companion_settings_without_launching_blender(self):
        with tempfile.TemporaryDirectory() as temp:
            blend = self.prepared(temp)
            with patch("kkvrm.runner.invoke", side_effect=AssertionError("Blender launched")), \
                    patch("kkvrm.runner.find_blender", side_effect=FileNotFoundError("none")), \
                    redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(main(["reexport", str(blend), "--dry-run", "--hair-physics", "off"]), 0)
                result = reexport(blend, Path(temp) / "x.vrm", dry_run=True)
            payload = result["plan"]["payload"]
            self.assertEqual(payload["action"], "reexport")
            self.assertEqual(payload["options"]["physics"]["preset"], "soft")
            self.assertEqual(payload["meta"]["name"], "Mika")
            self.assertFalse((Path(temp) / "x.vrm").exists())

    def test_stale_companion_and_sfw_change_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            blend = self.prepared(temp)
            with redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "SFW is an import-time option"):
                    reexport(blend, Path(temp) / "x.vrm", options={"sfw": True}, dry_run=True)
                blend.write_bytes(b"BLENDER changed after the companion was written")
                with self.assertRaisesRegex(ValueError, "needs the prepared .blend.json"):
                    reexport(blend, Path(temp) / "x.vrm", dry_run=True)


class InspectionTests(unittest.TestCase):
    def test_lightweight_inspection_maps_humanoid_and_plans_source_physics(self):
        bones = HUMANOID_BONES + [("cf_j_hair_01", "cf_j_head"), ("cf_j_hair_02", "cf_j_hair_01"),
                                  ("ribbon_A", "cf_j_spine02"), ("ribbon_B", "ribbon_A")]
        dynamics = [{"Root": "ribbon_A", "ParticleBones": ["ribbon_A", "ribbon_B"], "Weight": 1}]
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp, bones=bones, sidecars={"KK_DynamicBoneData.json": dynamics})
            outfit = folder / "Outfit 01"
            outfit.mkdir()
            (outfit / "model.pmx").write_bytes(b"PMX broken")
            report = inspect_export(folder, physics=True, options={"physics": {"preset": "balanced"}, "outfit": 0})
        self.assertEqual(report["humanoid"]["missing_required"], [])
        self.assertEqual(report["humanoid"]["mapped"]["head"], "cf_j_head")
        self.assertNotIn("pmx_errors", report)  # Outfit 01 is filtered out before parsing
        chains = {chain["category"]: chain for chain in report["physics"]["chains"]}
        self.assertEqual(chains["cloth"]["bones"][:2], ["ribbon_A", "ribbon_B"])
        self.assertEqual(chains["cloth"]["source"], "KK_DynamicBoneData")
        self.assertEqual(chains["hair"]["center"], "cf_j_head")
        self.assertEqual(report["physics_sources"]["systems"]["cloth"], 1)
        self.assertNotIn("data", chains["cloth"])
        self.assertEqual(report["morphs"], ["eye smiling"])

    def test_unparseable_pmx_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            (folder / "model.pmx").write_bytes(b"PMX \x00\x00")
            report = inspect_export(folder)
        self.assertIn("model.pmx", report["pmx_errors"][0])
        self.assertIn("hips", report["humanoid"]["missing_required"])


class CliPipelineTests(unittest.TestCase):
    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(item) for item in argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_convert_end_to_end_through_the_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            make_export(temp, "20260101_Mika")
            make_export(temp, "20260102_Ada")
            out = Path(temp) / "vrms"
            with FakeBlender(temp):
                code, stdout, stderr = self.run_cli("convert", temp, "-o", out, "--jobs", "2",
                                                    "--name-template", "{name}_v{version}",
                                                    "--batch-report", out / "batch.json", "--quiet")
            self.assertEqual(code, 0, stderr)
            self.assertEqual(sorted(path.name for path in out.glob("*.vrm")), ["Ada_v1.0.0.vrm", "Mika_v1.0.0.vrm"])
            batch = json.loads((out / "batch.json").read_text())
            self.assertEqual((batch["ok"], batch["converted"], batch["failed"]), (True, 2, 0))
            self.assertIn("2 converted, 0 failed", stderr)

    def test_dry_run_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = make_export(temp)
            target = Path(temp) / "new" / "Mika.vrm"
            with patch("kkvrm.runner.find_blender", side_effect=FileNotFoundError("no Blender")):
                code, _stdout, stderr = self.run_cli("convert", folder, "-o", target, "--dry-run",
                                                     "--profile", "cloth-balanced")
            self.assertEqual(code, 0, stderr)
            self.assertFalse(target.parent.exists())
            plan = json.loads(stderr[:stderr.rindex("}") + 1])
            self.assertEqual(plan["provenance"]["options.physics.preset"], "profile:cloth-balanced")
            self.assertEqual(plan["warnings"], ["no Blender"])

    def test_inspect_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            good, bad = Path(temp) / "good.vrm", Path(temp) / "bad.vrm"
            good.write_bytes(vrm_bytes())
            bad.write_bytes(b"not a glb")
            self.assertEqual(self.run_cli("inspect", good)[0], 0)
            self.assertEqual(self.run_cli("inspect", bad)[0], 1)
            folder = make_export(temp)
            code, stdout, _stderr = self.run_cli("inspect", folder, "--physics")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout)["game"], "sunshine")

    def test_profile_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.run_cli("profile", "save", "mine", "--profile", "hair-soft", "--author", "Me")[0], 0)
            self.assertEqual(self.run_cli("profile", "save", "mine")[0], 1)  # exists without --force
            code, stdout, _ = self.run_cli("profile", "show", "mine")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout)["options"]["physics"]["preset"], "soft")
            names = [item["name"] for item in json.loads(self.run_cli("profile", "list")[1])]
            self.assertIn("mine", names)
            del temp


if __name__ == "__main__":
    unittest.main()
