import re
from pathlib import Path

from .bones import match_humanoid
from .locate import character_name
from .physics import plan_physics
from .physics_sources import load_sources, source_summary
from .pmx import PmxError, parse_path


def inspect_export(folder, physics=False, options=None):
    folder = Path(folder).resolve()
    options = options or {}
    pmx_files = sorted(folder.rglob("*.pmx"))
    report = {"folder": str(folder), "name": character_name(folder),
              "pmx": [str(path) for path in pmx_files],
              "png_count": sum(1 for _ in folder.rglob("*.png"))}
    primary = next((path for path in pmx_files if path.parent == folder), None)
    if primary is None and pmx_files:
        primary = max(pmx_files, key=lambda path: path.stat().st_size)
    records, parsing_errors = {}, []
    for path in pmx_files:
        outfit = re.search(r"Outfit\s+(\d+)", str(path.relative_to(folder)), re.IGNORECASE)
        if options.get("outfit") is not None and outfit and int(outfit.group(1)) != options["outfit"]:
            continue
        if not physics and path != primary:
            continue
        try:
            data = parse_path(path)
        except (PmxError, OSError) as exc:
            parsing_errors.append(f"{path.name}: {exc}")
            continue
        if path == primary:
            report.update(primary_pmx=str(path), bones=data["bones"], morphs=data["morphs"],
                          materials=data["materials"], textures=data["textures"])
        for detail in data["bone_details"]:
            # KKBP's PMX root uses parent index 0 (itself); mmd_tools treats it as a root.
            parent = None if detail["index"] == 0 and detail["parent_index"] == 0 else detail["parent"]
            records.setdefault(detail["name"], {"name": detail["name"], "parent": parent,
                                               "aliases": [detail["english_name"]]})
    if parsing_errors:
        report["pmx_errors"] = parsing_errors
    humanoid, missing = match_humanoid(records)
    report["humanoid"] = {"mapped": humanoid, "missing_required": missing}
    if physics:
        sources = load_sources(folder)
        planned = plan_physics(list(records.values()), options.get("physics"), sources,
                               humanoid=humanoid, outfit=options.get("outfit"))
        for chain in planned["chains"]:
            chain.pop("data", None)
        report["physics_sources"] = source_summary(sources)
        report["physics"] = planned
        report["physics"]["note"] = "Source candidates only; use --deep to verify weights after Blender import."
    return report
