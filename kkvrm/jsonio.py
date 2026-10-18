import json
import os
import tempfile
from pathlib import Path


def read_object(path):
    path = Path(path).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return data


def write_object(path, data):
    """Replace JSON atomically; an interrupted write cannot truncate the original."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path
