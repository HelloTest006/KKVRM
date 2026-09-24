import json
import subprocess
import tempfile
from pathlib import Path

from .config import find_blender
from .locate import character_name
from .meta import build_meta


SCRIPT = Path(__file__).resolve().parent / "export_vrm.py"
RESULT_PREFIX = "KKVRM_RESULT "


def convert(
    folder,
    output,
    blender=None,
    card=None,
    sfw=False,
    sexual_ok=False,
    include_hidden=False,
    keep_blend=False,
    meta_file=None,
    meta=None,
    bust_lift=None,
    springs=True,
    timeout=1800,
):
    folder = Path(folder).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if bust_lift is not None and not 0 <= float(bust_lift) <= 0.05:
        raise ValueError("bust-lift must be between 0 and 0.05 meters")
    info = build_meta(
        character_name(folder),
        overrides=meta,
        meta_file=meta_file,
        sexual_ok=sexual_ok,
    )
    blender_path = find_blender(blender)
    thumbnail = info.get("thumbnail") or (str(card) if card else None)
    payload = {
        "import_dir": str(folder),
        "output": str(output),
        "name": info["name"],
        "thumbnail": thumbnail,
        "meta": info,
        "sfw": bool(sfw),
        "sexual_ok": bool(info["allow_sexual"]),
        "include_hidden": bool(include_hidden),
        "keep_blend": bool(keep_blend),
        "bust_lift": 0.006 if bust_lift is None else float(bust_lift),
        "springs": bool(springs),
        "package_root": str(Path(__file__).resolve().parent.parent),
    }
    with tempfile.TemporaryDirectory(prefix="kkvrm-") as temp:
        args_path = Path(temp) / "args.json"
        args_path.write_text(json.dumps(payload), encoding="utf-8")
        command = [
            str(blender_path),
            "--background",
            "--python-exit-code",
            "1",
            "--python",
            str(SCRIPT),
            "--",
            "--args",
            str(args_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    log_path = output.with_suffix(".log")
    log_path.write_text(text, encoding="utf-8")
    result = None
    for line in text.splitlines():
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX):])
    if completed.returncode != 0 or not result or not result.get("ok"):
        tail = "\n".join(text.splitlines()[-40:])
        message = (result or {}).get("error") or f"blender exit {completed.returncode}"
        raise RuntimeError(f"{message}\nlog: {log_path}\n{tail}")
    return result
