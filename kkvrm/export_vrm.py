import argparse
import fnmatch
import hashlib
import io
import json
import re
import sys
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kkvrm.bones import REQUIRED, match_humanoid
from kkvrm.blender_physics import apply_physics, inventory
from kkvrm.blender_project import environment, environment_identity, load_prepared, read_project, save_prepared, usable_cache
from kkvrm.defaults import BUST_LIFT, HEIGHT_MAX, HEIGHT_MIN, SPRINGS_DEFAULT, TARGET_HEIGHT
from kkvrm.expressions import PRESETS as EXPRESSION_PRESETS, choose_presets
from kkvrm.meta import DEFAULTS
from kkvrm.locate import find_card
from kkvrm.options import validate_options
from kkvrm.physics import plan_physics
from kkvrm.physics_sources import load_sources
from kkvrm.shaders import bust_clothing, is_eye_card, is_skin, lookup_shader, shader_is_alpha, shader_map

RESULT_PREFIX = "KKVRM_RESULT "
STARTED = time.monotonic()


def progress(stage):
    print("KKVRM_PROGRESS " + json.dumps({"stage": stage, "elapsed_seconds": round(time.monotonic() - STARTED, 3)}), flush=True)


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


def enable_required(required=True):
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
    if missing and required:
        known = sorted(name for name in installed if any(part in name for part in ("kkbp", "mmd", "vrm")))
        fail(
            "Blender is missing add-ons: "
            + ", ".join(missing)
            + ". Install KKBP Importer, mmd_tools, and the VRM add-on, then enable them. Found: "
            + (", ".join(known) or "none")
        )
    if found["kkbp"]:
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
        found, missing = match_humanoid(bone.name for bone in obj.data.bones)
        return len(REQUIRED) - len(missing), len(found)

    armatures.sort(key=score, reverse=True)
    if score(armatures[0])[0] == 0:
        fail("armature has no KKBP humanoid bones")
    return armatures[0]


def collect_meshes(armature, include_hidden, options=None):
    options = options or {}
    meshes = []
    seen_outfits = set()
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
        match = re.search(r"outfit\s+(\d+)", obj.name, re.IGNORECASE)
        if match:
            seen_outfits.add(int(match.group(1)))
            if options.get("outfit") is not None and int(match.group(1)) != options["outfit"]:
                continue
        if options.get("include_mesh") and not any(fnmatch.fnmatchcase(obj.name.lower(), pattern.lower()) for pattern in options["include_mesh"]):
            continue
        if any(fnmatch.fnmatchcase(obj.name.lower(), pattern.lower()) for pattern in options.get("exclude_mesh", [])):
            continue
        meshes.append(obj)
    if options.get("outfit") is not None and seen_outfits and options["outfit"] not in seen_outfits:
        fail(f"outfit {options['outfit']} not found; available: {sorted(seen_outfits)}")
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


def normalize_height(armature, meshes, policy="auto"):
    object_mode()
    height = world_height(meshes)
    if height <= 0.001 or policy == "keep" or (policy == "auto" and HEIGHT_MIN <= height <= HEIGHT_MAX):
        return height
    factor = (TARGET_HEIGHT if policy == "auto" else float(policy)) / height
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


def lift_bust_clothing(meshes, distance=BUST_LIFT, material_patterns=()):
    import numpy

    corrections = []
    if not distance or distance <= 0:
        return corrections
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
        normals = [vertex.normal.copy() for vertex in mesh.vertices]
        allowed = set()
        for polygon in mesh.polygons:
            material = obj.material_slots[polygon.material_index].material if polygon.material_index < len(obj.material_slots) else None
            if material is None or is_skin(material.name) or is_eye_card(material.name):
                continue
            if not material_patterns or any(fnmatch.fnmatchcase(material.name.lower(), pattern.lower()) for pattern in material_patterns):
                allowed.update(polygon.vertices)
        inverse = obj.matrix_world.to_3x3().inverted()
        normal_transform = inverse.transposed()
        moved = 0
        offsets = numpy.zeros((len(mesh.vertices), 3), dtype=numpy.float32)
        for vert in mesh.vertices:
            if vert.index not in allowed:
                continue
            weight = 0.0
            for element in vert.groups:
                if element.group in groups:
                    weight += element.weight
            if weight > 0.15:
                world_normal = normal_transform @ normals[vert.index]
                if world_normal.length < 1e-6:
                    continue
                delta = inverse @ (world_normal.normalized() * distance * min(weight, 1.0))
                offsets[vert.index] = delta
                moved += 1
        if moved:
            indices = numpy.flatnonzero(numpy.any(offsets != 0, axis=1))
            coordinates = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float32)
            if mesh.shape_keys:
                for block in mesh.shape_keys.key_blocks:
                    block.data.foreach_get("co", coordinates)
                    coordinates.reshape((-1, 3))[indices] += offsets[indices]
                    block.data.foreach_set("co", coordinates)
                mesh.shape_keys.key_blocks[0].data.foreach_get("co", coordinates)
            else:
                mesh.vertices.foreach_get("co", coordinates)
                coordinates.reshape((-1, 3))[indices] += offsets[indices]
            mesh.vertices.foreach_set("co", coordinates)
        mesh.update()
        if moved:
            corrections.append({"mesh": obj.name, "vertices": moved, "offset_meters": distance,
                                "shape_keys_updated": len(mesh.shape_keys.key_blocks) if mesh.shape_keys else 0})
    return corrections


