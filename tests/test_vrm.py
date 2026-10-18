import tempfile
import unittest
from pathlib import Path

from kkvrm.vrm import audit, audit_document
from test_runner import vrm_bytes


class VrmTests(unittest.TestCase):
    def test_truncated_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "out.vrm"
            path.write_bytes(vrm_bytes()[:-4])
            self.assertFalse(audit(path)["ok"])

    def test_spring_overlap_and_bad_center_are_reported(self):
        document = {"nodes": [{"children": [1]}, {"children": [2]}, {}],
                    "extensions": {"VRMC_springBone": {"springs": [
                        {"name": "one", "joints": [{"node": 0}, {"node": 1}]},
                        {"name": "two", "joints": [{"node": 1}, {"node": 2}], "center": 2},
                    ]}}}
        result = audit_document(document)
        self.assertTrue(any("overlaps" in error for error in result["errors"]))
        self.assertTrue(any("center" in error for error in result["errors"]))
