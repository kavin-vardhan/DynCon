"""Ground, paving and waterside pieces of the environment kit.

Everything here is a flat, walkable or edge-of-water piece. Anchor convention (see
`env_kit`): the origin is the ground-contact centre, and a piece that runs in a line runs
along **+X**, so the map places one with a location and a yaw.

Paving slabs are **blocking**, not decoration: they stand about 14 cm proud of the map's
ground plane, the Player walks on the slabs, and the lip where the paved area ends reads as
the edge of the plaza (the map puts a kerb there anyway). Abutting slabs are coplanar, so
there is no step between them.
"""

import env_kit as E

PIECES = ("paving_tile", "paving_edge", "kerb", "steps", "boardwalk",
          "pier_deck", "pier_post", "quay_wall", "slot_pad")

PAVE_T = 0.14          # how proud of the ground plane a paved area stands


def paving_tile(palette):
    """8 x 8 m slab with an inlaid cross-band, so a plaza has a rhythm without a texture."""
    P = E.EnvPiece("paving_tile", "ground", palette=palette, collision="blocking",
                   footprint=(8.0, 8.0))
    P.notes.append("Lays edge to edge on an 8 m grid; the top is PAVE_T above the ground plane.")
    h = 4.0
    P.box((-h, -h, 0.0), (h, h, PAVE_T - 0.012), "M_Paving")
    # top skin, so the band can be inlaid without z-fighting
    P.box((-h, -h, PAVE_T - 0.012), (h, h, PAVE_T), "M_Paving")
    band = 0.34
    for (lo, hi) in ((-band, band),):
        P.box((-h, lo, PAVE_T - 0.004), (h, hi, PAVE_T + 0.004), "M_PavingAlt")
        P.box((lo, -h, PAVE_T - 0.004), (hi, h, PAVE_T + 0.004), "M_PavingAlt")
    # a quartering joint line, a hair narrower
    for s in (-1, 1):
        P.box((-h, s * 2.0 - 0.07, PAVE_T - 0.004), (h, s * 2.0 + 0.07, PAVE_T + 0.002), "M_PavingAlt")
        P.box((s * 2.0 - 0.07, -h, PAVE_T - 0.004), (s * 2.0 + 0.07, h, PAVE_T + 0.002), "M_PavingAlt")
    return P


def paving_edge(palette):
    """4 m of chamfered paving edge: closes the lip where a paved area stops."""
    P = E.EnvPiece("paving_edge", "ground", palette=palette, collision="blocking",
                   footprint=(4.0, 0.6))
    P.notes.append("Runs along +X; the chamfer faces -Y, i.e. away from the paved area.")
    P.extrude([(-0.30, 0.0), (0.30, 0.0), (0.30, PAVE_T), (-0.10, PAVE_T)],
              "yz", -2.0, 2.0, "M_Paving", cap_mat="M_Paving")
    return P


def kerb(palette):
    """4 m kerb, 0.30 wide, standing 0.16 above the paving it edges."""
    P = E.EnvPiece("kerb", "ground", palette=palette, collision="blocking",
                   footprint=(4.0, 0.3))
    P.box((-2.0, -0.15, 0.0), (2.0, 0.15, 0.16), "M_Kerb")
    P.box((-2.0, -0.15, 0.16), (2.0, 0.15, 0.175), "M_PavingAlt")
    return P


def steps(palette):
    """A 4 m wide flight of three risers, climbing towards +Y.

    No cheek walls. A flight is laid several pieces wide, and a wedge at each piece's edge
    would put a 0.64 m wall across the flight every four metres - which is exactly what it
    did the first time, and what stopped the Player walking up onto the terrace.
    """
    P = E.EnvPiece("steps", "ground", palette=palette, collision="blocking",
                   footprint=(4.0, 1.5))
    P.notes.append("Climbs +Y: three risers of 0.17 m, 0.45 m going. Total rise 0.51 m.")
    P.notes.append("Tiles side by side on a 4 m pitch; nothing stands proud at the edges.")
    rise, going = 0.17, 0.45
    for i in range(3):
        y0 = -0.75 + i * going
        P.box((-2.0, y0, 0.0), (2.0, 0.75, rise * (i + 1)), "M_Paving")
        P.box((-2.0, y0, rise * (i + 1)), (2.0, y0 + 0.08, rise * (i + 1) + 0.012), "M_PavingAlt")
    return P


