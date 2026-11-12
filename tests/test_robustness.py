"""Deterministic fuzzing: malformed inputs may be rejected, but only with the documented error type."""

import _isolation  # noqa: F401  (must precede kkvrm imports)
import copy
import random
import tempfile
import unittest
from pathlib import Path

from kkvrm.meta import build_meta
from kkvrm.options import validate_options
from kkvrm.physics import normalize_config
from kkvrm.pmx import PmxError, parse
from kkvrm.profiles import validate_document
from kkvrm.vrm import audit, audit_document
from _fixtures import HUMANOID_BONES, glb, pmx_bytes, vrm_document, with_mesh

JUNK = (None, 0, -1, 0.5, 1e309, "", "x", "1.5", [], [None], [1, 2, 3], {}, {"a": 1}, True, False)
ITERATIONS = 1500


def mutate_bytes(rng, data):
    data = bytearray(data)
    for _ in range(rng.randint(1, 4)):
        if not data:
            break
        position = rng.randrange(len(data))
        choice = rng.random()
        if choice < 0.6:
            data[position] = rng.randrange(256)
        elif choice < 0.8:
            del data[position:]
        else:
            data[position:position] = bytes([rng.randrange(256)])
    return bytes(data)


def mutate_json(rng, value):
    if isinstance(value, dict) and value and rng.random() < 0.75:
        key = rng.choice(sorted(value, key=str))
        return dict(value, **{key: mutate_json(rng, value[key])})
    if isinstance(value, list) and value and rng.random() < 0.75:
        index = rng.randrange(len(value))
        return value[:index] + [mutate_json(rng, value[index])] + value[index + 1:]
    return copy.deepcopy(rng.choice(JUNK))


class PmxFuzzTests(unittest.TestCase):
    def test_corrupt_pmx_only_raises_pmx_error(self):
        rng = random.Random(1)
        seed = pmx_bytes(HUMANOID_BONES + [("cf_j_hair_01", "cf_j_head")], morphs=["eye smiling", "mouth a big"])
        for iteration in range(ITERATIONS):
            data = mutate_bytes(rng, seed)
            try:
                parse(data)
            except PmxError:
                pass
            except Exception as exc:  # noqa: BLE001 - this is the assertion
                self.fail(f"iteration {iteration}: {type(exc).__name__}: {exc}")

    def test_every_truncation_is_rejected(self):
        data = pmx_bytes(HUMANOID_BONES[:3], morphs=["eye smiling"])
        for length in range(len(data)):
            with self.assertRaises(PmxError, msg=f"length {length}"):
                parse(data[:length])


class VrmAuditFuzzTests(unittest.TestCase):
    def test_audit_never_raises_on_malformed_documents(self):
        rng = random.Random(2)
        document, node = with_mesh(vrm_document(), targets=3)
        extension = document["extensions"]["VRMC_vrm"]
        extension["expressions"] = {"preset": {"happy": {"morphTargetBinds": [{"node": node, "index": 1, "weight": 1}]}},
                                    "custom": {"x": {"morphTargetBinds": [{"node": node, "index": 2}]}}}
        document["extensions"]["VRMC_springBone"] = {
            "colliders": [{"node": 0, "shape": {"sphere": {"radius": 0.1, "offset": [0, 0, 0]}}}],
            "colliderGroups": [{"colliders": [0]}],
            "springs": [{"name": "s", "joints": [{"node": 0}, {"node": 1}], "colliderGroups": [0]}],
        }
        for iteration in range(ITERATIONS):
            broken = mutate_json(rng, document)
            try:
                report = audit_document(broken)
            except Exception as exc:  # noqa: BLE001 - this is the assertion
                self.fail(f"iteration {iteration}: {type(exc).__name__}: {exc}")
            self.assertIsInstance(report["ok"], bool)

    def test_audit_of_corrupt_files_reports_instead_of_raising(self):
        rng = random.Random(3)
        seed = glb(vrm_document())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "out.vrm"
            for _ in range(300):
                path.write_bytes(mutate_bytes(rng, seed))
                report = audit(path)
                self.assertIn("ok", report)
            self.assertFalse(audit(Path(temp) / "missing.vrm")["ok"])


class ValidatorFuzzTests(unittest.TestCase):
    def assert_value_error_only(self, function, value):
        try:
            function(value)
        except (ValueError, FileNotFoundError):
            pass
        except Exception as exc:  # noqa: BLE001 - this is the assertion
            self.fail(f"{function.__name__}({value!r}) raised {type(exc).__name__}: {exc}")

    def test_validators_reject_junk_with_value_error(self):
        rng = random.Random(4)
        option_keys = ("sfw", "include_hidden", "keep_blend", "cache", "bust_lift", "height", "outfit",
                       "include_mesh", "exclude_mesh", "bust_materials", "material_overrides", "physics")
        physics_keys = ("preset", "types", "colliders", "endpoints", "exclude", "settings", "chains", "joint_settings")
        chain_keys = ("name", "bones", "root", "center", "settings", "joint_settings", "colliders", "endpoint", "category")
        meta_keys = ("name", "version", "authors", "contact", "references", "licenseUrl", "avatarPermission",
                     "allowSexual", "commercialUsage", "thumbnail")
        for _ in range(ITERATIONS):
            self.assert_value_error_only(validate_options, {rng.choice(option_keys): rng.choice(JUNK)})
            self.assert_value_error_only(validate_options, {"material_overrides": {"m": {
                rng.choice(("alpha_mode", "alpha_cutoff", "double_sided")): rng.choice(JUNK)}}})
            self.assert_value_error_only(normalize_config, {rng.choice(physics_keys): rng.choice(JUNK)})
            self.assert_value_error_only(normalize_config, {"settings": {"hair": {
                rng.choice(("stiffness", "drag_force", "hit_radius", "gravity_power", "gravity_dir")): rng.choice(JUNK)}}})
            self.assert_value_error_only(normalize_config, {"chains": [dict(
                {"category": "hair", "root": "a"}, **{rng.choice(chain_keys): rng.choice(JUNK)})]})
            self.assert_value_error_only(lambda meta: build_meta("Model", overrides=meta),
                                         {rng.choice(meta_keys): rng.choice(JUNK)})
            self.assert_value_error_only(validate_document, {rng.choice(("schema_version", "meta", "options")): rng.choice(JUNK)})


