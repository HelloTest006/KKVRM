import json
import struct
import sys

path = sys.argv[1]
data = open(path, "rb").read()
length, ctype = struct.unpack_from("<I4s", data, 12)
chunk = data[20 : 20 + length]
glb = json.loads(chunk)
mats = glb.get("materials", [])
print("materials", len(mats))
for mat in mats:
    alpha = mat.get("alphaMode", "OPAQUE")
    name = mat.get("name", "")
    if alpha != "OPAQUE":
        print(alpha, mat.get("alphaCutoff"), name[:90])
print("--- cloth ---")
for mat in mats:
    name = mat.get("name", "")
    low = name.lower()
    if any(key in low for key in ("top", "bra", "sock", "shoe", "pant", "cloth", "hair", "mask")):
        print(mat.get("alphaMode", "OPAQUE"), name[:90])
