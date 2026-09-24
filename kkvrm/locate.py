import hashlib
from pathlib import Path

from .card import CardError, identify_path


def is_export_dir(path):
    path = Path(path)
    if not path.is_dir():
        return False
    if any(path.glob("*.pmx")):
        return True
    if any(path.glob("KK_*.json")) or any(path.glob("*MaterialData*.json")):
        return True
    return False


def list_exports(path):
    path = Path(path)
    if not path.is_dir() or is_export_dir(path):
        return []
    found = [child for child in path.iterdir() if child.is_dir() and is_export_dir(child)]
    return sorted(found, key=lambda item: item.name.lower())


def character_name(folder):
    stem = Path(folder).name
    if "_" in stem:
        prefix, rest = stem.split("_", 1)
        if prefix.isdigit() and rest:
            return rest
    return stem


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_dirs(root):
    root = Path(root)
    if is_export_dir(root):
        yield root
    if not root.is_dir():
        return
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if child.is_dir() and is_export_dir(child):
            yield child
            continue
        if not child.is_dir():
            continue
        try:
            grands = list(child.iterdir())
        except OSError:
            continue
        for grand in grands:
            if grand.is_dir() and is_export_dir(grand):
                yield grand


def _png_matches(folder, card):
    card = Path(card)
    if any(path.is_file() for path in folder.rglob(card.name)):
        return True
    try:
        wanted = _hash_file(card)
        size = card.stat().st_size
    except OSError:
        return False
    for png in folder.rglob("*.png"):
        if not png.is_file() or png.stat().st_size != size:
            continue
        if _hash_file(png) == wanted:
            return True
    return False


def find_card(folder):
    folder = Path(folder)
    pngs = [path for path in folder.glob("*.png") if path.is_file()]
    pngs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for png in pngs:
        try:
            identify_path(png)
        except (CardError, OSError):
            continue
        return png
    return None


def resolve_input(source, export_root=None):
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    card = None
    game = None
    if source.is_file():
        if source.suffix.lower() == ".png":
            try:
                game = identify_path(source)
            except CardError:
                game = None
            card = source
            if is_export_dir(source.parent):
                return source.parent, card, game
        folder = None
    else:
        folder = source if is_export_dir(source) else None
        if folder is None and is_export_dir(source.parent):
            folder = source.parent
    if folder is None and card is not None:
        roots = []
        if export_root:
            roots.append(Path(export_root))
        if card.parent not in roots:
            roots.append(card.parent)
        matches = []
        for root in roots:
            for candidate in _candidate_dirs(root):
                if _png_matches(candidate, card):
                    matches.append(candidate)
        if matches:
            matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            folder = matches[0]
    if folder is None:
        if card is not None and game is None:
            raise CardError(f"not a Koikatsu card and no KKBP export folder: {source}")
        if card is not None:
            raise FileNotFoundError(
                "KKBP export folder not found. Export the card from Koikatsu Sunshine "
                "with KKBP Exporter, then pass that Export_PMX folder or the card png inside it."
            )
        raise FileNotFoundError(f"not a KKBP export folder: {source}")
    if card is None:
        card = find_card(folder)
    if game is None and card is not None:
        try:
            game = identify_path(card)
        except CardError:
            game = None
    return folder, card, game
