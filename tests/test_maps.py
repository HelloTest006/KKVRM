import unittest

from kkvrm.bones import match_humanoid, spring_chains, spring_kind
from kkvrm.expressions import choose_presets, classify


class ExpressionTests(unittest.TestCase):
    def test_presets(self):
        cases = {
            "Eye Wink Left": "blink_left",
            "Eye Winking L": "blink_left",
            "Mouth Wink Right": "blink_right",
            "Eye Default, Closed": "blink",
            "Eye Closed": "blink",
            "Mouth a Big": "aa",
            "Mouth Big A": "aa",
            "Mouth Big I": "ih",
            "Mouth Big U": "ou",
            "Mouth Big E": "ee",
            "Mouth Big O": "oh",
            "Mouth i Big": "ih",
            "Mouth u Big": "ou",
            "Mouth e Big": "ee",
            "Mouth o Big": "oh",
            "Mouth a Small": None,
            "Eye Smiling": "happy",
            "Mouth Happy Broad": "happy",
            "Eye Happy Slight": None,
            "Eye Angry": "angry",
            "Eyebrow Angry": "angry",
            "Eye Angry 2": None,
            "Eye Angry Left": None,
            "Eye Lonely": "sad",
            "Mouth Sad": "sad",
            "Eye Shocked": "surprised",
            "Mouth Surprised": "surprised",
            "Eyebrow Surprised": "surprised",
            "Mouth Surprised (Moderate)": None,
            "Eye Bored": "relaxed",
            "Eyebrow Bored": "relaxed",
            "Eye Shocked Moderate": None,
            "Tears big": None,
            "Gag eye 00": None,
        }
        for name, expected in cases.items():
            self.assertEqual(classify(name), expected, name)

    def test_one_preset_per_region(self):
        chosen = choose_presets(
            [
                "Eye Smiling",
                "Eye Happy Broad",
                "Mouth Happy Broad",
                "Mouth Smiling",
                "Eye Angry",
                "Eye Angry 2",
                "Tears big",
            ]
        )
        self.assertEqual(chosen["Eye Happy Broad"], "happy")
        self.assertNotIn("Eye Smiling", chosen)
        self.assertEqual(chosen["Mouth Happy Broad"], "happy")
        self.assertNotIn("Mouth Smiling", chosen)
        self.assertEqual(chosen["Eye Angry"], "angry")


class BoneTests(unittest.TestCase):
    def test_required_english_names(self):
        names = [
            "Hips",
            "Spine",
            "Chest",
            "Upper Chest",
            "Neck",
            "Head",
            "Left Eye",
            "Right Eye",
            "Left shoulder",
            "Right shoulder",
            "Left arm",
            "Right arm",
            "Left elbow",
            "Right elbow",
            "Left wrist",
            "Right wrist",
            "Left leg",
            "Right leg",
            "Left knee",
            "Right knee",
            "Left ankle",
            "Right ankle",
            "Left toe",
            "Thumb0_L",
            "IndexFinger1_L",
        ]
        found, missing = match_humanoid(names)
        self.assertEqual(missing, [])
        self.assertEqual(found["hips"], "Hips")
        both, _missing = match_humanoid(names + ["Pelvis"])
        self.assertEqual(both["hips"], "Pelvis")
        self.assertEqual(found["left_foot"], "Left ankle")
        self.assertEqual(found["left_thumb_metacarpal"], "Thumb0_L")
        self.assertEqual(found["left_index_proximal"], "IndexFinger1_L")

    def test_missing_required(self):
        _found, missing = match_humanoid(["Hips", "Head"])
        self.assertIn("spine", missing)
        self.assertIn("left_hand", missing)

    def test_original_names(self):
        found, missing = match_humanoid(
            [
                "cf_j_waist01",
                "cf_j_spine01",
                "cf_j_head",
                "cf_j_arm00_L",
                "cf_j_forearm01_L",
                "cf_j_hand_L",
                "cf_j_arm00_R",
                "cf_j_forearm01_R",
                "cf_j_hand_R",
                "cf_j_thigh00_L",
                "cf_j_leg01_L",
                "cf_j_foot_L",
                "cf_j_thigh00_R",
                "cf_j_leg01_R",
                "cf_j_foot_R",
            ]
        )
        self.assertEqual(missing, [])
        self.assertEqual(found["hips"], "cf_j_waist01")
        self.assertEqual(found["left_hand"], "cf_j_hand_L")

    def test_spring_chains(self):
        bones = [
            ("Hips", None),
            ("cf_j_hair_01", "Head"),
            ("cf_j_hair_02", "cf_j_hair_01"),
            ("cf_j_hair_03", "cf_j_hair_02"),
            ("cf_j_hair_a", "Head"),
            ("cf_j_hair_a1", "cf_j_hair_a"),
            ("cf_j_hair_a2", "cf_j_hair_a"),
            ("cf_j_sk_00_00", "Hips"),
            ("cf_j_sk_00_01", "cf_j_sk_00_00"),
            ("cf_j_bust01_L", "Chest"),
            ("cf_j_bust02_L", "cf_j_bust01_L"),
            ("cf_j_bust03_L", "cf_j_bust02_L"),
            ("cf_d_bust_L", "Chest"),
        ]
        chains = spring_chains(bones, skip={"Hips"})
        hair = [chain for kind, chain in chains if kind == "hair"]
        skirt = [chain for kind, chain in chains if kind == "skirt"]
        bust = [chain for kind, chain in chains if kind == "bust"]
        self.assertEqual(hair, [
            ["cf_j_hair_01", "cf_j_hair_02", "cf_j_hair_03"],
            ["cf_j_hair_a", "cf_j_hair_a1"],
            ["cf_j_hair_a", "cf_j_hair_a2"],
        ])
        self.assertEqual(skirt, [["cf_j_sk_00_00", "cf_j_sk_00_01"]])
        self.assertEqual(bust, [["cf_j_bust02_L", "cf_j_bust03_L"]])
        self.assertIsNone(spring_kind("cf_j_bust01_L"))
        self.assertIsNone(spring_kind("cf_d_bust_L"))
        self.assertIsNone(spring_kind("cf_s_bust_L"))
        self.assertIsNone(spring_kind("cf_hit_bust_L"))


if __name__ == "__main__":
    unittest.main()
