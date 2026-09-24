REQUIRED = frozenset(
    {
        "hips",
        "spine",
        "head",
        "left_upper_arm",
        "left_lower_arm",
        "left_hand",
        "right_upper_arm",
        "right_lower_arm",
        "right_hand",
        "left_upper_leg",
        "left_lower_leg",
        "left_foot",
        "right_upper_leg",
        "right_lower_leg",
        "right_foot",
    }
)

HUMANOID = {
    "hips": ("Pelvis", "Hips", "cf_j_waist01"),
    "spine": ("Spine", "cf_j_spine01"),
    "chest": ("Chest", "cf_j_spine02"),
    "upper_chest": ("Upper Chest", "cf_j_spine03"),
    "neck": ("Neck", "cf_j_neck"),
    "head": ("Head", "cf_j_head"),
    "left_eye": ("Left Eye", "cf_J_hitomi_tx_L"),
    "right_eye": ("Right Eye", "cf_J_hitomi_tx_R"),
    "left_shoulder": ("Left shoulder", "cf_j_shoulder_L"),
    "right_shoulder": ("Right shoulder", "cf_j_shoulder_R"),
    "left_upper_arm": ("Left arm", "cf_j_arm00_L"),
    "right_upper_arm": ("Right arm", "cf_j_arm00_R"),
    "left_lower_arm": ("Left elbow", "cf_j_forearm01_L"),
    "right_lower_arm": ("Right elbow", "cf_j_forearm01_R"),
    "left_hand": ("Left wrist", "cf_j_hand_L"),
    "right_hand": ("Right wrist", "cf_j_hand_R"),
    "left_upper_leg": ("Left leg", "cf_j_thigh00_L"),
    "right_upper_leg": ("Right leg", "cf_j_thigh00_R"),
    "left_lower_leg": ("Left knee", "cf_j_leg01_L"),
    "right_lower_leg": ("Right knee", "cf_j_leg01_R"),
    "left_foot": ("Left ankle", "cf_j_foot_L"),
    "right_foot": ("Right ankle", "cf_j_foot_R"),
    "left_toes": ("Left toe", "cf_j_toes_L"),
    "right_toes": ("Right toe", "cf_j_toes_R"),
    "left_thumb_metacarpal": ("Thumb0_L", "cf_j_thumb01_L"),
    "left_thumb_proximal": ("Thumb1_L", "cf_j_thumb02_L"),
    "left_thumb_distal": ("Thumb2_L", "cf_j_thumb03_L"),
    "left_index_proximal": ("IndexFinger1_L", "cf_j_index01_L"),
    "left_index_intermediate": ("IndexFinger2_L", "cf_j_index02_L"),
    "left_index_distal": ("IndexFinger3_L", "cf_j_index03_L"),
    "left_middle_proximal": ("MiddleFinger1_L", "cf_j_middle01_L"),
    "left_middle_intermediate": ("MiddleFinger2_L", "cf_j_middle02_L"),
    "left_middle_distal": ("MiddleFinger3_L", "cf_j_middle03_L"),
    "left_ring_proximal": ("RingFinger1_L", "cf_j_ring01_L"),
    "left_ring_intermediate": ("RingFinger2_L", "cf_j_ring02_L"),
    "left_ring_distal": ("RingFinger3_L", "cf_j_ring03_L"),
    "left_little_proximal": ("LittleFinger1_L", "cf_j_little01_L"),
    "left_little_intermediate": ("LittleFinger2_L", "cf_j_little02_L"),
    "left_little_distal": ("LittleFinger3_L", "cf_j_little03_L"),
    "right_thumb_metacarpal": ("Thumb0_R", "cf_j_thumb01_R"),
    "right_thumb_proximal": ("Thumb1_R", "cf_j_thumb02_R"),
    "right_thumb_distal": ("Thumb2_R", "cf_j_thumb03_R"),
    "right_index_proximal": ("IndexFinger1_R", "cf_j_index01_R"),
    "right_index_intermediate": ("IndexFinger2_R", "cf_j_index02_R"),
    "right_index_distal": ("IndexFinger3_R", "cf_j_index03_R"),
    "right_middle_proximal": ("MiddleFinger1_R", "cf_j_middle01_R"),
    "right_middle_intermediate": ("MiddleFinger2_R", "cf_j_middle02_R"),
    "right_middle_distal": ("MiddleFinger3_R", "cf_j_middle03_R"),
    "right_ring_proximal": ("RingFinger1_R", "cf_j_ring01_R"),
    "right_ring_intermediate": ("RingFinger2_R", "cf_j_ring02_R"),
    "right_ring_distal": ("RingFinger3_R", "cf_j_ring03_R"),
    "right_little_proximal": ("LittleFinger1_R", "cf_j_little01_R"),
    "right_little_intermediate": ("LittleFinger2_R", "cf_j_little02_R"),
    "right_little_distal": ("LittleFinger3_R", "cf_j_little03_R"),
}

SPRING = {
    "hair": {"hit_radius": 0.008, "stiffness": 0.45, "gravity_power": 0.04, "drag_force": 0.8},
    "skirt": {"hit_radius": 0.01, "stiffness": 0.4, "gravity_power": 0.06, "drag_force": 0.75},
    "bust": {"hit_radius": 0.004, "stiffness": 1.2, "gravity_power": 0.008, "drag_force": 0.95},
}


def spring_kind(name):
    lowered = name.lower()
    if lowered.startswith("cf_s_") or "hit" in lowered:
        return None
    if lowered.startswith("cf_j_hair") or lowered.startswith("cf_d_hair"):
        return "hair"
    if lowered.startswith("cf_j_sk"):
        return "skirt"
    if lowered.startswith("cf_j_bust") and not lowered.startswith("cf_j_bust01") and not lowered.startswith("cf_j_bust00"):
        return "bust"
    return None


def match_humanoid(names):
    present = set(names)
    found = {}
    missing = []
    for slot, candidates in HUMANOID.items():
        match = next((candidate for candidate in candidates if candidate in present), None)
        if match:
            found[slot] = match
        elif slot in REQUIRED:
            missing.append(slot)
    return found, missing


def spring_chains(bones, skip=()):
    skipped = set(skip)
    parent = {name: par for name, par in bones}
    children = {name: [] for name, _par in bones}
    for name, par in bones:
        if par in children:
            children[par].append(name)
    chains = []

    def emit(kind, chain):
        if len(chain) >= 2:
            chains.append((kind, chain))

    def walk(kind, node, chain):
        kids = [
            kid
            for kid in children.get(node, [])
            if kid not in skipped and spring_kind(kid) == kind
        ]
        if not kids:
            emit(kind, chain)
            return
        if len(kids) == 1:
            walk(kind, kids[0], chain + [kids[0]])
            return
        for kid in kids:
            walk(kind, kid, chain + [kid])

    for name, _par in bones:
        if name in skipped:
            continue
        kind = spring_kind(name)
        if not kind:
            continue
        par = parent.get(name)
        if par and par not in skipped and spring_kind(par) == kind:
            continue
        walk(kind, name, [name])
    return chains
