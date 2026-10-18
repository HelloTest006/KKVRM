import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from .config import find_blender
from .cache import location as cache_location, locked as cache_locked
from .defaults import BUST_LIFT, BUST_LIFT_MAX, SPRINGS_DEFAULT
from .jsonio import read_object, write_object
from .locate import character_name
from .meta import build_meta
from .outputs import publish_output
from .options import validate_options
from .vrm import validate


SCRIPT = Path(__file__).resolve().parent / "export_vrm.py"
RESULT_PREFIX = "KKVRM_RESULT "
PROGRESS_PREFIX = "KKVRM_PROGRESS "
_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


def resolve_meta(folder, meta=None, meta_file=None, sexual_ok=False, config_meta=None):
    return build_meta(character_name(folder), overrides=meta, meta_file=meta_file,
                      sexual_ok=sexual_ok, config_meta=config_meta)


def blender_command(blender, args_path):
    return [str(blender), "--background", "--python-exit-code", "1", "--python",
            str(SCRIPT), "--", "--args", str(args_path)]


def plan(folder, output, blender=None, card=None, sfw=False, sexual_ok=False,
         include_hidden=False, keep_blend=False, meta_file=None, meta=None,
         config_meta=None, meta_info=None, bust_lift=None, springs=None,
         require_blender=False, options=None, provenance=None, blend_input=None):
    """Resolve a conversion without creating directories, backups or argument files."""
    folder = Path(folder).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if not folder.is_dir() and not blend_input:
        raise FileNotFoundError(f"export folder not found: {folder}")
    if blend_input and not Path(blend_input).is_file():
        raise FileNotFoundError(f"prepared .blend not found: {blend_input}")
    if output.suffix.lower() != ".vrm":
        raise ValueError("output must have a .vrm extension")
    if output.exists() and not output.is_file():
        raise ValueError(f"output is not a file: {output}")
    lift = BUST_LIFT if bust_lift is None else float(bust_lift)
    if not math.isfinite(lift) or not 0 <= lift <= BUST_LIFT_MAX:
        raise ValueError(f"bust-lift must be between 0 and {BUST_LIFT_MAX} meters")
    info = meta_info or resolve_meta(folder, meta, meta_file, sexual_ok, config_meta)
    resolved_options = validate_options(options or {
        "sfw": bool(sfw), "include_hidden": bool(include_hidden),
        "keep_blend": bool(keep_blend), "bust_lift": lift,
    })
    if springs is False:
        resolved_options["physics"]["types"] = {kind: False for kind in resolved_options["physics"]["types"]}
    payload = {
        "import_dir": str(folder), "output": str(output), "name": info["name"],
        "thumbnail": info.get("thumbnail") or (str(Path(card).resolve()) if card else None),
        "meta": info, "sexual_ok": bool(info["allow_sexual"]),
        "sfw": resolved_options["sfw"], "include_hidden": resolved_options["include_hidden"],
        "keep_blend": resolved_options["keep_blend"], "bust_lift": resolved_options["bust_lift"],
        "springs": SPRINGS_DEFAULT if springs is None else bool(springs),
        "options": resolved_options,
        "package_root": str(SCRIPT.parent.parent),
    }
    if blend_input:
        payload.update(action="reexport", blend_input=str(Path(blend_input).resolve()))
    warnings = []
    try:
        blender_path = str(find_blender(blender).resolve())
    except FileNotFoundError as exc:
        if require_blender or blender:
            raise
        blender_path = None
        warnings.append(str(exc))
    return {"output": str(output), "payload": payload, "blender": blender_path,
            "command": blender_command(blender_path or "blender", "<ARGS_JSON>"),
            "warnings": warnings, "provenance": provenance or {}}


