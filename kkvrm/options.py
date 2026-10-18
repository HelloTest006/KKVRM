import copy
import math

from .defaults import BUST_LIFT, BUST_LIFT_MAX
from .physics import merge_config, normalize_config


DEFAULTS = {
    "sfw": False, "include_hidden": False, "keep_blend": False, "cache": False,
    "bust_lift": BUST_LIFT, "height": "auto", "outfit": None,
    "include_mesh": [], "exclude_mesh": [], "bust_materials": [],
    "material_overrides": {}, "physics": {"preset": "legacy"},
}


def merge_options(base, updates):
    if not isinstance(updates or {}, dict):
        raise ValueError("conversion options must be an object")
    unknown = set(updates or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown conversion option: {', '.join(sorted(unknown))}")
    result = copy.deepcopy(base)
    for key, value in (updates or {}).items():
        if key == "physics":
            result[key] = merge_config(result.get(key, {}), value)
        elif key == "material_overrides" and isinstance(value, dict):
            result.setdefault(key, {}).update(copy.deepcopy(value))
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_options(raw):
    result = merge_options(DEFAULTS, raw)
    for field in ("sfw", "include_hidden", "keep_blend", "cache"):
        if not isinstance(result[field], bool):
            raise ValueError(f"{field} must be true or false")
    lift = float(result["bust_lift"])
    if not math.isfinite(lift) or not 0 <= lift <= BUST_LIFT_MAX:
        raise ValueError(f"bust_lift must be between 0 and {BUST_LIFT_MAX} meters")
    result["bust_lift"] = lift
    height = result["height"]
    if height not in ("auto", "keep"):
        try:
            height = float(height)
        except (ValueError, TypeError) as exc:
            raise ValueError("height must be auto, keep, or a height in meters") from exc
        if not math.isfinite(height) or not 0 < height <= 10:
            raise ValueError("target height must be between 0 and 10 meters")
    result["height"] = height
    outfit = result["outfit"]
    if outfit is not None and (not isinstance(outfit, int) or isinstance(outfit, bool) or outfit < 0):
        raise ValueError("outfit must be a non-negative index")
    for field in ("include_mesh", "exclude_mesh", "bust_materials"):
        if not isinstance(result[field], list) or any(not isinstance(item, str) or not item for item in result[field]):
            raise ValueError(f"{field} must be an array of non-empty patterns")
    if not isinstance(result["material_overrides"], dict):
        raise ValueError("material_overrides must be an object keyed by material-name patterns")
    for pattern, material in result["material_overrides"].items():
        if not isinstance(pattern, str) or not pattern or not isinstance(material, dict):
            raise ValueError("invalid material override")
        if set(material) - {"alpha_mode", "alpha_cutoff", "double_sided"}:
            raise ValueError(f"unsupported material override fields: {pattern}")
        if "alpha_mode" in material and material["alpha_mode"] not in ("OPAQUE", "MASK", "BLEND"):
            raise ValueError(f"invalid alpha_mode: {pattern}")
        if "alpha_cutoff" in material and (not math.isfinite(float(material["alpha_cutoff"])) or not 0 <= float(material["alpha_cutoff"]) <= 1):
            raise ValueError(f"invalid alpha_cutoff: {pattern}")
        if "double_sided" in material and not isinstance(material["double_sided"], bool):
            raise ValueError(f"double_sided must be true or false: {pattern}")
    result["physics"] = normalize_config(result["physics"])
    return result
