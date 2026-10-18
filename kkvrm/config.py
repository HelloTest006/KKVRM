import os
from pathlib import Path

from .jsonio import read_object, write_object


def config_path():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "kkvrm" / "config.json"
    return Path.home() / ".config" / "kkvrm" / "config.json"


def load():
    path = config_path()
    if not path.is_file():
        return {}
    return read_object(path)


def save(updates):
    path = config_path()
    data = load()
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return write_object(path, data)


def resolve_blender(path):
    path = Path(path).expanduser()
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for name in ("blender.exe", "blender"):
        candidate = path / name
        if candidate.is_file():
            return candidate
    nested = sorted(path.glob("*/blender.exe"))
    if nested:
        return nested[0]
    return None


def find_blender(explicit=None):
    if explicit:
        found = resolve_blender(explicit)
        if not found:
            raise FileNotFoundError(f"blender.exe not found: {explicit}")
        return found
    env = os.environ.get("KKVRM_BLENDER") or os.environ.get("BLENDER")
    if env:
        found = resolve_blender(env)
        if found:
            return found
    configured = load().get("blender")
    if configured:
        found = resolve_blender(configured)
        if found:
            return found
    names = ("blender.exe", "blender")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_file():
                return candidate
    roots = []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        roots.append(Path(program_files) / "Blender Foundation")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs")
    for root in roots:
        if not root.is_dir():
            continue
        found = sorted(root.glob("**/blender.exe"), reverse=True)
        if found:
            return found[0]
    raise FileNotFoundError(
        "blender.exe not found. Install Blender 5.2 or set it with: kkvrm config --blender PATH"
    )
