import json
import tempfile
import unittest
from pathlib import Path

from kkvrm.shaders import bust_clothing, is_skin, lookup_shader, shader_is_alpha, shader_map


class ShaderTests(unittest.TestCase):
    def test_exact_id_beats_shorter_name(self):
        shaders = {
            "cf_m_top": "Shader Forge/main_alpha",
            "cf_m_top 8750": "Shader Forge/main_opaque",
        }
        found = lookup_shader("KK cf_m_top 8750.001", "cf_m_top 8750", shaders)
        self.assertEqual(found, "Shader Forge/main_opaque")
        self.assertFalse(shader_is_alpha(found))

    def test_fuzzy_when_instance_suffix_differs(self):
        shaders = {"cf_m_bra 8920": "Shader Forge/main_opaque"}
        found = lookup_shader("cf_m_bra 8920 extra", None, shaders)
        self.assertEqual(found, "Shader Forge/main_opaque")

    def test_male_and_female_skin(self):
        self.assertTrue(is_skin("cf_m_body"))
        self.assertTrue(is_skin("cm_m_face"))
        self.assertFalse(is_skin("cf_m_hitomi_00"))

    def test_bust_lift_skips_body_and_hair(self):
        self.assertTrue(bust_clothing("Outfit 00 Mika"))
        self.assertTrue(bust_clothing("Clothes 01"))
        self.assertFalse(bust_clothing("Hair Outfit 00 Mika"))
        self.assertFalse(bust_clothing("Body Mika"))
        self.assertFalse(bust_clothing("Gag Eyes Mika"))

    def test_complete_json_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "KK_MaterialData.json").write_text(
                json.dumps([{"MaterialInformation": [{"MaterialName": "bra", "ShaderName": "Shader Forge/main_alpha"}]}]),
                encoding="utf-8",
            )
            (folder / "KK_MaterialDataComplete.json").write_text(
                json.dumps([{"MaterialInformation": [{"MaterialName": "bra", "ShaderName": "Shader Forge/main_opaque"}]}]),
                encoding="utf-8",
            )
            self.assertEqual(shader_map(folder)["bra"], "Shader Forge/main_opaque")
