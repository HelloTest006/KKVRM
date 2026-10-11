import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kkvrm.bones import SPRING, match_humanoid, spring_chains
from kkvrm.defaults import BUST_LIFT, HEIGHT_MAX, HEIGHT_MIN, SPRINGS_DEFAULT, TARGET_HEIGHT
from kkvrm.expressions import choose_presets
from kkvrm.meta import DEFAULTS
from kkvrm.shaders import bust_clothing, is_eye_card, is_skin, lookup_shader, shader_is_alpha, shader_map

RESULT_PREFIX = "KKVRM_RESULT "


def emit(payload):
    print(RESULT_PREFIX + json.dumps(payload), flush=True)


def fail(message):
    emit({"ok": False, "error": message})
    raise SystemExit(1)


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--args", required=True)
    parsed = parser.parse_args(argv)
    return json.loads(Path(parsed.args).read_text(encoding="utf-8"))


def installed_modules():
    import addon_utils

    names = set()
    try:
        modules = addon_utils.modules(refresh=True)
    except TypeError:
        modules = addon_utils.modules()
    for module in modules:
        name = getattr(module, "__name__", "")
        if name:
            names.add(name)
    return names


def enable(module_names, installed):
    for name in module_names:
        try:
            already = name in bpy.context.preferences.addons
        except Exception:
            already = False
        if already:
            return name
        if name not in installed:
            continue
        try:
            result = bpy.ops.preferences.addon_enable(module=name)
        except Exception as exc:
            print(f"could not enable {name}: {exc}")
            continue
        if result and "FINISHED" in result:
            return name
    return None


def enable_required():
    installed = installed_modules()
    found = {
        "mmd_tools": enable(
            ["bl_ext.blender_org.mmd_tools", "bl_ext.user_default.mmd_tools"],
            installed,
        ),
        "kkbp": enable(
            ["bl_ext.user_default.kkbp", "bl_ext.blender_org.kkbp"],
            installed,
        ),
        "vrm": enable(
            ["bl_ext.blender_org.vrm", "bl_ext.user_default.vrm"],
            installed,
        ),
    }
    missing = [name for name, module in found.items() if not module]
    if missing:
        known = sorted(name for name in installed if any(part in name for part in ("kkbp", "mmd", "vrm")))
        fail(
            "Blender is missing add-ons: "
            + ", ".join(missing)
            + ". Install KKBP Importer, mmd_tools, and the VRM add-on, then enable them. Found: "
            + (", ".join(known) or "none")
        )
    silence_console(found["kkbp"])
    return found


def silence_console(module_name):
    import importlib

    common = importlib.import_module(module_name + ".common")

    def noop():
        return None

    common.toggle_console = noop


def set_prop(scene, name, value, required=False):
    if not hasattr(scene, name):
        if required:
            fail(f"KKBP panel has no '{name}'")
        print(f"KKBP panel has no '{name}', skipped")
        return
    setattr(scene, name, value)


def import_character(args):
    if not hasattr(bpy.context.scene, "kkbp"):
        fail("KKBP Importer is not loaded")
    scene = bpy.context.scene.kkbp
    set_prop(scene, "import_dir", args["import_dir"], required=True)
    set_prop(scene, "shader_dropdown", "A")
    set_prop(scene, "use_rigify", False, required=True)
    set_prop(scene, "sfw_mode", bool(args.get("sfw")))
    set_prop(scene, "fix_seams", True)
    set_prop(scene, "use_outline", False)
    set_prop(scene, "separate_clothes", False)
    result = bpy.ops.kkbp.kkbpimport("EXEC_DEFAULT")
    if not result or "FINISHED" not in result:
        fail(f"KKBP import failed: {result}")


def prep_character():
    scene = bpy.context.scene.kkbp
    set_prop(scene, "prep_dropdown", "VRM", required=True)
    set_prop(scene, "simp_dropdown", "C", required=True)
    set_prop(scene, "atlas_dropdown", "None")
    try:
        result = bpy.ops.kkbp.exportprep("EXEC_DEFAULT")
    except Exception as exc:
        print(f"KKBP VRM prep error: {exc}")
        return False
    if not result or "FINISHED" not in result:
        print(f"KKBP VRM prep did not finish: {result}")
        return False
    return True


def object_mode():
    active = bpy.context.view_layer.objects.active
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def is_hitbox(obj):
    name = obj.name.lower()
    if "hitbox" in name or "cf_hit" in name or "o_hit" in name:
        return True
    for collection in obj.users_collection:
        lowered = collection.name.lower()
        if "hitbox" in lowered or lowered.startswith("hit"):
            return True
    return False


