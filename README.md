# KKVRM

Converts a Koikatsu Sunshine character to VRM 1.0: humanoid bones, extra bones, face shape keys, and baked textures.

A `.png` card does not contain the mesh. Export it from the game with [KKBP Exporter](https://gitgoon.dev/kkbp-dev/KKBP_Exporter) first. This tool takes that `Export_PMX` folder and drives Blender.

## Install

- Koikatsu Sunshine, HF Patch, KKBP Exporter (NET46 build) in `BepInEx/plugins`
- Blender 5.2 with [KKBP Importer](https://gitgoon.dev/kkbp-dev/KKBP_Importer), [mmd_tools](https://extensions.blender.org/add-ons/mmd-tools/), and [VRM Add-on for Blender](https://vrm-addon-for-blender.info/)
- Python 3.10+ on PATH

From this folder:

```text
python -m kkvrm config --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

## Use

1. In Koikatsu Sunshine character maker, open KKBP and click Export Model for KKBP. Leave the pose as T-pose. Do not freeze shape keys.
2. Convert the folder that appears under the game `Export_PMX` directory:

```text
python -m kkvrm convert "D:\KKS\Export_PMX\20260119_Name" -o Name.vrm
python -m kkvrm inspect "D:\KKS\Export_PMX\20260119_Name"
```

A card `.png` that sits inside an export folder, or a copy of that same file, also works. Pass `--export-root` if the card is elsewhere and the export lives under `Export_PMX`.

```text
python -m kkvrm convert card.png --export-root "D:\KKS\Export_PMX" -o Name.vrm
```

A folder that contains several KKBP exports converts each one. Pass `-o` as a directory in that case. One export folder, or a card `.png`, still writes one `.vrm`.

```text
python -m kkvrm convert "D:\KKS\Export_PMX" -o "D:\vrms"
```

Flags:

- `--sfw` — KKBP SFW import
- `--include-hidden` — export hidden meshes. Hitboxes stay out
- `--keep-blend` — write a `.blend` next to the `.vrm`
- `--no-springs` — skip hair, skirt, and bust spring bones
- `--bust-lift 0.006` — push bust-weighted clothes out, in meters. Default is `0.006`. `--no-bust-lift` disables it
- `--name`, `--author`, `--vrm-version`, `--copyright`, `--contact`, `--reference`, `--thumbnail`
- `--license`, `--license-url` — third-party license text and URL
- `--avatar onlyAuthor|onlySeparatelyLicensedPerson|everyone`
- `--commercial personalNonProfit|personalProfit|corporation`
- `--credit required|unnecessary`
- `--modification prohibited|allowModification|allowModificationRedistribution`
- `--sexual-ok` / `--no-sexual`, `--violent-ok` / `--no-violent`, `--political-ok` / `--no-political`, `--redistribute` / `--no-redistribute`

`--meta file.json` sets the same fields. Command flags override the file. `--sexual-ok` still forces sexual usage on. Defaults stay author-only, no redistribution, no violent or sexual usage, credit required, modification prohibited.

```json
{
  "authors": ["Mika"],
  "copyright": "2026 Mika",
  "contact": "mika@example.com",
  "references": ["https://example.com/mika"],
  "license": "Personal use only. Do not redistribute.",
  "licenseUrl": "https://example.com/license",
  "avatarPermission": "onlyAuthor",
  "commercialUsage": "personalNonProfit",
  "credit": "required",
  "modification": "prohibited",
  "allowSexual": false,
  "allowViolent": false,
  "allowPolitical": false,
  "allowRedistribution": false
}
```

Output is VRM 1.0. Body bones map to the humanoid rig. Hair, skirt, and bust chains stay as spring bones. Known KKBP shape keys bind to VRM presets (`blink`, `aa`/`ih`/`ou`/`ee`/`oh`, `happy`, `angry`, `sad`, `surprised`, `relaxed`). Every other shape key is a custom expression. Each material becomes MToon from the light texture. Real alpha shaders and cutout textures are masked. Skin, eyes, and solid clothes stay opaque and double-sided. Clothes weighted to the bust are pushed out slightly so they do not clip the body. No texture atlas, so materials stay separate.

The VRM license defaults to author-only, no redistribution. Game files are not included in this tool.
