import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import __version__
from .card import CardError, identify_path
from .config import config_path, find_blender, load, resolve_blender, save
from .inspection import inspect_export
from .jsonio import read_object, write_object
from .locate import character_name, find_card, list_exports, resolve_input
from .meta import AVATAR, COMMERCIAL, CREDIT, MODIFICATION, _apply, build_meta
from .options import merge_options, validate_options
from .outputs import format_stem, safe_stem
from .physics import CATEGORIES, PRESETS, merge_config
from .pmx import PmxError
from .profiles import list_profiles, load_profile, read_document, resolve_settings, save_profile
from .runner import cancel_active, convert, invoke
from .vrm import audit


def _print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def add_meta_flags(parser):
    parser.add_argument("--author", action="append", help="author; repeat to replace the author list")
    parser.add_argument("--vrm-version", help="VRM version string")
    parser.add_argument("--copyright")
    parser.add_argument("--contact")
    parser.add_argument("--reference", action="append", help="reference URL; repeat for multiple references")
    parser.add_argument("--license", help="third-party license text")
    parser.add_argument("--license-url", help="other license URL")
    parser.add_argument("--thumbnail", help="thumbnail image; defaults to the character card")
    parser.add_argument("--avatar", choices=AVATAR)
    parser.add_argument("--commercial", choices=COMMERCIAL)
    parser.add_argument("--credit", choices=CREDIT)
    parser.add_argument("--modification", choices=MODIFICATION)
    for allow, deny, help_text in (
        ("sexual-ok", "no-sexual", "excessively sexual usage"),
        ("violent-ok", "no-violent", "excessively violent usage"),
        ("political-ok", "no-political", "political or religious usage"),
        ("redistribute", "no-redistribute", "redistribution"),
    ):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(f"--{allow}", action="store_true", help=f"allow {help_text}")
        group.add_argument(f"--{deny}", action="store_true", help=f"deny {help_text}")