def is_hidden(obj):
    return bool(obj.hide_render or obj.hide_viewport or obj.hide_get())


def in_view_layer(obj):
    return obj.name in bpy.context.view_layer.objects


def attached(obj, armature):
    cursor = obj
    seen = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        for modifier in getattr(cursor, "modifiers", []):
            if modifier.type == "ARMATURE" and modifier.object == armature:
                return True
        if cursor.parent == armature:
            return True
        cursor = cursor.parent
    return False


def choose_armature():
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if not armatures:
        fail("KKBP import created no armature")

    def score(obj):
        names = {bone.name for bone in obj.data.bones}
        return int("Hips" in names) + int("Head" in names) + int("Left arm" in names)

    armatures.sort(key=score, reverse=True)
    if score(armatures[0]) == 0:
        fail("armature has no KKBP humanoid bones")
    return armatures[0]


def collect_meshes(armature, include_hidden):
    meshes = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not attached(obj, armature):
            continue
        if is_hitbox(obj):
            continue
        if not include_hidden and (is_hidden(obj) or not in_view_layer(obj)):
            continue
        if not in_view_layer(obj):
            print(f"skip {obj.name}: hidden collection")
            continue
        meshes.append(obj)
    if not meshes:
        fail("no meshes to export")
    return meshes


def world_height(meshes):
    low = None
    high = None
    for obj in meshes:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            low = point.z if low is None else min(low, point.z)
            high = point.z if high is None else max(high, point.z)
    if low is None:
        return 0.0
    return high - low


def normalize_height(armature, meshes):
    object_mode()
    height = world_height(meshes)
    if height <= 0.001 or HEIGHT_MIN <= height <= HEIGHT_MAX:
        return height
    factor = TARGET_HEIGHT / height
    armature.scale = tuple(axis * factor for axis in armature.scale)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.context.view_layer.update()
    return world_height(meshes)


def strip_modifiers(meshes):
    for obj in meshes:
        for modifier in list(obj.modifiers):
            if modifier.type != "ARMATURE":
                obj.modifiers.remove(modifier)


def lift_bust_clothing(meshes, distance=BUST_LIFT):
    if not distance or distance <= 0:
        return
    for obj in meshes:
        if not bust_clothing(obj.name):
            continue
        groups = {
            group.index
            for group in obj.vertex_groups
            if "bust" in group.name.lower() and not group.name.lower().startswith("cf_s_")
        }
        if not groups:
            continue
        mesh = obj.data
        mesh.update()
        for vert in mesh.vertices:
            weight = 0.0
            for element in vert.groups:
                if element.group in groups:
                    weight += element.weight
            if weight > 0.15:
                vert.co += vert.normal * distance * min(weight, 1.0)
        mesh.update()


def fix_normals(meshes):
    object_mode()
    for obj in meshes:
        if not in_view_layer(obj):
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            try:
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
            except Exception:
                pass
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            print(f"normals skip {obj.name}: {exc}")
            object_mode()
            continue
        for poly in obj.data.polygons:
            poly.use_smooth = True


def assign_humanoid(armature):
    extension = armature.data.vrm_addon_extension
    extension.spec_version = "1.0"
    humanoid = extension.vrm1.humanoid
    humanoid.pose = "restPositionPose"
    human_bones = humanoid.human_bones
    human_bones.filter_by_human_bone_hierarchy = False
    human_bones.initial_automatic_bone_assignment = False
    human_bones.allow_non_humanoid_rig = False
    found, missing = match_humanoid(bone.name for bone in armature.data.bones)
    if missing:
        fail("missing required bones: " + ", ".join(missing))
    for slot, bone_name in found.items():
        getattr(human_bones, slot).node.bone_name = bone_name
    extension.vrm1.look_at.type = "bone"
    return found


def assign_springs(armature, used_bones, centers):
    pairs = [
        (bone.name, bone.parent.name if bone.parent else None) for bone in armature.data.bones
    ]
    count = 0
    extension = armature.data.vrm_addon_extension
    for index, (kind, chain) in enumerate(spring_chains(pairs, skip=used_bones)):
        settings = SPRING[kind]
        spring = extension.spring_bone1.springs.add()
        spring.vrm_name = f"{kind}_{index}"
        center_name = centers.get(kind) if isinstance(centers, dict) else centers
        if center_name:
            spring.center.bone_name = center_name
        for bone_name in chain:
            joint = spring.joints.add()
            joint.node.bone_name = bone_name
            joint.hit_radius = settings["hit_radius"]
            joint.stiffness = settings["stiffness"]
            joint.gravity_power = settings["gravity_power"]
            joint.gravity_dir = (0.0, 0.0, -1.0)
            joint.drag_force = settings["drag_force"]
        count += 1
    return count


