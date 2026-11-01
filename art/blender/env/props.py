"""Street furniture, planting and the fountain.

The small pieces that make a place feel inhabited: trees, shrubs, benches, lamp posts,
planters, bollards, railings and a fountain. Anchor convention as everywhere in the kit -
origin at the ground-contact centre, a piece that runs in a line runs along **+X**.

Lamp posts carry an emissive head and **no light**: a walk-in content piece already spawns
about a dozen shadow-casting point lights and three slots of content is most of this PC's
light budget, so the environment contributes none (see the note in `env_kit`).
"""

import math

import env_kit as E

PIECES = ("tree_tall", "tree_round", "shrub", "bench", "lamp_post",
          "planter", "bollard", "railing", "fountain")


def tree_tall(palette):
    """About 8 m: a straight trunk and three stacked canopy masses."""
    P = E.EnvPiece("tree_tall", "planting", palette=palette, collision="blocking",
                   footprint=(3.6, 3.6))
    P.notes.append("Collision is the whole canopy, which is what stops a Player walking "
                   "through a tree; it is only a few hundred triangles.")
    P.b.revolve([(0.0, 0.0), (0.28, 0.0), (0.17, 4.6), (0.0, 4.6)], 0.0, 0.0, "M_Trunk", segs=8)
    for (z, r) in ((4.55, 1.70), (5.75, 1.45), (6.80, 1.00)):
        P.canopy_blob((0.0, 0.0, z + r * 0.55), r, "M_Foliage", segs=9, rings=4, squash=0.78)
    # a root collar, so it does not look stuck into the paving
    P.b.revolve([(0.0, 0.0), (0.52, 0.0), (0.30, 0.22), (0.0, 0.22)], 0.0, 0.0, "M_Trunk", segs=8)
    return P


def tree_round(palette):
    """About 5.5 m: a short trunk under one broad canopy - the plaza tree."""
    P = E.EnvPiece("tree_round", "planting", palette=palette, collision="blocking",
                   footprint=(4.4, 4.4))
    P.b.revolve([(0.0, 0.0), (0.26, 0.0), (0.19, 2.3), (0.0, 2.3)], 0.0, 0.0, "M_Trunk", segs=8)
    for (dx, dy, z, r) in ((0.0, 0.0, 3.55, 2.10), (0.85, 0.55, 3.05, 1.25),
                           (-0.75, -0.70, 3.15, 1.15)):
        P.canopy_blob((dx, dy, z), r, "M_Foliage", segs=9, rings=4, squash=0.80)
    P.b.revolve([(0.0, 0.0), (0.48, 0.0), (0.28, 0.20), (0.0, 0.20)], 0.0, 0.0, "M_Trunk", segs=8)
    return P


def shrub(palette):
    """A 1.3 m clump: two blobs, the cheapest way to break up a hard edge."""
    P = E.EnvPiece("shrub", "planting", palette=palette, collision="decoration",
                   footprint=(1.6, 1.4))
    P.canopy_blob((0.0, 0.0, 0.62), 0.66, "M_Foliage", segs=8, rings=3, squash=0.92)
    P.canopy_blob((0.42, 0.22, 0.46), 0.46, "M_Foliage", segs=8, rings=3, squash=0.92)
    return P


def bench(palette):
    """1.9 m of timber slats on metal legs, facing -Y."""
    P = E.EnvPiece("bench", "street", palette=palette, collision="blocking",
                   footprint=(1.9, 0.62))
    for s in (-1, 1):
        x = s * 0.72
        P.box((x - 0.05, -0.26, 0.0), (x + 0.05, -0.20, 0.44), "M_Metal")
        P.box((x - 0.05, 0.20, 0.0), (x + 0.05, 0.26, 0.86), "M_Metal")
        P.box((x - 0.05, -0.26, 0.40), (x + 0.05, 0.26, 0.46), "M_Metal")
    for i in range(4):
        y0 = -0.26 + i * 0.135
        P.box((-0.95, y0, 0.44), (0.95, y0 + 0.11, 0.50), "M_Timber")
    for i in range(3):
        z0 = 0.54 + i * 0.115
        P.box((-0.95, 0.18, z0), (0.95, 0.245, z0 + 0.09), "M_Timber")
    return P


