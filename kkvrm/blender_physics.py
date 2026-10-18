"""Apply a validated spring plan to the VRM add-on; all geometry uses metric Z-up."""

import fnmatch
import math

import bpy
from mathutils import Euler, Matrix, Vector

from .physics import CATEGORIES, plan_physics
from .physics_sources import renderer_category, vector
from .shaders import is_eye_card, is_skin


def bone_records(armature):
    records = []
    for bone in armature.data.bones:
        pose = armature.pose.bones.get(bone.name)
        mmd = getattr(pose, "mmd_bone", None)
        aliases = [getattr(mmd, "name_j", ""), getattr(mmd, "name_e", "")]
        records.append({"name": bone.name, "parent": bone.parent.name if bone.parent else None,
                        "aliases": [name for name in aliases if name],
                        "head": list(bone.head_local), "tail": list(bone.tail_local)})
    return records


def _resolver(records):
    names = {record["name"] for record in records}
    aliases = {}
    for record in records:
        for alias in [record["name"]] + record["aliases"]:
            aliases.setdefault(alias.casefold(), set()).add(record["name"])

    def resolve(name):
        if name in names:
            return name
        choices = aliases.get(str(name).casefold(), set())
        return next(iter(choices)) if len(choices) == 1 else None

    return resolve


def _material_kinds(material, sources):
    if material is None:
        return set()
    name = material.name
    original = material.get("id")
    if is_skin(name) or is_eye_card(name):
        return {"bust"}
    if "hair" in name.lower():
        return {"hair", "accessory"}
    matched = set()
    for renderer in sources.get("renderers", []):
        materials = renderer.get("SMRMaterialNames", [])
        if original in materials or any(name in (item, "KK " + item, "KKS " + item) for item in materials):
            category = renderer_category(renderer)
            if category:
                matched.add(category)
    if "hair" in matched:
        return {"hair", "accessory"}
    return {"cloth", "skirt", "accessory", "bust"}


def inventory(armature, meshes, sources):
    records = bone_records(armature)
    resolve = _resolver(records)
    weights = {kind: set() for kind in CATEGORIES}
    body_points = []
    material_kinds = {}
    for obj in meshes:
        group_names = {group.index: resolve(group.name) for group in obj.vertex_groups}
        vertices_by_kind = {kind: set() for kind in CATEGORIES}
        skin_vertices = set()
        for polygon in obj.data.polygons:
            material = obj.material_slots[polygon.material_index].material if polygon.material_index < len(obj.material_slots) else None
            key = material.name if material else ""
            if key not in material_kinds:
                material_kinds[key] = _material_kinds(material, sources)
            kinds = material_kinds[key]
            if material and is_skin(material.name):
                skin_vertices.update(polygon.vertices)
            for kind in kinds:
                vertices_by_kind[kind].update(polygon.vertices)
        for vertex in obj.data.vertices:
            names = {group_names.get(element.group) for element in vertex.groups if element.weight > 1e-5}
            names.discard(None)
            for kind in CATEGORIES:
                if vertex.index in vertices_by_kind[kind]:
                    weights[kind].update(names)
            if vertex.index in skin_vertices:
                body_points.append((obj.matrix_world @ vertex.co, names))
    return records, weights, body_points


def _source_matrix(item):
    values = item.get("worldTransform") if item else None
    if not isinstance(values, list) or len(values) != 16 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        return None
    return Matrix([values[index:index + 4] for index in range(0, 16, 4)])


def _unity_vector(value):
    x, y, z = vector(value)
    return Vector((x, -z, y))