def boardwalk(palette):
    """4 x 4 m timber deck. The promenade of Game B is a field of these."""
    P = E.EnvPiece("boardwalk", "ground", palette=palette, collision="blocking",
                   footprint=(4.0, 4.0))
    P.notes.append("Planks run along +X; lays edge to edge on a 4 m grid.")
    P.box((-2.0, -2.0, 0.0), (2.0, 2.0, 0.09), "M_Trim")          # the bearers below
    P.plank_deck(2.0, 2.0, 0.09, 0.15, "M_Timber", planks=9, gap=0.025, along="y")
    return P


def pier_deck(palette):
    """6 x 4 m pier deck with edge beams - carried on pier posts."""
    P = E.EnvPiece("pier_deck", "ground", palette=palette, collision="blocking",
                   footprint=(6.0, 4.0))
    P.notes.append("The deck only: the map stands it on pier_post pieces and sets its height.")
    P.box((-3.0, -2.0, 0.0), (3.0, 2.0, 0.10), "M_Trim")
    P.plank_deck(3.0, 2.0, 0.10, 0.17, "M_Timber", planks=13, gap=0.025, along="y")
    for s in (-1, 1):
        P.box((-3.0, s * 2.0 - 0.12, 0.0), (3.0, s * 2.0 + 0.12, 0.22), "M_Timber")
    return P


def pier_post(palette):
    """A 3.2 m timber pile with a cap - what a pier deck stands on."""
    P = E.EnvPiece("pier_post", "street", palette=palette, collision="blocking",
                   footprint=(0.5, 0.5))
    P.post(0.0, 0.0, 0.0, 3.05, 0.22, "M_Timber", segs=8)
    P.post(0.0, 0.0, 3.05, 3.20, 0.27, "M_Metal", segs=8)
    return P


def quay_wall(palette):
    """4 m of quay edge: a stone wall with a coping, for where the promenade meets water."""
    P = E.EnvPiece("quay_wall", "ground", palette=palette, collision="blocking",
                   footprint=(4.0, 0.8))
    P.notes.append("Runs along +X. The water side is -Y; the coping overhangs it.")
    P.box((-2.0, -0.30, 0.0), (2.0, 0.30, 2.30), "M_Kerb")
    P.box((-2.0, -0.40, 2.30), (2.0, 0.34, 2.46), "M_Paving")
    for i in range(4):
        x = -1.5 + i
        P.box((x - 0.05, -0.32, 0.30), (x + 0.05, -0.28, 2.30), "M_PavingAlt")
    return P


def slot_pad(palette):
    """The prepared ground a dynamic slot stands on: 14 x 14 m, with a kerb band.

    Why it exists: the packaged build contains **none** of the content, so between the map
    loading and the backend's first answer a slot has nothing in it. A pad means that moment
    reads as a place that is waiting for something rather than as a hole in the paving - and
    it costs nothing, because it is environment, not content. The map scales it to 0.5 for an
    S slot; L and T use it at 1.0.
    """
    P = E.EnvPiece("slot_pad", "ground", palette=palette, collision="blocking",
                   footprint=(14.0, 14.0))
    P.notes.append("Scaled 0.5 in X and Y for an S slot. Never carries a brand or a marking.")
    h = 7.0
    P.box((-h, -h, 0.0), (h, h, 0.17), "M_Paving")
    band = 0.55
    for (ax, ay, bx, by) in ((-h, -h, h, -h + band), (-h, h - band, h, h),
                             (-h, -h + band, -h + band, h - band),
                             (h - band, -h + band, h, h - band)):
        P.box((ax, ay, 0.0), (bx, by, 0.23), "M_Kerb")
    # a shallow inlaid square, so the pad has a centre to stand something on
    for s in (-1, 1):
        P.box((-h + 1.5, s * 4.4 - 0.09, 0.168), (h - 1.5, s * 4.4 + 0.09, 0.176), "M_PavingAlt")
        P.box((s * 4.4 - 0.09, -h + 1.5, 0.168), (s * 4.4 + 0.09, h - 1.5, 0.176), "M_PavingAlt")
    return P


BUILDERS = {name: globals()[name] for name in PIECES}
