import struct
import unittest

from kkvrm.pmx import PmxError, parse


def text(value):
    raw = value.encode("utf-8")
    return struct.pack("<i", len(raw)) + raw


def minimal_pmx():
    parts = [
        b"PMX ",
        struct.pack("<f", 2.0),
        bytes([8, 1, 0, 1, 1, 1, 1, 1, 1]),
        text("Model"),
        text(""),
        text(""),
        text(""),
        struct.pack("<i", 1),
        struct.pack("<8f", 0, 0, 0, 0, 1, 0, 0, 0),
        bytes([0, 0]),
        struct.pack("<f", 1.0),
        struct.pack("<i", 0),
        struct.pack("<i", 1),
        text("body.png"),
        struct.pack("<i", 0),
        struct.pack("<i", 2),
    ]
    parts.append(text("cf_j_head"))
    parts.append(text("head"))
    parts.append(struct.pack("<3f", 0, 1, 0))
    parts.append(bytes([255]))
    parts.append(struct.pack("<iH", 0, 0))
    parts.append(struct.pack("<3f", 0, 0.1, 0))
    parts.append(text("cf_j_hair_01"))
    parts.append(text("hair"))
    parts.append(struct.pack("<3f", 0, 1.2, 0))
    parts.append(bytes([0]))
    parts.append(struct.pack("<iH", 0, 0x0001 | 0x0020))
    parts.append(bytes([0]))
    parts.append(bytes([1]))
    parts.append(struct.pack("<i", 1))
    parts.append(struct.pack("<f", 0.5))
    parts.append(struct.pack("<i", 0))
    parts.append(struct.pack("<i", 1))
    parts.append(text("kuti_face.f00_egao_op"))
    parts.append(text(""))
    parts.append(bytes([3, 1]))
    parts.append(struct.pack("<i", 0))
    return b"".join(parts)


class PmxTests(unittest.TestCase):
    def test_parse_bones_and_morphs(self):
        parsed = parse(minimal_pmx())
        self.assertEqual(parsed["name"], "Model")
        self.assertEqual(parsed["bones"], ["cf_j_head", "cf_j_hair_01"])
        self.assertEqual(parsed["morphs"], ["kuti_face.f00_egao_op"])
        self.assertEqual(parsed["textures"], ["body.png"])

    def test_reject(self):
        with self.assertRaises(PmxError):
            parse(b"not pmx")


if __name__ == "__main__":
    unittest.main()