def usable_image(image):
    if image is None or image.size[0] == 0 or image.size[1] == 0:
        return False
    name = image.name.lower()
    if "placeholder" in name or name.startswith("template"):
        return False
    return True


def image_from_node(material, node_name):
    if not material or not material.node_tree:
        return None
    node = material.node_tree.nodes.get(node_name)
    image = getattr(node, "image", None) if node else None
    if usable_image(image):
        return image
    return None


def image_file(image):
    if image is None or not image.filepath:
        return None
    path = Path(bpy.path.abspath(image.filepath))
    if path.is_file():
        return path
    return None


def safe_name(text):
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    return cleaned[:80] or "material"


def solidify_cloth_alpha(src, dest):
    import numpy
    from PIL import Image

    image = Image.open(src).convert("RGBA")
    pixels = numpy.array(image)
    rgb_sum = pixels[:, :, :3].astype(numpy.int16).sum(axis=2)
    alpha = pixels[:, :, 3]
    visible = (alpha >= 128) | (rgb_sum >= 24)
    pixels[:, :, 3] = numpy.where(visible, 255, 0).astype(numpy.uint8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, "RGBA").save(dest)
    return dest


def texture_has_cutout(path):
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    image.thumbnail((64, 64))
    histogram = image.getchannel("A").histogram()
    total = sum(histogram) or 1
    clear = sum(histogram[:16]) / total
    solid = sum(histogram[240:]) / total
    return clear > 0.08 and solid > 0.05


def load_srgb(path):
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    return image


def assign_materials(meshes, folder):
    shaders = shader_map(folder)
    done = {}
    for obj in meshes:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in done:
                continue
            light = image_from_node(material, "_light.png")
            base_image = light
            light_path = image_file(light)
            shader = lookup_shader(material.name, material.get("id"), shaders)
            if is_eye_card(material.name):
                mode = "BLEND"
                cutoff = 0.5
                sided = True
            elif is_skin(material.name):
                mode = "OPAQUE"
                cutoff = 1.0
                sided = True
            elif light_path is not None and (shader_is_alpha(shader) or texture_has_cutout(light_path)):
                dest = Path(folder) / "kkvrm_baked" / (safe_name(material.name) + "_cloth.png")
                try:
                    cleaned = solidify_cloth_alpha(light_path, dest)
                    base_image = load_srgb(cleaned)
                except Exception as exc:
                    print(f"cloth alpha skip {material.name}: {exc}")
                mode = "MASK"
                cutoff = 0.5
                sided = True
            else:
                mode = "OPAQUE"
                cutoff = 1.0
                sided = True
            mtoon = material.vrm_addon_extension.mtoon1
            mtoon.enabled = True
            gltf = mtoon
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            if hasattr(gltf.pbr_metallic_roughness, "metallic_factor"):
                gltf.pbr_metallic_roughness.metallic_factor = 0.0
            if hasattr(gltf.pbr_metallic_roughness, "roughness_factor"):
                gltf.pbr_metallic_roughness.roughness_factor = 1.0
            if base_image is not None:
                gltf.pbr_metallic_roughness.base_color_texture.index.source = base_image
            shade = gltf.extensions.vrmc_materials_mtoon
            shade.shade_color_factor = (1.0, 1.0, 1.0)
            shade.shading_toony_factor = 0.0
            if hasattr(shade, "shading_shift_factor"):
                shade.shading_shift_factor = 1.0
            shade.gi_equalization_factor = 0.0
            shade.outline_width_mode = "none"
            gltf.alpha_mode = mode
            gltf.alpha_cutoff = cutoff
            gltf.double_sided = sided
            done[material.name] = mode
    return done


def reset_shape_keys(meshes):
    for obj in meshes:
        shape_keys = obj.data.shape_keys
        if not shape_keys:
            continue
        if shape_keys.animation_data:
            shape_keys.animation_data_clear()
        for block in shape_keys.key_blocks:
            block.value = 0.0
        obj.active_shape_key_index = 0


def assign_expressions(armature, meshes):
    reset_shape_keys(meshes)
    grouped = {}
    for obj in meshes:
        shape_keys = obj.data.shape_keys
        if not shape_keys:
            continue
        for block in shape_keys.key_blocks:
            if block.name == "Basis":
                continue
            grouped.setdefault(block.name, []).append(obj)
    chosen = choose_presets(grouped)
    expressions = armature.data.vrm_addon_extension.vrm1.expressions
    presets = 0
    custom = 0
    seen_custom = {}
    for key_name, objects in grouped.items():
        slot = chosen.get(key_name)
        if slot:
            expression = getattr(expressions.preset, slot)
            presets += 1
        else:
            expression = seen_custom.get(key_name)
            if expression is None:
                expression = expressions.custom.add()
                expression.custom_name = key_name[:64]
                seen_custom[key_name] = expression
                custom += 1
        for obj in objects:
            bind = expression.morph_target_binds.add()
            bind.node.mesh_object_name = obj.name
            bind.index = key_name
            bind.weight = 1.0
    return {"shape_keys": len(grouped), "preset_binds": presets, "custom": custom}


