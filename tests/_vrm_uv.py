import json
import struct
import sys

path = sys.argv[1]
data = open(path, "rb").read()
length = struct.unpack_from("<I", data, 12)[0]
glb = json.loads(data[20 : 20 + length])
meshes = glb.get("meshes", [])
print("meshes", len(meshes))
for mesh in meshes:
    name = mesh.get("name", "")
    prims = mesh.get("primitives", [])
    uvs = set()
    for prim in prims:
        attrs = prim.get("attributes", {})
        for key in attrs:
            if key.startswith("TEXCOORD"):
                uvs.add(key)
        mat = prim.get("material")
        mat_name = ""
        if mat is not None:
            mat_name = glb["materials"][mat].get("name", "")
        tex = glb["materials"][mat].get("pbrMetallicRoughness", {}).get("baseColorTexture", {}) if mat is not None else {}
        if any(k in mat_name.lower() for k in ("top", "bra", "pant", "body", "hair")):
            print(name[:30], mat_name[:50], "texCoord", tex.get("texCoord", 0), "uvs", sorted(uvs))
