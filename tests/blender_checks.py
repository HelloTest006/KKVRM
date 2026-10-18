"""Explicit Blender integration checks; not imported by unittest discovery."""

import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkvrm.blender_physics import apply_physics
from kkvrm.export_vrm import enable_required, fix_normals, lift_bust_clothing


enable_required()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()

mesh = bpy.data.meshes.new("cloth test")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
obj = bpy.data.objects.new("Outfit test", mesh)
bpy.context.collection.objects.link(obj)
obj.data.materials.append(bpy.data.materials.new("test cloth"))
obj.scale = (2, 3, 4)
obj.vertex_groups.new(name="cf_j_bust02_L").add([0, 1, 2, 3], 1.0, "REPLACE")
basis = obj.shape_key_add(name="Basis")
expression = obj.shape_key_add(name="cloth expression")
expression.data[0].co.x += 0.1
bpy.context.view_layer.update()
mesh.normals_split_custom_set([(0, 0, 1)] * len(mesh.loops))
assert mesh.has_custom_normals
fix_normals([obj])
assert not mesh.has_custom_normals
before = [vertex.co.copy() for vertex in basis.data]
delta_before = expression.data[0].co - basis.data[0].co
corrections = lift_bust_clothing([obj], distance=0.006)
assert corrections[0]["vertices"] == 4
assert abs((obj.matrix_world.to_3x3() @ (basis.data[0].co - before[0])).length - 0.006) < 1e-6
assert ((expression.data[0].co - basis.data[0].co) - delta_before).length < 1e-6

data = bpy.data.armatures.new("physics test")
armature = bpy.data.objects.new("physics test", data)
bpy.context.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
for name, parent, head, tail in (
    ("Hips", None, (0, 0, 0.8), (0, 0, 1)),
    ("Chest", "Hips", (0, 0, 1), (0, 0, 1.3)),
    ("Head", "Chest", (0, 0, 1.3), (0, 0, 1.5)),
    ("ribbon_A", "Chest", (0, 0.05, 1.1), (0, 0.05, 1)),
    ("ribbon_tail", "ribbon_A", (0, 0.05, 1), (0, 0.05, 0.9)),
    ("cf_hit_head", "Head", (0, 0, 1.4), (0, 0, 1.5)),
):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = head, tail
    if parent:
        bone.parent = data.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")
obj.vertex_groups.new(name="ribbon_A").add([0, 1, 2, 3], 1.0, "REPLACE")
humanoid = {"hips": "Hips", "chest": "Chest", "head": "Head"}
source = {"renderers": [], "dynamics": [], "bone_transforms": {}, "colliders": []}
config = {"preset": "balanced", "colliders": "auto", "chains": [
    {"category": "cloth", "bones": ["ribbon_A", "ribbon_tail"]},
]}
result = apply_physics(armature, [obj], config, source, humanoid)
assert result["counts"]["cloth"] == 1
assert result["collider_count"] >= 2
assert all(spec["radius"] > 0 for spec in result["collider_specs"])
obj.vertex_groups.new(name="ribbon_tail").add([0, 1, 2, 3], 1.0, "REPLACE")
result = apply_physics(armature, [obj], config, source, humanoid)
count = len(data.bones)
assert result["chains"][0]["endpoint"] is not None
apply_physics(armature, [obj], config, source, humanoid)
assert len(data.bones) == count

matrix = Matrix.Translation(Vector((0, 0, 1.4)))
source["bone_transforms"]["cf_hit_head"] = {"worldTransform": [value for row in matrix for value in row]}
source["colliders"] = [
    {"Name": "cf_hit_head", "Radius": 0.04, "Height": 0, "Direction": 1, "Bound": 0,
     "Center": {"x": 0, "y": 0.02, "z": 0}, "LossyScale": {"x": 1, "y": 1, "z": 1}},
    {"Name": "floor", "Radius": 100, "Height": 0, "Bound": 0},
]
config["colliders"] = "source"
config["chains"][0]["colliders"] = ["cf_hit_head", "floor"]
result = apply_physics(armature, [obj], config, source, humanoid, scale_factor=2, height=3.2)
assert result["collider_count"] == 1
spec = result["collider_specs"][0]
assert abs(spec["radius"] - 0.08) < 1e-6
world = armature.matrix_world @ data.bones[spec["bone"]].matrix_local @ Vector(spec["offset"])
assert (world - Vector((0, 0, 2.84))).length < 1e-5
assert any("floor" in warning for warning in result["warnings"])
print("KKVRM_BLENDER_CHECKS_OK: metric offsets, morph deltas, auto/source colliders")
