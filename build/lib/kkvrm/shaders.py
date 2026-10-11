import json
from pathlib import Path


ALPHA_SHADER_BITS = ("main_alpha", "clothes_alpha", "MainAlpha", "AlphaMask", "item_glasses")
SKIN_TOKENS = ("cf_m_body", "cf_m_face", "cm_m_body", "cm_m_face")
EYE_TOKENS = ("hitomi", "eyeline", "mayuge", "eyelash", "noseline", "namida", "gag")
NAME_PREFIXES = ("KK ", "KKS ", "EC ", "AI ", "HS2 ")
BUST_LIFT_SKIP = ("body", "hair", "gag", "tear", "tongue", "face", "eye", "hitomi")


def shader_is_alpha(shader):
    return any(bit in (shader or "") for bit in ALPHA_SHADER_BITS)


def is_eye_card(name):
    lowered = (name or "").lower()
    return any(token in lowered for token in EYE_TOKENS)


def is_skin(name):
    lowered = (name or "").lower()
    return any(token in lowered for token in SKIN_TOKENS) and not is_eye_card(name)


def bust_clothing(name):
    lowered = (name or "").lower()
    return not lowered.startswith(BUST_LIFT_SKIP)


def shader_map(folder):
    folder = Path(folder)
    found = {}
    complete = folder / "KK_MaterialDataComplete.json"
    paths = [path for path in folder.glob("*MaterialData*.json") if path != complete]
    if complete.is_file():
        paths.append(complete)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            for mat in item.get("MaterialInformation") or []:
                if not isinstance(mat, dict):
                    continue
                name = mat.get("MaterialName")
                if name:
                    found[name] = mat.get("ShaderName") or ""
    return found


def _strip_instance(name):
    if len(name) > 4 and name[-4] == "." and name[-3:].isdigit():
        return name[:-4]
    return name


def lookup_shader(material_name, material_id, shaders):
    shaders = shaders or {}
    if not shaders:
        return ""
    stripped = material_name or ""
    for prefix in NAME_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    stripped = _strip_instance(stripped)
    candidates = []
    if isinstance(material_id, str) and material_id:
        candidates.append(material_id)
        candidates.append(_strip_instance(material_id))
    if stripped:
        candidates.append(stripped)
    for key in candidates:
        if key in shaders:
            return shaders[key]
    haystacks = [text for text in (material_name, material_id, stripped) if isinstance(text, str) and text]
    best = ""
    best_len = 0
    for key, shader in shaders.items():
        if not key or len(key) <= best_len:
            continue
        if any(key in hay for hay in haystacks):
            best = shader
            best_len = len(key)
    return best
