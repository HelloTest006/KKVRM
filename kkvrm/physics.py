"""Blender-independent spring configuration, detection and graph validation."""

import copy
import fnmatch
import hashlib
import math

from .bones import SPRING, spring_kind


CATEGORIES = ("hair", "cloth", "skirt", "bust", "accessory")
PRESETS = ("legacy", "balanced", "soft", "stiff")
SETTINGS = dict(SPRING, cloth={"hit_radius": 0.006, "stiffness": 0.65, "gravity_power": 0.035, "drag_force": 0.85},
                accessory={"hit_radius": 0.003, "stiffness": 0.9, "gravity_power": 0.02, "drag_force": 0.9})
SETTING_KEYS = {"hit_radius", "stiffness", "gravity_power", "drag_force", "gravity_dir"}
CONFIG_KEYS = {"preset", "types", "colliders", "endpoints", "exclude", "settings", "chains", "joint_settings"}
CHAIN_KEYS = {"name", "category", "root", "bones", "center", "settings", "joint_settings", "colliders", "endpoint"}


def on_off(value):
    if isinstance(value, bool):
        return value
    if value in ("on", "off"):
        return value == "on"
    raise ValueError("physics switches must be on/off or true/false")


def validate_settings(raw):
    if not isinstance(raw, dict) or set(raw) - SETTING_KEYS:
        raise ValueError(f"spring settings support: {', '.join(sorted(SETTING_KEYS))}")
    result = {}
    for key, value in raw.items():
        if key == "gravity_dir":
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise ValueError("gravity_dir must have three components in Blender Z-up coordinates")
            vector = [float(component) for component in value]
            if not all(math.isfinite(component) for component in vector):
                raise ValueError("gravity_dir must be finite")
            length = math.sqrt(sum(component * component for component in vector))
            if length < 1e-8:
                raise ValueError("gravity_dir cannot be zero")
            result[key] = [component / length for component in vector]
        else:
            number = float(value)
            if not math.isfinite(number) or number < 0 or (key == "drag_force" and number > 1):
                raise ValueError(f"invalid {key}: {value}")
            result[key] = number
    return result


def _strings(value, field):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return list(value)


def merge_config(base, updates):
    result = copy.deepcopy(base or {})
    if not isinstance(updates or {}, dict):
        raise ValueError("physics configuration must be an object")
    for key, value in (updates or {}).items():
        if key in ("types", "settings", "joint_settings") and isinstance(value, dict):
            target = result.setdefault(key, {})
            for name, item in value.items():
                if key != "types" and isinstance(item, dict):
                    target.setdefault(name, {}).update(item)
                else:
                    target[name] = copy.deepcopy(item)
        else:
            result[key] = copy.deepcopy(value)
    return result


def normalize_config(raw=None):
    raw = copy.deepcopy({} if raw is None else raw)
    if not isinstance(raw, dict) or set(raw) - CONFIG_KEYS:
        raise ValueError(f"physics configuration supports: {', '.join(sorted(CONFIG_KEYS))}")
    preset = raw.get("preset", "legacy")
    if preset not in PRESETS:
        raise ValueError(f"unknown physics preset: {preset}")
    types = {kind: kind in ("hair", "skirt", "bust") or (kind == "cloth" and preset != "legacy")
             for kind in CATEGORIES}
    if not isinstance(raw.get("types", {}), dict) or set(raw.get("types", {})) - set(CATEGORIES):
        raise ValueError("unknown physics category")
    types.update({kind: on_off(value) for kind, value in raw.get("types", {}).items()})
    colliders = raw.get("colliders", "none")
    if colliders not in ("none", "auto", "source"):
        raise ValueError("colliders must be none, auto, or source")
    settings = raw.get("settings", {})
    if not isinstance(settings, dict) or set(settings) - set(CATEGORIES):
        raise ValueError("unknown category in physics settings")
    settings = {kind: validate_settings(value) for kind, value in settings.items()}
    joint_settings = raw.get("joint_settings", {})
    if not isinstance(joint_settings, dict):
        raise ValueError("joint_settings must be an object keyed by bone name")
    joint_settings = {name: validate_settings(value) for name, value in joint_settings.items()}
    chains = raw.get("chains", [])
    if not isinstance(chains, list):
        raise ValueError("chains must be an array")
    names = set()
    for chain in chains:
        if not isinstance(chain, dict) or set(chain) - CHAIN_KEYS:
            raise ValueError("invalid custom spring chain")
        if chain.get("category") not in CATEGORIES:
            raise ValueError("custom chain requires a physics category")
        if "root" in chain and "bones" in chain:
            raise ValueError("custom chain specifies root or bones, not both")
        if "bones" in chain:
            chain["bones"] = _strings(chain["bones"], "bones")
            if not chain["bones"]:
                raise ValueError("custom chain bones cannot be empty")
        elif not isinstance(chain.get("root"), str) or not chain["root"]:
            raise ValueError("custom chain requires root or bones")
        if "name" in chain:
            if not isinstance(chain["name"], str) or not chain["name"] or chain["name"] in names:
                raise ValueError("custom chain names must be non-empty and unique")
            names.add(chain["name"])
        if "center" in chain and not isinstance(chain["center"], str):
            raise ValueError("center must be a bone name, humanoid slot, or world")
        chain["settings"] = validate_settings(chain.get("settings", {}))
        overrides = chain.get("joint_settings", {})
        if not isinstance(overrides, dict):
            raise ValueError("chain joint_settings must be an object")
        chain["joint_settings"] = {name: validate_settings(value) for name, value in overrides.items()}
        if "colliders" in chain:
            chain["colliders"] = _strings(chain["colliders"], "colliders")
        if "endpoint" in chain:
            chain["endpoint"] = on_off(chain["endpoint"])
    return {"preset": preset, "types": types, "colliders": colliders,
            "endpoints": on_off(raw.get("endpoints", preset != "legacy")),
            "exclude": _strings(raw.get("exclude", []), "exclude"),
            "settings": settings, "joint_settings": joint_settings, "chains": chains}


