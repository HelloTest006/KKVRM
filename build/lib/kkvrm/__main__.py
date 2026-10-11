import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import __version__
from .card import CardError, identify_path
from .config import config_path, find_blender, load, resolve_blender, save
from .locate import character_name, find_card, list_exports, resolve_input
from .meta import AVATAR, COMMERCIAL, CREDIT, MODIFICATION
from .outputs import backup_existing, safe_stem
from .pmx import PmxError, parse_path
from .runner import convert, resolve_meta


def _cmd_config(args):
    updates = {}
    if args.blender:
        found = resolve_blender(args.blender)
        if not found:
            raise FileNotFoundError(f"blender.exe not found: {args.blender}")
        updates["blender"] = str(found.resolve())
    if args.export_root:
        updates["export_root"] = str(Path(args.export_root).expanduser().resolve())
    stored = _meta_overrides(args)
    if stored:
        merged = dict(load().get("meta") or {})
        merged.update(stored)
        updates["meta"] = merged
    if args.clear_meta:
        save({"meta": None})
        print(f"cleared stored metadata from {config_path()}")
        return
    if updates:
        path = save(updates)
        print(path)
        return
    data = load()
    data["config"] = str(config_path())
    print(json.dumps(data, indent=2))


def _inspect_folder(folder, card, game):
    pmx_files = sorted(Path(folder).rglob("*.pmx"))
    png_files = sorted(Path(folder).rglob("*.png"))
    primary = next((path for path in pmx_files if path.parent == Path(folder)), None)
    if primary is None and pmx_files:
        primary = max(pmx_files, key=lambda path: path.stat().st_size)
    report = {
        "folder": str(folder),
        "name": character_name(folder),
        "game": game,
        "card": str(card) if card else None,
        "pmx": [str(path) for path in pmx_files],
        "png_count": len(png_files),
    }
    if primary:
        try:
            parsed = parse_path(primary)
        except PmxError as exc:
            report["pmx_error"] = str(exc)
        else:
            report["primary_pmx"] = str(primary)
            report["bones"] = parsed["bones"]
            report["morphs"] = parsed["morphs"]
            report["materials"] = parsed["materials"]
            report["textures"] = parsed["textures"]
    return report


def _cmd_inspect(args):
    config = load()
    folder, card, game = resolve_input(args.input, export_root=args.export_root or config.get("export_root"))
    print(json.dumps(_inspect_folder(folder, card, game), indent=2))


def add_meta_flags(parser):
    """Shared by convert (apply once) and config (store as defaults)."""
    parser.add_argument("--author", action="append", help="author. Repeat for more than one. Replaces the default")
    parser.add_argument("--vrm-version", help="VRM version string")
    parser.add_argument("--copyright", help="copyright line")
    parser.add_argument("--contact", help="contact information")
    parser.add_argument("--reference", action="append", help="reference URL. Repeat to add more")
    parser.add_argument("--license", help="third-party license text")
    parser.add_argument("--license-url", help="other license URL")
    parser.add_argument("--thumbnail", help="thumbnail image. Default is the card png")
    parser.add_argument("--avatar", choices=AVATAR, help="who may use the avatar")
    parser.add_argument("--commercial", choices=COMMERCIAL, help="commercial usage permission")
    parser.add_argument("--credit", choices=CREDIT, help="credit notation")
    parser.add_argument("--modification", choices=MODIFICATION, help="modification permission")
    parser.add_argument("--sexual-ok", action="store_true", help="allow excessively sexual usage")
    parser.add_argument("--no-sexual", action="store_true", help="deny excessively sexual usage")
    parser.add_argument("--violent-ok", action="store_true", help="allow excessively violent usage")
    parser.add_argument("--no-violent", action="store_true", help="deny excessively violent usage")
    parser.add_argument("--political-ok", action="store_true", help="allow political or religious usage")
    parser.add_argument("--no-political", action="store_true", help="deny political or religious usage")
    parser.add_argument("--redistribute", action="store_true", help="allow redistribution")
    parser.add_argument("--no-redistribute", action="store_true", help="deny redistribution")


def _describe_export(folder, card, game):
    pmx_files = sorted(Path(folder).glob("*.pmx"))
    primary = next((path for path in pmx_files), None)
    card_path = card if card and Path(card).is_file() else find_card(folder)
    return {
        "name": character_name(folder),
        "folder": str(folder),
        "game": game,
        "card": str(card_path) if card_path else None,
        "pmx": len(pmx_files),
        "modified": datetime.fromtimestamp(Path(folder).stat().st_mtime).isoformat(timespec="seconds"),
        "has_pmx": primary is not None,
    }


