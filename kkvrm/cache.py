import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


IGNORED_FOLDERS = {"pre_light", "pre_dark", "kkvrm_baked", ".git", "__pycache__"}
SOURCE_SUFFIXES = {".pmx", ".png", ".jpg", ".jpeg", ".dds", ".tga", ".bmp", ".json"}


def default_root():
    root = os.environ.get("LOCALAPPDATA")
    return Path(root) / "kkvrm" / "cache" if root else Path.home() / ".cache" / "kkvrm"


def source_digest(folder):
    folder = Path(folder).resolve()
    digest = hashlib.sha256()
    digest.update(str(folder).encode())
    paths = sorted(path for path in folder.rglob("*") if path.is_file()
                   and path.suffix.lower() in SOURCE_SUFFIXES
                   and not {part.lower() for part in path.relative_to(folder).parts[:-1]} & IGNORED_FOLDERS
                   and path.name.lower() not in ("kkvrm.json",)
                   and not path.name.lower().endswith(".report.json"))
    for path in paths:
        digest.update(path.relative_to(folder).as_posix().encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def location(folder, blender, options, root=None):
    folder = Path(folder).resolve()
    root = Path(root).expanduser().resolve() if root else default_root().resolve()
    if root == folder or folder in root.parents:
        raise ValueError("cache-dir must be outside the source export folder")
    blender = Path(blender).resolve()
    code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        code.update(path.name.encode())
        code.update(path.read_bytes())
    stat = blender.stat()
    identity = {"source": source_digest(folder), "code": code.hexdigest(),
                "blender": str(blender), "blender_size": stat.st_size,
                "blender_mtime": stat.st_mtime_ns, "sfw": options["sfw"], "schema_version": 1}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return root / key / "prepared.blend", key


@contextmanager
def locked(path, timeout=60):
    """Serialize cache readers/writers, including separate KKVRM processes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.parent / ".lock"
    # OS advisory locks are released even if KKVRM crashes. Keep the lock file
    # in place: unlinking it would let another process lock a different inode.
    with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR), "r+b") as handle:
        started = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started >= timeout:
                    raise RuntimeError(f"prepared cache is in use: {path}; retry or use --no-cache")
                time.sleep(0.1)
        try:
            handle.seek(0)
            handle.write(b"0" + json.dumps({"pid": os.getpid(), "started": time.time()}).encode())
            handle.truncate()
            handle.flush()
            yield path
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