def convert(folder, output, blender=None, card=None, sfw=False, sexual_ok=False,
            include_hidden=False, keep_blend=False, meta_file=None, meta=None,
            config_meta=None, meta_info=None, bust_lift=None, springs=None,
            timeout=1800, verbose=False, quiet=False, dry_run=False, force=False,
            report=True, options=None, provenance=None, cache_root=None):
    if not math.isfinite(float(timeout)) or timeout <= 0:
        raise ValueError("timeout must be a positive number of seconds")
    job = plan(folder, output, blender, card, sfw, sexual_ok, include_hidden,
               keep_blend, meta_file, meta, config_meta, meta_info, bust_lift,
               springs, require_blender=not dry_run, options=options, provenance=provenance)
    if dry_run:
        print(json.dumps(job, indent=2, ensure_ascii=False), file=sys.stderr)
        return {"ok": True, "dry_run": True, "output": job["output"], "plan": job}
    return _execute(job, timeout, verbose, quiet, force, report, cache_root)


def _execute(job, timeout, verbose, quiet, force, report, cache_root=None):
    target = Path(job["output"])
    target.parent.mkdir(parents=True, exist_ok=True)
    log = target.with_suffix(".log")
    started = time.monotonic()
    try:
        with ExitStack() as stack:
            cache_path, cache_key = None, None
            if job["payload"]["options"]["cache"] and job["payload"].get("action", "convert") == "convert":
                cache_path, cache_key = cache_location(job["payload"]["import_dir"], job["blender"], job["payload"]["options"], cache_root)
                stack.enter_context(cache_locked(cache_path))
            temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix=".kkvrm-export-", dir=target.parent))
            stage = Path(temporary) / target.name
            payload = dict(job["payload"], output=str(stage), final_output=str(target))
            if cache_path:
                payload.update(cache_path=str(cache_path), cache_key=cache_key)
            args_path = write_object(Path(temporary) / "args.json", payload)
            command = blender_command(job["blender"], args_path)
            text, returncode = _run(command, timeout, verbose, log_path=log,
                                    quiet=quiet, label=target.stem)
            result = parse_result(text)
            if returncode or not result or not result.get("ok"):
                message = (result or {}).get("error") or f"blender exit {returncode}; no successful result"
                tail = "" if quiet else "\n" + "\n".join(text.splitlines()[-40:])
                raise RuntimeError(f"{message}\nlog: {log}{tail}")
            validation = validate(stage)
            if job["payload"]["keep_blend"]:
                blend = stage.with_suffix(".blend")
                if not blend.is_file():
                    raise RuntimeError("Blender did not save the requested .blend")
                publish_output(blend, target.with_suffix(".blend"), force=True)
                companion = blend.with_suffix(".blend.json")
                if companion.is_file():
                    publish_output(companion, target.with_suffix(".blend.json"), force=True)
            backup = publish_output(stage, target, force=force)
            if backup and not quiet:
                print(f"previous export kept at {backup}", file=sys.stderr)
        result.update(output=str(target), elapsed_seconds=round(time.monotonic() - started, 3),
                      validation=validation, options=job["payload"], provenance=job["provenance"])
        if report:
            write_object(target.with_suffix(".report.json"), result)
        return result
    except (RuntimeError, OSError, KeyboardInterrupt) as exc:
        if report:
            write_object(target.with_suffix(".report.json"), {
                "ok": False, "output": str(target), "error": str(exc) or "cancelled",
                "log": str(log), "elapsed_seconds": round(time.monotonic() - started, 3),
                "options": job["payload"],
            })
        raise


def prepared_info(path, blender=None, timeout=1800, allow_launch=True):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".blend":
        raise FileNotFoundError(f"prepared .blend not found: {path}")
    companion = path.with_suffix(".blend.json")
    if companion.is_file():
        project = read_object(companion)
        stat = path.stat()
        if project.get("blend_size") == stat.st_size and project.get("blend_mtime_ns") == stat.st_mtime_ns:
            return project
    if not allow_launch:
        raise ValueError("dry-run needs the prepared .blend.json companion; keep it alongside the .blend")
    result = invoke({"action": "describe", "blend_input": str(path)}, blender=blender, timeout=timeout, quiet=True)
    return result["project"]


