import re

VISEMES = {
    "mouth a big": "aa",
    "mouth big a": "aa",
    "mouth i big": "ih",
    "mouth big i": "ih",
    "mouth u big": "ou",
    "mouth big u": "ou",
    "mouth e big": "ee",
    "mouth big e": "ee",
    "mouth o big": "oh",
    "mouth big o": "oh",
}

PRESETS = (
    "happy",
    "angry",
    "sad",
    "relaxed",
    "surprised",
    "aa",
    "ih",
    "ou",
    "ee",
    "oh",
    "blink",
    "blink_left",
    "blink_right",
)


def normalize(name):
    return " ".join(name.replace(",", " ").lower().split())


def region_of(name):
    text = normalize(name)
    if text.startswith("eyebrow "):
        return "eyebrow"
    if text.startswith("mouth "):
        return "mouth"
    if text.startswith("eye "):
        return "eye"
    return "other"


def rank(name, preset):
    text = normalize(name)
    if preset == "happy":
        if "broad" in text:
            return 3
        if "smiling" in text:
            return 2
    if preset in VISEMES.values() or preset.startswith("blink"):
        return 5
    return 1


def choose_presets(names):
    best = {}
    for name in names:
        preset = classify(name)
        if not preset:
            continue
        key = (preset, region_of(name))
        scored = (rank(name, preset), name)
        current = best.get(key)
        if current is None or scored[0] > current[0]:
            best[key] = scored
    chosen = {}
    for (preset, _region), (_score, name) in best.items():
        chosen[name] = preset
    return chosen


def classify(name):
    text = normalize(name)
    if "wink left" in text or "winking l" in text:
        return "blink_left"
    if "wink right" in text or "winking r" in text:
        return "blink_right"
    if text in {"eye closed", "eyes closed", "eye default closed"}:
        return "blink"
    if text in VISEMES:
        return VISEMES[text]
    if any(token in text for token in ("slight", "moderate", "closed", "small")):
        return None
    if not text.startswith(("eye ", "mouth ", "eyebrow ")):
        return None
    if "smiling" in text or "happy" in text:
        return "happy"
    if "angry" in text and "angry 2" not in text and "left" not in text and "right" not in text:
        return "angry"
    if "lonely" in text or re.search(r"\bsad\b", text):
        return "sad"
    if "surprised" in text or "shocked" in text:
        return "surprised"
    if re.search(r"\bbored\b", text):
        return "relaxed"
    return None
