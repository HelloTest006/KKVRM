SUNSHINE = (
    b"KoiKatuCharaSun",
    b"KoiKatuCharaSP",
)
KOIKATSU = b"KoiKatuChara"
REJECT = (
    (b"HoneySelect2", "Honey Select 2"),
    (b"AIS_Chara", "AI Shoujo"),
    (b"EroMakeChara", "Emotion Creators"),
    (b"HoneyComeChara", "HoneyCome"),
)


class CardError(ValueError):
    pass


def identify(data):
    if not isinstance(data, (bytes, bytearray)):
        raise CardError("card data must be bytes")
    blob = bytes(data)
    for marker, game in REJECT:
        if marker in blob and b"KoiKatuChara" not in blob:
            raise CardError(f"{game} card, not Koikatsu Sunshine")
    for marker in SUNSHINE:
        if marker in blob:
            return "sunshine"
    if KOIKATSU in blob:
        return "koikatsu"
    for marker, game in REJECT:
        if marker in blob:
            raise CardError(f"{game} card, not Koikatsu Sunshine")
    raise CardError("not a Koikatsu card")


def identify_path(path):
    with open(path, "rb") as handle:
        return identify(handle.read())
