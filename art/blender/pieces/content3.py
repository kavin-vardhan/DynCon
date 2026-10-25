"""`content3` — tall uploadable content, size class T, fits slot A2 only (spec v1 §3).

v1  "Tower": a walk-in base hall 10 x 10 x 5 m with two stacked closed volumes above it,
    17.0 m in all, banded with horizontal glazing.
v2  The same base with the stacked volumes twisted 15 and 30 degrees, vertical fins instead of
    bands, and a stepped roof crown with a mast, 18.6 m.

Everything above the base hall is closed volume: it is there to break the 9 m line so the
piece only fits the tall slot, and to make the swap obvious from the far side of the booth.
"""

import dc_kit as K
from dc_kit import MeshBuilder as MB

HX = HY = 5.0                       # 10 x 10 m base hall
T = 0.25
BASE_TOP = 5.00
CEIL_UNDER = 4.78
DOOR_W, DOOR_HEAD = 1.80, 2.85
SIGN_Z = 4.05

VERSIONS = ("v1", "v2")


def build(version):
    if version == "v1":
        return _v1()
    if version == "v2":
        return _v2()
    raise ValueError("content3 has no %s" % version)


def _base_hall(P, *, layout, side_windows, back_windows, side_light_f):
    """The walk-in part. Identical between the versions apart from the window rhythm."""
    floor_top = P.plinth(HX, HY, skirt=0.25, base_h=0.09, deck_h=0.05)
    ix0, ix1 = -HX + T, HX - T
    iy0, iy1 = -HY + T, HY - T

    front = [dict(center=0.0, width=DOOR_W, sill=0.0, head=DOOR_HEAD)] + \
            [dict(center=sx * 3.30, width=1.40, sill=1.15, head=3.25) for sx in (-1, 1)]
    P.wall_run(along="x", outer=-HY, out_sign=-1, t=T, a=-HX, b=HX, z0=0.0, z1=BASE_TOP,
               openings=front)
    for o in front[1:]:
        P.window(along="x", outer=-HY, out_sign=-1, t=T, center=o["center"], width=o["width"],
                 sill=o["sill"], head=o["head"], mullions=1)

    P.wall_run(along="x", outer=HY, out_sign=1, t=T, a=-HX, b=HX, z0=0.0, z1=BASE_TOP,
               openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in back_windows])
    for (c, w, s, h) in back_windows:
        P.window(along="x", outer=HY, out_sign=1, t=T, center=c, width=w, sill=s, head=h, mullions=1)

    for sx in (-1, 1):
        P.wall_run(along="y", outer=sx * HX, out_sign=sx, t=T, a=-HY + T / 2, b=HY - T / 2,
                   z0=0.0, z1=BASE_TOP,
                   openings=[dict(center=c, width=w, sill=s, head=h) for (c, w, s, h) in side_windows])
        for (c, w, s, h) in side_windows:
            P.window(along="y", outer=sx * HX, out_sign=sx, t=T, center=c, width=w,
                     sill=s, head=h, mullions=1)
        P.panel_joints(along="y", outer=sx * HX, out_sign=sx, a=-HY + 0.4, b=HY - 0.4,
                       z0=0.55, z1=BASE_TOP - 0.18, pitch=1.25,
                       skip=[(c - w / 2 - 0.3, c + w / 2 + 0.3) for (c, w, s, h) in side_windows])

    P.ceiling((ix0, iy0), (ix1, iy1), CEIL_UNDER, BASE_TOP)
    P.base_course(HX, HY, 0.04, 0.46, skip_front=(-1.5, 1.5))

    P.add_door(hinge=(-DOOR_W / 2, -HY + T / 2, floor_top),
               width=DOOR_W, height=DOOR_HEAD - floor_top, open_sign=1)
    P.door_frame(along="x", outer=-HY, out_sign=-1, t=T, center=0.0, width=DOOR_W,
                 head=DOOR_HEAD, mat="M_BrandAccent", w=0.16, proud=0.06)
    for sx in (-1, 1):
        P.wall_lamp((sx * 1.32, -HY, 2.25), (0.0, -1.0, 0.0))

    P.entrance_step(center_x=0.0, y_out=-5.72, y_in=-HY + 0.06, half_w=1.55, z_top=floor_top)
    P.entrance_mat(center_x=0.0, y0=-5.46, y1=-5.20, half_w=0.98, z=floor_top)
    for sx in (-1, 1):
        P.planter((sx * 2.90, -5.44), size=(1.20, 0.80), h=0.58)
    P.downpipe(HX + 0.10, HY - 0.35, 0.10, BASE_TOP - 0.15)

    P.add_sign((0.0, -HY, SIGN_Z), (0.0, -1.0, 0.0), depth=0.13)
    P.standard_interior(lo=(ix0, iy0, floor_top), hi=(ix1, iy1, CEIL_UNDER),
                        door_center_x=0.0, lights_a=(3, 2), light_b_z=2.45, layout=layout,
                        side_light_f=side_light_f,
                        tall_avoid=[(c - w / 2 - 0.30, c + w / 2 + 0.30)
                                    for (c, w, _s, _h) in side_windows])
    return floor_top


