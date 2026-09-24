import unittest

from kkvrm.card import CardError, identify


class CardTests(unittest.TestCase):
    def test_sunshine(self):
        self.assertEqual(identify(b"xxKoiKatuCharaSunyy"), "sunshine")
        self.assertEqual(identify("【KoiKatuCharaSP】".encode("utf-8")), "sunshine")

    def test_koikatsu(self):
        self.assertEqual(identify(b"marker KoiKatuChara end"), "koikatsu")

    def test_sunshine_wins_over_shorter_marker(self):
        self.assertEqual(identify(b"KoiKatuCharaSun"), "sunshine")

    def test_reject(self):
        with self.assertRaises(CardError):
            identify(b"HoneySelect2Chara")
        with self.assertRaises(CardError):
            identify(b"plain png")


if __name__ == "__main__":
    unittest.main()
