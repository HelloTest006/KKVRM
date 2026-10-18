import os
import string
from pathlib import Path


RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
ILLEGAL = '<>:"/\\|?*'
MAX_STEM = 60


def safe_stem(text, fallback="model"):
    cleaned = "".join("_" if ch in ILLEGAL or ord(ch) < 32 else ch for ch in str(text or "")).strip(" .")
    cleaned = cleaned[:MAX_STEM].strip(" ._")
    if not cleaned:
        cleaned = "".join("_" if ch in ILLEGAL or ord(ch) < 32 else ch for ch in str(fallback)).strip(" ._")[:MAX_STEM] or "model"
    if cleaned.split(".", 1)[0].lower() in RESERVED:
        first, separator, rest = cleaned.partition(".")
        cleaned = first + "_" + separator + rest
    return cleaned


def format_stem(template, **fields):
    for _literal, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and (field not in {"name", "folder", "version"} or spec or conversion):
            raise ValueError("name-template only supports {name}, {folder}, and {version}")
    try:
        return safe_stem(template.format(**fields), fallback=fields.get("folder", "model"))
    except (ValueError, KeyError) as exc:
        raise ValueError(f"invalid name-template: {exc}") from exc


def backup_path(path):
    path = Path(path)
    return path.with_name(path.name + ".bak")


def backup_existing(path):
    """Move an existing file to path.bak, replacing any stale backup."""
    path = Path(path)
    if not path.is_file():
        return None
    backup = backup_path(path)
    os.replace(path, backup)
    return backup


def publish_output(staged, target, force=False):
    """Publish a complete export, retaining the previous file until this point."""
    staged, target = Path(staged), Path(target)
    if not staged.is_file():
        raise FileNotFoundError(f"export is missing: {staged}")
    if target.exists() and not target.is_file():
        raise ValueError(f"output is not a file: {target}")
    backup = None if force else backup_existing(target)
    try:
        os.replace(staged, target)
    except OSError:
        if backup and not target.exists():
            os.replace(backup, target)
        raise
    return backup


def prepare_output(path):
    """Back up an existing file and make sure the parent directory exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return backup_existing(path)
