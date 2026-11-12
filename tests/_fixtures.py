"""Small, spec-valid documents shared by the host tests."""

import copy
import json
import struct

from kkvrm.bones import REQUIRED


def camel(slot):
    first, *rest = slot.split("_")
    return first + "".join(part.title() for part in rest)


def vrm_document():
    """A minimal VRM 1.0 document that passes ``audit_document`` without errors."""
    slots = sorted(REQUIRED)
    human = {camel(slot): {"node": index} for index, slot in enumerate(slots)}
    return {
        "asset": {"version": "2.0"},
        "nodes": [{"name": slot} for slot in slots],
        "extensions": {"VRMC_vrm": {
            "specVersion": "1.0",
            "meta": {"name": "Fixture", "authors": ["KKVRM"], "licenseUrl": "https://vrm.dev/licenses/1.0/"},
            "humanoid": {"humanBones": human},
        }},
    }


def with_mesh(document, targets=2):
    """Attach one mesh node with ``targets`` morph targets; returns (document, node index)."""
    document = copy.deepcopy(document)
    document.setdefault("meshes", []).append({"primitives": [{"targets": [{} for _ in range(targets)]}]})
    document["nodes"].append({"name": "Body", "mesh": len(document["meshes"]) - 1})
    return document, len(document["nodes"]) - 1


def glb(document):
    chunk = json.dumps(document).encode()
    chunk += b" " * (-len(chunk) % 4)
    return struct.pack("<4sII", b"glTF", 2, len(chunk) + 20) + struct.pack("<I4s", len(chunk), b"JSON") + chunk


def vrm_bytes():
    return glb(vrm_document())


def _text(value):
    raw = value.encode("utf-8")
    return struct.pack("<i", len(raw)) + raw


def pmx_bytes(bones, morphs=(), name="Model"):
    """Build a UTF-8 PMX 2.0 with no geometry and ``bones`` as (name, parent_name_or_None).

    The root bone uses parent index 0 like KKBP's exporter does.
    """
    index = {bone: position for position, (bone, _parent) in enumerate(bones)}
    parts = [b"PMX ", struct.pack("<f", 2.0), bytes([8, 1, 0, 1, 1, 1, 1, 1, 1]),
             _text(name), _text(""), _text(""), _text(""),
             struct.pack("<i", 0), struct.pack("<i", 0), struct.pack("<i", 0), struct.pack("<i", 0),
             struct.pack("<i", len(bones))]
    for bone, parent in bones:
        parts += [_text(bone), _text(bone + "_en"), struct.pack("<3f", 0, 0, 0),
                  struct.pack("<b", index[parent] if parent else 0), struct.pack("<iH", 0, 0),
                  struct.pack("<3f", 0, 0.1, 0)]
    parts.append(struct.pack("<i", len(morphs)))
    for morph in morphs:
        parts += [_text(morph), _text(""), bytes([3, 1]), struct.pack("<i", 0)]
    return b"".join(parts)


HUMANOID_BONES = [
    ("cf_j_root", None), ("cf_j_waist01", "cf_j_root"), ("cf_j_spine01", "cf_j_waist01"),
    ("cf_j_spine02", "cf_j_spine01"), ("cf_j_neck", "cf_j_spine02"), ("cf_j_head", "cf_j_neck"),
    ("cf_j_arm00_L", "cf_j_spine02"), ("cf_j_forearm01_L", "cf_j_arm00_L"), ("cf_j_hand_L", "cf_j_forearm01_L"),
    ("cf_j_arm00_R", "cf_j_spine02"), ("cf_j_forearm01_R", "cf_j_arm00_R"), ("cf_j_hand_R", "cf_j_forearm01_R"),
    ("cf_j_thigh00_L", "cf_j_waist01"), ("cf_j_leg01_L", "cf_j_thigh00_L"), ("cf_j_foot_L", "cf_j_leg01_L"),
    ("cf_j_thigh00_R", "cf_j_waist01"), ("cf_j_leg01_R", "cf_j_thigh00_R"), ("cf_j_foot_R", "cf_j_leg01_R"),
]