def lamp_post(palette):
    """4.6 m: a tapered post, a short arm and an emissive head. No light component."""
    P = E.EnvPiece("lamp_post", "street", palette=palette, collision="blocking",
                   footprint=(0.9, 0.9))
    P.b.revolve([(0.0, 0.0), (0.26, 0.0), (0.20, 0.42), (0.11, 0.62), (0.085, 4.05),
                 (0.0, 4.05)], 0.0, 0.0, "M_Metal", segs=10)
    # the arm, reaching out along +Y
    P.box((-0.055, 0.0, 3.92), (0.055, 0.70, 4.03), "M_Metal")
    P.b.revolve([(0.0, 4.03), (0.30, 4.14), (0.26, 4.42), (0.0, 4.42)], 0.0, 0.70,
                "M_Metal", segs=10)
    P.b.revolve([(0.0, 3.92), (0.25, 3.98), (0.22, 4.13), (0.0, 4.13)], 0.0, 0.70,
                "M_Emissive", segs=10)
    return P


def planter(palette):
    """A 1.8 x 1.0 m trough with two shrubs in it."""
    P = E.EnvPiece("planter", "street", palette=palette, collision="blocking",
                   footprint=(1.8, 1.0))
    hx, hy, h, t = 0.9, 0.5, 0.60, 0.11
    P.box((-hx, -hy, 0.0), (hx, hy, 0.12), "M_Trim")
    for (ax, ay, bx, by) in ((-hx, -hy, hx, -hy + t), (-hx, hy - t, hx, hy),
                             (-hx, -hy, -hx + t, hy), (hx - t, -hy, hx, hy)):
        P.box((ax, ay, 0.12), (bx, by, h), "M_Trim")
    P.box((-hx + t, -hy + t, 0.12), (hx - t, hy - t, h - 0.10), "M_Trunk")
    for (dx, dy, r) in ((-0.40, 0.0, 0.40), (0.40, 0.05, 0.36)):
        P.canopy_blob((dx, dy, h + r * 0.35), r, "M_Foliage", segs=8, rings=3, squash=0.88)
    return P


def bollard(palette):
    """A 0.95 m tapered bollard: what keeps a plaza's edge legible."""
    P = E.EnvPiece("bollard", "street", palette=palette, collision="blocking",
                   footprint=(0.36, 0.36))
    P.b.revolve([(0.0, 0.0), (0.18, 0.0), (0.16, 0.10), (0.125, 0.80), (0.145, 0.86),
                 (0.11, 0.95), (0.0, 0.95)], 0.0, 0.0, "M_Metal", segs=10)
    return P


def railing(palette):
    """4 m of railing: two posts and two rails, running along +X."""
    P = E.EnvPiece("railing", "street", palette=palette, collision="blocking",
                   footprint=(4.0, 0.14))
    for x in (-2.0 + 0.07, 0.0, 2.0 - 0.07):
        P.b.revolve([(0.0, 0.0), (0.07, 0.0), (0.055, 1.08), (0.0, 1.08)], x, 0.0,
                    "M_Metal", segs=8)
    for z in (0.52, 1.00):
        P.box((-2.0, -0.035, z), (2.0, 0.035, z + 0.07), "M_Metal")
    for i in range(9):
        x = -1.75 + i * 0.4375
        P.box((x - 0.018, -0.018, 0.08), (x + 0.018, 0.018, 0.52), "M_Metal")
    return P


def fountain(palette):
    """A 6 m basin with a plinth and a bowl - the thing a plaza is arranged around."""
    P = E.EnvPiece("fountain", "street", palette=palette, collision="blocking",
                   footprint=(6.0, 6.0))
    P.notes.append("Still water: a flat M_Water disc, no simulation and no particles.")
    # basin wall and rim
    P.ring((0.0, 0.0), 2.55, 3.00, "xy", 0.0, 0.62, "M_Kerb", segs=28, face_mat="M_Paving")
    P.disc((0.0, 0.0), 2.58, "xy", 0.0, 0.16, "M_Paving", segs=28)
    # water
    P.disc((0.0, 0.0), 2.52, "xy", 0.16, 0.44, "M_Water", segs=28)
    # plinth and bowl
    P.b.revolve([(0.0, 0.16), (0.85, 0.16), (0.70, 0.52), (0.42, 1.30), (0.52, 1.46),
                 (0.0, 1.46)], 0.0, 0.0, "M_Paving", segs=20)
    P.b.revolve([(0.0, 1.46), (1.15, 1.72), (1.15, 1.90), (0.0, 1.78)], 0.0, 0.0,
                "M_Kerb", segs=20)
    P.disc((0.0, 0.0), 1.05, "xy", 1.70, 1.78, "M_Water", segs=20)
    P.b.revolve([(0.0, 1.90), (0.26, 1.96), (0.16, 2.45), (0.0, 2.45)], 0.0, 0.0,
                "M_Paving", segs=14)
    return P


BUILDERS = {name: globals()[name] for name in PIECES}