def _add_endpoints(armature, plan, records, sources, scale_factor, height):
    helpers = [chain for chain in plan["chains"] if chain["endpoint"]]
    if not helpers:
        return
    record_map = {record["name"]: record for record in records}
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for chain in helpers:
            helper = chain["endpoint"]
            parent = armature.data.edit_bones[helper["parent"]]
            previous = armature.data.edit_bones.get(helper["previous"] or "")
            delta = parent.head - previous.head if previous else parent.tail - parent.head
            method = "rest-pose segment"
            offsets = chain.get("data", {}).get("ParticleEndOffset", [])
            particles = chain.get("data", {}).get("ParticleBones", [])
            if "NULL" in particles and isinstance(offsets, list):
                index = particles.index("NULL")
                offset = _unity_vector(offsets[index]) if index < len(offsets) else Vector()
                original = next((alias for alias in record_map[parent.name]["aliases"] + [parent.name]
                                 if alias in sources.get("bone_transforms", {})), None)
                source = _source_matrix(sources.get("bone_transforms", {}).get(original))
                if source and offset.length > 1e-6:
                    world = armature.matrix_world @ (source @ offset * scale_factor)
                    proposed = armature.matrix_world.inverted() @ world - parent.head
                    if 1e-5 < proposed.length < height * 0.25:
                        delta, method = proposed, "source virtual particle"
            if delta.length < 1e-5:
                delta = Vector((0, 0, -max(0.005, height * 0.015)))
            if delta.length > height * 0.2:
                delta = delta.normalized() * height * 0.05
            bone = armature.data.edit_bones.get(helper["name"])
            if bone and not bone.get("kkvrm_endpoint"):
                raise ValueError(f"generated endpoint name is already in use: {helper['name']}")
            if bone is None:
                bone = armature.data.edit_bones.new(helper["name"])
            bone.head = parent.head + delta
            bone.tail = bone.head + delta.normalized() * max(0.005, height * 0.005)
            bone.parent = parent
            bone.use_deform = False
            bone["kkvrm_endpoint"] = True
            helper.update(position=list(bone.head), method=method)
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def _auto_colliders(armature, humanoid, body_points, height):
    bones = armature.data.bones
    parents = {bone.name: bone.parent.name if bone.parent else None for bone in bones}

    def below(name, root):
        while name:
            if name == root:
                return True
            name = parents.get(name)
        return False

    specs = []
    regions = [
        ("head", None, 0.052, {"hair", "accessory"}),
        ("chest", "neck", 0.060, {"hair", "cloth", "accessory"}),
        ("hips", "spine", 0.065, {"cloth", "skirt", "accessory"}),
        ("left_upper_leg", "left_lower_leg", 0.035, {"cloth", "skirt"}),
        ("right_upper_leg", "right_lower_leg", 0.035, {"cloth", "skirt"}),
        ("left_shoulder", "left_upper_arm", 0.030, {"hair", "cloth", "accessory"}),
        ("right_shoulder", "right_upper_arm", 0.030, {"hair", "cloth", "accessory"}),
    ]
    all_human = set(humanoid.values())
    nearest = {name: next((ancestor for ancestor in _ancestors(name, parents) if ancestor in all_human), None)
               for name in parents}
    for slot, tail_slot, fraction, kinds in regions:
        name = humanoid.get(slot)
        if not name or name not in bones:
            continue
        bone = bones[name]
        world = armature.matrix_world @ bone.matrix_local
        start = armature.matrix_world @ bone.head_local
        other = bones.get(humanoid.get(tail_slot, "")) if tail_slot else None
        end = armature.matrix_world @ other.head_local if other else start + Vector((0, 0, height * 0.065))
        axis = end - start
        points = [point for point, groups in body_points
                  if name in groups or any(nearest.get(group) == name for group in groups)]
        radius = height * fraction
        fitted = False
        if axis.length > 1e-6 and points:
            direction = axis.normalized()
            distances = sorted((point - start - direction * (point - start).dot(direction)).length for point in points
                               if -height * 0.05 <= (point - start).dot(direction) <= axis.length + height * 0.05)
            if len(distances) >= 8:
                estimate = distances[int((len(distances) - 1) * 0.8)] * 0.8
                radius = max(height * fraction * 0.6, min(height * fraction * 1.25, estimate))
                fitted = True
        start += axis * 0.15
        end -= axis * 0.15
        inverse = world.inverted()
        specs.append({"name": f"kkvrm_{slot}", "bone": name, "shape": "Capsule",
                      "offset": list(inverse @ start), "tail": list(inverse @ end),
                      "radius": radius, "categories": sorted(kinds),
                      "fitted": fitted, "source": "auto"})
    return specs


def _ancestors(name, parents):
    found = []
    while name and name not in found:
        found.append(name)
        name = parents.get(name)
    return found


