import tempfile
import unittest
from pathlib import Path

from kkvrm.card import CardError
from kkvrm.locate import character_name, list_exports, resolve_input


class LocateTests(unittest.TestCase):
    def test_character_name(self):
        self.assertEqual(character_name("20260119173812_Sameko"), "Sameko")
        self.assertEqual(character_name("Sameko"), "Sameko")

    def test_png_inside_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "20260101_Mika"
            root.mkdir()
            (root / "body.pmx").write_bytes(b"PMX ")
            card = root / "card.png"
            card.write_bytes(b"PNG KoiKatuCharaSun")
            folder, found, game = resolve_input(card)
            self.assertEqual(folder, root.resolve())
            self.assertEqual(found, card.resolve())
            self.assertEqual(game, "sunshine")

    def test_export_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "20260101_Mika"
            root.mkdir()
            (root / "body.pmx").write_bytes(b"PMX ")
            folder, _card, _game = resolve_input(root)
            self.assertEqual(folder, root.resolve())

    def test_card_searches_export_root(self):
        with tempfile.TemporaryDirectory() as temp:
            card = Path(temp) / "card.png"
            payload = b"PNG KoiKatuCharaSun payload"
            card.write_bytes(payload)
            export_root = Path(temp) / "Export_PMX"
            folder = export_root / "20260202_Mika"
            folder.mkdir(parents=True)
            (folder / "body.pmx").write_bytes(b"PMX ")
            (folder / "copied.png").write_bytes(payload)
            found_folder, found_card, game = resolve_input(card, export_root=export_root)
            self.assertEqual(found_folder, folder.resolve())
            self.assertEqual(found_card, card.resolve())
            self.assertEqual(game, "sunshine")

    def test_missing_export(self):
        with tempfile.TemporaryDirectory() as temp:
            card = Path(temp) / "card.png"
            card.write_bytes(b"PNG KoiKatuCharaSun")
            with self.assertRaises(FileNotFoundError):
                resolve_input(card)

    def test_list_exports_finds_children_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Export_PMX"
            one = root / "20260101_Mika"
            two = root / "20260102_Ada"
            one.mkdir(parents=True)
            two.mkdir()
            (one / "body.pmx").write_bytes(b"PMX ")
            (two / "model.pmx").write_bytes(b"PMX ")
            (root / "notes.txt").write_text("no", encoding="utf-8")
            found = list_exports(root)
            self.assertEqual(found, [one, two])
            self.assertEqual(list_exports(one), [])

    def test_not_a_card(self):
        with tempfile.TemporaryDirectory() as temp:
            png = Path(temp) / "tex.png"
            png.write_bytes(b"not a card")
            with self.assertRaises(CardError):
                resolve_input(png)


if __name__ == "__main__":
    unittest.main()
