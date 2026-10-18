import json
from pathlib import Path


AVATAR = ("onlyAuthor", "onlySeparatelyLicensedPerson", "everyone")
COMMERCIAL = ("personalNonProfit", "personalProfit", "corporation")
CREDIT = ("required", "unnecessary")
MODIFICATION = ("prohibited", "allowModification", "allowModificationRedistribution")

DEFAULTS = {
    "name": "Koikatsu",
    "version": "1.0.0",
    "authors": ["KKVRM"],
    "copyright": "",
    "contact": "",
    "references": [],
    "license": "",
    "license_url": "",
    "avatar_permission": "onlyAuthor",
    "allow_violent": False,
    "allow_sexual": False,
    "commercial_usage": "personalNonProfit",
    "allow_political": False,
    "allow_antisocial": False,
    "credit": "required",
    "allow_redistribution": False,
    "modification": "prohibited",
    "thumbnail": "",
}

ALIASES = {
    "name": "name",
    "version": "version",
    "authors": "authors",
    "author": "authors",
    "copyright": "copyright",
    "copyrightInformation": "copyright",
    "contact": "contact",
    "contactInformation": "contact",
    "references": "references",
    "reference": "references",
    "license": "license",
    "thirdPartyLicenses": "license",
    "licenseUrl": "license_url",
    "license_url": "license_url",
    "otherLicenseUrl": "license_url",
    "thumbnail": "thumbnail",
    "thumbnailImage": "thumbnail",
    "avatarPermission": "avatar_permission",
    "avatar_permission": "avatar_permission",
    "allowViolent": "allow_violent",
    "allow_violent": "allow_violent",
    "allowSexual": "allow_sexual",
    "allow_sexual": "allow_sexual",
    "sexual_ok": "allow_sexual",
    "commercialUsage": "commercial_usage",
    "commercial_usage": "commercial_usage",
    "commercial": "commercial_usage",
    "allowPolitical": "allow_political",
    "allow_political": "allow_political",
    "allowAntisocial": "allow_antisocial",
    "allow_antisocial": "allow_antisocial",
    "credit": "credit",
    "creditNotation": "credit",
    "allowRedistribution": "allow_redistribution",
    "allow_redistribution": "allow_redistribution",
    "modification": "modification",
}

LIST_FIELDS = {"authors", "references"}
BOOL_FIELDS = {
    "allow_violent",
    "allow_sexual",
    "allow_political",
    "allow_antisocial",
    "allow_redistribution",
}
ENUMS = {
    "avatar_permission": AVATAR,
    "commercial_usage": COMMERCIAL,
    "credit": CREDIT,
    "modification": MODIFICATION,
}


def _strings(value, field):
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{field} entries must be non-empty strings")
            found.append(item.strip())
        return found
    raise ValueError(f"{field} must be a string or a list of strings")


def _bool(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    raise ValueError(f"{field} must be true or false")


def _apply(merged, raw):
    if not raw:
        return
    if not isinstance(raw, dict):
        raise ValueError("metadata must be an object")
    for key, value in raw.items():
        dest = ALIASES.get(key)
        if dest is None:
            raise ValueError(f"unknown metadata field: {key}")
        if value is None:
            continue
        if dest in LIST_FIELDS:
            merged[dest] = _strings(value, dest)
        elif dest in BOOL_FIELDS:
            merged[dest] = _bool(value, dest)
        elif dest in ENUMS:
            if value not in ENUMS[dest]:
                choices = ", ".join(ENUMS[dest])
                raise ValueError(f"{dest} must be one of: {choices}")
            merged[dest] = value
        elif dest == "name":
            text = str(value).strip()
            if not text:
                raise ValueError("name must not be empty")
            merged["name"] = text
        else:
            merged[dest] = str(value)


def load_meta_file(path):
    path = Path(path).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid metadata JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"metadata file must be a JSON object: {path}")
    for key in ("thumbnail", "thumbnailImage"):
        thumb = data.get(key)
        if isinstance(thumb, str) and thumb:
            data[key] = str((path.parent / Path(thumb).expanduser()).resolve())
    return data


def build_meta(name, overrides=None, meta_file=None, sexual_ok=False, config_meta=None):
    """Layer metadata: defaults, then stored config, then a file, then flags."""
    merged = dict(DEFAULTS)
    merged["authors"] = list(DEFAULTS["authors"])
    merged["references"] = []
    merged["name"] = (name or "Koikatsu").strip() or "Koikatsu"
    _apply(merged, config_meta)
    if meta_file:
        _apply(merged, load_meta_file(meta_file))
    _apply(merged, overrides)
    if sexual_ok:
        merged["allow_sexual"] = True
    if not merged["authors"]:
        raise ValueError("at least one author is required")
    thumb = merged.get("thumbnail") or ""
    if thumb and not Path(thumb).is_file():
        raise FileNotFoundError(f"thumbnail not found: {thumb}")
    return merged
