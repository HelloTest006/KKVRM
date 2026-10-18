import json
import math
import struct
from pathlib import Path

from .bones import REQUIRED


def read_document(path):
    """Read the GLB JSON chunk without loading embedded meshes/textures into RAM."""
    path = Path(path)
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            raise ValueError("truncated GLB header")
        magic, version, length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or length != path.stat().st_size:
            raise ValueError("invalid GLB header or file length")
        chunk = handle.read(8)
        if len(chunk) != 8:
            raise ValueError("missing GLB JSON chunk")
        size, kind = struct.unpack("<I4s", chunk)
        if kind != b"JSON" or size % 4 or size > length - 20:
            raise ValueError("invalid GLB JSON chunk")
        try:
            document = json.loads(handle.read(size))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(f"invalid GLB JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("GLB JSON must be an object")
    return document


def audit_document(document):
    errors, warnings = [], []
    nodes = document.get("nodes", [])
    extension = document.get("extensions", {}).get("VRMC_vrm", {})
    spring_bone = document.get("extensions", {}).get("VRMC_springBone", {})

    def valid_node(index):
        return isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(nodes)

    if extension.get("specVersion") != "1.0":
        errors.append("missing VRMC_vrm 1.0 extension")
    human_bones = extension.get("humanoid", {}).get("humanBones", {})
    for slot in REQUIRED:
        parts = slot.split("_")
        key = parts[0] + "".join(part.title() for part in parts[1:])
        if not valid_node(human_bones.get(key, {}).get("node")):
            errors.append(f"missing humanoid bone: {key}")
    for key, bone in human_bones.items():
        if not valid_node(bone.get("node")):
            errors.append(f"invalid humanoid node: {key}")

    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if not valid_node(child) or child == index:
                errors.append(f"invalid child of node {index}")
            elif child in parents:
                errors.append(f"node {child} has multiple parents")
            else:
                parents[child] = index

    def ancestry(index):
        result = []
        while valid_node(index) and index not in result:
            result.append(index)
            index = parents.get(index)
        if index in result:
            errors.append("node hierarchy contains a cycle")
        return result

    colliders = spring_bone.get("colliders", [])
    groups = spring_bone.get("colliderGroups", [])
    for index, collider in enumerate(colliders):
        if not valid_node(collider.get("node")):
            errors.append(f"collider {index} references a missing node")
        shapes = collider.get("shape", {})
        if len(shapes) != 1 or not ({"sphere", "capsule"} & shapes.keys()):
            errors.append(f"collider {index} requires a sphere or capsule")
            continue
        shape = next(iter(shapes.values()))
        radius = shape.get("radius", -1)
        if not isinstance(radius, (float, int)) or not math.isfinite(radius) or radius < 0:
            errors.append(f"invalid radius for collider {index}")
        for key in ("offset", "tail"):
            vector = shape.get(key)
            if vector is not None and (len(vector) != 3 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector)):
                errors.append(f"invalid {key} for collider {index}")
    for index, group in enumerate(groups):
        if any(not isinstance(ref, int) or not 0 <= ref < len(colliders) for ref in group.get("colliders", [])):
            errors.append(f"collider group {index} has invalid references")

    claimed = set()
    occupied_by_spring = []
    for spring in spring_bone.get("springs", []):
        label = spring.get("name", "unnamed spring")
        joints = spring.get("joints", [])
        indices = [joint.get("node") for joint in joints]
        if len(indices) < 2 or not all(valid_node(index) for index in indices):
            errors.append(f"{label}: invalid or missing spring joints")
            continue
        occupied = set(indices)
        if len(occupied) != len(indices):
            errors.append(f"{label}: repeated spring joint")
        for head, tail in zip(indices, indices[1:]):
            path = ancestry(tail)
            if head not in path[1:]:
                errors.append(f"{label}: joints are not in ancestor order")
            else:
                occupied.update(path[:path.index(head) + 1])
        if occupied & claimed:
            errors.append(f"{label}: overlaps another spring chain")
        claimed.update(occupied)
        occupied_by_spring.append((spring, occupied))
        for joint in joints[:-1]:
            for key in ("hitRadius", "stiffness", "gravityPower", "dragForce"):
                value = joint.get(key, 0)
                if not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (key == "dragForce" and value > 1):
                    errors.append(f"{label}: invalid {key}")
        if any(not isinstance(ref, int) or not 0 <= ref < len(groups) for ref in spring.get("colliderGroups", [])):
            errors.append(f"{label}: invalid collider group reference")
    for spring, occupied in occupied_by_spring:
        center = spring.get("center")
        first = spring["joints"][0]["node"]
        if center is not None and (not valid_node(center) or center not in ancestry(first)):
            errors.append(f"{spring.get('name', 'spring')}: center is not an ancestor")
        if center is not None:
            for other, other_occupied in occupied_by_spring:
                if other is not spring and set(ancestry(center)) & other_occupied:
                    errors.append(f"{spring.get('name', 'spring')}: center depends on another spring")

    images = document.get("images", [])
    materials = document.get("materials", [])
    for material in materials:
        if not material.get("pbrMetallicRoughness", {}).get("baseColorTexture"):
            warnings.append(f"no base texture: {material.get('name', 'material')}")
    expressions = extension.get("expressions", {})
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": {
            "nodes": len(nodes),
            "humanoid_bones": len(human_bones),
            "meshes": len(document.get("meshes", [])),
            "materials": len(materials),
            "images": len(images),
            "springs": len(spring_bone.get("springs", [])),
            "colliders": len(colliders),
            "collider_groups": len(groups),
            "preset_expressions": len(expressions.get("preset", {})),
            "custom_expressions": len(expressions.get("custom", {})),
        },
        "meta": extension.get("meta", {}),
    }


def audit(path):
    try:
        return audit_document(read_document(path))
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "summary": {}}


def validate(path):
    report = audit(path)
    if not report["ok"]:
        raise RuntimeError("VRM validation failed: " + "; ".join(report["errors"]))
    return report