def _meta_overrides(args):
    result = {}
    for argument, field in (
        ("name", "name"), ("author", "authors"), ("vrm_version", "version"),
        ("copyright", "copyright"), ("contact", "contact"), ("reference", "references"),
        ("license", "license"), ("license_url", "license_url"), ("thumbnail", "thumbnail"),
        ("avatar", "avatar_permission"), ("commercial", "commercial_usage"),
        ("credit", "credit"), ("modification", "modification"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            result[field] = str(Path(value).expanduser().resolve()) if field == "thumbnail" else value
    for allow, deny, field in (
        ("sexual_ok", "no_sexual", "allow_sexual"), ("violent_ok", "no_violent", "allow_violent"),
        ("political_ok", "no_political", "allow_political"),
        ("redistribute", "no_redistribute", "allow_redistribution"),
    ):
        if getattr(args, allow, False):
            result[field] = True
        elif getattr(args, deny, False):
            result[field] = False
    return result


def add_conversion_options(parser):
    for option, help_text in (
        ("sfw", "KKBP SFW import"), ("include-hidden", "include hidden meshes except hitboxes"),
        ("keep-blend", "save a packed prepared .blend for fast re-export"),
        ("cache", "reuse an imported/prepared model when source and add-ons match"),
    ):
        parser.add_argument(f"--{option}", action=argparse.BooleanOptionalAction, default=None, help=help_text)
    parser.add_argument("--profile", help="saved profile name or profile JSON path")
    parser.add_argument("--model-config", help="model settings JSON; otherwise reads EXPORT/kkvrm.json")
    parser.add_argument("--physics-preset", choices=PRESETS)
    parser.add_argument("--physics-config", help="JSON containing spring settings, explicit chains and exclusions")
    parser.add_argument("--colliders", choices=("none", "auto", "source"))
    for category in CATEGORIES:
        parser.add_argument(f"--{category}-physics", choices=("on", "off"))
    parser.add_argument("--no-springs", action="store_true", help="disable every physics category")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--bust-lift", type=float, help="clothing offset in meters (default 0.006)")
    group.add_argument("--no-bust-lift", action="store_true", help="disable clothing offset")
    parser.add_argument("--bust-material", action="append", help="limit offset to material-name patterns")
    parser.add_argument("--height", help="auto, keep, or target height in meters")
    parser.add_argument("--outfit", type=int, help="export only this outfit index")
    parser.add_argument("--include-mesh", action="append", help="include only matching mesh names (repeatable)")
    parser.add_argument("--exclude-mesh", action="append", help="exclude matching mesh names (repeatable)")
    parser.add_argument("--material-config", help="JSON material-name patterns with alpha_mode/cutoff/double_sided")


def _conversion_overrides(args):
    result = {}
    for field in ("sfw", "include_hidden", "keep_blend", "cache", "height", "outfit", "include_mesh", "exclude_mesh", "bust_lift"):
        value = getattr(args, field, None)
        if value is not None:
            result[field] = value
    if getattr(args, "no_bust_lift", False):
        result["bust_lift"] = 0.0
    if getattr(args, "bust_material", None):
        result["bust_materials"] = args.bust_material
    if getattr(args, "material_config", None):
        result["material_overrides"] = read_object(args.material_config)
    physics = read_object(args.physics_config) if getattr(args, "physics_config", None) else {}
    if getattr(args, "physics_preset", None):
        physics["preset"] = args.physics_preset
    if getattr(args, "colliders", None):
        physics["colliders"] = args.colliders
    switches = {kind: getattr(args, f"{kind}_physics", None) for kind in CATEGORIES}
    if getattr(args, "no_springs", False):
        if any(value == "on" for value in switches.values()):
            raise ValueError("--no-springs conflicts with an enabled physics category")
        switches = {kind: False for kind in CATEGORIES}
    for kind, value in switches.items():
        if value is not None:
            physics = merge_config(physics, {"types": {kind: value}})
    if physics:
        result["physics"] = physics
    return result


def _cmd_config(args):
    current = load()
    updates = {}
    if args.blender:
        found = resolve_blender(args.blender)
        if not found:
            raise FileNotFoundError(f"blender.exe not found: {args.blender}")
        updates["blender"] = str(found.resolve())
    if args.export_root:
        updates["export_root"] = str(Path(args.export_root).expanduser().resolve())
    metadata = _meta_overrides(args)
    if metadata:
        merged = dict(current.get("meta") or {})
        _apply(merged, metadata)
        build_meta("Koikatsu", overrides=merged)
        updates["meta"] = merged
    options = _conversion_overrides(args)
    if options:
        merged = merge_options(current.get("options", {}), options)
        validate_options(merged)
        updates["options"] = merged
    if args.profile:
        load_profile(args.profile)
        updates["default_profile"] = args.profile
    if args.clear_meta:
        updates["meta"] = None
    if args.clear_options:
        updates["options"] = None
    if args.clear_profile:
        updates["default_profile"] = None
    if updates:
        print(save(updates))
    else:
        _print_json(dict(current, config=str(config_path())))


def _settings(args, folder, stored, base_document=None, overrides=None):
    return resolve_settings(folder, profile=args.profile, stored=stored,
                            model_config=getattr(args, "model_config", None),
                            overrides=_conversion_overrides(args) if overrides is None else overrides,
                            meta=_meta_overrides(args), meta_file=getattr(args, "meta", None),
                            sexual_ok=getattr(args, "sexual_ok", False), base_document=base_document)


def _cmd_inspect(args):
    source = Path(args.input).expanduser()
    if source.suffix.lower() == ".vrm" and source.is_file():
        report = audit(source)
        _print_json(report)
        return 0 if report["ok"] else 1
    stored = load()
    folder, card, game = resolve_input(source, export_root=args.export_root or stored.get("export_root"))
    settings = _settings(args, folder, stored)
    report = inspect_export(folder, physics=args.physics or args.deep, options=settings["options"])
    report.update(card=str(card) if card else None, game=game, resolved=settings)
    if args.deep:
        report["post_import"] = invoke({"action": "inspect", "import_dir": str(folder),
                                         "options": settings["options"], "meta": settings["meta"],
                                         "sfw": settings["options"]["sfw"]},
                                        blender=args.blender, timeout=args.timeout)
    _print_json(report)


def _game_for(card, fallback=None):
    if fallback or not card:
        return fallback
    try:
        return identify_path(card)
    except (CardError, OSError):
        return None


def _cmd_list(args):
    stored = load()
    source = Path(args.input).expanduser()
    roots = list_exports(source) if source.is_dir() else []
    if roots:
        found = [(folder.resolve(), find_card(folder), None) for folder in roots]
    else:
        found = [resolve_input(source, export_root=args.export_root or stored.get("export_root"))]
    report = []
    for folder, card, game in found:
        pmx = sorted(folder.glob("*.pmx"))
        report.append({"name": character_name(folder), "folder": str(folder),
                       "game": _game_for(card, game), "card": str(card) if card else None,
                       "pmx": len(pmx), "has_pmx": bool(pmx),
                       "pmx_bytes": sum(path.stat().st_size for path in pmx),
                       "modified": datetime.fromtimestamp(folder.stat().st_mtime).isoformat(timespec="seconds")})
    _print_json(report)


def _convert_resolved(args, folder, card, game, output, settings):
    if game == "koikatsu" and not args.quiet:
        print("Koikatsu card detected; importer compatibility will be checked by Blender.", file=sys.stderr)
    return convert(folder, output, blender=args.blender, card=card,
                   meta_info=settings["meta"], options=settings["options"], provenance=settings["provenance"],
                   bust_lift=args.bust_lift, springs=False if args.no_springs else None,
                   keep_blend=bool(settings["options"]["keep_blend"]),
                   force=args.force, dry_run=args.dry_run, verbose=args.verbose, quiet=args.quiet,
                   timeout=args.timeout, report=not args.no_report,
                   cache_root=args.cache_dir)


def _cmd_convert(args):
    if args.jobs < 1:
        raise ValueError("jobs must be at least 1")
    source = Path(args.input).expanduser()
    roots = list_exports(source) if source.is_dir() else []
    targets = roots or [source]
    if roots and args.name:
        raise ValueError("--name applies to one model; use --name-template for a batch")
    out_dir = (Path(args.output).expanduser() if args.output else Path.cwd()) if roots else None
    if out_dir is not None and out_dir.suffix.lower() == ".vrm":
        raise ValueError("batch convert needs an output directory, not a .vrm file")
    stored = load()
    overrides = _conversion_overrides(args)
    planned, used, origins, failures = [], set(), set(), []
    for target in targets:
        try:
            folder, card, game = resolve_input(target, export_root=args.export_root or stored.get("export_root"))
            origin = os.path.normcase(str(folder))
            if origin in origins:
                raise ValueError("the same export was resolved twice")
            origins.add(origin)
            settings = _settings(args, folder, stored, overrides=overrides)
            label = safe_stem(args.name) if args.name else format_stem(args.name_template or "{name}",
                         name=settings["meta"]["name"], folder=folder.name, version=settings["meta"]["version"])
            if label.casefold() in used:
                label = safe_stem(folder.name)
            if label.casefold() in used:
                raise ValueError(f"output name collision: {label}; change --name-template")
            used.add(label.casefold())
            output = out_dir / f"{label}.vrm" if out_dir is not None else Path(args.output).expanduser() if args.output else Path.cwd() / f"{label}.vrm"
            planned.append((folder, card, game, output, settings))
        except (ValueError, OSError, CardError) as exc:
            if not roots:
                raise
            failures.append({"input": str(target), "ok": False, "error": str(exc)})

    results = []

    def work(item):
        folder, card, game, output, settings = item
        try:
            result = _convert_resolved(args, folder, card, game, output, settings)
            return dict(result, input=str(folder))
        except (ValueError, OSError, RuntimeError) as exc:
            return {"ok": False, "input": str(folder), "output": str(output), "error": str(exc)}

    if args.jobs > 1 and len(planned) > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            pending = [pool.submit(work, item) for item in planned]
            try:
                for future in as_completed(pending):
                    results.append(future.result())
            except KeyboardInterrupt:
                cancel_active()
                for future in pending:
                    future.cancel()
                raise
    else:
        results = [work(item) for item in planned]
    for result in results:
        if result.get("ok", True):
            print(result["output"])
        else:
            failures.append(result)
    for failure in failures:
        print(f"failed {Path(failure['input']).name}: {failure['error']}", file=sys.stderr)
    completed = sum(result.get("ok", True) for result in results)
    if roots or failures:
        noun = "planned" if args.dry_run else "converted"
        print(f"{completed} {noun}, {len(failures)} failed", file=sys.stderr)
    if args.batch_report and not args.dry_run:
        write_object(Path(args.batch_report).expanduser(), {
            "ok": not failures, "converted": completed, "failed": len(failures),
            "results": sorted(results + [failure for failure in failures if failure not in results], key=lambda item: item["input"]),
        })
    return 1 if failures else 0


def _cmd_check(args):
    if args.path_only:
        print(find_blender(args.blender))
        return 0
    result = invoke({"action": "check"}, blender=args.blender, timeout=args.timeout, quiet=True)
    _print_json(result)
    return 0 if result.get("ok") else 1


def _cmd_profile_list(args):
    _print_json(list_profiles())


def _cmd_profile_show(args):
    _print_json(load_profile(args.profile_name))


def _cmd_profile_save(args):
    document = read_document(args.from_file) if args.from_file else load_profile(args.profile) if args.profile else {"schema_version": 1, "meta": {}, "options": {}}
    metadata = {}
    _apply(metadata, document["meta"])
    _apply(metadata, _meta_overrides(args))
    document["meta"] = metadata
    document["options"] = merge_options(document["options"], _conversion_overrides(args))
    print(save_profile(args.profile_name, document, force=args.force))


def _cmd_reexport(args):
    from .runner import prepared_info, reexport

    project = prepared_info(args.input, blender=args.blender, timeout=args.timeout, allow_launch=not args.dry_run)
    folder = Path(project.get("import_dir") or Path(args.input).parent)
    settings = _settings(args, folder, load(), base_document=project.get("settings"))
    output = Path(args.output) if args.output else Path(args.input).with_suffix(".vrm")
    result = reexport(args.input, output, blender=args.blender, options=settings["options"],
                      meta_info=settings["meta"], provenance=settings["provenance"],
                      dry_run=args.dry_run, force=args.force, verbose=args.verbose, quiet=args.quiet,
                      timeout=args.timeout, report=not args.no_report)
    print(result["output"])


def add_execution_flags(parser):
    parser.add_argument("-o", "--output")
    parser.add_argument("--blender")
    parser.add_argument("--name", help="VRM name and default output filename")
    parser.add_argument("--meta", help="metadata JSON overrides")
    parser.add_argument("--force", action="store_true", help="replace previous export without keeping .vrm.bak")
    parser.add_argument("--dry-run", action="store_true", help="resolve settings without filesystem changes or Blender launch")
    logs = parser.add_mutually_exclusive_group()
    logs.add_argument("--verbose", action="store_true", help="stream all Blender output")
    logs.add_argument("--quiet", action="store_true", help="only display outputs and errors")
    parser.add_argument("--timeout", type=float, default=1800, help="Blender timeout in seconds")
    parser.add_argument("--no-report", action="store_true", help="skip the conversion .report.json")
    add_conversion_options(parser)
    add_meta_flags(parser)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kkvrm", description="Convert KKBP exports to VRM 1.0 with configurable physics")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    conversion = sub.add_parser("convert", help="convert one export or a directory of exports")
    conversion.add_argument("input")
    conversion.add_argument("--export-root")
    conversion.add_argument("--jobs", type=int, default=1, help="parallel Blender instances; each consumes substantial RAM")
    conversion.add_argument("--name-template", help="{name}, {folder}, {version}; no path components")
    conversion.add_argument("--batch-report", help="write a JSON batch summary")
    conversion.add_argument("--cache-dir", help="prepared-model cache directory")
    add_execution_flags(conversion)
    conversion.set_defaults(func=_cmd_convert)

    reexport_parser = sub.add_parser("reexport", help="re-export a packed prepared .blend without KKBP import")
    reexport_parser.add_argument("input")
    add_execution_flags(reexport_parser)
    reexport_parser.set_defaults(func=_cmd_reexport)

    inspection = sub.add_parser("inspect", help="inspect export candidates or audit a VRM")
    inspection.add_argument("input")
    inspection.add_argument("--export-root")
    inspection.add_argument("--physics", action="store_true", help="show source candidates and physics plan")
    inspection.add_argument("--deep", action="store_true", help="use Blender to verify imported weights and rig")
    inspection.add_argument("--blender")
    inspection.add_argument("--timeout", type=float, default=1800)
    inspection.add_argument("--meta")
    add_conversion_options(inspection)
    add_meta_flags(inspection)
    inspection.set_defaults(func=_cmd_inspect)

    listing = sub.add_parser("list", help="list the exports a path would convert")
    listing.add_argument("input")
    listing.add_argument("--export-root")
    listing.set_defaults(func=_cmd_list)

    config = sub.add_parser("config", help="show or store paths, metadata and conversion defaults")
    config.add_argument("--blender")
    config.add_argument("--export-root")
    config.add_argument("--clear-meta", action="store_true")
    config.add_argument("--clear-options", action="store_true")
    config.add_argument("--clear-profile", action="store_true")
    add_conversion_options(config)
    add_meta_flags(config)
    config.set_defaults(func=_cmd_config)

    check = sub.add_parser("check", help="check Blender, installed extensions and required APIs")
    check.add_argument("--blender")
    check.add_argument("--path-only", action="store_true", help="only print Blender path")
    check.add_argument("--timeout", type=float, default=60)
    check.set_defaults(func=_cmd_check)

    profile = sub.add_parser("profile", help="list, inspect or save conversion profiles")
    commands = profile.add_subparsers(dest="profile_command", required=True)
    commands.add_parser("list").set_defaults(func=_cmd_profile_list)
    show = commands.add_parser("show")
    show.add_argument("profile_name")
    show.set_defaults(func=_cmd_profile_show)
    save_parser = commands.add_parser("save")
    save_parser.add_argument("profile_name")
    save_parser.add_argument("--from", dest="from_file", help="profile JSON to import")
    save_parser.add_argument("--force", action="store_true")
    add_conversion_options(save_parser)
    add_meta_flags(save_parser)
    save_parser.set_defaults(func=_cmd_profile_save)

    args = parser.parse_args(argv)
    try:
        if hasattr(args, "timeout") and (not math.isfinite(args.timeout) or args.timeout <= 0):
            raise ValueError("timeout must be positive and finite")
        return args.func(args) or 0
    except KeyboardInterrupt:
        cancel_active()
        print("cancelled; previous export retained", file=sys.stderr)
        return 130
    except (CardError, OSError, RuntimeError, PmxError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