def _ancestor_path(name, parents):
    result = []
    while name is not None:
        if name in result:
            raise ValueError(f"cyclic bone hierarchy at {name}")
        result.append(name)
        name = parents.get(name)
    return result


def linear_segments(parents, allowed):
    """Split at branches without copying the trunk into every child chain."""
    children = {name: [] for name in allowed}
    for name in allowed:
        if parents.get(name) in children:
            children[parents[name]].append(name)
    segments, visited = [], set()

    def walk(name):
        chain = []
        while name not in visited:
            visited.add(name)
            chain.append(name)
            kids = sorted(children[name])
            if len(kids) != 1:
                segments.append(chain)
                for child in kids:
                    walk(child)
                return
            name = kids[0]
        raise ValueError(f"cyclic or repeated bone: {name}")

    for root in sorted(name for name in allowed if parents.get(name) not in allowed):
        walk(root)
    if visited != set(allowed):
        raise ValueError("physics bones contain a hierarchy cycle")
    return segments


def _base_settings(kind, config):
    settings = dict(SETTINGS[kind], gravity_dir=[0.0, 0.0, -1.0])
    if kind != "bust":
        if config["preset"] == "soft":
            settings["stiffness"] *= 0.6
            settings["drag_force"] = max(0.65, settings["drag_force"] - 0.08)
        elif config["preset"] == "stiff":
            settings["stiffness"] *= 1.8
            settings["drag_force"] = min(0.98, settings["drag_force"] + 0.08)
    settings.update(config["settings"].get(kind, {}))
    return settings


