"""Read KKBP physics provenance without importing Blender or guessing skin weights."""

import json
import math
from pathlib import Path

from .bones import spring_kind


def vector(value, default=(0.0, 0.0, 0.0)):
    if isinstance(value, dict):
        value = [value.get(axis, 0) for axis in "xyz"]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return list(default)
    try:
        result = [float(item) for item in value]
    except (ValueError, TypeError):
        return list(default)
    return result if all(math.isfinite(item) for item in result) else list(default)


def renderer_category(renderer):
    name = (str(renderer.get("SMRName", "")) + " " + str(renderer.get("SMRPath", ""))).lower()
    if "ct_hair" in name or "hair" in str(renderer.get("SMRName", "")).lower():
        return "hair"
    if any(token in name for token in ("ct_clothes", "ct_bra", "ct_shorts", "ct_socks", "ct_shoes")):
        return "cloth"
    if any(token in name for token in ("ct_accessory", "ca_slot", "accessory", "ct_acc")):
        return "accessory"
    return None


def classify_source(root, renderers):
    known = spring_kind(root)
    if known:
        return known, "bone-prefix"
    lowered = root.lower()
    if any(token in lowered for token in ("ribbon", "scarf", "cape", "cloth", "coat", "hem")):
        return "cloth", "bone-name"
    if lowered.startswith(("cf_", "cm_")):
        # A renderer's bone table often contains the entire body skeleton.
        return None, "body-or-helper"
    matches = {renderer_category(item) for item in renderers}
    if "hair" in matches:
        return "hair", "renderer"
    if "accessory" in matches:
        return "accessory", "renderer"
    if "cloth" in matches:
        return "cloth", "renderer"
    return None, "unclassified"


def _read_list(folder, filename, warnings):
    path = Path(folder) / filename
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8-sig")
        if not content.strip():
            warnings.append(f"empty sidecar: {filename}")
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError("expected an array")
    except (OSError, ValueError, UnicodeError) as exc:
        warnings.append(f"cannot read {filename}: {exc}")
        return []
    if any(not isinstance(item, dict) for item in data):
        warnings.append(f"ignored non-object entries in {filename}")
    return [item for item in data if isinstance(item, dict)]


def load_sources(folder):
    warnings = []
    renderers = _read_list(folder, "KK_SMRData.json", warnings)
    dynamics = []
    for index, item in enumerate(_read_list(folder, "KK_DynamicBoneData.json", warnings)):
        root = item.get("Root")
        if not isinstance(root, str) or not root:
            warnings.append(f"dynamic system {index} has no root")
            continue
        coordinate = item.get("CoordinateType")
        related = [renderer for renderer in renderers
                   if renderer.get("CoordinateType") in (coordinate, -1, None)
                   and root in (renderer.get("SMRBoneNames") or [])]
        category, evidence = classify_source(root, related)
        particle_names = item.get("ParticleBones") or [root]
        if not isinstance(particle_names, list):
            warnings.append(f"invalid ParticleBones for {root}")
            particle_names = [root]
        try:
            enabled = float(item.get("Weight", 1)) > 0
        except (ValueError, TypeError):
            enabled = False
        names = [name for name in particle_names if isinstance(name, str) and name and name != "NULL"]
        if root not in names:
            names.insert(0, root)
        exclusions = item.get("Exclusions") or []
        exclusions = [name for name in exclusions if isinstance(name, str)] if isinstance(exclusions, list) else []
        dynamics.append({
            "name": root, "root": root, "category": category, "evidence": evidence,
            "coordinate": coordinate, "bones": list(dict.fromkeys(names)),
            "exclusions": exclusions, "enabled": enabled,
            "renderers": [renderer.get("SMRName", "") for renderer in related],
            "materials": list(dict.fromkeys(name for renderer in related
                                             for name in renderer.get("SMRMaterialNames", []) if isinstance(name, str))),
            "colliders": [name for name in item.get("Colliders", []) if isinstance(name, str)]
                         if isinstance(item.get("Colliders", []), list) else [],
            "data": item,
        })
    transforms = {}
    for item in _read_list(folder, "KK_EditBoneInfo.json", warnings):
        if isinstance(item.get("boneName"), str):
            transforms[item["boneName"]] = item
    colliders = _read_list(folder, "KK_DynamicBoneColliderData.json", warnings)
    return {"dynamics": dynamics, "renderers": renderers, "colliders": colliders,
            "bone_transforms": transforms, "warnings": warnings}


def source_summary(sources):
    counts = {kind: 0 for kind in ("hair", "cloth", "skirt", "bust", "accessory")}
    for system in sources.get("dynamics", []):
        if system["enabled"] and system["category"] in counts:
            counts[system["category"]] += 1
    return {"systems": counts, "colliders": len(sources.get("colliders", [])),
            "warnings": sources.get("warnings", [])}