class AuditRuleTests(unittest.TestCase):
    def test_fixture_is_valid(self):
        report = audit_document(vrm_document())
        self.assertTrue(report["ok"], report["errors"])

    def test_required_meta_fields(self):
        for field, value in (("name", ""), ("authors", []), ("authors", [""]), ("licenseUrl", None)):
            document = vrm_document()
            document["extensions"]["VRMC_vrm"]["meta"][field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(audit_document(document)["ok"])

    def test_two_humanoid_bones_cannot_share_a_node(self):
        document = vrm_document()
        bones = document["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
        bones["chest"] = {"node": bones["spine"]["node"]}
        errors = audit_document(document)["errors"]
        self.assertTrue(any("share node" in error for error in errors), errors)

    def test_texture_material_and_mesh_references(self):
        document = vrm_document()
        document["images"] = [{}]
        document["textures"] = [{"source": 5}]
        document["materials"] = [{"name": "m", "pbrMetallicRoughness": {"baseColorTexture": {"index": 3}},
                                  "alphaMode": "CUTOUT"}]
        document["nodes"].append({"mesh": 0})
        errors = audit_document(document)["errors"]
        for expected in ("texture 0 references a missing image", "m: base texture references a missing texture",
                         "m: invalid alphaMode", "references a missing mesh"):
            self.assertTrue(any(expected in error for error in errors), (expected, errors))

    def test_expression_binds_must_target_existing_morphs(self):
        document, node = with_mesh(vrm_document(), targets=2)
        expressions = document["extensions"]["VRMC_vrm"]["expressions"] = {"preset": {}, "custom": {}}
        expressions["preset"]["happy"] = {"morphTargetBinds": [{"node": node, "index": 1, "weight": 1.0}]}
        self.assertTrue(audit_document(document)["ok"], audit_document(document)["errors"])
        for bind, message in (({"node": node, "index": 2}, "out of range"),
                              ({"node": 0, "index": 0}, "without a mesh"),
                              ({"node": node, "index": 0, "weight": 2}, "weight")):
            expressions["custom"]["bad"] = {"morphTargetBinds": [bind]}
            with self.subTest(bind=bind):
                errors = audit_document(document)["errors"]
                self.assertTrue(any(message in error for error in errors), errors)

    def test_spring_and_collider_rules(self):
        document = vrm_document()
        document["nodes"][0]["children"] = [1]
        document["nodes"][1]["children"] = [2]
        document["extensions"]["VRMC_springBone"] = {
            "colliders": [{"node": 0, "shape": {"sphere": {"radius": -1}}},
                          {"node": 0, "shape": {"sphere": {}, "capsule": {}}},
                          {"node": 99, "shape": {"capsule": {"radius": 0.1, "tail": [0, 0]}}}],
            "colliderGroups": [{"colliders": [7]}],
            "springs": [{"name": "s", "joints": [{"node": 2}, {"node": 1}], "colliderGroups": [4]},
                        {"name": "t", "joints": [{"node": 0, "dragForce": 2}, {"node": 1}]}],
        }
        errors = audit_document(document)["errors"]
        for expected in ("invalid radius for collider 0", "collider 1 requires a sphere or capsule",
                         "collider 2 references a missing node", "invalid tail for collider 2",
                         "collider group 0 has invalid references", "s: joints are not in ancestor order",
                         "s: invalid collider group reference", "t: invalid dragForce"):
            self.assertIn(expected, errors)


class SuiteHygieneTests(unittest.TestCase):
    def test_every_test_module_isolates_user_configuration(self):
        for path in sorted(Path(__file__).parent.glob("test_*.py")):
            first = path.read_text(encoding="utf-8").lstrip().splitlines()
            code = [line for line in first if line and not line.startswith(("#", '"""')) and not line.endswith('"""')]
            imports = [line for line in code if line.startswith(("import ", "from "))]
            with self.subTest(module=path.name):
                self.assertTrue(imports and imports[0].startswith("import _isolation"),
                                f"{path.name} must import _isolation before anything else")

    def test_isolation_redirects_the_config_directory(self):
        from kkvrm.config import config_path
        self.assertTrue(str(config_path()).startswith(str(_isolation.ROOT)))


if __name__ == "__main__":
    unittest.main()
