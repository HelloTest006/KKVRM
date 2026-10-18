# KKVRM

Convert Koikatsu/Sunshine KKBP exports to VRM 1.0 with humanoid bones, expressions, MToon textures, and configurable hair/clothing physics.

A character `.png` contains no mesh. Export the character from the game with [KKBP Exporter](https://gitgoon.dev/kkbp-dev/KKBP_Exporter) first. KKVRM drives Blender's KKBP importer and VRM exporter.

## Requirements

- Koikatsu Sunshine, KKBP Exporter, and the character's required mods.
- Blender with [KKBP Importer](https://gitgoon.dev/kkbp-dev/KKBP_Importer), [mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/), and [VRM Add-on](https://vrm-addon-for-blender.info/).
- Python 3.10+.

Verified integration: Blender 5.2.1, KKBP 9.4.4, mmd_tools 4.5.14, VRM add-on 4.6.0. Extensions must be installed under their full `bl_ext.…` module IDs.

```text
python -m kkvrm config --blender "C:\Blender\blender.exe"
python -m kkvrm check
```

`check` reports versions and required APIs. `check --path-only` prints only Blender's path. The host CLI uses the Python standard library; image processing runs inside Blender.

## Quick start

Export from character maker in T-pose, without freezing shape keys. Then:

```text
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" -o Name.vrm
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" --profile cloth-balanced --keep-blend --cache -o Name.vrm
```

The default `legacy` preset uses the previous hair/skirt/bust settings. Branches are split into valid, nonoverlapping spring chains. `cloth-balanced` adds source-aware cloth/hair detection, terminal helpers when needed, and body colliders.

Spring physics reuses **existing weighted bones**. It does not automatically rig an unweighted garment or run a mesh cloth simulation. Reports identify skipped/unweighted chains.

## Inspect before exporting

```text
python -m kkvrm list "D:\KKS\Export_PMX"
python -m kkvrm inspect "D:\KKS\Export_PMX\20260119_Name" --physics --profile cloth-balanced
python -m kkvrm inspect "D:\KKS\Export_PMX\20260119_Name" --physics --deep --profile cloth-balanced
python -m kkvrm inspect Name.vrm
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" --profile cloth-balanced --dry-run
```

- Lightweight inspection reads PMX hierarchy and KKBP sidecars; its chains are candidates, not proof of skin weights.
- `--deep` imports through Blender and checks the actual rig and positive weights on selected meshes. It can take as long as an import.
- VRM inspection validates humanoid references, joint ordering, duplicate chains, centers, and colliders.
- Dry-run resolves settings and their override sources without launching Blender, creating output directories, or moving existing files. `<ARGS_JSON>` marks the runtime argument file in its command preview.

A card inside an export also works. A copied card can locate its export using `--export-root` or the configured export root.

## Physics options

| Option | Purpose |
| --- | --- |
| `--hair-physics on/off` | Hair and ponytails |
| `--cloth-physics on/off` | Existing ribbon, scarf, cape, coat, or hem chains |
| `--skirt-physics on/off` | Skirt chains |
| `--accessory-physics on/off` | Recognized accessory chains |
| `--bust-physics on/off` | Suitable existing bust chains; base/scale/hit bones are protected |
| `--no-springs` | Disable every category |
| `--physics-preset legacy/balanced/soft/stiff` | Initial joint settings |
| `--colliders none/auto/source` | No collisions, fitted body proxies, or supported source colliders |
| `--physics-config file.json` | Explicit chains, exclusions, category and per-joint settings |

Source-aware detection reads `KK_DynamicBoneData.json` and renderer associations from `KK_SMRData.json`, then resolves renamed bones against the imported armature. Missing sidecars fall back to known hair/skirt/bust prefixes. Unclassified body systems are not treated as accessories.

DynamicBone topology is reused; VRM presets approximate motion. Elasticity/inertia are not copied as if they were equivalent VRM parameters. `source` colliders use supported sphere/capsule geometry, metric reprojection, and conservative radii for nonuniform scales. Unsupported inside/floor/missing-target colliders are reported. Collision groups attach only to applicable springs.

Example `physics.json`:

```json
{
  "preset": "balanced",
  "types": { "hair": true, "cloth": true, "bust": false },
  "colliders": "auto",
  "endpoints": true,
  "settings": {
    "hair": { "stiffness": 0.6, "drag_force": 0.85 }
  },
  "joint_settings": {
    "cf_J_hairBL_03": { "stiffness": 0.25 }
  },
  "exclude": ["unwanted_chain*"],
  "chains": [
    {
      "name": "LeftRibbon",
      "category": "cloth",
      "root": "ribbon_LA0",
      "center": "chest",
      "settings": { "stiffness": 0.8, "gravity_power": 0.02 }
    }
  ]
}
```

Custom chains specify `root` **or** ordered `bones`. Centers accept a bone name, humanoid slot, or `world`. Exclusions match current/original bone names and their subtrees. Supported settings: `hit_radius`, `stiffness`, `gravity_power`, `drag_force`, `gravity_dir`. Radii/offsets use meters; config gravity vectors use Blender Z-up coordinates and are normalized before export. Explicit chains take priority over automatic detection.

## Profiles and model settings

```text
python -m kkvrm profile list
python -m kkvrm profile show cloth-balanced
python -m kkvrm profile save mine --profile cloth-balanced --author "Mika" --height keep --cache --keep-blend
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" --profile mine
python -m kkvrm config --profile mine
python -m kkvrm config --clear-profile
```

Built-ins: `legacy`, `cloth-balanced`, `hair-soft`. Save with `--from PROFILE.json` to import a file; use `--force` to replace a saved profile. Saved profiles live beside the user config in `profiles/`.

Put model-specific settings in `EXPORT/kkvrm.json`, or pass `--model-config`:

```json
{
  "schema_version": 1,
  "meta": { "authors": ["Mika"], "version": "2.0.0" },
  "options": {
    "outfit": 0,
    "height": "keep",
    "physics": { "preset": "balanced", "types": { "cloth": true } }
  }
}
```

Precedence, last wins: built-in defaults → stored config → selected profile → model config → metadata file → command flags. Nested physics category/settings overrides merge. Thumbnail paths in JSON files are relative to those files. Unknown fields are rejected.

## Cached import and fast re-export

```text
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" --cache --keep-blend -o Name.vrm
python -m kkvrm reexport Name.blend --profile cloth-balanced -o NamePhysics.vrm
python -m kkvrm reexport NamePhysics.blend --hair-physics off --no-keep-blend -o NameCloth.vrm
```

`--keep-blend` saves a **packed prepared snapshot**, before height/offset/spring export changes. It also retains reusable normals and expression bindings. Re-export inherits snapshot settings; an explicit profile or flags can override them. Repeated exports apply clothing corrections once, not cumulatively. SFW is import-time and requires converting the original export to change.

Keep `.blend.json` beside `.blend` for lightweight settings resolution and dry-run. Without the companion, normal re-export can inspect the embedded project through Blender. A prepared snapshot includes original and cleaned texture images, source physics data, and its thumbnail for portable re-export.

`--cache` fingerprints source assets, import mode, converter code, Blender executable, and live extension versions. Physics/metadata/model-config changes reuse the import; source/import/version changes invalidate it. Cache writes are atomic and OS locks serialize access, including other KKVRM processes. Default cache: `%LOCALAPPDATA%/kkvrm/cache` on Windows. `--cache-dir` overrides it and must be outside the export folder. `--no-cache` bypasses it. Prepared caches can be large because textures are packed.

## Fidelity controls

- `--height auto` keeps models between 1.2–2.0 m and normalizes other sizes to 1.6 m; `keep` preserves scale; a number sets target height.
- `--outfit N` selects an outfit; shared body meshes remain available.
- `--include-mesh PATTERN` / `--exclude-mesh PATTERN` filter exported meshes; repeat flags for multiple patterns.
- `--include-hidden` includes hidden meshes in the active view layer. Hitboxes and excluded collections stay out.
- `--bust-lift METERS` defaults to 0.006; `--no-bust-lift` disables it. `--bust-material PATTERN` limits affected material vertices. Corrections use world-space distance and update every shape key consistently.
- `--material-config FILE.json` overrides alpha/culling for exceptional materials:

```json
{
  "KK custom_top*": { "alpha_mode": "MASK", "alpha_cutoff": 0.5, "double_sided": true }
}
```

Materials use light textures with flat MToon shading. Eyes use blending, skin/solid clothing use opaque rendering, and cutout clothing uses masks. Materials are double-sided by default. Known face keys bind to presets including `relaxed` and `surprised`; other keys remain custom expressions. No texture atlas, dark-texture shadow lift, or automatic reweighting.

## Metadata and licenses

```text
python -m kkvrm config --author "Mika" --license "Personal use only" --avatar onlyAuthor
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" --name Name --vrm-version 2.0 --license-url "https://example.com/license"
python -m kkvrm config --clear-meta
```

Flags: `--author` (repeatable), `--copyright`, `--contact`, `--reference` (repeatable), `--thumbnail`, `--license`, `--license-url`, `--avatar`, `--commercial`, `--credit`, `--modification`, `--vrm-version`.

Usage toggles: `--sexual-ok/--no-sexual`, `--violent-ok/--no-violent`, `--political-ok/--no-political`, `--redistribute/--no-redistribute`. Other metadata fields, including antisocial-usage permission, can be set with `--meta` JSON. Defaults remain author-only, personal non-profit, credit required, no redistribution/modification/violent/sexual usage. Profile `meta` objects use the same schema as metadata files.

## Batch, logs, and output recovery

```text
python -m kkvrm convert "D:\KKS\Export_PMX" -o "D:\VRMs" --jobs 2 --profile cloth-balanced --name-template "{name}_v{version}" --batch-report batch.json
```

A directory of exports always uses a directory output, including a batch containing one export. Names support `{name}`, `{folder}`, `{version}`; unsafe filename characters are sanitized and collisions are checked. Each job uses its own Blender, so choose concurrency according to available RAM.

Stage progress prints by default. `--verbose` streams all Blender output; `--quiet` suppresses progress/tails. `.log` is flushed during execution and retained on crashes/timeouts. `--timeout` sets the Blender timeout. Ctrl+C cancels active workers.

Blender writes to a temporary target. Only a completed, validated VRM replaces the destination. Previous `.vrm` becomes `.vrm.bak`; `--force` replaces without backup. Failed runs retain the previous avatar. `.report.json` includes resolved settings, physics/skipped chains, colliders, geometry corrections, timings and validation; `--no-report` disables it. Batch failures are isolated and return exit code 1; cancellation returns 130.

## Verification

```text
python -m unittest discover -s tests
blender --background --python-exit-code 1 --python tests/blender_checks.py
python tests/verify_artifacts.py New.vrm --baseline Previous.vrm
```

CI runs host tests on Windows/Python 3.10–3.14, including CLI packaging checks and a syntax pass over the Blender-only modules and scripts. Physics coverage includes chain splitting, branch handling, category and preset resolution, per-joint settings, weight-based candidate filtering, source sidecar parsing, endpoint creation, exclusions, and spring/collider VRM validation. `tests/blender_checks.py` covers metric offsets, morph deltas, normal cleanup, endpoints and auto/source colliders; `tests/blender_portability.py` re-packs cleaned alpha textures and the portrait after the original export paths are removed. Both need a local Blender with the three add-ons.

Artifact checks (`tests/verify_artifacts.py`) compare embedded texture pixels, transparency, UVs, rest geometry and morph counts. Physics integration was exercised in three-vrm 3.5.5 over 360 animated frames. Unity/UniVRM visual validation remains a manual runtime check.

Game assets are not included in this repository.
