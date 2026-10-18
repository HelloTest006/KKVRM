import math
import struct
from pathlib import Path


class PmxError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, size):
        end = self.pos + size
        if size < 0 or end > len(self.data):
            raise PmxError("truncated PMX")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self):
        return self.read(1)[0]

    def u16(self):
        return struct.unpack("<H", self.read(2))[0]

    def i32(self):
        return struct.unpack("<i", self.read(4))[0]

    def f32(self):
        return struct.unpack("<f", self.read(4))[0]

    def count(self):
        value = self.i32()
        if value < 0:
            raise PmxError("negative PMX element count")
        return value

    def skip_floats(self, count):
        self.read(4 * count)

    def index(self, size):
        if size == 1:
            return struct.unpack("<b", self.read(1))[0]
        if size == 2:
            return struct.unpack("<h", self.read(2))[0]
        if size == 4:
            return struct.unpack("<i", self.read(4))[0]
        raise PmxError(f"bad index size {size}")

    def text(self, encoding):
        length = self.i32()
        if length < 0:
            raise PmxError("negative string length")
        raw = self.read(length)
        codec = "utf-8" if encoding == 1 else "utf-16-le"
        return raw.decode(codec, errors="replace")


def _skip_vertex(reader, extra_uv, bone_size):
    reader.skip_floats(8 + (4 * extra_uv))
    kind = reader.u8()
    if kind == 0:
        reader.index(bone_size)
    elif kind == 1:
        reader.index(bone_size)
        reader.index(bone_size)
        reader.f32()
    elif kind in (2, 4):
        for _ in range(4):
            reader.index(bone_size)
        reader.skip_floats(4)
    elif kind == 3:
        reader.index(bone_size)
        reader.index(bone_size)
        reader.skip_floats(10)
    else:
        raise PmxError(f"unknown weight type {kind}")
    reader.f32()


def _skip_bone_tail(reader, flags, bone_size):
    if flags & 0x0001:
        connection = reader.index(bone_size)
    else:
        connection = [reader.f32() for _ in range(3)]
    if flags & 0x0100 or flags & 0x0200:
        reader.index(bone_size)
        reader.f32()
    if flags & 0x0400:
        reader.skip_floats(3)
    if flags & 0x0800:
        reader.skip_floats(6)
    if flags & 0x2000:
        reader.i32()
    if flags & 0x0020:
        reader.index(bone_size)
        reader.i32()
        reader.f32()
        links = reader.count()
        for _ in range(links):
            reader.index(bone_size)
            if reader.u8():
                reader.skip_floats(6)
    return connection


def _skip_morph_data(reader, kind, count, vertex_size, bone_size, material_size, morph_size):
    for _ in range(count):
        if kind == 0:
            reader.index(morph_size)
            reader.f32()
        elif kind == 1:
            reader.index(vertex_size)
            reader.skip_floats(3)
        elif kind == 2:
            reader.index(bone_size)
            reader.skip_floats(7)
        elif kind in (3, 4, 5, 6, 7):
            reader.index(vertex_size)
            reader.skip_floats(4)
        elif kind == 8:
            reader.index(material_size)
            reader.u8()
            reader.skip_floats(4 + 3 + 1 + 3 + 4 + 1 + 4 + 4 + 4)
        elif kind == 9:
            reader.index(morph_size)
            reader.f32()
        elif kind == 10:
            # PMX 2.1 impulse morph: rigid-body index, local flag, velocity, torque.
            reader.index(vertex_size)
            reader.u8()
            reader.skip_floats(6)
        else:
            raise PmxError(f"unknown morph type {kind}")


def parse(data):
    reader = _Reader(data)
    if reader.read(4) != b"PMX ":
        raise PmxError("not a PMX file")
    version = struct.unpack("<f", reader.read(4))[0]
    if not math.isfinite(version) or not 2.0 <= version < 2.11:
        raise PmxError(f"unsupported PMX version {version}")
    globals_count = reader.u8()
    globals_ = list(reader.read(globals_count))
    if len(globals_) < 8:
        raise PmxError("PMX globals truncated")
    encoding, extra_uv, vertex_size, texture_size, material_size, bone_size, morph_size, _rigid = globals_[:8]
    if encoding not in (0, 1) or extra_uv > 4 or any(size not in (1, 2, 4) for size in globals_[2:8]):
        raise PmxError("invalid PMX globals")
    model_name = reader.text(encoding)
    reader.text(encoding)
    reader.text(encoding)
    reader.text(encoding)
    vertex_count = reader.count()
    for _ in range(vertex_count):
        _skip_vertex(reader, extra_uv, bone_size)
    face_count = reader.count()
    for _ in range(face_count):
        reader.index(vertex_size)
    texture_count = reader.count()
    textures = [reader.text(encoding) for _ in range(texture_count)]
    material_count = reader.count()
    materials = []
    for _ in range(material_count):
        name = reader.text(encoding)
        reader.text(encoding)
        reader.skip_floats(4 + 3 + 1 + 3)
        reader.u8()
        reader.skip_floats(4 + 1)
        reader.index(texture_size)
        reader.index(texture_size)
        reader.u8()
        if reader.u8() == 0:
            reader.index(texture_size)
        else:
            reader.u8()
        reader.text(encoding)
        reader.i32()
        materials.append(name)
    bone_count = reader.count()
    bones, bone_details = [], []
    for index in range(bone_count):
        name = reader.text(encoding)
        english_name = reader.text(encoding)
        position = [reader.f32() for _ in range(3)]
        parent = reader.index(bone_size)
        reader.i32()
        flags = reader.u16()
        connection = _skip_bone_tail(reader, flags, bone_size)
        bones.append(name)
        bone_details.append({"name": name, "english_name": english_name, "index": index,
                             "position": position, "parent_index": parent, "tail": connection})
    for detail in bone_details:
        parent = detail["parent_index"]
        if parent < -1 or parent >= len(bones):
            raise PmxError("bone parent index out of range")
        detail["parent"] = bones[parent] if parent >= 0 else None
    morph_count = reader.count()
    morphs = []
    for _ in range(morph_count):
        name = reader.text(encoding)
        reader.text(encoding)
        reader.u8()
        kind = reader.u8()
        count = reader.count()
        _skip_morph_data(reader, kind, count, _rigid if kind == 10 else vertex_size, bone_size, material_size, morph_size)
        morphs.append(name)
    return {
        "name": model_name,
        "bones": bones,
        "bone_details": bone_details,
        "morphs": morphs,
        "materials": materials,
        "textures": textures,
    }


def parse_path(path):
    return parse(Path(path).read_bytes())