def _put(obj, name, value):
    if hasattr(obj, name):
        setattr(obj, name, value)


def assign_meta(armature, args):
    meta = armature.data.vrm_addon_extension.vrm1.meta
    info = args.get("meta") or {}
    fields = dict(DEFAULTS)
    fields.update(info)
    _put(meta, "vrm_name", fields["name"] or args.get("name") or "Koikatsu")
    _put(meta, "version", fields["version"] or "1.0.0")
    for value in fields["authors"] or ["KKVRM"]:
        meta.authors.add().value = value
    _put(meta, "copyright_information", fields["copyright"])
    _put(meta, "contact_information", fields["contact"])
    for value in fields["references"]:
        meta.references.add().value = value
    _put(meta, "third_party_licenses", fields["license"])
    _put(meta, "avatar_permission", fields["avatar_permission"])
    _put(meta, "allow_excessively_violent_usage", bool(fields["allow_violent"]))
    _put(meta, "allow_excessively_sexual_usage", bool(fields["allow_sexual"] or args.get("sexual_ok")))
    _put(meta, "commercial_usage", fields["commercial_usage"])
    _put(meta, "allow_political_or_religious_usage", bool(fields["allow_political"]))
    _put(meta, "allow_antisocial_or_hate_usage", bool(fields["allow_antisocial"]))
    _put(meta, "credit_notation", fields["credit"])
    _put(meta, "allow_redistribution", bool(fields["allow_redistribution"]))
    _put(meta, "modification", fields["modification"])
    _put(meta, "other_license_url", fields["license_url"])
    thumbnail = fields["thumbnail"] or args.get("thumbnail")
    if thumbnail and Path(thumbnail).is_file():
        meta.thumbnail_image = bpy.data.images.load(thumbnail)
    else:
        meta.thumbnail_image = bpy.data.images.new("kkvrm_thumb", 32, 32, alpha=True)


def export_vrm(armature, meshes, args):
    object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes + [armature]:
        if not in_view_layer(obj):
            print(f"skip export {obj.name}: not in view layer")
            continue
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    output = str(Path(args["output"]))
    result = bpy.ops.export_scene.vrm(
        filepath=output,
        export_only_selections=True,
        export_invisibles=False,
        export_all_influences=True,
        use_addon_preferences=False,
        armature_object_name=armature.name,
    )
    if not result or "FINISHED" not in result:
        fail(f"VRM export failed: {result}")
    if not Path(output).is_file():
        fail("VRM export reported success but the file is missing")


def main():
    args = parse_args()
    try:
        enable_required()
        import_character(args)
        prepped = prep_character()
        object_mode()
        armature = choose_armature()
        meshes = collect_meshes(armature, bool(args.get("include_hidden")))
        height = normalize_height(armature, meshes)
        strip_modifiers(meshes)
        fix_normals(meshes)
        lift_bust_clothing(meshes, float(args.get("bust_lift", BUST_LIFT)))
        humanoid = assign_humanoid(armature)
        springs = 0
        if args.get("springs", SPRINGS_DEFAULT):
            springs = assign_springs(
                armature,
                set(humanoid.values()),
                {
                    "bust": humanoid.get("chest") or humanoid.get("upper_chest") or humanoid.get("hips"),
                    "hair": humanoid.get("head") or humanoid.get("hips"),
                    "skirt": humanoid.get("hips"),
                },
            )
        materials = assign_materials(meshes, Path(args["import_dir"]))
        expressions = assign_expressions(armature, meshes)
        assign_meta(armature, args)
        export_vrm(armature, meshes, args)
        if args.get("keep_blend"):
            blend = str(Path(args["output"]).with_suffix(".blend"))
            bpy.ops.wm.save_as_mainfile(filepath=blend)
        emit(
            {
                "ok": True,
                "output": args["output"],
                "height": height,
                "prepped": prepped,
                "bones": len(humanoid),
                "springs": springs,
                "materials": len(materials),
                "expressions": expressions,
                "meshes": [obj.name for obj in meshes],
            }
        )
    except SystemExit:
        raise
    except Exception:
        fail(traceback.format_exc())


if __name__ == "__main__":
    main()
