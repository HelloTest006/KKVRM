import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .card import CardError
from .config import config_path, find_blender, load, resolve_blender, save
from .locate import character_name, list_exports, resolve_input
from .meta import AVATAR, COMMERCIAL, CREDIT, MODIFICATION
from .pmx import PmxError, parse_path
from .runner import convert


def _cmd_config(args):
    updates = {}
    if args.blender:
        found = resolve_blender(args.blender)
        if not found:
            raise FileNotFoundError(f"blender.exe not found: {args.blender}")
        updates["blender"] = str(found.resolve())
    if args.export_root:
        updates["export_root"] = str(Path(args.export_root).expanduser().resolve())
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


def _flag_pair(left, right, message):
    if left and right:
        raise ValueError(message)


def _meta_overrides(args):
    _flag_pair(args.sexual_ok, args.no_sexual, "use only one of --sexual-ok and --no-sexual")
    _flag_pair(args.violent_ok, args.no_violent, "use only one of --violent-ok and --no-violent")
    _flag_pair(args.political_ok, args.no_political, "use only one of --political-ok and --no-political")
    _flag_pair(args.redistribute, args.no_redistribute, "use only one of --redistribute and --no-redistribute")
    _flag_pair(args.no_bust_lift, args.bust_lift is not None, "use only one of --bust-lift and --no-bust-lift")
    raw = {}
    if args.name:
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


def _convert_resolved(args, folder, card, game, output):
    if game == "koikatsu":
        print("card is Koikatsu, not Sunshine. KKBP Sunshine exporter may still load it.", file=sys.stderr)
    result = convert(
        folder,
        output,
        blender=args.blender,
        card=card,
        sfw=args.sfw,
        sexual_ok=args.sexual_ok,
        include_hidden=args.include_hidden,
        keep_blend=args.keep_blend,
        meta_file=args.meta,
        meta=_meta_overrides(args),
        bust_lift=0.0 if args.no_bust_lift else args.bust_lift,
        springs=not args.no_springs,
    )
    print(result["output"])
    return result


def _cmd_convert(args):
    source = Path(args.input).expanduser()
    jobs = list_exports(source) if source.is_dir() else []
    root = _export_root(args)
    if len(jobs) > 1:
        if args.name:
            raise ValueError("--name applies to one model. Omit it when converting a folder of exports")
        out_dir = Path(args.output) if args.output else Path.cwd()
        if out_dir.suffix.lower() == ".vrm":
            raise ValueError("batch convert needs an output directory, not a .vrm file")
        out_dir.mkdir(parents=True, exist_ok=True)
        used = set()
        for job in jobs:
            folder, card, game = resolve_input(job, export_root=root)
            label = character_name(folder)
            if label in used:
                label = folder.name
            used.add(label)
            _convert_resolved(args, folder, card, game, out_dir / f"{label}.vrm")
        return
    target = jobs[0] if jobs else source
    folder, card, game = resolve_input(target, export_root=root)
    label = args.name or character_name(folder)
    output = Path(args.output) if args.output else Path.cwd() / f"{label}.vrm"
    _convert_resolved(args, folder, card, game, output)


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
    convert_parser.add_argument("--no-springs", action="store_true", help="skip hair, skirt, and bust spring bones")
    convert_parser.add_argument("--bust-lift", type=float, help="push bust-weighted clothes out, in meters (default 0.006)")
    convert_parser.add_argument("--no-bust-lift", action="store_true", help="do not push clothes off the chest")
    convert_parser.add_argument("--meta", help="JSON file of VRM metadata and license fields")
    convert_parser.add_argument("--name", help="VRM name. Also used as the output filename when --output is omitted")
    convert_parser.add_argument("--author", action="append", help="author. Repeat for more than one. Replaces the default")
    convert_parser.add_argument("--vrm-version", help="VRM version string")
    convert_parser.add_argument("--copyright", help="copyright line")
    convert_parser.add_argument("--contact", help="contact information")
    convert_parser.add_argument("--reference", action="append", help="reference URL. Repeat to add more")
    convert_parser.add_argument("--license", help="third-party license text")
    convert_parser.add_argument("--license-url", help="other license URL")
    convert_parser.add_argument("--thumbnail", help="thumbnail image. Default is the card png")
    convert_parser.add_argument("--avatar", choices=AVATAR, help="who may use the avatar")
    convert_parser.add_argument("--commercial", choices=COMMERCIAL, help="commercial usage permission")
    convert_parser.add_argument("--credit", choices=CREDIT, help="credit notation")
    convert_parser.add_argument("--modification", choices=MODIFICATION, help="modification permission")
    convert_parser.add_argument("--sexual-ok", action="store_true", help="allow excessively sexual usage")
    convert_parser.add_argument("--no-sexual", action="store_true", help="deny excessively sexual usage")
    convert_parser.add_argument("--violent-ok", action="store_true", help="allow excessively violent usage")
    convert_parser.add_argument("--no-violent", action="store_true", help="deny excessively violent usage")
    convert_parser.add_argument("--political-ok", action="store_true", help="allow political or religious usage")
    convert_parser.add_argument("--no-political", action="store_true", help="deny political or religious usage")
    convert_parser.add_argument("--redistribute", action="store_true", help="allow redistribution")
    convert_parser.add_argument("--no-redistribute", action="store_true", help="deny redistribution")
    convert_parser.set_defaults(func=_cmd_convert)

    inspect_parser = sub.add_parser("inspect", help="show bones, morphs, and textures in a KKBP export")
    inspect_parser.add_argument("input")
    inspect_parser.add_argument("--export-root")
    inspect_parser.set_defaults(func=_cmd_inspect)

    config_parser = sub.add_parser("config", help="show or set blender and export-root paths")
    config_parser.add_argument("--blender")
    config_parser.add_argument("--export-root")
    config_parser.set_defaults(func=_cmd_config)

    check_parser = sub.add_parser("check", help="print the blender path that convert will use")
    check_parser.add_argument("--blender")
    check_parser.set_defaults(func=lambda args: print(find_blender(args.blender)))

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (CardError, FileNotFoundError, RuntimeError, PmxError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