def _fin_ring(P, half, deg, z0, z1, *, count=5, w=0.16, d=0.26, mat="M_Trim"):
    """Vertical fins round a (possibly rotated) square volume."""
    for side in range(4):
        for i in range(count):
            f = -half + 2 * half * (i + 1) / (count + 1)
            rect = [(half, f - w / 2), (half + d, f - w / 2), (half + d, f + w / 2), (half, f + w / 2)]
            rect = MB.rot2d(MB.rot2d(rect, 90.0 * side), deg)
            P.extrude(rect, "xy", z0, z1, mat)


def _corner_posts(P, half, deg, z0, z1, *, w=0.34, d=0.13, mat="M_Trim"):
    """A post on each corner of a rotated volume, so the eye can trace which way it is turned."""
    rect = [(half - w, half - w), (half + d, half - w), (half + d, half + d), (half - w, half + d)]
    for side in range(4):
        P.extrude(MB.rot2d(MB.rot2d(rect, 90.0 * side), deg), "xy", z0, z1, mat)


# ----------------------------------------------------------------------------------- v1
def _v1():
    P = K.Piece("content3", "v1", "T")
    P.notes.append("17.0 m tall, so it is the only piece that fits A2 and nothing else.")
    _base_hall(P, layout="a", side_light_f=0.62,
               side_windows=[(c, 1.50, 1.15, 3.25) for c in (-2.6, 0.0, 2.6)],
               back_windows=[(sx * 4.00, 1.60, 1.15, 3.25) for sx in (-1, 1)])

    # cornice, then two stacked closed volumes with horizontal glazing bands
    P.box((-HX - 0.22, -HY - 0.22, BASE_TOP), (HX + 0.22, HY + 0.22, BASE_TOP + 0.28), "M_Trim")
    V1H, V2H = 4.00, 3.30
    P.box((-V1H, -V1H, BASE_TOP + 0.20), (V1H, V1H, 10.60), "M_Wall")
    P.box((-V1H - 0.20, -V1H - 0.20, 10.60), (V1H + 0.20, V1H + 0.20, 10.92), "M_Trim")
    P.box((-V2H, -V2H, 10.84), (V2H, V2H, 16.30), "M_Wall")

    for k in range(4):
        z = BASE_TOP + 0.75 + k * 1.22
        P.perimeter_band(V1H, V1H, z, z + 0.62, proud=0.03, depth=0.10, mat="M_Glass")
        P.perimeter_band(V1H, V1H, z - 0.09, z, proud=0.07, depth=0.14, mat="M_Trim")
        P.perimeter_band(V1H, V1H, z + 0.62, z + 0.71, proud=0.07, depth=0.14, mat="M_Trim")
    for k in range(3):
        z = 11.45 + k * 1.42
        P.perimeter_band(V2H, V2H, z, z + 0.72, proud=0.03, depth=0.10, mat="M_Glass")
        P.perimeter_band(V2H, V2H, z - 0.09, z, proud=0.07, depth=0.14, mat="M_Trim")

    P.perimeter_band(V1H, V1H, BASE_TOP + 0.34, BASE_TOP + 0.62, proud=0.08, depth=0.16,
                     mat="M_BrandAccent")
    P.box((-V2H - 0.30, -V2H - 0.30, 16.30), (V2H + 0.30, V2H + 0.30, 16.62), "M_Roof",
          faces={"+z": "M_Trim"})
    P.box((-2.00, -2.00, 16.62), (2.00, 2.00, 17.00), "M_Trim")
    P.standard_markers(roof_top=17.00, front_y=-HY)
    return P