def fix_normals(meshes):
    object_mode()
    for obj in meshes:
        if not in_view_layer(obj):
            continue
        if not obj.data.has_custom_normals:
            obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            # This operator polls in OBJECT mode; EDIT mode silently failed before.
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception as exc:
            print(f"normals skip {obj.name}: {exc}")
            object_mode()
            continue
        obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))


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
        node = getattr(human_bones, slot).node
        if node.bone_name != bone_name:
            node.bone_name = bone_name
    extension.vrm1.look_at.type = "bone"
    return found


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


def prepare_images(meshes, folder, sources, writable_folder=None):
    shaders = sources.get("shaders", {})
    prepared = set()
    for obj in meshes:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in prepared:
                continue
            prepared.add(material.name)
            light = image_from_node(material, "_light.png") or bpy.data.images.get(material.get("kkvrm_light_image", ""))
            path = image_file(light)
            shader = lookup_shader(material.name, material.get("id"), shaders)
            mode = material.get("kkvrm_default_alpha_mode") or ("BLEND" if is_eye_card(material.name) else "OPAQUE" if is_skin(material.name) else \
                "MASK" if path is not None and (shader_is_alpha(shader) or texture_has_cutout(path)) else "OPAQUE")
            material["kkvrm_default_alpha_mode"] = mode
            if light:
                material["kkvrm_light_image"] = light.name
            mask = bpy.data.images.get(material.get("kkvrm_mask_image", ""))
            if mode == "MASK" and mask:
                mask.use_fake_user = True
            elif mode == "MASK" and light:
                digest = hashlib.sha256(material.name.encode()).hexdigest()[:8]
                destination = (Path(writable_folder) / "textures" if writable_folder else Path(folder) / "kkvrm_baked") / f"{safe_name(material.name)}_{digest}_cloth.png"
                try:
                    source = io.BytesIO(bytes(light.packed_file.data)) if light.packed_file else path
                    if source is None:
                        raise ValueError("no source bytes for alpha cleanup")
                    cleaned = solidify_cloth_alpha(source, destination)
                    mask = load_srgb(cleaned)
                    mask.use_fake_user = True
                    material["kkvrm_mask_image"] = mask.name
                except Exception as exc:
                    sources.setdefault("warnings", []).append(f"alpha cleanup skipped for {material.name}: {exc}")


def assign_materials(meshes, folder, options=None, sources=None):
    options, sources = options or {}, sources or {}
    shaders = sources.get("shaders") or shader_map(folder)
    done = {}
    for obj in meshes:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name in done:
                continue
            light = image_from_node(material, "_light.png") or bpy.data.images.get(material.get("kkvrm_light_image", ""))
            base_image = light
            light_path = image_file(light)
            shader = lookup_shader(material.name, material.get("id"), shaders)
            overrides = {}
            for pattern, value in options.get("material_overrides", {}).items():
                if fnmatch.fnmatchcase(material.name.lower(), pattern.lower()):
                    overrides.update(value)
            if material.get("kkvrm_default_alpha_mode"):
                mode = material["kkvrm_default_alpha_mode"]
                cutoff = 0.5 if mode in ("BLEND", "MASK") else 1.0
                sided = True
            elif is_eye_card(material.name):
                mode = "BLEND"
                cutoff = 0.5
                sided = True
            elif is_skin(material.name):
                mode = "OPAQUE"
                cutoff = 1.0
                sided = True
            elif light_path is not None and (shader_is_alpha(shader) or texture_has_cutout(light_path)):
                mode = "MASK"
                cutoff = 0.5
                sided = True
            else:
                mode = "OPAQUE"
                cutoff = 1.0
                sided = True
            mode = overrides.get("alpha_mode", mode)
            cutoff = float(overrides.get("alpha_cutoff", cutoff))
            sided = overrides.get("double_sided", sided)
            if mode == "MASK":
                base_image = bpy.data.images.get(material.get("kkvrm_mask_image", "")) or base_image
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
            done[material.name] = {"alpha_mode": mode, "alpha_cutoff": cutoff, "double_sided": sided,
                                   "texture": base_image.name if base_image else None, "shader": shader}
    return done


