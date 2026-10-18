import hashlib
import importlib
import json
import os
import re
import uuid
from pathlib import Path

import bpy

from .jsonio import read_object, write_object


PROJECT_KEY = "kkvrm_prepared_project"
SCHEMA_VERSION = 1


def environment(found):
    extensions, issues = {}, []
    for label, name in found.items():
        if not name:
            issues.append(f"missing extension: {label}")
            continue
        module = importlib.import_module(name)
        manifest = Path(module.__file__).parent / "blender_manifest.toml"
        content = manifest.read_bytes() if manifest.is_file() else b""
        match = re.search(rb'^version\s*=\s*"([^\"]+)"', content, re.MULTILINE)
        extensions[label] = {"module": name,
                             "version": match.group(1).decode() if match else str(getattr(module, "bl_info", {}).get("version", "unknown")),
                             "manifest_digest": hashlib.sha256(content).hexdigest()}
    capabilities = {}
    for label, operator in (("kkbp_import", bpy.ops.kkbp.kkbpimport),
                            ("kkbp_prep", bpy.ops.kkbp.exportprep), ("vrm_export", bpy.ops.export_scene.vrm)):
        try:
            operator.get_rna_type()
            capabilities[label] = True
        except (RuntimeError, AttributeError, KeyError):
            capabilities[label] = False
            issues.append(f"missing API: {label}")
    data = bpy.data.armatures.new("kkvrm_api_check")
    try:
        extension = getattr(data, "vrm_addon_extension", None)
        capabilities["spring_bone1"] = bool(extension and hasattr(extension, "spring_bone1"))
        capabilities["vrm1_metadata"] = bool(extension and hasattr(extension, "vrm1"))
        for capability in ("spring_bone1", "vrm1_metadata"):
            if not capabilities[capability]:
                issues.append(f"missing API: {capability}")
    finally:
        bpy.data.armatures.remove(data)
    scene = getattr(bpy.context.scene, "kkbp", None)
    for property_name in ("import_dir", "use_rigify", "prep_dropdown", "simp_dropdown"):
        key = f"kkbp_{property_name}"
        capabilities[key] = bool(scene and hasattr(scene, property_name))
        if not capabilities[key]:
            issues.append(f"missing KKBP property: {property_name}")
    return {"blender_version": bpy.app.version_string, "blender": bpy.app.binary_path,
            "extensions": extensions, "capabilities": capabilities, "issues": issues}


def environment_identity(report):
    return {"blender_version": report["blender_version"], "extensions": report["extensions"]}


def read_project():
    text = bpy.context.scene.get(PROJECT_KEY)
    if not isinstance(text, str):
        raise ValueError("not a KKVRM prepared model; convert once with --keep-blend")
    project = json.loads(text)
    if project.get("schema_version") != SCHEMA_VERSION or project.get("phase") != "prepared":
        raise ValueError("unsupported or export-modified prepared model")
    return project


def load_prepared(path):
    result = bpy.ops.wm.open_mainfile(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError(f"could not open prepared model: {path}")
    return read_project()


def usable_cache(path, key, current_environment):
    path = Path(path)
    manifest = path.with_suffix(".blend.json")
    if not path.is_file() or not manifest.is_file():
        return False
    try:
        project = read_object(manifest)
        stat = path.stat()
        return project.get("cache_key") == key and project.get("schema_version") == SCHEMA_VERSION \
            and project.get("phase") == "prepared" and project.get("environment") == environment_identity(current_environment) \
            and project.get("blend_size") == stat.st_size and project.get("blend_mtime_ns") == stat.st_mtime_ns
    except (OSError, ValueError):
        return False


def save_prepared(path, project):
    """Save a pristine, packed snapshot, before scale/offset/spring export changes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene[PROJECT_KEY] = json.dumps(project, ensure_ascii=False)
    bpy.ops.file.pack_all()
    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex}.blend")
    try:
        result = bpy.ops.wm.save_as_mainfile(filepath=str(temporary), copy=True, compress=True, check_existing=False)
        if "FINISHED" not in result:
            raise RuntimeError(f"could not save prepared model: {path}")
        os.replace(temporary, path)
        stat = path.stat()
        write_object(path.with_suffix(".blend.json"), dict(project, blend_size=stat.st_size, blend_mtime_ns=stat.st_mtime_ns))
    finally:
        temporary.unlink(missing_ok=True)
