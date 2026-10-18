"""Check packed textures/thumbnail without reading original export paths."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kkvrm.blender_project import load_prepared
from kkvrm.export_vrm import assign_materials, assign_meta, choose_armature, collect_meshes, enable_required, prepare_images, restore_thumbnail

enable_required()
argv = sys.argv[sys.argv.index("--") + 1:]
project = load_prepared(argv[0])
missing = Path(argv[0]).parent / "missing-original-export"
assert not missing.exists()
for image in bpy.data.images:
    if image.packed_file:
        image.filepath = str(missing / image.name)
project["import_dir"] = str(missing)
args = {"meta": project["settings"]["meta"]}
restore_thumbnail(project, args)
armature = choose_armature()
meshes = collect_meshes(armature, False)
prepare_images(meshes, missing, project["sources"], writable_folder=Path(argv[0]).parent)
materials = assign_materials(meshes, missing, project["settings"]["options"], project["sources"])
assign_meta(armature, args)
masked = [material for material in materials.values() if material["alpha_mode"] == "MASK"]
assert masked and all(material["texture"] for material in masked)
assert all(bpy.data.images[material["texture"]].packed_file for material in masked)
assert armature.data.vrm_addon_extension.vrm1.meta.thumbnail_image.size[0] > 32
print("KKVRM_PORTABILITY_OK: cleaned alpha images and portrait survive missing source paths")