def reset_shape_keys(meshes):
    for obj in meshes:
        shape_keys = obj.data.shape_keys
        if not shape_keys:
            continue
        if shape_keys.animation_data:
            shape_keys.animation_data_clear()
        for block in shape_keys.key_blocks:
            if block.value != 0:
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
    expressions.custom.clear()
    for name in EXPRESSION_PRESETS + ("neutral", "look_up", "look_down", "look_left", "look_right"):
        expression = getattr(expressions.preset, name, None)
        if expression:
            expression.morph_target_binds.clear()
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


def expression_signature(meshes):
    names = [(obj.name, [block.name for block in obj.data.shape_keys.key_blocks])
             for obj in meshes if obj.data.shape_keys]
    return hashlib.sha256(json.dumps(sorted(names), ensure_ascii=False).encode()).hexdigest()


def restore_thumbnail(project, args):
    image = bpy.data.images.get(project.get("thumbnail_image") or "")
    explicit = args.get("meta", {}).get("thumbnail") or args.get("thumbnail")
    if explicit and Path(explicit).is_file():
        image = bpy.data.images.load(explicit, check_existing=True)
    if image is None and project.get("thumbnail_image"):
        name = re.sub(r"\.\d{3}$", "", project["thumbnail_image"])
        candidate = Path(project["import_dir"]) / name
        if candidate.is_file():
            image = bpy.data.images.load(str(candidate), check_existing=True)
        elif not project["settings"]["meta"].get("thumbnail") and Path(project["import_dir"]).is_dir():
            card = find_card(project["import_dir"])
            if card:
                image = bpy.data.images.load(str(card), check_existing=True)
    if image:
        image.use_fake_user = True
        project["thumbnail_image"] = image.name
    elif project.get("thumbnail_image"):
        project["sources"].setdefault("warnings", []).append("prepared thumbnail is unavailable; regenerate the packed snapshot")
    args["packed_thumbnail"] = project.get("thumbnail_image")


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
    meta.authors.clear()
    meta.references.clear()
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
    elif args.get("packed_thumbnail") and bpy.data.images.get(args["packed_thumbnail"]):
        meta.thumbnail_image = bpy.data.images[args["packed_thumbnail"]]
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
        action = args.get("action", "convert")
        progress("Checking Blender extensions")
        found = enable_required(required=action != "check")
        current_environment = environment(found)
        if action == "check":
            emit(dict(current_environment, ok=not current_environment["issues"]))
            return
        if current_environment["issues"]:
            fail("; ".join(current_environment["issues"]))
        project, cache_hit = None, False
        cache_path = args.get("cache_path")
        if action in ("reexport", "describe"):
            progress("Opening prepared model")
            project = load_prepared(args["blend_input"])
        elif cache_path and usable_cache(cache_path, args.get("cache_key"), current_environment):
            progress("Loading prepared cache")
            project = load_prepared(cache_path)
            cache_hit = True
        if action == "describe":
            emit({"ok": True, "project": read_project()})
            return
        options = validate_options(args.get("options") or {
            "sfw": bool(args.get("sfw")), "include_hidden": bool(args.get("include_hidden")),
            "keep_blend": bool(args.get("keep_blend")), "bust_lift": args.get("bust_lift", BUST_LIFT),
        })
        if not args.get("springs", True):
            options["physics"]["types"] = {kind: False for kind in options["physics"]["types"]}
        if project is None:
            progress("Importing KKBP character")
            import_character(dict(args, sfw=options["sfw"]))
            progress("Preparing humanoid rig")
            prepped = prep_character()
            sources = load_sources(args["import_dir"])
            sources["shaders"] = shader_map(args["import_dir"])
            if not prepped:
                sources["warnings"].append("KKBP prep did not finish; rig/physics coverage requires review")
        else:
            prepped = project["prepped"]
            sources = project["sources"]
            args["import_dir"] = project["import_dir"]
            args["packed_thumbnail"] = project.get("thumbnail_image")
            if project["environment"] != environment_identity(current_environment):
                sources.setdefault("warnings", []).append("prepared model was created with different Blender/extension versions")
        object_mode()
        armature = choose_armature()
        meshes = collect_meshes(armature, options["include_hidden"], options)
        if action == "inspect":
            humanoid = assign_humanoid(armature)
            records, weights, _points = inventory(armature, meshes, sources)
            physics = plan_physics(records, options["physics"], sources, humanoid, weights, options["outfit"])
            for chain in physics["chains"]:
                chain.pop("data", None)
            emit({"ok": True, "prepped": prepped, "environment": current_environment,
                  "height": world_height(meshes), "humanoid": humanoid, "physics": physics,
                  "meshes": [obj.name for obj in meshes]})
            return
        if project is None:
            progress("Preparing texture images")
            all_meshes = collect_meshes(armature, True)
            prepare_images(all_meshes, Path(args["import_dir"]), sources)
            thumbnail = args.get("thumbnail") or args.get("meta", {}).get("thumbnail")
            thumbnail_image = bpy.data.images.load(thumbnail, check_existing=True) if thumbnail and Path(thumbnail).is_file() else None
            if thumbnail_image:
                thumbnail_image.use_fake_user = True
            project = {"schema_version": 1, "phase": "prepared", "prepped": prepped,
                       "import_dir": args["import_dir"], "sources": sources,
                       "environment": environment_identity(current_environment),
                       "thumbnail_image": thumbnail_image.name if thumbnail_image else None,
                       "settings": {"schema_version": 1, "options": options,
                                    "meta": args.get("meta") or dict(DEFAULTS, name=args.get("name", "Koikatsu"))},
                       "cache_key": args.get("cache_key")}
        else:
            # Repair pre-fake-user snapshots without depending on external texture paths.
            prepare_images(collect_meshes(armature, True), Path(args["import_dir"]), sources,
                           writable_folder=Path(args["output"]).parent)
        restore_thumbnail(project, args)
        progress("Preparing reusable normals and expressions")
        all_meshes = collect_meshes(armature, True)
        fix_normals(all_meshes)
        humanoid = assign_humanoid(armature)
        signature = expression_signature(meshes)
        if project.get("expression_signature") != signature:
            project["expressions"] = assign_expressions(armature, meshes)
            project["expression_signature"] = signature
        expressions = project["expressions"]
        if options["keep_blend"] or (cache_path and not cache_hit):
            progress("Saving packed prepared model")
            snapshot = dict(project, settings={"schema_version": 1, "options": options, "meta": args["meta"]})
            thumbnail = args.get("meta", {}).get("thumbnail") or args.get("thumbnail")
            if thumbnail and Path(thumbnail).is_file():
                image = bpy.data.images.load(thumbnail, check_existing=True)
                image.use_fake_user = True
                snapshot["thumbnail_image"] = image.name
                project["thumbnail_image"] = snapshot["thumbnail_image"]
            if cache_path and not cache_hit:
                save_prepared(cache_path, snapshot)
            if options["keep_blend"]:
                save_prepared(Path(args["output"]).with_suffix(".blend"), snapshot)
        args["packed_thumbnail"] = project.get("thumbnail_image")
        reset_shape_keys(meshes)
        progress("Applying geometry and scale options")
        original_height = world_height(meshes)
        height = normalize_height(armature, meshes, options["height"])
        scale_factor = height / original_height if original_height > 0.001 else 1.0
        strip_modifiers(meshes)
        fix_normals(meshes)
        corrections = lift_bust_clothing(meshes, options["bust_lift"], options["bust_materials"])
        humanoid = assign_humanoid(armature)
        progress("Building spring chains and colliders")
        physics = apply_physics(armature, meshes, options["physics"], sources, humanoid,
                                scale_factor=scale_factor, height=height, outfit=options["outfit"])
        progress("Assigning MToon materials and expressions")
        materials = assign_materials(meshes, Path(args["import_dir"]), options, sources)
        assign_meta(armature, args)
        progress("Exporting VRM 1.0")
        export_vrm(armature, meshes, args)
        emit(
            {
                "ok": True,
                "output": args["output"],
                "height": height,
                "prepped": prepped,
                "bones": len(humanoid),
                "springs": len(physics["chains"]),
                "physics": physics,
                "colliders": physics["collider_count"],
                "materials": len(materials),
                "material_details": materials,
                "expressions": expressions,
                "meshes": [obj.name for obj in meshes],
                "corrections": corrections,
                "source_height": original_height,
                "scale_factor": scale_factor,
                "cache_hit": cache_hit,
                "cache_path": cache_path,
                "environment": current_environment,
            }
        )
    except SystemExit:
        raise
    except Exception:
        fail(traceback.format_exc())


if __name__ == "__main__":
    main()
