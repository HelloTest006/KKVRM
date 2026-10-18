"""Manual artifact regression check: rig, materials, images, UVs and rest geometry."""

import argparse
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kkvrm.vrm import audit, read_document


def binary_chunk(path):
    with Path(path).open("rb") as handle:
        handle.seek(12)
        while chunk := handle.read(8):
            size, kind = struct.unpack("<I4s", chunk)
            if kind == b"BIN\x00":
                return handle.read(size)
            handle.seek(size, 1)
    return b""


def positions(document, binary, accessor_index):
    accessor = document["accessors"][accessor_index]
    assert accessor["componentType"] == 5126 and accessor["type"] == "VEC3"
    view = document["bufferViews"][accessor["bufferView"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride", 12)
    return [struct.unpack_from("<3f", binary, offset + index * stride) for index in range(accessor["count"])]


def image_hashes(document, binary):
    hashes = []
    for image in document.get("images", []):
        view = document["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        data = binary[start:start + view["byteLength"]]
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as pixels:
                data = pixels.convert("RGBA").tobytes()
        except ImportError:
            pass
        hashes.append(hashlib.sha256(data).hexdigest())
    return sorted(hashes)


def image_details(document, binary):
    from PIL import Image
    result = {}
    for image in document.get("images", []):
        view = document["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        data = binary[start:start + view["byteLength"]]
        with Image.open(io.BytesIO(data)) as source:
            pixels = source.convert("RGBA")
            result[image.get("name", str(len(result)))] = {
                "sha": hashlib.sha256(pixels.tobytes()).hexdigest(), "size": pixels.size,
                "range": pixels.getextrema(), "average": list(pixels.resize((1, 1)).getpixel((0, 0))),
            }
    return result


def uv_bytes(document, binary, index):
    accessor = document["accessors"][index]
    assert accessor["componentType"] == 5126 and accessor["type"] == "VEC2"
    view = document["bufferViews"][accessor["bufferView"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride", 8)
    return b"".join(binary[offset + vertex * stride:offset + vertex * stride + 8]
                    for vertex in range(accessor["count"]))


def policy(document):
    return sorted((material["name"], material.get("alphaMode", "OPAQUE"), material.get("doubleSided", False))
                  for material in document["materials"])


parser = argparse.ArgumentParser()
parser.add_argument("artifact")
parser.add_argument("--baseline")
args = parser.parse_args()
result = audit(args.artifact)
assert result["ok"], result["errors"]
output = {"validation": result["summary"]}
if args.baseline:
    previous, current = read_document(args.baseline), read_document(args.artifact)
    old_binary, new_binary = binary_chunk(args.baseline), binary_chunk(args.artifact)
    assert policy(previous) == policy(current), "material transparency/culling changed"
    if image_hashes(previous, old_binary) != image_hashes(current, new_binary):
        old_images, new_images = image_details(previous, old_binary), image_details(current, new_binary)
        differences = {name: {"before": old_images.get(name), "after": new_images.get(name)}
                       for name in old_images.keys() | new_images.keys() if old_images.get(name) != new_images.get(name)}
        print(json.dumps(differences, indent=2))
        raise AssertionError("embedded texture content changed")
    assert len(previous["meshes"]) == len(current["meshes"])
    maximum, body_maximum = 0.0, 0.0
    for old, new in zip(previous["meshes"], current["meshes"]):
        assert old["name"] == new["name"] and len(old["primitives"]) == len(new["primitives"])
        for first, second in zip(old["primitives"], new["primitives"]):
            a = positions(previous, old_binary, first["attributes"]["POSITION"])
            b = positions(current, new_binary, second["attributes"]["POSITION"])
            assert len(a) == len(b)
            delta = max((abs(x - y) for v, w in zip(a, b) for x, y in zip(v, w)), default=0)
            maximum = max(maximum, delta)
            if "body" in old["name"].lower():
                body_maximum = max(body_maximum, delta)
            for key in first["attributes"]:
                if key.startswith("TEXCOORD"):
                    assert key in second["attributes"]
                    assert uv_bytes(previous, old_binary, first["attributes"][key]) == uv_bytes(current, new_binary, second["attributes"][key]), "UV coordinates changed"
            assert len(first.get("targets", [])) == len(second.get("targets", [])), "morph targets lost"
    assert body_maximum < 1e-6, "body rest geometry changed"
    assert maximum <= 0.0061, "unexpected geometry displacement"
    output.update(material_policy_equal=True, embedded_images_equal=True, uv_coordinates_equal=True,
                  maximum_position_delta=maximum, body_position_delta=body_maximum)
print(json.dumps(output, indent=2))