def plan_physics(records, config=None, sources=None, humanoid=None, weighted=None, outfit=None):
    config = normalize_config(config)
    sources, humanoid = sources or {}, humanoid or {}
    records = [dict(record) for record in records]
    bones = {record["name"]: record for record in records}
    if len(bones) != len(records):
        raise ValueError("bone names must be unique in the selected armature")
    parents = {name: record.get("parent") for name, record in bones.items()}
    for name in parents:
        _ancestor_path(name, parents)
    aliases = {}
    for name, record in bones.items():
        for alias in [name] + record.get("aliases", []):
            if isinstance(alias, str) and alias:
                aliases.setdefault(alias.casefold(), set()).add(name)

    def resolve(name):
        if name in bones:
            return name
        matches = aliases.get(str(name).casefold(), set())
        return next(iter(matches)) if len(matches) == 1 else None

    protected = set(humanoid.values())
    excluded_roots = {name for name, record in bones.items()
                      if any(fnmatch.fnmatchcase(alias.lower(), pattern.lower())
                             for alias in [name] + record.get("aliases", []) for pattern in config["exclude"])}

    def permitted(name):
        low = name.lower()
        return name not in protected and not low.startswith(("cf_s_", "cm_s_", "cf_d_bust", "cf_j_bust00", "cf_j_bust01")) \
            and "hit" not in low and not (set(_ancestor_path(name, parents)) & excluded_roots)

    candidates, skipped, notes = [], [], list(sources.get("warnings", []))
    for item in config["chains"]:
        kind = item["category"]
        if "bones" in item:
            names = [resolve(name) for name in item["bones"]]
            candidates.append(dict(item, bones=names, source="config", original=item["bones"]))
        else:
            root = resolve(item["root"])
            names = {name for name in bones if root and root in _ancestor_path(name, parents) and permitted(name)}
            if not root:
                skipped.append({"name": item["root"], "category": kind, "reason": "root not found or ambiguous"})
            for chain in linear_segments(parents, names):
                candidates.append(dict(item, bones=chain, source="config", original=chain))

    source_names = set()
    for item in sources.get("dynamics", []):
        kind = item.get("category")
        if kind not in CATEGORIES or kind == "bust" or not item.get("enabled"):
            continue
        if config["preset"] == "legacy" and kind in ("hair", "skirt"):
            continue
        if outfit is not None and item.get("coordinate") not in (None, -1, outfit):
            continue
        names = {resolve(name) for name in item["bones"]}
        names.discard(None)
        excluded = {resolve(name) for name in item.get("exclusions", [])}
        names = {name for name in names if permitted(name) and not set(_ancestor_path(name, parents)) & excluded}
        source_names.update(names)
        if not names:
            skipped.append({"name": item["name"], "category": kind, "reason": "source bones absent, excluded or ambiguous"})
        for chain in linear_segments(parents, names):
            candidates.append({"name": item["name"], "category": kind, "bones": chain,
                               "source": "KK_DynamicBoneData", "original": item["bones"],
                               "colliders": item.get("colliders", []), "data": item.get("data", {})})
    for kind in ("hair", "skirt", "bust"):
        names = {name for name in bones if permitted(name) and spring_kind(name) == kind and name not in source_names}
        for chain in linear_segments(parents, names):
            candidates.append({"category": kind, "bones": chain, "source": "bone-prefix", "original": chain})

    planned, occupied, used_labels = [], set(), set()
    for candidate in candidates:
        kind, chain = candidate["category"], list(candidate["bones"])
        label = candidate.get("name") or (chain[0] if chain and chain[0] else "unknown")

        def skip(reason):
            skipped.append({"name": label, "category": kind, "reason": reason})

        if not config["types"][kind]:
            skip("category disabled")
            continue
        if not chain or any(name not in bones or not permitted(name) for name in chain):
            skip("missing, ambiguous or protected bone")
            continue
        if len(set(chain)) != len(chain):
            raise ValueError(f"{label}: duplicate joint")
        path_nodes = set(chain)
        for first, last in zip(chain, chain[1:]):
            path = _ancestor_path(last, parents)
            if first not in path[1:]:
                raise ValueError(f"{label}: joints are not in ancestor order")
            path_nodes.update(path[:path.index(first) + 1])
        if path_nodes & protected:
            skip("chain crosses a humanoid bone")
            continue
        if path_nodes & occupied:
            skip("already covered by another spring")
            continue
        active_weights = weighted.get(kind, set()) if isinstance(weighted, dict) else weighted
        if active_weights is not None and not set(chain) & set(active_weights):
            skip("no positive weights on exported meshes")
            continue
        has_branch = sum(parent == chain[-1] for parent in parents.values()) > 1
        endpoint = candidate.get("endpoint", config["endpoints"] and kind != "bust")
        helper = None
        last_weighted = active_weights is None or chain[-1] in active_weights
        if endpoint and last_weighted and not has_branch:
            digest = hashlib.sha256((kind + "|" + "|".join(chain)).encode()).hexdigest()[:12]
            helper = {"name": f"kkvrm_tip_{digest}", "parent": chain[-1], "previous": chain[-2] if len(chain) > 1 else None}
            chain.append(helper["name"])
        if len(chain) < 2:
            skip("single joint or branching anchor has no usable endpoint")
            continue
        center_value = candidate.get("center")
        ancestry = _ancestor_path(candidate["bones"][0], parents)
        if center_value == "world":
            center = None
        elif center_value:
            center = humanoid.get(center_value) or resolve(center_value)
            if not center or center not in ancestry:
                raise ValueError(f"{label}: center must be an ancestor of the first joint")
        else:
            preferred = ("head", "hips") if kind == "hair" else ("chest", "upper_chest", "hips") if kind in ("cloth", "bust") else ("hips",)
            center = next((humanoid.get(slot) for slot in preferred if humanoid.get(slot) in ancestry), None)
        settings = _base_settings(kind, config)
        settings.update(candidate.get("settings", {}))
        joint_settings = []
        for name in chain:
            joint = copy.deepcopy(settings)
            joint.update(config["joint_settings"].get(name, {}))
            joint.update(candidate.get("joint_settings", {}).get(name, {}))
            joint_settings.append(joint)
        final_label = f"{kind}_{label}"
        if final_label in used_labels:
            final_label += f"_{len(planned)}"
        used_labels.add(final_label)
        planned.append({"name": final_label, "category": kind, "bones": chain, "center": center,
                        "settings": joint_settings, "source": candidate["source"],
                        "colliders": candidate.get("colliders", []), "endpoint": helper,
                        "data": candidate.get("data", {})})
        occupied.update(path_nodes)
    for chain in planned:
        if chain["center"] and set(_ancestor_path(chain["center"], parents)) & occupied:
            chain["center"] = None
            notes.append(f"{chain['name']}: using world center to avoid a simulated ancestor")
    if any(chain["source"] == "KK_DynamicBoneData" for chain in planned):
        notes.append("DynamicBone topology reused; VRM presets approximate motion. Elasticity/inertia are not copied directly.")
    return {"config": config, "chains": planned, "skipped": skipped,
            "warnings": list(dict.fromkeys(notes)), "weights_checked": weighted is not None,
            "counts": {kind: sum(chain["category"] == kind for chain in planned) for kind in CATEGORIES}}
