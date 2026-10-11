import json
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .config import find_blender
from .defaults import BUST_LIFT, BUST_LIFT_MAX, SPRINGS_DEFAULT
from .locate import character_name
from .meta import build_meta


SCRIPT = Path(__file__).resolve().parent / "export_vrm.py"
RESULT_PREFIX = "KKVRM_RESULT "


def resolve_meta(folder, meta=None, meta_file=None, sexual_ok=False, config_meta=None):
    """Merge metadata so the CLI can name output before Blender runs."""
    return build_meta(
        character_name(folder),
        overrides=meta,
        meta_file=meta_file,
        sexual_ok=sexual_ok,
        config_meta=config_meta,
    )


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
    config_meta=None,
    meta_info=None,
    bust_lift=None,
    springs=None,
    timeout=1800,
    verbose=False,
    quiet=False,
    dry_run=False,
):
    folder = Path(folder).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if bust_lift is not None and not 0 <= float(bust_lift) <= BUST_LIFT_MAX:
        raise ValueError(f"bust-lift must be between 0 and {BUST_LIFT_MAX} meters")
    info = meta_info or resolve_meta(
        folder,
        meta=meta,
        meta_file=meta_file,
        sexual_ok=sexual_ok,
        config_meta=config_meta,
    )
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
        "bust_lift": BUST_LIFT if bust_lift is None else float(bust_lift),
        "springs": SPRINGS_DEFAULT if springs is None else bool(springs),
        "package_root": str(Path(__file__).resolve().parent.parent),
    }
    blender_path = find_blender(blender)
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
        if dry_run:
            for line in format_plan(folder, output, info, payload, command, blender_path):
                print(line, file=sys.stderr)
            return {"ok": True, "output": str(output), "dry_run": True, **summarize(info)}
        completed = _run(command, timeout=timeout, verbose=verbose)
    text, returncode = completed
    log_path = output.with_suffix(".log")
    log_path.write_text(text, encoding="utf-8")
    result = None
    for line in text.splitlines():
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX):])
    if returncode != 0 or not result or not result.get("ok"):
        tail = "" if quiet else "\n".join(text.splitlines()[-40:])
        message = (result or {}).get("error") or f"blender exit {completed.returncode}"
        raise RuntimeError(f"{message}\nlog: {log_path}\n{tail}")
    return result


def format_plan(folder, output, info, payload, command, blender_path):
    log_path = Path(output).with_suffix(".log")
    return [
        "dry run, nothing was written",
        f"folder: {folder}",
        f"card: {payload['thumbnail'] or '(none)'}",
        f"name: {info['name']}",
        f"output: {output}",
        f"log: {log_path}",
        f"sfw: {info_str(payload['sfw'])}  include hidden: {info_str(payload['include_hidden'])}"
        f"  springs: {info_str(payload['springs'])}  keep blend: {info_str(payload['keep_blend'])}",
        f"bust lift: {payload['bust_lift']} m",
        f"authors: {', '.join(info['authors']) or '(none)'}",
        f"version: {info['version']}",
        f"license: {info['license'] or '(none)'}",
        f"license url: {info['license_url'] or '(none)'}",
        f"avatar permission: {info['avatar_permission']}",
        f"commercial usage: {info['commercial_usage']}",
        f"credit: {info['credit']}  modification: {info['modification']}",
        f"violent: {info_str(info['allow_violent'])}  sexual: {info_str(info['allow_sexual'])}"
        f"  political: {info_str(info['allow_political'])}  redistribution: {info_str(info['allow_redistribution'])}",
        f"blender: {blender_path}",
        "command: " + " ".join(shlex.quote(part) for part in command),
    ]


def info_str(value):
    return "yes" if value else "no"


def summarize(info):
    return {
        "meta": {key: info[key] for key in sorted(info) if key != "name"},
    }


def _run(command, timeout=1800, verbose=False):
    """Run Blender and stream output so a long convert never looks hung."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines = []

    def pump():
        for line in process.stdout:
            lines.append(line)
            if verbose:
                sys.stderr.write(line)
                sys.stderr.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    reader.join(timeout=5)
    return "".join(lines), returncode
