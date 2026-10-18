import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kkvrm.__main__ import main


def make_export(root, name, with_card=True):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "model.pmx").write_bytes(b"PMX ")
    if with_card:
        (folder / "card.png").write_bytes(b"PNG KoiKatuCharaSun")
    return folder


class CliTests(unittest.TestCase):
    def test_list_reports_each_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, "20260101_Mika")
            make_export(root, "20260102_Ada")
            out = []
            with mock.patch("sys.stdout") as stdout:
                stdout.write.side_effect = out.append
                code = main(["list", str(root)])
            self.assertEqual(code, 0)
            report = json.loads("".join(out))
            self.assertEqual([item["name"] for item in report], ["Mika", "Ada"])
            self.assertTrue(all(item["has_pmx"] for item in report))
            self.assertEqual(report[0]["game"], "sunshine")

    def test_dry_run_names_output_from_the_export_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, "20260905_VKSomi")
            card = root / "20260905_VKSomi" / "card.png"
            calls = []
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.resolve_input", return_value=(root / "20260905_VKSomi", card, "sunshine")):
                    with mock.patch("kkvrm.__main__.convert", side_effect=lambda *a, **k: calls.append((a, k)) or {"output": "x"}):
                        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                            code = main(["convert", str(root / "20260905_VKSomi" / "card.png"), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            _positional, keyword = calls[0]
            self.assertIsNone(keyword["bust_lift"])
            self.assertTrue(keyword["dry_run"])
            self.assertEqual(Path(calls[0][0][1]).name, "VKSomi.vrm")

    def test_cli_defers_output_replacement_to_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = make_export(root, "20260905_VKSomi")
            card = folder / "card.png"
            target = root / "VKSomi.vrm"
            target.write_text("old")
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.resolve_input", return_value=(folder, card, "sunshine")):
                    with mock.patch("kkvrm.__main__.convert", side_effect=lambda *a, **k: {"output": str(a[1])}):
                        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                            main(["convert", str(folder), "-o", str(target)])
            self.assertFalse((root / "VKSomi.vrm.bak").exists())
            self.assertEqual(target.read_text(), "old")
            target.write_text("newer")
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.resolve_input", return_value=(folder, card, "sunshine")):
                    with mock.patch("kkvrm.__main__.convert", side_effect=lambda *a, **k: {"output": str(a[1])}):
                        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                            main(["convert", str(folder), "-o", str(target), "--force"])
            self.assertFalse((root / "VKSomi.vrm.bak.bak").exists())

    def test_batch_keeps_going_after_a_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, "20260101_Mika")
            make_export(root, "20260102_Ada")
            out_dir = Path(temp) / "out"
            seen = []

            def fake_convert(folder, output, **keyword):
                seen.append(Path(folder).name)
                if Path(folder).name.startswith("20260101"):
                    raise RuntimeError("first one exploded")
                return {"output": str(output)}

            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.convert", side_effect=fake_convert):
                    with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                        code = main(["convert", str(root), "-o", str(out_dir), "--jobs", "2"])
            self.assertEqual(code, 1)
            self.assertEqual(sorted(seen), ["20260101_Mika", "20260102_Ada"])
            self.assertTrue((out_dir / "Ada.vrm.bak").exists() is False)

    def test_duplicate_labels_fall_back_to_folder_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, "20260101_Same")
            make_export(root, "20260102_Same")
            out_dir = Path(temp) / "out"
            outputs = []
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.convert", side_effect=lambda f, o, **k: outputs.append(Path(o)) or {"output": str(o)}):
                    with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                        code = main(["convert", str(root), "-o", str(out_dir)])
            self.assertEqual(code, 0)
            self.assertEqual(sorted(path.name for path in outputs), ["20260102_Same.vrm", "Same.vrm"])

    def test_name_template_is_applied(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = make_export(root, "20260905_VKSomi")
            card = folder / "card.png"
            outputs = []
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.resolve_input", return_value=(folder, card, "sunshine")):
                    with mock.patch("kkvrm.__main__.convert", side_effect=lambda f, o, **k: outputs.append(Path(o)) or {"output": str(o)}):
                        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                            main(["convert", str(folder), "--name-template", "{folder}--v{version}", "--vrm-version", "2.0.0"])
            self.assertEqual(outputs[0].name, "20260905_VKSomi--v2.0.0.vrm")

    def test_template_characters_are_sanitized(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = make_export(root, "20260905_VKSomi")
            card = folder / "card.png"
            outputs = []
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("kkvrm.__main__.resolve_input", return_value=(folder, card, "sunshine")):
                    with mock.patch("kkvrm.__main__.convert", side_effect=lambda f, o, **k: outputs.append(Path(o)) or {"output": str(o)}):
                        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
                            main(["convert", str(folder), "--name-template", "a../../b:c"])
            self.assertEqual(outputs[0].name, "a.._.._b_c.vrm")

    def test_batch_with_a_vrm_output_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, "20260101_Mika")
            make_export(root, "20260102_Ada")
            with mock.patch("kkvrm.__main__.load", return_value={}):
                with mock.patch("sys.stderr") as stderr:
                    code = main(["convert", str(root), "-o", str(Path(temp) / "bundle.vrm")])
            self.assertEqual(code, 1)
            self.assertIn("batch convert needs an output directory", "\n".join(str(call.args[0]) for call in stderr.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