def reexport(blend, output, blender=None, options=None, meta_info=None, provenance=None,
             timeout=1800, verbose=False, quiet=False, dry_run=False, force=False, report=True):
    project = prepared_info(blend, blender=blender, timeout=timeout, allow_launch=not dry_run)
    if options is not None and options.get("sfw", False) != project["settings"]["options"].get("sfw", False):
        raise ValueError("SFW is an import-time option; convert the original export again to change it")
    folder = project.get("import_dir") or Path(blend).parent
    info = meta_info or project["settings"]["meta"]
    job = plan(folder, output, blender=blender, meta_info=info,
               options=options or project["settings"]["options"], provenance=provenance,
               require_blender=not dry_run, blend_input=blend)
    if dry_run:
        print(json.dumps(job, indent=2, ensure_ascii=False), file=sys.stderr)
        return {"ok": True, "dry_run": True, "output": job["output"], "plan": job}
    return _execute(job, timeout, verbose, quiet, force, report)


def invoke(payload, blender=None, timeout=1800, verbose=False, quiet=False):
    """Run a diagnostic action using the same result/progress contract as export."""
    blender = find_blender(blender)
    with tempfile.TemporaryDirectory(prefix="kkvrm-check-") as temporary:
        args_path = write_object(Path(temporary) / "args.json", payload)
        text, code = _run(blender_command(blender, args_path), timeout, verbose,
                          quiet=quiet, label=payload.get("action", "check"))
    result = parse_result(text)
    if result and payload.get("action") == "check":
        return result
    if code or not result or not result.get("ok"):
        message = (result or {}).get("error") or f"blender exit {code}"
        raise RuntimeError(message + "\n" + "\n".join(text.splitlines()[-30:]))
    return result


def parse_result(text):
    result = None
    for line in text.splitlines():
        if line.startswith(RESULT_PREFIX):
            try:
                value = json.loads(line[len(RESULT_PREFIX):])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result = value
    return result


def format_command(command):
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def _stop(process):
    if os.name == "nt" and process.poll() is None:
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def cancel_active():
    with _ACTIVE_LOCK:
        processes = list(_ACTIVE)
    for process in processes:
        try:
            _stop(process)
        except OSError:
            pass


def _run(command, timeout=1800, verbose=False, log_path=None, quiet=False, label=""):
    """Drain both streams, flush the log as it arrives, and reap on cancellation."""
    log = Path(log_path).open("w", encoding="utf-8") if log_path else None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError:
        if log:
            log.close()
        raise
    with _ACTIVE_LOCK:
        _ACTIVE.add(process)
    lines, reader_errors = [], []

    def pump():
        try:
            for line in process.stdout:
                lines.append(line)
                if log:
                    log.write(line)
                    log.flush()
                if verbose:
                    sys.stderr.write(line)
                    sys.stderr.flush()
                elif not quiet and line.startswith(PROGRESS_PREFIX):
                    try:
                        event = json.loads(line[len(PROGRESS_PREFIX):])
                        print(f"[{label}] {event['stage']} ({event.get('elapsed_seconds', 0):.1f}s)",
                              file=sys.stderr, flush=True)
                    except (ValueError, KeyError, TypeError):
                        pass
        except (OSError, ValueError) as exc:
            reader_errors.append(exc)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop(process)
            raise RuntimeError(f"blender timed out after {timeout}s\nlog: {log_path or '(none)'}") from exc
        except KeyboardInterrupt:
            _stop(process)
            raise
        reader.join(timeout=10)
        if reader.is_alive():
            raise RuntimeError(f"Blender output stream did not close\nlog: {log_path or '(none)'}")
        if reader_errors:
            raise RuntimeError(f"could not read Blender output: {reader_errors[0]}")
        return "".join(lines), returncode
    finally:
        if process.poll() is None:
            _stop(process)
        reader.join(timeout=10)
        if not reader.is_alive():
            process.stdout.close()
        if log:
            log.close()
        with _ACTIVE_LOCK:
            _ACTIVE.discard(process)
