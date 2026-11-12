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


def _index(value, size):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def audit_document(document):
    """Check the VRM 1.0 structures KKVRM writes; never raise on malformed input."""
    errors, warnings = [], []

    def typed(container, key, kind, label):
        value = container.get(key) if isinstance(container, dict) else None
        if value is None:
            return kind()
        if not isinstance(value, kind):
            errors.append(f"{label} must be {'an object' if kind is dict else 'an array'}")
            return kind()
        return value

    def objects(container, key, label):
        items = typed(container, key, list, label)
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{label}[{index}] must be an object")
        return [item if isinstance(item, dict) else {} for item in items]

    if not isinstance(document, dict):
        return {"ok": False, "errors": ["GLB JSON must be an object"], "warnings": [], "summary": {}, "meta": {}}
    nodes = objects(document, "nodes", "nodes")
    meshes = objects(document, "meshes", "meshes")
    images = objects(document, "images", "images")
    textures = objects(document, "textures", "textures")
    materials = objects(document, "materials", "materials")
    extensions = typed(document, "extensions", dict, "extensions")
    extension = typed(extensions, "VRMC_vrm", dict, "VRMC_vrm")
    spring_bone = typed(extensions, "VRMC_springBone", dict, "VRMC_springBone")

    def valid_node(index):
        return _index(index, len(nodes))

    if extension.get("specVersion") != "1.0":
        errors.append("missing VRMC_vrm 1.0 extension")

    meta = typed(extension, "meta", dict, "VRMC_vrm.meta")
    if extension:
        name = meta.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append("meta.name is required")
        authors = meta.get("authors")
        if not isinstance(authors, list) or not authors or not all(isinstance(item, str) and item.strip() for item in authors):
            errors.append("meta.authors requires at least one non-empty author")
        if not isinstance(meta.get("licenseUrl"), str) or not meta.get("licenseUrl"):
            errors.append("meta.licenseUrl is required")

    humanoid = typed(extension, "humanoid", dict, "humanoid")
    human_bones = typed(humanoid, "humanBones", dict, "humanoid.humanBones")
    for slot in REQUIRED:
        parts = slot.split("_")
        key = parts[0] + "".join(part.title() for part in parts[1:])
        bone = human_bones.get(key)
        if not isinstance(bone, dict) or not valid_node(bone.get("node")):
            errors.append(f"missing humanoid bone: {key}")
    used_by = {}
    for key, bone in human_bones.items():
        node = bone.get("node") if isinstance(bone, dict) else None
        if not valid_node(node):
            errors.append(f"invalid humanoid node: {key}")
        elif node in used_by:
            errors.append(f"humanoid bones {used_by[node]} and {key} share node {node}")
        else:
            used_by[node] = key

    parents = {}
    for index, node in enumerate(nodes):
        for child in typed(node, "children", list, f"node {index} children"):
            if not valid_node(child) or child == index:
                errors.append(f"invalid child of node {index}")
            elif child in parents:
                errors.append(f"node {child} has multiple parents")
            else:
                parents[child] = index
        if "mesh" in node and not _index(node["mesh"], len(meshes)):
            errors.append(f"node {index} references a missing mesh")

    def ancestry(index):
        result = []
        while valid_node(index) and index not in result:
            result.append(index)
            index = parents.get(index)
        if index in result:
            errors.append("node hierarchy contains a cycle")
        return result

    for index, texture in enumerate(textures):
        if "source" in texture and not _index(texture["source"], len(images)):
            errors.append(f"texture {index} references a missing image")
    for material in materials:
        label = material.get("name", "material")
        pbr = material.get("pbrMetallicRoughness")
        base = pbr.get("baseColorTexture") if isinstance(pbr, dict) else None
        if not base:
            warnings.append(f"no base texture: {label}")
        elif not isinstance(base, dict) or not _index(base.get("index"), len(textures)):
            errors.append(f"{label}: base texture references a missing texture")
        mode = material.get("alphaMode", "OPAQUE")
        if mode not in ("OPAQUE", "MASK", "BLEND"):
            errors.append(f"{label}: invalid alphaMode {mode!r}")
        cutoff = material.get("alphaCutoff", 0.5)
        if not _number(cutoff) or cutoff < 0:
            errors.append(f"{label}: invalid alphaCutoff")

    def target_count(node):
        mesh_index = nodes[node].get("mesh")
        if not _index(mesh_index, len(meshes)):
            return None
        primitives = typed(meshes[mesh_index], "primitives", list, f"mesh {mesh_index} primitives")
        counts = {len(item["targets"]) if isinstance(item.get("targets"), list) else 0
                  for item in primitives if isinstance(item, dict)}
        return min(counts) if counts else 0

    expressions = typed(extension, "expressions", dict, "expressions")
    presets = typed(expressions, "preset", dict, "expressions.preset")
    custom = typed(expressions, "custom", dict, "expressions.custom")
    for name, expression in list(presets.items()) + list(custom.items()):
        if not isinstance(expression, dict):
            errors.append(f"expression {name} must be an object")
            continue
        for bind in typed(expression, "morphTargetBinds", list, f"expression {name} binds"):
            node = bind.get("node") if isinstance(bind, dict) else None
            count = target_count(node) if valid_node(node) else None
            weight = bind.get("weight", 1.0) if isinstance(bind, dict) else None
            if count is None:
                errors.append(f"expression {name}: bind references a node without a mesh")
            elif not _index(bind.get("index"), count):
                errors.append(f"expression {name}: morph target index out of range")
            elif not _number(weight) or not 0 <= weight <= 1:
                errors.append(f"expression {name}: weight must be between 0 and 1")

    colliders = objects(spring_bone, "colliders", "colliders")
    groups = objects(spring_bone, "colliderGroups", "colliderGroups")
    springs = objects(spring_bone, "springs", "springs")
    for index, collider in enumerate(colliders):
        if not valid_node(collider.get("node")):
            errors.append(f"collider {index} references a missing node")
        shapes = collider.get("shape")
        if not isinstance(shapes, dict) or len(shapes) != 1 or not ({"sphere", "capsule"} & shapes.keys()):
            errors.append(f"collider {index} requires a sphere or capsule")
            continue
        shape = next(iter(shapes.values()))
        if not isinstance(shape, dict):
            errors.append(f"collider {index} shape must be an object")
            continue
        radius = shape.get("radius", -1)
        if not _number(radius) or radius < 0:
            errors.append(f"invalid radius for collider {index}")
        for key in ("offset", "tail"):
            vector = shape.get(key)
            if vector is not None and (not isinstance(vector, list) or len(vector) != 3 or not all(_number(v) for v in vector)):
                errors.append(f"invalid {key} for collider {index}")
    for index, group in enumerate(groups):
        if any(not _index(ref, len(colliders)) for ref in typed(group, "colliders", list, f"collider group {index}")):
            errors.append(f"collider group {index} has invalid references")

    claimed = set()
    occupied_by_spring = []
    for spring in springs:
        label = spring.get("name", "unnamed spring")
        joints = objects(spring, "joints", f"{label} joints")
        indices = [joint.get("node") for joint in joints]
        if len(indices) < 2 or not all(valid_node(index) for index in indices):
            errors.append(f"{label}: invalid or missing spring joints")
            continue
        occupied = set(indices)
        if len(occupied) != len(indices):
            errors.append(f"{label}: repeated spring joint")
        for head, tail in zip(indices, indices[1:]):  # noqa: B905 - neighbouring pairs
            path = ancestry(tail)
            if head not in path[1:]:
                errors.append(f"{label}: joints are not in ancestor order")
            else:
                occupied.update(path[:path.index(head) + 1])
        if occupied & claimed:
            errors.append(f"{label}: overlaps another spring chain")
        claimed.update(occupied)
        occupied_by_spring.append((spring, indices[0], occupied))
        for joint in joints[:-1]:
            for key in ("hitRadius", "stiffness", "gravityPower", "dragForce"):
                value = joint.get(key, 0)
                if not _number(value) or value < 0 or (key == "dragForce" and value > 1):
                    errors.append(f"{label}: invalid {key}")
        if any(not _index(ref, len(groups)) for ref in typed(spring, "colliderGroups", list, f"{label} colliderGroups")):
            errors.append(f"{label}: invalid collider group reference")
    for spring, first, _occupied in occupied_by_spring:
        label = spring.get("name", "spring")
        center = spring.get("center")
        if center is None:
            continue
        if not valid_node(center) or center not in ancestry(first):
            errors.append(f"{label}: center is not an ancestor")
            continue
        for other, _first, other_occupied in occupied_by_spring:
            if other is not spring and set(ancestry(center)) & other_occupied:
                errors.append(f"{label}: center depends on another spring")

    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": {
            "nodes": len(nodes),
            "humanoid_bones": len(human_bones),
            "meshes": len(meshes),
            "materials": len(materials),
            "images": len(images),
            "springs": len(springs),
            "colliders": len(colliders),
            "collider_groups": len(groups),
            "preset_expressions": len(presets),
            "custom_expressions": len(custom),
        },
        "meta": meta,
    }


def audit(path):
    try:
        return audit_document(read_document(path))
    except (ValueError, OSError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "summary": {}}


def validate(path):
    report = audit(path)
    if not report["ok"]:
        raise RuntimeError("VRM validation failed: " + "; ".join(report["errors"]))
    return report
