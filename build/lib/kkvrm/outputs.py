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
    cleaned = cleaned[:MAX_STEM].strip(" ._") or fallback
    if cleaned.lower() in RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned


def backup_path(path):
    path = Path(path)
    return path.with_name(path.name + ".bak")


def backup_existing(path):
    """Move an existing file to path.bak, replacing any stale backup."""
    path = Path(path)
    if not path.is_file():
        return None
    backup = backup_path(path)
    if backup.exists():
        backup.unlink()
    path.rename(backup)
    return backup


def prepare_output(path):
    """Back up an existing file and make sure the parent directory exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return backup_existing(path)