# ----------------------------------------------------------------------------------- v2
def _v2():
    P = K.Piece("content3", "v2", "T")
    P.notes.append("Same base hall and socket set as v1; the stacked volumes twist 20 and 47 "
                   "degrees, fins replace the bands, and a stepped crown takes it to 18.6 m.")
    _base_hall(P, layout="b", side_light_f=0.50,
               side_windows=[(c, 2.20, 1.25, 3.60) for c in (-2.4, 2.4)],
               back_windows=[(sx * 4.00, 1.80, 1.25, 3.60) for sx in (-1, 1)])

    # The twist only reads if each volume's corners hang over the slab it stands on. In 003 the
    # angles were 15 / 30 and the volumes were small enough to stay inside the plan below them,
    # so from the front three-quarter view the tower looked like three straight boxes. Now each
    # volume is wider, the angles are bigger (20, then 47 — 27 of relative twist), the slab
    # under each one keeps the angle of the volume BELOW it, and corner posts draw the edges.
    D1, D2 = 20.0, 47.0
    V1H, V2H = 4.30, 3.60
    P.box((-HX - 0.22, -HY - 0.22, BASE_TOP), (HX + 0.22, HY + 0.22, BASE_TOP + 0.28), "M_Trim")
    P.extrude(MB.square2d(V1H, deg=D1), "xy", BASE_TOP + 0.20, 11.00, "M_Wall", cap_mat="M_Roof")
    P.extrude(MB.square2d(V1H + 0.26, deg=D1), "xy", 11.00, 11.34, "M_Trim")
    P.extrude(MB.square2d(V2H, deg=D2), "xy", 11.26, 17.00, "M_Wall", cap_mat="M_Roof")

    _fin_ring(P, V1H, D1, BASE_TOP + 0.80, 10.80, count=5, w=0.18, d=0.28)
    _fin_ring(P, V2H, D2, 11.60, 16.80, count=4, w=0.18, d=0.28)
    _corner_posts(P, V1H, D1, BASE_TOP + 0.20, 11.00)
    _corner_posts(P, V2H, D2, 11.26, 17.00)
    for (h, deg, z0, z1) in ((V1H, D1, BASE_TOP + 0.34, BASE_TOP + 0.70),
                             (V2H, D2, 11.34, 11.62)):
        P.extrude(MB.square2d(h + 0.16, deg=deg), "xy", z0, z1, "M_BrandAccent")
    for (h, deg, z0, z1) in ((V1H, D1, 4.0, 10.4), (V2H, D2, 11.8, 16.6)):
        P.extrude(MB.square2d(h + 0.025, deg=deg), "xy", z0 + 2.0, z1 - 2.0, "M_Glass")

    P.extrude(MB.square2d(V2H + 0.30, deg=D2), "xy", 17.00, 17.34, "M_Roof")
    P.extrude(MB.square2d(2.10, deg=0.0), "xy", 17.34, 18.10, "M_Trim")
    P.sb.disc((0.0, 0.0), 0.18, "xy", 18.10, 18.60, "M_Metal", segs=10)
    P.standard_markers(roof_top=18.60, front_y=-HY)
    return P