def _game_for(card, fallback=None):
    if fallback:
        return fallback
    if not card or not Path(card).is_file():
        return None
    try:
        return identify_path(card)
    except (CardError, OSError):
        return None


def _cmd_list(args):
    config = load()
    source = Path(args.input).expanduser()
    roots = list_exports(source) if source.is_dir() else []
    found = []
    if roots:
        for folder in roots:
            found.append((folder, find_card(folder), None))
    else:
        folder, card, game = resolve_input(source, export_root=args.export_root or config.get("export_root"))
        found.append((folder, card, game))
    report = [_describe_export(folder, card, _game_for(card, game)) for folder, card, game in found]
    print(json.dumps(report, indent=2))


def _flag_pair(left, right, message):
    if left and right:
        raise ValueError(message)


def _meta_overrides(args):
    _flag_pair(getattr(args, "sexual_ok", False), args.no_sexual, "use only one of --sexual-ok and --no-sexual")
    _flag_pair(getattr(args, "violent_ok", False), args.no_violent, "use only one of --violent-ok and --no-violent")
    _flag_pair(args.political_ok, args.no_political, "use only one of --political-ok and --no-political")
    _flag_pair(args.redistribute, args.no_redistribute, "use only one of --redistribute and --no-redistribute")
    if getattr(args, "no_bust_lift", False) and args.bust_lift is not None:
        raise ValueError("use only one of --bust-lift and --no-bust-lift")
    raw = {}
    if getattr(args, "name", None):
        raw["name"] = args.name
    if args.author:
        raw["authors"] = args.author
    if args.vrm_version:
        raw["version"] = args.vrm_version
    if args.copyright:
        raw["copyright"] = args.copyright
    if args.contact:
        raw["contact"] = args.contact
    if args.reference:
        raw["references"] = args.reference
    if args.license:
        raw["license"] = args.license
    if args.license_url:
        raw["license_url"] = args.license_url
    if args.thumbnail:
        raw["thumbnail"] = args.thumbnail
    if args.avatar:
        raw["avatar_permission"] = args.avatar
    if args.commercial:
        raw["commercial_usage"] = args.commercial
    if args.credit:
        raw["credit"] = args.credit
    if args.modification:
        raw["modification"] = args.modification
    if args.violent_ok:
        raw["allow_violent"] = True
    if args.no_violent:
        raw["allow_violent"] = False
    if args.no_sexual:
        raw["allow_sexual"] = False
    if args.political_ok:
        raw["allow_political"] = True
    if args.no_political:
        raw["allow_political"] = False
    if args.redistribute:
        raw["allow_redistribution"] = True
    if args.no_redistribute:
        raw["allow_redistribution"] = False
    return raw


def _export_root(args):
    if args.export_root:
        return args.export_root
    return load().get("export_root")


def _claim_output(output, force):
    """Back up an existing target unless --force, so a rerun never loses data."""
    output = Path(output)
    if output.is_file():
        if force:
            print(f"overwriting {output}", file=sys.stderr)
        else:
            backup = backup_existing(output)
            print(f"{output} exists, kept the old one at {backup}", file=sys.stderr)
    return output


def _convert_resolved(args, folder, card, game, output, config_meta=None):
    if game == "koikatsu":
        print("card is Koikatsu, not Sunshine. KKBP Sunshine exporter may still load it.", file=sys.stderr)
    result = convert(
        folder,
        _claim_output(output, args.force),
        blender=args.blender,
        card=card,
        sfw=args.sfw,
        sexual_ok=args.sexual_ok,
        include_hidden=args.include_hidden,
        keep_blend=args.keep_blend,
        meta_file=args.meta,
        meta=_meta_overrides(args),
        config_meta=config_meta,
        bust_lift=0.0 if args.no_bust_lift else args.bust_lift,
        springs=not args.no_springs,
        verbose=args.verbose,
        quiet=args.quiet,
        dry_run=args.dry_run,
    )
    print(result["output"])
    return result


def _label_for(args, folder, info, template):
    if args.name:
        return args.name
    return safe_stem(
        template.format(name=character_name(folder), folder=folder.name, version=info.get("version", "")),
        fallback=folder.name,
    )


