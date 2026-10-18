import json
import tempfile
import unittest
from pathlib import Path

from kkvrm.physics import linear_segments, normalize_config, plan_physics
from kkvrm.physics_sources import load_sources


def records(pairs):
    return [{"name": name, "parent": parent, "aliases": []} for name, parent in pairs]


class PhysicsTests(unittest.TestCase):
    def test_branch_joints_are_never_duplicated(self):
        bones = records([("Head", None), ("cf_j_hair_a", "Head"), ("cf_j_hair_b", "cf_j_hair_a"),
                         ("cf_j_hair_c", "cf_j_hair_b"), ("cf_j_hair_d", "cf_j_hair_c"),
                         ("cf_j_hair_x", "cf_j_hair_b"), ("cf_j_hair_y", "cf_j_hair_x")])
        result = plan_physics(bones, humanoid={"head": "Head"})
        joints = [joint for chain in result["chains"] for joint in chain["bones"]]
        self.assertEqual(len(joints), len(set(joints)))
        self.assertEqual(result["counts"]["hair"], 3)

    def test_original_name_alias_recovers_ribbon_chain(self):
        bones = records([("Hips", None), ("Chest", "Hips"), ("renamed ribbon", "Chest"), ("ribbon_tail", "renamed ribbon")])
        bones[2]["aliases"] = ["ribbon_A"]
        source = {"dynamics": [{"name": "ribbon_A", "category": "cloth", "enabled": True,
                                "bones": ["ribbon_A", "ribbon_tail"], "colliders": ["torso"]}]}
        result = plan_physics(bones, {"preset": "balanced"}, source,
                              humanoid={"hips": "Hips", "chest": "Chest"},
                              weighted={"cloth": {"renamed ribbon"}})
        self.assertEqual(result["counts"]["cloth"], 1)
        chain = result["chains"][0]
        self.assertEqual(chain["bones"], ["renamed ribbon", "ribbon_tail"])
        self.assertEqual(chain["center"], "Chest")
        self.assertIsNone(chain["endpoint"])

    def test_no_weights_means_no_fake_physics(self):
        bones = records([("ribbon", None), ("tip", "ribbon")])
        config = {"preset": "balanced", "chains": [{"category": "cloth", "bones": ["ribbon", "tip"]}]}
        result = plan_physics(bones, config, weighted={"cloth": set()})
        self.assertEqual(result["counts"]["cloth"], 0)
        self.assertIn("no positive weights", result["skipped"][0]["reason"])

    def test_weighted_leaf_receives_a_separate_unweighted_endpoint(self):
        bones = records([("Head", None), ("cf_j_hair_01", "Head"), ("cf_j_hair_02", "cf_j_hair_01")])
        result = plan_physics(bones, {"preset": "balanced"}, humanoid={"head": "Head"},
                              weighted={"hair": {"cf_j_hair_01", "cf_j_hair_02"}})
        chain = result["chains"][0]
        self.assertEqual(len(chain["bones"]), 3)
        self.assertEqual(chain["endpoint"]["parent"], "cf_j_hair_02")
        self.assertTrue(chain["bones"][-1].startswith("kkvrm_tip_"))

    def test_bust_base_and_humanoid_bones_remain_protected(self):
        bones = records([("Chest", None), ("cf_j_bust01_L", "Chest"), ("cf_j_bust02_L", "cf_j_bust01_L"),
                         ("cf_j_bust03_L", "cf_j_bust02_L")])
        result = plan_physics(bones, {"preset": "balanced"}, humanoid={"chest": "Chest"},
                              weighted={"bust": {"cf_j_bust02_L", "cf_j_bust03_L"}})
        self.assertEqual(result["chains"][0]["bones"], ["cf_j_bust02_L", "cf_j_bust03_L"])

    def test_category_off_does_not_get_enabled_by_custom_chain(self):
        config = {"preset": "balanced", "types": {"cloth": False},
                  "chains": [{"category": "cloth", "bones": ["ribbon", "tail"]}]}
        result = plan_physics(records([("ribbon", None), ("tail", "ribbon")]), config)
        self.assertEqual(result["counts"]["cloth"], 0)

    def test_exclusions_follow_original_names_and_remove_subtrees(self):
        bones = records([("renamed", None), ("tail", "renamed")])
        bones[0]["aliases"] = ["original_ribbon"]
        config = {"preset": "balanced", "exclude": ["original_*"],
                  "chains": [{"category": "cloth", "root": "original_ribbon"}]}
        result = plan_physics(bones, config)
        self.assertEqual(result["counts"]["cloth"], 0)

    def test_invalid_order_cycle_and_center_are_rejected(self):
        bones = records([("Head", None), ("ribbon", "Head"), ("tail", "ribbon")])
        for chain in (["tail", "ribbon"], ["ribbon", "ribbon"]):
            with self.assertRaises(ValueError):
                plan_physics(bones, {"preset": "balanced", "chains": [{"category": "cloth", "bones": chain}]})
        with self.assertRaises(ValueError):
            linear_segments({"a": "b", "b": "a"}, {"a", "b"})
        with self.assertRaises(ValueError):
            plan_physics(bones, {"preset": "balanced", "chains": [{"category": "cloth", "bones": ["ribbon", "tail"], "center": "tail"}]})

    def test_settings_are_finite_and_gravity_normalized(self):
        for settings in ({"drag_force": 1.2}, {"hit_radius": -1}, {"stiffness": float("nan")}, {"gravity_dir": [0, 0, 0]}):
            with self.assertRaises(ValueError):
                normalize_config({"settings": {"hair": settings}})
        config = normalize_config({"settings": {"hair": {"gravity_dir": [0, 0, -2]}}})
        self.assertEqual(config["settings"]["hair"]["gravity_dir"], [0, 0, -1])

    def test_sidecars_identify_generic_hair_and_handle_empty_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "KK_DynamicBoneData.json").write_text(json.dumps([
                {"Root": "j_01", "ParticleBones": ["j_01", "J_02"], "CoordinateType": 0},
                {"Root": "ribbon", "ParticleBones": ["ribbon", "NULL"]},
            ]))
            (folder / "KK_SMRData.json").write_text(json.dumps([
                {"SMRName": "hair", "SMRPath": "/ct_hair/", "SMRBoneNames": ["j_01"], "CoordinateType": 0},
            ]))
            (folder / "KK_EditBoneInfo.json").write_text("")
            source = load_sources(folder)
        self.assertEqual(source["dynamics"][0]["category"], "hair")
        self.assertEqual(source["dynamics"][1]["bones"], ["ribbon"])
        self.assertTrue(source["warnings"])
