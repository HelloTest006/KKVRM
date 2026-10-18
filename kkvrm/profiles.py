import copy
import re
from pathlib import Path

from .config import config_path
from .jsonio import read_object, write_object
from .locate import character_name
from .meta import ALIASES, _apply, build_meta, load_meta_file
from .options import DEFAULTS, merge_options, validate_options


BUILTINS = {
    "legacy": {"schema_version": 1, "meta": {}, "options": {"physics": {"preset": "legacy"}}},
    "cloth-balanced": {"schema_version": 1, "meta": {}, "options": {"physics": {
        "preset": "balanced", "types": {"hair": True, "cloth": True, "skirt": True, "accessory": False},
        "colliders": "auto", "endpoints": True,
    }}},
    "hair-soft": {"schema_version": 1, "meta": {}, "options": {"physics": {
        "preset": "soft", "types": {"hair": True, "cloth": False, "skirt": False, "bust": False, "accessory": False},
        "colliders": "auto",
    }}},
}


def profiles_dir():
    return config_path().parent / "profiles"


def validate_document(document, base=None, packed=False):
    if not isinstance(document, dict) or set(document) - {"schema_version", "meta", "options"}:
        raise ValueError("profile/model configuration supports schema_version, meta, and options")
    if document.get("schema_version", 1) != 1:
        raise ValueError("unsupported profile schema_version")
    doc = copy.deepcopy(document)
    doc.setdefault("schema_version", 1)
    doc.setdefault("meta", {})
    doc.setdefault("options", {})
    if not isinstance(doc["meta"], dict):
        raise ValueError("profile metadata must be an object")
    if base is not None:
        for key in ("thumbnail", "thumbnailImage"):
            if doc["meta"].get(key):
                doc["meta"][key] = str((Path(base) / Path(doc["meta"][key]).expanduser()).resolve())
    validate_options(doc["options"])
    metadata = dict(doc["meta"])
    if packed:
        metadata.pop("thumbnail", None)
        metadata.pop("thumbnailImage", None)
    build_meta("Koikatsu", overrides=metadata)
    return doc


def read_document(path):
    path = Path(path).expanduser().resolve()
    return validate_document(read_object(path), base=path.parent)


def load_profile(name):
    if name in BUILTINS:
        return copy.deepcopy(BUILTINS[name])
    path = Path(name).expanduser()
    if path.is_file():
        return read_document(path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(name)):
        raise FileNotFoundError(f"profile file not found: {name}")
    path = profiles_dir() / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"unknown profile: {name}; use kkvrm profile list")
    return read_document(path)


def list_profiles():
    result = [{"name": name, "builtin": True} for name in BUILTINS]
    root = profiles_dir()
    if root.is_dir():
        result.extend({"name": path.stem, "builtin": False, "path": str(path)}
                      for path in sorted(root.glob("*.json")) if path.stem not in BUILTINS)
    return result


def save_profile(name, document, force=False):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or name in BUILTINS:
        raise ValueError("use a new profile name containing letters, digits, '.', '_' or '-'")
    doc = validate_document(document)
    path = profiles_dir() / f"{name}.json"
    if path.exists() and not force:
        raise ValueError(f"profile already exists: {name}; use --force to replace it")
    return write_object(path, doc)


def _record_provenance(value, prefix, source, provenance):
    if isinstance(value, dict):
        for key, nested in value.items():
            _record_provenance(nested, f"{prefix}.{key}" if prefix else key, source, provenance)
    else:
        provenance[prefix] = source


def resolve_settings(folder, profile=None, stored=None, model_config=None, overrides=None,
                     meta=None, meta_file=None, sexual_ok=False, base_document=None):
    """Resolve every option once. Paths from files are relative to those files."""
    folder = Path(folder)
    stored = stored or {}
    info = build_meta(character_name(folder))
    options = copy.deepcopy(DEFAULTS)
    provenance = {}
    _record_provenance(options, "options", "defaults", provenance)
    for key in info:
        provenance[f"meta.{key}"] = "defaults"

    def layer(source, metadata=None, settings=None):
        nonlocal options
        if metadata is not None:
            _apply(info, metadata)
            for key, value in metadata.items():
                if value is not None:
                    provenance[f"meta.{ALIASES[key]}"] = source
        if settings is not None:
            options = merge_options(options, settings)
            _record_provenance(settings, "options", source, provenance)

    layer("stored config", stored.get("meta"), stored.get("options"))
    if base_document:
        doc = validate_document(base_document, packed=True)
        layer("prepared model", doc["meta"], doc["options"])
    chosen = profile or (stored.get("default_profile") if base_document is None else None)
    if chosen:
        doc = load_profile(chosen)
        layer(f"profile:{chosen}", doc["meta"], doc["options"])
    model_path = Path(model_config).expanduser() if model_config else folder / "kkvrm.json"
    if model_config or (base_document is None and model_path.is_file()):
        doc = read_document(model_path)
        layer(f"model config:{model_path}", doc["meta"], doc["options"])
    if meta_file:
        layer(f"metadata file:{meta_file}", load_meta_file(meta_file))
    layer("command flags", meta or {}, overrides or {})
    if sexual_ok:
        layer("command flags", {"allow_sexual": True})
    if info["thumbnail"] and not Path(info["thumbnail"]).is_file() and provenance.get("meta.thumbnail") == "prepared model":
        info["thumbnail"] = ""
        provenance["meta.thumbnail"] = "prepared model (packed image)"
    info = build_meta(info["name"], overrides=info)
    options = validate_options(options)
    return {"meta": info, "options": options, "provenance": provenance,
            "profile": str(chosen) if chosen else None}
