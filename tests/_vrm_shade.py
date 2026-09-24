import json
import struct
import sys

path = sys.argv[1]
data = open(path, "rb").read()
length = struct.unpack_from("<I", data, 12)[0]
glb = json.loads(data[20 : 20 + length])
images = glb.get("images", [])
textures = glb.get("textures", [])

def tex_name(info):
    if not isinstance(info, dict):
        return None
    index = info.get("index")
    if index is None or index >= len(textures):
        return None
    source = textures[index].get("source")
    if source is None or source >= len(images):
        return None
    image = images[source]
    return image.get("name") or image.get("uri") or str(source)

for mat in glb.get("materials", []):
    name = mat.get("name", "")
    mtoon = (mat.get("extensions") or {}).get("VRMC_materials_mtoon") or {}
    pbr = mat.get("pbrMetallicRoughness") or {}
    base = tex_name(pbr.get("baseColorTexture"))
    shade = tex_name(mtoon.get("shadeMultiplyTexture"))
    normal = tex_name(mat.get("normalTexture"))
    shift = mtoon.get("shadingShiftFactor")
    toony = mtoon.get("shadingToonyFactor")
    shade_color = mtoon.get("shadeColorFactor")
    if shade or (base and "dark" in str(base).lower()) or (shade_color and shade_color != [1, 1, 1]):
        print(name[:55])
        print("  base", base, "shade", shade, "normal", normal)
        print("  shift", shift, "toony", toony, "shadeColor", shade_color)