def _cmd_convert(args):
    source = Path(args.input).expanduser()
    jobs = list_exports(source) if source.is_dir() else []
    root = _export_root(args)
    config_meta = load().get("meta")
    targets = jobs or [source]
    if len(targets) > 1 and args.name:
        raise ValueError("--name applies to one model. Omit it when converting a folder of exports")
    out_dir = None
    if len(targets) > 1:
        out_dir = Path(args.output) if args.output else Path.cwd()
        if out_dir.suffix.lower() == ".vrm":
            raise ValueError("batch convert needs an output directory, not a .vrm file")
        out_dir.mkdir(parents=True, exist_ok=True)
    template = args.name_template or "{name}"
    uses_template = bool(args.name_template) and not args.name
    planned = []
    used = {}
    for target in targets:
        folder, card, game = resolve_input(target, export_root=root)
        if uses_template or len(targets) > 1:
            info = resolve_meta(
                folder,
                meta=_meta_overrides(args),
                meta_file=args.meta,
                sexual_ok=args.sexual_ok,
                config_meta=config_meta,
            )
            label = _label_for(args, folder, info, template)
        else:
            label = args.name or character_name(folder)
        if label in used:
            label = folder.name
            if label in used:
                raise ValueError(f"two exports both resolve to '{label}', use --name-template")
        used[label] = folder
        if out_dir is not None:
            output = out_dir / f"{label}.vrm"
        else:
            output = Path(args.output) if args.output else Path.cwd() / f"{label}.vrm"
        planned.append((folder, card, game, output))
    failures = []

    def work(item):
        folder, card, game, output = item
        try:
            _convert_resolved(args, folder, card, game, output, config_meta=config_meta)
        except Exception as exc:
            failures.append((character_name(folder), exc))

    if args.jobs > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            list(pool.map(work, planned))
    else:
        for item in planned:
            work(item)
    if failures:
        done = len(planned) - len(failures)
        print(f"{done} converted, {len(failures)} failed", file=sys.stderr)
        for label, error in failures:
            print(f"  {label}: {str(error).splitlines()[0]}", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kkvrm", description="Convert a KKBP Koikatsu Sunshine export to VRM 1.0")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    convert_parser = sub.add_parser("convert", help="import a KKBP export in Blender and write a .vrm")
    convert_parser.add_argument("input", help="KKBP export folder, or a card .png inside one")
    convert_parser.add_argument("-o", "--output", help="output .vrm path")
    convert_parser.add_argument("--blender", help="path to blender.exe")
    convert_parser.add_argument("--export-root", help="folder to search when the card is not inside an export")
    convert_parser.add_argument("--sfw", action="store_true", help="use KKBP SFW mode")
    convert_parser.add_argument("--include-hidden", action="store_true", help="export hidden meshes except hitboxes")
    convert_parser.add_argument("--keep-blend", action="store_true", help="save a .blend next to the .vrm")
    convert_parser.add_argument("--force", action="store_true", help="overwrite the output instead of backing it up to .bak")
    convert_parser.add_argument("--dry-run", action="store_true", help="print the resolved options and Blender command, then exit")
    convert_parser.add_argument("--verbose", action="store_true", help="echo Blender output while converting")
    convert_parser.add_argument("--quiet", action="store_true", help="suppress the log tail when a convert fails")
    convert_parser.add_argument("--jobs", type=int, default=1, help="convert this many models at once. Each runs its own Blender, so keep this low")
    convert_parser.add_argument("--name-template", help="output name pattern for a batch. Fields: {name}, {folder}, {version}. Default {name}")
    convert_parser.add_argument("--no-springs", action="store_true", help="skip hair, skirt, and bust spring bones")
    convert_parser.add_argument("--bust-lift", type=float, help="push bust-weighted clothes out, in meters (default 0.006)")
    convert_parser.add_argument("--no-bust-lift", action="store_true", help="do not push clothes off the chest")
    convert_parser.add_argument("--meta", help="JSON file of VRM metadata and license fields")
    convert_parser.add_argument("--name", help="VRM name. Also used as the output filename when --output is omitted")
    add_meta_flags(convert_parser)
    convert_parser.set_defaults(func=_cmd_convert)

    inspect_parser = sub.add_parser("inspect", help="show bones, morphs, and textures in a KKBP export")
    inspect_parser.add_argument("input")
    inspect_parser.add_argument("--export-root")
    inspect_parser.set_defaults(func=_cmd_inspect)

    list_parser = sub.add_parser("list", help="show the KKBP exports a path would convert")
    list_parser.add_argument("input", help="export folder, a folder of exports, or a card .png")
    list_parser.add_argument("--export-root")
    list_parser.set_defaults(func=_cmd_list)

    config_parser = sub.add_parser("config", help="show or set blender, export-root, and default metadata")
    config_parser.add_argument("--blender")
    config_parser.add_argument("--export-root")
    config_parser.add_argument("--clear-meta", action="store_true", help="forget stored metadata and license defaults")
    add_meta_flags(config_parser)
    config_parser.set_defaults(func=_cmd_config)

    check_parser = sub.add_parser("check", help="print the blender path that convert will use")
    check_parser.add_argument("--blender")
    check_parser.set_defaults(func=lambda args: print(find_blender(args.blender)))

    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (CardError, FileNotFoundError, RuntimeError, PmxError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