def _source_colliders(armature, records, sources, scale_factor, height, outfit, warnings):
    resolve = _resolver(records)
    transforms = sources.get("bone_transforms", {})
    basis = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
    specs = []
    for raw in sources.get("colliders", []):
        name = raw.get("Name", "")
        if not isinstance(name, str):
            continue
        if outfit is not None and raw.get("CoordinateType") not in (None, -1, outfit):
            continue
        try:
            radius, length = float(raw.get("Radius", 0)), float(raw.get("Height", 0))
            direction = int(raw.get("Direction", 1))
            if not math.isfinite(radius + length) or radius <= 0 or radius > 5 or length < 0 or direction not in (0, 1, 2) or raw.get("Bound", 0) != 0:
                raise ValueError("unsupported dimensions or inside/floor collider")
            original = name.removeprefix("KKS_Colliders_").split("__", 1)[0]
            target = resolve(name) or resolve(original)
            source = _source_matrix(transforms.get(name))
            if source is None and original in transforms:
                position = vector(transforms[original].get("worldPosition"))
                rotation = basis @ Euler([math.radians(value) for value in vector(raw.get("OffsetRotation"))], "ZXY").to_matrix() @ basis.inverted()
                scales = basis @ Matrix.Diagonal(Vector(vector(raw.get("LossyScale"), (1, 1, 1)))) @ basis.inverted()
                source = Matrix.Translation(position) @ (rotation @ scales).to_4x4()
            if not target or source is None:
                raise ValueError("source transform or target bone missing")
            scales = [abs(value) for value in vector(raw.get("LossyScale"), (1, 1, 1))]
            radius *= max(scales) * scale_factor
            if radius <= 0 or radius > height * 0.3:
                raise ValueError("collider exceeds model dimensions")
            center = _unity_vector(raw.get("Center"))
            axis = basis @ Vector([1 if index == direction else 0 for index in range(3)])
            half = max(0.0, length * 0.5 - float(raw["Radius"]))
            source_start = source @ (center - axis * half)
            source_end = source @ (center + axis * half)
            inverse = (armature.matrix_world @ armature.data.bones[target].matrix_local).inverted()
            start = inverse @ (armature.matrix_world @ (source_start * scale_factor))
            end = inverse @ (armature.matrix_world @ (source_end * scale_factor))
            specs.append({"name": name, "bone": target, "shape": "Capsule" if half else "Sphere",
                          "offset": list(start), "tail": list(end), "radius": radius,
                          "source": "KK_DynamicBoneColliderData", "categories": list(CATEGORIES)})
            if min(scales) > 0 and max(scales) / min(scales) > 1.05:
                warnings.append(f"{name}: nonuniform source collider approximated with a conservative radius")
        except (ValueError, TypeError, KeyError) as exc:
            warnings.append(f"collider {name} skipped: {exc}")
    return specs


def apply_physics(armature, meshes, config, sources, humanoid, scale_factor=1.0, height=1.6, outfit=None):
    records, weights, body_points = inventory(armature, meshes, sources)
    plan = plan_physics(records, config, sources, humanoid=humanoid, weighted=weights, outfit=outfit)
    extension = armature.data.vrm_addon_extension.spring_bone1
    for collider in extension.colliders:
        if collider.bpy_object:
            for child in list(collider.bpy_object.children):
                bpy.data.objects.remove(child, do_unlink=True)
            bpy.data.objects.remove(collider.bpy_object, do_unlink=True)
    extension.springs.clear()
    extension.collider_groups.clear()
    extension.colliders.clear()
    _add_endpoints(armature, plan, records, sources, scale_factor, height)
    mode = plan["config"]["colliders"]
    specs = _auto_colliders(armature, humanoid, body_points, height) if mode == "auto" else \
        _source_colliders(armature, records, sources, scale_factor, height, outfit, plan["warnings"]) if mode == "source" else []
    selected_specs, groups = {}, {}
    for chain in plan["chains"]:
        kind = chain["category"]
        selected = [index for index, spec in enumerate(specs)
                    if (kind in spec["categories"] if mode == "auto" else spec["name"] in chain["colliders"])]
        if mode == "auto" and kind == "bust":
            selected = []
        for index in selected:
            if index in selected_specs:
                continue
            spec = specs[index]
            collider = extension.add_collider(bpy.context, armature)
            collider.node.bone_name = spec["bone"]
            collider.shape_type = spec["shape"]
            collider.reset_bpy_object(bpy.context, armature)
            collider.bpy_object.name = spec["name"]
            shape = collider.shape.capsule if spec["shape"] == "Capsule" else collider.shape.sphere
            shape.offset = spec["offset"]
            if spec["shape"] == "Capsule":
                shape.tail = spec["tail"]
            shape.radius = spec["radius"]
            selected_specs[index] = collider.uuid
        key = tuple(selected)
        if key and key not in groups:
            group = extension.add_collider_group()
            group.vrm_name = f"kkvrm_{kind}_{len(groups)}"
            for index in selected:
                group.add_collider().collider_uuid = selected_specs[index]
            groups[key] = group.uuid
        spring = extension.add_spring()
        spring.vrm_name = chain["name"][:63]
        if chain["center"]:
            spring.center.bone_name = chain["center"]
        if key:
            spring.add_collider_group().collider_group_uuid = groups[key]
        for name, settings in zip(chain["bones"], chain["settings"]):
            joint = spring.add_joint()
            joint.node.bone_name = name
            for property_name, value in settings.items():
                setattr(joint, property_name, value)
        chain.pop("data", None)
    plan["collider_specs"] = [specs[index] for index in selected_specs]
    plan["collider_count"] = len(extension.colliders)
    plan["collider_group_count"] = len(extension.collider_groups)
    plan["weighted_bones"] = {kind: sorted(names) for kind, names in weights.items()}
    return plan
